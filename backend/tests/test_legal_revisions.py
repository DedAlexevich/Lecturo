from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, update

from app.api import legal as legal_api
from app.core.db import SessionLocal
from app.models import LegalNotice, LegalRevision, NoticeChannel, User
from app.services import legal_notices
from app.services.consents import apply_effective_revisions, require_ai_transfer_consent
from app.services.legal import NOTICE_DAYS_AFTER, read_document

AI_TRANSFER = read_document("ai-transfer")
BEFORE = AI_TRANSFER.effective_date - timedelta(days=1)
AFTER = AI_TRANSFER.effective_date
PREVIOUS = AI_TRANSFER.revision_date - timedelta(days=1)


@pytest.fixture
async def people() -> AsyncIterator[dict[str, User]]:
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        await session.execute(delete(LegalRevision))
        users = {
            "previous": User(
                display_name="Старая редакция",
                email=f"previous-{now.timestamp()}@lecturo.test",
                email_verified_at=now,
                telegram_chat_id=101,
                ai_transfer_accepted_at=now,
                ai_transfer_revision=PREVIOUS,
            ),
            "current": User(
                display_name="Новая редакция",
                email=f"current-{now.timestamp()}@lecturo.test",
                email_verified_at=now,
                ai_transfer_accepted_at=now,
                ai_transfer_revision=AI_TRANSFER.revision_date,
            ),
            "revoked": User(
                display_name="Без согласия",
                email=f"revoked-{now.timestamp()}@lecturo.test",
                email_verified_at=now,
                telegram_chat_id=102,
            ),
            "unverified": User(
                display_name="Почта не подтверждена",
                email=f"unverified-{now.timestamp()}@lecturo.test",
                ai_transfer_accepted_at=now,
                ai_transfer_revision=PREVIOUS,
            ),
        }
        session.add_all(users.values())
        await session.commit()
        yield users
        for user in users.values():
            await session.delete(user)
        await session.execute(delete(LegalRevision))
        await session.commit()


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    sent: list[tuple[str, str, str]] = []

    async def record(to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    monkeypatch.setattr(legal_notices, "deliver_mail", record)
    return sent


async def stored(user: User) -> User:
    async with SessionLocal() as session:
        return await session.get(User, user.id)


async def notices(users: dict[str, User]) -> list[LegalNotice]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(LegalNotice).where(LegalNotice.user_id.in_([user.id for user in users.values()]))
        )
        return list(rows)


def test_ai_transfer_revision_has_effective_date_and_changes():
    assert AI_TRANSFER.effective_date >= AI_TRANSFER.revision_date + timedelta(days=7)
    assert AI_TRANSFER.changes
    terms = read_document("terms")
    assert terms.effective_date == terms.revision_date
    assert terms.changes is None


async def test_previous_revision_applies_until_effective_date(people):
    async with SessionLocal() as session:
        await apply_effective_revisions(session, BEFORE)
        await session.commit()
    previous = await stored(people["previous"])
    assert previous.ai_transfer_revision == PREVIOUS
    require_ai_transfer_consent(previous)


async def test_new_revision_accepted_by_default_from_effective_date(people):
    async with SessionLocal() as session:
        await apply_effective_revisions(session, AFTER)
        await session.commit()
    previous = await stored(people["previous"])
    assert previous.ai_transfer_revision == AI_TRANSFER.revision_date
    require_ai_transfer_consent(previous)


async def test_revoked_consent_is_not_accepted_by_default(people):
    async with SessionLocal() as session:
        await apply_effective_revisions(session, AFTER)
        await session.commit()
    revoked = await stored(people["revoked"])
    assert revoked.ai_transfer_accepted_at is None
    assert revoked.ai_transfer_revision is None
    with pytest.raises(HTTPException) as error:
        require_ai_transfer_consent(revoked)
    assert error.value.status_code == 403


