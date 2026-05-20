from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.friendships import (
    AcceptFriendshipRequest,
    CreateFriendshipRequest,
    FriendshipOut,
    MyFriendsResponse,
)
from app.services.friendships_service import (
    accept_friendship_request,
    create_friendship_request,
    delete_friendship,
    get_friend_suggestions,
    get_my_friends,
)

router = APIRouter(prefix="/friendships", tags=["friendships"])


def _require_active_user_email(request: Request) -> str:
    user_email = request.session.get("user_name")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="There is no active session",
        )
    return user_email


@router.post("/", response_model=FriendshipOut, status_code=status.HTTP_201_CREATED)
async def create_friendship_request_endpoint(
    payload: CreateFriendshipRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FriendshipOut:
    user_email = _require_active_user_email(request)
    return await create_friendship_request(
        db,
        requester_email=user_email,
        payload=payload,
    )


@router.get("/mine", response_model=MyFriendsResponse)
async def my_friends_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MyFriendsResponse:
    user_email = _require_active_user_email(request)
    return await get_my_friends(
        db,
        logged_user_email=user_email,
    )


@router.put("/accept", response_model=FriendshipOut)
async def accept_friendship_request_endpoint(
    payload: AcceptFriendshipRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> FriendshipOut:
    user_email = _require_active_user_email(request)
    return await accept_friendship_request(
        db,
        logged_user_email=user_email,
        payload=payload,
    )

@router.get("/suggestions", response_model=list[str])
async def get_friend_suggestions_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    user_email = _require_active_user_email(request)

    return await get_friend_suggestions(
        db,
        logged_user_email=user_email,
    )

@router.delete("/{friend_email}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_friendship_endpoint(
    friend_email: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    user_email = _require_active_user_email(request)
    normalized_friend_email = friend_email.strip().lower()

    await delete_friendship(
        db,
        logged_user_email=user_email,
        friend_email=normalized_friend_email,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
