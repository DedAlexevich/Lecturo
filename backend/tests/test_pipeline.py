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
from arq.connections import ArqRedis, RedisSettings
from arq.constants import (
    abort_jobs_ss,
    default_queue_name,
    in_progress_key_prefix,
    job_key_prefix,
)
from arq.jobs import Job, JobStatus
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
    NotificationEvent,
    NotificationKind,
    NotificationOutcome,
    ProcessingStep,
    SearchChunk,
    SourceType,
    StepName,
    StepStatus,
    Subscription,
    Summary,
    TranscriptSegment,
    UsageEntry,
)
from app.pipeline import download, events, media, stages, tasks
from app.providers.stub import STUB_PHRASES
from tests.conftest import notifications


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
    assert response.json()["video_url"].startswith(f"/media/{lecture.id}.mp4?expires=")


async def test_subscriber_video_kept_longer(user, sample_video):
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add(
            Subscription(
                user_id=user.id, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29)
            )
        )
        await session.commit()
    lecture = await create_lecture(user, sample_video)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    lecture = await load(lecture.id)
    days = get_settings().subscription_video_retention_days
    expected_expiry = datetime.now(UTC) + timedelta(days=days)
    assert abs(lecture.video_expires_at - expected_expiry) < timedelta(minutes=1)


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


async def test_upload_is_ready_before_video_is_compressed(user, sample_video, monkeypatch):
    lecture = await create_lecture(user, sample_video)
    order = []
    transcode = tasks.HANDLERS[StepName.video]

    async def tracked_video(session, lecture, report):
        order.append((StepName.video, lecture.status))
        await transcode(session, lecture, report)

    for name in (StepName.audio, StepName.transcribe, StepName.summarize, StepName.embed):

        def tracked(handler=tasks.HANDLERS[name], name=name):
            async def run(session, lecture, report):
                order.append((name, lecture.status))
                await handler(session, lecture, report)

            return run

        monkeypatch.setitem(tasks.HANDLERS, name, tracked())
    monkeypatch.setitem(tasks.HANDLERS, StepName.video, tracked_video)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    assert order == [
        (StepName.audio, LectureStatus.processing),
        (StepName.transcribe, LectureStatus.processing),
        (StepName.summarize, LectureStatus.processing),
        (StepName.embed, LectureStatus.processing),
        (StepName.video, LectureStatus.ready),
    ]
    assert (await load(lecture.id)).video_path is not None


async def test_failed_video_keeps_lecture_ready(user, sample_video, storage, monkeypatch):
    lecture = await create_lecture(user, sample_video)

    encode = media.encode

    async def broken_encode(args, target, duration, report, error):
        if target.parent.name == "videos":
            raise media.MediaError(error)
        await encode(args, target, duration, report, error)

    monkeypatch.setattr(media, "encode", broken_encode)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    lecture = await load(lecture.id)
    steps = steps_by_name(lecture)
    assert lecture.status == LectureStatus.ready
    assert lecture.video_path is None
    assert steps[StepName.video].status == StepStatus.failed
    assert steps[StepName.video].error == "Не удалось пережать видео"
    assert steps[StepName.transcribe].status == StepStatus.done
    assert await count(UsageEntry, lecture.id) == 1
    assert await notifications(lecture.id) == [
        (NotificationKind.lecture, NotificationOutcome.ready)
    ]
    assert not media.original_path(lecture.id).exists()


async def test_ready_lecture_job_only_finishes_video(user, sample_video, monkeypatch):
    lecture = await create_lecture(user, sample_video)
    publish = events.publish_status

    async def cancelled_on_ready(lecture_id, user_id, status, error=None):
        if status == LectureStatus.ready:
            raise asyncio.CancelledError
        await publish(lecture_id, user_id, status, error)

    monkeypatch.setattr(tasks, "publish_status", cancelled_on_ready)
    with pytest.raises(asyncio.CancelledError):
        await tasks.process_lecture({}, str(lecture.id))
    assert steps_by_name(await load(lecture.id))[StepName.video].status == StepStatus.pending

    monkeypatch.setattr(tasks, "publish_status", publish)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    lecture = await load(lecture.id)
    steps = steps_by_name(lecture)
    assert steps[StepName.video].status == StepStatus.done
    assert steps[StepName.transcribe].attempts == 1
    assert lecture.video_path is not None


def encode_sample(path: Path, size: str, *video_args: str) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={size}:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440",
            "-t",
            "2",
            *video_args,
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )
    return path


async def test_player_ready_video_is_copied(user, storage, tmp_path):
    source = encode_sample(
        tmp_path / "ready.mp4", "1280x720", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"
    )
    assert media.fits_player(await media.media_streams(source))
    lecture = await create_lecture(user, source)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    video = storage / "videos" / f"{lecture.id}.mp4"
    assert (await load(lecture.id)).video_path == str(video)
    copied, original = await asyncio.to_thread(lambda: (video.read_bytes(), source.read_bytes()))
    assert len(copied) == pytest.approx(len(original), rel=0.05)
    assert copied.index(b"moov") < copied.index(b"mdat")


