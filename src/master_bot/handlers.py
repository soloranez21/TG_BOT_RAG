"""
Master Bot command handlers.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from qdrant_client import QdrantClient

from .states import BotSetup
from .validators import validate_bot_token, validate_openai_key
from .process_manager import (
    spawn_personal_bot,
    stop_personal_bot,
    is_bot_running,
    get_bot_process_info,
)

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, db, qdrant_url: str):
    """Handle /start command."""
    # Check if user already has a bot
    existing = await db.get_user_bot(message.from_user.id)

    if existing:
        running = is_bot_running(message.from_user.id)
        status_emoji = "🟢" if running else "🔴"

        await message.answer(
            f"✅ У вас уже есть бот: @{existing.bot_username}\n"
            f"Статус: {status_emoji} {'Работает' if running else 'Остановлен'}\n\n"
            "Команды:\n"
            "/status - Проверить статус бота\n"
            "/restart - Перезапустить бота\n"
            "/delete - Удалить бота"
        )
        return

    await state.set_state(BotSetup.waiting_for_token)
    await message.answer(
        "👋 Добро пожаловать в Фабрику RAG-ботов!\n\n"
        "Я помогу вам создать персонального чат-бота для работы с документами.\n\n"
        "Вам понадобится:\n"
        "1. Токен бота от @BotFather\n"
        "2. API ключ OpenAI\n\n"
        "Готовы? Отправьте мне токен вашего бота.\n"
        "(Создайте бота в @BotFather командой /newbot)"
    )


@router.message(BotSetup.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    """Process the bot token."""
    token = message.text.strip()

    # Basic format check
    if ":" not in token or len(token) < 30:
        await message.answer(
            "❌ Это не похоже на токен бота.\n\n"
            "Токены выглядят так: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`\n\n"
            "Попробуйте ещё раз."
        )
        return

    status_msg = await message.answer("🔄 Проверяю токен бота...")

    is_valid, bot_username = await validate_bot_token(token)

    if not is_valid:
        await status_msg.edit_text(
            "❌ Неверный токен бота. Проверьте и попробуйте снова.\n\n"
            "Убедитесь, что отправляете токен от @BotFather."
        )
        return

    await state.update_data(bot_token=token, bot_username=bot_username)
    await state.set_state(BotSetup.waiting_for_openai_key)

    await status_msg.edit_text(
        f"✅ Токен подтверждён! Ваш бот: @{bot_username}\n\n"
        "Теперь отправьте API ключ OpenAI.\n"
        "(Получите на platform.openai.com/api-keys)"
    )


@router.message(BotSetup.waiting_for_openai_key)
async def process_openai_key(
    message: Message, state: FSMContext, db, qdrant_url: str
):
    """Process the OpenAI API key."""
    key = message.text.strip()

    # Try to delete the message containing the API key for security
    try:
        await message.delete()
    except Exception:
        pass  # May not have permission

    # Basic format check
    if not key.startswith("sk-"):
        await message.answer(
            "❌ Это не похоже на API ключ OpenAI.\n\n"
            "API ключи начинаются с `sk-`\n\n"
            "Попробуйте ещё раз."
        )
        return

    status_msg = await message.answer("🔄 Проверяю API ключ OpenAI...")

    is_valid = await validate_openai_key(key)

    if not is_valid:
        await status_msg.edit_text(
            "❌ Неверный API ключ OpenAI. Проверьте и попробуйте снова.\n\n"
            "Убедитесь, что ключ активен и на счёте есть средства."
        )
        return

    data = await state.get_data()

    await status_msg.edit_text("🚀 Создаю вашего персонального бота...")

    # Save to database
    try:
        await db.create_user_bot(
            telegram_user_id=message.from_user.id,
            bot_token=data["bot_token"],
            bot_username=data["bot_username"],
            openai_key=key,
        )
    except Exception as e:
        logger.error(f"Failed to create user bot: {e}")
        await status_msg.edit_text(
            "❌ Не удалось создать бота. Попробуйте позже."
        )
        return

    # Spawn personal bot
    qdrant_collection = f"user_{message.from_user.id}"
    success = spawn_personal_bot(
        telegram_user_id=message.from_user.id,
        bot_token=data["bot_token"],
        openai_key=key,
        qdrant_collection=qdrant_collection,
        qdrant_url=qdrant_url,
    )

    await state.clear()

    if success:
        await status_msg.edit_text(
            f"✅ Готово! Ваш бот запущен: @{data['bot_username']}\n\n"
            "Перейдите к боту и загрузите ZIP-архив с документами!"
        )
    else:
        await status_msg.edit_text(
            f"⚠️ Бот создан, но не удалось запустить: @{data['bot_username']}\n\n"
            "Используйте /restart для повторного запуска."
        )


@router.message(Command("status"))
async def cmd_status(message: Message, db):
    """Handle /status command."""
    bot_data = await db.get_user_bot(message.from_user.id)

    if not bot_data:
        await message.answer(
            "❌ У вас ещё нет бота.\n\n"
            "Используйте /start чтобы создать."
        )
        return

    running = is_bot_running(message.from_user.id)
    status_emoji = "🟢" if running else "🔴"

    await message.answer(
        f"📊 Статус бота\n\n"
        f"Бот: @{bot_data.bot_username}\n"
        f"Статус: {status_emoji} {'Работает' if running else 'Остановлен'}\n"
        f"Документов: {bot_data.document_count}\n"
        f"Чанков: {bot_data.chunk_count}\n\n"
        "Команды:\n"
        "/restart - Перезапустить бота\n"
        "/delete - Удалить бота"
    )


@router.message(Command("restart"))
async def cmd_restart(message: Message, db, qdrant_url: str):
    """Handle /restart command."""
    bot_data = await db.get_user_bot(message.from_user.id)

    if not bot_data:
        await message.answer(
            "❌ У вас ещё нет бота.\n\n"
            "Используйте /start чтобы создать."
        )
        return

    status_msg = await message.answer("🔄 Перезапускаю бота...")

    # Stop if running
    stop_personal_bot(message.from_user.id)

    # Spawn again
    success = spawn_personal_bot(
        telegram_user_id=message.from_user.id,
        bot_token=bot_data.bot_token,
        openai_key=bot_data.openai_key,
        qdrant_collection=bot_data.qdrant_collection,
        qdrant_url=qdrant_url,
    )

    if success:
        await status_msg.edit_text(
            f"✅ Бот перезапущен: @{bot_data.bot_username}"
        )
    else:
        await status_msg.edit_text(
            "❌ Не удалось перезапустить бота. Попробуйте ещё раз."
        )


@router.message(Command("delete"))
async def cmd_delete(message: Message, db, qdrant_url: str):
    """Handle /delete command."""
    bot_data = await db.get_user_bot(message.from_user.id)

    if not bot_data:
        await message.answer("❌ У вас нет бота для удаления.")
        return

    status_msg = await message.answer("🗑️ Удаляю бота...")

    # Stop bot process
    stop_personal_bot(message.from_user.id)

    # Delete Qdrant collection
    try:
        qdrant = QdrantClient(url=qdrant_url)
        qdrant.delete_collection(bot_data.qdrant_collection)
    except Exception as e:
        logger.warning(f"Failed to delete Qdrant collection: {e}")

    # Delete from database
    await db.delete_user_bot(message.from_user.id)

    await status_msg.edit_text(
        "✅ Бот удалён.\n\n"
        "Используйте /start чтобы создать нового."
    )




@router.message(Command("debug"))
async def cmd_debug(message: Message, db):
    """Handle /debug command - show detailed process information."""
    bot_data = await db.get_user_bot(message.from_user.id)

    if not bot_data:
        await message.answer("❌ У вас ещё нет бота.")
        return

    # Get process info
    info = get_bot_process_info(message.from_user.id)
    
    debug_msg = f"🔍 Диагностика бота @{bot_data.bot_username}\n\n"
    debug_msg += f"Статус: {info['status']}\n"
    debug_msg += f"Сообщение: {info['message']}\n"
    
    if info['status'] == 'running':
        debug_msg += f"PID: {info['pid']}\n"
        
        # Show last logs for running process
        if info.get('stdout'):
            last_stdout = info['stdout'][-500:] if len(info['stdout']) > 500 else info['stdout']
            if last_stdout.strip():
                debug_msg += f"\n📤 Последние логи (STDOUT):\n{last_stdout}\n"
        
        if info.get('stderr'):
            last_stderr = info['stderr'][-500:] if len(info['stderr']) > 500 else info['stderr']
            if last_stderr.strip():
                debug_msg += f"\n📛 Ошибки (STDERR):\n{last_stderr}\n"
                
    elif info['status'] == 'terminated':
        debug_msg += f"Exit Code: {info['exit_code']}\n"
        if info.get('stdout'):
            debug_msg += f"\n📤 STDOUT:\n{info['stdout'][:500]}\n"
        if info.get('stderr'):
            debug_msg += f"\n📛 STDERR:\n{info['stderr'][:500]}\n"
    
    await message.answer(debug_msg)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command."""
    await message.answer(
        "📚 Помощь по Фабрике RAG-ботов\n\n"
        "Этот бот помогает создать персонального чат-бота для работы с документами.\n\n"
        "Команды:\n"
        "/start - Создать нового бота или посмотреть существующего\n"
        "/status - Проверить статус бота\n"
        "/restart - Перезапустить бота\n"
        "/delete - Удалить бота\n"
        "/debug - Показать детальную диагностику процесса\n"
        "/help - Показать эту справку\n\n"
        "Нужна помощь? Пишите @airanez"
    )

