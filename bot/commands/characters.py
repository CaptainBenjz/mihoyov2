"""Character showcase commands and callback navigation.

Commands:
    /mycharacters (/myc) — browse your own showcase.
    /inspect <UID>       — browse another player's showcase.

Navigation is driven entirely by inline-button ``callback_data`` (see
:mod:`bot.utils.callbacks`), so switching pages or opening/closing a character edits the
same message and never requires rerunning the command. State is reconstructed from the
pressed button plus the cached showcase.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.app_context import AppContext
from bot.commands.common import get_app, guard, resolve_language, user_id_of
from bot.models.character import Character
from bot.models.player import Showcase
from bot.translations.i18n import t
from bot.utils import callbacks
from bot.utils.errors import BotError
from bot.utils.logging import get_logger

logger = get_logger(__name__)

PAGE_SIZE = 8       # character buttons per page
COLUMNS = 2

CALLBACK_PREFIX = "gsc"  # matches the CallbackQueryHandler pattern in main.py


# --------------------------------------------------------------------------- commands
@guard
async def my_characters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)
    if tg_id is None:
        return
    uid = await app.account_service.require_uid(tg_id)
    showcase = await app.character_service.get_showcase(uid, lang)
    text, markup = _render_list(showcase, uid, page=0, lang=lang, viewer_uid=uid)
    await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


@guard
async def inspect(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    lang = await resolve_language(update, context)
    if not context.args:
        await update.message.reply_text(t("inspect.usage", lang), parse_mode=ParseMode.HTML)
        return
    from bot.services.account_service import validate_uid

    uid = validate_uid(context.args[0])  # raises InvalidUID -> handled by @guard
    viewer_uid = await app.account_service.get_uid(user_id_of(update)) if user_id_of(update) else None
    showcase = await app.character_service.get_showcase(uid, lang)
    text, markup = _render_list(showcase, uid, page=0, lang=lang, viewer_uid=viewer_uid)
    await update.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)


# --------------------------------------------------------------------------- callback router
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline-button presses for the character-browsing flow."""
    query = update.callback_query
    if query is None:
        return
    app = get_app(context)
    lang = await resolve_language(update, context)
    tg_id = user_id_of(update)
    viewer_uid = await app.account_service.get_uid(tg_id) if tg_id else None

    cb = callbacks.decode(query.data or "")
    try:
        if cb.action == callbacks.ACTION_NOOP:
            await query.answer()
            return

        if cb.action == callbacks.ACTION_CHAR:
            showcase = await app.character_service.get_showcase(cb.uid, lang)
            character = showcase.get_character(cb.char_id)
            if character is None:
                await query.answer(t("error.character_not_found", lang), show_alert=True)
                return
            text = _render_character(character, lang)
            markup = _character_keyboard(cb.uid, cb.page, lang)
            await _safe_edit(query, text, markup)
            await query.answer()
            return

        # LIST / PAGE / BACK all resolve to showing the list at a page.
        showcase = await app.character_service.get_showcase(cb.uid, lang)
        text, markup = _render_list(showcase, cb.uid, page=cb.page, lang=lang, viewer_uid=viewer_uid)
        await _safe_edit(query, text, markup)
        await query.answer()
    except BotError as exc:
        await query.answer(t(exc.i18n_key, lang), show_alert=True)
    except Exception:  # noqa: BLE001 - never crash on a button press
        logger.exception("Callback failed")
        await query.answer(t("error.generic", lang), show_alert=True)


