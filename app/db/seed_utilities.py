import asyncio
import hashlib
import random

from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models import Room, UtilityType
from app.db.repositories.room_utilities_repo import replace_room_utilities


ALL_UTILITIES = [
    UtilityType.blackout,
    UtilityType.power_outlet,
    UtilityType.television,
    UtilityType.interactive_classroom,
    UtilityType.mobile_whiteboards,
    UtilityType.computer,
    UtilityType.videobeam,
]


def deterministic_rng(room_id: str) -> random.Random:
    seed = int(hashlib.sha256(room_id.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def choose_utilities(room_id: str, capacity: int) -> list[UtilityType]:
    rng = deterministic_rng(room_id)

    chosen: set[UtilityType] = set()

    # Common utilities
    if rng.random() < 0.75:
        chosen.add(UtilityType.power_outlet)

    if rng.random() < 0.45:
        chosen.add(UtilityType.blackout)

    if rng.random() < 0.35:
        chosen.add(UtilityType.mobile_whiteboards)

    # Medium / large room tendencies
    if capacity >= 30 and rng.random() < 0.45:
        chosen.add(UtilityType.videobeam)

    if capacity >= 40 and rng.random() < 0.30:
        chosen.add(UtilityType.television)

    if capacity >= 45 and rng.random() < 0.20:
        chosen.add(UtilityType.interactive_classroom)

    if capacity >= 25 and rng.random() < 0.18:
        chosen.add(UtilityType.computer)

    # Guarantee at least one utility
    if not chosen:
        chosen.add(UtilityType.power_outlet)

    # Keep output stable
    return sorted(chosen, key=lambda u: u.value)


async def seed_utilities() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Room.id, Room.capacity))
        rooms = result.all()

        for room_id, capacity in rooms:
            utilities = choose_utilities(room_id, capacity)
            await replace_room_utilities(
                db,
                room_id=room_id,
                utilities=utilities,
            )

        await db.commit()
        print(f"Inserted utilities for {len(rooms)} rooms.")


if __name__ == "__main__":
    asyncio.run(seed_utilities())