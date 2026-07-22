"""Character showcase business logic.

Aggregates Enka showcase data with best-effort Akasha rankings, caches the combined
result per UID, and exposes helpers the command layer uses for the browsing flow
(list + open one character). No Telegram or rendering concerns here.
"""

from __future__ import annotations

from bot.api.akasha_client import AkashaClient
from bot.api.enka_client import EnkaClient
from bot.cache.cache import ResponseCache
from bot.database.repository import CacheMetaRepository
from bot.models.character import Character
from bot.models.player import Showcase
from bot.utils.errors import CharacterNotFound
from bot.utils.logging import get_logger

logger = get_logger(__name__)


class CharacterService:
    """Fetches, enriches, and caches player showcases."""

    def __init__(
        self,
        enka: EnkaClient,
        akasha: AkashaClient,
        cache: ResponseCache,
        cache_meta: CacheMetaRepository | None = None,
    ) -> None:
        self._enka = enka
        self._akasha = akasha
        self._cache = cache
        self._cache_meta = cache_meta

    async def get_showcase(self, uid: str, language: str = "en") -> Showcase:
        """Return a cached (or freshly fetched + enriched) showcase for a UID."""
        key = ("showcase", uid, language)

        async def _load() -> Showcase:
            showcase = await self._enka.fetch_showcase(uid, language)
            await self._enrich_rankings(uid, showcase)
            if self._cache_meta is not None:
                try:
                    await self._cache_meta.touch("enka", uid)
                except Exception as exc:  # noqa: BLE001 - metadata is non-critical
                    logger.debug("cache_meta touch failed: %s", exc)
            return showcase

        return await self._cache.get_or_set(key, _load)

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
