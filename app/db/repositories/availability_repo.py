from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RoomAvailabilityRule
from app.integrations.uniandes.ingest_runner import AvailabilityRuleSeed


BATCH_SIZE = 1000


async def replace_term_rules(
    db: AsyncSession,
    *,
    term_id: str,
    rules: list[AvailabilityRuleSeed],
) -> int:
    await db.execute(
        delete(RoomAvailabilityRule).where(RoomAvailabilityRule.term_id == term_id)
    )

    if not rules:
        return 0

    payload = [
        {
            "term_id": r.term_id,
            "room_id": r.room_id,
            "day": r.day,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "valid_from": r.valid_from,
            "valid_to": r.valid_to,
        }
        for r in rules
    ]

    total = 0
    for i in range(0, len(payload), BATCH_SIZE):
        chunk = payload[i:i + BATCH_SIZE]
        await db.execute(insert(RoomAvailabilityRule).values(chunk))
        total += len(chunk)

    return total


async def count_rules(db: AsyncSession, term_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(RoomAvailabilityRule)
        .where(RoomAvailabilityRule.term_id == term_id)
    )
    return int(result.scalar_one())