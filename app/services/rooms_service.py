from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_rules import get_operating_hours
from app.db.models import RoomNavAnchor, UtilityType, Weekday
from app.db.repositories.bookings_repo import (
    UserBookedRoomPreference,
    list_user_room_preferences,
)
from app.db.repositories.rooms_repo import (
    fetch_room_base_info,
    fetch_room_daily_slots,
    fetch_room_search_rows,
)
from app.services.navigation_service import NavigationService
from app.schemas.rooms import (
    RoomDateAvailabilityOut,
    RoomDateAvailabilitySlotOut,
    RoomSearchItemOut,
    RoomSearchQueryOut,
    RoomSearchRequest,
    RoomSearchResponse,
    TimeWindowOut,
)

BOGOTA_TZ = ZoneInfo("America/Bogota")

WEEKDAY_MAP = {
    0: Weekday.monday,
    1: Weekday.tuesday,
    2: Weekday.wednesday,
    3: Weekday.thursday,
    4: Weekday.friday,
    5: Weekday.saturday,
    6: Weekday.sunday,
}

BUILDING_WEIGHT = 0.35
FLOOR_WEIGHT = 0.15
CAPACITY_WEIGHT = 0.10
UTILITY_WEIGHT = 0.20
AVAILABILITY_WEIGHT = 0.20


