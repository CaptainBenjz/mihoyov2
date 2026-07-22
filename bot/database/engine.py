"""Async database engine and session management."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.config import ROOT_DIR, get_settings
from bot.database.models import Base
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_sqlite_dir(database_url: str) -> None:
    """Make sure the parent directory of a SQLite file exists."""
    marker = "sqlite+aiosqlite:///"
    if database_url.startswith(marker):
        rel = database_url[len(marker):]
        if rel and rel != ":memory:":
            path = Path(rel)
            if not path.is_absolute():
                path = ROOT_DIR / path
            path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use."""
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _ensure_sqlite_dir(settings.database_url)
        _engine = create_async_engine(settings.database_url, echo=False, future=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
        logger.info("Database engine created (%s)", settings.database_url.split("://", 1)[0])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory, creating the engine if needed."""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None  # for type-checkers
    return _session_factory


async def init_db() -> None:
    """Create tables if they do not exist. Safe to call on every startup."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ready")


async def dispose_engine() -> None:
    """Dispose the engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
