ALTER TABLE telegram_alert_deliveries
ADD COLUMN escalated_at TIMESTAMPTZ,
ADD COLUMN escalation_reason TEXT;

CREATE INDEX idx_telegram_alert_deliveries_escalated
ON telegram_alert_deliveries (escalated_at)
WHERE escalated_at IS NOT NULL;
