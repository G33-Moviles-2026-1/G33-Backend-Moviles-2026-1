import asyncio
from app.db.session import engine
from app.db.base import Base
import app.db.models  # noqa: F401 (ensures models are imported)

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    asyncio.run(init())