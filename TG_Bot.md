# PRD: Personal Document RAG Bot System

## Executive Summary

A master-slave Telegram bot architecture where users create their own personal document chatbot instances. Users provide a BotFather token and OpenAI API key to the master bot, which spawns a dedicated bot process for them. Each personal bot accepts ZIP uploads, builds a RAG pipeline using LangChain + Docling + Qdrant, and enables natural language conversations about the user's documents.

**Core Value**: Zero-setup personal AI document assistant — each user gets their own bot they fully control.

---

## Problem Statement

Users want to chat with their document collections but face barriers: shared infrastructure raises privacy concerns, existing RAG tools require technical setup, and generic bots don't provide ownership or customization.

**User Pain Points**:
- Privacy concerns with uploading documents to shared bots
- No sense of ownership over the AI assistant
- Complex RAG setup for non-technical users
- Desire for dedicated, always-available document assistant

---

## Goals & Success Metrics

| Goal | Metric | Target |
|------|--------|--------|
| Bot creation success | Token validation → running bot | >95% |
| Document processing | ZIP → queryable index | >90% success rate |
| User engagement | Queries after setup | >5 queries per user |
| System reliability | Bot uptime per instance | >99% |

---

## Target Users

Professionals and researchers who:
- Have document collections they reference frequently
- Value privacy and data ownership
- Use Telegram as primary messaging platform
- Are comfortable creating a BotFather token (simple process)
- Have or can obtain an OpenAI API key

---

