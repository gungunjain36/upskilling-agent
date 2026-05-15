import logging
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes,
)
from config import settings
from agents import handle_message
from core.scheduler import set_send_callback, start_scheduler, reschedule
from core.memory import get_schedule_config, clear_session, save_session_summary

logger = logging.getLogger(__name__)

_application: Application | None = None

_BOT_COMMANDS = [
    BotCommand("start", "Start or restart the bot"),
    BotCommand("challenge", "Get a practice problem"),
    BotCommand("concept", "Get a concept explained"),
    BotCommand("progress", "See your full roadmap progress"),
    BotCommand("status", "Quick level overview"),
    BotCommand("topic", "What's next on your roadmap"),
    BotCommand("domains", "List your configured topics"),
    BotCommand("help", "Show available commands"),
    BotCommand("newsession", "Clear conversation context and start fresh"),
    BotCommand("reschedule", "Change delivery interval (e.g. /reschedule 2)"),
]


def get_application() -> Application:
    global _application
    if _application is None:
        _application = Application.builder().token(settings.telegram_bot_token).build()
    return _application


async def send_message(text: str):
    """Send a message to the configured chat ID (used by scheduler)."""
    app = get_application()
    if len(text) <= 4096:
        await app.bot.send_message(
            chat_id=settings.telegram_chat_id,
            text=text,
            parse_mode="Markdown",
        )
    else:
        for chunk in _split_message(text):
            await app.bot.send_message(
                chat_id=settings.telegram_chat_id,
                text=chunk,
                parse_mode="Markdown",
            )


def _split_message(text: str, limit: int = 4000) -> list[str]:
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks


async def _route_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route all incoming messages through the orchestrator."""
    if update.effective_chat.id != int(settings.telegram_chat_id):
        await update.message.reply_text("Unauthorized.")
        return

    user_text = update.message.text or ""
    if not user_text:
        return

    # If the user explicitly replied to a specific bot message, pass that as context.
    # This lets them reply to an old challenge even if newer cron messages arrived.
    reply_context: str | None = None
    if update.message.reply_to_message and update.message.reply_to_message.text:
        reply_context = update.message.reply_to_message.text

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing",
    )

    try:
        response = await handle_message(user_text, reply_context=reply_context)
        await update.message.reply_text(response, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        await update.message.reply_text(
            "Hit an error on my end — give it a moment and try again."
        )


async def _start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != int(settings.telegram_chat_id):
        return
    response = await handle_message("/start")
    await update.message.reply_text(response, parse_mode="Markdown")


async def _newsession_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != int(settings.telegram_chat_id):
        return
    clear_session()
    save_session_summary("")
    await update.message.reply_text("Session cleared. Next message starts a fresh context.")


async def _reschedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != int(settings.telegram_chat_id):
        return
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /reschedule <hours> (e.g., /reschedule 2)")
        return
    hours = int(args[0])
    reschedule(hours)
    config = get_schedule_config()
    config["interval_hours"] = hours
    from core.memory import save_schedule_config
    save_schedule_config(config)
    await update.message.reply_text(f"Rescheduled concept delivery to every {hours} hour(s).")


async def _register_commands(app: Application):
    try:
        await app.bot.set_my_commands(_BOT_COMMANDS)
        logger.info("Bot commands registered")
    except Exception as e:
        logger.warning(f"Could not register bot commands: {e}")


def setup_bot() -> Application:
    app = get_application()

    app.add_handler(CommandHandler("start", _start_command))
    app.add_handler(CommandHandler("newsession", _newsession_command))
    app.add_handler(CommandHandler("reschedule", _reschedule_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _route_message))
    app.add_handler(MessageHandler(filters.COMMAND, _route_message))

    # Register commands with Telegram so they appear in the dropdown
    app.post_init = _post_init

    set_send_callback(send_message)
    return app


async def _post_init(app: Application):
    await _register_commands(app)
    start_scheduler()
