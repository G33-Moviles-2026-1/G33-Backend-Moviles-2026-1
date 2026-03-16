from __future__ import annotations

from datetime import date, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ── Upload responses ────────────────────────────────────────────────────────


class ScheduleUploadOut(BaseModel):
    ok: bool = True
    schedule_id: UUID
    classes_count: int
    warnings: list[str] = Field(default_factory=list)


# ── Weekly calendar ─────────────────────────────────────────────────────────

class ScheduleClassOccurrenceOut(BaseModel):
    class_id: UUID
    title: str | None = None
    location_text: str | None = None
    room_id: str | None = None
    date: date
    weekday: str
    start_time: time
    end_time: time


class WeeklyScheduleOut(BaseModel):
    week_start: date
    week_end: date
    occurrences: list[ScheduleClassOccurrenceOut]


# ── Free-room discovery ──────────────────────────────────────────────────────

class FreeSlotOut(BaseModel):
    start_time: time
    end_time: time


class RoomInSlotOut(BaseModel):
    room_id: str
    building_name: str | None = None
    capacity: int
    reliability: float


class SlotWithRoomsOut(BaseModel):
    slot_start: time
    slot_end: time
    available_rooms: list[RoomInSlotOut]


class FreeRoomsForDayOut(BaseModel):
    date: date
    weekday: str
    free_slots: list[FreeSlotOut]
    slots_with_rooms: list[SlotWithRoomsOut]


# ── Manual schedule input ────────────────────────────────────────────────────

ManualWeekday = Literal[
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]


class ManualClassIn(BaseModel):
    title: str
    location_text: str | None = None
    room_id: str | None = None
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    weekdays: list[ManualWeekday]


class ManualScheduleIn(BaseModel):
    user_email: str
    classes: list[ManualClassIn]


class ManualScheduleOut(BaseModel):
    ok: bool = True
    schedule_id: UUID
    classes_count: int


class ScheduleDeleteOut(BaseModel):
    ok: bool = True
    deleted: bool


class ScheduleDeleteClassOut(BaseModel):
    ok: bool = True
    deleted: bool


class ScheduleDeleteOccurrenceOut(BaseModel):
    ok: bool = True
    deleted: bool
    split: bool


class ScheduleClassBaseOut(BaseModel):
    class_id: UUID
    title: str | None = None
    location_text: str | None = None
    room_id: str | None = None
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    weekdays: list[str]


class ScheduleClassesOut(BaseModel):
    classes: list[ScheduleClassBaseOut]
