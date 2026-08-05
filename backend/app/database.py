import os
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator, Optional
from importlib import import_module

# Lazy-initialized engine and sessionmaker so environment overrides (e.g., tests) work when set before use.
_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None
_engine_url: Optional[str] = None


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")


def get_engine() -> AsyncEngine:
    """Return a cached AsyncEngine, recreating it if DATABASE_URL changed since creation."""
    global _engine, _engine_url, _sessionmaker
    current_url = get_database_url()
    if _engine is None or _engine_url != current_url:
        # recreate engine when URL changed
        _engine = create_async_engine(current_url, echo=False)
        _engine_url = current_url
        # reset sessionmaker so it's bound to the new engine
        _sessionmaker = None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    # Ensure models are imported so SQLModel metadata is populated
    import_module("backend.app.models")

    # create tables synchronously via a connection from the async engine
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield an AsyncSession and ensure rollback on exception.

    Usage:
        async with get_session() as session:
            ...
    or as a dependency: session: AsyncSession = Depends(get_session)
    """
    session: AsyncSession = get_sessionmaker()()
    try:
        yield session
        # commit should be explicit by callers; but if not, flush/commit here is not done to avoid surprise
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
