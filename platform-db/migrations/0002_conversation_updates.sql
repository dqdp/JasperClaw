ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;

UPDATE conversations
SET updated_at = created_at
WHERE updated_at IS NULL;

ALTER TABLE conversations
ALTER COLUMN updated_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_conversations_profile_updated_at
ON conversations (public_profile, updated_at DESC, created_at DESC);
