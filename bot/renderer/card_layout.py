"""Pixel coordinate map + element themes for the character profile card.

All coordinates target the fixed 1280x720 template. They are intentionally kept as data so
the renderer never computes layout — it only draws live values at these positions. Tune the
numbers here to align with the template; the renderer reads them verbatim.
"""

from __future__ import annotations

CARD_SIZE = (1280, 720)

# --- Element themes -------------------------------------------------------------------
# `bg`: background tint applied behind the character / across the card so the whole card
#       takes on the element's colour ("green character -> green background").
# `accent`: borders / accent lines / labels. `glow`: portrait backdrop glow.
ELEMENT_THEMES: dict[str, dict[str, tuple[int, int, int]]] = {
    "PYRO": {"bg": (168, 54, 40), "accent": (255, 120, 70), "glow": (255, 90, 50)},
    "HYDRO": {"bg": (30, 92, 168), "accent": (80, 180, 255), "glow": (60, 150, 255)},
    "ELECTRO": {"bg": (108, 60, 168), "accent": (190, 120, 255), "glow": (170, 90, 255)},
    "CRYO": {"bg": (96, 150, 180), "accent": (170, 230, 255), "glow": (150, 220, 255)},
    "ANEMO": {"bg": (30, 140, 118), "accent": (90, 220, 180), "glow": (70, 210, 165)},
    "GEO": {"bg": (170, 120, 30), "accent": (240, 190, 70), "glow": (235, 175, 55)},
    "DENDRO": {"bg": (70, 140, 30), "accent": (150, 220, 80), "glow": (130, 210, 60)},
}
DEFAULT_THEME = {"bg": (60, 62, 82), "accent": (200, 180, 120), "glow": (150, 150, 170)}

# Enka reports elements by their in-data names (Fire/Water/…); map to canonical elements.
_ELEMENT_ALIASES = {
    "FIRE": "PYRO", "PYRO": "PYRO",
    "WATER": "HYDRO", "HYDRO": "HYDRO",
    "ELECTRIC": "ELECTRO", "ELECTRO": "ELECTRO",
    "ICE": "CRYO", "CRYO": "CRYO",
    "WIND": "ANEMO", "ANEMO": "ANEMO",
    "ROCK": "GEO", "GEO": "GEO",
    "GRASS": "DENDRO", "DENDRO": "DENDRO",
}


def canonical_element(element: str | None) -> str | None:
    """Normalize any element spelling (e.g. 'Fire') to a canonical key (e.g. 'PYRO')."""
    if not element:
        return None
    key = element.strip().upper()
    if key in _ELEMENT_ALIASES:
        return _ELEMENT_ALIASES[key]
    for canon in ELEMENT_THEMES:
        if canon in key:
            return canon
    return None


def theme_for(element: str | None) -> dict[str, tuple[int, int, int]]:
    canon = canonical_element(element)
    return ELEMENT_THEMES.get(canon, DEFAULT_THEME) if canon else DEFAULT_THEME


# --- Portrait -------------------------------------------------------------------------
# Bounding box of the oval character frame (left, top, right, bottom).
PORTRAIT_BOX = (150, 105, 352, 600)

# --- Header ---------------------------------------------------------------------------
NAME_POS = (118, 34)             # top-left anchor, big
NAME_MAX_WIDTH = 250
RARITY_STARS_POS = (120, 74)     # header rarity stars (top-left)
TITLE_POS = (120, 96)

# --- Left rail ------------------------------------------------------------------------
FRIENDSHIP_POS = (120, 560)      # value drawn after the "Friendship" pill label

# --- Top level/constellation/rarity bar ----------------------------------------------
LEVEL_VALUE_POS = (450, 62)      # centered under LEVEL
CONSTELLATION_VALUE_POS = (603, 66)  # centered in the circle (e.g. "6")
RARITY_BAR_STARS_POS = (770, 66)     # centered under RARITY

# --- Weapon panel ---------------------------------------------------------------------
WEAPON_ICON_CENTER = (445, 168)
WEAPON_ICON_RADIUS = 42
WEAPON_NAME_POS = (525, 138)
WEAPON_NAME_MAX_WIDTH = 300
WEAPON_TYPE_POS = (560, 176)     # after the type icon box
WEAPON_LEVEL_POS = (560, 212)    # "Lv. 90"
WEAPON_REFINE_POS = (817, 176)   # centered in the "R" box (e.g. "R5")

# --- Base stats (right-aligned values per row) ----------------------------------------
BASE_STAT_VALUE_X = 825          # right edge for values
BASE_STAT_ROWS_Y = {            # y baseline per labelled row (order matches template)
    "hp": 283,
    "atk": 307,
    "defense": 331,
    "elemental_mastery": 355,
    "crit_rate": 379,
    "crit_dmg": 402,
    "energy_recharge": 425,
    "elemental_bonus": 448,
}

# --- Talents (levels under each of the 3 icons) ---------------------------------------
TALENT_LEVEL_POS = [(428, 600), (492, 600), (557, 600)]  # NA, Skill, Burst

# --- Set bonus ------------------------------------------------------------------------
SET_NAME_POS = (700, 522)
SET_2PC_POS = (662, 552)
SET_4PC_POS = (662, 598)

# --- Artifacts (5 cards) --------------------------------------------------------------
# Per card: main-stat text position, rarity-stars position, and 4 substat text positions.
ARTIFACT_CARD_TOP = [68, 181, 294, 407, 520]
ARTIFACT_MAIN_STAT_POS = (985, 118)     # relative-to-card handled by adding card top offset
ARTIFACT_STARS_POS = (900, 150)
ARTIFACT_SUBSTAT_X = 1105
ARTIFACT_SUBSTAT_YS = [78, 100, 122, 144]
ARTIFACT_CARD_REF_TOP = 68              # the y the offsets above were measured against

# --- Bottom summary bar (7 values under labels) ---------------------------------------
BOTTOM_BAR_Y = 678
BOTTOM_BAR_VALUE_X = [78, 190, 320, 440, 535, 665, 808]
# order: CRIT Rate, CRIT DMG, Energy Recharge, ATK, DEF, Elemental Mastery, Elemental Bonus

# --- Akasha ranking badge (drawn only when ranking data exists) -----------------------
RANKING_BADGE_BOX = (378, 640, 838, 712)   # a premium badge strip along the bottom-center
