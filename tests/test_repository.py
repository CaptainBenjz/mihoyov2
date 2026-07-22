"""Tests for the database repositories."""

from __future__ import annotations

from bot.database.repository import CacheMetaRepository, UserRepository


async def test_get_or_create_is_idempotent(session_factory):
    users = UserRepository(session_factory)
    u1 = await users.get_or_create(1, "en")
    u2 = await users.get_or_create(1, "en")
    assert u1.telegram_user_id == u2.telegram_user_id == 1


async def test_language_defaults_and_updates(session_factory):
    users = UserRepository(session_factory)
    assert await users.get_language(5, "en") == "en"
    await users.set_language(5, "ja")
    assert await users.get_language(5, "en") == "ja"


async def test_link_and_unlink_uid(session_factory):
    users = UserRepository(session_factory)
    await users.link_uid(7, "901211014")
    assert await users.get_uid(7) == "901211014"
    assert await users.unlink_uid(7) is True
    assert await users.get_uid(7) is None


async def test_settings_kv(session_factory):
    users = UserRepository(session_factory)
    await users.set_setting(9, "show_ranks", "true")
    assert await users.get_setting(9, "show_ranks") == "true"
    await users.set_setting(9, "show_ranks", "false")
    assert await users.get_setting(9, "show_ranks") == "false"
    assert await users.get_setting(9, "missing", "default") == "default"
    assert await users.get_all_settings(9) == {"show_ranks": "false"}


async def test_cache_meta_touch(session_factory):
    meta = CacheMetaRepository(session_factory)
    assert await meta.last_fetched("enka", "901211014") is None
    await meta.touch("enka", "901211014")
    assert await meta.last_fetched("enka", "901211014") is not None
