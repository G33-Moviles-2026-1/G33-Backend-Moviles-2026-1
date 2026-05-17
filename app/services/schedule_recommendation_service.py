from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoomNavAnchor, Weekday
from app.db.repositories.schedule_recommendations_repo import (
    UserRoomPreferenceSignal,
    fetch_user_room_preference_signals,
)
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

CAMPUS_START = time(5, 30)
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
    room_affinity_score: float = 0.0
    building_affinity_score: float = 0.0
    floor_affinity_score: float = 0.0
    capacity_affinity_score: float = 0.0
    room_penalty_score: float = 0.0
    reliability_score: float = 0.0
    score: float = 0.0


@dataclass(slots=True)
class LearnedPreferenceProfile:
    room_scores: dict[str, float]
    room_penalties: dict[str, float]
    building_scores: dict[str, float]
    floor_scores: dict[int, float]
    evidence_weight: float
    preferred_building: str | None
    preferred_floor: int | None
    preferred_capacity: float | None


@dataclass(slots=True)
class RecommendationWeights:
    from_previous: float
    to_next: float
    room_affinity: float
    building_affinity: float
    floor_affinity: float
    capacity_affinity: float
    reliability: float


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


def _extract_building_code(room_id: str | None) -> str | None:
    if not room_id:
        return None

    parts = room_id.strip().split()
    if not parts:
        return None

    return parts[0].upper()


def _capacity_similarity(
    candidate_capacity: int | None,
    preferred_capacity: float | None,
) -> float:
    if candidate_capacity is None or preferred_capacity is None:
        return 0.0

    max_capacity = max(float(candidate_capacity), preferred_capacity, 1.0)
    diff = abs(float(candidate_capacity) - preferred_capacity)
    return max(0.0, 1.0 - (diff / max_capacity))


def _normalize_score_map(raw: dict) -> dict:
    if not raw:
        return {}

    max_value = max(float(value) for value in raw.values())
    if max_value <= 0:
        return {key: 0.0 for key in raw}

    return {key: float(value) / max_value for key, value in raw.items()}


def _best_key(raw: dict) -> object | None:
    if not raw:
        return None

    return max(raw.items(), key=lambda item: (item[1], str(item[0])))[0]


def _add_room_signal(
    *,
    room_id: str | None,
    building_code: str | None,
    capacity: int | None,
    weight: float,
    room_scores: dict[str, float],
    building_scores: dict[str, float],
    floor_scores: dict[int, float],
    capacity_accumulator: list[float],
) -> None:
    if not room_id or weight <= 0:
        return

    normalized_room_id = room_id.strip().upper()
    if not normalized_room_id:
        return

    resolved_building = (building_code or _extract_building_code(room_id))
    if resolved_building:
        resolved_building = resolved_building.strip().upper()

    room_scores[normalized_room_id] = (
        room_scores.get(normalized_room_id, 0.0) + weight
    )

    if resolved_building:
        building_scores[resolved_building] = (
            building_scores.get(resolved_building, 0.0) + weight
        )

    floor = _infer_floor(room_id)
    if floor is not None:
        floor_scores[floor] = floor_scores.get(floor, 0.0) + weight

    if capacity is not None:
        capacity_accumulator.append(float(capacity) * weight)


def _build_learned_preference_profile(
    *,
    signals: list[UserRoomPreferenceSignal],
    all_classes,
    target_weekday: str,
) -> LearnedPreferenceProfile:
    room_scores: dict[str, float] = {}
    room_penalties: dict[str, float] = {}
    building_scores: dict[str, float] = {}
    floor_scores: dict[int, float] = {}
    capacity_weighted_values: list[float] = []
    capacity_total_weight = 0.0

    for signal in signals:
        if signal.weight < 0:
            normalized_room_id = signal.room_id.strip().upper()
            room_penalties[normalized_room_id] = (
                room_penalties.get(normalized_room_id, 0.0)
                + abs(signal.weight)
            )
            continue

        _add_room_signal(
            room_id=signal.room_id,
            building_code=signal.building_code,
            capacity=signal.capacity,
            weight=signal.weight,
            room_scores=room_scores,
            building_scores=building_scores,
            floor_scores=floor_scores,
            capacity_accumulator=capacity_weighted_values,
        )
        if signal.capacity is not None:
            capacity_total_weight += signal.weight

    for cls in all_classes:
        if not cls.room_id:
            continue

        schedule_weight = 1.35 if target_weekday in cls.weekdays else 0.7
        _add_room_signal(
            room_id=cls.room_id,
            building_code=getattr(cls, "building_code", None),
            capacity=None,
            weight=schedule_weight,
            room_scores=room_scores,
            building_scores=building_scores,
            floor_scores=floor_scores,
            capacity_accumulator=capacity_weighted_values,
        )

    evidence_weight = sum(room_scores.values())
    preferred_building = _best_key(building_scores)
    preferred_floor = _best_key(floor_scores)
    preferred_capacity = (
        sum(capacity_weighted_values) / capacity_total_weight
        if capacity_total_weight > 0
        else None
    )

    return LearnedPreferenceProfile(
        room_scores=_normalize_score_map(room_scores),
        room_penalties=_normalize_score_map(room_penalties),
        building_scores=_normalize_score_map(building_scores),
        floor_scores=_normalize_score_map(floor_scores),
        evidence_weight=evidence_weight,
        preferred_building=(
            str(preferred_building) if preferred_building is not None else None
        ),
        preferred_floor=(
            int(preferred_floor) if preferred_floor is not None else None
        ),
        preferred_capacity=preferred_capacity,
    )


