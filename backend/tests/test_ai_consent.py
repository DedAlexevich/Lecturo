import pytest
from sqlalchemy import func, select, update

from app.api import lectures as lectures_api
from app.api import local_results as local_results_api
from app.core.db import SessionLocal
from app.models import (
    Lecture,
    LectureStatus,
    ProcessingStep,
    SourceType,
    StepName,
    StepStatus,
    TranscriptSegment,
    User,
)
from app.pipeline import stages, summarize, tasks
from app.services import consent


async def revoke_consent(user: User) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(ai_transfer_accepted_at=None)
        )
        await session.commit()


async def create_link_lecture(user: User) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Матанализ",
            source_type=SourceType.link,
            duration_sec=2.0,
            audio_path="missing.opus",
        )
        session.add(lecture)
        await session.commit()
        return lecture


async def noop_download(session, lecture, report) -> None:
    return None


async def report(progress: float) -> None:
    return None


async def test_transcribe_requires_consent(user):
    await revoke_consent(user)
    lecture = await create_link_lecture(user)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        with pytest.raises(stages.ConsentMissing):
            await stages.transcribe(session, stored, report)


async def test_summarize_requires_consent(user):
    await revoke_consent(user)
    lecture = await create_link_lecture(user)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        with pytest.raises(stages.ConsentMissing):
            await summarize.summarize(session, stored, report)


async def test_pipeline_without_consent_fails_before_server_processing(user, monkeypatch):
    monkeypatch.setitem(tasks.HANDLERS, StepName.download, noop_download)
    await revoke_consent(user)
    lecture = await create_link_lecture(user)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed

    async with SessionLocal() as session:
        step = await session.scalar(
            select(ProcessingStep).where(
                ProcessingStep.lecture_id == lecture.id, ProcessingStep.step == StepName.transcribe
            )
        )
        assert step.status == StepStatus.failed
        assert step.error == stages.AI_TRANSFER_REQUIRED
        segments = await session.scalar(
            select(func.count())
            .select_from(TranscriptSegment)
            .where(TranscriptSegment.lecture_id == lecture.id)
        )
        assert segments == 0


async def lecture_count(user: User) -> int:
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(Lecture).where(Lecture.owner_id == user.id)
        )


@pytest.fixture
def no_server_work(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("обработка без согласия")

    monkeypatch.setattr(lectures_api, "inspect_link", forbidden)
    monkeypatch.setattr(lectures_api, "enqueue_lecture", forbidden)
    monkeypatch.setattr(local_results_api, "enqueue_lecture", forbidden)
    monkeypatch.setattr(local_results_api, "enforce_rate_limit", forbidden)


async def test_add_link_requires_consent(client, user, auth_headers, no_server_work):
    await revoke_consent(user)
    response = await client.post(
        "/api/v1/lectures/link",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == consent.AI_TRANSFER_REQUIRED
    assert await lecture_count(user) == 0


async def test_upload_requires_consent(client, user, auth_headers):
    await revoke_consent(user)
    request = {
        "Type": "pre-create",
        "Event": {
            "Upload": {"Size": 1000, "MetaData": {"filename": "a.mp4"}},
            "HTTPRequest": {"Header": {name: [value] for name, value in auth_headers.items()}},
        },
    }
    response = await client.post("/api/v1/uploads/hooks", json=request)

    body = response.json()
    assert body["RejectUpload"] is True
    assert body["HTTPResponse"]["StatusCode"] == 403
    assert "ChangeFileInfo" not in body


async def test_local_result_requires_consent(client, user, auth_headers, no_server_work):
    await revoke_consent(user)
    response = await client.post(
        "/api/v1/local-results",
        json={
            "title": "Матанализ",
            "duration_sec": 60.0,
            "model": "whisper-small",
            "segments": [{"start": 0.0, "end": 60.0, "text": "слово " * 40}],
        },
        headers=auth_headers,
    )

    assert response.status_code == 403
    assert response.json()["detail"] == consent.AI_TRANSFER_REQUIRED
    assert await lecture_count(user) == 0
