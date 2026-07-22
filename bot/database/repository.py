"""Async repositories: all database access goes through these.

Keeping CRUD here (rather than in services/commands) means storage concerns are
isolated and easy to test against an in-memory SQLite database.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.database.engine import get_session_factory
from bot.database.models import CacheMeta, User, UserSetting


class UserRepository:
    """CRUD for users, their linked UID, language, and settings."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    # -- users -------------------------------------------------------------
    async def get(self, telegram_user_id: int) -> User | None:
        async with self._session_factory() as session:
            return await session.get(User, telegram_user_id)

    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> User:
        async with self._session_factory() as session:
            user = await session.get(User, telegram_user_id)
            if user is None:
                user = User(telegram_user_id=telegram_user_id, language=default_language)
                session.add(user)
                await session.commit()
                await session.refresh(user)
            return user

    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> User:
        """Link (or relink) a Genshin UID for a user. Idempotent."""
        async with self._session_factory() as session:
            user = await session.get(User, telegram_user_id)
            if user is None:
                user = User(
                    telegram_user_id=telegram_user_id,
                    genshin_uid=uid,
                    language=default_language,
                )
                session.add(user)
            else:
                user.genshin_uid = uid
            await session.commit()
            await session.refresh(user)
            return user

    async def unlink_uid(self, telegram_user_id: int) -> bool:
        """Clear a user's linked UID. Returns True if a UID was present."""
        async with self._session_factory() as session:
            user = await session.get(User, telegram_user_id)
            if user is None or user.genshin_uid is None:
                return False
            user.genshin_uid = None
            await session.commit()
            return True

    async def get_uid(self, telegram_user_id: int) -> str | None:
        user = await self.get(telegram_user_id)
        return user.genshin_uid if user else None

    # -- language ----------------------------------------------------------
    async def set_language(self, telegram_user_id: int, language: str, default_language: str = "en") -> User:
        async with self._session_factory() as session:
            user = await session.get(User, telegram_user_id)
            if user is None:
                user = User(telegram_user_id=telegram_user_id, language=language)
                session.add(user)
            else:
                user.language = language
            await session.commit()
            await session.refresh(user)
            return user

    async def get_language(self, telegram_user_id: int, default_language: str = "en") -> str:
        user = await self.get(telegram_user_id)
        return user.language if (user and user.language) else default_language

    # -- settings (key/value) ---------------------------------------------
    async def set_setting(self, telegram_user_id: int, key: str, value: str) -> None:
        async with self._session_factory() as session:
            stmt = select(UserSetting).where(
                UserSetting.telegram_user_id == telegram_user_id, UserSetting.key == key
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                session.add(UserSetting(telegram_user_id=telegram_user_id, key=key, value=value))
            else:
                existing.value = value
            await session.commit()

    async def get_setting(self, telegram_user_id: int, key: str, default: str | None = None) -> str | None:
        async with self._session_factory() as session:
            stmt = select(UserSetting).where(
                UserSetting.telegram_user_id == telegram_user_id, UserSetting.key == key
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return row.value if row is not None else default

    async def get_all_settings(self, telegram_user_id: int) -> dict[str, str]:
        async with self._session_factory() as session:
            stmt = select(UserSetting).where(UserSetting.telegram_user_id == telegram_user_id)
            rows = (await session.execute(stmt)).scalars().all()
            return {r.key: r.value for r in rows}


class CacheMetaRepository:
    """Durable record of when each external resource was last fetched."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory or get_session_factory()

    async def touch(self, source: str, key: str) -> None:
        """Record a fresh fetch for (source, key), replacing any previous row."""
        async with self._session_factory() as session:
            await session.execute(
                delete(CacheMeta).where(CacheMeta.source == source, CacheMeta.key == key)
            )
            session.add(CacheMeta(source=source, key=key))
            await session.commit()

    async def last_fetched(self, source: str, key: str):
        async with self._session_factory() as session:
            stmt = select(CacheMeta).where(CacheMeta.source == source, CacheMeta.key == key)
            row = (await session.execute(stmt)).scalar_one_or_none()
            return row.fetched_at if row else None
