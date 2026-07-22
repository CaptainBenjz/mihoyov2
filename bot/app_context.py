"""Application context: the dependency container shared across all handlers.

Built once at startup and stored on ``Application.bot_data``. Handlers pull services from
here instead of constructing them, which keeps handlers thin and makes wiring/testing easy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from bot.api.akasha_client import AkashaClient
from bot.api.enka_client import EnkaClient
from bot.cache.redis_cache import RedisCache
from bot.config import Settings, get_settings
from bot.database.redis_client import RedisClient
from bot.database.store import RedisStore
from bot.renderer.base import Renderer, get_renderer
from bot.services.abyss_service import AbyssService
from bot.services.account_service import AccountService
from bot.services.banner_service import BannerService
from bot.services.build_service import BuildService
from bot.services.character_service import CharacterService
from bot.services.stats_service import StatsService
from bot.services.theater_service import TheaterService

# Key under which the context is stored in Application.bot_data.
BOT_DATA_KEY = "app_ctx"


@dataclass
class AppContext:
    settings: Settings
    redis: RedisClient
    users: RedisStore  # primary persistent store (users, UIDs, language, settings, groups, stats)
    account_service: AccountService
    character_service: CharacterService
    abyss_service: AbyssService
    theater_service: TheaterService
    banner_service: BannerService
    build_service: BuildService
    stats_service: StatsService
    renderer: Renderer
    started_at: float

    async def language_for(self, telegram_user_id: int) -> str:
        """Resolve a user's preferred language (defaulting to the configured default)."""
        return await self.users.get_language(telegram_user_id, self.settings.default_language)


def build_app_context(settings: Settings | None = None) -> AppContext:
    """Construct the full dependency graph."""
    settings = settings or get_settings()

    redis = RedisClient(settings.redis_url)
    store = RedisStore(redis.client)
    showcase_cache = RedisCache(redis.client, ttl=settings.enka_cache_ttl, prefix="cache")

    enka = EnkaClient(language=settings.default_language)
    akasha = AkashaClient()

    started_at = time.time()

    account_service = AccountService(store, default_language=settings.default_language)
    character_service = CharacterService(enka, akasha, showcase_cache, ttl=settings.enka_cache_ttl)
    abyss_service = AbyssService(character_service)
    theater_service = TheaterService(character_service)
    banner_service = BannerService()
    build_service = BuildService()
    stats_service = StatsService(store, redis, started_at)

    return AppContext(
        settings=settings,
        redis=redis,
        users=store,
        account_service=account_service,
        character_service=character_service,
        abyss_service=abyss_service,
        theater_service=theater_service,
        banner_service=banner_service,
        build_service=build_service,
        stats_service=stats_service,
        renderer=get_renderer(),
        started_at=started_at,
    )
