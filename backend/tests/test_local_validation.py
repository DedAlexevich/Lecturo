import pytest

from app.core.config import Settings
from app.schemas.lecture import ChapterOut, LocalResultIn, SegmentOut
from app.services.local_validation import LocalResultInvalid, validate_local_result

TEXT = "слово " * 40


def make_body(**overrides) -> LocalResultIn:
    fields = {
        "title": "Матанализ",
        "duration_sec": 120.0,
        "model": "whisper-small",
        "segments": [
            SegmentOut(start=0.0, end=60.0, text=TEXT),
            SegmentOut(start=60.0, end=120.0, text=TEXT),
        ],
        **overrides,
    }
    return LocalResultIn(**fields)


def test_valid_result_passes():
    validate_local_result(make_body(), Settings())


@pytest.mark.parametrize(
    "segments",
    [
        [SegmentOut(start=0.0, end=200.0, text=TEXT)],
        [SegmentOut(start=-1.0, end=10.0, text=TEXT)],
        [SegmentOut(start=10.0, end=5.0, text=TEXT)],
        [SegmentOut(start=50.0, end=60.0, text=TEXT), SegmentOut(start=10.0, end=20.0, text=TEXT)],
    ],
)
def test_bad_segment_timecodes(segments):
    with pytest.raises(LocalResultInvalid):
        validate_local_result(make_body(segments=segments), Settings())


def test_chapter_beyond_duration():
    chapters = [ChapterOut(start=0.0, end=500.0, title="Глава", summary="")]
    with pytest.raises(LocalResultInvalid):
        validate_local_result(make_body(chapters=chapters), Settings())


def test_chapters_must_ascend():
    chapters = [
        ChapterOut(start=60.0, end=100.0, title="Б", summary=""),
        ChapterOut(start=0.0, end=60.0, title="А", summary=""),
    ]
    with pytest.raises(LocalResultInvalid):
        validate_local_result(make_body(chapters=chapters), Settings())


@pytest.mark.parametrize("text", ["да", "слово " * 5000])
def test_text_length_must_match_duration(text):
    segments = [SegmentOut(start=0.0, end=100.0, text=text)]
    with pytest.raises(LocalResultInvalid):
        validate_local_result(make_body(segments=segments), Settings())


def test_nan_timecodes_rejected():
    segments = [SegmentOut(start=float("nan"), end=float("nan"), text=TEXT)]
    with pytest.raises(LocalResultInvalid):
        validate_local_result(make_body(segments=segments), Settings())


def test_too_many_segments_rejected():
    segments = [SegmentOut(start=0.0, end=1.0, text=TEXT)] * 3
    with pytest.raises(LocalResultInvalid):
        validate_local_result(make_body(segments=segments), Settings(local_max_segments=2))
