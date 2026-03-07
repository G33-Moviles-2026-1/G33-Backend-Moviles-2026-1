from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Building
from app.integrations.uniandes.ingest_runner import BuildingSeed


async def upsert_buildings(db: AsyncSession, buildings: list[BuildingSeed]) -> int:
    if not buildings:
        return 0

    payload = [
        {
            "code": b.code,
            "name": b.name,
            "latitude": None,
            "longitude": None,
        }
        for b in buildings
    ]

    await db.execute(
        insert(Building).values(payload).on_conflict_do_update(
            index_elements=[Building.code],
            set_={"name": insert(Building).excluded.name},
        )
    )
    return len(buildings)