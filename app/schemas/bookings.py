from datetime import date, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.db.models import BookingPurpose, BookingStatus


class CreateBookingRequest(BaseModel):
    room_id: str
    date: date
    start_time: time
    end_time: time
    purpose: BookingPurpose

    @field_validator("room_id")
    @classmethod
    def normalize_room_id(cls, value: str) -> str:
        cleaned = " ".join(value.upper().split())
        if not cleaned:
            raise ValueError("room_id is required")
        return cleaned


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_email: str
    term_id: str
    room_id: str
    date: date
    start_time: time
    end_time: time
    purpose: BookingPurpose
    status: BookingStatus