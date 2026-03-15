from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_rules import clip_to_operating_hours
from app.db.models import (
    Booking,
    BookingPurpose,
    BookingStatus,
    Room,
    RoomAvailabilityRule,
    Term,
    Weekday,
)


@dataclass(slots=True)
class BookableTimeRange:
    start_time: time
    end_time: time


async def current_term_exists(
    db: AsyncSession,
    *,
    term_id: str,
) -> bool:
    result = await db.execute(
        select(Term.id).where(Term.id == term_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def room_exists(
    db: AsyncSession,
    *,
    room_id: str,
) -> bool:
    result = await db.execute(
        select(Room.id).where(Room.id == room_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def fetch_bookable_time_ranges_for_room(
    db: AsyncSession,
    *,
    room_id: str,
    target_date: date,
    weekday: Weekday,
) -> list[BookableTimeRange]:
    result = await db.execute(
        select(
            RoomAvailabilityRule.start_time,
            RoomAvailabilityRule.end_time,
        )
        .where(
            RoomAvailabilityRule.term_id == settings.current_term_id,
            RoomAvailabilityRule.room_id == room_id,
            RoomAvailabilityRule.day == weekday,
            RoomAvailabilityRule.valid_from <= target_date,
            RoomAvailabilityRule.valid_to >= target_date,
        )
        .order_by(
            RoomAvailabilityRule.start_time.asc(),
            RoomAvailabilityRule.end_time.asc(),
        )
    )

    seen: set[tuple[time, time]] = set()
    ranges: list[BookableTimeRange] = []

    for start_time, end_time in result.all():
        clipped = clip_to_operating_hours(weekday, start_time, end_time)
        if clipped is None:
            continue

        if clipped in seen:
            continue

        seen.add(clipped)
        ranges.append(
            BookableTimeRange(
                start_time=clipped[0],
                end_time=clipped[1],
            )
        )

    return ranges


async def count_active_bookings_for_user(
    db: AsyncSession,
    *,
    user_email: str,
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Booking)
        .where(
            Booking.term_id == settings.current_term_id,
            Booking.user_email == user_email,
            Booking.status == BookingStatus.active,
        )
    )
    return int(result.scalar_one())


async def user_has_overlapping_active_booking(
    db: AsyncSession,
    *,
    user_email: str,
    target_date: date,
    start_time: time,
    end_time: time,
) -> bool:
    result = await db.execute(
        select(Booking.id)
        .where(
            Booking.term_id == settings.current_term_id,
            Booking.user_email == user_email,
            Booking.date == target_date,
            Booking.status == BookingStatus.active,
            Booking.start_time < end_time,
            Booking.end_time > start_time,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def room_has_overlapping_active_booking(
    db: AsyncSession,
    *,
    room_id: str,
    target_date: date,
    start_time: time,
    end_time: time,
) -> bool:
    result = await db.execute(
        select(Booking.id)
        .where(
            Booking.term_id == settings.current_term_id,
            Booking.room_id == room_id,
            Booking.date == target_date,
            Booking.status == BookingStatus.active,
            Booking.start_time < end_time,
            Booking.end_time > start_time,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def insert_booking(
    db: AsyncSession,
    *,
    user_email: str,
    room_id: str,
    target_date: date,
    start_time: time,
    end_time: time,
    purpose: BookingPurpose,
    status: BookingStatus,
) -> Booking:
    booking = Booking(
        user_email=user_email,
        term_id=settings.current_term_id,
        room_id=room_id,
        date=target_date,
        start_time=start_time,
        end_time=end_time,
        purpose=purpose,
        status=status,
    )

    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return booking