async def test_notice_is_sent_once_by_mail_and_bot(people, mails):
    for _ in range(2):
        async with SessionLocal() as session:
            await legal_notices.announce_revisions(session, BEFORE)
            await legal_notices.send_email_notices(session)

    rows = await notices(people)
    assert sorted((row.user_id, row.channel) for row in rows) == sorted(
        [
            (people["previous"].id, NoticeChannel.email),
            (people["previous"].id, NoticeChannel.telegram),
        ]
    )
    assert all(row.slug == "ai-transfer" for row in rows)
    email = next(row for row in rows if row.channel == NoticeChannel.email)
    assert email.sent_at is not None
    telegram = next(row for row in rows if row.channel == NoticeChannel.telegram)
    assert telegram.sent_at is None
    assert telegram.link.endswith("/legal/ai-transfer")
    ours = [mail for mail in mails if mail[0] == people["previous"].email]
    assert len(ours) == 1
    _, subject, body = ours[0]
    assert AI_TRANSFER.title in subject
    assert AI_TRANSFER.changes in body
    assert AI_TRANSFER.effective_date.strftime("%d.%m.%Y") in body
    assert "/legal/ai-transfer" in body
    assert "отзовите согласие" in body
    assert "удалите аккаунт" in body


async def test_notice_is_not_sent_after_effective_date(people, mails):
    async with SessionLocal() as session:
        assert await legal_notices.announce_revisions(session, AFTER + timedelta(days=1)) == 0
    assert await notices(people) == []


async def test_updates_show_revision_until_banner_ends(client, monkeypatch):
    monkeypatch.setattr(legal_api, "today", lambda: AFTER + timedelta(days=NOTICE_DAYS_AFTER))
    response = await client.get("/api/v1/legal/updates")
    assert response.status_code == 200
    assert response.json() == [
        {
            "slug": "ai-transfer",
            "title": AI_TRANSFER.title,
            "revision_date": AI_TRANSFER.revision_date.isoformat(),
            "effective_date": AI_TRANSFER.effective_date.isoformat(),
            "changes": AI_TRANSFER.changes,
        }
    ]
    monkeypatch.setattr(legal_api, "today", lambda: AFTER + timedelta(days=NOTICE_DAYS_AFTER + 1))
    assert (await client.get("/api/v1/legal/updates")).json() == []


async def test_failed_email_is_retried_later_and_limited(people, monkeypatch):
    attempts: list[str] = []

    async def broken(to: str, subject: str, body: str) -> None:
        attempts.append(to)
        raise OSError("smtp down")

    monkeypatch.setattr(legal_notices, "deliver_mail", broken)
    async with SessionLocal() as session:
        await legal_notices.announce_revisions(session, BEFORE)
        assert await legal_notices.send_email_notices(session) == 0
        assert await legal_notices.send_email_notices(session) == 0
    ours = [to for to in attempts if to == people["previous"].email]
    assert ours == [people["previous"].email]
    email = next(row for row in await notices(people) if row.channel == NoticeChannel.email)
    assert email.sent_at is None
    assert email.attempts == 1

    for _ in range(legal_notices.MAX_ATTEMPTS):
        async with SessionLocal() as session:
            await session.execute(
                update(LegalNotice)
                .where(LegalNotice.id == email.id)
                .values(attempted_at=datetime(2000, 1, 1, tzinfo=UTC))
            )
            await session.commit()
            await legal_notices.send_email_notices(session)
    ours = [to for to in attempts if to == people["previous"].email]
    assert len(ours) == legal_notices.MAX_ATTEMPTS
    email = next(row for row in await notices(people) if row.channel == NoticeChannel.email)
    assert email.sent_at is None
    assert email.attempts == legal_notices.MAX_ATTEMPTS


async def test_email_is_not_sent_after_verification_is_lost(people, mails):
    async with SessionLocal() as session:
        await legal_notices.announce_revisions(session, BEFORE)
        await session.execute(
            update(User).where(User.id == people["previous"].id).values(email_verified_at=None)
        )
        await session.commit()
        await legal_notices.send_email_notices(session)
    assert [mail for mail in mails if mail[0] == people["previous"].email] == []
    email = next(row for row in await notices(people) if row.channel == NoticeChannel.email)
    assert email.sent_at is None
    assert email.attempts == legal_notices.MAX_ATTEMPTS
