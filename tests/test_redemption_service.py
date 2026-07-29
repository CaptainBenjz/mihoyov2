"""Tests for the redemption service, code validation, and the /redeem response layouts."""

from __future__ import annotations

import pytest

from bot.commands.redeem import _render
from bot.services.redemption_service import (
    LinkRedeemer,
    RedeemResult,
    RedeemStatus,
    RedemptionService,
    gift_url,
    normalize_code,
)

# --- code normalization ------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("genshingift", "GENSHINGIFT"),   # upper-cased
        ("  GA6PH4NPZ8V9  ", "GA6PH4NPZ8V9"),  # trimmed
        ("AB12", "AB12"),                 # min length
    ],
)
def test_normalize_code_accepts_valid(raw, expected):
    assert normalize_code(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "ab", "has space", "sym!bol", "way-too-long-code-xxxxx"])
def test_normalize_code_rejects_invalid(raw):
    assert normalize_code(raw) is None


def test_gift_url_contains_code():
    assert gift_url("GENSHINGIFT") == "https://genshin.hoyoverse.com/en/gift?code=GENSHINGIFT"


# --- service behaviour -------------------------------------------------------


async def test_redeem_invalid_code_returns_invalid_status():
    result = await RedemptionService().redeem("618285856", "!!bad!!")
    assert result.status is RedeemStatus.INVALID


async def test_redeem_valid_code_default_backend_returns_link_with_region():
    # 6-prefixed UID -> America.
    result = await RedemptionService().redeem("618285856", "genshingift")
    assert result.status is RedeemStatus.LINK
    assert result.code == "GENSHINGIFT"
    assert result.region == "America"
    assert result.redeem_url == "https://genshin.hoyoverse.com/en/gift?code=GENSHINGIFT"


async def test_service_never_raises_on_backend_failure():
    class _BoomRedeemer:
        async def redeem(self, uid, code, region):
            raise RuntimeError("upstream down")

    result = await RedemptionService(_BoomRedeemer()).redeem("700000001", "GENSHINGIFT")
    assert result.status is RedeemStatus.SERVER_ERROR
    assert result.code == "GENSHINGIFT"
    assert result.region == "Europe"


async def test_custom_backend_success_passes_through():
    class _WinRedeemer:
        async def redeem(self, uid, code, region):
            return RedeemResult(
                status=RedeemStatus.SUCCESS, code=code, uid=uid, region=region,
                rewards=["Primogem ×60", "Mora ×10,000"],
            )

    result = await RedemptionService(_WinRedeemer()).redeem("800000005", "abc123")
    assert result.status is RedeemStatus.SUCCESS
    assert result.rewards == ["Primogem ×60", "Mora ×10,000"]


async def test_link_redeemer_directly():
    result = await LinkRedeemer().redeem("900000001", "GENSHINGIFT", "TW/HK/MO")
    assert result.status is RedeemStatus.LINK
    assert result.redeem_url.endswith("code=GENSHINGIFT")


# --- rendering ---------------------------------------------------------------


def test_render_link_card_has_fields_and_button():
    result = RedeemResult(
        status=RedeemStatus.LINK, code="GENSHINGIFT", uid="618285856",
        region="America", nickname="Traveler", redeem_url=gift_url("GENSHINGIFT"),
    )
    text, markup = _render(result, "en")
    assert "GENSHINGIFT" in text
    assert "618285856" in text
    assert "America" in text
    assert "Traveler" in text
    # A one-tap redemption button points at the official page.
    assert markup is not None
    button = markup.inline_keyboard[0][0]
    assert button.url == "https://genshin.hoyoverse.com/en/gift?code=GENSHINGIFT"


def test_render_success_card_lists_rewards():
    result = RedeemResult(
        status=RedeemStatus.SUCCESS, code="GENSHINGIFT", uid="618285856",
        region="America", rewards=["Primogem ×60"],
    )
    text, markup = _render(result, "en")
    assert "Primogem" in text
    assert markup is None  # nothing to open; already redeemed


def test_render_invalid_escapes_offending_code():
    result = RedeemResult(status=RedeemStatus.INVALID, code="<script>")
    text, markup = _render(result, "en")
    assert "&lt;script&gt;" in text  # HTML-escaped, not injected
    assert "<script>" not in text
    assert markup is None


@pytest.mark.parametrize(
    "status", [RedeemStatus.EXPIRED, RedeemStatus.ALREADY_REDEEMED,
               RedeemStatus.WRONG_REGION, RedeemStatus.SERVER_ERROR],
)
def test_render_error_layouts_are_nonempty_oneliners(status):
    text, markup = _render(RedeemResult(status=status, code="GENSHINGIFT"), "en")
    assert text and "GENSHINGIFT" in text
    assert markup is None
