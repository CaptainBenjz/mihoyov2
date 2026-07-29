"""Redemption command: ``/redeem <code>``.

Redeems (or hands off redemption of) an official HoYoverse gift code for the user's linked
Genshin account. Thin handler: it checks the account link, delegates validation + redemption
to :class:`~bot.services.redemption_service.RedemptionService`, and renders a premium,
localized response for each possible outcome.
"""

from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from bot.app_context import AppContext
from bot.commands.common import get_app, guard, reply, resolve_language, user_id_of, with_action
from bot.services.redemption_service import RedeemResult, RedeemStatus
from bot.translations.i18n import t
from bot.utils.logging import get_logger

logger = get_logger(__name__)

# Outcomes rendered as a full "card" (title + fields + closing note), vs. a short one-liner.
_CARD_STATUSES = {RedeemStatus.LINK, RedeemStatus.SUCCESS}


@guard
@with_action(ChatAction.TYPING)
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)
    if tg_id is None:
        return

    # 🔒 Account not linked — a dedicated, friendly redeem-flavoured prompt.
    linked_uid = await app.account_service.get_uid(tg_id)
    if not linked_uid:
        await reply(update, t("redeem.not_linked", lang))
        return

    # No code supplied — show usage.
    if not context.args:
        await reply(update, t("redeem.usage", lang))
        return

    result = await app.redemption_service.redeem(linked_uid, context.args[0])

    # Best-effort profile enrichment for the success/link card (nickname). Never blocks or
    # breaks the flow if the showcase is private/empty/unreachable.
    if result.status in _CARD_STATUSES:
        result.nickname = await _best_effort_nickname(app, linked_uid, lang)

    text, markup = _render(result, lang)
    await reply(update, text, reply_markup=markup)


async def _best_effort_nickname(app: AppContext, uid: str, lang: str) -> str | None:
    """Fetch the account nickname if we can. Any failure yields ``None`` (never raises)."""
    try:
        showcase = await app.character_service.get_showcase(uid, lang)
        return showcase.player.nickname or None
    except Exception as exc:  # noqa: BLE001 - enrichment is optional
        logger.debug("Nickname enrichment skipped for %s: %s", uid, exc)
        return None


# --------------------------------------------------------------------------- rendering
def _render(result: RedeemResult, lang: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Map a :class:`RedeemResult` to (message_html, optional_inline_keyboard)."""
    status = result.status

    if status in _CARD_STATUSES:
        title_key, note_key = (
            ("redeem.link_title", "redeem.link_note")
            if status is RedeemStatus.LINK
            else ("redeem.success_title", "redeem.success_note")
        )
        text = _card(result, lang, title_key=title_key, note_key=note_key)
        markup = _redeem_button(result, lang)
        return text, markup

    # One-line error layouts. INVALID echoes the (escaped) offending code for clarity.
    if status is RedeemStatus.INVALID:
        return t("redeem.invalid", lang, code=html.escape(result.code or "—")), None

    key = {
        RedeemStatus.EXPIRED: "redeem.expired",
        RedeemStatus.ALREADY_REDEEMED: "redeem.already",
        RedeemStatus.WRONG_REGION: "redeem.wrong_region",
        RedeemStatus.SERVER_ERROR: "redeem.server_error",
    }.get(status, "error.generic")
    return t(key, lang, code=html.escape(result.code or "—")), None


def _card(result: RedeemResult, lang: str, *, title_key: str, note_key: str) -> str:
    """Build the multi-line premium card shared by the success and link layouts."""
    lines = [t(title_key, lang), ""]
    lines.append(t("redeem.field_code", lang, code=html.escape(result.code)))
    if result.uid:
        lines.append(t("redeem.field_uid", lang, uid=html.escape(result.uid)))
    if result.nickname:
        lines.append(t("redeem.field_nickname", lang, nickname=html.escape(result.nickname)))
    if result.region:
        lines.append(t("redeem.field_region", lang, region=html.escape(result.region)))
    if result.rewards:
        rewards = ", ".join(html.escape(r) for r in result.rewards)
        lines.append(t("redeem.field_rewards", lang, rewards=rewards))
    lines.append("")
    lines.append(t(note_key, lang))
    return "\n".join(lines)


def _redeem_button(result: RedeemResult, lang: str) -> InlineKeyboardMarkup | None:
    """A one-tap button to the official redemption page (only when we have a URL)."""
    if not result.redeem_url:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("redeem.button_open", lang), url=result.redeem_url)]]
    )
