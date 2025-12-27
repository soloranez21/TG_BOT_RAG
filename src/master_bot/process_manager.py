"""
Process Manager - handles spawning and managing personal bot subprocesses.
"""
import subprocess
import sys
import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# Global dict tracking running bot processes: telegram_user_id -> Popen
running_bots: dict[int, subprocess.Popen] = {}


def get_personal_bot_path() -> Path:
    """Get the path to the personal bot main.py."""
    return Path(__file__).parent.parent / "personal_bot" / "main.py"


def spawn_personal_bot(
    telegram_user_id: int,
    bot_token: str,
    openai_key: str,
    qdrant_collection: str,
    qdrant_url: str,
) -> bool:
    """
    Spawn a personal bot subprocess.

    Args:
        telegram_user_id: The Telegram user ID
        bot_token: The personal bot's Telegram token
        openai_key: The user's OpenAI API key
        qdrant_collection: The Qdrant collection name
        qdrant_url: The Qdrant server URL

    Returns:
        True if spawned successfully, False otherwise
    """
    logger.info(f"[SPAWN] Starting spawn process for user {telegram_user_id}")
    
    # Check if already running
    if telegram_user_id in running_bots:
        proc = running_bots[telegram_user_id]
        if proc.poll() is None:  # Still running
            logger.info(f"[SPAWN] Bot for user {telegram_user_id} is already running (PID: {proc.pid})")
            return True
        else:
            logger.warning(f"[SPAWN] Found dead process for user {telegram_user_id}, will respawn")

    personal_bot_path = get_personal_bot_path()
    logger.info(f"[SPAWN] Personal bot path: {personal_bot_path}")

    if not personal_bot_path.exists():
        logger.error(f"[SPAWN] Personal bot script not found at {personal_bot_path}")
        return False

    # Build command for logging
    cmd = [
        sys.executable,
        "-m", "src.personal_bot.main",
        "--user-id", str(telegram_user_id),
        "--bot-token", bot_token,
        "--openai-key", openai_key[:10] + "...",  # Log only first 10 chars for security
        "--collection", qdrant_collection,
        "--qdrant-url", qdrant_url,
    ]
    logger.info(f"[SPAWN] Command: {' '.join(cmd)}")
    logger.info(f"[SPAWN] Python executable: {sys.executable}")

    # Get project root directory (where src/ is located)
    project_root = personal_bot_path.parent.parent.parent
    logger.info(f"[SPAWN] Project root: {project_root}")

    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m", "src.personal_bot.main",  # Run as module instead of script
                "--user-id", str(telegram_user_id),
                "--bot-token", bot_token,
                "--openai-key", openai_key,
                "--collection", qdrant_collection,
                "--qdrant-url", qdrant_url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(project_root),  # Set working directory to project root
        )

        running_bots[telegram_user_id] = proc
        logger.info(f"[SPAWN] ✅ Spawned personal bot for user {telegram_user_id} (PID: {proc.pid})")
        
        # Check if process is still alive after a short delay
        import time
        time.sleep(0.5)
        
        if proc.poll() is not None:
            # Process died immediately
            stdout, stderr = proc.communicate()
            logger.error(f"[SPAWN] ❌ Process died immediately! Exit code: {proc.returncode}")
            logger.error(f"[SPAWN] STDOUT: {stdout}")
            logger.error(f"[SPAWN] STDERR: {stderr}")
            del running_bots[telegram_user_id]
            return False
        
        logger.info(f"[SPAWN] Process is alive and running")
        return True

    except Exception as e:
        logger.error(f"[SPAWN] ❌ Failed to spawn personal bot for user {telegram_user_id}: {e}")
        logger.exception(e)
        return False


def stop_personal_bot(telegram_user_id: int) -> bool:
    """
    Stop a personal bot subprocess.

    Args:
        telegram_user_id: The Telegram user ID

    Returns:
        True if stopped, False if not found
    """
    if telegram_user_id not in running_bots:
        return False

    proc = running_bots[telegram_user_id]

    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        del running_bots[telegram_user_id]
        logger.info(f"Stopped personal bot for user {telegram_user_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to stop personal bot for user {telegram_user_id}: {e}")
        return False


def is_bot_running(telegram_user_id: int) -> bool:
    """
    Check if a personal bot is running.

    Args:
        telegram_user_id: The Telegram user ID

    Returns:
        True if running, False otherwise
    """
    if telegram_user_id not in running_bots:
        return False

    proc = running_bots[telegram_user_id]
    return proc.poll() is None


def respawn_all_bots(
    active_bots: list,
    qdrant_url: str,
) -> int:
    """
    Respawn all active bots on master startup.

    Args:
        active_bots: List of UserBot objects from database
        qdrant_url: The Qdrant server URL

    Returns:
        Number of bots respawned
    """
    count = 0
    for bot in active_bots:
        success = spawn_personal_bot(
            telegram_user_id=bot.telegram_user_id,
            bot_token=bot.bot_token,
            openai_key=bot.openai_key,
            qdrant_collection=bot.qdrant_collection,
            qdrant_url=qdrant_url,
        )
        if success:
            count += 1

    logger.info(f"Respawned {count}/{len(active_bots)} active bots")
    return count


def get_running_bot_count() -> int:
    """Get the count of currently running bots."""
    return sum(1 for proc in running_bots.values() if proc.poll() is None)


def get_bot_process_info(telegram_user_id: int) -> dict:
    """
    Get detailed information about a bot process.
    
    Args:
        telegram_user_id: The Telegram user ID
        
    Returns:
        Dictionary with process information
    """
    if telegram_user_id not in running_bots:
        return {"status": "not_found", "message": "No process found"}
    
    proc = running_bots[telegram_user_id]
    
    # Check if process is still running
    poll_result = proc.poll()
    
    if poll_result is None:
        # Still running
        return {
            "status": "running",
            "pid": proc.pid,
            "message": f"Process is running with PID {proc.pid}"
        }
    else:
        # Process has terminated
        try:
            stdout, stderr = proc.communicate(timeout=1)
        except Exception:
            stdout, stderr = "", ""
            
        return {
            "status": "terminated",
            "exit_code": poll_result,
            "stdout": stdout,
            "stderr": stderr,
            "message": f"Process terminated with exit code {poll_result}"
        }

