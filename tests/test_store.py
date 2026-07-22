"""Tests for the Redis-backed store (against fakeredis)."""

from __future__ import annotations

import pytest
from redis.exceptions import RedisError

from bot.database.store import RedisStore
from bot.utils.errors import DatastoreUnavailable


class _BoomPipe:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def hsetnx(self, *a, **k):
        return self

    def hset(self, *a, **k):
        return self

    def sadd(self, *a, **k):
        return self

    async def execute(self):
        raise RedisError("connection refused")


class _BoomRedis:
    def pipeline(self, transaction: bool = True):
        return _BoomPipe()


async def test_link_uid_raises_clear_error_when_redis_down():
    """A failed write surfaces DatastoreUnavailable (clear message), not a bare RedisError."""
    store = RedisStore(_BoomRedis())
    with pytest.raises(DatastoreUnavailable):
        await store.link_uid(1, "901211014")


async def test_get_or_create_registers_user(store):
    await store.get_or_create(1, "en")
    assert await store.count_users() == 1
    # Idempotent — no duplicate registration.
    await store.get_or_create(1, "en")
    assert await store.count_users() == 1


async def test_link_and_get_uid_persists(store):
    await store.link_uid(7, "901211014")
    assert await store.get_uid(7) == "901211014"
    # Linking registers the user.
    assert await store.count_users() == 1


async def test_relink_overwrites_uid(store):
    await store.link_uid(7, "901211014")
    await store.link_uid(7, "600000000")
    assert await store.get_uid(7) == "600000000"


async def test_unlink_uid(store):
    await store.link_uid(7, "901211014")
    assert await store.unlink_uid(7) is True
    assert await store.get_uid(7) is None
    # Nothing to remove the second time.
    assert await store.unlink_uid(7) is False


async def test_language_default_and_update(store):
    assert await store.get_language(5, "en") == "en"
    await store.set_language(5, "ja")
    assert await store.get_language(5, "en") == "ja"


async def test_settings_kv(store):
    await store.set_setting(9, "show_ranks", "true")
    assert await store.get_setting(9, "show_ranks") == "true"
    await store.set_setting(9, "show_ranks", "false")
    assert await store.get_setting(9, "show_ranks") == "false"
    assert await store.get_setting(9, "missing", "default") == "default"
    assert await store.get_all_settings(9) == {"show_ranks": "false"}


async def test_register_interaction_counts_private_and_users(store):
    await store.register_interaction(100, "private")
    await store.register_interaction(100, "private")  # idempotent
    await store.register_interaction(200, "group")
    assert await store.count_users() == 2
    assert await store.count_private_chats() == 1
    assert await store.count_interactions() >= 3


async def test_group_register_and_unregister(store):
    await store.register_group(-100123)
    await store.register_group(-100123)  # no duplicate
    assert await store.count_groups() == 1
    await store.unregister_group(-100123)
    assert await store.count_groups() == 0


async def test_uid_is_user_specific(store):
    await store.link_uid(1, "601111111")
    await store.link_uid(2, "702222222")
    assert await store.get_uid(1) == "601111111"
    assert await store.get_uid(2) == "702222222"
