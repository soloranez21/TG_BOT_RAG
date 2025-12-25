"""
Personal Bot command handlers.
"""
import tempfile
import logging
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message

from .document_processor import DocumentProcessor
from .rag_chain import RAGChain

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, processor: DocumentProcessor):
    """Handle /start command."""
    formats = processor.get_supported_formats()
    await message.answer(
        "👋 Привет! Я ваш персональный документ-ассистент.\n\n"
        f"Загрузите ZIP-архив с документами ({formats}), "
        "и я помогу вам искать информацию и отвечать на вопросы.\n\n"
        "Просто отправьте ZIP-файл, чтобы начать!"
    )


@router.message(Command("status"))
async def cmd_status(message: Message, rag: RAGChain):
    """Handle /status command."""
    doc_count, chunk_count = rag.get_stats()

    if chunk_count == 0:
        await message.answer(
            "📭 У вас пока нет загруженных документов.\n\n"
            "Отправьте ZIP-архив, чтобы начать!"
        )
    else:
        await message.answer(
            f"📊 Статус базы знаний\n\n"
            f"Документов: ~{doc_count}\n"
            f"Чанков: {chunk_count}\n\n"
            "Задайте вопрос по вашим документам!"
        )


@router.message(Command("clear"))
async def cmd_clear(message: Message, rag: RAGChain):
    """Handle /clear command."""
    status_msg = await message.answer("🗑️ Удаляю все документы...")

    try:
        rag.clear()
        await status_msg.edit_text(
            "✅ Все документы удалены.\n\n"
            "Загрузите новый ZIP-архив, чтобы начать заново."
        )
    except Exception as e:
        logger.error(f"Failed to clear documents: {e}")
        await status_msg.edit_text(
            "❌ Не удалось очистить документы. Попробуйте ещё раз."
        )


@router.message(Command("help"))
async def cmd_help(message: Message, processor: DocumentProcessor):
    """Handle /help command."""
    formats = processor.get_supported_formats()
    await message.answer(
        "📚 Помощь\n\n"
        "Я помогу вам работать с документами.\n\n"
        "Команды:\n"
        "/start - Приветствие\n"
        "/status - Статистика документов\n"
        "/clear - Удалить все документы\n"
        "/help - Эта справка\n\n"
        f"Поддерживаемые форматы: {formats}\n\n"
        "Просто отправьте ZIP-архив с документами или задайте вопрос!"
    )


@router.message(F.document)
async def handle_document(
    message: Message, bot: Bot, rag: RAGChain, processor: DocumentProcessor
):
    """Handle document uploads."""
    doc = message.document

    # Validate file type
    if not doc.file_name or not doc.file_name.lower().endswith(".zip"):
        await message.answer(
            "❌ Пожалуйста, отправьте ZIP-архив с документами."
        )
        return

    # Validate file size (50MB limit)
    if doc.file_size > 50 * 1024 * 1024:
        await message.answer(
            "❌ Файл слишком большой. Максимальный размер: 50 МБ."
        )
        return

    file_size_mb = doc.file_size / (1024 * 1024)
    status_msg = await message.answer(
        f"📦 Получен: {doc.file_name} ({file_size_mb:.1f} МБ)\n\n"
        "Обрабатываю документы..."
    )

    # Download file
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        await bot.download(doc, destination=tmp.name)
        zip_path = Path(tmp.name)

    try:
        results = []
        total_chunks = 0
        success_count = 0
        error_count = 0

        for filename, chunks, error in processor.process_zip(zip_path):
            if not filename and error:
                # Global error (e.g., invalid ZIP)
                await status_msg.edit_text(f"❌ {error}")
                return

            if chunks:
                added = rag.add_documents(chunks)
                total_chunks += added
                success_count += 1
                results.append(f"├── {filename} ✓ ({added} чанков)")
            else:
                error_count += 1
                results.append(f"├── {filename} ❌")

        if not results:
            await status_msg.edit_text(
                "❌ В архиве не найдено поддерживаемых документов.\n\n"
                f"Поддерживаемые форматы: {processor.get_supported_formats()}"
            )
            return

        # Fix last item prefix
        if results:
            results[-1] = results[-1].replace("├──", "└──")

        result_text = "\n".join(results)

        await status_msg.edit_text(
            f"📦 {doc.file_name}\n\n"
            f"{result_text}\n\n"
            f"✅ Проиндексировано: {success_count} документов ({total_chunks} чанков)\n"
            + (f"⚠️ С ошибками: {error_count}\n" if error_count > 0 else "")
            + "\nТеперь можете задавать вопросы по документам!"
        )

    except Exception as e:
        logger.error(f"Failed to process ZIP: {e}")
        await status_msg.edit_text(
            "❌ Ошибка при обработке архива. Проверьте, что это валидный ZIP-файл."
        )

    finally:
        # Cleanup temp file
        try:
            zip_path.unlink()
        except Exception:
            pass


@router.message(F.text)
async def handle_query(message: Message, rag: RAGChain):
    """Handle text messages as RAG queries."""
    _, chunk_count = rag.get_stats()

    if chunk_count == 0:
        await message.answer(
            "📭 У вас пока нет загруженных документов.\n\n"
            "Отправьте ZIP-архив с документами, чтобы я мог отвечать на вопросы!"
        )
        return

    thinking_msg = await message.answer("🤔 Ищу информацию в ваших документах...")

    try:
        answer, sources = rag.query(message.text)

        response = answer
        if sources:
            sources_text = ", ".join(sources)
            response += f"\n\n📄 Источники: {sources_text}"

        await thinking_msg.edit_text(response)

    except Exception as e:
        logger.error(f"Query failed: {e}")
        await thinking_msg.edit_text(
            "⚠️ Произошла ошибка при обработке запроса. Попробуйте ещё раз."
        )
