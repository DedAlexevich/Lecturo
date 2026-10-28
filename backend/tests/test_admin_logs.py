import json
import os
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.api.admin_logs import stream_events
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import create_access_token
from app.models import (
    AdminAction,
    AdminAuditEntry,
    BusinessEvent,
    BusinessEventKind,
    Lecture,
    LectureStatus,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    User,
)
from app.services import admin_events, admin_logs, business_events
from app.services.admin_logs import LogLevel, LogService, mask_text
from app.services.auth import hash_password


def headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}


@pytest.fixture
async def admin() -> AsyncIterator[User]:
    async with SessionLocal() as session:
        user = User(
            email=f"logs-{uuid.uuid4().hex[:10]}@example.org", display_name="Админ", is_admin=True
        )
        session.add(user)
        await session.commit()
    yield user
    async with SessionLocal() as session:
        await session.execute(delete(AdminAuditEntry).where(AdminAuditEntry.actor_id == user.id))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(get_settings(), "log_dir", tmp_path)
    return tmp_path


API_LOG = (
    "2026-10-28 10:00:00,001 INFO api app.main: запуск\n"
    "2026-10-28 10:00:01,001 WARNING api app.auth: подозрительный вход\n"
    "2026-10-28 10:00:02,001 ERROR api app.pipeline: шаг упал\n"
    "Traceback (most recent call last):\n"
    '  File "x.py", line 1\n'
    "2026-10-28 10:00:03,001 INFO api app.main: конец\n"
)


@pytest.mark.parametrize(
    ("raw", "hidden"),
    [
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("login password=hunter2secret ok", "hunter2secret"),
        ('{"password": "p@ss w0rd", "name": "x"}', "p@ss w0rd"),
        ("GET /api/v1/share?token=abc123def456&x=1 HTTP/1.1", "abc123def456"),
        ("GET /media/x.mp4?signature=zzz999&share=qqq888", "zzz999"),
        ("GET /auth/vk?code=oauthcode777&state=st888", "oauthcode777"),
        ("postgresql://lecturo:supersecretpw@db:5432/lecturo", "supersecretpw"),
        ('"Authorization":["Bearer eyJhbGciOi.eyJzdWIiOiIx.c2lnbmF0dXJl"]', "eyJzdWIiOiIx"),
        ("bot token 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw9 failed", "AAHdqTcvCH1vGWJ"),
        ("jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4 end", "SflKxwRJSMeKKF2QT4"),
        ("key sk-abcdefghijklmnopqrstuvwxyz used", "abcdefghijklmnopqrstuvwxyz"),
        ("secret_key=" + "a1" * 30, "a1a1a1a1a1"),
        ('"Cookie":["session=abcd1234efgh; theme=dark"]', "abcd1234efgh"),
        ("api_key: 'AQVNabcdef12345'", "AQVNabcdef12345"),
    ],
)
def test_mask_hides_secrets(raw: str, hidden: str):
    masked = mask_text(raw)

    assert hidden not in masked
    assert "***" in masked


def test_mask_keeps_regular_text():
    line = "2026-10-28 10:00:00,001 INFO api app.main: лекция 4f1c2d3e-aaaa-bbbb-cccc-123456789ab0"

    assert mask_text(line) == line


def test_mask_shows_email_partially():
    masked = mask_text("вход i.ivanov@example.org не удался")

    assert "i***@e***.org" in masked
    assert "ivanov" not in masked


def test_level_detection_covers_all_formats():
    assert admin_logs.detect_level("2026-10-28 10:00:00,001 ERROR api app: x") == LogLevel.error
    assert admin_logs.detect_level('{"level":"warn","ts":1}') == LogLevel.warning
    assert admin_logs.detect_level("time=2026 level=INFO msg=ok") == LogLevel.info
    assert admin_logs.detect_level("Traceback (most recent call last):") is None


