# Technical Implementation Document: Personal Document RAG Bot System

## Document Info
| Field | Value |
|-------|-------|
| Version | 1.0 |
| Timeline | 5 days |
| Stack | Python 3.11, aiogram 3.x, LangChain, Qdrant, PostgreSQL, Railway |

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     MASTER BOT (main.py)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐    │
│  │  Handlers   │  │  Validator  │  │  Process Manager     │    │
│  │  /start     │  │  Bot Token  │  │  (in-memory dict)    │    │
│  │  /status    │  │  OpenAI Key │  │  spawn/restart/stop  │    │
│  │  /restart   │  │             │  │                      │    │
│  │  /delete    │  │             │  │                      │    │
│  └─────────────┘  └─────────────┘  └──────────────────────┘    │
│                           │                                     │
│                    ┌──────▼──────┐                              │
│                    │  PostgreSQL │                              │
│                    │  user_bots  │                              │
│                    └─────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
                              │
            subprocess.Popen (per user)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ PERSONAL BOT 1  │ │ PERSONAL BOT 2  │ │ PERSONAL BOT N  │
│ personal_bot.py │ │ personal_bot.py │ │ personal_bot.py │
│                 │ │                 │ │                 │
│ • ZIP handler   │ │ • ZIP handler   │ │ • ZIP handler   │
│ • Doc processor │ │ • Doc processor │ │ • Doc processor │
│ • RAG query     │ │ • RAG query     │ │ • RAG query     │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                   │
         └───────────────────┼───────────────────┘
                             ▼
                   ┌─────────────────┐
                   │     QDRANT      │
                   │  (Railway)      │
                   │  Collection per │
                   │  user           │
                   └─────────────────┘
```

---

## 2. Technology Decisions

### 2.1 Document Processing Stack

| Format | Loader | Package |
|--------|--------|---------|
| PDF | `PyPDFLoader` | `langchain-community` + `pypdf` |
| DOCX | `Docx2txtLoader` | `langchain-community` + `docx2txt` |
| TXT/MD | `TextLoader` | `langchain-community` |
| HTML | `UnstructuredHTMLLoader` | `langchain-community` + `unstructured` |
| PPTX | `UnstructuredPowerPointLoader` | `langchain-community` + `unstructured` |

**Rationale**: Lightweight, fast (~0.1s/page vs 3s/page with Docling), Railway-compatible without GPU/heavy RAM requirements.

### 2.2 Text Splitting Strategy

```python
from langchain.text_splitter import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ". ", " ", ""]
)
```

**Rationale**: Simple, works well for most document types. No need for semantic chunking in MVP.

### 2.3 Vector Store

- **Qdrant** via Railway template (managed)
- One collection per user: `user_{telegram_user_id}`
- Dense retrieval only (no hybrid/sparse for MVP)
- Embedding: `text-embedding-3-small` (1536 dimensions)

### 2.4 Process Management

**In-memory dictionary** tracking subprocess PIDs:

```python
# Global state in master bot
running_bots: dict[int, subprocess.Popen] = {}  # telegram_user_id -> process
```

**On master bot startup**: Query PostgreSQL for active bots, respawn all.

### 2.5 Encryption

**Fernet symmetric encryption** for OpenAI keys:

```python
from cryptography.fernet import Fernet

