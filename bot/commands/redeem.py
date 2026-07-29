"""Redemption command: ``/redeem <code>``.

Claims an official HoYoverse gift code automatically on the bot's configured HoYoLAB
account and returns the final result inside Telegram — no buttons, no links, no website
redirect, no UID/login prompt. The handler validates + waits for the redemption to complete,
then renders a premium, Genshin-themed layout for the outcome.
"""

from __future__ import annotations

import html

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, reply, resolve_language, with_action
from bot.services.redemption_service import RedeemResult, RedeemStatus
from bot.translations.i18n import t

# Decorative divider used across every redemption layout.
HR = "━━━━━━━━━━━━━━━━━━"


def _esc(value: str) -> str:
    """Escape HTML-significant chars in body text. quote=False keeps apostrophes/quotes
    readable (e.g. "Hero's Wit"); these values are never placed in HTML attributes."""
    return html.escape(value, quote=False)


@guard
@with_action(ChatAction.TYPING)
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)

    if not context.args:
        await reply(update, t("redeem.usage", lang))
        return

    # Redeem on the configured account and wait for the result before replying.
    result = await app.redemption_service.redeem(context.args[0])
    await reply(update, _render(result, lang))


# --------------------------------------------------------------------------- rendering
def _render(result: RedeemResult, lang: str) -> str:
    """Map a :class:`RedeemResult` to a finished, premium HTML message (never a link/button)."""
    status = result.status
    if status is RedeemStatus.SUCCESS:
        return _success(result, lang)
    if status is RedeemStatus.INVALID:
        return _panel(lang, "redeem.h_invalid", "redeem.invalid_body")
    if status is RedeemStatus.ALREADY_REDEEMED:
        return _panel(lang, "redeem.h_already", "redeem.already_body")
    if status is RedeemStatus.AUTH_FAILED:
        return _panel(lang, "redeem.h_auth", "redeem.auth_body")
    if status in (RedeemStatus.COOLDOWN, RedeemStatus.SERVER_ERROR):
        return _panel(lang, "redeem.h_busy", "redeem.busy_body")

    # EXPIRED / WRONG_REGION / LEVEL_TOO_LOW share the "Redemption Failed" card + a reason.
    reason_key = {
        RedeemStatus.EXPIRED: "redeem.reason_expired",
        RedeemStatus.WRONG_REGION: "redeem.reason_region",
        RedeemStatus.LEVEL_TOO_LOW: "redeem.reason_level",
    }.get(status, "redeem.reason_generic")
    return _failed(result, lang, reason_key)


def _field(label_key: str, value: str, lang: str, *, mono: bool = False) -> list[str]:
    val = f"<code>{value}</code>" if mono else value
    return [f"<b>{t(label_key, lang)}</b>", val, ""]


def _success(result: RedeemResult, lang: str) -> str:
    lines = [HR, f"<b>{t('redeem.h_success', lang)}</b>", HR, ""]
    lines += _field("redeem.l_code", _esc(result.code), lang, mono=True)
    if result.uid:
        lines += _field("redeem.l_uid", _esc(result.uid), lang, mono=True)
    if result.nickname:
        lines += _field("redeem.l_traveler", _esc(result.nickname), lang)
    if result.region:
        lines += _field("redeem.l_region", _esc(result.region), lang)
    if result.rewards:
        lines.append(f"<b>{t('redeem.l_rewards', lang)}</b>")
        lines += [f"• {_esc(r)}" for r in result.rewards]
        lines.append("")
    lines += [
        t("redeem.success_confirm", lang), "",
        t("redeem.success_mail", lang), "",
        t("redeem.success_enjoy", lang), "",
        HR,
    ]
    return "\n".join(lines)


def _failed(result: RedeemResult, lang: str, reason_key: str) -> str:
    lines = [HR, f"<b>{t('redeem.h_failed', lang)}</b>", HR, ""]
    lines += _field("redeem.l_code", _esc(result.code), lang, mono=True)
    lines += _field("redeem.l_reason", t(reason_key, lang), lang)
    lines += [t("redeem.failed_norewards", lang), "", HR]
    return "\n".join(lines)


def _panel(lang: str, header_key: str, body_key: str) -> str:
    return "\n".join([HR, f"<b>{t(header_key, lang)}</b>", HR, "", t(body_key, lang), "", HR])
