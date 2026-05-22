from pydantic import BaseModel, ConfigDict, field_validator
from app.db.models import FriendshipStatus, UserStatus


class FriendshipBase(BaseModel):
    correo_amigo_2: str

    @field_validator("correo_amigo_2")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("correo_amigo_2 is required")
        return cleaned


class CreateFriendshipRequest(FriendshipBase):
    pass


class AcceptFriendshipRequest(BaseModel):
    correo_amigo_1: str

    @field_validator("correo_amigo_1")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("correo_amigo_1 is required")
        return cleaned


class FriendshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    correo_amigo_1: str
    correo_amigo_2: str
    estado: FriendshipStatus

class FriendItemOut(BaseModel):
    email: str
    username: str
    status: UserStatus
    share_schedule: bool

class MyFriendsResponse(BaseModel):
    total: int
    items: list[FriendItemOut]
