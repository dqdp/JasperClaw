CREATE TABLE telegram_alert_deliveries (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT UNIQUE,
    status TEXT NOT NULL,
    matched_alerts INTEGER NOT NULL,
    attempt_count INTEGER NOT NULL,
    next_attempt_at TIMESTAMPTZ,
    locked_until TIMESTAMPTZ,
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (status IN ('pending', 'delivering', 'completed', 'failed')),
    CHECK (matched_alerts >= 0),
    CHECK (attempt_count >= 0)
);

CREATE INDEX idx_telegram_alert_deliveries_due
ON telegram_alert_deliveries (status, next_attempt_at, created_at);

CREATE INDEX idx_telegram_alert_deliveries_locked
ON telegram_alert_deliveries (status, locked_until);

CREATE TABLE telegram_alert_delivery_targets (
    delivery_id TEXT NOT NULL REFERENCES telegram_alert_deliveries(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    message_text TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL,
    last_error_code TEXT,
    last_error_message TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (delivery_id, chat_id),
    CHECK (status IN ('pending', 'sent', 'failed')),
    CHECK (attempt_count >= 0)
);

CREATE INDEX idx_telegram_alert_delivery_targets_status
ON telegram_alert_delivery_targets (status, delivery_id);
