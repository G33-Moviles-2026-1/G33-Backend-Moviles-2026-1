from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoomNavAnchor, Weekday
from app.db.repositories.schedule_repo import (
    fetch_rooms_for_windows,
    get_active_schedule_id,
    get_classes_with_weekdays,
)
from app.schemas.schedule import (
    RecommendedRoomOut,
    RoomRecommendationReasonOut,
    SlotRoomRecommendationsOut,
    DayRoomRecommendationsOut,
)
from app.services.navigation_service import NavigationService

BOGOTA_TZ = ZoneInfo("America/Bogota")

CAMPUS_START = time(6, 0)
CAMPUS_END = time(22, 0)
MIN_FREE_SLOT_MINUTES = 30

_PYTHON_WEEKDAY_MAP: dict[int, str] = {
    0: "monday",
    1: "tuesday",
    2: "wednesday",
    3: "thursday",
    4: "friday",
    5: "saturday",
    6: "sunday",
}

_DB_WEEKDAY: dict[str, Weekday] = {w.value: w for w in Weekday}

WEIGHT_FROM_PREVIOUS = 0.35
WEIGHT_TO_NEXT = 0.30
WEIGHT_BUILDING = 0.20
WEIGHT_FLOOR = 0.15


@dataclass(slots=True)
class CandidateRoom:
    room_id: str
    building_name: str | None
    capacity: int
    reliability: float
    from_previous_seconds: float | None
    to_next_seconds: float | None
    matches_frequent_building: bool
    matches_frequent_floor: bool
    score: float = 0.0


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _compute_free_slots(
    occupied: list[tuple[time, time]],
) -> list[tuple[time, time]]:
    if not occupied:
        return [(CAMPUS_START, CAMPUS_END)]

    occupied_sorted = sorted(occupied, key=lambda x: x[0])

    merged: list[tuple[time, time]] = [occupied_sorted[0]]
    for s, e in occupied_sorted[1:]:
        last_s, last_e = merged[-1]
        if s <= last_e:
            merged[-1] = (last_s, max(last_e, e))
        else:
            merged.append((s, e))

    free: list[tuple[time, time]] = []
    cursor = CAMPUS_START
    for occ_start, occ_end in merged:
        if occ_start > cursor:
            free.append((cursor, occ_start))
        cursor = max(cursor, occ_end)

    if cursor < CAMPUS_END:
        free.append((cursor, CAMPUS_END))

    return [
        (s, e)
        for s, e in free
        if _time_to_minutes(e) - _time_to_minutes(s) >= MIN_FREE_SLOT_MINUTES
    ]


def _infer_floor(room_id: str | None) -> int | None:
    """
    Ejemplos:
    'ML 515' -> 5
    'SD 203' -> 2
    """
    if not room_id:
        return None

    parts = room_id.strip().split()
    if len(parts) < 2:
        return None

    room_number = parts[-1]
    if not room_number or not room_number[0].isdigit():
        return None

    return int(room_number[0])


def _normalize_inverse(values: list[float | None]) -> list[float]:
    """
    Menor distancia => mayor score.
    None => 0.
    """
    existing = [v for v in values if v is not None]
    if not existing:
        return [0.0 for _ in values]

    min_v = min(existing)
    max_v = max(existing)

    if min_v == max_v:
        return [1.0 if v is not None else 0.0 for v in values]

    out: list[float] = []
    for v in values:
        if v is None:
            out.append(0.0)
        else:
            norm = (max_v - v) / (max_v - min_v)
            out.append(norm)
    return out


def _find_previous_and_next_classes(classes_for_day, slot_start: time, slot_end: time):
    previous_cls = None
    next_cls = None

    for cls in classes_for_day:
        if cls.end_time <= slot_start:
            if previous_cls is None or cls.end_time > previous_cls.end_time:
                previous_cls = cls

        if cls.start_time >= slot_end:
            if next_cls is None or cls.start_time < next_cls.start_time:
                next_cls = cls

    return previous_cls, next_cls


def _extract_frequent_building(classes_for_day) -> str | None:
    counts: dict[str, int] = {}
    for cls in classes_for_day:
        if cls.room_id:
            building = cls.room_id.split()[0]
            counts[building] = counts.get(building, 0) + 1
        elif getattr(cls, "building_code", None):
            counts[cls.building_code] = counts.get(cls.building_code, 0) + 1

    if not counts:
        return None

    return max(counts.items(), key=lambda x: x[1])[0]


def _extract_frequent_floor(classes_for_day) -> int | None:
    counts: dict[int, int] = {}
    for cls in classes_for_day:
        floor = _infer_floor(cls.room_id)
        if floor is not None:
            counts[floor] = counts.get(floor, 0) + 1

    if not counts:
        return None

    return max(counts.items(), key=lambda x: x[1])[0]


async def _load_room_anchor_map(db: AsyncSession) -> dict[str, uuid.UUID]:
    result = await db.execute(select(RoomNavAnchor))
    anchors = result.scalars().all()
    return {a.room_id: a.node_id for a in anchors}


