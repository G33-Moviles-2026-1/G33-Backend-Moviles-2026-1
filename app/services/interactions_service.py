from datetime import time
from enum import Enum
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.interactions_repo import (
    upsert_user_room_interaction,
    get_user_contextual_scores
)

class InteractionAction(str, Enum):
    SKIP = "SKIP"
    FAVORITE = "FAVORITE"
    BOOK = "BOOK"

ACTION_WEIGHTS = {
    InteractionAction.SKIP: -2.0,
    InteractionAction.FAVORITE: 5.0,
    InteractionAction.BOOK: 10.0
}

async def record_user_interaction(
    db: AsyncSession,
    *,
    user_email: str,
    room_id: str,
    action: InteractionAction,
    weekday: str,
    slot_start: time,
) -> None:
    weight = ACTION_WEIGHTS[action]
    
    await upsert_user_room_interaction(
        db,
        user_email=user_email,
        room_id=room_id,
        weekday=weekday,
        slot_start=slot_start,
        weight=weight,
    )
    
    await db.commit()