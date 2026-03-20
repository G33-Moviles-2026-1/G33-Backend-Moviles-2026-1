from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.db.models import UtilityType
from app.schemas.rooms import GapRoomsResponse, RoomSearchRequest, RoomSearchResponse
from app.services.rooms_service import get_gap_rooms, search_rooms

from datetime import date, time
from app.schemas.rooms import RoomDateAvailabilityOut
from app.services.rooms_service import get_room_date_availability

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.get("/{room_id}/availability", response_model=RoomDateAvailabilityOut)
async def room_date_availability(
    room_id: str,
    date_value: date,
    db: AsyncSession = Depends(get_db),
) -> RoomDateAvailabilityOut:
    return await get_room_date_availability(
        db,
        room_id=room_id,
        target_date=date_value,
    )


@router.post("/search", response_model=RoomSearchResponse)
async def search_rooms_endpoint(
    payload: RoomSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> RoomSearchResponse:
    return await search_rooms(db, payload)


@router.get("/search/gap", response_model=GapRoomsResponse)
async def search_rooms_by_gap(
    date_value: date,
    gap_start: time,
    gap_end: time,
    utilities: list[UtilityType] = Query(default=[]),
    db: AsyncSession = Depends(get_db),
) -> GapRoomsResponse:
    return await get_gap_rooms(
        db,
        target_date=date_value,
        gap_start=gap_start,
        gap_end=gap_end,
        utilities=utilities,
    )
