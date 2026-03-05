import asyncio
from app.db.session import engine
from app.db.models import Base
from sqlalchemy import text

async def reset_db():
    async with engine.begin() as conn:
        print("Forzando limpieza de tablas...")
        await conn.execute(text("DROP TABLE IF EXISTS sessions CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS users CASCADE;"))        
        print("Creando tablas desde cero...")
        await conn.run_sync(Base.metadata.create_all)
    print("Base de datos reiniciada con éxito.")

if __name__ == "__main__":
    asyncio.run(reset_db())