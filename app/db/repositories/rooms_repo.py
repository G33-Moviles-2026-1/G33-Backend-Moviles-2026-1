from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Room
from app.integrations.uniandes.ingest_runner import RoomSeed


async def upsert_rooms(db: AsyncSession, rooms: list[RoomSeed]) -> int:
    if not rooms:
        return 0

    payload = [
        {
            "id": r.room_id,
            "building_code": r.building_code,
            "room_number": r.room_number,
            "building_name": r.building_name,
            "capacity": r.capacity,
            "reliability": 100.0,
        }
        for r in rooms
    ]

    await db.execute(
        insert(Room).values(payload).on_conflict_do_update(
            index_elements=[Room.id],
            set_={
                "building_code": insert(Room).excluded.building_code,
                "room_number": insert(Room).excluded.room_number,
                "building_name": insert(Room).excluded.building_name,
                "capacity": insert(Room).excluded.capacity,
            },
        )
    )
    return len(rooms)