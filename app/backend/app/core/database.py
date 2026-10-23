import asyncio

from sqlalchemy.orm import DeclarativeBase

from .config import settings

_backend = settings.database_backend


class Base(DeclarativeBase):
    pass


if _backend == "snowflake":
    # --- Snowflake backend (sync engine wrapped for async FastAPI) ---
    try:
        from snowflake.sqlalchemy import URL as SnowflakeURL
    except ImportError as e:
        raise ImportError(
            "snowflake-sqlalchemy is required when database.backend = 'snowflake'. "
            "Install it with: pip install snowflake-sqlalchemy"
        ) from e

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, Session as SyncSession

    _sync_engine = create_engine(
        SnowflakeURL(
            account=settings.snowflake_account,
            user=settings.snowflake_user,
            password=settings.snowflake_pat,
            database=settings.snowflake_database or "NANOCORTEX",
            schema=settings.snowflake_schema or "PUBLIC",
            warehouse=settings.snowflake_warehouse,
            role=settings.snowflake_role,
        ),
        echo=settings.debug,
    )
    _sync_session_factory = sessionmaker(_sync_engine, expire_on_commit=False)

    engine = None  # Not used for Snowflake

    class _SnowflakeAsyncSession:
        """Wraps a synchronous Snowflake session to work with async FastAPI endpoints."""

        def __init__(self):
            self._sync_session: SyncSession = _sync_session_factory()

        async def execute(self, *args, **kwargs):
            return await asyncio.to_thread(self._sync_session.execute, *args, **kwargs)

        async def scalar(self, stmt, *args, **kwargs):
            result = await asyncio.to_thread(self._sync_session.execute, stmt, *args, **kwargs)
            return result.scalar()

        async def commit(self):
            await asyncio.to_thread(self._sync_session.commit)

        async def rollback(self):
            await asyncio.to_thread(self._sync_session.rollback)

        async def flush(self):
            await asyncio.to_thread(self._sync_session.flush)

        async def refresh(self, instance):
            await asyncio.to_thread(self._sync_session.refresh, instance)

        def add(self, instance):
            if hasattr(instance, "updated_at"):
                from datetime import datetime, timezone
                instance.updated_at = datetime.now(timezone.utc)
            self._sync_session.add(instance)

        async def close(self):
            await asyncio.to_thread(self._sync_session.close)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            if exc_type:
                await self.rollback()
            await self.close()

    async def get_db():
        session = _SnowflakeAsyncSession()
        try:
            yield session
        finally:
            await session.close()

    async_session = _SnowflakeAsyncSession  # callable returning a session

else:
    # --- PostgreSQL backend (default) ---
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    try:
        from pgvector.sqlalchemy import Vector  # noqa: F401 — registers the type
    except ImportError:
        pass

    _sync_engine = None  # Not used for Postgres

    engine = create_async_engine(settings.database_url, echo=settings.debug)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def get_db() -> AsyncSession:
        async with async_session() as session:
            yield session
