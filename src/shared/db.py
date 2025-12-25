"""
Database module - PostgreSQL operations using asyncpg.
"""
import asyncpg
from typing import Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class UserBot:
    """Represents a user's personal bot configuration."""

    id: int
    telegram_user_id: int
    bot_token: str
    bot_username: str
    openai_key: str
    qdrant_collection: str
    status: str
    document_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: asyncpg.Record) -> "UserBot":
        """Create UserBot from database record."""
        return cls(
            id=record["id"],
            telegram_user_id=record["telegram_user_id"],
            bot_token=record["bot_token"],
            bot_username=record["bot_username"],
            openai_key=record["openai_key"],
            qdrant_collection=record["qdrant_collection"],
            status=record["status"],
            document_count=record["document_count"],
            chunk_count=record["chunk_count"],
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )


class Database:
    """Async PostgreSQL database wrapper."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Create connection pool."""
        self.pool = await asyncpg.create_pool(self.dsn)

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self.pool:
            await self.pool.close()

    async def create_user_bot(
        self,
        telegram_user_id: int,
        bot_token: str,
        bot_username: str,
        openai_key: str,
    ) -> int:
        """
        Create a new user bot record.
        Returns the new record ID.
        """
        qdrant_collection = f"user_{telegram_user_id}"

        return await self.pool.fetchval(
            """
            INSERT INTO user_bots (
                telegram_user_id, bot_token, bot_username,
                openai_key, qdrant_collection
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            telegram_user_id,
            bot_token,
            bot_username,
            openai_key,
            qdrant_collection,
        )

    async def get_user_bot(self, telegram_user_id: int) -> Optional[UserBot]:
        """Get user bot by Telegram user ID."""
        record = await self.pool.fetchrow(
            "SELECT * FROM user_bots WHERE telegram_user_id = $1",
            telegram_user_id,
        )
        if record:
            return UserBot.from_record(record)
        return None

    async def get_active_bots(self) -> list[UserBot]:
        """Get all active user bots."""
        records = await self.pool.fetch(
            "SELECT * FROM user_bots WHERE status = 'active'"
        )
        return [UserBot.from_record(r) for r in records]

    async def update_status(self, telegram_user_id: int, status: str) -> None:
        """Update bot status."""
        await self.pool.execute(
            """
            UPDATE user_bots
            SET status = $1, updated_at = NOW()
            WHERE telegram_user_id = $2
            """,
            status,
            telegram_user_id,
        )

    async def update_counts(
        self, telegram_user_id: int, document_count: int, chunk_count: int
    ) -> None:
        """Update document and chunk counts."""
        await self.pool.execute(
            """
            UPDATE user_bots
            SET document_count = $1, chunk_count = $2, updated_at = NOW()
            WHERE telegram_user_id = $3
            """,
            document_count,
            chunk_count,
            telegram_user_id,
        )

    async def delete_user_bot(self, telegram_user_id: int) -> bool:
        """
        Delete user bot record.
        Returns True if deleted, False if not found.
        """
        result = await self.pool.execute(
            "DELETE FROM user_bots WHERE telegram_user_id = $1",
            telegram_user_id,
        )
        return result == "DELETE 1"
