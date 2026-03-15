CREATE TABLE ingress_completion_cache (
    idempotency_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    public_model TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    response_content TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (source IN ('telegram', 'telegram_command'))
);

CREATE TABLE telegram_ingress_updates (
    update_key TEXT PRIMARY KEY,
    update_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    status TEXT NOT NULL,
    response_text TEXT,
    conversation_id TEXT,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CHECK (status IN ('processing', 'pending_send', 'completed'))
);

CREATE INDEX idx_telegram_ingress_updates_status_locked
ON telegram_ingress_updates (status, locked_until, updated_at);