## Product Overview

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        MASTER BOT                                │
│  - Receives bot token + OpenAI key from user                    │
│  - Validates credentials                                         │
│  - Stores in PostgreSQL                                          │
│  - Spawns personal bot process on Railway                        │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  PERSONAL BOT 1 │ │  PERSONAL BOT 2 │ │  PERSONAL BOT N │
│  (User's token) │ │  (User's token) │ │  (User's token) │
│                 │ │                 │ │                 │
│  - ZIP upload   │ │  - ZIP upload   │ │  - ZIP upload   │
│  - Docling parse│ │  - Docling parse│ │  - Docling parse│
│  - Qdrant store │ │  - Qdrant store │ │  - Qdrant store │
│  - RAG queries  │ │  - RAG queries  │ │  - RAG queries  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              ▼
                    ┌─────────────────┐
                    │     QDRANT      │
                    │  (Shared, but   │
                    │  isolated       │
                    │  collections)   │
                    └─────────────────┘
```

### Tech Stack

| Component | Technology |
|-----------|------------|
| Master Bot | aiogram 3.x |
| Personal Bots | aiogram 3.x (separate processes) |
| RAG Pipeline | LangChain |
| Document Parsing | Docling + langchain-docling |
| Embeddings | OpenAI text-embedding-3-small |
| Vector Store | Qdrant (Railway template) |
| LLM | GPT-4o-mini |
| Database | PostgreSQL (Railway) |
| Deployment | Railway |

---

## Functional Requirements

### P0 - Must Have (MVP)

#### Master Bot

**FR-1: Bot Token Registration**
- User sends `/start` → bot explains the setup process
- User sends BotFather token → master bot validates via `getMe` API call
- If valid, store token and prompt for OpenAI key
- If invalid, return clear error message

**FR-2: OpenAI Key Registration**
- User sends OpenAI API key
- Master bot validates by making test embedding call
- If valid, store key (encrypted) in PostgreSQL
- If invalid, return clear error message

**FR-3: Personal Bot Spawning**
- After both credentials validated:
  - Create record in PostgreSQL: `user_id`, `bot_token`, `openai_key`, `status`, `created_at`
  - Create Qdrant collection named `user_{telegram_user_id}`
  - Spawn personal bot process
  - Confirm to user their bot is ready with link to chat

**FR-4: Bot Management**
- `/status` - Check if personal bot is running
- `/restart` - Restart personal bot process
- `/delete` - Stop bot, delete Qdrant collection, remove from database

#### Personal Bot

**FR-5: ZIP Upload & Processing**
- Accept ZIP files up to 50MB
- Extract to temporary directory
- Parse documents using `DoclingLoader` with `ExportType.DOC_CHUNKS`
- Supported formats: PDF, DOCX, PPTX, TXT, MD, HTML
- Generate embeddings using user's OpenAI key
- Store in user's Qdrant collection
- Send progress updates during processing
- Clean up temp files after indexing

**FR-6: RAG Query Handling**
- User sends text message → treat as query
- Retrieve top-5 relevant chunks from Qdrant
- Build prompt with context + query
- Generate response via GPT-4o-mini
- Include source document names in response

**FR-7: Personal Bot Commands**
- `/start` - Show welcome and instructions
- `/status` - Show document count, chunk count
- `/clear` - Delete all documents from index
- `/help` - List available commands

### P1 - Should Have (Post-MVP)

**FR-8: Incremental Document Addition**
- Upload additional ZIPs without clearing existing index

**FR-9: Document Listing**
- `/docs` - List all indexed documents with metadata

**FR-10: Conversation Memory**
- Maintain last 5 exchanges for follow-up questions

---

## Non-Functional Requirements

**NFR-1: Performance**
- Query response: <15 seconds (including LLM)
- ZIP processing: <3 minutes for 20 documents

**NFR-2: Scalability**
- Support up to 100 concurrent personal bot instances
- Qdrant handles collection isolation

**NFR-3: Security**
- OpenAI keys encrypted at rest in PostgreSQL
- Bot tokens stored securely
- User data isolated in separate Qdrant collections

**NFR-4: Reliability**
- Personal bots auto-restart on crash
- Graceful handling of malformed ZIPs
- Retry logic for OpenAI API calls (3 attempts)

---

## User Experience

### Master Bot Flow

```
User: /start

Bot: 👋 Welcome to the Personal RAG Bot Factory!

I'll help you create your own private document chatbot.

Here's what you need:
1. A Telegram bot token from @BotFather
2. An OpenAI API key

Ready? Send me your bot token first.
(Create one by messaging @BotFather and using /newbot)
```

```
User: 7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw

Bot: ✅ Bot token valid! Your bot: @YourDocBotName

Now send me your OpenAI API key.
(Get one at platform.openai.com/api-keys)
```

```
User: sk-proj-xxxxx

Bot: ✅ OpenAI key valid!

🚀 Creating your personal document bot...

✅ Done! Your bot is ready: @YourDocBotName

Go chat with your bot and upload a ZIP file with your documents!
```

### Personal Bot Flow

```
User: /start

Bot: 👋 Hi! I'm your personal document assistant.

Upload a ZIP file containing your documents (PDF, DOCX, TXT, MD, PPTX, HTML) and I'll help you search and chat about them.

Just drag and drop a ZIP file to get started!
```

```
User: [uploads research_papers.zip]

Bot: 📦 Received: research_papers.zip (4.2 MB)

Processing documents...
├── paper1.pdf ✓
├── paper2.pdf ✓
├── notes.docx ✓
└── summary.md ✓

✅ Ready! Indexed 4 documents (312 chunks).
Ask me anything about your documents!
```

```
User: What are the main findings about neural networks?

Bot: Based on your documents, the main findings about neural networks include:

[Generated answer based on retrieved context]

📄 Sources: paper1.pdf, paper2.pdf
```

### Error States

```
# Invalid ZIP
Bot: ❌ I couldn't process that file. Please ensure it's a valid ZIP archive with supported documents (PDF, DOCX, TXT, MD, PPTX, HTML).

# OpenAI API error
Bot: ⚠️ There was an issue with the OpenAI API. Please check your API key has sufficient credits. Use /status in the master bot to update your key.

# No documents indexed
Bot: 📭 You haven't uploaded any documents yet. Send me a ZIP file to get started!
```

---

## Technical Considerations

### Database Schema (PostgreSQL)

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
```

### Process Management

Each personal bot runs as a separate Railway service or subprocess:

```python
# Option A: Subprocess per bot (simpler, MVP)
import subprocess
subprocess.Popen(["python", "personal_bot.py", "--user-id", str(user_id)])

# Option B: Railway service per bot (scalable, post-MVP)
# Use Railway API to spawn new services dynamically
```

For MVP, use subprocess approach with a process manager that:
- Tracks running bot processes
- Restarts crashed processes
- Provides status to master bot

### Qdrant Collection Strategy

- One shared Qdrant instance on Railway
- Each user gets isolated collection: `user_{telegram_user_id}`
- Collection auto-created when personal bot starts
- Collection deleted when user runs `/delete` on master bot

### LangChain RAG Pipeline

```python
from langchain_docling import DoclingLoader, ExportType
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_qdrant import QdrantVectorStore
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain

# Document loading
loader = DoclingLoader(
    file_path=document_paths,
    export_type=ExportType.DOC_CHUNKS
)
docs = loader.load()

# Vector store
embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=user_openai_key
)
vectorstore = QdrantVectorStore.from_documents(
    docs,
    embeddings,
    url=QDRANT_URL,
    collection_name=f"user_{user_id}"
)

# RAG chain
llm = ChatOpenAI(model="gpt-4o-mini", api_key=user_openai_key)
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
# ... create chain
```

### Dependencies

```
aiogram>=3.0
langchain>=0.2
langchain-openai
langchain-qdrant
qdrant-client
docling
langchain-docling
psycopg2-binary
python-dotenv
cryptography  # for key encryption
```

### Environment Variables

```
# Master bot
MASTER_BOT_TOKEN=
DATABASE_URL=
QDRANT_URL=
ENCRYPTION_KEY=

# Personal bot (passed as args or env)
USER_BOT_TOKEN=
USER_OPENAI_KEY=
USER_QDRANT_COLLECTION=
```

---

## Timeline & Milestones

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| **M1: Infrastructure** | Day 1 | PostgreSQL + Qdrant on Railway, project structure |
| **M2: Master Bot** | Day 2 | Token/key validation, database storage, bot spawning |
| **M3: Personal Bot Core** | Day 3 | ZIP handling, Docling parsing, Qdrant indexing |
| **M4: RAG Pipeline** | Day 4 | Query handling, LangChain chain, response generation |
| **M5: Polish & Deploy** | Day 5 | Error handling, status commands, process management |

**Total MVP Timeline**: 5 days

---

## Risks & Assumptions

### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Docling fails on complex PDFs | Medium | Log failures, notify user, skip problematic files |
| User's OpenAI key runs out of credits | High | Clear error message, direct to master bot to update |
| Process crashes | Medium | Auto-restart logic, status monitoring |
| Railway resource limits | Medium | Monitor usage, implement user limits if needed |

### Assumptions

- Users can create BotFather tokens (simple, documented process)
- Users have or can obtain OpenAI API keys
- Qdrant Railway template provides sufficient performance
- Single Railway project can manage multiple bot processes
- Documents are primarily text-based (not scanned images)

---

## Out of Scope (Explicitly Excluded)

- Image OCR within documents
- Multi-language support (English only for MVP)
- Web interface for management
- Sharing documents between users
- Payment system / usage billing
- Document editing capabilities
- Webhook mode (polling only for simplicity)

