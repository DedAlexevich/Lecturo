import asyncio
import json
import math
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from arq import create_pool
from arq.connections import RedisSettings
from arq.constants import abort_jobs_ss, default_queue_name, job_key_prefix
from arq.worker import Worker
from arq.worker import func as arq_func
from redis.asyncio import Redis
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
    UsageEntry,
)
from app.pipeline import events, media, stages, tasks
from app.providers.stub import STUB_PHRASES


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


async def test_retry_publishes_failed_when_queue_is_down(
    user, sample_video, client, auth_headers, received, monkeypatch
):
    lecture = await fail_lecture(user, sample_video)
    await received(lecture)

    async def queue_down(lecture_id):
        raise ConnectionRefusedError

    monkeypatch.setattr(lectures_api, "enqueue_lecture", queue_down)
    response = await client.post(f"/api/v1/lectures/{lecture.id}/retry", headers=auth_headers)
    assert response.status_code == 503
    assert await received(lecture) == [
        {
            "lecture_id": str(lecture.id),
            "user_id": str(user.id),
            "status": "failed",
            "error": "Очередь недоступна, попробуйте позже",
        }
    ]


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


async def test_cancelled_ffmpeg_is_killed(sample_video, storage, monkeypatch):
    started = asyncio.Event()

    async def report(progress):
        started.set()

    monkeypatch.setattr(media, "PROGRESS_INTERVAL_SEC", 0.0)
    target = storage / "videos" / "cancelled.mp4"
    encoding = asyncio.create_task(
        media.encode(
            ["-stream_loop", "-1", "-i", str(sample_video), "-c:v", "libx264", "-f", "mp4"],
            target,
            2.0,
            report,
            "ошибка",
        )
    )
    await asyncio.wait_for(started.wait(), 30)
    encoding.cancel()

    with pytest.raises(asyncio.CancelledError):
        await encoding
    assert not target.exists()
    assert not list((storage / "tmp").iterdir())


async def load_segments(lecture_id) -> list[TranscriptSegment]:
    async with SessionLocal() as session:
        rows = await session.scalars(
            select(TranscriptSegment)
            .where(TranscriptSegment.lecture_id == lecture_id)
            .order_by(TranscriptSegment.idx)
        )
        return list(rows)


async def run_transcribe(lecture_id) -> None:
    async def report(progress):
        pass

    async with SessionLocal() as session:
        lecture = await session.get(Lecture, lecture_id)
        await stages.transcribe(session, lecture, report)
        await session.commit()


async def charged_seconds(lecture_id) -> int:
    async with SessionLocal() as session:
        return await session.scalar(
            select(func.coalesce(func.sum(UsageEntry.seconds), 0)).where(
                UsageEntry.lecture_id == lecture_id
            )
        )


async def test_transcribe_saves_stub_segments_in_order(user, sample_audio):
    lecture = await create_lecture(user, sample_audio)

    await run_transcribe(lecture.id)

    segments = await load_segments(lecture.id)
    assert [s.idx for s in segments] == list(range(len(STUB_PHRASES)))
    assert [s.text for s in segments] == STUB_PHRASES
    assert all(s.start < s.end for s in segments)
    assert [s.start for s in segments] == sorted(s.start for s in segments)


async def test_repeated_transcribe_replaces_segments(user, sample_audio):
    lecture = await create_lecture(user, sample_audio)

    await run_transcribe(lecture.id)
    await run_transcribe(lecture.id)

    segments = await load_segments(lecture.id)
    assert [s.idx for s in segments] == list(range(len(STUB_PHRASES)))
    assert await charged_seconds(lecture.id) == 2


async def test_transcribe_charges_lecture_duration(user, sample_video):
    lecture = await create_lecture(user, sample_video)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    loaded = await load(lecture.id)
    assert await charged_seconds(lecture.id) == math.ceil(loaded.duration_sec)


async def test_transcribe_waits_for_quota(user, sample_audio, monkeypatch):
    monkeypatch.setattr(get_settings(), "free_weekly_seconds", 1)
    lecture = await create_lecture(user, sample_audio)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.waiting_quota

    waiting = await load(lecture.id)
    step = steps_by_name(waiting)[StepName.transcribe]
    assert waiting.status == LectureStatus.waiting_quota
    assert step.status == StepStatus.pending
    assert step.error == "Не хватает лимита на обработку лекции"
    assert StepName.summarize not in steps_by_name(waiting)
    assert await count(TranscriptSegment, lecture.id) == 0
    assert await charged_seconds(lecture.id) == 0


