from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, time

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Booking,
    BookingStatus,
    Building,
    Room,
    RoomAvailabilityRule,
    Schedule,
    ScheduleClass,
    ScheduleClassWeekday,
    ScheduleSource,
    Weekday,
    User,
)


# ── Data Transfer Objects ────────────────────────────────────────────────────

@dataclass
class ClassInputData:
    title: str | None
    location_text: str | None
    room_id: str | None
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    weekdays: list[str]


@dataclass
class ScheduleClassRow:
    class_id: uuid.UUID
    title: str | None
    location_text: str | None
    room_id: str | None
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    weekdays: list[str] = field(default_factory=list)


@dataclass
class AvailableRoomRow:
    room_id: str
    building_name: str | None
    capacity: int
    reliability: float
    rule_start: time
    rule_end: time


async def user_exists(db: AsyncSession, user_email: str) -> bool:
    result = await db.execute(
        select(User.email).where(User.email == user_email).limit(1)
    )
    return result.first() is not None


async def existing_room_ids(db: AsyncSession, room_ids: list[str]) -> set[str]:
    if not room_ids:
        return set()

    result = await db.execute(
        select(Room.id).where(Room.id.in_(room_ids))
    )
    return {row[0] for row in result.all()}


# ── Helpers ──────────────────────────────────────────────────────────────────

async def purge_schedules_for_user(db: AsyncSession, user_email: str) -> None:
    """Delete all schedules (and their classes) for a user."""
    result = await db.execute(
        select(Schedule.id).where(Schedule.user_email == user_email)
    )
    schedule_ids = [row[0] for row in result.all()]
    if not schedule_ids:
        return

    result = await db.execute(
        select(ScheduleClass.id).where(
            ScheduleClass.schedule_id.in_(schedule_ids))
    )
    class_ids = [row[0] for row in result.all()]

    if class_ids:
        await db.execute(
            delete(ScheduleClassWeekday).where(
                ScheduleClassWeekday.schedule_class_id.in_(class_ids)
            )
        )
        await db.execute(
            delete(ScheduleClass).where(
                ScheduleClass.schedule_id.in_(schedule_ids))
        )

    await db.execute(delete(Schedule).where(Schedule.id.in_(schedule_ids)))


async def create_schedule_with_classes(
    db: AsyncSession,
    *,
    user_email: str,
    source: ScheduleSource,
    classes: list[ClassInputData],
) -> uuid.UUID:
    schedule_id = uuid.uuid4()
    await db.execute(
        insert(Schedule).values(id=schedule_id,
                                user_email=user_email, source=source)
    )

    for cls in classes:
        class_id = uuid.uuid4()
        await db.execute(
            insert(ScheduleClass).values(
                id=class_id,
                schedule_id=schedule_id,
                title=cls.title,
                location_text=cls.location_text,
                room_id=cls.room_id,
                start_date=cls.start_date,
                end_date=cls.end_date,
                start_time=cls.start_time,
                end_time=cls.end_time,
            )
        )
        if cls.weekdays:
            await db.execute(
                insert(ScheduleClassWeekday).values(
                    [{"schedule_class_id": class_id, "day": d}
                        for d in cls.weekdays]
                )
            )

    return schedule_id


async def get_active_schedule_id(
    db: AsyncSession, user_email: str
) -> uuid.UUID | None:
    result = await db.execute(
        select(Schedule.id).where(Schedule.user_email == user_email).limit(1)
    )
    row = result.first()
    return row[0] if row else None


async def get_classes_with_weekdays(
    db: AsyncSession, schedule_id: uuid.UUID
) -> list[ScheduleClassRow]:
    result = await db.execute(
        select(ScheduleClass).where(ScheduleClass.schedule_id == schedule_id)
    )
    classes = result.scalars().all()
    if not classes:
        return []

    class_ids = [c.id for c in classes]
    wd_result = await db.execute(
        select(ScheduleClassWeekday).where(
            ScheduleClassWeekday.schedule_class_id.in_(class_ids)
        )
    )
    weekdays_map: dict[uuid.UUID, list[str]] = {}
    for wd in wd_result.scalars().all():
        weekdays_map.setdefault(wd.schedule_class_id, []).append(wd.day.value)

    return [
        ScheduleClassRow(
            class_id=c.id,
            title=c.title,
            location_text=c.location_text,
            room_id=c.room_id,
            start_date=c.start_date,
            end_date=c.end_date,
            start_time=c.start_time,
            end_time=c.end_time,
            weekdays=weekdays_map.get(c.id, []),
        )
        for c in classes
    ]


