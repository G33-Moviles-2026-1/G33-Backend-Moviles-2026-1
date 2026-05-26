-- Add friendship timestamps for analytics / Power BI.
-- created_at represents when the friendship row/request was created.
-- accepted_at represents when the relationship became an accepted friendship.
-- Existing accepted rows are backfilled with the current timestamp because
-- there is no historical acceptance timestamp available.

ALTER TABLE friendships
ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ;

UPDATE friendships
SET created_at = NOW()
WHERE created_at IS NULL;

ALTER TABLE friendships
ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE friendships
ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE friendships
ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ;

UPDATE friendships
SET accepted_at = NOW()
WHERE estado = 1
  AND accepted_at IS NULL;

CREATE INDEX IF NOT EXISTS ix_friendships_estado_accepted_at
ON friendships (estado, accepted_at);

CREATE INDEX IF NOT EXISTS ix_friendships_accepted_at
ON friendships (accepted_at);

CREATE INDEX IF NOT EXISTS ix_friendships_created_at
ON friendships (created_at);