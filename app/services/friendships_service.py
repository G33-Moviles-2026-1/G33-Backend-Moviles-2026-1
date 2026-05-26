from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.friendships_repo import (
    delete_friendship_any_direction,
    friendship_exists_any_direction,
    get_friend_suggestion_usernames,
    get_pending_friendship,
    insert_friendship,
    list_accepted_friends_for_user,
    list_incoming_pending_requests,
    list_outgoing_pending_requests,
    resolve_user_identifier_to_email,
    update_friendship_to_accepted,
    user_exists,
    get_friendship_between_users,
    get_username_by_email,
)
from app.schemas.friendships import (
    AcceptFriendshipRequest,
    CreateFriendshipRequest,
    FriendItemOut,
    FriendshipOut,
    MyFriendsResponse,
)


def _status_value(value) -> str:
    if value is None:
        return "incognito"

    if hasattr(value, "value"):
        return value.value

    return str(value)


def _friend_items_from_rows(rows) -> list[FriendItemOut]:
    items: list[FriendItemOut] = []

    for email, username, user_status, share_schedule in rows:
        safe_username = username or email.split("@", 1)[0]

        items.append(
            FriendItemOut(
                email=email,
                username=safe_username,
                status=_status_value(user_status),
                share_schedule=bool(share_schedule),
            )
        )

    return items

def _friendship_status_int(value) -> int:
    if hasattr(value, "value"):
        return int(value.value)
    return int(value)


async def _friend_display_name(
    db: AsyncSession,
    *,
    friend_email: str,
) -> str:
    username = await get_username_by_email(db, email=friend_email)
    return username or friend_email.split("@", 1)[0]


async def create_friendship_request(
    db: AsyncSession,
    *,
    requester_email: str,
    payload: CreateFriendshipRequest,
) -> FriendshipOut:
    friend_email = await resolve_user_identifier_to_email(
        db,
        identifier=payload.correo_amigo_2,
    )

    if not friend_email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="friend user was not found",
        )

    if requester_email == friend_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot add yourself as friend",
        )

    existing_friendship = await get_friendship_between_users(
        db,
        email_1=requester_email,
        email_2=friend_email,
    )

    if existing_friendship is not None:
        friend_name = await _friend_display_name(
            db,
            friend_email=friend_email,
        )

        existing_status = _friendship_status_int(existing_friendship.estado)

        if existing_status == 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You and {friend_name} are already friends.",
            )

        if existing_status == 0:
            if existing_friendship.correo_amigo_1 == requester_email:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"You already sent a friend request to {friend_name}. "
                        "Wait for their response."
                    ),
                )

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"You already have a pending request from {friend_name}. "
                    "Accept it or decline it."
                ),
            )

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already have a friendship relationship with {friend_name}.",
        )

    friendship = await insert_friendship(
        db,
        correo_amigo_1=requester_email,
        correo_amigo_2=friend_email,
    )

    return FriendshipOut.model_validate(friendship)


async def get_incoming_requests(
    db: AsyncSession,
    *,
    logged_user_email: str,
) -> MyFriendsResponse:
    requests = await list_incoming_pending_requests(
        db,
        user_email=logged_user_email,
    )

    items = _friend_items_from_rows(requests)
    return MyFriendsResponse(total=len(items), items=items)


async def get_outgoing_requests(
    db: AsyncSession,
    *,
    logged_user_email: str,
) -> MyFriendsResponse:
    requests = await list_outgoing_pending_requests(
        db,
        user_email=logged_user_email,
    )

    items = _friend_items_from_rows(requests)
    return MyFriendsResponse(total=len(items), items=items)


async def accept_friendship_request(
    db: AsyncSession,
    *,
    logged_user_email: str,
    payload: AcceptFriendshipRequest,
) -> FriendshipOut:
    requester_email = await resolve_user_identifier_to_email(
        db,
        identifier=payload.correo_amigo_1,
    )

    if not requester_email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="pending friendship request was not found",
        )

    friendship = await get_pending_friendship(
        db,
        correo_amigo_1=requester_email,
        correo_amigo_2=logged_user_email,
    )

    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="pending friendship request was not found",
        )

    accepted = await update_friendship_to_accepted(
        db,
        friendship=friendship,
    )

    return FriendshipOut.model_validate(accepted)


async def delete_friendship(
    db: AsyncSession,
    *,
    logged_user_email: str,
    friend_email: str,
) -> None:
    resolved_friend_email = await resolve_user_identifier_to_email(
        db,
        identifier=friend_email,
    )

    if not resolved_friend_email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="friendship was not found",
        )

    if not await friendship_exists_any_direction(
        db,
        email_1=logged_user_email,
        email_2=resolved_friend_email,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="friendship was not found",
        )

    await delete_friendship_any_direction(
        db,
        email_1=logged_user_email,
        email_2=resolved_friend_email,
    )


async def get_my_friends(
    db: AsyncSession,
    *,
    logged_user_email: str,
) -> MyFriendsResponse:
    friends = await list_accepted_friends_for_user(
        db,
        user_email=logged_user_email,
    )

    items = _friend_items_from_rows(friends)
    return MyFriendsResponse(total=len(items), items=items)


async def get_friend_suggestions(
    db: AsyncSession,
    *,
    logged_user_email: str,
) -> list[str]:
    if not await user_exists(db, email=logged_user_email):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Your user account was not found.",
        )

    return await get_friend_suggestion_usernames(
        db,
        user_email=logged_user_email,
    )