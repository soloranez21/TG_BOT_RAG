"""
Validators for bot tokens and API keys.
"""
import aiohttp
from openai import AsyncOpenAI


async def validate_bot_token(token: str) -> tuple[bool, str | None]:
    """
    Validate a Telegram bot token by calling the getMe API.

    Args:
        token: The bot token to validate

    Returns:
        Tuple of (is_valid, bot_username or None)
    """
    url = f"https://api.telegram.org/bot{token}/getMe"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok"):
                        return True, data["result"]["username"]
                return False, None
    except Exception:
        return False, None


async def validate_openai_key(key: str) -> bool:
    """
    Validate an OpenAI API key by making a test embedding call.

    Args:
        key: The OpenAI API key to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        client = AsyncOpenAI(api_key=key)
        await client.embeddings.create(
            model="text-embedding-3-small",
            input="test",
        )
        return True
    except Exception:
        return False
