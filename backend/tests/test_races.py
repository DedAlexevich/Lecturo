import asyncio

from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models import (
    HourPackage,
    Lecture,
    LectureStatus,
    PaymentStatus,
    SourceType,
    UsageEntry,
    User,
)
from app.services import quota, yookassa
from tests.test_quota import SETTINGS, WEEK_START, prepare
from tests.test_yookassa_webhook import SETTINGS as YOOKASSA_SETTINGS
from tests.test_yookassa_webhook import FakeYooKassa, load_payment, make_payment, packages_of

NOW = WEEK_START
HOUR = 3600


async def new_lecture(user, seconds: float | None = None, status=None) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Лекция",
            source_type=SourceType.upload,
            duration_sec=seconds,
            status=status or LectureStatus.queued,
        )
        session.add(lecture)
        await session.commit()
        return lecture


async def used_seconds(user) -> int:
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.coalesce(func.sum(UsageEntry.seconds), 0)).where(
                UsageEntry.user_id == user.id
            )
        )


async def statuses(lectures) -> list[LectureStatus]:
    async with SessionLocal() as session:
        return [(await session.get(Lecture, lecture.id)).status for lecture in lectures]


async def test_parallel_webhooks_grant_once(user, race, monkeypatch):
    apply_succeeded = yookassa.apply_succeeded

    async def slow_apply(*args):
        await asyncio.sleep(0.1)
        await apply_succeeded(*args)

    monkeypatch.setattr(yookassa, "apply_succeeded", slow_apply)
    payment = await make_payment(user, "hours_5")
    fake = FakeYooKassa()
    fake.set_remote(payment, "succeeded")

    async def notify(session):
        return await yookassa.process_notification(
            session, fake.client(), payment.yookassa_id, YOOKASSA_SETTINGS
        )

    results = await race(notify, notify)

    assert not [result for result in results if isinstance(result, Exception)]
    [package] = await packages_of(user)
    assert package.seconds_total == 5 * HOUR
    assert (await load_payment(payment)).status == PaymentStatus.succeeded


async def test_parallel_charges_of_one_lecture_count_once(user, race):
    await prepare(user)
    lecture = await new_lecture(user)

    async def charge(session):
        charged = await quota.charge_lecture(
            session, user.id, lecture.id, 40 * 60, now=NOW, settings=SETTINGS
        )
        await session.commit()
        return charged

    assert await race(charge, charge) == [True, True]
    assert await used_seconds(user) == 40 * 60


async def test_parallel_charges_do_not_overdraw_quota(user, race):
    [package_id] = await prepare(user, packages=[HOUR])
    lectures = [await new_lecture(user), await new_lecture(user)]

    def charge(lecture):
        async def run(session):
            charged = await quota.charge_lecture(
                session, user.id, lecture.id, 1.5 * HOUR, now=NOW, settings=SETTINGS
            )
            await session.commit()
            return charged

        return run

    results = await race(*(charge(lecture) for lecture in lectures))

    assert sorted(results) == [False, True]
    assert await used_seconds(user) == 1.5 * HOUR
    async with SessionLocal() as session:
        assert (await session.get(HourPackage, package_id)).seconds_left == HOUR // 2


def plan(user, lectures):
    async def run(session):
        db_user = await session.get(User, user.id)
        planned = await quota.plan_queue(
            session, db_user, [lecture.id for lecture in lectures], now=NOW, settings=SETTINGS
        )
        await session.commit()
        return planned

    return run


async def test_parallel_plans_of_same_lectures_queue_once(user, race):
    await prepare(user)
    lectures = [
        await new_lecture(user, 20 * 60, LectureStatus.waiting_quota),
        await new_lecture(user, 30 * 60, LectureStatus.waiting_quota),
    ]

    results = await race(plan(user, lectures), plan(user, lectures))

    assert sum(isinstance(result, quota.LectureNotWaiting) for result in results) == 1
    assert await statuses(lectures) == [LectureStatus.queued, LectureStatus.queued]
    assert await used_seconds(user) == 50 * 60


async def test_parallel_plans_do_not_exceed_quota(user, race):
    await prepare(user)
    first = await new_lecture(user, 40 * 60, LectureStatus.waiting_quota)
    second = await new_lecture(user, 40 * 60, LectureStatus.waiting_quota)

    results = await race(plan(user, [first]), plan(user, [second]))

    assert sum(isinstance(result, quota.PlanExceedsQuota) for result in results) == 1
    assert sorted(await statuses([first, second])) == sorted(
        [LectureStatus.queued, LectureStatus.waiting_quota]
    )
    assert await used_seconds(user) == 40 * 60
