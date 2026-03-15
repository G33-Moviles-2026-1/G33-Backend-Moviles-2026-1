from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field

from app.db.models import UtilityType, Weekday

from datetime import date, time
from pydantic import BaseModel
from app.db.models import Weekday

class RoomDateAvailabilitySlotOut(BaseModel):
    start: time
    end: time
    is_available: bool

class RoomDateAvailabilityOut(BaseModel):
    room_id: str
    date: date
    weekday: Weekday
    building_code: str
    building_name: str | None
    room_number: str
    capacity: int
    reliability: float
    utilities: list[str]
    available_slots: list[RoomDateAvailabilitySlotOut]
    blocked_slots: list[RoomDateAvailabilitySlotOut]

class LocationIn(BaseModel):
    latitude: float
    longitude: float


class TimeWindowOut(BaseModel):
    start: time
    end: time


class WeeklyAvailabilityWindowOut(BaseModel):
    day: Weekday
    start: time
    end: time
    valid_from: date
    valid_to: date


class RoomSearchRequest(BaseModel):
    room_prefix: str | None = None
    room_prefixes: list[str] = Field(default_factory=list)

    date: date
    since: time | None = None
    until: time | None = None

    building_codes: list[str] = Field(default_factory=list)
    utilities: list[UtilityType] = Field(default_factory=list)

    near_me: bool = False
    user_location: LocationIn | None = None

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RoomSearchQueryOut(BaseModel):
    room_prefixes: list[str] = Field(default_factory=list)
    date: date
    since: time
    until: time
    building_codes: list[str] = Field(default_factory=list)
    utilities: list[UtilityType] = Field(default_factory=list)
    near_me: bool = False
    limit: int = 20
    offset: int = 0


class RoomSearchItemOut(BaseModel):
    room_id: str
    building_code: str
    building_name: str | None = None
    room_number: str
    capacity: int
    reliability: float
    utilities: list[UtilityType] = Field(default_factory=list)
    distance_meters: float | None = None

    matching_windows: list[TimeWindowOut] = Field(default_factory=list)

    # NUEVO
    weekly_availability: list[WeeklyAvailabilityWindowOut] = Field(default_factory=list)


class RoomSearchResponse(BaseModel):
    query: RoomSearchQueryOut
    total: int
    items: list[RoomSearchItemOut]