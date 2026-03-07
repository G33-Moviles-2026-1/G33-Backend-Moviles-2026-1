from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoomUtility, UtilityType


async def replace_room_utilities(
    db: AsyncSession,
    *,
    room_id: str,
    utilities: list[UtilityType],
) -> None:
    await db.execute(
        delete(RoomUtility).where(RoomUtility.room_id == room_id)
    )

    if not utilities:
        return

    payload = [
        {
            "room_id": room_id,
            "utility": utility,
        }
        for utility in utilities
    ]

    await db.execute(insert(RoomUtility).values(payload))