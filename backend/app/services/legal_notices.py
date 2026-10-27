from datetime import date

from sqlalchemy import ColumnElement, func, literal, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import LegalNotice, LegalRevision, NoticeChannel, User
from app.schemas.legal import LegalDocOut
from app.services.consents import ACCEPTANCES, apply_effective_revisions
from app.services.legal import announced_documents, today
from app.services.mail import send_mail

EMAIL_BATCH = 100
CHANNELS: dict[NoticeChannel, ColumnElement[bool]] = {
    NoticeChannel.email: User.email.is_not(None) & User.email_verified_at.is_not(None),
    NoticeChannel.telegram: User.telegram_chat_id.is_not(None),
}


def notice_subject(doc: LegalDocOut) -> str:
    return f"Новая редакция документа «{doc.title}»"


def notice_text(doc: LegalDocOut, link: str, account_link: str) -> str:
    effective = doc.effective_date.strftime("%d.%m.%Y")
    return (
        f"Мы обновили документ «{doc.title}». Что изменилось: {doc.changes}\n\n"
        f"Новая редакция: {link}\n"
        f"Она вступает в силу {effective}. С этой даты она действует для вас "
        "без отдельного подтверждения.\n\n"
        "Если вы не согласны, до этой даты отзовите согласие в личном кабинете "
        f"({account_link}) или удалите аккаунт."
    )


def audience(slug: str, revision: date) -> ColumnElement[bool]:
    if slug not in ACCEPTANCES:
        return true()
    accepted_at, accepted_revision = ACCEPTANCES[slug]
    return (
        accepted_at.is_not(None) & accepted_revision.is_not(None) & (accepted_revision < revision)
    )


async def announce(session: AsyncSession, doc: LegalDocOut) -> bool:
    claimed = await session.scalar(
        insert(LegalRevision)
        .values(
            slug=doc.slug,
            revision_date=doc.revision_date,
            effective_date=doc.effective_date,
        )
        .on_conflict_do_nothing()
        .returning(LegalRevision.slug)
    )
    if claimed is None:
        return False
    public_url = get_settings().public_url.rstrip("/")
    link = f"{public_url}/legal/{doc.slug}"
    text = notice_text(doc, link, f"{public_url}/account")
    for channel, reachable in CHANNELS.items():
        await session.execute(
            insert(LegalNotice)
            .from_select(
                ["user_id", "slug", "revision_date", "channel", "subject", "text", "link"],
                select(
                    User.id,
                    literal(doc.slug),
                    literal(doc.revision_date),
                    literal(channel, LegalNotice.channel.type),
                    literal(notice_subject(doc)),
                    literal(text),
                    literal(link),
                ).where(reachable, audience(doc.slug, doc.revision_date)),
            )
            .on_conflict_do_nothing()
        )
    return True


async def announce_revisions(session: AsyncSession, day: date) -> int:
    announced = 0
    for doc in announced_documents():
        if day <= doc.effective_date and await announce(session, doc):
            announced += 1
    await session.commit()
    return announced


async def send_email_notices(session: AsyncSession) -> int:
    sent = 0
    while True:
        pending = (
            select(LegalNotice.id)
            .where(LegalNotice.channel == NoticeChannel.email, LegalNotice.sent_at.is_(None))
            .order_by(LegalNotice.created_at)
            .limit(EMAIL_BATCH)
            .with_for_update(skip_locked=True)
        )
        claimed = (
            await session.execute(
                update(LegalNotice)
                .where(LegalNotice.id.in_(pending.scalar_subquery()))
                .values(sent_at=func.now())
                .returning(LegalNotice.user_id, LegalNotice.subject, LegalNotice.text)
            )
        ).all()
        await session.commit()
        if not claimed:
            return sent
        emails = dict(
            (
                await session.execute(
                    select(User.id, User.email).where(User.id.in_([row.user_id for row in claimed]))
                )
            ).all()
        )
        for row in claimed:
            if emails.get(row.user_id):
                await send_mail(emails[row.user_id], row.subject, row.text)
                sent += 1


async def process_legal_revisions(ctx: dict) -> int:
    day = today()
    async with SessionLocal() as session:
        await apply_effective_revisions(session, day)
        await announce_revisions(session, day)
        return await send_email_notices(session)
