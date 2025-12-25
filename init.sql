-- Database schema for RAG Bot System

CREATE TABLE IF NOT EXISTS user_bots (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT UNIQUE NOT NULL,
    bot_token TEXT NOT NULL,
    bot_username TEXT NOT NULL,
    openai_key TEXT NOT NULL,
    qdrant_collection TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    document_count INT DEFAULT 0,
    chunk_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_bots_status ON user_bots(status);
CREATE INDEX IF NOT EXISTS idx_user_bots_telegram_user_id ON user_bots(telegram_user_id);
