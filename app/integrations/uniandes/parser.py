from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import re


DAY_MAP = {
    "l": "monday",
    "m": "tuesday",
    "i": "wednesday",
    "j": "thursday",
    "v": "friday",
    "s": "saturday",
    "d": "sunday",
}

BUILDING_BLACKLIST = {
    "0", "", " -", "VIRT", "NOREQ", "SALA", "LIGA", "LAB",
    "FEDELLER", "FSFB", "HFONTIB", "HLSAMAR", "HLVICT",
    "HSBOLIV", "HSUBA", "IMI", "MEDLEG", "SVICENP", "ZIPAUF",
}

APP_DAY_START = time(5, 30)
APP_DAY_END = time(22, 0)


@dataclass(frozen=True)
class OccupiedMeeting:
    room_id: str
    building_code: str
    building_name: str
    room_number: str
    day: str
    start_time: time
    end_time: time
    valid_from: date
    valid_to: date
    capacity: int


def safe_int(value) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def format_api_time(raw: str | None) -> time | None:
    if not raw or len(raw) < 4:
        return None
    return time(hour=int(raw[:2]), minute=int(raw[2:4]))


def parse_api_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace(" ", "T")).date()


def parse_classroom(classroom: str | None) -> tuple[str, str]:
    if not classroom:
        return ("NOREQ", "")
    cleaned = classroom.lstrip(".")
    if "_" in cleaned:
        building, room = cleaned.split("_", 1)
        return building, room
    return cleaned, ""


def sanitize_building_code(code: str) -> str:
    code = (code or "").strip().upper()
    if code in BUILDING_BLACKLIST:
        return "NOREQ"
    return code


def clean_building_name(raw_building: str | None, fallback_code: str) -> str:
    if not raw_building:
        return fallback_code

    cleaned = raw_building.lstrip(".").strip()

    # ".Edif. Mario Laserna (ML)" -> "Edif. Mario Laserna"
    match = re.match(r"^(.*?)(\s*\([A-Z0-9\-]+\))?$", cleaned)
    if match:
        name = match.group(1).strip()
        if name:
            return name.title()

    return cleaned.title()


def clip_to_app_window(start: time, end: time) -> tuple[time, time] | None:
    clipped_start = max(start, APP_DAY_START)
    clipped_end = min(end, APP_DAY_END)
    if clipped_end <= clipped_start:
        return None
    return clipped_start, clipped_end


def normalize_meetings(raw_courses: list[dict], term_id: str) -> list[OccupiedMeeting]:
    meetings: list[OccupiedMeeting] = []

    for raw in raw_courses:
        if str(raw.get("term", "")) != term_id:
            continue

        capacity = safe_int(raw.get("maxenrol"))
        schedules = raw.get("schedules") or []

        for s in schedules:
            start = format_api_time(s.get("time_ini"))
            end = format_api_time(s.get("time_fin"))
            if start is None or end is None:
                continue
            if end <= start:
                continue

            clipped = clip_to_app_window(start, end)
            if clipped is None:
                continue
            start, end = clipped

            valid_from = parse_api_date(s.get("date_ini"))
            valid_to = parse_api_date(s.get("date_fin"))
            if valid_from is None or valid_to is None or valid_to < valid_from:
                continue

            building_code, room_number = parse_classroom(s.get("classroom"))
            building_code = sanitize_building_code(building_code)

            if building_code == "NOREQ" or not room_number:
                continue

            building_name = clean_building_name(s.get("building"), building_code)
            room_id = f"{building_code} {room_number}"

            for raw_day, weekday in DAY_MAP.items():
                if s.get(raw_day):
                    meetings.append(
                        OccupiedMeeting(
                            room_id=room_id,
                            building_code=building_code,
                            building_name=building_name,
                            room_number=room_number,
                            day=weekday,
                            start_time=start,
                            end_time=end,
                            valid_from=valid_from,
                            valid_to=valid_to,
                            capacity=capacity,
                        )
                    )

    return meetings