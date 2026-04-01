from pydantic import BaseModel, ConfigDict, field_validator


class CreateFavoriteRequest(BaseModel):
    room_id: str

    @field_validator("room_id")
    @classmethod
    def normalize_room_id(cls, value: str) -> str:
        cleaned = " ".join(value.upper().split())
        if not cleaned:
            raise ValueError("room_id is required")
        return cleaned


class FavoriteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_email: str
    room_id: str


class MyFavoriteItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_id: str


class MyFavoritesResponse(BaseModel):
    total: int
    items: list[MyFavoriteItemOut]
