"""Tests for CharacterService using mocked API clients (no network)."""

from __future__ import annotations

import pytest

from bot.cache.cache import ResponseCache
from bot.models.character import Character, CharacterStats
from bot.models.player import PlayerInfo, Showcase
from bot.models.ranking import Ranking
from bot.services.character_service import CharacterService
from bot.utils.errors import CharacterNotFound


class FakeEnka:
    def __init__(self, showcase):
        self.showcase = showcase
        self.calls = 0

    async def fetch_showcase(self, uid, language="en"):
        self.calls += 1
        return self.showcase


class FakeAkasha:
    def __init__(self, rankings=None):
        self.rankings = rankings or {}

    async def fetch_rankings(self, uid):
        return self.rankings


def _showcase():
    return Showcase(
        player=PlayerInfo(uid="901211014", nickname="Traveler", level=60),
        characters=[
            Character(id="10000046", name="Hu Tao", level=90, stats=CharacterStats(hp=15000)),
            Character(id="10000002", name="Ayaka", level=80, stats=CharacterStats(atk=2000)),
        ],
    )


async def test_get_showcase_caches_result():
    enka = FakeEnka(_showcase())
    service = CharacterService(enka, FakeAkasha(), ResponseCache(ttl=60))
    await service.get_showcase("901211014")
    await service.get_showcase("901211014")
    assert enka.calls == 1  # second call served from cache


async def test_ranking_enrichment_best_effort():
    ranking = Ranking(rank=5, total_players=1000, top_percent=0.5)
    enka = FakeEnka(_showcase())
    service = CharacterService(enka, FakeAkasha({"10000046": ranking}), ResponseCache(ttl=60))
    showcase = await service.get_showcase("901211014")
    hutao = showcase.get_character("10000046")
    assert hutao.ranking is not None and hutao.ranking.rank == 5
    # Character without ranking data stays None.
    assert showcase.get_character("10000002").ranking is None


async def test_get_character_missing_raises():
    service = CharacterService(FakeEnka(_showcase()), FakeAkasha(), ResponseCache(ttl=60))
    with pytest.raises(CharacterNotFound):
        await service.get_character("901211014", "99999999")


async def test_ranking_failure_does_not_break_showcase():
    class BrokenAkasha:
        async def fetch_rankings(self, uid):
            raise RuntimeError("akasha down")

    service = CharacterService(FakeEnka(_showcase()), BrokenAkasha(), ResponseCache(ttl=60))
    showcase = await service.get_showcase("901211014")  # must not raise
    assert len(showcase.characters) == 2
