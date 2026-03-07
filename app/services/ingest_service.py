from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Building, Room
from app.db.repositories.availability_repo import count_rules, replace_term_rules
from app.db.repositories.buildings_repo import upsert_buildings
from app.db.repositories.rooms_repo import upsert_rooms
from app.db.repositories.terms_repo import upsert_current_term
from app.integrations.uniandes.client import UniandesCoursesClient
from app.integrations.uniandes.ingest_runner import build_ingest_snapshot
from app.schemas.ingest import IngestRunResponse, IngestSummaryResponse


class IngestService:
    def __init__(self, client: UniandesCoursesClient | None = None) -> None:
        self.client = client or UniandesCoursesClient()

    async def run(self, db: AsyncSession, *, term_id: str) -> IngestRunResponse:
        raw_courses = await self.client.fetch_all_courses()
        snapshot = build_ingest_snapshot(raw_courses, term_id)

        await upsert_current_term(
            db,
            term_id=snapshot.term_id,
            start_date=snapshot.term_start,
            end_date=snapshot.term_end,
        )

        buildings_count = await upsert_buildings(db, snapshot.buildings)
        rooms_count = await upsert_rooms(db, snapshot.rooms)
        rules_count = await replace_term_rules(db, term_id=snapshot.term_id, rules=snapshot.rules)

        await db.commit()

        return IngestRunResponse(
            term_id=snapshot.term_id,
            term_start=snapshot.term_start,
            term_end=snapshot.term_end,
            raw_courses=len(raw_courses),
            normalized_meetings=snapshot.normalized_meetings_count,
            buildings_upserted=buildings_count,
            rooms_upserted=rooms_count,
            availability_rules_written=rules_count,
        )

    async def summary(self, db: AsyncSession, *, term_id: str) -> IngestSummaryResponse:
        buildings_result = await db.execute(select(func.count()).select_from(Building))
        rooms_result = await db.execute(select(func.count()).select_from(Room))
        rooms_sample_result = await db.execute(select(Room.id).order_by(Room.id).limit(10))

        return IngestSummaryResponse(
            term_id=term_id,
            buildings=int(buildings_result.scalar_one()),
            rooms=int(rooms_result.scalar_one()),
            availability_rules=await count_rules(db, term_id),
            sample_rooms=list(rooms_sample_result.scalars().all()),
        )