# ENCRYPTION_KEY from env (generate once: Fernet.generate_key())
fernet = Fernet(ENCRYPTION_KEY)
encrypted = fernet.encrypt(openai_key.encode())
decrypted = fernet.decrypt(encrypted).decode()
```

---

## 3. Database Schema

### 3.1 PostgreSQL Table

```sql
CREATE TABLE user_bots (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    bot_token TEXT NOT NULL,
    bot_username TEXT NOT NULL,
    openai_key_encrypted TEXT NOT NULL,
    qdrant_collection TEXT NOT NULL,
    status TEXT DEFAULT 'active',  -- active, stopped, error
    document_count INT DEFAULT 0,
    chunk_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_user_bots_status ON user_bots(status);
```

### 3.2 Database Operations

```python
# db.py - Simple async PostgreSQL wrapper
import asyncpg

class Database:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool = None
    
    async def connect(self):
        self.pool = await asyncpg.create_pool(self.dsn)
    
    async def create_user_bot(self, telegram_user_id: int, bot_token: str, 
                               bot_username: str, openai_key_encrypted: str) -> int:
        return await self.pool.fetchval("""
            INSERT INTO user_bots (telegram_user_id, bot_token, bot_username, 
                                   openai_key_encrypted, qdrant_collection)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """, telegram_user_id, bot_token, bot_username, openai_key_encrypted,
            f"user_{telegram_user_id}")
    
    async def get_user_bot(self, telegram_user_id: int) -> dict | None:
        return await self.pool.fetchrow(
            "SELECT * FROM user_bots WHERE telegram_user_id = $1", telegram_user_id)
    
    async def get_active_bots(self) -> list[dict]:
        return await self.pool.fetch("SELECT * FROM user_bots WHERE status = 'active'")
    
    async def update_status(self, telegram_user_id: int, status: str):
        await self.pool.execute(
            "UPDATE user_bots SET status = $1, updated_at = NOW() WHERE telegram_user_id = $2",
            status, telegram_user_id)
    
    async def update_counts(self, telegram_user_id: int, doc_count: int, chunk_count: int):
        await self.pool.execute("""
            UPDATE user_bots SET document_count = $1, chunk_count = $2, updated_at = NOW()
            WHERE telegram_user_id = $3
        """, doc_count, chunk_count, telegram_user_id)
    
    async def delete_user_bot(self, telegram_user_id: int):
        await self.pool.execute(
            "DELETE FROM user_bots WHERE telegram_user_id = $1", telegram_user_id)
```

---

## 4. Master Bot Implementation

### 4.1 Project Structure

```
rag-bot/
├── master_bot/
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── handlers.py          # Command handlers
│   ├── validators.py        # Token/key validation
│   ├── process_manager.py   # Subprocess management
│   └── states.py            # FSM states
├── personal_bot/
│   ├── __init__.py
│   ├── main.py              # Entry point (receives args)
│   ├── handlers.py          # ZIP + query handlers
│   ├── document_processor.py
│   └── rag_chain.py
├── shared/
│   ├── __init__.py
│   ├── db.py                # Database operations
│   ├── encryption.py        # Fernet wrapper
│   └── config.py            # Environment variables
├── requirements.txt
├── Procfile
└── railway.toml
```

### 4.2 FSM States

```python
# master_bot/states.py
from aiogram.fsm.state import State, StatesGroup

class BotSetup(StatesGroup):
    waiting_for_token = State()
    waiting_for_openai_key = State()
```

### 4.3 Validators

```python
# master_bot/validators.py
import aiohttp

async def validate_bot_token(token: str) -> tuple[bool, str | None]:
    """Validate bot token via getMe API call. Returns (is_valid, bot_username)."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                return True, data["result"]["username"]
            return False, None

async def validate_openai_key(key: str) -> bool:
    """Validate OpenAI key by making a test embedding call."""
    from openai import AsyncOpenAI
    try:
        client = AsyncOpenAI(api_key=key)
        await client.embeddings.create(
            model="text-embedding-3-small",
            input="test"
        )
        return True
    except Exception:
        return False
```

### 4.4 Process Manager

```python
# master_bot/process_manager.py
import subprocess
import sys
from pathlib import Path

running_bots: dict[int, subprocess.Popen] = {}

def spawn_personal_bot(telegram_user_id: int, bot_token: str, 
                       openai_key: str, qdrant_collection: str) -> bool:
    """Spawn a personal bot subprocess."""
    if telegram_user_id in running_bots:
        proc = running_bots[telegram_user_id]
        if proc.poll() is None:  # Still running
            return True
    
    personal_bot_path = Path(__file__).parent.parent / "personal_bot" / "main.py"
    
    proc = subprocess.Popen([
        sys.executable, str(personal_bot_path),
        "--user-id", str(telegram_user_id),
        "--bot-token", bot_token,
        "--openai-key", openai_key,
        "--collection", qdrant_collection
    ])
    
    running_bots[telegram_user_id] = proc
    return True

def stop_personal_bot(telegram_user_id: int) -> bool:
    """Stop a personal bot subprocess."""
    if telegram_user_id not in running_bots:
        return False
    
    proc = running_bots[telegram_user_id]
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    
    del running_bots[telegram_user_id]
    return True

def is_bot_running(telegram_user_id: int) -> bool:
    """Check if personal bot is running."""
    if telegram_user_id not in running_bots:
        return False
    return running_bots[telegram_user_id].poll() is None

def respawn_all_bots(active_bots: list[dict], decrypt_func):
    """Respawn all active bots on master startup."""
    for bot in active_bots:
        openai_key = decrypt_func(bot["openai_key_encrypted"])
        spawn_personal_bot(
            bot["telegram_user_id"],
            bot["bot_token"],
            openai_key,
            bot["qdrant_collection"]
        )
```

### 4.5 Master Bot Handlers

```python
# master_bot/handlers.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, db: Database):
    # Check if user already has a bot
    existing = await db.get_user_bot(message.from_user.id)
    if existing:
        await message.answer(
            f"✅ You already have a bot: @{existing['bot_username']}\n\n"
            "Commands:\n"
            "/status - Check bot status\n"
            "/restart - Restart your bot\n"
            "/delete - Delete your bot"
        )
        return
    
    await state.set_state(BotSetup.waiting_for_token)
    await message.answer(
        "👋 Welcome to the Personal RAG Bot Factory!\n\n"
        "I'll help you create your own private document chatbot.\n\n"
        "Send me your bot token from @BotFather.\n"
        "(Create one by messaging @BotFather and using /newbot)"
    )

@router.message(BotSetup.waiting_for_token)
async def process_token(message: Message, state: FSMContext):
    token = message.text.strip()
    
    is_valid, bot_username = await validate_bot_token(token)
    if not is_valid:
        await message.answer("❌ Invalid bot token. Please try again.")
        return
    
    await state.update_data(bot_token=token, bot_username=bot_username)
    await state.set_state(BotSetup.waiting_for_openai_key)
    await message.answer(
        f"✅ Bot token valid! Your bot: @{bot_username}\n\n"
        "Now send me your OpenAI API key.\n"
        "(Get one at platform.openai.com/api-keys)"
    )

@router.message(BotSetup.waiting_for_openai_key)
async def process_openai_key(message: Message, state: FSMContext, 
                              db: Database, fernet: Fernet):
    key = message.text.strip()
    
    # Delete message containing API key for security
    await message.delete()
    
    status_msg = await message.answer("🔄 Validating OpenAI key...")
    
    if not await validate_openai_key(key):
        await status_msg.edit_text("❌ Invalid OpenAI key. Please try again.")
        return
    
    data = await state.get_data()
    encrypted_key = fernet.encrypt(key.encode()).decode()
    
    # Save to database
    await db.create_user_bot(
        telegram_user_id=message.from_user.id,
        bot_token=data["bot_token"],
        bot_username=data["bot_username"],
        openai_key_encrypted=encrypted_key
    )
    
    # Spawn personal bot
    spawn_personal_bot(
        telegram_user_id=message.from_user.id,
        bot_token=data["bot_token"],
        openai_key=key,
        qdrant_collection=f"user_{message.from_user.id}"
    )
    
    await state.clear()
    await status_msg.edit_text(
        f"✅ Done! Your bot is ready: @{data['bot_username']}\n\n"
        "Go chat with your bot and upload a ZIP file with your documents!"
    )

@router.message(Command("status"))
async def cmd_status(message: Message, db: Database):
    bot_data = await db.get_user_bot(message.from_user.id)
    if not bot_data:
        await message.answer("❌ You don't have a bot. Use /start to create one.")
        return
    
    running = is_bot_running(message.from_user.id)
    status_emoji = "🟢" if running else "🔴"
    
    await message.answer(
        f"Bot: @{bot_data['bot_username']}\n"
        f"Status: {status_emoji} {'Running' if running else 'Stopped'}\n"
        f"Documents: {bot_data['document_count']}\n"
        f"Chunks: {bot_data['chunk_count']}"
    )

@router.message(Command("restart"))
async def cmd_restart(message: Message, db: Database, fernet: Fernet):
    bot_data = await db.get_user_bot(message.from_user.id)
    if not bot_data:
        await message.answer("❌ You don't have a bot. Use /start to create one.")
        return
    
    stop_personal_bot(message.from_user.id)
    
    openai_key = fernet.decrypt(bot_data["openai_key_encrypted"].encode()).decode()
    spawn_personal_bot(
        telegram_user_id=message.from_user.id,
        bot_token=bot_data["bot_token"],
        openai_key=openai_key,
        qdrant_collection=bot_data["qdrant_collection"]
    )
    
    await message.answer("✅ Bot restarted!")

@router.message(Command("delete"))
async def cmd_delete(message: Message, db: Database):
    bot_data = await db.get_user_bot(message.from_user.id)
    if not bot_data:
        await message.answer("❌ You don't have a bot.")
        return
    
    # Stop bot process
    stop_personal_bot(message.from_user.id)
    
    # Delete Qdrant collection
    from qdrant_client import QdrantClient
    qdrant = QdrantClient(url=QDRANT_URL)
    try:
        qdrant.delete_collection(bot_data["qdrant_collection"])
    except Exception:
        pass  # Collection might not exist
    
    # Delete from database
    await db.delete_user_bot(message.from_user.id)
    
    await message.answer("✅ Bot deleted. Use /start to create a new one.")
```

### 4.6 Master Bot Entry Point

```python
# master_bot/main.py
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from cryptography.fernet import Fernet

from shared.config import MASTER_BOT_TOKEN, DATABASE_URL, ENCRYPTION_KEY
from shared.db import Database
from master_bot.handlers import router
from master_bot.process_manager import respawn_all_bots

logging.basicConfig(level=logging.INFO)

async def main():
    # Initialize
    bot = Bot(token=MASTER_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    db = Database(DATABASE_URL)
    fernet = Fernet(ENCRYPTION_KEY)
    
    await db.connect()
    
    # Inject dependencies
    dp["db"] = db
    dp["fernet"] = fernet
    
    # Register handlers
    dp.include_router(router)
    
    # Respawn active bots on startup
    active_bots = await db.get_active_bots()
    respawn_all_bots(active_bots, lambda x: fernet.decrypt(x.encode()).decode())
    logging.info(f"Respawned {len(active_bots)} active bots")
    
    # Start polling
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. Personal Bot Implementation

### 5.1 Document Processor

```python
# personal_bot/document_processor.py
import zipfile
import tempfile
from pathlib import Path
from typing import Generator

from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
    UnstructuredHTMLLoader,
    UnstructuredPowerPointLoader
)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

SUPPORTED_EXTENSIONS = {
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".doc": Docx2txtLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
    ".html": UnstructuredHTMLLoader,
    ".htm": UnstructuredHTMLLoader,
    ".pptx": UnstructuredPowerPointLoader,
}

class DocumentProcessor:
    def __init__(self):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""]
        )
    
    def process_zip(self, zip_path: Path) -> Generator[tuple[str, list[Document]], None, None]:
        """
        Extract and process documents from ZIP.
        Yields (filename, chunks) for each processed document.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Extract ZIP
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(temp_path)
            
            # Process each file
            for file_path in temp_path.rglob("*"):
                if file_path.is_file() and not file_path.name.startswith("."):
                    ext = file_path.suffix.lower()
                    
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue
                    
                    try:
                        loader_class = SUPPORTED_EXTENSIONS[ext]
                        loader = loader_class(str(file_path))
                        docs = loader.load()
                        
                        # Add source metadata
                        for doc in docs:
                            doc.metadata["source"] = file_path.name
                        
                        # Split into chunks
                        chunks = self.splitter.split_documents(docs)
                        
                        yield file_path.name, chunks
                        
                    except Exception as e:
                        # Log error but continue processing other files
                        yield file_path.name, []  # Empty list signals failure
    
    def get_supported_formats(self) -> str:
        return ", ".join(ext.upper().replace(".", "") for ext in SUPPORTED_EXTENSIONS.keys())
```

### 5.2 RAG Chain

```python
# personal_bot/rag_chain.py
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_qdrant import QdrantVectorStore
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from qdrant_client import QdrantClient

class RAGChain:
    def __init__(self, openai_key: str, qdrant_url: str, collection_name: str):
        self.openai_key = openai_key
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        
        self.embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=openai_key
        )
        
        self.llm = ChatOpenAI(
            model="gpt-4o-mini",
            api_key=openai_key,
            temperature=0.3
        )
        
        self.qdrant_client = QdrantClient(url=qdrant_url)
        self.vectorstore = None
        self._ensure_collection()
    
    def _ensure_collection(self):
        """Create collection if it doesn't exist."""
        collections = [c.name for c in self.qdrant_client.get_collections().collections]
        
        if self.collection_name not in collections:
            from qdrant_client.models import Distance, VectorParams
            self.qdrant_client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
            )
        
        self.vectorstore = QdrantVectorStore(
            client=self.qdrant_client,
            collection_name=self.collection_name,
            embedding=self.embeddings
        )
    
    def add_documents(self, documents: list) -> int:
        """Add documents to vector store. Returns number of chunks added."""
        if not documents:
            return 0
        self.vectorstore.add_documents(documents)
        return len(documents)
    
    def get_stats(self) -> tuple[int, int]:
        """Get document and chunk counts."""
        try:
            info = self.qdrant_client.get_collection(self.collection_name)
            chunk_count = info.points_count
            
            # Estimate document count from unique sources
            # This is approximate - for exact count we'd need to query metadata
            return chunk_count // 10, chunk_count  # Rough estimate
        except Exception:
            return 0, 0
    
    def clear(self):
        """Delete all documents from collection."""
        self.qdrant_client.delete_collection(self.collection_name)
        self._ensure_collection()
    
    def query(self, question: str) -> tuple[str, list[str]]:
        """
        Query the RAG chain.
        Returns (answer, source_documents).
        """
        retriever = self.vectorstore.as_retriever(search_kwargs={"k": 5})
        
        prompt = ChatPromptTemplate.from_template("""
Answer the question based only on the following context. If you cannot answer 
the question based on the context, say "I couldn't find relevant information 
in your documents."

Context:
{context}

Question: {question}

Answer:""")
        
        def format_docs(docs):
            return "\n\n".join(doc.page_content for doc in docs)
        
        # Get relevant docs first for source tracking
        relevant_docs = retriever.invoke(question)
        sources = list(set(doc.metadata.get("source", "Unknown") for doc in relevant_docs))
        
        chain = (
            {"context": retriever | format_docs, "question": RunnablePassthrough()}
            | prompt
            | self.llm
            | StrOutputParser()
        )
        
        answer = chain.invoke(question)
        return answer, sources
