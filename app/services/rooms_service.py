from __future__ import annotations

import heapq
import uuid
from dataclasses import dataclass, asdict
from datetime import date, datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_rules import get_operating_hours
from app.db.models import NavEdge, NavNode, RoomNavAnchor, UtilityType, Weekday
from app.db.repositories.rooms_repo import (
    fetch_room_base_info,
    fetch_room_daily_slots,
    fetch_room_search_rows,
)
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

# --- UTILIDADES DE NAVEGACIÓN ---

async def get_dijkstra_map(db: AsyncSession, start_node_id: uuid.UUID) -> dict[uuid.UUID, float]:
    """Calcula el costo mínimo en segundos desde un nodo hacia todos los demás."""
    result = await db.execute(select(NavEdge))
    edges = result.scalars().all()

    graph = {}
    for edge in edges:
        if edge.from_node_id not in graph:
            graph[edge.from_node_id] = []
        graph[edge.from_node_id].append((edge.to_node_id, edge.weight_seconds))

    distances = {start_node_id: 0.0}
    priority_queue = [(0.0, start_node_id)]
    visited = set()

    while priority_queue:
        current_distance, current_node = heapq.heappop(priority_queue)
        if current_node in visited:
            continue
        visited.add(current_node)

        for neighbor, weight in graph.get(current_node, []):
            distance = current_distance + weight
            if distance < distances.get(neighbor, float('inf')):
                distances[neighbor] = distance
                heapq.heappush(priority_queue, (distance, neighbor))
    return distances

def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6371000.0
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2)**2
    return earth_radius_m * 2 * asin(sqrt(a))

async def _find_closest_node(db: AsyncSession, lat: float, lon: float) -> uuid.UUID:
    result = await db.execute(select(NavNode))
    nodes = result.scalars().all()
    if not nodes:
        raise HTTPException(status_code=500, detail="No navigation nodes found in database")
    return min(nodes, key=lambda n: _haversine_meters(lat, lon, n.lat, n.lon)).id

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
    return " ".join(value.replace("-", " ").upper().split())

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

async def search_rooms(db: AsyncSession, payload: RoomSearchRequest) -> RoomSearchResponse:
    resolved = resolve_room_search_request(payload)

    rows = await fetch_room_search_rows(
        db, target_date=resolved.date, weekday=resolved.weekday,
        since=resolved.since, until=resolved.until,
        room_prefixes=resolved.room_prefixes,
        building_codes=resolved.building_codes, utilities=resolved.utilities,
    )

    grouped: dict[uuid.UUID, dict] = {}
    for row in rows:
        if row.room_id not in grouped:
            grouped[row.room_id] = {
                "room_id": row.room_id, "building_code": row.building_code,
                "building_name": row.building_name, "room_number": row.room_number,
                "capacity": row.capacity, "reliability": row.reliability,
                "utilities": row.utilities, "distance_seconds": None,
                "matching_windows": [], "_earliest_start": row.rule_start_time
            }
        
        window = TimeWindowOut(start=row.rule_start_time, end=row.rule_end_time)
        if window not in grouped[row.room_id]["matching_windows"]:
            grouped[row.room_id]["matching_windows"].append(window)
        if row.rule_start_time < grouped[row.room_id]["_earliest_start"]:
            grouped[row.room_id]["_earliest_start"] = row.rule_start_time

    if resolved.near_me and resolved.user_location:
        start_node_id = await _find_closest_node(db, resolved.user_location.latitude, resolved.user_location.longitude)
        cost_map = await get_dijkstra_map(db, start_node_id)
        anchors_res = await db.execute(select(RoomNavAnchor))
        room_to_node = {a.room_id: a.node_id for a in anchors_res.scalars().all()}

        for rid, item in grouped.items():
            target_node_id = room_to_node.get(rid)
            if target_node_id:
                item["distance_seconds"] = cost_map.get(target_node_id)

    items = list(grouped.values())
    if resolved.near_me:
        items.sort(key=lambda x: (
            x["distance_seconds"] is None, 
            x["distance_seconds"] if x["distance_seconds"] is not None else float('inf'),
            -x["reliability"], x["room_id"]
        ))
    else:
        items.sort(key=lambda x: (-x["reliability"], x["room_id"]))

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