def _derive_dynamic_weights(
    profile: LearnedPreferenceProfile,
) -> RecommendationWeights:
    confidence = min(1.0, profile.evidence_weight / 24.0)

    raw = {
        "from_previous": 0.34 - (0.08 * confidence),
        "to_next": 0.28 - (0.07 * confidence),
        "room_affinity": 0.08 + (0.22 * confidence),
        "building_affinity": 0.17 + (0.08 * confidence),
        "floor_affinity": 0.09 + (0.04 * confidence),
        "capacity_affinity": 0.04 + (0.03 * confidence),
        "reliability": 0.04 + (0.01 * (1.0 - confidence)),
    }

    total = sum(raw.values())
    if total <= 0:
        total = 1.0

    return RecommendationWeights(
        from_previous=raw["from_previous"] / total,
        to_next=raw["to_next"] / total,
        room_affinity=raw["room_affinity"] / total,
        building_affinity=raw["building_affinity"] / total,
        floor_affinity=raw["floor_affinity"] / total,
        capacity_affinity=raw["capacity_affinity"] / total,
        reliability=raw["reliability"] / total,
    )


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
    
    nav_service = NavigationService(db)

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

        prev_cost_map = await nav_service.get_dijkstra_map(prev_node) if prev_node else {}
        next_cost_map = await nav_service.get_dijkstra_map(next_node) if next_node else {}

        preference_signals = await fetch_user_room_preference_signals(
            db,
            user_email=user_email,
            weekday=weekday_str,
            slot_start=slot_start,
        )
        preference_profile = _build_learned_preference_profile(
            signals=preference_signals,
            all_classes=all_classes,
            target_weekday=weekday_str,
        )
        recommendation_weights = _derive_dynamic_weights(preference_profile)

        frequent_building = (
            preference_profile.preferred_building
            or _extract_frequent_building(classes_for_day)
        )
        frequent_floor = (
            preference_profile.preferred_floor
            if preference_profile.preferred_floor is not None
            else _extract_frequent_floor(classes_for_day)
        )

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
            candidate_building = _extract_building_code(
                normalized_candidate_room_id
            )

            from_previous = None
            if prev_node and candidate_node:
                from_previous = prev_cost_map.get(candidate_node)

            to_next = None
            if next_node and candidate_node:
                to_next = next_cost_map.get(candidate_node)

            room_affinity_score = preference_profile.room_scores.get(
                normalized_candidate_room_id.upper(), 0.0
            )
            room_penalty_score = preference_profile.room_penalties.get(
                normalized_candidate_room_id.upper(), 0.0
            )
            building_affinity_score = (
                preference_profile.building_scores.get(candidate_building, 0.0)
                if candidate_building
                else 0.0
            )
            floor_affinity_score = (
                preference_profile.floor_scores.get(candidate_floor, 0.0)
                if candidate_floor is not None
                else 0.0
            )
            capacity_affinity_score = _capacity_similarity(
                r.capacity,
                preference_profile.preferred_capacity,
            )
            reliability_score = (
                max(0.0, min(float(r.reliability or 0.0), 100.0)) / 100.0
            )

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
                    room_affinity_score=room_affinity_score,
                    building_affinity_score=building_affinity_score,
                    floor_affinity_score=floor_affinity_score,
                    capacity_affinity_score=capacity_affinity_score,
                    room_penalty_score=room_penalty_score,
                    reliability_score=reliability_score,
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
            weighted_sum = 0.0
            total_weight = 0.0

            if previous_cls is not None:
                weighted_sum += recommendation_weights.from_previous * prev_scores[idx]
                total_weight += recommendation_weights.from_previous

            if next_cls is not None:
                weighted_sum += recommendation_weights.to_next * next_scores[idx]
                total_weight += recommendation_weights.to_next

            weighted_sum += recommendation_weights.room_affinity * c.room_affinity_score
            total_weight += recommendation_weights.room_affinity

            weighted_sum -= (
                recommendation_weights.room_affinity
                * 0.65
                * c.room_penalty_score
            )

            weighted_sum += (
                recommendation_weights.building_affinity
                * c.building_affinity_score
            )
            total_weight += recommendation_weights.building_affinity

            weighted_sum += recommendation_weights.floor_affinity * c.floor_affinity_score
            total_weight += recommendation_weights.floor_affinity

            weighted_sum += (
                recommendation_weights.capacity_affinity
                * c.capacity_affinity_score
            )
            total_weight += recommendation_weights.capacity_affinity

            weighted_sum += recommendation_weights.reliability * c.reliability_score
            total_weight += recommendation_weights.reliability

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
