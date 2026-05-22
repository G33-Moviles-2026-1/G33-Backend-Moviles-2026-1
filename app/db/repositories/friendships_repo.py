from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Friendship, FriendshipStatus, User, UserStatus


async def resolve_user_identifier_to_email(
    db: AsyncSession,
    *,
    identifier: str,
) -> str | None:
    """
    Accepts either a user email or username (correo_amigo_* fields / path params).
    """
    cleaned = identifier.strip().lower()
    if not cleaned:
        return None

    if "@" in cleaned:
        result = await db.execute(
            select(User.email).where(User.email == cleaned).limit(1)
        )
        return result.scalar_one_or_none()

    result = await db.execute(
        select(User.email)
        .where(func.lower(User.username) == cleaned)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def user_exists(
    db: AsyncSession,
    *,
    email: str,
) -> bool:
    resolved = await resolve_user_identifier_to_email(db, identifier=email)
    return resolved is not None


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



async def list_incoming_pending_requests(
    db: AsyncSession,
    *,
    user_email: str,
) -> list[tuple[str, str]]:
    result = await db.execute(
        select(User.email, User.username)
        .join(Friendship, User.email == Friendship.correo_amigo_1)
        .where(
            Friendship.correo_amigo_2 == user_email,
            Friendship.estado == FriendshipStatus.pending,
        )
        .order_by(User.username.asc())
    )
    return list(result.all())


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


async def count_total_users(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(User))
    return int(result.scalar_one() or 0)


async def count_accepted_friendships(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Friendship)
        .where(Friendship.estado == FriendshipStatus.accepted)
    )
    return int(result.scalar_one() or 0)


async def list_accepted_friends_for_user(
    db: AsyncSession,
    *,
    user_email: str,
) -> list[tuple[str, str]]:
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
        select(User.email, User.username)
        .join(friend_email_col, User.email == friend_email_col.c.friend_email)
        .order_by(User.username.asc())
    )
    return list(result.all())


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