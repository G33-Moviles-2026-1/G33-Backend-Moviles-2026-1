from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time_rules import clip_to_operating_hours
from app.db.models import BookingStatus, Weekday
from app.db.repositories.bookings_repo import (
    count_active_bookings_for_user,
    current_term_exists,
    fetch_bookable_time_ranges_for_room,
    insert_booking,
    room_exists,
    room_has_overlapping_active_booking,
    user_has_overlapping_active_booking,
)
from app.schemas.bookings import BookingOut, CreateBookingRequest

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


def _today_bogota() -> date:
    return datetime.now(BOGOTA_TZ).date()


async def create_booking(
    db: AsyncSession,
    *,
    user_email: str,
    payload: CreateBookingRequest,
) -> BookingOut:
    today = _today_bogota()
    max_allowed = today + timedelta(days=7)

    if payload.date < today or payload.date > max_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date must be between today and the next 7 days",
        )

    if payload.start_time >= payload.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_time must be earlier than end_time",
        )

    weekday = WEEKDAY_MAP[payload.date.weekday()]

    clipped_requested_window = clip_to_operating_hours(
        weekday,
        payload.start_time,
        payload.end_time,
    )

    if clipped_requested_window is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="campus is closed for the selected day/time",
        )

    if clipped_requested_window != (payload.start_time, payload.end_time):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="selected slot must be fully inside campus operating hours",
        )

    if not await current_term_exists(db, term_id=settings.current_term_id):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="current term is not configured in the database yet",
        )

    if not await room_exists(db, room_id=payload.room_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="room was not found",
        )

    valid_ranges = await fetch_bookable_time_ranges_for_room(
        db,
        room_id=payload.room_id,
        target_date=payload.date,
        weekday=weekday,
    )

    valid_range_keys = {
        (item.start_time, item.end_time)
        for item in valid_ranges
    }

    if (payload.start_time, payload.end_time) not in valid_range_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="selected slot is not a valid bookable slot for this room and date",
        )

    active_bookings_count = await count_active_bookings_for_user(
        db,
        user_email=user_email,
    )
    if active_bookings_count >= 5:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="you already have 5 active bookings",
        )

    if await user_has_overlapping_active_booking(
        db,
        user_email=user_email,
        target_date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="you already have another active booking that overlaps this slot",
        )

    if await room_has_overlapping_active_booking(
        db,
        room_id=payload.room_id,
        target_date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this room slot is already booked",
        )

    booking = await insert_booking(
        db,
        user_email=user_email,
        room_id=payload.room_id,
        target_date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        purpose=payload.purpose,
        status=BookingStatus.active,
    )

    return BookingOut.model_validate(booking)