@pytest.mark.parametrize(
    ("size", "video_args"),
    [
        ("1280x720", ("-c:v", "mpeg4")),
        ("1920x1080", ("-c:v", "libx264", "-pix_fmt", "yuv420p")),
        ("1280x720", ("-c:v", "libx264", "-pix_fmt", "yuv444p")),
        ("1280x720", ("-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv420p")),
    ],
)
async def test_other_videos_are_transcoded(tmp_path, size, video_args):
    source = encode_sample(tmp_path / "source.mp4", size, *video_args)
    assert not media.fits_player(await media.media_streams(source))


async def test_videos_without_aac_are_transcoded(sample_video, sample_audio):
    assert not media.fits_player(await media.media_streams(sample_video))
    assert not media.fits_player(await media.media_streams(sample_audio))


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


async def test_cancelled_job_returns_lecture_to_queue(user, sample_video, monkeypatch):
    lecture = await create_lecture(user, sample_video)

    async def cancelled(session, lecture, report):
        raise asyncio.CancelledError

    transcribe = tasks.HANDLERS[StepName.transcribe]
    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, cancelled)

    with pytest.raises(asyncio.CancelledError):
        await tasks.process_lecture({}, str(lecture.id))
    interrupted = await load(lecture.id)
    steps = steps_by_name(interrupted)
    assert interrupted.status == LectureStatus.queued
    assert steps[StepName.audio].status == StepStatus.done
    assert steps[StepName.transcribe].status == StepStatus.pending
    assert media.original_path(lecture.id).exists()

    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, transcribe)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    steps = steps_by_name(await load(lecture.id))
    assert steps[StepName.audio].attempts == 1
    assert all(s.status == StepStatus.done for s in steps.values())


async def test_timed_out_job_marks_running_step_failed(user, sample_audio, monkeypatch):
    lecture = await create_lecture(user, sample_audio)

    async def endless(session, lecture, report):
        await asyncio.sleep(60)

    monkeypatch.setattr(tasks, "LECTURE_TIMEOUT_SEC", 0.5)
    monkeypatch.setitem(tasks.HANDLERS, StepName.audio, endless)

    with pytest.raises(TimeoutError):
        await tasks.process_lecture({}, str(lecture.id))
    failed = await load(lecture.id)
    assert failed.status == LectureStatus.failed
    assert steps_by_name(failed)[StepName.audio].status == StepStatus.failed


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


async def test_link_lecture_charges_downloaded_duration(user, sample_audio, monkeypatch):
    async with SessionLocal() as session:
        lecture = Lecture(
            owner_id=user.id,
            title="Лекция по ссылке",
            source_type=SourceType.link,
            source_url="https://vkvideo.ru/video-1_2",
            duration_sec=0.5,
        )
        session.add(lecture)
        await session.commit()

    async def allow(url):
        pass

    def fake_fetch(url, target, progress):
        path = target.with_suffix(".opus")
        shutil.copy(sample_audio, path)
        return path

    monkeypatch.setattr(download, "ensure_public_host", allow)
    monkeypatch.setattr(download, "fetch_audio", fake_fetch)

    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    loaded = await load(lecture.id)
    assert loaded.duration_sec == pytest.approx(2.0, abs=0.2)
    assert await charged_seconds(lecture.id) == math.ceil(loaded.duration_sec)


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
    assert await notifications(lecture.id) == []
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


async def test_ready_lecture_records_notification(user, sample_audio):
    lecture = await create_lecture(user, sample_audio)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready

    async with SessionLocal() as session:
        event = await session.scalar(
            select(NotificationEvent).where(NotificationEvent.lecture_id == lecture.id)
        )
    assert (event.user_id, event.kind, event.outcome) == (
        user.id,
        NotificationKind.lecture,
        NotificationOutcome.ready,
    )
    assert event.sent_at is None
    assert event.expired_at is None
    assert event.attempts == 0


async def test_failed_step_records_notification_once(user, sample_audio, monkeypatch):
    lecture = await create_lecture(user, sample_audio)

    async def broken(session, lecture, report):
        raise RuntimeError("сбой распознавания")

    monkeypatch.setitem(tasks.HANDLERS, StepName.transcribe, broken)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.failed

    assert await notifications(lecture.id) == [
        (NotificationKind.lecture, NotificationOutcome.failed)
    ]


async def test_error_outside_step_records_notification(user, sample_audio, monkeypatch):
    lecture = await create_lecture(user, sample_audio)

    async def broken_get_step(*args):
        raise ConnectionError("база недоступна")

    monkeypatch.setattr("app.pipeline.runner.get_step", broken_get_step)
    with pytest.raises(ConnectionError):
        await tasks.process_lecture({}, str(lecture.id))

    assert await notifications(lecture.id) == [
        (NotificationKind.lecture, NotificationOutcome.failed)
    ]


