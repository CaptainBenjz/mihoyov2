"""The SVG layout is the machine-readable source of truth for card geometry.

These tests pin the contract the renderer depends on: the canvas resolves to the required
1536x864, every slot the card needs exists, and no dynamic slot silently loses its geometry.
"""

from __future__ import annotations

import pytest

from bot.renderer.slot_manager import ImageSlot, TextSlot, get_layout, load_layout


@pytest.fixture(scope="module")
def layout():
    return get_layout()


def test_canvas_is_1536x864_from_a_native_1280x720_viewbox(layout):
    """Coordinates stay in the template's measured pixel space; output is scaled 1.2x."""
    assert (layout.view_width, layout.view_height) == (1280, 720)
    assert (layout.out_width, layout.out_height) == (1536, 864)
    assert layout.scale == pytest.approx(1.2)


def test_every_required_slot_group_is_present(layout):
    required_images = {
        "character-image", "weapon-image", "artifact-set-image",
        "talent-normal-image", "talent-skill-image", "talent-burst-image",
        *(f"artifact-{s}-image" for s in ("flower", "plume", "sands", "goblet", "circlet")),
    }
    assert required_images <= set(layout.images)

    required_text = {
        "character-name", "character-level", "character-constellation",
        "weapon-name", "weapon-base-attack", "weapon-secondary-stat",
        "weapon-level", "weapon-refinement",
        "stat-hp", "stat-atk", "stat-def", "stat-em",
        "stat-crit-rate", "stat-crit-dmg", "stat-energy-recharge", "stat-elemental-bonus",
        "artifact-set-name", "artifact-set-2pc", "artifact-set-4pc",
        "summary-crit-rate", "summary-atk", "summary-elemental-bonus",
    }
    assert required_text <= set(layout.text)


def test_each_artifact_exposes_the_same_component_structure(layout):
    """All five positions are identical components differing only in position."""
    shapes = {}
    for slot in ("flower", "plume", "sands", "goblet", "circlet"):
        roles = layout.artifact_slots(slot)
        shapes[slot] = set(roles)
        assert "image" in roles and "main-stat" in roles and "main-value" in roles
        for i in range(1, 5):
            assert f"substat-{i}-name" in roles
            assert f"substat-{i}-value" in roles
    assert len(set(map(frozenset, shapes.values()))) == 1, "components must be uniform"


def test_artifact_positions_differ_while_structure_matches(layout):
    ys = [layout.image_slot(f"artifact-{s}-image").y
          for s in ("flower", "plume", "sands", "goblet", "circlet")]
    assert ys == sorted(ys)
    gaps = [ys[i + 1] - ys[i] for i in range(4)]
    assert all(g == 115 for g in gaps), gaps


def test_numeric_stat_values_are_end_anchored(layout):
    """A longer number must not shift its row, so stat values right-align."""
    for key in ("hp", "atk", "def", "em", "crit-rate", "crit-dmg",
                "energy-recharge", "elemental-bonus"):
        slot = layout.text_slot(f"stat-{key}")
        assert slot.anchor == "end", key
        assert slot.pil_anchor == "rm"


def test_every_text_slot_can_shrink_to_fit(layout):
    """Text auto-fit needs a real max width and a floor below the nominal size."""
    for slot in layout.text.values():
        assert slot.max_width > 0, slot.id
        assert 0 < slot.min_size <= slot.size, slot.id


def test_every_image_slot_has_a_real_box_and_fit_rule(layout):
    for slot in layout.images.values():
        assert slot.width > 0 and slot.height > 0, slot.id
        assert slot.fit in ("contain", "cover"), slot.id
        assert slot.clip in ("rect", "circle", "stadium"), slot.id


def test_character_image_is_contained_not_stretched(layout):
    slot = layout.image_slot("character-image")
    assert slot.fit == "contain", "the portrait must never be distorted"
    assert slot.clip == "stadium", "clipped to the frame's pill window"


def test_unknown_slots_return_none_rather_than_raising(layout):
    assert layout.text_slot("does-not-exist") is None
    assert layout.image_slot("does-not-exist") is None


def test_layout_reloads_from_disk(tmp_path):
    """load_layout parses a file directly; get_layout is the cached process-wide view."""
    fresh = load_layout()
    assert isinstance(fresh.text["character-name"], TextSlot)
    assert isinstance(fresh.images["character-image"], ImageSlot)
