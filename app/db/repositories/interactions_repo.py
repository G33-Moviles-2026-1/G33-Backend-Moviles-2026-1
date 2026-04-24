from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import UserRoomInteraction


async def upsert_user_room_interaction(
    db: AsyncSession,
    *,
    user_email: str,
    room_id: str,
    weekday: str,
    slot_start: time,
    weight: float,
) -> None:
    """
    Upserts a learning score for a specific user + room + time context.
    If it exists, it adds the new weight to the existing score.
    """
    stmt = (
        insert(UserRoomInteraction)
        .values(
            user_email=user_email,
            room_id=room_id,
            weekday=weekday,
            slot_start=slot_start,
            learning_score=weight,
        )
    )

    stmt = stmt.on_conflict_do_update(
        constraint="uix_user_room_time",
        set_={
            "learning_score": UserRoomInteraction.learning_score + weight
        }
    )

    await db.execute(stmt)
    # Note: In the repository pattern, we typically let the Service or Router 
    # handle `await db.commit()` to maintain transaction boundaries across multiple calls!


async def get_user_contextual_scores(
    db: AsyncSession,
    *,
    user_email: str,
    weekday: str,
    slot_start: time,
) -> dict[str, float]:
    """
    Returns a dictionary of {room_id: learning_score} for a specific time context.
    """
    stmt = (
        select(UserRoomInteraction.room_id, UserRoomInteraction.learning_score)
        .where(
            UserRoomInteraction.user_email == user_email,
            UserRoomInteraction.weekday == weekday,
            UserRoomInteraction.slot_start == slot_start,
        )
    )

    result = await db.execute(stmt)
    
    # Using result.all() to match your analytics_repository style
    return {row.room_id: row.learning_score for row in result.all()}