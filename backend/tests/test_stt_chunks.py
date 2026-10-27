import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.models import StepName
from app.pipeline import chunks
from app.pipeline.chunks import Part, merge_segments, parse_silences, plan_parts, split_audio
from app.pipeline.estimate import expected_seconds
from app.pipeline.media import probe_duration
from app.providers import Segment
from app.providers.retry import RetryPolicy
from app.providers.yandex import RECOGNIZE_URL, YandexSpeechKitError, YandexSpeechToText
from tests.test_yandex_stt import yandex_settings

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="нужен ffmpeg")


async def synthetic_audio(path: Path, duration: int, silences: list[tuple[int, int]]) -> None:
    gaps = "+".join(f"between(t,{start},{end})" for start, end in silences) or "0"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:sample_rate=16000:duration={duration}",
        "-af",
        f"volume=enable='{gaps}':volume=0",
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-b:a",
        "32k",
        "-f",
        "opus",
        str(path),
    )
    assert await process.wait() == 0


def seg(start: float, end: float, text: str) -> Segment:
    return Segment(start=start, end=end, text=text)


def test_parse_silences_pairs_and_open_tail():
    log = (
        "[silencedetect @ 0x1] silence_start: 10.5\n"
        "[silencedetect @ 0x1] silence_end: 12.0 | silence_duration: 1.5\n"
        "[silencedetect @ 0x1] silence_start: 95\n"
    )

    assert parse_silences(log, 100.0) == [(10.5, 12.0), (95.0, 100.0)]


def test_plan_cuts_in_pause_near_target():
    parts = plan_parts(600.0, [(290.0, 292.0), (150.0, 151.0)], target=300.0)

    assert len(parts) == 2
    assert parts[0].cut_end == pytest.approx(291.0)
    assert parts[1].cut_start == pytest.approx(291.0)
    assert parts[0].start == 0.0
    assert parts[0].end == pytest.approx(291.0 + chunks.OVERLAP_SECONDS / 2)
    assert parts[1].start == pytest.approx(291.0 - chunks.OVERLAP_SECONDS / 2)
    assert parts[1].end == 600.0


def test_plan_ignores_pause_outside_window():
    parts = plan_parts(600.0, [(200.0, 202.0)], target=300.0)

    assert parts[0].cut_end == pytest.approx(300.0)


def test_plan_splits_into_parts_near_target():
    parts = plan_parts(1500.0, [], target=420.0)

    assert len(parts) == 4
    assert [part.cut_end for part in parts[:-1]] == pytest.approx([375.0, 750.0, 1125.0])
    assert all(a.cut_end == b.cut_start for a, b in zip(parts, parts[1:], strict=False))


def test_merge_shifts_by_part_offset():
    parts = plan_parts(600.0, [], target=300.0)
    first = [seg(1.0, 3.0, "Начало лекции")]
    second = [seg(10.0, 12.0, "Вторая часть")]

    merged = merge_segments([(parts[0], first), (parts[1], second)], 600.0)

    offset = parts[1].start
    assert merged == [
        seg(1.0, 3.0, "Начало лекции"),
        seg(10.0 + offset, 12.0 + offset, "Вторая часть"),
    ]


def test_merge_joins_overlap_without_duplicates():
    parts = plan_parts(600.0, [], target=300.0)
    boundary = parts[0].cut_end
    shift = parts[1].start
    seam_phrase = "Это граничная фраза"
    first = [
        seg(boundary - 20, boundary - 12, "Предыдущая фраза"),
        seg(boundary - 2.0, boundary - 0.5, seam_phrase),
        seg(boundary + 0.2, boundary + 1.0, "обрывок"),
    ]
    second = [
        seg(boundary - 2.0 - shift, boundary - 0.5 - shift, seam_phrase),
        seg(boundary + 0.1 - shift, boundary + 5 - shift, "Следующая фраза"),
    ]

    merged = merge_segments([(parts[0], first), (parts[1], second)], 600.0)

    assert [s.text for s in merged] == ["Предыдущая фраза", seam_phrase, "Следующая фраза"]


def test_merge_drops_segments_inside_covered_zone():
    parts = plan_parts(600.0, [], target=300.0)
    boundary = parts[0].cut_end
    shift = parts[1].start
    first = [seg(boundary - 6, boundary - 1, "Длинная фраза")]
    second = [seg(boundary - 4 - shift, boundary - 2 - shift, "Длинная фраза внутри")]

    merged = merge_segments([(parts[0], first), (parts[1], second)], 600.0)

    assert [s.text for s in merged] == ["Длинная фраза"]


