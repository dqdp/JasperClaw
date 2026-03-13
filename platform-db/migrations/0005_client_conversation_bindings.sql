CREATE TABLE client_conversation_bindings (
    client_source TEXT NOT NULL,
    client_conversation_id TEXT NOT NULL,
    public_profile TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (client_source, client_conversation_id, public_profile)
);

CREATE INDEX idx_client_conversation_bindings_conversation_id
ON client_conversation_bindings (conversation_id);
