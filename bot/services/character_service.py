"""Character showcase business logic.

Aggregates Enka showcase data with best-effort Akasha rankings, caches the combined result
per UID in Redis (as JSON, so it persists across restarts and respects rate limits), and
exposes helpers the command layer uses for the browsing flow. No Telegram or rendering here.
"""

from __future__ import annotations

from bot.api.akasha_client import AkashaClient
from bot.api.enka_client import EnkaClient
from bot.cache.redis_cache import RedisCache
from bot.models.character import Character
from bot.models.player import Showcase
from bot.models.serialize import showcase_from_dict, showcase_to_dict
from bot.utils.errors import CharacterNotFound
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_CACHE_NS = "showcase"


class CharacterService:
    """Fetches, enriches, and caches player showcases."""

    def __init__(
        self,
        enka: EnkaClient,
        akasha: AkashaClient,
        cache: RedisCache,
        ttl: int = 300,
    ) -> None:
        self._enka = enka
        self._akasha = akasha
        self._cache = cache
        self._ttl = ttl

    async def get_showcase(self, uid: str, language: str = "en") -> Showcase:
        """Return a cached (or freshly fetched + enriched) showcase for a UID."""
        cache_key = f"{language}:{uid}"

        cached = await self._cache.get_json(_CACHE_NS, cache_key)
        if cached is not None:
            try:
                return showcase_from_dict(cached)
            except Exception as exc:  # noqa: BLE001 - corrupt cache -> refetch
                logger.debug("Discarding unreadable cached showcase for %s: %s", uid, exc)

        showcase = await self._enka.fetch_showcase(uid, language)
        await self._enrich_rankings(uid, showcase)
        await self._cache.set_json(_CACHE_NS, cache_key, showcase_to_dict(showcase), ttl=self._ttl)
        return showcase

    async def get_character(self, uid: str, char_id: str, language: str = "en") -> Character:
        """Return a single character from the (cached) showcase."""
        showcase = await self.get_showcase(uid, language)
        character = showcase.get_character(char_id)
        if character is None:
            raise CharacterNotFound(f"{char_id} not in showcase for {uid}")
        return character

    async def _enrich_rankings(self, uid: str, showcase: Showcase) -> None:
        """Attach Akasha rankings to characters. Best-effort: failures are ignored."""
        try:
            rankings = await self._akasha.fetch_rankings(uid)
        except Exception as exc:  # noqa: BLE001 - never let rankings break the flow
            logger.info("Ranking enrichment skipped for %s: %s", uid, exc)
            return
        for character in showcase.characters:
            ranking = rankings.get(character.id)
            if ranking is not None and ranking.available:
                character.ranking = ranking
