import pytest

from app.services.durations import format_duration


@pytest.mark.parametrize(
    ("seconds", "round_up", "expected"),
    [
        (0, True, "0 мин"),
        (1, True, "1 мин"),
        (89, False, "1 мин"),
        (90, False, "2 мин"),
        (3599, True, "1 ч"),
        (3601, True, "1 ч 1 мин"),
        (3601, False, "1 ч"),
        (2 * 3600 + 150, False, "2 ч 3 мин"),
    ],
)
def test_format_duration(seconds, round_up, expected):
    assert format_duration(seconds, round_up=round_up) == expected
