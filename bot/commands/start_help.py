"""/start and /help handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.commands.common import get_app, guard, reply, resolve_language, user_id_of
from bot.translations.i18n import t


@guard
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    app = get_app(context)
    uid = user_id_of(update)
    # Ensure a user row exists so language/settings persist from first contact.
    if uid is not None:
        await app.users.get_or_create(uid, app.settings.default_language)
    lang = await resolve_language(update, context)
    await reply(update, t("start.welcome", lang))


@guard
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await resolve_language(update, context)
    await reply(update, t("help.text", lang))
