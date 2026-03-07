from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable

from app.integrations.uniandes.parser import (
    APP_DAY_END,
    APP_DAY_START,
    OccupiedMeeting,
    normalize_meetings,
)

RULES_WINDOW_START = date(2026, 1, 19)
RULES_WINDOW_END = date(2026, 5, 24)

@dataclass(frozen=True)
class BuildingSeed:
    code: str
    name: str


@dataclass(frozen=True)
class RoomSeed:
    room_id: str
    building_code: str
    room_number: str
    building_name: str
    capacity: int


@dataclass(frozen=True)
class AvailabilityRuleSeed:
    term_id: str
    room_id: str
    day: str
    start_time: time
    end_time: time
    valid_from: date
    valid_to: date


@dataclass(frozen=True)
class IngestSnapshot:
    term_id: str
    term_start: date
    term_end: date
    raw_courses_count: int
    normalized_meetings_count: int
    buildings: list[BuildingSeed]
    rooms: list[RoomSeed]
    rules: list[AvailabilityRuleSeed]


WEEKDAYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_time(m: int) -> time:
    return time(hour=m // 60, minute=m % 60)


def _is_inside_rules_window(valid_from: date, valid_to: date) -> bool:
    return valid_from >= RULES_WINDOW_START and valid_to <= RULES_WINDOW_END


def _is_long_enough_rule(valid_from: date, valid_to: date) -> bool:
    return (valid_to - valid_from).days > 39


def _split_interval(start: time, end: time) -> list[tuple[time, time]]:
    """Split a free interval into 90-min blocks, keeping final remainder only if > 15 min."""
    start_m = _time_to_minutes(start)
    end_m = _time_to_minutes(end)
    total = end_m - start_m
    if total <= 15:
        return []

    out: list[tuple[time, time]] = []
    cursor = start_m

    while (end_m - cursor) > 90:
        out.append((_minutes_to_time(cursor), _minutes_to_time(cursor + 90)))
        cursor += 90

    remainder = end_m - cursor
    if remainder > 15:
        out.append((_minutes_to_time(cursor), _minutes_to_time(end_m)))

    return out


def _merge_intervals(intervals: list[tuple[time, time]]) -> list[tuple[time, time]]:
    if not intervals:
        return []

    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [intervals[0]]

    for current_start, current_end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if current_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, current_end))
        else:
            merged.append((current_start, current_end))

    return merged


def _free_intervals_from_occupied(occupied: list[tuple[time, time]]) -> list[tuple[time, time]]:
    occupied = _merge_intervals(occupied)

    free: list[tuple[time, time]] = []
    cursor = APP_DAY_START

    for occ_start, occ_end in occupied:
        if occ_start > cursor:
            free.append((cursor, occ_start))
        cursor = max(cursor, occ_end)

    if cursor < APP_DAY_END:
        free.append((cursor, APP_DAY_END))

    return free


def _compress_rules(rules: list[AvailabilityRuleSeed]) -> list[AvailabilityRuleSeed]:
    if not rules:
        return []

    rules = sorted(
        rules,
        key=lambda r: (r.room_id, r.day, r.start_time, r.end_time, r.valid_from, r.valid_to),
    )

    compressed: list[AvailabilityRuleSeed] = [rules[0]]

    for rule in rules[1:]:
        prev = compressed[-1]
        contiguous = rule.valid_from == (prev.valid_to + timedelta(days=1))
        same_shape = (
            rule.room_id == prev.room_id
            and rule.day == prev.day
            and rule.start_time == prev.start_time
            and rule.end_time == prev.end_time
            and rule.term_id == prev.term_id
        )

        if same_shape and contiguous:
            compressed[-1] = AvailabilityRuleSeed(
                term_id=prev.term_id,
                room_id=prev.room_id,
                day=prev.day,
                start_time=prev.start_time,
                end_time=prev.end_time,
                valid_from=prev.valid_from,
                valid_to=rule.valid_to,
            )
        else:
            compressed.append(rule)

    return compressed


