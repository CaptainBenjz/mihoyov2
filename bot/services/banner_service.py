"""Banner information business logic.

Reads current/upcoming banners from a bundled JSON resource (``bot/resources/banners.json``).
Swap the file for a live source later without changing callers. Never raises: an unreadable
or empty file yields an empty board that the command layer reports gracefully.
"""

from __future__ import annotations

import json
from pathlib import Path

from bot.models.banner import Banner, BannerBoard
from bot.utils.logging import get_logger

logger = get_logger(__name__)

_RESOURCE = Path(__file__).resolve().parent.parent / "resources" / "banners.json"


class BannerService:
    def __init__(self, resource_path: Path | None = None) -> None:
        self._path = resource_path or _RESOURCE

    async def get_banners(self) -> BannerBoard:
        data = self._read()
        return BannerBoard(
            current=[self._to_banner(b) for b in data.get("current", [])],
            upcoming=[self._to_banner(b) for b in data.get("upcoming", [])],
        )

    def _read(self) -> dict:
        try:
            with self._path.open(encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read banners resource: %s", exc)
            return {}

    @staticmethod
    def _to_banner(raw: dict) -> Banner:
        return Banner(
            name=str(raw.get("name", "?")),
            kind=str(raw.get("kind", "character")),
            featured=list(raw.get("featured", []) or []),
            start=raw.get("start"),
            end=raw.get("end"),
            version=raw.get("version"),
        )
