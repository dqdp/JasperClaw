CREATE TABLE IF NOT EXISTS tool_executions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    model_run_id TEXT NULL REFERENCES model_runs(id) ON DELETE SET NULL,
    request_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    latency_ms DOUBLE PRECISION NULL,
    error_type TEXT NULL,
    error_code TEXT NULL,
    request_payload_json JSONB NULL,
    response_payload_json JSONB NULL,
    policy_decision TEXT NULL,
    adapter_name TEXT NULL,
    provider TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_executions_request_id
ON tool_executions (request_id);

CREATE INDEX IF NOT EXISTS idx_tool_executions_conversation_started_at
ON tool_executions (conversation_id, started_at DESC);
