from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Booking,
    BookingStatus,
    Building,
    Room,
    RoomAvailabilityRule,
    RoomUtility,
    UtilityType,
    Weekday,
)
from app.integrations.uniandes.ingest_runner import RoomSeed


@dataclass(slots=True)
class RoomSearchRow:
    room_id: str
    building_code: str
    building_name: str | None
    room_number: str
    capacity: int
    reliability: float
    rule_start_time: time
    rule_end_time: time
    latitude: float | None
    longitude: float | None
    utilities: list[UtilityType]


@dataclass(slots=True)
class WeeklyAvailabilityRow:
    room_id: str
    day: Weekday
    start_time: time
    end_time: time
    valid_from: date
    valid_to: date


async def upsert_rooms(db: AsyncSession, rooms: list[RoomSeed]) -> int:
    if not rooms:
        return 0

    payload = [
        {
            "id": r.room_id,
            "building_code": r.building_code,
            "room_number": r.room_number,
            "building_name": r.building_name,
            "capacity": r.capacity,
            "reliability": 100.0,
        }
        for r in rooms
    ]

    await db.execute(
        insert(Room).values(payload).on_conflict_do_update(
            index_elements=[Room.id],
            set_={
                "building_code": insert(Room).excluded.building_code,
                "room_number": insert(Room).excluded.room_number,
                "building_name": insert(Room).excluded.building_name,
                "capacity": insert(Room).excluded.capacity,
            },
        )
    )
    return len(rooms)


async def _fetch_utilities_for_rooms(
    db: AsyncSession,
    room_ids: list[str],
) -> dict[str, list[UtilityType]]:
    if not room_ids:
        return {}

    result = await db.execute(
        select(RoomUtility.room_id, RoomUtility.utility)
        .where(RoomUtility.room_id.in_(room_ids))
        .order_by(RoomUtility.room_id.asc(), RoomUtility.utility.asc())
    )

    utilities_map: dict[str, list[UtilityType]] = {}
    for room_id, utility in result.all():
        utilities_map.setdefault(room_id, []).append(utility)

    return utilities_map


async def _fetch_active_bookings_for_rooms(
    db: AsyncSession,
    *,
    room_ids: list[str],
    target_date: date,
) -> dict[str, list[tuple[time, time]]]:
    if not room_ids:
        return {}

    result = await db.execute(
        select(Booking.room_id, Booking.start_time, Booking.end_time)
        .where(
            Booking.term_id == settings.current_term_id,
            Booking.date == target_date,
            Booking.status == BookingStatus.active,
            Booking.room_id.in_(room_ids),
        )
        .order_by(Booking.room_id.asc(), Booking.start_time.asc())
    )

    bookings_map: dict[str, list[tuple[time, time]]] = {}
    for room_id, start_time, end_time in result.all():
        bookings_map.setdefault(room_id, []).append((start_time, end_time))

    return bookings_map


async def fetch_room_search_rows(
    db: AsyncSession,
    *,
    target_date: date,
    weekday: Weekday,
    since: time,
    until: time,
    room_prefixes: list[str],
    building_codes: list[str],
    utilities: list[UtilityType],
) -> list[RoomSearchRow]:

    stmt = (
        select(
            Room.id.label("room_id"),
            Room.building_code.label("building_code"),
            func.coalesce(Room.building_name, Building.name).label("building_name"),
            Room.room_number.label("room_number"),
            Room.capacity.label("capacity"),
            Room.reliability.label("reliability"),
            RoomAvailabilityRule.start_time.label("rule_start_time"),
            RoomAvailabilityRule.end_time.label("rule_end_time"),
            Building.latitude.label("latitude"),
            Building.longitude.label("longitude"),
        )
        .join(RoomAvailabilityRule, RoomAvailabilityRule.room_id == Room.id)
        .join(Building, Building.code == Room.building_code)
        .where(
            RoomAvailabilityRule.term_id == settings.current_term_id,
            RoomAvailabilityRule.day == weekday,
            RoomAvailabilityRule.valid_from <= target_date,
            RoomAvailabilityRule.valid_to >= target_date,
            RoomAvailabilityRule.start_time < until,
            RoomAvailabilityRule.end_time > since,
        )
    )

    if room_prefixes:
        stmt = stmt.where(
            or_(
                *[
                    func.upper(Room.id).like(f"{prefix}%")
                    for prefix in room_prefixes
                ]
            )
        )

    if building_codes:
        stmt = stmt.where(Room.building_code.in_(building_codes))

    if utilities:
        utilities_filter_subquery = (
            select(RoomUtility.room_id)
            .where(RoomUtility.utility.in_(utilities))
            .group_by(RoomUtility.room_id)
            .having(func.count(func.distinct(RoomUtility.utility)) == len(utilities))
        )
        stmt = stmt.where(Room.id.in_(utilities_filter_subquery))

    stmt = stmt.order_by(
        Room.id.asc(),
        RoomAvailabilityRule.start_time.asc(),
        RoomAvailabilityRule.end_time.asc(),
    )

    result = await db.execute(stmt)
    raw_rows = result.all()

    if not raw_rows:
        return []

    room_ids = list({row.room_id for row in raw_rows})
    utilities_map = await _fetch_utilities_for_rooms(db, room_ids)
    bookings_map = await _fetch_active_bookings_for_rooms(
        db,
        room_ids=room_ids,
        target_date=target_date,
    )

    filtered_rows: list[RoomSearchRow] = []

    for row in raw_rows:
        room_bookings = bookings_map.get(row.room_id, [])

        window_is_blocked = any(
            booking_start < row.rule_end_time and booking_end > row.rule_start_time
            for booking_start, booking_end in room_bookings
        )

        if window_is_blocked:
            continue

        filtered_rows.append(
            RoomSearchRow(
                room_id=row.room_id,
                building_code=row.building_code,
                building_name=row.building_name,
                room_number=row.room_number,
                capacity=row.capacity,
                reliability=float(row.reliability),
                rule_start_time=row.rule_start_time,
                rule_end_time=row.rule_end_time,
                latitude=row.latitude,
                longitude=row.longitude,
                utilities=utilities_map.get(row.room_id, []),
            )
        )

    return filtered_rows


async def fetch_weekly_availability_for_rooms(
    db: AsyncSession,
    *,
    room_ids: list[str],
) -> dict[str, list[WeeklyAvailabilityRow]]:
    if not room_ids:
        return {}

    result = await db.execute(
        select(
            RoomAvailabilityRule.room_id,
            RoomAvailabilityRule.day,
            RoomAvailabilityRule.start_time,
            RoomAvailabilityRule.end_time,
            RoomAvailabilityRule.valid_from,
            RoomAvailabilityRule.valid_to,
        )
        .where(
            RoomAvailabilityRule.term_id == settings.current_term_id,
            RoomAvailabilityRule.room_id.in_(room_ids),
        )
        .order_by(
            RoomAvailabilityRule.room_id.asc(),
            RoomAvailabilityRule.day.asc(),
            RoomAvailabilityRule.start_time.asc(),
            RoomAvailabilityRule.end_time.asc(),
            RoomAvailabilityRule.valid_from.asc(),
        )
    )

    weekly_map: dict[str, list[WeeklyAvailabilityRow]] = {}
    for room_id, day, start_time, end_time, valid_from, valid_to in result.all():
        weekly_map.setdefault(room_id, []).append(
            WeeklyAvailabilityRow(
                room_id=room_id,
                day=day,
                start_time=start_time,
                end_time=end_time,
                valid_from=valid_from,
                valid_to=valid_to,
            )
        )

    return weekly_map
