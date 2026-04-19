from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.navigation import PathResponse
from app.services.navigation_service import NavigationService

router = APIRouter(prefix="/navigation", tags=["navigation"])


@router.get("/path", response_model=PathResponse)
async def get_path(
    from_room: str,
    to_room: str,
    db: AsyncSession = Depends(get_db),
) -> PathResponse:
    nav = NavigationService(db)

    start_node = await nav.find_node_for_room(from_room)
    end_node = await nav.find_node_for_room(to_room)

    result = await nav.get_route(start_node.id, end_node.id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No route found between the two rooms",
        )

    return PathResponse(
        from_room=" ".join(from_room.replace("-", " ").upper().split()),
        to_room=" ".join(to_room.replace("-", " ").upper().split()),
        total_time_seconds=result["total_time_seconds"],
        steps=result["steps"],
    )
