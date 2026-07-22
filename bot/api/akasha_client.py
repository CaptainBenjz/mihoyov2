"""Async wrapper over the Akasha System API (``akasha-py`` package).

Akasha provides leaderboard/ranking data. Its upstream API is unofficial and changes
without notice, so this client is **best-effort**: every failure is swallowed into an
empty result (or a domain error the caller treats as "no ranking"), and it never blocks
the core character flow. Rankings simply don't appear when Akasha is unavailable.

Returns a mapping of character id -> :class:`bot.models.ranking.Ranking`.
"""

from __future__ import annotations

from typing import Any

from bot.models.ranking import Ranking
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_LEADERBOARD_URL = "https://akasha.cv/leaderboards/{calc_id}"


class AkashaClient:
    """Thin async client around ``akasha.AkashaAPI``. Best-effort; never raises to callers."""

    async def fetch_rankings(self, uid: str) -> dict[str, Ranking]:
        """Return per-character rankings for a UID. Empty dict if unavailable."""
        try:
            raw = await self._fetch_raw(uid)
        except Exception as exc:  # noqa: BLE001 - best effort; degrade silently
            logger.info("Akasha rankings unavailable for %s: %s", uid, exc)
            return {}
        return self._map(raw)

    async def _fetch_raw(self, uid: str) -> list[Any]:
        try:
            import akasha  # type: ignore
        except ImportError:  # pragma: no cover - depends on environment
            logger.info("akasha-py not installed; skipping rankings")
            return []

        api = akasha.AkashaAPI()
        try:
            # The wrapper exposes calculations per user; each entry ~ one character build.
            calcs = await api.get_calculations_for_user(int(uid))
            return list(calcs) if calcs is not None else []
        finally:
            close = getattr(api, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    pass

    def _map(self, calcs: list[Any]) -> dict[str, Ranking]:
        out: dict[str, Ranking] = {}
        for calc in calcs:
            char_id = _first_str(calc, "character_id", "avatar_id", "characterId")
            if char_id is None:
                continue
            calc_id = _first_str(calc, "calculation_id", "id", "calculationId")
            ranking = Ranking(
                calculation_id=calc_id,
                calculation_name=_first_str(calc, "name", "calculation_name"),
                rank=_first_int(calc, "ranking", "rank"),
                total_players=_first_int(calc, "out_of", "total", "outOf"),
                top_percent=_first_float(calc, "top_percent", "priority", "topPercent"),
                leaderboard_url=_LEADERBOARD_URL.format(calc_id=calc_id) if calc_id else None,
                damage=_first_float(calc, "result", "damage"),
            )
            # Keep the strongest (best-ranked) calc per character.
            existing = out.get(char_id)
            if existing is None or _better(ranking, existing):
                out[char_id] = ranking
        return out


def _better(a: Ranking, b: Ranking) -> bool:
    """Whether ranking ``a`` is better (lower rank number) than ``b``."""
    if a.rank is None:
        return False
    if b.rank is None:
        return True
    return a.rank < b.rank


def _attr(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _first_str(obj: Any, *names: str) -> str | None:
    for n in names:
        v = _attr(obj, n)
        if v is not None:
            return str(v)
    return None


def _first_int(obj: Any, *names: str) -> int | None:
    for n in names:
        v = _attr(obj, n)
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return None


def _first_float(obj: Any, *names: str) -> float | None:
    for n in names:
        v = _attr(obj, n)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None
