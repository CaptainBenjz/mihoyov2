"""Character showcase business logic.

Aggregates Enka showcase data with best-effort Akasha rankings, caches the combined result
per UID in Redis (as JSON, so it persists across restarts and respects rate limits), and
exposes helpers the command layer uses for the browsing flow. No Telegram or rendering here.
"""

from __future__ import annotations

import asyncio

from bot.api.akasha_client import AkashaClient
from bot.api.enka_client import EnkaClient
from bot.cache.redis_cache import RedisCache
from bot.models.character import Character
from bot.models.player import Showcase
from bot.models.ranking import Ranking
from bot.models.serialize import showcase_from_dict, showcase_to_dict
from bot.utils.errors import CharacterNotFound
from bot.utils.logging import get_logger
from bot.utils.timing import atimed

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
        """Return a cached (or freshly fetched + enriched) showcase for a UID.

        On a cache miss the Enka showcase fetch and the (independent) Akasha ranking fetch
        are issued **concurrently** — neither depends on the other's result — so a fresh
        lookup costs roughly ``max(enka, akasha)`` instead of ``enka + akasha``.
        """
        cache_key = f"{language}:{uid}"

        async with atimed("showcase.cache_read"):
            cached = await self._cache.get_json(_CACHE_NS, cache_key)
        if cached is not None:
            try:
                return showcase_from_dict(cached)
            except Exception as exc:  # noqa: BLE001 - corrupt cache -> refetch
                logger.debug("Discarding unreadable cached showcase for %s: %s", uid, exc)

        showcase, rankings = await self._fetch_concurrently(uid, language)
        self._attach_rankings(showcase, rankings)

        async with atimed("showcase.cache_write"):
            await self._cache.set_json(_CACHE_NS, cache_key, showcase_to_dict(showcase), ttl=self._ttl)
        return showcase

    async def _fetch_concurrently(
        self, uid: str, language: str
    ) -> tuple[Showcase, dict[str, Ranking]]:
        """Fetch the Enka showcase and Akasha rankings in parallel.

        The Enka result is authoritative: any Enka domain error (private profile, empty
        showcase, rate limit, …) propagates unchanged. Akasha is best-effort — a failure or
        slow response yields empty rankings and never affects the showcase.
        """
        async def _enka() -> Showcase:
            async with atimed("showcase.enka_fetch"):
                return await self._enka.fetch_showcase(uid, language)

        async def _akasha() -> dict[str, Ranking]:
            async with atimed("showcase.akasha_fetch"):
                try:
                    return await self._akasha.fetch_rankings(uid)
                except Exception as exc:  # noqa: BLE001 - rankings must never break the flow
                    logger.info("Ranking enrichment skipped for %s: %s", uid, exc)
                    return {}

        showcase_res, rankings_res = await asyncio.gather(
            _enka(), _akasha(), return_exceptions=True
        )
        # Enka error is authoritative — re-raise it (Akasha result is discarded).
        if isinstance(showcase_res, BaseException):
            raise showcase_res
        rankings = {} if isinstance(rankings_res, BaseException) else rankings_res
        return showcase_res, rankings

    @staticmethod
    def _attach_rankings(showcase: Showcase, rankings: dict[str, Ranking]) -> None:
        for character in showcase.characters:
            ranking = rankings.get(character.id)
            if ranking is not None and ranking.available:
                character.ranking = ranking

    async def get_character(self, uid: str, char_id: str, language: str = "en") -> Character:
        """Return a single character from the (cached) showcase."""
        showcase = await self.get_showcase(uid, language)
        character = showcase.get_character(char_id)
        if character is None:
            raise CharacterNotFound(f"{char_id} not in showcase for {uid}")
        return character
