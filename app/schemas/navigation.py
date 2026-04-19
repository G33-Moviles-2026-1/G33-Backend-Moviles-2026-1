from pydantic import BaseModel


class PathResponse(BaseModel):
    from_room: str
    to_room: str
    total_time_seconds: float
    steps: list[str]
