from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Booking,
    BookingStatus,
    Favorite,
    Room,
    UserRoomInteraction,
)


@dataclass(slots=True)
class UserRoomPreferenceSignal:
    room_id: str
    building_code: str | None
    capacity: int | None
    weight: float
    source: str


async def fetch_user_room_preference_signals(
    db: AsyncSession,
    *,
    user_email: str,
    weekday: str,
    slot_start: time,
) -> list[UserRoomPreferenceSignal]:
    signals: list[UserRoomPreferenceSignal] = []

    bookings_result = await db.execute(
        select(
            Booking.room_id,
            Room.building_code,
            Room.capacity,
            func.count().label("booking_count"),
        )
        .join(Room, Room.id == Booking.room_id)
        .where(
            Booking.term_id == settings.current_term_id,
            Booking.user_email == user_email,
            Booking.status.in_([BookingStatus.active, BookingStatus.completed]),
        )
        .group_by(Booking.room_id, Room.building_code, Room.capacity)
    )

    for room_id, building_code, capacity, booking_count in bookings_result.all():
        count = int(booking_count or 0)
        if count <= 0:
            continue

        signals.append(
            UserRoomPreferenceSignal(
                room_id=room_id,
                building_code=building_code,
                capacity=capacity,
                weight=float(count),
                source="booking",
            )
        )

    favorites_result = await db.execute(
        select(Favorite.room_id, Room.building_code, Room.capacity)
        .join(Room, Room.id == Favorite.room_id)
        .where(Favorite.user_email == user_email)
    )

    booking_weight_values = [
        signal.weight for signal in signals if signal.source == "booking"
    ]
    favorite_weight = (
        sum(booking_weight_values) / len(booking_weight_values)
        if booking_weight_values
        else 1.0
    )

    for room_id, building_code, capacity in favorites_result.all():
        signals.append(
            UserRoomPreferenceSignal(
                room_id=room_id,
                building_code=building_code,
                capacity=capacity,
                weight=max(1.0, favorite_weight),
                source="favorite",
            )
        )

    interactions_result = await db.execute(
        select(
            UserRoomInteraction.room_id,
            Room.building_code,
            Room.capacity,
            UserRoomInteraction.slot_start,
            UserRoomInteraction.learning_score,
        )
        .join(Room, Room.id == UserRoomInteraction.room_id, isouter=True)
        .where(
            UserRoomInteraction.user_email == user_email,
            UserRoomInteraction.weekday == weekday,
        )
    )

    target_minutes = _time_to_minutes(slot_start)
    for room_id, building_code, capacity, interaction_time, learning_score in (
        interactions_result.all()
    ):
        score = float(learning_score or 0.0)
        if score == 0:
            continue

        distance_minutes = abs(target_minutes - _time_to_minutes(interaction_time))
        proximity = max(0.25, 1.0 - (distance_minutes / 180.0))

        signals.append(
            UserRoomPreferenceSignal(
                room_id=room_id,
                building_code=building_code,
                capacity=capacity,
                weight=score * proximity,
                source="interaction",
            )
        )

    return signals


def _time_to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute
