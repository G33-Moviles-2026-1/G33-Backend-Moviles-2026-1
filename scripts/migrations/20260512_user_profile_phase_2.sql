BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM users
        WHERE username IS NULL OR username = ''
    ) THEN
        RAISE EXCEPTION 'Cannot enforce NOT NULL because some users still have empty usernames.';
    END IF;
END $$;

ALTER TABLE users
ALTER COLUMN username SET NOT NULL;

ALTER TABLE users
ALTER COLUMN status SET NOT NULL;

COMMIT;