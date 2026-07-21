"""
Entrypoint. Run with: python bot.py
Requires TELEGRAM_BOT_TOKEN and IMGBB_API_KEY in the environment (or a .env file).

Also starts a tiny HTTP server on $PORT (default 8080). This does nothing for
the bot itself — it only exists so that Render's free "Web Service" tier has
something to health-check and route traffic to. Render's free tier requires
a bound port and puts the service to sleep after ~15 minutes of no HTTP
traffic; use an external pinger (e.g. UptimeRobot, cron-job.org) hitting this
service's URL every 5-10 minutes to keep it awake.
"""
import asyncio
import logging
import os

from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import load_settings, configure_logging
from handlers import (
    TITLE,
    DESCRIPTION,
    COLLECT_IMAGES,
    COLLECT_LINKS,
    DONE_CALLBACK_DATA,
    start,
    receive_title,
    receive_description,
    receive_image,
    images_done,
    receive_link_text,
    links_done,
    cancel,
)

logger = logging.getLogger(__name__)


def build_application() -> Application:
    settings = load_settings()
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["settings"] = settings

    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            TITLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title),
            ],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description),
            ],
            COLLECT_IMAGES: [
                CommandHandler("done", images_done),
                CallbackQueryHandler(images_done, pattern=f"^{DONE_CALLBACK_DATA}$"),
                MessageHandler(
                    (filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND,
                    receive_image,
                ),
            ],
            COLLECT_LINKS: [
                CommandHandler("done", links_done),
                CallbackQueryHandler(links_done, pattern=f"^{DONE_CALLBACK_DATA}$"),
                MessageHandler(
                    (filters.TEXT | filters.CAPTION) & ~filters.COMMAND,
                    receive_link_text,
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(conversation)
    return application


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def _run_web_server() -> None:
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", _health)
    app.router.add_get("/health", _health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health-check web server listening on port %d", port)


async def _run_bot(application: Application) -> None:
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot polling started.")


async def _amain() -> None:
    configure_logging()
    application = build_application()

    await _run_web_server()
    await _run_bot(application)

    # Keep the process alive until interrupted (Ctrl+C / SIGTERM).
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()

