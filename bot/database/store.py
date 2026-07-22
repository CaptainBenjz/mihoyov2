"""Redis-backed persistent store — the primary source of truth for user data.

Holds everything that must survive bot restarts:
  * per-user record (linked Genshin UID, language, timestamps, session metadata),
  * per-user settings (free-form key/value, so new preferences need no schema change),
  * the set of registered users and the subsets by chat context,
  * the set of groups/supergroups the bot is in,
  * bot statistics counters.

Every operation is wrapped so a Redis outage degrades gracefully (safe default / no-op)
rather than crashing the bot. Reads return ``None``/defaults on failure; the caller then
behaves as if the data is absent (e.g. the user is asked to link) — never a crash.

Key layout
----------
  user:{tid}            hash   uid, language, created_at, last_seen, last_chat_type
  user:{tid}:settings   hash   arbitrary preference key/value
  users                 set    all registered telegram user ids
  chats:private         set    user ids that have opened a private chat
  groups                set    group/supergroup chat ids the bot is in
  stats:interactions    str    monotonically increasing interaction counter
"""

from __future__ import annotations

import time
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from bot.utils.errors import DatastoreUnavailable
from bot.utils.logging import get_logger

logger = get_logger(__name__)

USERS_SET = "users"
PRIVATE_SET = "chats:private"
GROUPS_SET = "groups"
INTERACTIONS = "stats:interactions"


def _user_key(tid: int) -> str:
    return f"user:{tid}"


def _settings_key(tid: int) -> str:
    return f"user:{tid}:settings"


def _now() -> int:
    return int(time.time())


class RedisStore:
    """Async persistent store backed by Redis."""

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    # ------------------------------------------------------------------ users
    async def get_or_create(self, telegram_user_id: int, default_language: str = "en") -> dict[str, Any]:
        """Ensure a user record exists and is registered. Returns the record."""
        key = _user_key(telegram_user_id)
        try:
            existing = await self._r.hgetall(key)
            if not existing:
                now = _now()
                await self._r.hset(key, mapping={
                    "language": default_language,
                    "created_at": now,
                    "last_seen": now,
                })
                await self._r.sadd(USERS_SET, telegram_user_id)
                return {"language": default_language, "created_at": now, "last_seen": now}
            return existing
        except RedisError as exc:
            logger.warning("get_or_create failed for %s: %s", telegram_user_id, exc)
            return {}

    async def link_uid(self, telegram_user_id: int, uid: str, default_language: str = "en") -> None:
        """Persist a user's Genshin UID permanently. Idempotent; also registers the user."""
        key = _user_key(telegram_user_id)
        try:
            async with self._r.pipeline(transaction=True) as pipe:
                pipe.hsetnx(key, "created_at", _now())
                pipe.hsetnx(key, "language", default_language)
                pipe.hset(key, mapping={"uid": str(uid), "last_seen": _now()})
                pipe.sadd(USERS_SET, telegram_user_id)
                await pipe.execute()
        except RedisError as exc:
            logger.error("link_uid failed for %s: %s", telegram_user_id, exc)
            # Surface a clear, localized "try again" message instead of the generic error.
            raise DatastoreUnavailable(str(exc)) from exc

    async def unlink_uid(self, telegram_user_id: int) -> bool:
        """Remove a user's linked UID. Returns True if one was present."""
        key = _user_key(telegram_user_id)
        try:
            removed = await self._r.hdel(key, "uid")
            return bool(removed)
        except RedisError as exc:
            logger.error("unlink_uid failed for %s: %s", telegram_user_id, exc)
            return False

    async def get_uid(self, telegram_user_id: int) -> str | None:
        try:
            return await self._r.hget(_user_key(telegram_user_id), "uid")
        except RedisError as exc:
            logger.warning("get_uid failed for %s: %s", telegram_user_id, exc)
            return None

    # --------------------------------------------------------------- language
    async def set_language(self, telegram_user_id: int, language: str, default_language: str = "en") -> None:
        key = _user_key(telegram_user_id)
        try:
            await self._r.hset(key, "language", language)
            await self._r.sadd(USERS_SET, telegram_user_id)
        except RedisError as exc:
            logger.error("set_language failed for %s: %s", telegram_user_id, exc)

    async def get_language(self, telegram_user_id: int, default_language: str = "en") -> str:
        try:
            lang = await self._r.hget(_user_key(telegram_user_id), "language")
            return lang or default_language
        except RedisError as exc:
            logger.warning("get_language failed for %s: %s", telegram_user_id, exc)
            return default_language

    # --------------------------------------------------------------- settings
    async def set_setting(self, telegram_user_id: int, key: str, value: str) -> None:
        try:
            await self._r.hset(_settings_key(telegram_user_id), key, value)
        except RedisError as exc:
            logger.error("set_setting failed for %s: %s", telegram_user_id, exc)

    async def get_setting(self, telegram_user_id: int, key: str, default: str | None = None) -> str | None:
        try:
            value = await self._r.hget(_settings_key(telegram_user_id), key)
            return value if value is not None else default
        except RedisError as exc:
            logger.warning("get_setting failed for %s: %s", telegram_user_id, exc)
            return default

    async def get_all_settings(self, telegram_user_id: int) -> dict[str, str]:
        try:
            return await self._r.hgetall(_settings_key(telegram_user_id)) or {}
        except RedisError as exc:
            logger.warning("get_all_settings failed for %s: %s", telegram_user_id, exc)
            return {}

    # ----------------------------------------------- registration & sessions
    async def register_interaction(self, telegram_user_id: int, chat_type: str | None) -> None:
        """Register a user on interaction and record lightweight session metadata.

        Called for every update via the tracking handler. Idempotent (sets prevent
        duplicates). Never raises.
        """
        key = _user_key(telegram_user_id)
        try:
            async with self._r.pipeline(transaction=False) as pipe:
                pipe.sadd(USERS_SET, telegram_user_id)
                pipe.hsetnx(key, "created_at", _now())
                pipe.hset(key, mapping={"last_seen": _now(), "last_chat_type": chat_type or "private"})
                if chat_type in (None, "private"):
                    pipe.sadd(PRIVATE_SET, telegram_user_id)
                pipe.incr(INTERACTIONS)
                await pipe.execute()
        except RedisError as exc:
            logger.debug("register_interaction failed for %s: %s", telegram_user_id, exc)

    async def register_group(self, chat_id: int) -> None:
        try:
            await self._r.sadd(GROUPS_SET, chat_id)
        except RedisError as exc:
            logger.debug("register_group failed for %s: %s", chat_id, exc)

    async def unregister_group(self, chat_id: int) -> None:
        try:
            await self._r.srem(GROUPS_SET, chat_id)
        except RedisError as exc:
            logger.debug("unregister_group failed for %s: %s", chat_id, exc)

    # -------------------------------------------------------------- statistics
    async def count_users(self) -> int:
        try:
            return int(await self._r.scard(USERS_SET))
        except RedisError:
            return 0

    async def count_private_chats(self) -> int:
        try:
            return int(await self._r.scard(PRIVATE_SET))
        except RedisError:
            return 0

    async def count_groups(self) -> int:
        try:
            return int(await self._r.scard(GROUPS_SET))
        except RedisError:
            return 0

    async def count_interactions(self) -> int:
        try:
            value = await self._r.get(INTERACTIONS)
            return int(value) if value else 0
        except (RedisError, ValueError):
            return 0
