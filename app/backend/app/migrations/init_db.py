import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from ..core.config import settings
from ..core.database import Base, _sync_engine
from ..models.user import User
from ..models.session import Session, Project, Asset, AssetVersion, Question, Feedback, SearchCache, Topic


async def init():
    if settings.database_backend == "postgres":
        engine = create_async_engine(settings.database_url, echo=True)
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()
    else:
        # Snowflake: use the sync engine from database.py
        Base.metadata.create_all(_sync_engine)
    print("Database initialized successfully")


if __name__ == "__main__":
    asyncio.run(init())
