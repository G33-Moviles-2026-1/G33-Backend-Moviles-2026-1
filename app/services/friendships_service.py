from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.friendships_repo import (
    delete_friendship_any_direction,
    friendship_exists_any_direction,
    get_friend_suggestion_usernames,
    get_pending_friendship,
    insert_friendship,
    list_accepted_friends_for_user,
    update_friendship_to_accepted,
    user_exists,
)
from app.schemas.friendships import (
    AcceptFriendshipRequest,
    CreateFriendshipRequest,
    FriendItemOut,
    FriendshipOut,
    MyFriendsResponse,
)


async def create_friendship_request(
    db: AsyncSession,
    *,
    requester_email: str,
    payload: CreateFriendshipRequest,
) -> FriendshipOut:
    if requester_email == payload.correo_amigo_2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you cannot add yourself as friend",
        )

    if not await user_exists(db, email=payload.correo_amigo_2):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="friend user was not found",
        )

    if await friendship_exists_any_direction(
        db,
        email_1=requester_email,
        email_2=payload.correo_amigo_2,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="friendship already exists or pending",
        )

    friendship = await insert_friendship(
        db,
        correo_amigo_1=requester_email,
        correo_amigo_2=payload.correo_amigo_2,
    )
    return FriendshipOut.model_validate(friendship)


async def accept_friendship_request(
    db: AsyncSession,
    *,
    logged_user_email: str,
    payload: AcceptFriendshipRequest,
) -> FriendshipOut:
    friendship = await get_pending_friendship(
        db,
        correo_amigo_1=payload.correo_amigo_1,
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
    if not await friendship_exists_any_direction(
        db,
        email_1=logged_user_email,
        email_2=friend_email,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="friendship was not found",
        )

    await delete_friendship_any_direction(
        db,
        email_1=logged_user_email,
        email_2=friend_email,
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
    items = [
        FriendItemOut(email=email, username=username)
        for email, username in friends
    ]
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