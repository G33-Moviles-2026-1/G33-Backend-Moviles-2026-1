from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.schemas.ingest import IngestRunResponse, IngestSummaryResponse
from app.services.ingest_service import IngestService

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/run", response_model=IngestRunResponse)
async def run_ingest(
    db: AsyncSession = Depends(get_db),
):
    service = IngestService()
    return await service.run(db, term_id=settings.current_term_id)


@router.get("/summary", response_model=IngestSummaryResponse)
async def ingest_summary(
    db: AsyncSession = Depends(get_db),
):
    service = IngestService()
    return await service.summary(db, term_id=settings.current_term_id)