async def get_class_with_weekdays_for_user(
    db: AsyncSession,
    *,
    user_email: str,
    class_id: uuid.UUID,
) -> ScheduleClassRow | None:
    class_result = await db.execute(
        select(ScheduleClass)
        .join(Schedule, Schedule.id == ScheduleClass.schedule_id)
        .where(
            Schedule.user_email == user_email,
            ScheduleClass.id == class_id,
        )
        .limit(1)
    )
    cls = class_result.scalars().first()
    if cls is None:
        return None

    wd_result = await db.execute(
        select(ScheduleClassWeekday.day).where(
            ScheduleClassWeekday.schedule_class_id == class_id
        )
    )
    weekdays = [row[0].value for row in wd_result.all()]

    return ScheduleClassRow(
        class_id=cls.id,
        title=cls.title,
        location_text=cls.location_text,
        room_id=cls.room_id,
        start_date=cls.start_date,
        end_date=cls.end_date,
        start_time=cls.start_time,
        end_time=cls.end_time,
        weekdays=weekdays,
    )


async def delete_class_by_id(db: AsyncSession, class_id: uuid.UUID) -> None:
    await db.execute(
        delete(ScheduleClassWeekday).where(
            ScheduleClassWeekday.schedule_class_id == class_id
        )
    )
    await db.execute(delete(ScheduleClass).where(ScheduleClass.id == class_id))


async def update_class_date_range(
    db: AsyncSession,
    *,
    class_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> None:
    await db.execute(
        update(ScheduleClass)
        .where(ScheduleClass.id == class_id)
        .values(start_date=start_date, end_date=end_date)
    )


async def clone_class_with_date_range(
    db: AsyncSession,
    *,
    source: ScheduleClassRow,
    start_date: date,
    end_date: date,
) -> uuid.UUID:
    new_id = uuid.uuid4()
    class_model = await db.execute(
        select(ScheduleClass).where(
            ScheduleClass.id == source.class_id).limit(1)
    )
    src = class_model.scalars().first()
    if src is None:
        raise ValueError("Source class not found")

    await db.execute(
        insert(ScheduleClass).values(
            id=new_id,
            schedule_id=src.schedule_id,
            title=source.title,
            location_text=source.location_text,
            room_id=source.room_id,
            start_date=start_date,
            end_date=end_date,
            start_time=source.start_time,
            end_time=source.end_time,
        )
    )

    if source.weekdays:
        await db.execute(
            insert(ScheduleClassWeekday).values(
                [{"schedule_class_id": new_id, "day": d}
                    for d in source.weekdays]
            )
        )

    return new_id


async def fetch_rooms_for_windows(
    db: AsyncSession,
    *,
    weekday: Weekday,
    target_date: date,
    windows: list[tuple[time, time]],
) -> list[AvailableRoomRow]:
    """Return rooms with availability rules overlapping any of the given windows."""
    if not windows:
        return []

    overlap_clauses = [
        and_(
            RoomAvailabilityRule.start_time < w_end,
            RoomAvailabilityRule.end_time > w_start,
        )
        for w_start, w_end in windows
    ]

    stmt = (
        select(
            Room.id.label("room_id"),
            func.coalesce(Room.building_name, Building.name).label(
                "building_name"),
            Room.capacity,
            Room.reliability,
            RoomAvailabilityRule.start_time.label("rule_start"),
            RoomAvailabilityRule.end_time.label("rule_end"),
        )
        .join(RoomAvailabilityRule, RoomAvailabilityRule.room_id == Room.id)
        .join(Building, Building.code == Room.building_code)
        .where(
            RoomAvailabilityRule.term_id == settings.current_term_id,
            RoomAvailabilityRule.day == weekday,
            RoomAvailabilityRule.valid_from <= target_date,
            RoomAvailabilityRule.valid_to >= target_date,
            or_(*overlap_clauses),
        )
        .order_by(Room.id.asc(), RoomAvailabilityRule.start_time.asc())
    )

    # Exclude rooms with active bookings that block available windows
    booking_result = await db.execute(
        select(Booking.room_id, Booking.start_time, Booking.end_time).where(
            Booking.date == target_date,
            Booking.status == BookingStatus.active,
        )
    )
    booked: dict[str, list[tuple[time, time]]] = {}
    for room_id, s, e in booking_result.all():
        booked.setdefault(room_id, []).append((s, e))

    result = await db.execute(stmt)
    rows: list[AvailableRoomRow] = []
    for row in result.all():
        room_bookings = booked.get(row.room_id, [])
        blocked = any(bs < row.rule_end and be >
                      row.rule_start for bs, be in room_bookings)
        if not blocked:
            rows.append(
                AvailableRoomRow(
                    room_id=row.room_id,
                    building_name=row.building_name,
                    capacity=row.capacity,
                    reliability=row.reliability,
                    rule_start=row.rule_start,
                    rule_end=row.rule_end,
                )
            )
    return rows