```

### 5.3 Personal Bot Handlers

```python
# personal_bot/handlers.py
import tempfile
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message

from personal_bot.document_processor import DocumentProcessor
from personal_bot.rag_chain import RAGChain

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Hi! I'm your personal document assistant.\n\n"
        "Upload a ZIP file containing your documents "
        "(PDF, DOCX, TXT, MD, PPTX, HTML) and I'll help you "
        "search and chat about them.\n\n"
        "Just drag and drop a ZIP file to get started!"
    )

@router.message(Command("status"))
async def cmd_status(message: Message, rag: RAGChain):
    doc_count, chunk_count = rag.get_stats()
    await message.answer(
        f"📊 Status:\n"
        f"Documents indexed: ~{doc_count}\n"
        f"Total chunks: {chunk_count}"
    )

@router.message(Command("clear"))
async def cmd_clear(message: Message, rag: RAGChain):
    rag.clear()
    await message.answer("🗑️ All documents cleared. Upload a new ZIP to start fresh.")

@router.message(Command("help"))
async def cmd_help(message: Message, processor: DocumentProcessor):
    await message.answer(
        "📚 Commands:\n"
        "/start - Welcome message\n"
        "/status - Show document stats\n"
        "/clear - Delete all documents\n"
        "/help - This message\n\n"
        f"Supported formats: {processor.get_supported_formats()}\n\n"
        "Just send me a ZIP file to index, or ask questions about your documents!"
    )