async def test_transcribe_takes_duration_from_last_segment(user, sample_audio):
    lecture = await create_lecture(user, sample_audio)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        stored.duration_sec = None
        await session.commit()

    await run_transcribe(lecture.id)

    assert (await load(lecture.id)).duration_sec == 59.5
    assert await charged_seconds(lecture.id) == 60


Received = Callable[[Lecture], Awaitable[list[dict]]]


@pytest.fixture
async def received() -> AsyncIterator[Received]:
    redis = Redis.from_url(get_settings().redis_url)
    pubsub = redis.pubsub()
    await pubsub.subscribe(events.CHANNEL)
    await pubsub.get_message(timeout=1)

    async def collect(lecture: Lecture) -> list[dict]:
        messages = []
        while message := await pubsub.get_message(ignore_subscribe_messages=True, timeout=1):
            payload = json.loads(message["data"])
            if payload["lecture_id"] == str(lecture.id):
                messages.append(payload)
        return messages

    yield collect
    await pubsub.aclose()
    await redis.aclose()


async def test_ready_lecture_publishes_events(user, sample_audio, received):
    lecture = await create_lecture(user, sample_audio)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    assert await received(lecture) == [
        {"lecture_id": str(lecture.id), "user_id": str(user.id), "status": status, "error": None}
        for status in ("processing", "ready")
    ]


async def test_failed_step_publishes_error(user, sample_audio, received, monkeypatch):
    lecture = await create_lecture(user, sample_audio)

    async def broken(session, lecture, report):
        raise RuntimeError("сбой распознавания")

    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, broken)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed

    assert (await received(lecture))[-1] == {
        "lecture_id": str(lecture.id),
        "user_id": str(user.id),
        "status": "failed",
        "error": "сбой распознавания",
    }


async def test_error_outside_step_publishes_failed(user, sample_audio, received, monkeypatch):
    lecture = await create_lecture(user, sample_audio)

    async def broken_get_step(*args):
        raise ConnectionError("база недоступна")

    monkeypatch.setattr("app.pipeline.runner.get_step", broken_get_step)
    with pytest.raises(ConnectionError):
        await tasks.process_lecture({}, str(lecture.id))

    last = (await received(lecture))[-1]
    assert (last["status"], last["error"]) == ("failed", "база недоступна")


async def test_unavailable_redis_does_not_break_pipeline(user, sample_audio, monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    lecture = await create_lecture(user, sample_audio)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready


async def test_interrupted_ready_event_keeps_lecture_ready(user, sample_audio, monkeypatch):
    lecture = await create_lecture(user, sample_audio)
    publish = events.publish_status

    async def cancelled_on_ready(lecture_id, user_id, status, error=None):
        if status == LectureStatus.ready:
            raise asyncio.CancelledError
        await publish(lecture_id, user_id, status, error)

    monkeypatch.setattr(tasks, "publish_status", cancelled_on_ready)
    with pytest.raises(asyncio.CancelledError):
        await tasks.process_lecture({}, str(lecture.id))
    assert (await load(lecture.id)).status == LectureStatus.ready


async def test_cancelled_job_is_not_started():
    lecture_id = uuid.uuid4()
    calls = []

    async def fake_process(ctx, job_lecture_id):
        calls.append(job_lecture_id)

    job_id = tasks.lecture_job_id(lecture_id)
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    worker = Worker(
        functions=[arq_func(fake_process, name="process_lecture")],
        redis_pool=redis,
        burst=True,
        allow_abort_jobs=True,
        keep_result=0,
        poll_delay=0.1,
    )
    try:
        assert not await tasks.cancel_lecture_job(lecture_id)
        await tasks.enqueue_lecture(lecture_id)
        assert await tasks.cancel_lecture_job(lecture_id)
        await worker.main()
    finally:
        await redis.delete(job_key_prefix + job_id)
        await redis.zrem(default_queue_name, job_id)
        await redis.zrem(abort_jobs_ss, job_id)
        await worker.close()
    assert calls == []
    assert not await tasks.cancel_lecture_job(lecture_id)
