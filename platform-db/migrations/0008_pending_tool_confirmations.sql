CREATE TABLE IF NOT EXISTS pending_tool_confirmations (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    source_class TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    clarification_count INTEGER NOT NULL DEFAULT 0,
    request_payload_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_pending_tool_confirmations_conversation_created_at
ON pending_tool_confirmations (conversation_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_tool_confirmations_one_pending_per_conversation
ON pending_tool_confirmations (conversation_id)
WHERE status = 'pending';