@router.message(F.document)
async def handle_document(message: Message, bot: Bot, rag: RAGChain, 
                          processor: DocumentProcessor):
    doc = message.document
    
    # Validate file
    if not doc.file_name.lower().endswith(".zip"):
        await message.answer(
            "❌ Please send a ZIP file containing your documents."
        )
        return
    
    if doc.file_size > 50 * 1024 * 1024:  # 50MB limit
        await message.answer("❌ File too large. Maximum size is 50MB.")
        return
    
    status_msg = await message.answer(
        f"📦 Received: {doc.file_name} ({doc.file_size // 1024 / 1024:.1f} MB)\n\n"
        "Processing documents..."
    )
    
    # Download file
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        await bot.download(doc, destination=tmp.name)
        zip_path = Path(tmp.name)
    
    try:
        results = []
        total_chunks = 0
        
        for filename, chunks in processor.process_zip(zip_path):
            if chunks:
                added = rag.add_documents(chunks)
                total_chunks += added
                results.append(f"├── {filename} ✓ ({added} chunks)")
            else:
                results.append(f"├── {filename} ❌")
        
        if results:
            results[-1] = results[-1].replace("├──", "└──")  # Last item
        
        success_count = sum(1 for r in results if "✓" in r)
        
        await status_msg.edit_text(
            f"📦 {doc.file_name}\n\n"
            + "\n".join(results) + "\n\n"
            f"✅ Indexed {success_count} documents ({total_chunks} chunks).\n"
            "Ask me anything about your documents!"
        )
    
    except zipfile.BadZipFile:
        await status_msg.edit_text(
            "❌ Invalid ZIP file. Please ensure it's a valid archive."
        )
    
    finally:
        zip_path.unlink(missing_ok=True)

