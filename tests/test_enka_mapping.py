"""Tests for Enka client error mapping and defensive field mapping."""

from __future__ import annotations

import pytest

from bot.api.enka_client import EnkaClient
from bot.utils.errors import ApiUnavailable, NetworkError, ProfilePrivate, RateLimited


@pytest.mark.parametrize(
    "exc, expected",
    [
        (Exception("HTTP 429 rate limit"), RateLimited),
        (TimeoutError("connection timeout"), NetworkError),
        (Exception("player does not exist"), ProfilePrivate),
        (Exception("something weird"), ApiUnavailable),
    ],
)
def test_error_mapping(exc, expected):
    with pytest.raises(expected):
        EnkaClient._raise_mapped(exc)


class _FakeStat:
    def __init__(self, value):
        self.value = value


class _FakeRawChar:
    id = "10000046"
    name = "Hu Tao"
    level = 90
    constellation = 6
    weapon = None
    talents = []
    artifacts = []

    class _Stats:
        max_hp = _FakeStat(15000)
        atk = _FakeStat(2000)
        crit_rate = _FakeStat(70.5)

    stats = _Stats()


class _FakeRawPlayer:
    nickname = "Traveler"
    level = 60
    world_level = 8
    signature = "hi"


class _FakeRawShowcase:
    player = _FakeRawPlayer()
    characters = [_FakeRawChar()]


def test_map_showcase_defensive():
    client = EnkaClient()
    showcase = client._map_showcase("901211014", _FakeRawShowcase())
    assert showcase.player.nickname == "Traveler"
    assert len(showcase.characters) == 1
    c = showcase.characters[0]
    assert c.name == "Hu Tao"
    assert c.level == 90
    assert c.stats.hp == 15000
    assert c.stats.crit_rate == 70.5
