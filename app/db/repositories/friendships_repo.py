from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Friendship, FriendshipStatus, User


async def user_exists(
    db: AsyncSession,
    *,
    email: str,
) -> bool:
    result = await db.execute(
        select(User.email).where(User.email == email).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def friendship_exists_any_direction(
    db: AsyncSession,
    *,
    email_1: str,
    email_2: str,
) -> bool:
    result = await db.execute(
        select(Friendship.correo_amigo_1)
        .where(
            or_(
                (Friendship.correo_amigo_1 == email_1) & (Friendship.correo_amigo_2 == email_2),
                (Friendship.correo_amigo_1 == email_2) & (Friendship.correo_amigo_2 == email_1),
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def insert_friendship(
    db: AsyncSession,
    *,
    correo_amigo_1: str,
    correo_amigo_2: str,
) -> Friendship:
    friendship = Friendship(
        correo_amigo_1=correo_amigo_1,
        correo_amigo_2=correo_amigo_2,
        estado=FriendshipStatus.pending,
    )
    db.add(friendship)
    await db.commit()
    await db.refresh(friendship)
    return friendship


async def get_pending_friendship(
    db: AsyncSession,
    *,
    correo_amigo_1: str,
    correo_amigo_2: str,
) -> Friendship | None:
    result = await db.execute(
        select(Friendship).where(
            Friendship.correo_amigo_1 == correo_amigo_1,
            Friendship.correo_amigo_2 == correo_amigo_2,
            Friendship.estado == FriendshipStatus.pending,
        )
    )
    return result.scalar_one_or_none()


async def update_friendship_to_accepted(
    db: AsyncSession,
    *,
    friendship: Friendship,
) -> Friendship:
    friendship.estado = FriendshipStatus.accepted
    await db.commit()
    await db.refresh(friendship)
    return friendship


async def delete_friendship_any_direction(
    db: AsyncSession,
    *,
    email_1: str,
    email_2: str,
) -> None:
    await db.execute(
        delete(Friendship).where(
            or_(
                (Friendship.correo_amigo_1 == email_1) & (Friendship.correo_amigo_2 == email_2),
                (Friendship.correo_amigo_1 == email_2) & (Friendship.correo_amigo_2 == email_1),
            )
        )
    )
    await db.commit()