async def test_unavailable_redis_does_not_break_pipeline(user, sample_audio, monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    lecture = await create_lecture(user, sample_audio)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    assert await notifications(lecture.id) == [
        (NotificationKind.lecture, NotificationOutcome.ready)
    ]


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


async def interrupted_lecture(user, source: Path, step: StepName) -> Lecture:
    lecture = await create_lecture(user, source)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        stored.status = LectureStatus.processing
        session.add(
            ProcessingStep(
                lecture_id=lecture.id,
                step=step,
                status=StepStatus.running,
                attempts=1,
                progress=0.3,
            )
        )
        await session.commit()
    return lecture


@pytest.fixture
async def arq_redis() -> AsyncIterator[ArqRedis]:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    yield redis
    job_ids = await redis.zrange(default_queue_name, 0, -1)
    for job_id in job_ids:
        await redis.delete(
            job_key_prefix + job_id.decode(), in_progress_key_prefix + job_id.decode()
        )
    await redis.delete(default_queue_name)
    await redis.aclose()


async def test_orphaned_job_is_released_on_startup(user, sample_video, arq_redis):
    lecture = await interrupted_lecture(user, sample_video, StepName.audio)
    job_id = tasks.lecture_job_id(lecture.id)
    await arq_redis.enqueue_job("process_lecture", str(lecture.id), _job_id=job_id)
    await arq_redis.set(in_progress_key_prefix + job_id, b"1")

    assert await tasks.resume_interrupted_lectures(arq_redis) == 0

    assert await Job(job_id, arq_redis).status() == JobStatus.queued
    assert await arq_redis.zcard(default_queue_name) == 1
    resumed = await load(lecture.id)
    step = steps_by_name(resumed)[StepName.audio]
    assert resumed.status == LectureStatus.queued
    assert (step.status, step.progress) == (StepStatus.pending, 0.0)


async def test_lost_job_is_enqueued_on_startup(user, sample_video, arq_redis):
    lecture = await interrupted_lecture(user, sample_video, StepName.audio)

    assert await tasks.resume_interrupted_lectures(arq_redis) == 1

    job_id = tasks.lecture_job_id(lecture.id)
    assert await Job(job_id, arq_redis).status() == JobStatus.queued
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    steps = steps_by_name(await load(lecture.id))
    assert steps[StepName.audio].attempts == 2
    assert all(s.status == StepStatus.done for s in steps.values())


async def test_ready_lecture_with_interrupted_video_is_resumed(user, sample_video, arq_redis):
    lecture = await interrupted_lecture(user, sample_video, StepName.video)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        stored.status = LectureStatus.ready
        await session.commit()

    assert await tasks.resume_interrupted_lectures(arq_redis) == 1

    resumed = await load(lecture.id)
    assert resumed.status == LectureStatus.ready
    assert steps_by_name(resumed)[StepName.video].status == StepStatus.pending


async def test_finished_and_waiting_lectures_are_not_resumed(user, sample_audio, arq_redis):
    lecture = await create_lecture(user, sample_audio)
    assert await tasks.process_lecture({}, str(lecture.id)) == LectureStatus.ready
    waiting = await create_lecture(user, sample_audio)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, waiting.id)
        stored.status = LectureStatus.waiting_quota
        await session.commit()

    assert await tasks.resume_interrupted_lectures(arq_redis) == 0
    assert await arq_redis.zcard(default_queue_name) == 0


async def test_interrupted_regeneration_is_left_to_its_job(user, sample_audio, arq_redis):
    lecture = await interrupted_lecture(user, sample_audio, StepName.summarize)
    job_id = tasks.regeneration_job_id(lecture.id)
    await arq_redis.enqueue_job("process_regeneration", str(lecture.id), _job_id=job_id)
    await arq_redis.set(in_progress_key_prefix + job_id, b"1")

    assert await tasks.resume_interrupted_lectures(arq_redis) == 0

    assert await Job(job_id, arq_redis).status() == JobStatus.queued
    assert await Job(tasks.lecture_job_id(lecture.id), arq_redis).info() is None
    assert (await load(lecture.id)).status == LectureStatus.processing


async def test_ready_lecture_with_pending_video_is_resumed(user, sample_video, arq_redis):
    lecture = await create_lecture(user, sample_video)
    async with SessionLocal() as session:
        stored = await session.get(Lecture, lecture.id)
        stored.status = LectureStatus.ready
        session.add(ProcessingStep(lecture_id=lecture.id, step=StepName.video, attempts=0))
        await session.commit()

    assert await tasks.resume_interrupted_lectures(arq_redis) == 1
    assert await Job(tasks.lecture_job_id(lecture.id), arq_redis).status() == JobStatus.queued