async def test_tail_filters_by_level_and_text(log_dir: Path):
    (log_dir / "api.log").write_text(API_LOG)

    everything = await admin_logs.read_tail(LogService.api, 100, None, "")
    errors = await admin_logs.read_tail(LogService.api, 100, LogLevel.error, "")
    found = await admin_logs.read_tail(LogService.api, 100, None, "ПОДОЗРИТЕЛЬНЫЙ")
    last = await admin_logs.read_tail(LogService.api, 2, None, "")

    assert len(everything.lines) == 6
    assert [line.text.split(": ")[-1] for line in errors.lines[:1]] == ["шаг упал"]
    assert errors.lines[1].text == "Traceback (most recent call last):"
    assert len(errors.lines) == 3
    assert len(found.lines) == 1
    assert [line.level for line in last.lines] == [LogLevel.error, LogLevel.info]


async def test_tail_masks_secrets_before_search(log_dir: Path):
    (log_dir / "api.log").write_text("2026-10-28 10:00:00,001 INFO api x: password=topsecret1\n")

    visible = await admin_logs.read_tail(LogService.api, 10, None, "***")
    probing = await admin_logs.read_tail(LogService.api, 10, None, "topsecret1")

    assert len(visible.lines) == 1
    assert probing.lines == []


async def test_tail_refuses_symlink_and_missing_file(log_dir: Path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.log"
    outside.write_text("do not read\n")
    os.symlink(outside, log_dir / "worker.log")

    with pytest.raises(admin_logs.LogUnavailable):
        await admin_logs.read_tail(LogService.worker, 10, None, "")
    with pytest.raises(admin_logs.LogUnavailable):
        await admin_logs.read_tail(LogService.bot, 10, None, "")


async def test_log_endpoint_rejects_unknown_service_and_traversal(
    client: AsyncClient, admin: User, log_dir: Path
):
    for service in ("..%2F..%2Fetc%2Fpasswd", "passwd", "api.log", "..", "%2e%2e"):
        response = await client.get(f"/api/v1/admin/logs/{service}", headers=headers(admin))
        assert response.status_code in (404, 422), service


async def test_log_endpoint_returns_masked_lines(client: AsyncClient, admin: User, log_dir: Path):
    (log_dir / "api.log").write_text(
        "2026-10-28 10:00:00,001 ERROR api x: GET /a?token=leakedvalue1 user a.b@example.org\n"
    )

    response = await client.get(
        "/api/v1/admin/logs/api", params={"level": "error", "lines": 10}, headers=headers(admin)
    )

    body = response.json()
    assert response.status_code == 200
    assert body["lines"][0]["level"] == "error"
    assert "leakedvalue1" not in body["lines"][0]["text"]
    assert "a.b@example.org" not in body["lines"][0]["text"]


async def test_log_endpoint_is_404_for_regular_user(
    client: AsyncClient, user: User, auth_headers: dict, log_dir: Path
):
    (log_dir / "api.log").write_text(API_LOG)

    response = await client.get("/api/v1/admin/logs/api", headers=auth_headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_log_endpoint_missing_file_is_404(client: AsyncClient, admin: User, log_dir: Path):
    response = await client.get("/api/v1/admin/logs/caddy", headers=headers(admin))

    assert response.status_code == 404
    assert response.json()["detail"] == admin_logs.LOG_UNAVAILABLE


async def test_follow_yields_only_new_masked_lines_and_handles_rotation(log_dir: Path):
    path = log_dir / "api.log"
    path.write_text("2026-10-28 10:00:00,001 INFO api x: старая\n")
    pauses: list[float] = []

    async def no_sleep(seconds: float) -> None:
        pauses.append(seconds)

    stream = admin_logs.follow(LogService.api, None, "", None, sleep=no_sleep)

    assert await anext(stream) is None
    with path.open("a") as handle:
        handle.write("2026-10-28 10:00:01,001 INFO api x: новая token=abcsecret99\n")
    chunk = await anext(stream)
    assert [line.text.split(": ", 1)[1] for line in chunk.lines] == ["новая token=***"]
    path.write_text("2026-10-28 10:00:02,001 ERROR api x: после ротации\n")
    rotated = await anext(stream)
    assert rotated.restarted is True
    assert rotated.lines[0].level == LogLevel.error
    await stream.aclose()
    assert pauses


async def test_follow_level_filter_inherits_for_traceback(log_dir: Path):
    path = log_dir / "api.log"
    path.write_text("")

    async def no_sleep(seconds: float) -> None:
        return None

    stream = admin_logs.follow(LogService.api, LogLevel.error, "", None, sleep=no_sleep)
    assert await anext(stream) is None
    path.write_text(API_LOG)
    chunk = await anext(stream)
    await stream.aclose()

    assert len(chunk.lines) == 3


class FakeRequest:
    def __init__(self, disconnect_after: int = 1000) -> None:
        self.calls = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > self.disconnect_after


async def test_stream_limit_of_concurrent_streams(log_dir: Path, monkeypatch: pytest.MonkeyPatch):
    (log_dir / "api.log").write_text(API_LOG)
    monkeypatch.setattr(get_settings(), "log_stream_limit", 1)
    monkeypatch.setattr(admin_logs, "STREAM_POLL_SECONDS", 0.01)
    first = stream_events(FakeRequest(), LogService.api, None, "", 0)
    second = stream_events(FakeRequest(), LogService.api, None, "", 0)

    opened = await anext(first)
    refused = [event async for event in second]
    await first.aclose()
    after_close = stream_events(FakeRequest(disconnect_after=0), LogService.api, None, "", 0)
    reopened = [event async for event in after_close]

    assert opened.startswith("id: ")
    detail = json.dumps({"detail": admin_logs.TOO_MANY_STREAMS}, ensure_ascii=False)
    assert refused == [f"event: error\ndata: {detail}\n\n"]
    assert reopened == []
    assert admin_logs.stream_slots.active == 0


async def test_stream_stops_when_client_disconnects(log_dir: Path, monkeypatch: pytest.MonkeyPatch):
    (log_dir / "api.log").write_text("")
    monkeypatch.setattr(admin_logs, "STREAM_POLL_SECONDS", 0.01)

    events = [event async for event in stream_events(FakeRequest(2), LogService.api, None, "", 0)]

    assert events == []
    assert admin_logs.stream_slots.active == 0


async def test_stream_endpoint_is_404_for_regular_user(
    client: AsyncClient, user: User, auth_headers: dict, log_dir: Path
):
    (log_dir / "api.log").write_text(API_LOG)

    response = await client.get("/api/v1/admin/logs/api/stream", headers=auth_headers)

    assert response.status_code == 404


@pytest.fixture
async def failed_lecture() -> AsyncIterator[tuple[User, Lecture]]:
    async with SessionLocal() as session:
        owner = User(email=f"owner-{uuid.uuid4().hex[:10]}@example.org", display_name="Автор")
        session.add(owner)
        await session.flush()
        lecture = Lecture(
            owner_id=owner.id,
            title="Упавшая лекция",
            source_type=SourceType.upload,
            status=LectureStatus.failed,
        )
        session.add(lecture)
        await session.flush()
        session.add(
            ProcessingStep(
                lecture_id=lecture.id,
                step=StepName.transcribe,
                status=StepStatus.failed,
                error="STT отказал: api_key=sk-leakedleakedleaked12345",
                attempts=3,
            )
        )
        await session.commit()
    yield owner, lecture
    async with SessionLocal() as session:
        await session.execute(
            delete(AdminAuditEntry).where(AdminAuditEntry.target_id == str(lecture.id))
        )
        await session.execute(delete(User).where(User.id == owner.id))
        await session.commit()


async def test_processing_errors_list_masks_error_text(
    client: AsyncClient, admin: User, failed_lecture: tuple[User, Lecture]
):
    owner, lecture = failed_lecture

    response = await client.get("/api/v1/admin/processing-errors", headers=headers(admin))

    items = [item for item in response.json()["items"] if item["lecture_id"] == str(lecture.id)]
    assert response.status_code == 200
    assert len(items) == 1
    assert items[0]["step"] == "transcribe"
    assert items[0]["user_label"] == owner.email
    assert items[0]["can_retry"] is True
    assert "leakedleaked" not in items[0]["error"]


async def test_admin_retry_requeues_failed_lecture_and_logs_it(
    client: AsyncClient,
    admin: User,
    failed_lecture: tuple[User, Lecture],
    monkeypatch: pytest.MonkeyPatch,
):
    _, lecture = failed_lecture
    queued: list[uuid.UUID] = []

    async def fake_enqueue(lecture_id: uuid.UUID) -> None:
        queued.append(lecture_id)

    monkeypatch.setattr(admin_events, "enqueue_lecture", fake_enqueue)

    response = await client.post(
        f"/api/v1/admin/processing-errors/{lecture.id}/retry", headers=headers(admin)
    )
    again = await client.post(
        f"/api/v1/admin/processing-errors/{lecture.id}/retry", headers=headers(admin)
    )

    async with SessionLocal() as session:
        status_now = await session.scalar(select(Lecture.status).where(Lecture.id == lecture.id))
        step = await session.scalar(
            select(ProcessingStep).where(ProcessingStep.lecture_id == lecture.id)
        )
        entries = list(
            await session.scalars(
                select(AdminAuditEntry).where(AdminAuditEntry.target_id == str(lecture.id))
            )
        )
    assert response.status_code == 202
    assert again.status_code == 409
    assert queued == [lecture.id]
    assert status_now == LectureStatus.queued
    assert step.status == StepStatus.pending
    assert step.error is None
    assert [entry.action for entry in entries] == [AdminAction.lecture_retried]


async def test_admin_retry_unknown_lecture_is_404(client: AsyncClient, admin: User):
    response = await client.post(
        f"/api/v1/admin/processing-errors/{uuid.uuid4()}/retry", headers=headers(admin)
    )

    assert response.status_code == 404


@pytest.fixture
async def clean_events() -> AsyncIterator[Callable[[uuid.UUID], None]]:
    marks: list[uuid.UUID] = []
    yield marks.append
    async with SessionLocal() as session:
        await session.execute(delete(BusinessEvent).where(BusinessEvent.user_id.in_(marks)))
        await session.commit()


async def test_business_events_are_listed_filtered_and_masked(
    client: AsyncClient, admin: User, clean_events
):
    subject = uuid.uuid4()
    clean_events(subject)
    await business_events.record_event(
        BusinessEventKind.payment_succeeded,
        user_id=subject,
        label="x@example.org",
        amount_kopecks=19900,
        reason="token=abc12345secret",
    )
    await business_events.record_event(BusinessEventKind.login, user_id=subject, provider="email")

    everything = await client.get(
        "/api/v1/admin/events", params={"user_id": str(subject)}, headers=headers(admin)
    )
    payments = await client.get(
        "/api/v1/admin/events",
        params={"user_id": str(subject), "kind": "payment_succeeded"},
        headers=headers(admin),
    )

    assert everything.json()["total"] == 2
    assert [item["kind"] for item in payments.json()["items"]] == ["payment_succeeded"]
    details = payments.json()["items"][0]["details"]
    assert details["amount_kopecks"] == "19900"
    assert "abc12345secret" not in details["reason"]


async def test_business_events_for_regular_user_are_404(
    client: AsyncClient, user: User, auth_headers: dict
):
    assert (await client.get("/api/v1/admin/events", headers=auth_headers)).status_code == 404


async def test_login_and_failed_login_are_recorded(
    client: AsyncClient, admin: User, reset_auth_rate_limits, clean_events
):
    async with SessionLocal() as session:
        user = User(
            email=f"event-{uuid.uuid4().hex[:8]}@example.org",
            password_hash=hash_password("правильный-пароль-1"),
            display_name="Вход",
        )
        session.add(user)
        await session.commit()
    clean_events(user.id)

    bad = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "неверный-пароль"}
    )
    good = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "правильный-пароль-1"}
    )

    async with SessionLocal() as session:
        kinds = list(
            await session.scalars(
                select(BusinessEvent.kind).where(
                    (BusinessEvent.user_id == user.id) | (BusinessEvent.kind == "login_failed")
                )
            )
        )
        failed = list(
            await session.scalars(
                select(BusinessEvent.user_label).where(BusinessEvent.kind == "login_failed")
            )
        )
        await session.execute(delete(BusinessEvent).where(BusinessEvent.kind == "login_failed"))
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()
    assert bad.status_code == 401
    assert good.status_code == 200
    assert "login" in kinds
    assert any(label.endswith("@e***.org") and user.email not in label for label in failed)
