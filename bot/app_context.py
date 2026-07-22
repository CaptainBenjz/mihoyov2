"""Application context: the dependency container shared across all handlers.

Built once at startup and stored on ``Application.bot_data``. Handlers pull services from
here instead of constructing them, which keeps handlers thin and makes wiring/testing easy.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.api.akasha_client import AkashaClient
from bot.api.enka_client import EnkaClient
from bot.cache.cache import ResponseCache
from bot.config import Settings, get_settings
from bot.database.repository import CacheMetaRepository, UserRepository
from bot.renderer.base import Renderer, get_renderer
from bot.services.abyss_service import AbyssService
from bot.services.account_service import AccountService
from bot.services.banner_service import BannerService
from bot.services.build_service import BuildService
from bot.services.character_service import CharacterService
from bot.services.theater_service import TheaterService

# Key under which the context is stored in Application.bot_data.
BOT_DATA_KEY = "app_ctx"


@dataclass
class AppContext:
    settings: Settings
    users: UserRepository
    cache_meta: CacheMetaRepository
    account_service: AccountService
    character_service: CharacterService
    abyss_service: AbyssService
    theater_service: TheaterService
    banner_service: BannerService
    build_service: BuildService
    renderer: Renderer

    async def language_for(self, telegram_user_id: int) -> str:
        """Resolve a user's preferred language (defaulting to the configured default)."""
        return await self.users.get_language(telegram_user_id, self.settings.default_language)


def build_app_context(settings: Settings | None = None) -> AppContext:
    """Construct the full dependency graph."""
    settings = settings or get_settings()

    users = UserRepository()
    cache_meta = CacheMetaRepository()

    enka = EnkaClient(language=settings.default_language)
    akasha = AkashaClient()

    enka_cache = ResponseCache(ttl=settings.enka_cache_ttl)

    account_service = AccountService(users, default_language=settings.default_language)
    character_service = CharacterService(enka, akasha, enka_cache, cache_meta)
    abyss_service = AbyssService(character_service)
    theater_service = TheaterService(character_service)
    banner_service = BannerService()
    build_service = BuildService()

    return AppContext(
        settings=settings,
        users=users,
        cache_meta=cache_meta,
        account_service=account_service,
        character_service=character_service,
        abyss_service=abyss_service,
        theater_service=theater_service,
        banner_service=banner_service,
        build_service=build_service,
        renderer=get_renderer(),
    )
