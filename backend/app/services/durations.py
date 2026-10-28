import math


def whole_minutes(seconds: float, *, round_up: bool) -> int:
    minutes = seconds / 60
    return math.ceil(minutes) if round_up else math.floor(minutes + 0.5)


def format_duration(seconds: float, *, round_up: bool) -> str:
    hours, minutes = divmod(whole_minutes(seconds, round_up=round_up), 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"
