from app.providers.audio_chunks import chunk_boundaries, chunk_windows, parse_silences
from app.providers.base import Segment
from app.providers.yandex import merge_chunk_segments


def test_chunk_boundaries_use_nearest_pause_and_keep_chunks_bounded():
    boundaries = chunk_boundaries(25 * 60, [(460, 470), (930, 940)])

    assert boundaries == [(0.0, 465.0), (465.0, 935.0), (935.0, 1500)]
    assert all(5 * 60 <= end - start <= 10 * 60 for start, end in boundaries)


def test_chunk_boundaries_fall_back_to_target_without_pauses():
    assert chunk_boundaries(25 * 60, []) == [
        (0.0, 480.0),
        (480.0, 960.0),
        (960.0, 1500),
    ]


def test_chunk_windows_overlap_at_boundaries():
    windows = chunk_windows(25 * 60, [])

    assert windows[0] == (0.0, 481.5)
    assert windows[1] == (478.5, 961.5)
    assert windows[-1] == (958.5, 1500)


def test_parse_silences_ignores_unpaired_events():
    output = """
[silencedetect] silence_start: 460.000
[silencedetect] silence_end: 470.000 | silence_duration: 10.000
[silencedetect] silence_start: 930.000
"""

    assert parse_silences(output) == [(460.0, 470.0)]


def test_merge_chunk_segments_offsets_and_removes_overlap_duplicates():
    segments = merge_chunk_segments(
        [
            (0.0, [Segment(478.5, 480.5, "Повторённая фраза."), Segment(500, 502, "Дальше.")]),
            (478.5, [Segment(0, 2.2, "повторённая фраза"), Segment(8, 10, "Продолжение.")]),
        ]
    )

    assert segments == [
        Segment(478.5, 480.7, "повторённая фраза"),
        Segment(486.5, 488.5, "Продолжение."),
        Segment(500, 502, "Дальше."),
    ]


def test_ten_minute_recording_is_not_split():
    assert chunk_boundaries(600, []) == [(0.0, 600)]


def test_recording_longer_than_ten_minutes_gets_minimum_sized_parts():
    assert chunk_boundaries(601, []) == [(0.0, 301.0), (301.0, 601)]
