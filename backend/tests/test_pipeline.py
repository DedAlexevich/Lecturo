import asyncio
import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api import lectures as lectures_api
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import (
    Chapter,
    Lecture,
    LectureStatus,
    SearchChunk,
    SourceType,
    StepName,
    StepStatus,
    Summary,
    TranscriptSegment,
)
from app.pipeline import media, tasks
from app.pipeline.stages import split_into_chunks


def generate_media(path: Path, *inputs: str) -> Path:
    args = ["ffmpeg", "-v", "error"]
    for source in inputs:
        args += ["-f", "lavfi", "-i", source]
    subprocess.run([*args, "-t", "2", "-shortest", str(path)], check=True)
    return path


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    return generate_media(
        tmp_path_factory.mktemp("media") / "sample.mkv",
        "testsrc=size=1920x1080:rate=10",
        "sine=frequency=440",
    )


@pytest.fixture(scope="session")
def sample_audio(tmp_path_factory) -> Path:
    return generate_media(tmp_path_factory.mktemp("media") / "sample.m4a", "sine=frequency=440")


@pytest.fixture(autouse=True)
def storage(monkeypatch, tmp_path) -> Path:
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path)
    return tmp_path


async def create_lecture(user, source: Path) -> Lecture:
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id, title="Матанализ", source_type=SourceType.upload, duration_sec=2.0
        )
        session.add(lecture)
        await session.flush()
        original = media.original_path(lecture.id)
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, original)
        lecture.audio_path = str(original)
        await session.commit()
        return lecture


def probe_streams(path: Path) -> list[dict]:
    output = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,height,channels",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
    ).stdout
    return json.loads(output)["streams"]


async def load(lecture_id) -> Lecture:
    async with SessionLocal() as session:
        return await session.scalar(
            select(Lecture).where(Lecture.id == lecture_id).options(selectinload(Lecture.steps))
        )


async def count(model, lecture_id) -> int:
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(model).where(model.lecture_id == lecture_id)
        )


def steps_by_name(lecture: Lecture) -> dict:
    return {step.step: step for step in lecture.steps}


async def test_lecture_passes_all_steps(user, sample_video):
    lecture = await create_lecture(user, sample_video)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    lecture = await load(lecture.id)
    assert lecture.status == LectureStatus.ready
    assert lecture.duration_sec
    steps = steps_by_name(lecture)
    assert set(steps) == {
        StepName.audio,
        StepName.video,
        StepName.transcribe,
        StepName.summarize,
        StepName.embed,
    }
    assert all(s.status == StepStatus.done and s.progress == 1.0 for s in steps.values())
    assert await count(TranscriptSegment, lecture.id) > 0
    assert await count(Chapter, lecture.id) == 1
    assert await count(Summary, lecture.id) == 1
    assert await count(SearchChunk, lecture.id) > 0


async def test_upload_gets_compressed_audio_and_video(
    user, sample_video, storage, client, auth_headers
):
    lecture = await create_lecture(user, sample_video)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    lecture = await load(lecture.id)
    audio = storage / "audio" / f"{lecture.id}.opus"
    video = storage / "videos" / f"{lecture.id}.mp4"
    assert lecture.audio_path == str(audio)
    assert lecture.video_path == str(video)
    assert not media.original_path(lecture.id).exists()
    assert list((storage / "videos").iterdir()) == [video]
    assert not list((storage / "tmp").iterdir())
    assert lecture.duration_sec == pytest.approx(2.0, abs=0.2)
    expected_expiry = datetime.now(UTC) + timedelta(days=get_settings().free_video_retention_days)
    assert abs(lecture.video_expires_at - expected_expiry) < timedelta(minutes=1)

    [audio_stream] = probe_streams(audio)
    assert audio_stream["codec_name"] == "opus"
    assert audio_stream["channels"] == 1

    streams = {stream["codec_type"]: stream for stream in probe_streams(video)}
    assert streams["video"]["codec_name"] == "h264"
    assert streams["video"]["height"] == 720
    assert streams["audio"]["codec_name"] == "aac"
    content = video.read_bytes()
    assert content.index(b"moov") < content.index(b"mdat")

    response = await client.get(f"/api/v1/lectures/{lecture.id}", headers=auth_headers)
    assert response.json()["video_url"] == f"/media/{lecture.id}.mp4"


