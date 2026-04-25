from datetime import date,time
from fastapi import APIRouter, Depends, Request, Query, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.interactions_service import InteractionAction, record_user_interaction
from app.services.recommendations_service import get_auto_search_recommendations
from app.schemas.rooms import RoomSearchItemOut 
from typing import List

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])

class InteractionPayload(BaseModel):
    room_id: str
    action: InteractionAction
    weekday: str
    slot_start: time

class AutoSearchPayload(BaseModel):
    target_date: date
    target_time: time
    top_k: int = 3
    exclude_ids: List[str] = []

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

@router.post("/auto-search", response_model=list[RoomSearchItemOut])
async def auto_search_rooms(
    request: Request,
    payload: AutoSearchPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Get ML-powered room recommendations based on historical preferences 
    and reinforcement learning (Contextual Bandit).
    """
    user_email = _require_active_user_email(request)
    top_k = payload.top_k
    target_date = payload.target_date
    target_time = payload.target_time
    recommendations = await get_auto_search_recommendations(
        db,
        top_k=top_k,
        target_date = target_date,
        target_time = target_time,
        user_email=user_email,
        exclude_ids=payload.exclude_ids
    )

    return recommendations