"""
Personal Bot - Entry point.

This bot handles document processing and RAG queries for a single user.
It receives configuration via command-line arguments from the master bot.
"""
import argparse
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .handlers import router
from .document_processor import DocumentProcessor
from .rag_chain import RAGChain

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Personal RAG Bot")
    parser.add_argument(
        "--user-id",
        type=int,
        required=True,
        help="Telegram user ID (owner of this bot)",
    )
    parser.add_argument(
        "--bot-token",
        required=True,
        help="Telegram bot token",
    )
    parser.add_argument(
        "--openai-key",
        required=True,
        help="OpenAI API key",
    )
    parser.add_argument(
        "--collection",
        required=True,
        help="Qdrant collection name",
    )
    parser.add_argument(
        "--qdrant-url",
        default="http://localhost:6333",
        help="Qdrant server URL",
    )
    return parser.parse_args()


async def main():
    """Main entry point for the personal bot."""
    args = parse_args()

    logger.info(f"Starting Personal Bot for user {args.user_id}")

    # Initialize bot and dispatcher
    bot = Bot(token=args.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    # Initialize components
    processor = DocumentProcessor()
    rag = RAGChain(
        openai_key=args.openai_key,
        qdrant_url=args.qdrant_url,
        collection_name=args.collection,
    )

    # Inject dependencies into dispatcher
    dp["processor"] = processor
    dp["rag"] = rag

    # Register handlers
    dp.include_router(router)

    logger.info(f"Personal Bot for user {args.user_id} is running...")

    # Start polling
    try:
        await dp.start_polling(bot)
    finally:
        logger.info(f"Personal Bot for user {args.user_id} stopped")


if __name__ == "__main__":
    asyncio.run(main())
