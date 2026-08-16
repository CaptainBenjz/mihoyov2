"""Slot-driven character card renderer.

The card is treated as a fixed UI, not as a picture to draw over:

    static template  +  named slots (SVG)  +  normalized data  +  assets  ->  1536x864 PNG

Responsibilities are deliberately split. :mod:`slot_manager` owns *where* (parsed from
``templates/character_card.svg`` — the single source of truth for geometry); this module owns
*how* it is composited. It performs no I/O and no API calls: it receives already-normalized
data and already-fetched images, so the same card renders identically for the same input.

Because every position comes from the slot map, a character released tomorrow needs no
change here — only data and assets differ.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from bot.renderer import image_fitter
from bot.renderer.card_data import CardData
from bot.renderer.image_fitter import Adjustment
from bot.renderer.slot_manager import Layout, get_layout
from bot.renderer.text_fitter import draw_text
from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Ink colours sampled from the approved reference card.
INK_DARK = (52, 44, 34)
INK_BODY = (90, 78, 62)
INK_LIGHT = (240, 232, 214)
GOLD = (214, 168, 74)

# Panel background colours used to erase the template's baked placeholder glyphs before
# live values are drawn. Sampled from the template itself at render time.
def _sample(img, x: int, y: int) -> tuple[int, int, int]:
    """Colour of one template pixel, in output coordinates."""
    return img.getpixel((x, y))[:3]


_SAMPLE_POINTS = {
    "cream": (1000, 92),
    "weapon_top": (690, 150),
    "weapon_bottom": (470, 245),
    "header": (330, 20),
    "topbar": (500, 60),
    "set": (760, 522),
    "level_box": (650, 213),
    "talent": (405, 548),
}


class CharacterCardRenderer:
    """Composites a :class:`CardData` onto the fixed template using the slot map."""

    def __init__(self, layout: Layout | None = None, font_provider=None) -> None:
        self._layout = layout or get_layout()
        self._font_for = font_provider or _default_font_provider()

    # -- public API --------------------------------------------------------
    def render(self, data: CardData, *, debug: bool = False) -> bytes:
        """Render ``data`` to PNG bytes at the layout's output resolution."""
        layout = self._layout
        scale = layout.scale
        base = self._base_canvas()

        draw = ImageDraw.Draw(base)
        colors = {name: base.getpixel((int(x * scale), int(y * scale)))[:3]
                  for name, (x, y) in _SAMPLE_POINTS.items()}
        self._erase_placeholders(draw, colors, scale)

        self._draw_character(base, draw, data, scale, colors)
        self._draw_weapon(base, draw, data, scale)
        self._draw_stats(draw, data, scale)
        self._draw_talents(base, draw, data, scale)
        self._draw_artifacts(base, draw, data, scale, colors["cream"])
        self._draw_set_bonus(base, draw, data, scale)
        self._draw_summary(draw, data, scale)

        if debug:
            self._draw_debug_overlay(draw, scale)

        buf = io.BytesIO()
        base.convert("RGB").save(buf, format="PNG")
        return buf.getvalue()

    # -- canvas ------------------------------------------------------------
    def _base_canvas(self) -> Image.Image:
        """The static layer, scaled once to the output resolution."""
        from bot.renderer.template_source import load_base_template

        layout = self._layout
        base = load_base_template()
        if base.size != (layout.out_width, layout.out_height):
            base = base.resize((layout.out_width, layout.out_height), Image.LANCZOS)
        return base.convert("RGBA")

    def _erase_placeholders(self, draw, colors, scale) -> None:
        """Clear the template's baked placeholder glyphs ("/", "Main Stat", star rows).

        The template ships with sample text in every slot. Live values are drawn on top, so
        each region is first filled with its own panel colour, sampled next to it.
        """
        def box(x0, y0, x1, y1, color):
            draw.rectangle(
                (x0 * scale, y0 * scale, x1 * scale, y1 * scale), fill=color
            )

        c = colors
        box(110, 24, 362, 70, c["header"])       # character name
        box(116, 70, 250, 92, c["header"])       # header rarity stars
        box(116, 88, 322, 110, c["header"])      # title line (left blank by design)
        box(428, 50, 476, 80, c["topbar"])       # level "/"
        box(724, 52, 826, 80, c["topbar"])       # baked rarity stars
        box(512, 128, 704, 160, c["weapon_top"])   # weapon name
        box(398, 215, 494, 239, c["weapon_bottom"])  # weapon rarity stars
        box(668, 164, 758, 189, c["weapon_top"])   # weapon 2nd stat box
        box(806, 166, 832, 189, c["weapon_top"])   # refinement box
        box(508, 201, 700, 226, c["level_box"])    # "Lv. /"
        box(608, 510, 762, 542, c["set"])          # set name
        # The constellation cell bakes an empty circle placeholder; without clearing it the
        # dynamic "C1" is drawn straight through the ring.
        box(586, 50, 620, 84, _sample(draw._image, int(566 * scale), int(66 * scale)))
        # Enka exposes no set-bonus descriptions, so the template's sample copy would stay
        # visible under empty slots. Clear both description blocks (the "2-/4-Piece Bonus"
        # headings themselves are real template furniture and are kept).
        box(636, 553, 800, 581, c["set"])
        box(636, 599, 800, 622, c["set"])
        # Friendship value area next to the baked heart pill.
        box(124, 552, 168, 570, _sample(draw._image, int(100 * scale), int(561 * scale)))
        box(428, 439, 560, 459, c["cream"])        # baked "Pyro DMG Bonus" (stats row)

        # Bottom summary bar: clear each baked "/" placeholder and the element label, using
        # the bar's own interior colour sampled next to them.
        bar = _sample(draw._image, int(300 * scale), int(664 * scale))
        box(774, 650, 870, 670, bar)               # baked "PYRO DMG BONUS"
        for key in ("crit-rate", "crit-dmg", "er", "atk", "def", "em", "elemental-bonus"):
            slot = self._layout.text_slot(f"summary-{key}")
            if slot is not None:
                box(slot.x - 26, slot.y - 11, slot.x + 74, slot.y + 11, bar)

        for slot_name in ("flower", "plume", "sands", "goblet", "circlet"):
            main = self._layout.text_slot(f"artifact-{slot_name}-main-stat")
            if main is None:
                continue
            dy = main.y - 104
            box(968, 94 + dy, 1086, 136 + dy, c["cream"])   # main stat lines
            box(896, 140 + dy, 968, 162 + dy, c["cream"])   # baked stars
            for i in range(4):
                sub = self._layout.text_slot(f"artifact-{slot_name}-substat-{i + 1}-name")
                if sub is not None:
                    box(1096, sub.y - 11, 1262, sub.y + 11, c["cream"])

        for name in ("normal", "skill", "burst"):
            slot = self._layout.text_slot(f"talent-{name}-level")
            if slot is not None:
                box(slot.x - 18, slot.y - 13, slot.x + 18, slot.y + 11, c["talent"])

    # -- sections ----------------------------------------------------------
    def _text(self, draw, slot_id, value, color, scale) -> None:
        slot = self._layout.text_slot(slot_id)
        if slot is not None:
            draw_text(draw, value, slot, self._font_for, color, scale=scale)

    def _image(self, base, slot_id, img, scale, *, align="center",
               adjustment: Adjustment = image_fitter.DEFAULT_ADJUSTMENT) -> None:
        slot = self._layout.image_slot(slot_id)
        if slot is None:
            return
        x0, y0, x1, y1 = slot.box
        box = (round(x0 * scale), round(y0 * scale), round(x1 * scale), round(y1 * scale))
        image_fitter.paste_into(
            base, img, box, mode=slot.fit, clip=slot.clip, align=align, adjustment=adjustment
        )

    def _draw_character(self, base, draw, data, scale, colors) -> None:
        ch = data.character
        # Erase the template's "CHARACTER IMAGE PLACEHOLDER" behind the portrait first.
        slot = self._layout.image_slot("character-image")
        if slot is not None:
            x0, y0, x1, y1 = (round(v * scale) for v in slot.box)
            # Dark element-tinted panel: opaque so it erases the template's baked
            # "CHARACTER IMAGE PLACEHOLDER", but dim enough that the artwork reads
            # against it the way it does in the reference.
            tint = tuple(int(c * 0.22) for c in data.glow)
            backdrop = Image.new("RGBA", (x1 - x0, y1 - y0), (*tint, 255))
            mask = image_fitter._clip_mask((x1 - x0, y1 - y0), slot.clip)
            if mask is not None:
                backdrop.putalpha(mask)
            base.alpha_composite(backdrop, (x0, y0))
        self._image(base, "character-image", data.portrait, scale,
                    align="bottom", adjustment=data.character_adjustment)

        self._text(draw, "character-name", (ch.name or "").upper(), INK_DARK, scale)
        self._text(draw, "character-rarity", "★" * (ch.rarity or 0), GOLD, scale)
        self._text(draw, "character-rarity-bar", "★" * (ch.rarity or 0), GOLD, scale)
        self._text(draw, "character-level", str(ch.level), INK_LIGHT, scale)
        self._text(draw, "character-constellation", f"C{ch.constellation}", INK_LIGHT, scale)
        if ch.friendship is not None:
            self._text(draw, "character-friendship", str(ch.friendship), INK_DARK, scale)

    def _draw_weapon(self, base, draw, data, scale) -> None:
        w = data.weapon
        if w is None:
            return
        # The reference seats the weapon on a dark disc; the bare template circle is cream,
        # which leaves light weapon art almost invisible.
        slot = self._layout.image_slot("weapon-image")
        if slot is not None:
            x0, y0, x1, y1 = (round(v * scale) for v in slot.box)
            disc = Image.new("RGBA", (x1 - x0, y1 - y0), (46, 38, 30, 255))
            mask = image_fitter._clip_mask((x1 - x0, y1 - y0), "circle")
            if mask is not None:
                disc.putalpha(mask)
            base.alpha_composite(disc, (x0, y0))
        self._image(base, "weapon-image", data.weapon_image, scale)
        self._text(draw, "weapon-name", w.name, INK_DARK, scale)
        self._text(draw, "weapon-rarity", "★" * (w.rarity or 0), GOLD, scale)
        self._text(draw, "weapon-base-attack", w.base_attack, INK_DARK, scale)
        self._text(draw, "weapon-secondary-stat", w.secondary_stat, INK_DARK, scale)
        self._text(draw, "weapon-level", w.level_text, INK_DARK, scale)
        self._text(draw, "weapon-refinement", w.refinement_text, INK_DARK, scale)

    def _draw_stats(self, draw, data, scale) -> None:
        for key, value in data.stats.rows():
            self._text(draw, f"stat-{key}", value, INK_DARK, scale)
        # The element row's label follows the character, not the template.
        self._text(draw, "stat-elemental-bonus-label",
                   data.stats.elemental_bonus_name, INK_BODY, scale)

    def _draw_talents(self, base, draw, data, scale) -> None:
        for name, talent in data.talents.items():
            self._image(base, f"talent-{name}-image", talent.image, scale)
            self._text(draw, f"talent-{name}-level", talent.level_text, INK_DARK, scale)

    def _draw_artifacts(self, base, draw, data, scale, cream) -> None:
        for slot_name, art in data.artifacts.items():
            if art is None:
                continue
            self._image(base, f"artifact-{slot_name}-image", art.image, scale)
            self._text(draw, f"artifact-{slot_name}-rarity", "★" * (art.rarity or 0), GOLD, scale)
            self._text(draw, f"artifact-{slot_name}-main-stat", art.main_stat, INK_BODY, scale)
            self._text(draw, f"artifact-{slot_name}-main-value", art.main_value, INK_DARK, scale)
            for i, (name, value) in enumerate(art.substats[:4], start=1):
                self._text(draw, f"artifact-{slot_name}-substat-{i}-name", name, INK_BODY, scale)
                self._text(draw, f"artifact-{slot_name}-substat-{i}-value", value, INK_DARK, scale)

    def _draw_set_bonus(self, base, draw, data, scale) -> None:
        s = data.artifact_set
        if s is None:
            return
        self._image(base, "artifact-set-image", s.image, scale)
        self._text(draw, "artifact-set-name", s.name, INK_DARK, scale)
        self._text(draw, "artifact-set-2pc", s.two_piece, INK_BODY, scale)
        self._text(draw, "artifact-set-4pc", s.four_piece, INK_BODY, scale)

    def _draw_summary(self, draw, data, scale) -> None:
        for key, value in data.stats.summary_rows():
            self._text(draw, f"summary-{key}", value, INK_LIGHT, scale)
        self._text(draw, "summary-elemental-bonus-label",
                   data.stats.elemental_bonus_name.upper(), (206, 186, 148), scale)

    # -- debug -------------------------------------------------------------
    def _draw_debug_overlay(self, draw, scale) -> None:
        """Outline every slot and label it. Development only — never in production output."""
        font = self._font_for(9, 400)
        for slot in self._layout.images.values():
            x0, y0, x1, y1 = (v * scale for v in slot.box)
            draw.rectangle((x0, y0, x1, y1), outline=(0, 200, 255), width=1)
            draw.text((x0 + 2, y0 + 2), slot.id, font=font, fill=(0, 200, 255))
        for slot in self._layout.text.values():
            x, y = slot.x * scale, slot.y * scale
            w = slot.max_width * scale
            left = {"start": x, "middle": x - w / 2, "end": x - w}[slot.anchor]
            draw.rectangle((left, y - 7 * scale, left + w, y + 7 * scale),
                           outline=(255, 0, 128), width=1)
            draw.text((left + 1, y - 7 * scale - 8), slot.id, font=font, fill=(255, 0, 128))


def _default_font_provider():
    """Font lookup backed by the bundled variable font, cached per (size, weight)."""
    from PIL import ImageFont

    from bot.assets import bootstrap

    cache: dict[tuple[int, int], ImageFont.FreeTypeFont] = {}

    def font_for(size: int, weight: int = 400):
        key = (size, weight)
        if key not in cache:
            try:
                font = ImageFont.truetype(str(bootstrap.font_path()), size)
                try:
                    font.set_variation_by_axes([weight])
                except Exception:  # noqa: BLE001 - non-variable build
                    pass
                cache[key] = font
            except (OSError, ValueError):
                cache[key] = ImageFont.load_default()
        return cache[key]

    return font_for


_RENDERER: CharacterCardRenderer | None = None


def get_card_renderer() -> CharacterCardRenderer:
    """Shared renderer — the layout and fonts are static, so one instance is reused."""
    global _RENDERER
    if _RENDERER is None:
        _RENDERER = CharacterCardRenderer()
    return _RENDERER
