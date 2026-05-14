from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Friendship, FriendshipStatus, User, UserStatus


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

async def get_accepted_friends_emails_not_incognito(
    db: AsyncSession,
    *,
    user_email: str,
) -> list[str]:
    friend_email_col = (
        select(
            Friendship.correo_amigo_2.label("friend_email")
        ).where(
            Friendship.correo_amigo_1 == user_email,
            Friendship.estado == FriendshipStatus.accepted,
        )
        .union_all(
            select(
                Friendship.correo_amigo_1.label("friend_email")
            ).where(
                Friendship.correo_amigo_2 == user_email,
                Friendship.estado == FriendshipStatus.accepted,
            )
        )
    ).subquery()

    result = await db.execute(
        select(User.email)
        .join(friend_email_col, User.email == friend_email_col.c.friend_email)
        .where(User.status != UserStatus.incognito)
    )
    return list(result.scalars().all())


async def get_friend_suggestion_usernames(
    db: AsyncSession,
    *,
    user_email: str,
) -> list[str]:
    query = """
    WITH my_friends AS (
        SELECT
            CASE
                WHEN correo_amigo_1 = :user_email THEN correo_amigo_2
                ELSE correo_amigo_1
            END AS friend_email
        FROM friendships
        WHERE estado = :accepted_status
          AND (
              correo_amigo_1 = :user_email
              OR correo_amigo_2 = :user_email
          )
    ),
    second_degree_candidates AS (
        SELECT DISTINCT
            CASE
                WHEN f.correo_amigo_1 = mf.friend_email THEN f.correo_amigo_2
                ELSE f.correo_amigo_1
            END AS candidate_email
        FROM my_friends mf
        JOIN friendships f
          ON f.estado = :accepted_status
         AND (
             f.correo_amigo_1 = mf.friend_email
             OR f.correo_amigo_2 = mf.friend_email
         )
    )
    SELECT DISTINCT u.username
    FROM second_degree_candidates sdc
    JOIN users u
      ON u.email = sdc.candidate_email
    WHERE sdc.candidate_email <> :user_email
      AND u.username IS NOT NULL
      AND u.username <> ''
      AND sdc.candidate_email NOT IN (
          SELECT friend_email
          FROM my_friends
      )
      AND NOT EXISTS (
          SELECT 1
          FROM friendships existing
          WHERE (
              existing.correo_amigo_1 = :user_email
              AND existing.correo_amigo_2 = sdc.candidate_email
          )
          OR (
              existing.correo_amigo_2 = :user_email
              AND existing.correo_amigo_1 = sdc.candidate_email
          )
      )
    ORDER BY u.username;
    """

    result = await db.execute(
        text(query),
        {
            "user_email": user_email,
            "accepted_status": FriendshipStatus.accepted.value,
        },
    )
    return list(result.scalars().all())