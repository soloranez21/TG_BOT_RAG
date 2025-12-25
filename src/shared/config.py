"""
Configuration module - loads environment variables.
"""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load .env file
load_dotenv()


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # Master Bot
    master_bot_token: str

    # Database
    database_url: str

    # Qdrant Vector Store
    qdrant_url: str

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        master_bot_token = os.getenv("MASTER_BOT_TOKEN")
        if not master_bot_token:
            raise ValueError("MASTER_BOT_TOKEN environment variable is required")

        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is required")

        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

        return cls(
            master_bot_token=master_bot_token,
            database_url=database_url,
            qdrant_url=qdrant_url,
        )


# Global config instance - loaded lazily
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


# For convenience, export as 'config'
config = property(lambda self: get_config())