async def get_room_recommendations_for_day(
    db: AsyncSession,
    *,
    user_email: str,
    target_date: date,
    top_k: int = 3,
) -> DayRoomRecommendationsOut:
    schedule_id = await get_active_schedule_id(db, user_email)
    if schedule_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No schedule found for this user. Upload one first.",
        )

    all_classes = await get_classes_with_weekdays(db, schedule_id)
    weekday_str = _PYTHON_WEEKDAY_MAP[target_date.weekday()]
    db_weekday = _DB_WEEKDAY[weekday_str]

    classes_for_day = [
        cls
        for cls in all_classes
        if weekday_str in cls.weekdays and cls.start_date <= target_date <= cls.end_date
    ]
    classes_for_day.sort(key=lambda c: c.start_time)

    occupied = [(cls.start_time, cls.end_time) for cls in classes_for_day]
    free_slots = _compute_free_slots(occupied)

    if not free_slots:
        return DayRoomRecommendationsOut(
            date=target_date,
            weekday=weekday_str,
            slots=[],
        )

    room_anchor_map = await _load_room_anchor_map(db)

    slot_results: list[SlotRoomRecommendationsOut] = []

    for slot_start, slot_end in free_slots:
        previous_cls, next_cls = _find_previous_and_next_classes(
            classes_for_day, slot_start, slot_end
        )

        prev_node = (
            room_anchor_map.get(previous_cls.room_id)
            if previous_cls and previous_cls.room_id
            else None
        )
        next_node = (
            room_anchor_map.get(next_cls.room_id)
            if next_cls and next_cls.room_id
            else None
        )

        prev_cost_map = await get_dijkstra_map(db, prev_node) if prev_node else {}
        next_cost_map = await get_dijkstra_map(db, next_node) if next_node else {}

        frequent_building = _extract_frequent_building(classes_for_day)
        frequent_floor = _extract_frequent_floor(classes_for_day)

        room_rows = await fetch_rooms_for_windows(
            db,
            weekday=db_weekday,
            target_date=target_date,
            windows=[(slot_start, slot_end)],
        )

        grouped_candidates: dict[str, CandidateRoom] = {}

        for r in room_rows:
            normalized_candidate_room_id = r.room_id

            overlap_start = max(r.rule_start, slot_start)
            overlap_end = min(r.rule_end, slot_end)

            overlap_minutes = (
                (overlap_end.hour * 60 + overlap_end.minute)
                - (overlap_start.hour * 60 + overlap_start.minute)
            )

            if overlap_minutes < MIN_FREE_SLOT_MINUTES:
                continue

            candidate_node = room_anchor_map.get(normalized_candidate_room_id)
            candidate_floor = _infer_floor(normalized_candidate_room_id)
            candidate_building = (
                normalized_candidate_room_id.split()[0]
                if normalized_candidate_room_id
                else None
            )

            from_previous = None
            if prev_node and candidate_node:
                from_previous = prev_cost_map.get(candidate_node)

            to_next = None
            if next_node and candidate_node:
                to_next = next_cost_map.get(candidate_node)

            if normalized_candidate_room_id not in grouped_candidates:
                grouped_candidates[normalized_candidate_room_id] = CandidateRoom(
                    room_id=normalized_candidate_room_id,
                    building_name=r.building_name,
                    capacity=r.capacity,
                    reliability=r.reliability,
                    from_previous_seconds=from_previous,
                    to_next_seconds=to_next,
                    matches_frequent_building=(
                        frequent_building is not None
                        and candidate_building == frequent_building
                    ),
                    matches_frequent_floor=(
                        frequent_floor is not None
                        and candidate_floor == frequent_floor
                    ),
                )

        candidates = list(grouped_candidates.values())

        if not candidates:
            slot_results.append(
                SlotRoomRecommendationsOut(
                    slot_start=slot_start,
                    slot_end=slot_end,
                    recommended_rooms=[],
                )
            )
            continue

        prev_scores = _normalize_inverse(
            [c.from_previous_seconds for c in candidates]
        )
        next_scores = _normalize_inverse(
            [c.to_next_seconds for c in candidates]
        )

        for idx, c in enumerate(candidates):
            building_score = 1.0 if c.matches_frequent_building else 0.0
            floor_score = 1.0 if c.matches_frequent_floor else 0.0

            weighted_sum = 0.0
            total_weight = 0.0

            if previous_cls is not None:
                weighted_sum += WEIGHT_FROM_PREVIOUS * prev_scores[idx]
                total_weight += WEIGHT_FROM_PREVIOUS

            if next_cls is not None:
                weighted_sum += WEIGHT_TO_NEXT * next_scores[idx]
                total_weight += WEIGHT_TO_NEXT

            weighted_sum += WEIGHT_BUILDING * building_score
            total_weight += WEIGHT_BUILDING

            weighted_sum += WEIGHT_FLOOR * floor_score
            total_weight += WEIGHT_FLOOR

            c.score = weighted_sum / total_weight if total_weight > 0 else 0.0

        candidates.sort(
            key=lambda c: (
                -c.score,
                -(c.reliability or 0.0),
                c.from_previous_seconds is None,
                c.from_previous_seconds
                if c.from_previous_seconds is not None
                else float("inf"),
                c.room_id,
            )
        )

        recommended = [
            RecommendedRoomOut(
                room_id=c.room_id,
                building_name=c.building_name,
                capacity=c.capacity,
                reliability=c.reliability,
                score=round(c.score, 4),
                from_previous_seconds=c.from_previous_seconds,
                to_next_seconds=c.to_next_seconds,
                matches_frequent_building=c.matches_frequent_building,
                matches_frequent_floor=c.matches_frequent_floor,
                reasons=RoomRecommendationReasonOut(
                    near_previous_class=c.from_previous_seconds is not None,
                    near_next_class=c.to_next_seconds is not None,
                    frequent_building_match=c.matches_frequent_building,
                    frequent_floor_match=c.matches_frequent_floor,
                ),
            )
            for c in candidates[:top_k]
        ]

        slot_results.append(
            SlotRoomRecommendationsOut(
                slot_start=slot_start,
                slot_end=slot_end,
                recommended_rooms=recommended,
            )
        )

    return DayRoomRecommendationsOut(
        date=target_date,
        weekday=weekday_str,
        slots=slot_results,
    )