# --------------------------------------------------------------------------- rendering (text)
def _render_list(
    showcase: Showcase, uid: str, *, page: int, lang: str, viewer_uid: str | None
) -> tuple[str, InlineKeyboardMarkup]:
    chars = showcase.characters
    if not chars:
        raise _empty_showcase_error()

    total_pages = max(1, (len(chars) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    page_chars = chars[start : start + PAGE_SIZE]

    is_own = viewer_uid is not None and viewer_uid == uid
    title = t("characters.title", lang) if is_own else t("characters.title_other", lang, uid=uid)
    text = f"{title}\n{t('characters.page', lang, current=page + 1, total=total_pages)}"

    # Character buttons, arranged in rows of COLUMNS.
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for c in page_chars:
        label = f"{c.name} (Lv.{c.level} C{c.constellation})"
        row.append(
            InlineKeyboardButton(
                label, callback_data=callbacks.encode(callbacks.ACTION_CHAR, uid=uid, char_id=c.id, page=page)
            )
        )
        if len(row) == COLUMNS:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Pagination row (only when more than one page).
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    t("common.prev", lang),
                    callback_data=callbacks.encode(callbacks.ACTION_PAGE, uid=uid, page=page - 1),
                )
            )
        if page < total_pages - 1:
            nav.append(
                InlineKeyboardButton(
                    t("common.next", lang),
                    callback_data=callbacks.encode(callbacks.ACTION_PAGE, uid=uid, page=page + 1),
                )
            )
        if nav:
            rows.append(nav)

    return text, InlineKeyboardMarkup(rows)


def _character_keyboard(uid: str, page: int, lang: str) -> InlineKeyboardMarkup:
    """A single 'Back' button that returns to the list at the page we came from."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t("common.back", lang), callback_data=callbacks.encode(callbacks.ACTION_BACK, uid=uid, page=page))]]
    )


def _render_character(c: Character, lang: str) -> str:
    """Full text build of a character (placeholder for the future image card)."""
    lines = [t("character.details_title", lang, name=c.name)]
    lines.append(t("character.level", lang, level=c.level))
    lines.append(t("character.constellation", lang, constellation=c.constellation))

    if c.weapon:
        lines.append(
            t("character.weapon", lang, name=c.weapon.name, refinement=c.weapon.refinement, level=c.weapon.level)
        )
    else:
        lines.append(t("character.no_weapon", lang))

    if c.talents:
        talents = ", ".join(f"{tal.name} {tal.level}" for tal in c.talents)
        lines.append(t("character.talents", lang, talents=talents))

    # Stats block.
    s = c.stats
    lines.append("")
    lines.append(t("character.stats_title", lang))
    lines.append(f"{t('stats.hp', lang)}: {s.hp:,.0f}")
    lines.append(f"{t('stats.atk', lang)}: {s.atk:,.0f}")
    lines.append(f"{t('stats.def', lang)}: {s.defense:,.0f}")
    lines.append(f"{t('stats.crit_rate', lang)}: {s.crit_rate:.1f}%")
    lines.append(f"{t('stats.crit_dmg', lang)}: {s.crit_dmg:.1f}%")
    lines.append(f"{t('stats.energy_recharge', lang)}: {s.energy_recharge:.1f}%")
    lines.append(f"{t('stats.elemental_mastery', lang)}: {s.elemental_mastery:,.0f}")

    # Artifacts.
    lines.append("")
    lines.append(t("character.artifacts_title", lang))
    if c.artifacts:
        for a in c.artifacts:
            main = f"{a.main_stat.name} {a.main_stat.value:g}" if a.main_stat else "-"
            lines.append(t("character.artifact_line", lang, slot=a.slot, set_name=a.set_name or "-", level=a.level, main_stat=main))
    else:
        lines.append(t("character.no_artifacts", lang))

    # Ranking (only if present).
    if c.ranking and c.ranking.available:
        lines.append("")
        lines.append(t("ranking.title", lang))
        if c.ranking.rank is not None:
            lines.append(t("ranking.rank", lang, rank=c.ranking.rank))
        if c.ranking.total_players is not None:
            lines.append(t("ranking.total_players", lang, total=c.ranking.total_players))
        if c.ranking.top_percent is not None:
            lines.append(t("ranking.top_percent", lang, percent=f"{c.ranking.top_percent:.1f}"))

    return "\n".join(lines)


async def _safe_edit(query, text: str, markup: InlineKeyboardMarkup) -> None:
    """Edit the message text; ignore 'message not modified' style errors."""
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except Exception as exc:  # noqa: BLE001 - editing to identical content raises BadRequest
        logger.debug("edit_message_text ignored: %s", exc)


def _empty_showcase_error() -> BotError:
    from bot.utils.errors import EmptyShowcase

    return EmptyShowcase()
