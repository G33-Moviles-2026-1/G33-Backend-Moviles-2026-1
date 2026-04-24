from datetime import date,time
from fastapi import APIRouter, Depends, Request, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.interactions_service import InteractionAction, record_user_interaction
from app.services.recommendations_service import get_auto_search_recommendations
from app.schemas.rooms import RoomSearchItemOut 

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

class InteractionPayload(BaseModel):
    room_id: str
    action: InteractionAction
    weekday: str
    slot_start: time


def _require_active_user_email(request: Request) -> str:
    user_email = request.session.get("user_name")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="There is no active session",
        )
    return user_email

@router.post("/interact", status_code=status.HTTP_204_NO_CONTENT)
async def submit_room_interaction(
    payload: InteractionPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit user feedback (SKIP, BOOK, FAVORITE) for a recommended room.
    """

    user_email = _require_active_user_email(request)

    await record_user_interaction(
        db,
        user_email=user_email,
        room_id=payload.room_id,
        action=payload.action,
        weekday=payload.weekday,
        slot_start=payload.slot_start,
    )

@router.get("/auto-search", response_model=list[RoomSearchItemOut])
async def auto_search_rooms(
    request: Request,
    target_date: date = Query(..., description="The target date for the booking"),
    since: time = Query(..., description="Start of the search time window"),
    until: time = Query(..., description="End of the search time window"),
    top_k: int = Query(3, ge=1, le=10, description="Number of recommendations to return"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get ML-powered room recommendations based on historical preferences 
    and reinforcement learning (Contextual Bandit).
    """
    user_email = _require_active_user_email(request)
    recommendations = await get_auto_search_recommendations(
        db,
        user_email=user_email,
        target_date=target_date,
        since=since,
        until=until,
        top_k=top_k,
    )

    return recommendations