def _build_rules_for_room_day(
    room_id: str,
    day: str,
    meetings: list[OccupiedMeeting],
    term_id: str,
    term_start: date,
    term_end: date,
) -> list[AvailabilityRuleSeed]:
    if not meetings:
        # Room has no classes this weekday at all -> free all day for full term
        full_day_chunks = _split_interval(APP_DAY_START, APP_DAY_END)
        return [
            AvailabilityRuleSeed(
                term_id=term_id,
                room_id=room_id,
                day=day,
                start_time=s,
                end_time=e,
                valid_from=term_start,
                valid_to=term_end,
            )
            for s, e in full_day_chunks
        ]

    cut_points = {term_start, term_end + timedelta(days=1)}
    for m in meetings:
        cut_points.add(m.valid_from)
        cut_points.add(m.valid_to + timedelta(days=1))

    sorted_points = sorted(cut_points)
    rules: list[AvailabilityRuleSeed] = []

    for i in range(len(sorted_points) - 1):
        seg_start = sorted_points[i]
        seg_end_exclusive = sorted_points[i + 1]
        seg_end = seg_end_exclusive - timedelta(days=1)
        if seg_end < seg_start:
            continue

        active = [m for m in meetings if m.valid_from <= seg_start <= m.valid_to]
        occupied = [(m.start_time, m.end_time) for m in active]
        free = _free_intervals_from_occupied(occupied)

        for free_start, free_end in free:
            for chunk_start, chunk_end in _split_interval(free_start, free_end):
                if _is_inside_rules_window(seg_start, seg_end) and _is_long_enough_rule(seg_start, seg_end):
                    rules.append(
                        AvailabilityRuleSeed(
                            term_id=term_id,
                            room_id=room_id,
                            day=day,
                            start_time=chunk_start,
                            end_time=chunk_end,
                            valid_from=seg_start,
                            valid_to=seg_end,
                        )
                    )

    return _compress_rules(rules)


def build_ingest_snapshot(raw_courses: list[dict], term_id: str) -> IngestSnapshot:
    meetings = normalize_meetings(raw_courses, term_id)
    if not meetings:
        raise ValueError(f"No meetings found for term {term_id}")

    term_start = min(m.valid_from for m in meetings)
    term_end = max(m.valid_to for m in meetings)

    buildings_map: dict[str, BuildingSeed] = {}
    rooms_map: dict[str, RoomSeed] = {}

    for m in meetings:
        buildings_map[m.building_code] = BuildingSeed(code=m.building_code, name=m.building_name)

        prev = rooms_map.get(m.room_id)
        if prev is None:
            rooms_map[m.room_id] = RoomSeed(
                room_id=m.room_id,
                building_code=m.building_code,
                room_number=m.room_number,
                building_name=m.building_name,
                capacity=m.capacity,
            )
        else:
            rooms_map[m.room_id] = RoomSeed(
                room_id=prev.room_id,
                building_code=prev.building_code,
                room_number=prev.room_number,
                building_name=prev.building_name,
                capacity=max(prev.capacity, m.capacity),
            )

    meetings_by_room_day: dict[tuple[str, str], list[OccupiedMeeting]] = defaultdict(list)
    for m in meetings:
        meetings_by_room_day[(m.room_id, m.day)].append(m)

    all_rules: list[AvailabilityRuleSeed] = []
    for room_id in rooms_map.keys():
        for day in WEEKDAYS:
            group = meetings_by_room_day.get((room_id, day), [])
            all_rules.extend(
                _build_rules_for_room_day(
                    room_id=room_id,
                    day=day,
                    meetings=group,
                    term_id=term_id,
                    term_start=term_start,
                    term_end=term_end,
                )
            )

    return IngestSnapshot(
        term_id=term_id,
        term_start=term_start,
        term_end=term_end,
        raw_courses_count=len(raw_courses),
        normalized_meetings_count=len(meetings),
        buildings=sorted(buildings_map.values(), key=lambda b: b.code),
        rooms=sorted(rooms_map.values(), key=lambda r: r.room_id),
        rules=all_rules,
    )