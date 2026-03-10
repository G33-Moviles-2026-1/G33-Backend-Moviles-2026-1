from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.rooms import RoomSearchRequest, RoomSearchResponse
from app.services.rooms_service import search_rooms

router = APIRouter(prefix="/rooms", tags=["rooms"])


@router.post("/search", response_model=RoomSearchResponse)
async def search_rooms_endpoint(
    payload: RoomSearchRequest,
    db: AsyncSession = Depends(get_db),
) -> RoomSearchResponse:
    return await search_rooms(db, payload)