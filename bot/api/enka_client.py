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
from bot.models.character import Character, CharacterStats, Talent
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
        )

    def _map_character(self, rc: Any) -> Character:
        weapon = self._map_weapon(_get(rc, "weapon"))
        talents = self._map_talents(_get(rc, "talents", default=[]) or [])
        artifacts = self._map_artifacts(_get(rc, "artifacts", default=[]) or [])
        stats = self._map_stats(_get(rc, "stats", default=None))
        return Character(
            id=str(_get(rc, "id", "avatar_id", default="")),
            name=str(_get(rc, "name", default="?") or "?"),
            element=_opt_str(_get(rc, "element")),
            rarity=_opt_int(_get(rc, "rarity")),
            level=int(_num(_get(rc, "level", default=1), 1)),
            ascension=int(_num(_get(rc, "ascension", default=0))),
            constellation=int(_num(_get(rc, "constellation", "constellations_unlocked", default=0))),
            friendship=_opt_int(_get(rc, "friendship_level", "friendship")),
            icon=self._icon_key(_get(rc, "icon", "side_icon")),
            art=self._icon_key(_get(rc, "art", "splash", "gacha_icon")),
            weapon=weapon,
            talents=talents,
            artifacts=artifacts,
            stats=stats,
        )

    def _map_weapon(self, rw: Any) -> Weapon | None:
        if rw is None:
            return None
        return Weapon(
            name=str(_get(rw, "name", default="?") or "?"),
            level=int(_num(_get(rw, "level", default=1), 1)),
            refinement=int(_num(_get(rw, "refinement", default=1), 1)),
            ascension=int(_num(_get(rw, "ascension", default=0))),
            rarity=_opt_int(_get(rw, "rarity")),
            icon=self._icon_key(_get(rw, "icon")),
            main_stat_name=_opt_str(_get(rw, "main_stat.name", "main_stat_name")),
            main_stat_value=_opt_float(_get(rw, "main_stat.value", "main_stat_value")),
            sub_stat_name=_opt_str(_get(rw, "sub_stat.name", "sub_stat_name")),
            sub_stat_value=_opt_float(_get(rw, "sub_stat.value", "sub_stat_value")),
        )

    def _map_talents(self, rts: Any) -> list[Talent]:
        talents: list[Talent] = []
        for rt in rts:
            talents.append(
                Talent(
                    name=str(_get(rt, "name", default="?") or "?"),
                    level=int(_num(_get(rt, "level", default=0))),
                )
            )
        return talents

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
                    slot=str(_get(ra, "equip_type", "slot", "pos", default="?") or "?"),
                    set_name=_opt_str(_get(ra, "set_name", "set.name")),
                    level=int(_num(_get(ra, "level", default=0))),
                    rarity=_opt_int(_get(ra, "rarity")),
                    icon=self._icon_key(_get(ra, "icon")),
                    main_stat=main_stat,
                    sub_stats=subs,
                )
            )
        return artifacts

    def _map_stats(self, rstats: Any) -> CharacterStats:
        """Map the library's stat collection into our stat block.

        Enka exposes stats as a mapping of fight-prop -> value object. We pull the ones we
        model explicitly and keep everything else in ``extra`` so nothing is lost.
        """
        stats = CharacterStats()
        if rstats is None:
            return stats

        # Try named-property access first (common in the wrapper), then dict iteration.
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
            val = _get(rstats, *candidates)
            value = self._stat_value(val)
            if value is not None:
                setattr(stats, field_name, value)

        # Sweep any dict-like collection into extra (keyed by stat name).
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
                if value is not None:
                    stats.extra.setdefault(name, value)
        return stats

    @staticmethod
    def _stat_value(val: Any) -> float | None:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        inner = _get(val, "value")
        return _num(inner) if inner is not None else None

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
