"""Async wrapper over the Enka.Network API (``enka-api`` package).

Responsibilities:
    * Fetch a player's showcase for a UID.
    * Map the library's response objects into our framework-agnostic domain models.
    * Translate library / network errors into :mod:`bot.utils.errors` domain exceptions.

The mapping is deliberately defensive: Enka's schema evolves and the wrapper's attribute
names can shift between versions, so every field is read via ``getattr``/helpers and a
failure to map one field never discards the whole character. If the upstream library or
API shape changes, this file is the single place to adjust.
"""

from __future__ import annotations

from typing import Any

from bot.models.artifact import Artifact, ArtifactStat
from bot.models.character import Character, CharacterStats, ConstellationNode, Talent
from bot.models.player import PlayerInfo, Showcase
from bot.models.weapon import Weapon
from bot.utils.errors import (
    ApiUnavailable,
    EmptyShowcase,
    NetworkError,
    ProfilePrivate,
    RateLimited,
)
from bot.utils.logging import get_logger

logger = get_logger(__name__)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Return the first present, non-None attribute among ``names`` (dot-paths allowed)."""
    for name in names:
        cur = obj
        ok = True
        for part in name.split("."):
            if cur is None:
                ok = False
                break
            cur = getattr(cur, part, None)
        if ok and cur is not None:
            return cur
    return default


class EnkaClient:
    """Thin async client around ``enka.GenshinClient``.

    A fresh library client is created per call inside an ``async with`` block, which is the
    usage the library expects and keeps us stateless and safe under concurrency.
    """

    def __init__(self, language: str = "en") -> None:
        self._language = language

    # -- public API --------------------------------------------------------
    async def fetch_showcase(self, uid: str, language: str | None = None) -> Showcase:
        """Fetch and map a player's showcase. Raises a domain error on failure."""
        raw = await self._fetch_raw(uid, language or self._language)
        return self._map_showcase(uid, raw)

    # -- internals ---------------------------------------------------------
    async def _fetch_raw(self, uid: str, language: str) -> Any:
        # Imported lazily so importing this module never requires the network library.
        try:
            import enka  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ApiUnavailable("enka-api not installed") from exc

        lang = self._resolve_language(enka, language)
        try:
            async with enka.GenshinClient(lang) as client:
                return await client.fetch_showcase(int(uid))
        except Exception as exc:  # noqa: BLE001 - normalize any library error
            self._raise_mapped(exc)

    @staticmethod
    def _resolve_language(enka_module: Any, language: str) -> Any:
        """Map our language code to the library's language enum, defaulting to English."""
        mapping = {
            "en": "ENGLISH",
            "es": "SPANISH",
            "it": "ITALIAN",
            "ja": "JAPANESE",
            "zh": "SIMPLIFIED_CHINESE",
        }
        try:
            lang_enum = enka_module.gi.Language
            return getattr(lang_enum, mapping.get(language, "ENGLISH"), lang_enum.ENGLISH)
        except Exception:  # noqa: BLE001 - fall back to whatever the lib accepts
            return getattr(enka_module, "Language", None)

    @staticmethod
    def _raise_mapped(exc: Exception) -> None:
        """Translate a library exception into a domain error and raise it."""
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        if "ratelimit" in name or "429" in text or "rate limit" in text:
            raise RateLimited(str(exc)) from exc
        if "timeout" in name or "timeout" in text or "connection" in text:
            raise NetworkError(str(exc)) from exc
        if any(k in name for k in ("playerdoesnotexist", "notfound")) or "does not exist" in text:
            # UID is valid-format but no such player / no public data.
            raise ProfilePrivate(str(exc)) from exc
        if "maintenance" in name or "maintenance" in text:
            raise ApiUnavailable(str(exc)) from exc
        # Fallback: treat unknown upstream problems as API unavailable (never crash).
        logger.warning("Unmapped Enka error %s: %s", type(exc).__name__, exc)
        raise ApiUnavailable(str(exc)) from exc

    # -- mapping -----------------------------------------------------------
    def _map_showcase(self, uid: str, raw: Any) -> Showcase:
        player = self._map_player(uid, _get(raw, "player"))
        raw_chars = _get(raw, "characters", default=[]) or []
        characters = []
        for rc in raw_chars:
            try:
                characters.append(self._map_character(rc))
            except Exception as exc:  # noqa: BLE001 - skip a bad character, keep the rest
                logger.warning("Failed to map a character: %s", exc)
        if not characters:
            # Public profile but empty/hidden showcase.
            raise EmptyShowcase(f"No characters in showcase for {uid}")
        return Showcase(player=player, characters=characters)

    def _map_player(self, uid: str, rp: Any) -> PlayerInfo:
        if rp is None:
            return PlayerInfo(uid=uid)
        return PlayerInfo(
            uid=uid,
            nickname=str(_get(rp, "nickname", default="") or ""),
            level=int(_num(_get(rp, "level", default=0))),
            world_level=int(_num(_get(rp, "world_level", "worldLevel", default=0))),
            signature=str(_get(rp, "signature", default="") or ""),
            namecard=self._icon_key(_get(rp, "namecard", "name_card")),
            profile_icon=self._icon_key(_get(rp, "profile_picture_icon", "profile_picture", "icon")),
            achievements=_opt_int(_get(rp, "achievements", "achievement_count")),
            abyss_floor=_opt_int(_get(rp, "abyss_floor", "spiral_abyss_floor")),
            abyss_chamber=_opt_int(_get(rp, "abyss_level", "spiral_abyss_level", "abyss_chamber")),
            theater_act=_opt_int(_get(rp, "theater_act")),
            theater_stars=_opt_int(_get(rp, "theater_stars")),
        )

    def _map_character(self, rc: Any) -> Character:
        weapon = self._map_weapon(_get(rc, "weapon"))
        talents = self._map_talents(_get(rc, "talents", default=[]) or [])
        constellations = self._map_constellations(_get(rc, "constellations", default=[]) or [])
        artifacts = self._map_artifacts(_get(rc, "artifacts", default=[]) or [])
        stats = self._map_stats(_get(rc, "stats", default=None))
        # The Enka icon object exposes full CDN URLs: gacha (splash), front, circle, side.
        icon_obj = _get(rc, "icon")
        return Character(
            id=str(_get(rc, "id", "avatar_id", default="")),
            name=str(_get(rc, "name", default="?") or "?"),
            element=_opt_str(_get(rc, "element")),
            rarity=_opt_int(_get(rc, "rarity")),
            level=int(_num(_get(rc, "level", default=1), 1)),
            ascension=int(_num(_get(rc, "ascension", default=0))),
            constellation=sum(1 for n in constellations if n.unlocked)
            or int(_num(_get(rc, "constellations_unlocked", "constellation", default=0))),
            friendship=_opt_int(_get(rc, "friendship_level", "friendship")),
            icon=self._icon_key(_icon_url(icon_obj, "front", "circle", "side")),
            art=_icon_url(icon_obj, "gacha", "front", "circle"),  # full splash-art URL
            weapon=weapon,
            talents=talents,
            constellations=constellations,
            artifacts=artifacts,
            stats=stats,
        )

    def _map_weapon(self, rw: Any) -> Weapon | None:
        if rw is None:
            return None
        icon = _as_url(_get(rw, "icon"))
        # enka's Weapon exposes stats as a list[Stat] (``weaponStats``): the main stat
        # (FIGHT_PROP_BASE_ATTACK) plus at most one secondary stat. There is no
        # ``main_stat``/``sub_stat``/``type`` attribute on the 2.5.20 model, so read the list.
        stats = list(_get(rw, "stats", default=[]) or [])
        main = next(
            (s for s in stats if getattr(getattr(s, "type", None), "name", "") == "FIGHT_PROP_BASE_ATTACK"),
            None,
        )
        if main is None and stats:
            main = stats[0]
        sub = next((s for s in stats if s is not main), None)
        return Weapon(
            name=str(_get(rw, "name", default="?") or "?"),
            level=int(_num(_get(rw, "level", default=1), 1)),
            refinement=int(_num(_get(rw, "refinement", default=1), 1)),
            ascension=int(_num(_get(rw, "ascension", default=0))),
            rarity=_opt_int(_get(rw, "rarity")),
            # The weapon class (Sword/Claymore/Polearm/Bow/Catalyst) is not a scalar field on
            # enka's Weapon; it is encoded in the icon filename (``UI_EquipIcon_Sword_...``).
            weapon_type=_weapon_type(icon),
            icon=icon,
            main_stat_name=_opt_str(_get(main, "name")) if main is not None else None,
            main_stat_value=_opt_float(_get(main, "value")) if main is not None else None,
            sub_stat_name=_opt_str(_get(sub, "name")) if sub is not None else None,
            sub_stat_value=_opt_float(_get(sub, "value")) if sub is not None else None,
        )

    def _map_talents(self, rts: Any) -> list[Talent]:
        talents: list[Talent] = []
        for rt in rts:
            talents.append(
                Talent(
                    name=str(_get(rt, "name", default="?") or "?"),
                    level=int(_num(_get(rt, "level", default=0))),
                    icon=_as_url(_get(rt, "icon")),
                )
            )
        return talents

    def _map_constellations(self, rcs: Any) -> list[ConstellationNode]:
        nodes: list[ConstellationNode] = []
        for rc in rcs or []:
            nodes.append(
                ConstellationNode(
                    name=str(_get(rc, "name", default="") or ""),
                    unlocked=bool(_get(rc, "unlocked", default=False)),
                    icon=_as_url(_get(rc, "icon")),
                )
            )
        return nodes

    def _map_artifacts(self, ras: Any) -> list[Artifact]:
        artifacts: list[Artifact] = []
        for ra in ras:
            main = _get(ra, "main_stat", "mainstat")
            main_stat = (
                ArtifactStat(
                    name=str(_get(main, "name", "type", default="") or ""),
                    value=_num(_get(main, "value", default=0)),
                    is_percent=bool(_get(main, "is_percentage", "is_percent", default=False)),
                )
                if main is not None
                else None
            )
            subs = []
            for rs in _get(ra, "sub_stats", "substats", default=[]) or []:
                subs.append(
                    ArtifactStat(
                        name=str(_get(rs, "name", "type", default="") or ""),
                        value=_num(_get(rs, "value", default=0)),
                        is_percent=bool(_get(rs, "is_percentage", "is_percent", default=False)),
                    )
                )
            artifacts.append(
                Artifact(
                    slot=self._slot_name(_get(ra, "equip_type", "slot", "pos")),
                    set_name=_opt_str(_get(ra, "set_name", "set.name")),
                    level=int(_num(_get(ra, "level", default=0))),
                    rarity=_opt_int(_get(ra, "rarity")),
                    icon=_as_url(_get(ra, "icon")),
                    main_stat=main_stat,
                    sub_stats=subs,
                )
            )
        return artifacts

    # Final-stat fight-prop -> our stat field. Percentage props are fractions (0.52 == 52%).
    _FIGHT_PROP_FIELD = {
        "FIGHT_PROP_MAX_HP": "hp",
        "FIGHT_PROP_CUR_ATTACK": "atk",
        "FIGHT_PROP_CUR_DEFENSE": "defense",
        "FIGHT_PROP_CRITICAL": "crit_rate",
        "FIGHT_PROP_CRITICAL_HURT": "crit_dmg",
        "FIGHT_PROP_CHARGE_EFFICIENCY": "energy_recharge",
        "FIGHT_PROP_ELEMENT_MASTERY": "elemental_mastery",
    }
    _FIGHT_PROP_PERCENT = {
        "FIGHT_PROP_CRITICAL",
        "FIGHT_PROP_CRITICAL_HURT",
        "FIGHT_PROP_CHARGE_EFFICIENCY",
    }

    def _map_stats(self, rstats: Any) -> CharacterStats:
        """Map the library's stat collection into our stat block.

        The GI client exposes ``character.stats`` as a ``dict[FightPropType, Stat]`` where
        each key has a ``FIGHT_PROP_*`` name and each value has ``.value``. Percentage props
        (crit rate/dmg, energy recharge) are fractions and are scaled to percentages here.
        Everything we don't model explicitly is kept in ``extra`` so nothing is lost.

        Falls back to named-attribute access for other/older library shapes.
        """
        stats = CharacterStats()
        if rstats is None:
            return stats

        # Preferred path: a dict-like mapping of FightPropType -> Stat.
        items = None
        if hasattr(rstats, "items"):
            try:
                items = list(rstats.items())
            except Exception:  # noqa: BLE001
                items = None

        if items:
            for key, val in items:
                name = str(getattr(key, "name", key))
                value = self._stat_value(val)
                if value is None:
                    continue
                if name in self._FIGHT_PROP_PERCENT:
                    value *= 100.0
                field = self._FIGHT_PROP_FIELD.get(name)
                if field is not None:
                    setattr(stats, field, value)
                else:
                    stats.extra.setdefault(name, value)
            return stats

        # Fallback: named-attribute access (other library shapes / test doubles).
        named = {
            "hp": ("max_hp", "hp"),
            "atk": ("atk", "attack"),
            "defense": ("def_", "defense", "def"),
            "crit_rate": ("crit_rate",),
            "crit_dmg": ("crit_dmg", "crit_damage"),
            "energy_recharge": ("energy_recharge",),
            "elemental_mastery": ("elemental_mastery",),
        }
        for field_name, candidates in named.items():
            value = self._stat_value(_get(rstats, *candidates))
            if value is not None:
                setattr(stats, field_name, value)
        return stats

    @staticmethod
    def _stat_value(val: Any) -> float | None:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        inner = _get(val, "value")
        return _num(inner) if inner is not None else None

    # Enka equip-type enum -> friendly artifact slot name. Handles both the enum name
    # (FLOWER/FEATHER/...) and the underlying value (EQUIP_BRACER/...).
    _SLOT_NAMES = {
        "FLOWER": "Flower", "EQUIP_BRACER": "Flower",
        "FEATHER": "Plume", "EQUIP_NECKLACE": "Plume",
        "SANDS": "Sands", "EQUIP_SHOES": "Sands",
        "GOBLET": "Goblet", "EQUIP_RING": "Goblet",
        "CIRCLET": "Circlet", "EQUIP_DRESS": "Circlet",
    }

    @classmethod
    def _slot_name(cls, val: Any) -> str:
        """Normalize an artifact equip type to a friendly slot name."""
        if val is None:
            return "?"
        raw = str(getattr(val, "name", val))
        return cls._SLOT_NAMES.get(raw, raw.title())

    @staticmethod
    def _icon_key(val: Any) -> str | None:
        """Reduce an icon object/URL to a stable key usable for asset lookup."""
        if val is None:
            return None
        if isinstance(val, str):
            return val.rsplit("/", 1)[-1]
        # Icon objects commonly expose a filename or url attribute.
        candidate = _get(val, "filename", "name", "url")
        if isinstance(candidate, str):
            return candidate.rsplit("/", 1)[-1]
        return None