def _infer_floor(room_id: str | None) -> int | None:
    """
    Same idea already used in recommendation_service:
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


def _capacity_similarity(candidate_capacity: int | None, booked_capacity: int | None) -> float:
    if candidate_capacity is None or booked_capacity is None:
        return 0.0

    max_capacity = max(candidate_capacity, booked_capacity, 1)
    diff = abs(candidate_capacity - booked_capacity)
    return max(0.0, 1.0 - (diff / max_capacity))


def _utilities_similarity(
    candidate_utilities: list[UtilityType],
    booked_utilities: list[UtilityType],
) -> float:
    candidate_set = set(candidate_utilities)
    booked_set = set(booked_utilities)
    if not candidate_set or not booked_set:
        return 0.0

    union_count = len(candidate_set | booked_set)
    if union_count == 0:
        return 0.0

    return len(candidate_set & booked_set) / union_count


def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _window_overlap_ratio(
    candidate_start: time,
    candidate_end: time,
    pref_start: time,
    pref_end: time,
) -> float:
    start = max(_time_to_minutes(candidate_start), _time_to_minutes(pref_start))
    end = min(_time_to_minutes(candidate_end), _time_to_minutes(pref_end))
    overlap = max(0, end - start)
    candidate_minutes = max(1, _time_to_minutes(candidate_end) - _time_to_minutes(candidate_start))
    return overlap / candidate_minutes


def _availability_similarity(
    candidate_windows: list[TimeWindowOut],
    pref_windows: list[tuple[Weekday, time, time]],
    weekday: Weekday,
) -> float:
    if not candidate_windows:
        return 0.0

    same_day_pref = [(start, end) for day, start, end in pref_windows if day == weekday]
    if not same_day_pref:
        return 0.0

    per_window_scores: list[float] = []
    for candidate in candidate_windows:
        best = 0.0
        for pref_start, pref_end in same_day_pref:
            best = max(
                best,
                _window_overlap_ratio(
                    candidate.start,
                    candidate.end,
                    pref_start,
                    pref_end,
                ),
            )
        per_window_scores.append(best)

    return sum(per_window_scores) / len(per_window_scores) if per_window_scores else 0.0


def _compute_interest_score(
    item: dict,
    preferences: list[UserBookedRoomPreference],
    *,
    weekday: Weekday,
) -> float:
    if not preferences:
        return 0.0

    candidate_floor = _infer_floor(item["room_id"])

    weighted_sum = 0.0
    total_weight = 0

    for pref in preferences:
        booked_floor = _infer_floor(pref.room_id)

        same_building = item["building_code"] == pref.building_code
        same_floor = (
            candidate_floor is not None
            and booked_floor is not None
            and candidate_floor == booked_floor
        )
        capacity_score = _capacity_similarity(item["capacity"], pref.capacity)
        utilities_score = _utilities_similarity(item["utilities"], pref.utilities)
        availability_score = _availability_similarity(
            item["matching_windows"],
            pref.availability_windows,
            weekday,
        )

        score = (
            BUILDING_WEIGHT * (1.0 if same_building else 0.0)
            + FLOOR_WEIGHT * (1.0 if same_floor else 0.0)
            + CAPACITY_WEIGHT * capacity_score
            + UTILITY_WEIGHT * utilities_score
            + AVAILABILITY_WEIGHT * availability_score
        )

        weighted_sum += score * pref.booking_count
        total_weight += pref.booking_count

    return weighted_sum / total_weight if total_weight > 0 else 0.0

@dataclass(slots=True)
class ResolvedSearchParams:
    room_prefixes: list[str]
    date: date
    since: time
    until: time
    building_codes: list[str]
    utilities: list[UtilityType]
    near_me: bool
    user_location: object | None
    limit: int
    offset: int
    weekday: Weekday

# --- LÓGICA DE DISPONIBILIDAD INDIVIDUAL ---

async def get_room_date_availability(
    db: AsyncSession,
    *,
    room_id: str,
    target_date: date,
) -> RoomDateAvailabilityOut:
    today = _current_bogota_datetime().date()
    max_allowed = today + timedelta(days=7)

    if target_date < today or target_date > max_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date must be between today and the next 7 days",
        )

    weekday = WEEKDAY_MAP[target_date.weekday()]
    room = await fetch_room_base_info(db, room_id=room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="room was not found")

    operating_hours = get_operating_hours(weekday)
    if operating_hours is None:
        return RoomDateAvailabilityOut(
            **_map_room_base_to_dict(room, target_date, weekday),
            available_slots=[], blocked_slots=[],
        )

    available_slots, blocked_slots = await fetch_room_daily_slots(
        db, room_id=room_id, target_date=target_date, weekday=weekday,
    )

    return RoomDateAvailabilityOut(
        **_map_room_base_to_dict(room, target_date, weekday),
        available_slots=[RoomDateAvailabilitySlotOut(start=s.start_time, end=s.end_time, is_available=True) for s in available_slots],
        blocked_slots=[RoomDateAvailabilitySlotOut(start=s.start_time, end=s.end_time, is_available=False) for s in blocked_slots],
    )

def _map_room_base_to_dict(room, target_date, weekday):
    return {
        "room_id": room.room_id, "date": target_date, "weekday": weekday,
        "building_code": room.building_code, "building_name": room.building_name,
        "room_number": room.room_number, "capacity": room.capacity,
        "reliability": room.reliability, "utilities": [u.value for u in room.utilities],
    }

# --- LÓGICA DE NORMALIZACIÓN Y RESOLUCIÓN ---

def _normalize_text_token(value: str) -> str:
    value = re.sub(r'([A-Za-z])(\d)', r'\1 \2', value.replace("-", " "))
    return " ".join(value.upper().split())

def _normalize_prefixes(payload: RoomSearchRequest) -> list[str]:
    candidates = ([payload.room_prefix] if payload.room_prefix else []) + payload.room_prefixes
    normalized = []
    for val in candidates:
        cleaned = _normalize_text_token(val)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized

def _current_bogota_datetime() -> datetime:
    return datetime.now(BOGOTA_TZ)

def _resolve_time_window(target_date: date, weekday: Weekday, since: time | None, until: time | None) -> tuple[time, time]:
    if since is None and until is None:
        raise HTTPException(status_code=400, detail="at least one of since or until must be provided")
    
    op_hours = get_operating_hours(weekday)
    if op_hours is None:
        raise HTTPException(status_code=400, detail="campus is closed on sunday")
    
    open_t, close_t = op_hours
    if since is None:
        now = _current_bogota_datetime()
        since = max(time(now.hour, now.minute) if target_date == now.date() else open_t, open_t)
    if until is None:
        until = close_t

    if not (open_t <= since <= close_t) or not (open_t <= until <= close_t):
        raise HTTPException(status_code=400, detail=f"since/until must be between {open_t} and {close_t}")
    if since >= until:
        raise HTTPException(status_code=400, detail="since must be earlier than until")
    
    return since, until

def resolve_room_search_request(payload: RoomSearchRequest) -> ResolvedSearchParams:
    today = _current_bogota_datetime().date()
    if not (today <= payload.date <= today + timedelta(days=7)):
        raise HTTPException(status_code=400, detail="date must be within the next 7 days")
    
    if payload.near_me and payload.user_location is None:
        raise HTTPException(status_code=400, detail="user_location is required for near_me")

    weekday = WEEKDAY_MAP[payload.date.weekday()]
    since, until = _resolve_time_window(payload.date, weekday, payload.since, payload.until)

    return ResolvedSearchParams(
        room_prefixes=_normalize_prefixes(payload),
        date=payload.date, since=since, until=until,
        building_codes=list(dict.fromkeys(_normalize_text_token(c) for c in payload.building_codes if c)),
        utilities=payload.utilities, near_me=payload.near_me,
        user_location=payload.user_location, limit=payload.limit,
        offset=payload.offset, weekday=weekday,
    )

# --- SERVICIO PRINCIPAL ---

async def search_rooms(
    db: AsyncSession,
    payload: RoomSearchRequest,
    *,
    user_email: str | None = None,
) -> RoomSearchResponse:
    resolved = resolve_room_search_request(payload)
    nav_service = NavigationService(db) # Instanciamos el servicio espacial

    rows = await fetch_room_search_rows(
        db, target_date=resolved.date, weekday=resolved.weekday,
        since=resolved.since, until=resolved.until,
        room_prefixes=resolved.room_prefixes,
        building_codes=resolved.building_codes, utilities=resolved.utilities,
    )

    user_preferences: list[UserBookedRoomPreference] = []
    if not resolved.near_me and user_email:
        user_preferences = await list_user_room_preferences(
            db,
            user_email=user_email,
        )

    grouped: dict[str, dict] = {}
    for row in rows:
        if row.room_id not in grouped:
            grouped[row.room_id] = {
                "room_id": row.room_id,
                "building_code": row.building_code,
                "building_name": row.building_name,
                "room_number": row.room_number,
                "capacity": row.capacity,
                "reliability": row.reliability,
                "utilities": row.utilities,
                "distance_seconds": None,
                "matching_windows": [],
                "_earliest_start": row.rule_start_time,
                "_interest_score": 0.0,
            }

        window = TimeWindowOut(start=row.rule_start_time, end=row.rule_end_time)
        if window not in grouped[row.room_id]["matching_windows"]:
            grouped[row.room_id]["matching_windows"].append(window)

    # --- LÓGICA DE CERCANÍA REFACTORIZADA ---
    if resolved.near_me and resolved.user_location:
        # 1. Encontrar nodo origen (Centralizado)
        start_node = await nav_service.find_nearest_node(
            resolved.user_location.latitude, 
            resolved.user_location.longitude
        )
        # 2. Obtener mapa de costos (Centralizado)
        cost_map = await nav_service.get_dijkstra_map(start_node.id)
        
        # 3. Mapear salones a nodos (Optimizado)
        anchors_res = await db.execute(select(RoomNavAnchor))
        room_to_node = {a.room_id: a.node_id for a in anchors_res.scalars().all()}

        for rid, item in grouped.items():
            target_node_id = room_to_node.get(rid)
            if target_node_id:
                item["distance_seconds"] = cost_map.get(target_node_id)

    # --- SORTING Y PAGINACIÓN ---
    items = list(grouped.values())

    if resolved.near_me:
        sort_key = lambda x: (
            x["distance_seconds"] is None,
            x["distance_seconds"] or float("inf"),
            -x["reliability"],
        )
    else:
        if user_preferences:
            for item in items:
                item["_interest_score"] = _compute_interest_score(
                    item,
                    user_preferences,
                    weekday=resolved.weekday,
                )

            sort_key = lambda x: (
                -x["_interest_score"],
                -x["reliability"],
                x["room_id"],
            )
        else:
            sort_key = lambda x: (
                -x["reliability"],
                x["room_id"],
            )

    items.sort(key=sort_key)

    paginated = items[resolved.offset : resolved.offset + resolved.limit]

    response_items = [
        RoomSearchItemOut(
            **{k: v for k, v in item.items() if not k.startswith("_") and k not in ["distance_seconds", "matching_windows"]},
            distance_seconds=item["distance_seconds"],
            matching_windows=sorted(item["matching_windows"], key=lambda w: w.start),
        ) for item in paginated
    ]

    return RoomSearchResponse(
        query=RoomSearchQueryOut(**asdict(resolved)),
        total=len(items),
        items=response_items
    )