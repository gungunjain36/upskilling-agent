import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from bot.telegram_bot import setup_bot
from core.tracker import init_tracker

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting UpskillBot...")
    init_tracker()

    telegram_app = setup_bot()
    await telegram_app.initialize()  # triggers post_init: registers commands + starts scheduler
    await telegram_app.start()

    # Start polling in background
    asyncio.create_task(telegram_app.updater.start_polling(drop_pending_updates=True))

    logger.info("UpskillBot is live and polling Telegram.")
    yield

    logger.info("Shutting down...")
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()


app = FastAPI(title="UpskillBot", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {"message": "UpskillBot is running"}
