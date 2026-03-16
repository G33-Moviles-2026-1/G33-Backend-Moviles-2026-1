from datetime import time

from app.db.models import Weekday


OPERATING_HOURS: dict[Weekday, tuple[time, time] | None] = {
    Weekday.monday: (time(5, 30), time(22, 0)),
    Weekday.tuesday: (time(5, 30), time(22, 0)),
    Weekday.wednesday: (time(5, 30), time(22, 0)),
    Weekday.thursday: (time(5, 30), time(22, 0)),
    Weekday.friday: (time(5, 30), time(22, 0)),
    Weekday.saturday: (time(6, 0), time(18, 0)),
    Weekday.sunday: None,
}


def get_operating_hours(weekday: Weekday) -> tuple[time, time] | None:
    return OPERATING_HOURS.get(weekday)


def clip_to_operating_hours(
    weekday: Weekday,
    start: time,
    end: time,
) -> tuple[time, time] | None:
    hours = get_operating_hours(weekday)
    if hours is None:
        return None

    open_time, close_time = hours
    clipped_start = max(start, open_time)
    clipped_end = min(end, close_time)

    if clipped_start >= clipped_end:
        return None

    return clipped_start, clipped_end