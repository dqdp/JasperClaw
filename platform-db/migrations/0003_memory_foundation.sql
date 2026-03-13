CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS principals (
    id TEXT PRIMARY KEY,
    principal_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

INSERT INTO principals (id, principal_key, created_at, updated_at)
VALUES ('prn_local_assistant', 'local-assistant', NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS memory_items (
    id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL REFERENCES principals(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    source_message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id TEXT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    confidence DOUBLE PRECISION NULL,
    embedding vector NULL,
    embedding_model TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_principal_kind_status
ON memory_items (principal_id, kind, status);

CREATE INDEX IF NOT EXISTS idx_memory_items_source_message_id
ON memory_items (source_message_id);

CREATE TABLE IF NOT EXISTS retrieval_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    profile_id TEXT NULL,
    strategy TEXT NULL,
    top_k INTEGER NULL,
    status TEXT NULL,
    latency_ms DOUBLE PRECISION NULL,
    error_type TEXT NULL,
    error_code TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_runs_request_id
ON retrieval_runs (request_id);

CREATE TABLE IF NOT EXISTS retrieval_hits (
    id TEXT PRIMARY KEY,
    retrieval_run_id TEXT NOT NULL REFERENCES retrieval_runs(id) ON DELETE CASCADE,
    memory_item_id TEXT NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    included_in_prompt BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_retrieval_hits_run_rank UNIQUE (retrieval_run_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_retrieval_hits_run_rank
ON retrieval_hits (retrieval_run_id, rank);
