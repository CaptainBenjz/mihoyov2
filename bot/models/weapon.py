"""Weapon domain model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Weapon:
    """A character's equipped weapon."""

    name: str
    level: int = 1
    refinement: int = 1          # 1..5
    ascension: int = 0
    rarity: int | None = None    # star rating, if known
    icon: str | None = None      # icon key/name for asset lookup
    main_stat_name: str | None = None
    main_stat_value: float | None = None
    sub_stat_name: str | None = None
    sub_stat_value: float | None = None
