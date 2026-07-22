"""Character artwork retrieval + local caching.

Akasha has no image API, so we use Enka's official character art (the same source
akasha.cv relies on): ``character.icon.gacha`` (full splash) with a fallback to the front
icon. Downloaded art is cached on disk (``assets/characters/<key>.png``) so new characters
work automatically and repeat renders don't re-download. Everything is best-effort: on any
failure the service returns ``None`` and the renderer shows the empty portrait frame.
"""

from __future__ import annotations

import io
from pathlib import Path

import aiohttp
from PIL import Image

from bot.config import get_settings
from bot.models.character import Character
from bot.utils.logging import get_logger

logger = get_logger(__name__)


class ArtworkService:
    def __init__(self) -> None:
        self._cache_dir = get_settings().assets_path / "characters"

    def _candidate_urls(self, character: Character) -> list[str]:
        """Prefer full splash art, then the front portrait icon."""
        urls: list[str] = []
        icon = getattr(character, "_icon_obj", None)
        # character.art / character.icon are reduced to filename keys in the mapper; we also
        # accept a full URL if present. Reconstruct Enka CDN URLs from the stored key.
        for key in (character.art, character.icon):
            if not key:
                continue
            if key.startswith("http"):
                urls.append(key)
            else:
                urls.append(f"https://enka.network/ui/{key}")
        return urls

    def _cache_file(self, character: Character) -> Path:
        stem = (character.art or character.icon or character.id or "unknown").rsplit("/", 1)[-1]
        stem = stem.replace(".png", "").replace(".jpg", "")
        return self._cache_dir / f"{stem}.png"

    async def get_portrait(self, character: Character) -> Image.Image | None:
        """Return the character's artwork as an RGBA image, or None if unavailable."""
        cache_file = self._cache_file(character)
        if cache_file.exists():
            try:
                return Image.open(cache_file).convert("RGBA")
            except Exception:  # noqa: BLE001 - corrupt cache -> refetch
                pass

        for url in self._candidate_urls(character):
            img = await self._download_image(url)
            if img is not None:
                try:
                    self._cache_dir.mkdir(parents=True, exist_ok=True)
                    img.save(cache_file)
                except Exception as exc:  # noqa: BLE001 - caching is non-critical
                    logger.debug("Could not cache portrait %s: %s", cache_file, exc)
                return img
        logger.info("No artwork available for character %s", character.name)
        return None

    async def _download_image(self, url: str) -> Image.Image | None:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (MihoyoBot)"}
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
            return Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception as exc:  # noqa: BLE001 - best effort
            logger.debug("Artwork download failed (%s): %s", url, exc)
            return None
