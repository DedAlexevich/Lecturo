from collections.abc import Iterable

from app.core.config import Settings
from app.models import StepName, StepStatus

ETA_STEP_MINIMUM_SEC = 5.0


def expected_seconds(
    step: StepName, duration_sec: float | None, settings: Settings
) -> float | None:
    if not duration_sec or duration_sec <= 0:
        return None
    ratios = {
        StepName.download: settings.eta_download_ratio,
        StepName.audio: settings.eta_audio_ratio,
        StepName.transcribe: settings.stt_expected_ratio,
        StepName.summarize: settings.eta_summarize_ratio,
        StepName.embed: settings.eta_embed_ratio,
    }
    ratio = ratios.get(step)
    if ratio is None:
        return None
    minimum = settings.stt_expected_min_seconds if step == StepName.transcribe else 0.0
    return max(duration_sec * ratio, minimum, ETA_STEP_MINIMUM_SEC)


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
