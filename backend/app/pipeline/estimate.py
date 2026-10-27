import math
from collections.abc import Iterable

from app.core.config import Settings
from app.models import StepName, StepStatus

ETA_STEP_MINIMUM_SEC = 5.0


def recognition_seconds(duration_sec: float, settings: Settings) -> float:
    return max(duration_sec * settings.stt_expected_ratio, settings.stt_expected_min_seconds)


def is_chunked(duration_sec: float | None, settings: Settings) -> bool:
    return bool(duration_sec) and duration_sec > settings.stt_chunk_threshold_seconds


def chunked_recognition_seconds(duration_sec: float, settings: Settings) -> float:
    parts = max(2, round(duration_sec / max(settings.stt_chunk_target_seconds, 1.0)))
    waves = math.ceil(parts / max(1, settings.stt_parallel_parts))
    return waves * recognition_seconds(duration_sec / parts, settings)


def expected_seconds(
    step: StepName, duration_sec: float | None, settings: Settings
) -> float | None:
    if not duration_sec or duration_sec <= 0:
        return None
    if step == StepName.transcribe:
        if is_chunked(duration_sec, settings):
            return max(chunked_recognition_seconds(duration_sec, settings), ETA_STEP_MINIMUM_SEC)
        return max(recognition_seconds(duration_sec, settings), ETA_STEP_MINIMUM_SEC)
    ratios = {
        StepName.download: settings.eta_download_ratio,
        StepName.audio: settings.eta_audio_ratio,
        StepName.summarize: settings.eta_summarize_ratio,
        StepName.embed: settings.eta_embed_ratio,
    }
    ratio = ratios.get(step)
    if ratio is None:
        return None
    return max(duration_sec * ratio, ETA_STEP_MINIMUM_SEC)


def remaining_seconds(
    plan: list[StepName],
    steps: Iterable[tuple[StepName, StepStatus, float]],
    duration_sec: float | None,
    settings: Settings,
) -> int | None:
    known = {name: (status, progress) for name, status, progress in steps}
    total = 0.0
    for name in plan:
        expected = expected_seconds(name, duration_sec, settings)
        if expected is None:
            return None
        status, progress = known.get(name, (StepStatus.pending, 0.0))
        if status == StepStatus.done:
            continue
        done_share = progress if status == StepStatus.running else 0.0
        total += expected * (1.0 - min(max(done_share, 0.0), 1.0))
    return round(total)
