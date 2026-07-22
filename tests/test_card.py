"""Tests for the character profile card: caption, element theme, and render output."""

from __future__ import annotations

from bot.commands.characters import _build_caption
from bot.models.artifact import Artifact, ArtifactStat
from bot.models.character import Character, CharacterStats, Talent
from bot.models.player import PlayerInfo
from bot.models.ranking import Ranking
from bot.models.weapon import Weapon
from bot.renderer import card_layout
from bot.renderer.context import CharacterCardContext
from bot.renderer.pillow_renderer import PillowRenderer
from bot.utils.text import strip_custom_emoji

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _character(**kw) -> Character:
    base = dict(
        id="10000046", name="Hu Tao", element="Fire", rarity=5, level=90, constellation=1,
        weapon=Weapon(name="Staff of Homa", level=90, refinement=1, rarity=5),
        talents=[Talent("Normal", 10), Talent("Skill", 9), Talent("Burst", 9)],
        artifacts=[
            Artifact(slot="Flower", set_name="Crimson Witch", rarity=5,
                     main_stat=ArtifactStat("HP", 4780),
                     sub_stats=[ArtifactStat("CRIT Rate", 7.8), ArtifactStat("ATK%", 9.3)]),
        ],
        stats=CharacterStats(hp=15552, atk=2100, defense=876, crit_rate=72.4, crit_dmg=241.0,
                             energy_recharge=128.0, elemental_mastery=120,
                             extra={"FIGHT_PROP_FIRE_ADD_HURT": 0.616}),
    )
    base.update(kw)
    return Character(**base)


def test_caption_with_ranking():
    ch = _character(ranking=Ranking(rank=2147, total_players=100000, top_percent=0.8,
                                    calculation_name="Hypercarry"))
    cap = _build_caption(ch, PlayerInfo(uid="1", nickname="Traveler"))
    assert "Hu Tao" in cap and "Traveler" in cap
    assert "Rank: #2,147" in cap
    assert "Top 0.8%" in cap
    assert "Category: Hypercarry" in cap
    assert "tg-emoji" in cap  # custom emoji present


def test_caption_missing_values_become_dashes():
    ch = _character(ranking=None)
    cap = _build_caption(ch, PlayerInfo(uid="1", nickname=""))
    assert "Rank: #--" in cap
    assert "Top --%" in cap
    assert "Category: --" in cap
    # And it degrades to plain emoji cleanly.
    assert "tg-emoji" not in strip_custom_emoji(cap)


def test_element_aliases():
    assert card_layout.canonical_element("Fire") == "PYRO"
    assert card_layout.canonical_element("Water") == "HYDRO"
    assert card_layout.canonical_element("Grass") == "DENDRO"
    assert card_layout.theme_for("Ice") is card_layout.ELEMENT_THEMES["CRYO"]
    assert card_layout.theme_for(None) is card_layout.DEFAULT_THEME


def test_render_profile_card_produces_png():
    ch = _character(ranking=Ranking(rank=5, top_percent=1.2, calculation_name="DPS"))
    png = PillowRenderer().render_profile_card(
        CharacterCardContext(language="en", character=ch, player=PlayerInfo(uid="1", nickname="T"),
                             portrait=None)
    )
    assert png.startswith(PNG_MAGIC)


def test_render_profile_card_no_ranking_still_renders():
    ch = _character(ranking=None)
    png = PillowRenderer().render_profile_card(
        CharacterCardContext(language="en", character=ch, player=PlayerInfo(uid="1"))
    )
    assert png.startswith(PNG_MAGIC)