def _as_url(val: Any) -> str | None:
    """Return a full icon URL. Enka icon objects stringify to their CDN URL; strings pass through."""
    if val is None:
        return None
    if isinstance(val, str):
        return val or None
    for attr in ("url", "gacha", "front", "circle"):
        v = getattr(val, attr, None)
        if isinstance(v, str) and v:
            return v
    text = str(val)
    return text if text.startswith("http") else None


def _weapon_type(val: Any) -> str | None:
    """Normalize an Enka weapon type (e.g. 'WEAPON_SWORD_ONE_HAND'/'ITEM_WEAPON') to a label."""
    if val is None:
        return None
    raw = str(getattr(val, "name", val)).upper()
    for label in ("SWORD", "CLAYMORE", "POLE", "BOW", "CATALYST"):
        if label in raw:
            return {"POLE": "Polearm"}.get(label, label.capitalize())
    return None


def _icon_url(icon_obj: Any, *attrs: str) -> str | None:
    """Return the first present URL attribute (e.g. gacha/front/circle) of an Enka Icon."""
    if icon_obj is None:
        return None
    for attr in attrs:
        val = getattr(icon_obj, attr, None)
        if isinstance(val, str) and val:
            return val
    return None


def _opt_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _opt_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _opt_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val)
    return s or None
