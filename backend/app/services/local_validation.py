import math

from app.core.config import Settings
from app.schemas.lecture import LocalResultIn


class LocalResultInvalid(Exception):
    pass


def validate_local_result(body: LocalResultIn, settings: Settings) -> None:
    if (
        len(body.segments) > settings.local_max_segments
        or len(body.chapters) > settings.local_max_chapters
    ):
        raise LocalResultInvalid("Слишком много сегментов или глав")
    if any(len(s.text) > settings.local_max_text_chars for s in body.segments):
        raise LocalResultInvalid("Слишком длинный текст сегмента")
    total = (
        sum(len(s.text) for s in body.segments)
        + sum(len(c.title) + len(c.summary) for c in body.chapters)
        + len(body.summary_md or "")
    )
    if total > settings.local_max_total_chars:
        raise LocalResultInvalid("Слишком большой объём текста")
    items = [*body.segments, *body.chapters]
    if not all(math.isfinite(i.start) and math.isfinite(i.end) for i in items):
        raise LocalResultInvalid("Некорректные таймкоды")
    limit = body.duration_sec + settings.local_timecode_tolerance_sec
    previous_start = 0.0
    for segment in body.segments:
        if segment.start < 0 or segment.end < segment.start:
            raise LocalResultInvalid("Некорректные таймкоды в расшифровке")
        if segment.start < previous_start:
            raise LocalResultInvalid("Таймкоды расшифровки должны идти по возрастанию")
        if segment.end > limit:
            raise LocalResultInvalid("Таймкоды расшифровки выходят за длительность записи")
        previous_start = segment.start

    previous_start = 0.0
    for chapter in body.chapters:
        if chapter.start < 0 or chapter.end < chapter.start:
            raise LocalResultInvalid("Некорректные таймкоды в главах")
        if chapter.start < previous_start:
            raise LocalResultInvalid("Таймкоды глав должны идти по возрастанию")
        if chapter.end > limit:
            raise LocalResultInvalid("Таймкоды глав выходят за длительность записи")
        previous_start = chapter.start

    characters = sum(len(segment.text.strip()) for segment in body.segments)
    per_minute = characters / (body.duration_sec / 60)
    if not settings.local_min_chars_per_minute <= per_minute <= settings.local_max_chars_per_minute:
        raise LocalResultInvalid("Объём текста не соответствует длительности записи")
