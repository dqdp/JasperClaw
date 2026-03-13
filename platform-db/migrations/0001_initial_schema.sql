CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    public_profile TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE model_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    assistant_message_id TEXT NULL REFERENCES messages(id),
    request_id TEXT NOT NULL,
    public_profile TEXT NOT NULL,
    runtime_model TEXT NOT NULL,
    status TEXT NOT NULL,
    error_type TEXT NULL,
    error_code TEXT NULL,
    error_message TEXT NULL,
    prompt_tokens INTEGER NULL,
    completion_tokens INTEGER NULL,
    total_tokens INTEGER NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_messages_conversation_id
ON messages (conversation_id, message_index);

CREATE INDEX idx_model_runs_request_id
ON model_runs (request_id);