def test_merge_trims_partial_overlap_and_keeps_monotonic():
    parts = plan_parts(600.0, [], target=300.0)
    boundary = parts[0].cut_end
    shift = parts[1].start
    first = [seg(boundary - 8, boundary + 0.5, "Первая")]
    second = [seg(boundary - 0.4 - shift, boundary + 6 - shift, "Вторая")]

    merged = merge_segments([(parts[0], first), (parts[1], second)], 600.0)

    assert [s.text for s in merged] == ["Первая", "Вторая"]
    assert merged[1].start == merged[0].end
    assert all(a.end <= b.start for a, b in zip(merged, merged[1:], strict=False))


def test_merge_removes_same_text_with_same_time():
    part = Part(index=0, start=0.0, end=100.0, cut_start=0.0, cut_end=100.0)
    duplicated = [seg(41.0, 43.0, "Надуть и перекрыть"), seg(41.0, 43.0, "Надуть и перекрыть")]

    assert merge_segments([(part, duplicated)], 100.0) == [seg(41.0, 43.0, "Надуть и перекрыть")]


def test_merge_clamps_to_duration():
    part = Part(index=0, start=0.0, end=100.0, cut_start=0.0, cut_end=100.0)

    merged = merge_segments([(part, [seg(98.0, 103.0, "Хвост")])], 100.0)

    assert merged == [seg(98.0, 100.0, "Хвост")]


def test_expected_seconds_shrinks_with_parallel_parts():
    single = Settings(stt_chunk_threshold_seconds=1e9)
    parallel = Settings()

    chunked = expected_seconds(StepName.transcribe, 1500.0, parallel)
    whole = expected_seconds(StepName.transcribe, 1500.0, single)
    assert chunked is not None and whole is not None
    assert chunked < whole
    assert expected_seconds(StepName.transcribe, 600.0, parallel) == expected_seconds(
        StepName.transcribe, 600.0, single
    )


