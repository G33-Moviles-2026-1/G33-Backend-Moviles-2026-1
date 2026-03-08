from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import asin, cos, radians, sin, sqrt
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UtilityType, Weekday
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


def _normalize_text_token(value: str) -> str:
    return " ".join(value.replace("-", " ").upper().split())


def _normalize_prefixes(payload: RoomSearchRequest) -> list[str]:
    candidates: list[str] = []

    if payload.room_prefix:
        candidates.append(payload.room_prefix)

    candidates.extend(payload.room_prefixes)

    normalized: list[str] = []
    for value in candidates:
        cleaned = _normalize_text_token(value)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)

    return normalized


def _normalize_building_codes(building_codes: list[str]) -> list[str]:
    normalized: list[str] = []
    for code in building_codes:
        cleaned = _normalize_text_token(code)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _current_bogota_datetime() -> datetime:
    return datetime.now(BOGOTA_TZ)


def _resolve_time_window(
    *,
    target_date: date,
    since: time | None,
    until: time | None,
) -> tuple[time, time]:
    if since is None and until is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="at least one of since or until must be provided",
        )

    if since is None:
        now = _current_bogota_datetime()
        # Sensible interpretation of the open edge case in the source:
        # - today -> current local time
        # - future day -> earliest allowed search time
        inferred_since = time(now.hour, now.minute) if target_date == now.date() else MIN_TIME
        since = max(inferred_since, MIN_TIME)

    if until is None:
        until = MAX_TIME

    if since < MIN_TIME or since > MAX_TIME or until < MIN_TIME or until > MAX_TIME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since and until must be between 05:30 and 22:00",
        )

    if since >= until:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since must be earlier than until",
        )

    return since, until


def resolve_room_search_request(payload: RoomSearchRequest) -> ResolvedSearchParams:
    today = _current_bogota_datetime().date()
    max_allowed = today + timedelta(days=7)

    if payload.date < today or payload.date > max_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date must be between today and the next 7 days",
        )

    if payload.near_me and payload.user_location is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_location is required when near_me is true",
        )

    since, until = _resolve_time_window(
        target_date=payload.date,
        since=payload.since,
        until=payload.until,
    )

    return ResolvedSearchParams(
        room_prefixes=_normalize_prefixes(payload),
        date=payload.date,
        since=since,
        until=until,
        building_codes=_normalize_building_codes(payload.building_codes),
        utilities=payload.utilities,
        near_me=payload.near_me,
        user_location=payload.user_location,
        limit=payload.limit,
        offset=payload.offset,
        weekday=WEEKDAY_MAP[payload.date.weekday()],
    )


def _haversine_meters(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    earth_radius_m = 6371000.0

    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)

    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    c = 2 * asin(sqrt(a))
    return earth_radius_m * c


async def search_rooms(
    db: AsyncSession,
    payload: RoomSearchRequest,
) -> RoomSearchResponse:
    resolved = resolve_room_search_request(payload)

    rows = await fetch_room_search_rows(
        db,
        target_date=resolved.date,
        weekday=resolved.weekday,
        since=resolved.since,
        until=resolved.until,
        room_prefixes=resolved.room_prefixes,
        building_codes=resolved.building_codes,
        utilities=resolved.utilities,
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
                "distance_meters": None,
                "matching_windows": [],
                "_lat": row.latitude,
                "_lon": row.longitude,
            }

        window = TimeWindowOut(
            start=row.rule_start_time,
            end=row.rule_end_time,
        )

        existing_windows = grouped[row.room_id]["matching_windows"]
        if window not in existing_windows:
            existing_windows.append(window)

    items: list[dict] = list(grouped.values())

    if resolved.near_me and resolved.user_location is not None:
        user_lat = resolved.user_location.latitude
        user_lon = resolved.user_location.longitude

        for item in items:
            lat = item["_lat"]
            lon = item["_lon"]
            if lat is not None and lon is not None:
                item["distance_meters"] = round(
                    _haversine_meters(user_lat, user_lon, lat, lon),
                    1,
                )

        items.sort(
            key=lambda item: (
                item["distance_meters"] is None,
                item["distance_meters"] if item["distance_meters"] is not None else float("inf"),
                -item["reliability"],
                item["room_id"],
            )
        )
    else:
        items.sort(
            key=lambda item: (
                -item["reliability"],
                item["room_id"],
            )
        )

    total = len(items)
    paginated = items[resolved.offset:resolved.offset + resolved.limit]

    paginated_room_ids = [item["room_id"] for item in paginated]
    weekly_map = await fetch_weekly_availability_for_rooms(
        db,
        room_ids=paginated_room_ids,
    )

    response_items = [
        RoomSearchItemOut(
            room_id=item["room_id"],
            building_code=item["building_code"],
            building_name=item["building_name"],
            room_number=item["room_number"],
            capacity=item["capacity"],
            reliability=item["reliability"],
            utilities=item["utilities"],
            distance_meters=item["distance_meters"],
            matching_windows=item["matching_windows"],
            weekly_availability=[
                WeeklyAvailabilityWindowOut(
                    day=window.day,
                    start=window.start_time,
                    end=window.end_time,
                    valid_from=window.valid_from,
                    valid_to=window.valid_to,
                )
                for window in weekly_map.get(item["room_id"], [])
            ],
        )
        for item in paginated
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
        total=total,
        items=response_items,
    )