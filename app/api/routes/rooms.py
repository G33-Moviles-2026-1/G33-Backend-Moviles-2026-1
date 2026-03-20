from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.rooms import RoomSearchRequest, RoomSearchResponse
from app.services.rooms_service import search_rooms

from datetime import date
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