@needs_ffmpeg
async def test_split_cuts_by_pause(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    await synthetic_audio(audio, 100, [(38, 40)])
    work = tmp_path / "work"
    work.mkdir()

    parts = await split_audio(audio, 100.0, work, target=50.0)

    assert len(parts) == 2
    first, second = (part for part, _ in parts)
    assert first.cut_end == pytest.approx(39.0, abs=0.5)
    assert second.start == pytest.approx(first.cut_end - chunks.OVERLAP_SECONDS / 2)
    assert all(file.exists() and file.suffix == ".opus" for _, file in parts)
    assert first.end > first.cut_end


@needs_ffmpeg
async def test_split_cuts_by_target_without_pauses(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    await synthetic_audio(audio, 100, [])
    work = tmp_path / "work"
    work.mkdir()

    parts = await split_audio(audio, 100.0, work, target=50.0)

    assert [part.cut_end for part, _ in parts] == pytest.approx([50.0, 100.0])


@needs_ffmpeg
async def test_split_part_lengths_match_plan(tmp_path: Path):
    audio = tmp_path / "lecture.opus"
    await synthetic_audio(audio, 100, [(38, 40)])
    work = tmp_path / "work"
    work.mkdir()

    parts = await split_audio(audio, 100.0, work, target=50.0)

    for part, file in parts:
        assert await probe_duration(file) == pytest.approx(part.duration, abs=0.2)


async def test_split_without_ffmpeg_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(chunks.ChunkingError):
        await split_audio(tmp_path / "a.opus", 100.0, tmp_path, target=50.0)


def long_settings(tmp_path: Path, **options) -> Settings:
    values = yandex_settings().model_dump()
    values.update(
        stt_chunk_threshold_seconds=100.0,
        stt_chunk_target_seconds=100.0,
        stt_parallel_parts=2,
        stt_retry_base_seconds=0.0,
        storage_dir=tmp_path / "storage",
    )
    values.update(options)
    return Settings(**values)


def fake_split(count: int, part_length: float = 100.0):
    async def split(audio: Path, duration: float, workdir: Path, *, target: float):
        result = []
        for index in range(count):
            file = workdir / f"part-{index}.opus"
            file.write_bytes(f"OggS{index}".encode())
            start = index * part_length
            part = Part(
                index=index,
                start=start,
                end=start + part_length,
                cut_start=start,
                cut_end=start + part_length,
            )
            result.append((part, file))
        return result

    return split


class Recognizer:
    def __init__(self, fail_part: int | None = None, fail_times: int = 0) -> None:
        self.parts: dict[str, int] = {}
        self.running = 0
        self.peak = 0
        self.deleted = 0
        self.fail_part = fail_part
        self.fail_times = fail_times
        self.start_calls: dict[int, int] = {}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.yandexcloud.net":
            if request.method == "PUT":
                self.parts[str(request.url)] = int(request.content[-1:])
            if request.method == "DELETE":
                self.deleted += 1
            return httpx.Response(200)
        if str(request.url) == RECOGNIZE_URL:
            index = self.parts[json.loads(request.content)["audio"]["uri"]]
            self.start_calls[index] = self.start_calls.get(index, 0) + 1
            if index == self.fail_part and self.start_calls[index] <= self.fail_times:
                return httpx.Response(503)
            self.running += 1
            self.peak = max(self.peak, self.running)
            return httpx.Response(200, json={"id": f"op{index}", "done": False})
        index = int(request.url.path.rsplit("op", 1)[1])
        await asyncio.sleep(0.02)
        self.running -= 1
        words = [{"startTime": "1.000s", "endTime": "2.000s"}]
        response = {"chunks": [{"alternatives": [{"text": f"Часть {index}", "words": words}]}]}
        return httpx.Response(200, json={"id": f"op{index}", "done": True, "response": response})


async def run_parts(settings: Settings, recognizer: Recognizer, count: int, monkeypatch, tmp_path):
    monkeypatch.setattr("app.providers.yandex.split_audio", fake_split(count))
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS")
    events: list[tuple[str, float]] = []

    async def on_progress(stage: str, fraction: float) -> None:
        events.append((stage, fraction))

    provider = YandexSpeechToText(
        settings, poll_interval=0, transport=httpx.MockTransport(recognizer.handler)
    )
    segments = await provider.transcribe(
        audio, "ru", duration=count * 100.0, on_progress=on_progress
    )
    return segments, events


async def test_parts_run_in_parallel_with_limit(monkeypatch, tmp_path):
    recognizer = Recognizer()

    segments, events = await run_parts(
        long_settings(tmp_path), recognizer, 5, monkeypatch, tmp_path
    )

    assert recognizer.peak == 2
    assert [s.text for s in segments] == [f"Часть {i}" for i in range(5)]
    assert [s.start for s in segments] == [1.0, 101.0, 201.0, 301.0, 401.0]
    assert recognizer.deleted == 5
    assert not list((tmp_path / "storage" / "tmp").iterdir())
    fractions = [fraction for _, fraction in events]
    assert fractions == sorted(fractions)
    assert events[0] == ("upload", 0.0)
    assert events[-1] == ("fetch", 0.95)
    assert any(stage == "recognize" for stage, _ in events)


async def test_part_error_is_retried_independently(monkeypatch, tmp_path):
    recognizer = Recognizer(fail_part=1, fail_times=2)

    segments, _ = await run_parts(long_settings(tmp_path), recognizer, 3, monkeypatch, tmp_path)

    assert len(segments) == 3
    assert recognizer.start_calls == {0: 1, 1: 3, 2: 1}


async def test_part_failure_after_retries_fails_step(monkeypatch, tmp_path):
    recognizer = Recognizer(fail_part=2, fail_times=99)
    settings = long_settings(tmp_path, stt_retry_attempts=2)

    with pytest.raises(YandexSpeechKitError, match="запуск распознавания"):
        await run_parts(settings, recognizer, 3, monkeypatch, tmp_path)

    assert recognizer.start_calls[2] == RetryPolicy.from_settings(settings).attempts
    assert not list((tmp_path / "storage" / "tmp").iterdir())


async def test_short_lecture_is_one_request(monkeypatch, tmp_path):
    recognizer = Recognizer()
    called = []

    async def forbidden(*args, **kwargs):
        called.append(True)

    monkeypatch.setattr("app.providers.yandex.split_audio", forbidden)
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS0")
    provider = YandexSpeechToText(
        long_settings(tmp_path), poll_interval=0, transport=httpx.MockTransport(recognizer.handler)
    )

    segments = await provider.transcribe(audio, "ru", duration=60.0)

    assert [s.text for s in segments] == ["Часть 0"]
    assert called == []


async def test_split_failure_falls_back_to_single_request(monkeypatch, tmp_path):
    recognizer = Recognizer()

    async def broken(*args, **kwargs):
        raise chunks.ChunkingError("нет ffmpeg")

    monkeypatch.setattr("app.providers.yandex.split_audio", broken)
    audio = tmp_path / "lecture.opus"
    audio.write_bytes(b"OggS0")
    provider = YandexSpeechToText(
        long_settings(tmp_path), poll_interval=0, transport=httpx.MockTransport(recognizer.handler)
    )

    segments = await provider.transcribe(audio, "ru", duration=500.0)

    assert [s.text for s in segments] == ["Часть 0"]
