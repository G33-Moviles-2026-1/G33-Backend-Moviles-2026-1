from datetime import date
from pydantic import BaseModel


class IngestRunResponse(BaseModel):
    term_id: str
    term_start: date
    term_end: date
    raw_courses: int
    normalized_meetings: int
    buildings_upserted: int
    rooms_upserted: int
    availability_rules_written: int


class IngestSummaryResponse(BaseModel):
    term_id: str
    buildings: int
    rooms: int
    availability_rules: int
    sample_rooms: list[str]