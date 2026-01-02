"""
Master Bot - Entry point.

This bot manages the creation and lifecycle of personal document bots.
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from src.shared.config import get_config
from src.shared.db import Database
from .handlers import router
from .process_manager import respawn_all_bots

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the master bot."""
    # Load configuration
    config = get_config()

    logger.info("Starting Master Bot...")

    # Initialize bot and dispatcher
    bot = Bot(token=config.master_bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    # Initialize database
    db = Database(config.database_url)
    await db.connect()
    await db.init_db()
    logger.info("Connected to database and initialized schema")

    # Inject dependencies into dispatcher
    dp["db"] = db
    dp["qdrant_url"] = config.qdrant_url

    # Register handlers
    dp.include_router(router)

    # Respawn active bots on startup
    try:
        active_bots = await db.get_active_bots()
        if active_bots:
            count = respawn_all_bots(active_bots, config.qdrant_url)
            logger.info(f"Respawned {count} active bots")
    except Exception as e:
        logger.error(f"Failed to respawn bots: {e}")

    # Start polling
    logger.info("Master Bot is running...")
    try:
        await dp.start_polling(bot)
    finally:
        await db.disconnect()
        logger.info("Master Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
