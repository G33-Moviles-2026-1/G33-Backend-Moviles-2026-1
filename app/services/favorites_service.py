from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.favorites_repo import (
    delete_favorite_for_user,
    favorite_exists,
    insert_favorite,
    list_favorites_for_user,
    room_exists,
)
from app.schemas.favorites import (
    CreateFavoriteRequest,
    FavoriteOut,
    MyFavoriteItemOut,
    MyFavoritesResponse,
)


async def create_favorite(
    db: AsyncSession,
    *,
    user_email: str,
    payload: CreateFavoriteRequest,
) -> FavoriteOut:
    if not await room_exists(db, room_id=payload.room_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="room was not found",
        )

    if await favorite_exists(db, user_email=user_email, room_id=payload.room_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="favorite already exists",
        )

    favorite = await insert_favorite(
        db,
        user_email=user_email,
        room_id=payload.room_id,
    )
    return FavoriteOut.model_validate(favorite)


async def get_my_favorites(
    db: AsyncSession,
    *,
    user_email: str,
) -> MyFavoritesResponse:
    favorites = await list_favorites_for_user(db, user_email=user_email)
    return MyFavoritesResponse(
        total=len(favorites),
        items=[MyFavoriteItemOut.model_validate(item) for item in favorites],
    )


async def delete_my_favorite(
    db: AsyncSession,
    *,
    user_email: str,
    room_id: str,
) -> None:
    if not await favorite_exists(db, user_email=user_email, room_id=room_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="favorite was not found",
        )

    await delete_favorite_for_user(
        db,
        user_email=user_email,
        room_id=room_id,
    )
