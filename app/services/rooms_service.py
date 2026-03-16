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

from app.db.models import NavEdge, NavNode, RoomNavAnchor, UtilityType, Weekday
from app.db.repositories.rooms_repo import (
    fetch_room_search_rows,
    fetch_weekly_availability_for_rooms,
)
from app.schemas.rooms import (
    RoomSearchItemOut,
    RoomSearchQueryOut,
    RoomSearchRequest,
    RoomSearchResponse,
    TimeWindowOut,
    WeeklyAvailabilityWindowOut,
)

BOGOTA_TZ = ZoneInfo("America/Bogota")
MIN_TIME = time(5, 30)
MAX_TIME = time(22, 0)

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
    """Encuentra el nodo del grafo más cercano físicamente a la posición GPS del usuario."""
    result = await db.execute(select(NavNode))
    nodes = result.scalars().all()
    if not nodes:
        raise HTTPException(status_code=500, detail="No navigation nodes found in database")
    
    return min(nodes, key=lambda n: _haversine_meters(lat, lon, n.lat, n.lon)).id

# --- LÓGICA DE NORMALIZACIÓN Y RESOLUCIÓN ---

def _normalize_text_token(value: str) -> str:
    return " ".join(value.replace("-", " ").upper().split())

def _normalize_prefixes(payload: RoomSearchRequest) -> list[str]:
    candidates = ([payload.room_prefix] if payload.room_prefix else []) + payload.room_prefixes
    return list(dict.fromkeys(_normalize_text_token(c) for c in candidates if c))

def _resolve_time_window(target_date: date, since: time | None, until: time | None) -> tuple[time, time]:
    if since is None and until is None:
        raise HTTPException(status_code=400, detail="at least one of since or until must be provided")
    
    now = datetime.now(BOGOTA_TZ)
    if since is None:
        since = max(time(now.hour, now.minute) if target_date == now.date() else MIN_TIME, MIN_TIME)
    if until is None:
        until = MAX_TIME

    if not (MIN_TIME <= since <= MAX_TIME) or not (MIN_TIME <= until <= MAX_TIME):
        raise HTTPException(status_code=400, detail="Time must be between 05:30 and 22:00")
    if since >= until:
        raise HTTPException(status_code=400, detail="since must be earlier than until")
    
    return since, until

def resolve_room_search_request(payload: RoomSearchRequest) -> ResolvedSearchParams:
    today = datetime.now(BOGOTA_TZ).date()
    if not (today <= payload.date <= today + timedelta(days=7)):
        raise HTTPException(status_code=400, detail="date must be within the next 7 days")
    
    if payload.near_me and not payload.user_location:
        raise HTTPException(status_code=400, detail="user_location is required for near_me")

    since, until = _resolve_time_window(payload.date, payload.since, payload.until)

    return ResolvedSearchParams(
        room_prefixes=_normalize_prefixes(payload),
        date=payload.date, since=since, until=until,
        building_codes=[_normalize_text_token(c) for c in payload.building_codes],
        utilities=payload.utilities, near_me=payload.near_me,
        user_location=payload.user_location, limit=payload.limit,
        offset=payload.offset, weekday=WEEKDAY_MAP[payload.date.weekday()],
    )

# --- SERVICIO PRINCIPAL ---

async def search_rooms(db: AsyncSession, payload: RoomSearchRequest) -> RoomSearchResponse:
    resolved = resolve_room_search_request(payload)

    # 1. Obtener datos base de salones
    rows = await fetch_room_search_rows(
        db, target_date=resolved.date, weekday=resolved.weekday,
        since=resolved.since, until=resolved.until,
        room_prefixes=resolved.room_prefixes,
        building_codes=resolved.building_codes, utilities=resolved.utilities,
    )

    # 2. Agrupar por salón
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

    # 3. Lógica de Cercanía (Dijkstra)
    if resolved.near_me and resolved.user_location:
        # A. Encontrar nodo inicial más cercano al GPS del usuario
        start_node_id = await _find_closest_node(db, resolved.user_location.latitude, resolved.user_location.longitude)
        
        # B. Correr Dijkstra para tener mapa de costos
        cost_map = await get_dijkstra_map(db, start_node_id)
        
        # C. Obtener anclas de los salones (qué salón está en qué nodo)
        anchors_res = await db.execute(select(RoomNavAnchor))
        room_to_node = {a.room_id: a.node_id for a in anchors_res.scalars().all()}

        for rid, item in grouped.items():
            target_node_id = room_to_node.get(rid)
            if target_node_id:
                item["distance_seconds"] = cost_map.get(target_node_id)

    # 4. Ordenamiento
    items = list(grouped.values())
    if resolved.near_me:
        items.sort(key=lambda x: (
            x["distance_seconds"] is None, 
            x["distance_seconds"] if x["distance_seconds"] is not None else float('inf'),
            x["_earliest_start"]
        ))
    else:
        items.sort(key=lambda x: (x["_earliest_start"], -x["reliability"]))

    # 5. Paginación y Enriquecimiento
    paginated = items[resolved.offset : resolved.offset + resolved.limit]
    weekly_map = await fetch_weekly_availability_for_rooms(db, room_ids=[i["room_id"] for i in paginated])

    response_items = [
        RoomSearchItemOut(
            **{
                k: v for k, v in item.items() 
                if not k.startswith("_") 
                and k not in ["distance_seconds", "matching_windows"]
            },
            distance_meters=item["distance_seconds"], 
            matching_windows=sorted(item["matching_windows"], key=lambda w: w.start),
            weekly_availability=[
                WeeklyAvailabilityWindowOut(
                    day=w.day, 
                    start=w.start_time, 
                    end=w.end_time,
                    valid_from=w.valid_from, 
                    valid_to=w.valid_to
                ) for w in weekly_map.get(item["room_id"], [])
            ]
        ) for item in paginated
    ]

    return RoomSearchResponse(
        query=RoomSearchQueryOut(
            room_prefixes=resolved.room_prefixes,
            date=resolved.date,
            since=resolved.since,
            until=resolved.until,
            building_codes=resolved.building_codes,
            utilities=resolved.utilities,
            near_me=resolved.near_me,
            limit=resolved.limit,
            offset=resolved.offset,
        ),
        total=len(items),
        items=response_items
    )