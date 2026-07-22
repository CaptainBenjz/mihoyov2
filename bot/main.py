"""Bot entrypoint: build the Application, wire handlers, and start polling.

Run with::

    python -m bot.main

Requires ``BOT_TOKEN`` in the environment / ``.env``.
"""

from __future__ import annotations

import sys

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    TypeHandler,
)

from bot.app_context import BOT_DATA_KEY, build_app_context
from bot.commands import (
    abyss,
    account,
    banner,
    build_guide,
    characters,
    ownership,
    settings_lang,
    start_help,
    stats,
    theater,
    tracking,
)
from bot.config import get_settings
from bot.translations.i18n import t
from bot.utils.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def _post_init(application: Application) -> None:
    """Build the dependency container and verify Redis before serving traffic."""
    app_ctx = build_app_context(get_settings())
    application.bot_data[BOT_DATA_KEY] = app_ctx

    # Verify the primary datastore is reachable before the bot becomes operational.
    if await app_ctx.redis.verify():
        logger.info("Redis (primary datastore) is connected")
    else:
        logger.error(
            "Redis connection could not be verified — running in DEGRADED mode. "
            "Persistence and stats may be unavailable until Redis recovers."
        )

    await _set_bot_commands(application)
    logger.info("Bot initialized and ready")


async def _post_shutdown(application: Application) -> None:
    app_ctx = application.bot_data.get(BOT_DATA_KEY)
    if app_ctx is not None:
        await app_ctx.redis.close()


async def _set_bot_commands(application: Application) -> None:
    """Publish the command list shown in Telegram's UI (best-effort)."""
    commands = [
        ("start", "Start the bot"),
        ("help", "Show help"),
        ("genshinlogin", "Link your Genshin UID"),
        ("genshinlogout", "Unlink your account"),
        ("myuid", "Show your linked UID"),
        ("myinfo", "Show your account info"),
        ("mycharacters", "Browse your showcased characters"),
        ("myc", "Browse your showcased characters"),
        ("inspect", "Inspect another player's showcase"),
        ("abyss", "Spiral Abyss"),
        ("preabyss", "Previous Spiral Abyss"),
        ("abysscard", "Spiral Abyss card"),
        ("preabysscard", "Previous Spiral Abyss card"),
        ("theater", "Imaginarium Theater"),
        ("theatercard", "Imaginarium Theater card"),
        ("banner", "Banner information"),
        ("build_guide", "Build recommendations"),
        ("settings", "Your settings"),
        ("language", "Change language"),
        ("stats", "Bot statistics"),
    ]
    try:
        await application.bot.set_my_commands(commands)
    except Exception as exc:  # noqa: BLE001 - non-critical
        logger.warning("Failed to set bot commands: %s", exc)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler — last line of defence so the bot never crashes."""
    logger.exception("Unhandled exception", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.effective_message is not None:
            await update.effective_message.reply_text(t("error.generic", "en"))
    except Exception:  # noqa: BLE001
        pass


def _register_handlers(application: Application) -> None:
    # --- universal ownership gate (group=-2: runs before tracking and all callback
    #     handlers; blocks non-owners from operating another user's inline keyboard) ---
    application.add_handler(CallbackQueryHandler(ownership.enforce_callback_owner), group=-2)

    # --- tracking (group=-1 so it runs first, then command handlers in group 0 also run) ---
    application.add_handler(TypeHandler(Update, tracking.track), group=-1)
    application.add_handler(
        ChatMemberHandler(tracking.on_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # --- simple commands ---
    application.add_handler(CommandHandler("start", start_help.start))
    application.add_handler(CommandHandler("help", start_help.help_command))
    application.add_handler(CommandHandler("stats", stats.stats))

    # --- account ---
    application.add_handler(CommandHandler("genshinlogin", account.genshin_login))
    application.add_handler(CommandHandler("genshinlogout", account.genshin_logout))
    application.add_handler(CommandHandler("myuid", account.my_uid))
    application.add_handler(CommandHandler("myinfo", account.my_info))

    # --- characters (with /myc alias) ---
    application.add_handler(CommandHandler(["mycharacters", "myc"], characters.my_characters))
    application.add_handler(CommandHandler("inspect", characters.inspect))

    # --- abyss ---
    application.add_handler(CommandHandler("abyss", abyss.abyss))
    application.add_handler(CommandHandler("preabyss", abyss.pre_abyss))
    application.add_handler(CommandHandler("abysscard", abyss.abyss_card))
    application.add_handler(CommandHandler("preabysscard", abyss.pre_abyss_card))

    # --- theater ---
    application.add_handler(CommandHandler("theater", theater.theater))
    application.add_handler(CommandHandler("theatercard", theater.theater_card))

    # --- misc ---
    application.add_handler(CommandHandler("banner", banner.banner))
    application.add_handler(CommandHandler("build_guide", build_guide.build_guide))
    application.add_handler(CommandHandler("settings", settings_lang.settings))
    application.add_handler(CommandHandler("language", settings_lang.language))

    # --- callback queries (order matters: most specific first) ---
    application.add_handler(
        CallbackQueryHandler(settings_lang.on_settings_menu_callback, pattern=r"^lang:__menu__")
    )
    application.add_handler(CallbackQueryHandler(settings_lang.on_language_callback, pattern=r"^lang:"))
    application.add_handler(
        CallbackQueryHandler(characters.on_callback, pattern=r"^(list|char|page|back|noop)\|")
    )

    application.add_error_handler(_on_error)


def build_application() -> Application:
    settings = get_settings()
    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set. Copy .env.example to .env and set BOT_TOKEN.")
        sys.exit(1)
    if not settings.redis_url:
        logger.error("REDIS_URL is not set. Redis is the primary datastore; set it in .env.")
        sys.exit(1)

    application = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    _register_handlers(application)
    return application


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting Genshin Impact Telegram bot")
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
