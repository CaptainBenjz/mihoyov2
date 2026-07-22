"""Shared pytest fixtures.

Uses an in-memory SQLite database so repository tests are fast and isolated. No network
access is performed anywhere in the test suite — API clients are always mocked.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.database.models import Base


@pytest_asyncio.fixture
async def session_factory():
    """A fresh in-memory database + session factory per test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()
