from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Term


async def upsert_current_term(
    db: AsyncSession,
    *,
    term_id: str,
    start_date,
    end_date,
) -> None:
    await db.execute(
        insert(Term).values(
            id=term_id,
            start_date=start_date,
            end_date=end_date,
            is_current=True,
        ).on_conflict_do_update(
            index_elements=[Term.id],
            set_={
                "start_date": start_date,
                "end_date": end_date,
                "is_current": True,
            },
        )
    )