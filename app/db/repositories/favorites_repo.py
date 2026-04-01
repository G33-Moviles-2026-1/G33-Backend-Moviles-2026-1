from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Favorite, Room


async def room_exists(
    db: AsyncSession,
    *,
    room_id: str,
) -> bool:
    result = await db.execute(
        select(Room.id).where(Room.id == room_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def favorite_exists(
    db: AsyncSession,
    *,
    user_email: str,
    room_id: str,
) -> bool:
    result = await db.execute(
        select(Favorite.user_email)
        .where(Favorite.user_email == user_email, Favorite.room_id == room_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def insert_favorite(
    db: AsyncSession,
    *,
    user_email: str,
    room_id: str,
) -> Favorite:
    favorite = Favorite(user_email=user_email, room_id=room_id)
    db.add(favorite)
    await db.commit()
    await db.refresh(favorite)
    return favorite


async def list_favorites_for_user(
    db: AsyncSession,
    *,
    user_email: str,
) -> list[Favorite]:
    result = await db.execute(
        select(Favorite)
        .where(Favorite.user_email == user_email)
        .order_by(Favorite.room_id.asc())
    )
    return list(result.scalars().all())


async def delete_favorite_for_user(
    db: AsyncSession,
    *,
    user_email: str,
    room_id: str,
) -> None:
    await db.execute(
        delete(Favorite).where(
            Favorite.user_email == user_email,
            Favorite.room_id == room_id,
        )
    )
    await db.commit()