async def test_odd_sized_video_is_transcoded(user, storage, tmp_path):
    odd = generate_media(tmp_path / "odd.mkv", "testsrc=size=641x359:rate=10", "sine=frequency=440")
    lecture = await create_lecture(user, odd)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    lecture = await load(lecture.id)
    streams = {stream["codec_type"]: stream for stream in probe_streams(Path(lecture.video_path))}
    assert streams["video"]["height"] == 358


async def test_audio_upload_has_no_video(user, sample_audio, storage):
    lecture = await create_lecture(user, sample_audio)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    lecture = await load(lecture.id)
    assert lecture.audio_path == str(storage / "audio" / f"{lecture.id}.opus")
    assert lecture.video_path is None
    assert lecture.video_expires_at is None
    assert steps_by_name(lecture)[StepName.video].status == StepStatus.done
    assert not media.original_path(lecture.id).exists()
    assert not (storage / "videos").exists()


async def test_broken_original_fails_audio_step(user, storage, tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    lecture = await create_lecture(user, broken)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed

    lecture = await load(lecture.id)
    steps = steps_by_name(lecture)
    assert steps[StepName.audio].status == StepStatus.failed
    assert steps[StepName.audio].error == "Не удалось извлечь звук из записи"
    assert StepName.video not in steps
    assert media.original_path(lecture.id).exists()
    assert not list((storage / "audio").iterdir())
    assert not list((storage / "tmp").iterdir())


async def test_ffmpeg_progress_is_reported(sample_video, tmp_path, monkeypatch):
    monkeypatch.setattr(media, "PROGRESS_INTERVAL_SEC", 0.0)
    reported = []

    async def report(progress):
        reported.append(progress)

    await media.run_ffmpeg(
        [
            "-i",
            str(sample_video),
            "-vn",
            "-c:a",
            "libopus",
            "-f",
            "opus",
            str(tmp_path / "out.opus"),
        ],
        2.0,
        report,
        "ошибка",
    )

    assert reported
    assert all(0 <= value <= 1.05 for value in reported)
    assert reported == sorted(reported)


async def test_failed_step_retries_without_repeating_done_steps(
    user, sample_video, client, auth_headers, monkeypatch
):
    lecture = await create_lecture(user, sample_video)
    calls = {"summarize": 0}
    original = tasks.HANDLERS[StepName.summarize]

    async def flaky_summarize(session, lecture, report):
        calls["summarize"] += 1
        if calls["summarize"] == 1:
            raise RuntimeError("LLM недоступна")
        await original(session, lecture, report)

    monkeypatch.setitem(tasks.HANDLERS, StepName.summarize, flaky_summarize)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed
    failed = await load(lecture.id)
    steps = steps_by_name(failed)
    assert failed.status == LectureStatus.failed
    assert steps[StepName.transcribe].status == StepStatus.done
    assert steps[StepName.summarize].status == StepStatus.failed
    assert steps[StepName.summarize].error == "LLM недоступна"
    assert StepName.embed not in steps

    enqueued = []

    async def fake_enqueue(lecture_id):
        enqueued.append(lecture_id)

    monkeypatch.setattr(lectures_api, "enqueue_lecture", fake_enqueue)
    response = await client.post(f"/api/v1/lectures/{lecture.id}/retry", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert enqueued == [lecture.id]

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    steps = steps_by_name(await load(lecture.id))
    assert steps[StepName.transcribe].attempts == 1
    assert steps[StepName.summarize].attempts == 2
    assert all(s.status == StepStatus.done for s in steps.values())


async def test_retry_rejects_lecture_that_did_not_fail(user, sample_video, client, auth_headers):
    lecture = await create_lecture(user, sample_video)
    response = await client.post(f"/api/v1/lectures/{lecture.id}/retry", headers=auth_headers)
    assert response.status_code == 409


@pytest.mark.parametrize(
    ("bounds", "expected"),
    [
        ([(0, 20), (20, 40), (40, 59)], [(0, 59)]),
        ([(0, 30), (30, 61), (61, 90)], [(0, 30), (30, 90)]),
        ([], []),
    ],
)
def test_split_into_chunks(bounds, expected):
    segments = [TranscriptSegment(start=s, end=e, text="т") for s, e in bounds]
    assert [(s, e) for s, e, _ in split_into_chunks(segments)] == expected


async def test_error_outside_step_marks_lecture_failed(user, sample_video, monkeypatch):
    lecture = await create_lecture(user, sample_video)

    async def broken_get_step(*args):
        raise ConnectionError("база недоступна")

    monkeypatch.setattr("app.pipeline.runner.get_step", broken_get_step)

    with pytest.raises(ConnectionError):
        await tasks.process_lecture({}, str(lecture.id))
    assert (await load(lecture.id)).status == LectureStatus.failed


async def test_cancelled_job_marks_running_step_failed(user, sample_video, monkeypatch):
    lecture = await create_lecture(user, sample_video)

    async def cancelled(session, lecture, report):
        raise asyncio.CancelledError

    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, cancelled)

    with pytest.raises(asyncio.CancelledError):
        await tasks.process_lecture({}, str(lecture.id))
    failed = await load(lecture.id)
    assert failed.status == LectureStatus.failed
    assert steps_by_name(failed)[StepName.transcribe].status == StepStatus.failed


async def fail_lecture(user, sample_video) -> Lecture:
    lecture = await create_lecture(user, sample_video)

    async def broken(session, lecture, report):
        raise RuntimeError("сбой")

    original = tasks.HANDLERS[StepName.transcribe]
    tasks.HANDLERS[StepName.transcribe] = broken
    try:
        await tasks.process_lecture({}, str(lecture.id))
    finally:
        tasks.HANDLERS[StepName.transcribe] = original
    return lecture


async def test_retry_returns_lecture_to_failed_when_queue_is_down(
    user, sample_video, client, auth_headers, monkeypatch
):
    lecture = await fail_lecture(user, sample_video)

    async def queue_down(lecture_id):
        raise ConnectionRefusedError

    monkeypatch.setattr(lectures_api, "enqueue_lecture", queue_down)
    response = await client.post(f"/api/v1/lectures/{lecture.id}/retry", headers=auth_headers)
    assert response.status_code == 503
    assert (await load(lecture.id)).status == LectureStatus.failed


async def test_second_retry_is_rejected(user, sample_video, client, auth_headers, monkeypatch):
    lecture = await fail_lecture(user, sample_video)

    async def fake_enqueue(lecture_id):
        pass

    monkeypatch.setattr(lectures_api, "enqueue_lecture", fake_enqueue)
    url = f"/api/v1/lectures/{lecture.id}/retry"
    first = await client.post(url, headers=auth_headers)
    second = await client.post(url, headers=auth_headers)
    assert first.status_code == 200
    assert second.status_code == 409


async def test_link_lecture_downloads_audio_before_transcribe(user, monkeypatch):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Лекция по ссылке",
            source_type=SourceType.link,
            source_url="https://vkvideo.ru/video-1_2",
        )
        session.add(lecture)
        await session.commit()
    order = []

    async def fake_download(session, lecture, report):
        order.append(StepName.download)
        lecture.audio_path = f"/data/storage/audio/{lecture.id}.opus"

    original = tasks.HANDLERS[StepName.transcribe]

    async def tracked_transcribe(session, lecture, report):
        order.append(StepName.transcribe)
        await original(session, lecture, report)

    monkeypatch.setitem(tasks.HANDLERS, StepName.download, fake_download)
    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, tracked_transcribe)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    loaded = await load(lecture.id)
    assert order == [StepName.download, StepName.transcribe]
    assert loaded.audio_path == f"/data/storage/audio/{lecture.id}.opus"
    assert steps_by_name(loaded)[StepName.download].status == StepStatus.done