@router.message(F.text)
async def handle_query(message: Message, rag: RAGChain):
    _, chunk_count = rag.get_stats()
    
    if chunk_count == 0:
        await message.answer(
            "📭 No documents indexed yet. Send me a ZIP file first!"
        )
        return
    
    thinking_msg = await message.answer("🤔 Searching your documents...")
    
    try:
        answer, sources = rag.query(message.text)
        
        response = answer
        if sources:
            response += f"\n\n📄 Sources: {', '.join(sources)}"
        
        await thinking_msg.edit_text(response)
    
    except Exception as e:
        await thinking_msg.edit_text(
            "⚠️ Error processing your question. Please try again."
        )
```

### 5.4 Personal Bot Entry Point

```python
# personal_bot/main.py
import argparse
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from shared.config import QDRANT_URL
from personal_bot.handlers import router
from personal_bot.document_processor import DocumentProcessor
from personal_bot.rag_chain import RAGChain

logging.basicConfig(level=logging.INFO)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--bot-token", required=True)
    parser.add_argument("--openai-key", required=True)
    parser.add_argument("--collection", required=True)
    return parser.parse_args()

async def main():
    args = parse_args()
    
    bot = Bot(token=args.bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    
    # Initialize components
    processor = DocumentProcessor()
    rag = RAGChain(
        openai_key=args.openai_key,
        qdrant_url=QDRANT_URL,
        collection_name=args.collection
    )
    
    # Inject dependencies
    dp["processor"] = processor
    dp["rag"] = rag
    
    # Register handlers
    dp.include_router(router)
    
    logging.info(f"Starting personal bot for user {args.user_id}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Configuration & Deployment

### 6.1 Environment Variables

```bash
# Master bot
MASTER_BOT_TOKEN=your_master_bot_token
DATABASE_URL=postgresql://user:pass@host:5432/dbname
QDRANT_URL=http://qdrant-service:6333
ENCRYPTION_KEY=your_fernet_key  # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 6.2 Requirements

```txt
# requirements.txt
aiogram>=3.4.0
asyncpg>=0.29.0
cryptography>=42.0.0
aiohttp>=3.9.0

# LangChain
langchain>=0.2.0
langchain-community>=0.2.0
langchain-openai>=0.1.0
langchain-qdrant>=0.1.0

# Document loaders
pypdf>=4.0.0
docx2txt>=0.8
unstructured>=0.12.0

# Vector store
qdrant-client>=1.8.0

# OpenAI
openai>=1.12.0

python-dotenv>=1.0.0
```

### 6.3 Railway Configuration

```toml
# railway.toml
[build]
builder = "nixpacks"

[deploy]
startCommand = "python -m master_bot.main"
restartPolicyType = "always"
```

```
# Procfile (alternative)
web: python -m master_bot.main
```

### 6.4 Railway Services Setup

1. **PostgreSQL**: Use Railway's PostgreSQL template
2. **Qdrant**: Use Railway's Qdrant template
3. **Master Bot**: Deploy from GitHub repo

---

## 7. Implementation Phases

### Phase 1: Infrastructure (Day 1)
| Task | Description | Acceptance |
|------|-------------|------------|
| PostgreSQL setup | Railway template + schema | Can connect and create tables |
| Qdrant setup | Railway template | Can create/delete collections |
| Project structure | Create folder structure | All files in place |
| Config module | Environment variables | Config loads correctly |

### Phase 2: Master Bot Core (Day 2)
| Task | Description | Acceptance |
|------|-------------|------------|
| Bot token validation | Async getMe call | Valid/invalid tokens detected |
| OpenAI key validation | Test embedding call | Valid/invalid keys detected |
| Database operations | CRUD for user_bots | All operations work |
| FSM flow | Token → Key → Complete | Full flow works |
| Encryption | Fernet encrypt/decrypt | Keys encrypted in DB |

### Phase 3: Personal Bot Core (Day 3)
| Task | Description | Acceptance |
|------|-------------|------------|
| Document processor | ZIP extraction + parsing | All formats processed |
| Text splitting | RecursiveCharacterTextSplitter | Chunks created correctly |
| Qdrant integration | Add documents | Documents stored |
| ZIP handler | Download + process | End-to-end ZIP processing |

### Phase 4: RAG Pipeline (Day 4)
| Task | Description | Acceptance |
|------|-------------|------------|
| RAG chain | Retriever + LLM | Queries return answers |
| Source tracking | Include doc names | Sources in response |
| Query handler | Full query flow | Questions answered |
| Stats/clear commands | Collection management | Commands work |

### Phase 5: Integration & Polish (Day 5)
| Task | Description | Acceptance |
|------|-------------|------------|
| Process manager | Spawn/stop/restart | All operations work |
| Auto-respawn | On master startup | Bots restart after deploy |
| Error handling | Graceful failures | No crashes on bad input |
| Master bot commands | /status, /restart, /delete | All commands work |
| End-to-end testing | Full flow | Complete workflow succeeds |

---

## 8. Error Handling Strategy

### 8.1 Master Bot Errors

| Error | Response |
|-------|----------|
| Invalid bot token | "❌ Invalid bot token. Please check and try again." |
| Invalid OpenAI key | "❌ Invalid OpenAI key. Please check and try again." |
| Bot already exists | Show existing bot info + commands |
| Database error | Log error, return generic message |

### 8.2 Personal Bot Errors

| Error | Response |
|-------|----------|
| Invalid ZIP | "❌ Invalid ZIP file. Please ensure it's a valid archive." |
| File too large | "❌ File too large. Maximum size is 50MB." |
| Unsupported format | Skip file, continue processing |
| OpenAI rate limit | "⚠️ Rate limited. Please wait a moment." |
| Empty collection | "📭 No documents indexed yet. Send me a ZIP file first!" |

### 8.3 Retry Logic

```python
# Simple retry decorator for OpenAI calls
import asyncio
from functools import wraps

def retry(max_attempts=3, delay=1):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    await asyncio.sleep(delay * (attempt + 1))
        return wrapper
    return decorator
```

---

## 9. Testing Checklist

### Manual Testing Flow

```
□ Master Bot
  □ /start → Prompts for token
  □ Invalid token → Error message
  □ Valid token → Prompts for OpenAI key
  □ Invalid key → Error message  
  □ Valid key → Bot created, personal bot spawns
  □ /status → Shows bot info
  □ /restart → Bot restarts
  □ /delete → Bot removed

□ Personal Bot
  □ /start → Welcome message
  □ /help → Shows commands
  □ Non-ZIP file → Error message
  □ ZIP upload → Documents processed, progress shown
  □ Text query (no docs) → "No documents" message
  □ Text query (with docs) → Answer with sources
  □ /status → Shows counts
  □ /clear → Documents deleted

□ Integration
  □ Master restart → Personal bots respawn
  □ Multiple users → Each gets own bot
  □ Qdrant isolation → Users can't see each other's docs
```

---

## 10. Future Enhancements (Post-MVP)

1. **Incremental uploads** - Add documents without clearing
2. **Document listing** - `/docs` command to list indexed files
3. **Conversation memory** - Track last 5 exchanges
4. **Docling integration** - Better PDF parsing (requires more resources)
5. **Webhook mode** - More efficient than polling at scale
6. **Railway service API** - Dynamic service spawning instead of subprocesses