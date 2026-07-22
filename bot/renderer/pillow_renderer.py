"""Pillow rendering backend — placeholder layouts.

This phase intentionally produces simple, functional placeholder cards: a background,
optional artwork/frame slots pulled via the AssetLoader, and text blocks driven by the
domain data. The goal is a working rendering *pipeline* that commands can already call;
the premium visual design is a later phase and only replaces the drawing code here.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from bot.assets.loader import AssetLoader, get_asset_loader
from bot.renderer.base import Renderer
from bot.renderer.context import (
    AbyssCardContext,
    CharacterCardContext,
    TheaterCardContext,
)
from bot.translations.i18n import t

_CARD_SIZE = (900, 1200)
_BG = (30, 31, 41, 255)
_PANEL = (40, 42, 54, 255)
_ACCENT = (98, 114, 164, 255)
_TEXT = (248, 248, 242, 255)
_MUTED = (139, 145, 176, 255)


class PillowRenderer(Renderer):
    def __init__(self, assets: AssetLoader | None = None) -> None:
        self._assets = assets or get_asset_loader()
        self._font_cache: dict[int, ImageFont.ImageFont] = {}

    # -- fonts -------------------------------------------------------------
    def _font(self, size: int) -> ImageFont.ImageFont:
        if size not in self._font_cache:
            try:
                # Prefer a bundled/ui font if provided; otherwise Pillow's default.
                path = self._assets.resolve("ui", f"font_{size}.ttf") or self._assets.resolve("ui", "font.ttf")
                self._font_cache[size] = (
                    ImageFont.truetype(str(path), size) if path else ImageFont.load_default()
                )
            except (OSError, ValueError):
                self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    # -- canvas helpers ----------------------------------------------------
    def _canvas(self, ctx) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGBA", _CARD_SIZE, _BG)
        # Optional background asset (falls back to placeholder internally).
        if getattr(ctx, "background", None):
            bg = self._assets.load("backgrounds", ctx.background, size=_CARD_SIZE)
            img.alpha_composite(bg)
        draw = ImageDraw.Draw(img)
        return img, draw

    def _panel(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
        draw.rectangle(box, fill=_PANEL, outline=_ACCENT, width=2)

    def _text(self, draw, xy, text, *, size=28, color=_TEXT) -> int:
        draw.text(xy, text, font=self._font(size), fill=color)
        return xy[1] + size + 10

    def _to_png(self, img: Image.Image) -> bytes:
        buf = io.BytesIO()
        img.convert("RGBA").save(buf, format="PNG")
        return buf.getvalue()

    # -- cards -------------------------------------------------------------
    def render_character_card(self, ctx: CharacterCardContext) -> bytes:
        img, draw = self._canvas(ctx)
        lang = ctx.language
        c = ctx.character
        y = 40
        if c is None:
            self._text(draw, (40, y), t("error.character_not_found", lang), size=32)
            return self._to_png(img)

        # Artwork slot (placeholder-aware).
        art = self._assets.load("characters", c.art or c.icon or c.id or "unknown", size=(320, 320))
        img.alpha_composite(art, (40, 40))
        if ctx.frame:
            frame = self._assets.load("frames", ctx.frame, size=(320, 320))
            img.alpha_composite(frame, (40, 40))

        # Header text next to the artwork.
        x = 400
        y = self._text(draw, (x, 50), c.name, size=44)
        y = self._text(draw, (x, y), t("character.level", lang, level=c.level), size=28, color=_MUTED)
        y = self._text(draw, (x, y), t("character.constellation", lang, constellation=c.constellation),
                       size=28, color=_MUTED)
        if c.weapon:
            y = self._text(
                draw, (x, y),
                t("character.weapon", lang, name=c.weapon.name,
                  refinement=c.weapon.refinement, level=c.weapon.level),
                size=26, color=_MUTED,
            )

        # Stats panel.
        y = 400
        self._panel(draw, (40, y, 860, y + 300))
        y = self._text(draw, (60, y + 20), t("character.stats_title", lang), size=30)
        s = c.stats
        rows = [
            (t("stats.hp", lang), f"{s.hp:,.0f}"),
            (t("stats.atk", lang), f"{s.atk:,.0f}"),
            (t("stats.def", lang), f"{s.defense:,.0f}"),
            (t("stats.crit_rate", lang), f"{s.crit_rate:.1f}%"),
            (t("stats.crit_dmg", lang), f"{s.crit_dmg:.1f}%"),
            (t("stats.energy_recharge", lang), f"{s.energy_recharge:.1f}%"),
            (t("stats.elemental_mastery", lang), f"{s.elemental_mastery:,.0f}"),
        ]
        for label, value in rows:
            draw.text((60, y), label, font=self._font(24), fill=_MUTED)
            draw.text((520, y), value, font=self._font(24), fill=_TEXT)
            y += 34

        # Ranking panel (only if available).
        if c.ranking and c.ranking.available:
            ry = 730
            self._panel(draw, (40, ry, 860, ry + 180))
            ry = self._text(draw, (60, ry + 20), t("ranking.title", lang), size=30)
            if c.ranking.rank is not None:
                ry = self._text(draw, (60, ry), t("ranking.rank", lang, rank=c.ranking.rank), size=24, color=_MUTED)
            if c.ranking.top_percent is not None:
                ry = self._text(draw, (60, ry),
                                t("ranking.top_percent", lang, percent=f"{c.ranking.top_percent:.1f}"),
                                size=24, color=_MUTED)

        return self._to_png(img)

    def render_abyss_card(self, ctx: AbyssCardContext) -> bytes:
        img, draw = self._canvas(ctx)
        lang = ctx.language
        title = t("abyss.pre_title" if (ctx.abyss and ctx.abyss.is_previous) else "abyss.title", lang)
        y = self._text(draw, (40, 40), _strip_tags(title), size=40)
        if not ctx.abyss or not ctx.abyss.available:
            self._text(draw, (40, y), t("abyss.unavailable", lang), size=28, color=_MUTED)
            return self._to_png(img)
        a = ctx.abyss
        self._panel(draw, (40, y, 860, y + 220))
        yy = y + 20
        if a.max_floor:
            yy = self._text(draw, (60, yy), t("abyss.max_floor", lang, floor=a.max_floor), size=28)
        if a.total_stars is not None:
            yy = self._text(draw, (60, yy), t("abyss.stars", lang, stars=a.total_stars), size=28)
        return self._to_png(img)

    def render_theater_card(self, ctx: TheaterCardContext) -> bytes:
        img, draw = self._canvas(ctx)
        lang = ctx.language
        y = self._text(draw, (40, 40), _strip_tags(t("theater.title", lang)), size=40)
        if not ctx.theater or not ctx.theater.available:
            self._text(draw, (40, y), t("theater.unavailable", lang), size=28, color=_MUTED)
            return self._to_png(img)
        th = ctx.theater
        self._panel(draw, (40, y, 860, y + 220))
        yy = y + 20
        if th.difficulty:
            yy = self._text(draw, (60, yy), th.difficulty, size=28)
        if th.stars is not None:
            yy = self._text(draw, (60, yy), t("abyss.stars", lang, stars=th.stars), size=28)
        return self._to_png(img)


def _strip_tags(text: str) -> str:
    """Remove simple HTML tags so titles render cleanly on an image."""
    import re

    return re.sub(r"<[^>]+>", "", text)
