BEGIN;

DO $$
BEGIN
    CREATE TYPE user_status AS ENUM (
        'incognito',
        'busy',
        'exercising',
        'free',
        'hanging_out',
        'at_home',
        'lunching'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS username VARCHAR(25);

ALTER TABLE users
ADD COLUMN IF NOT EXISTS status user_status;

ALTER TABLE users
ALTER COLUMN status SET DEFAULT 'incognito';

UPDATE users
SET status = 'incognito'
WHERE status IS NULL;

WITH prepared AS (
    SELECT
        email,
        CASE
            WHEN LENGTH(cleaned_username) >= 3 THEN LEFT(cleaned_username, 25)
            ELSE LEFT(cleaned_username || '000', 3)
        END AS base_username
    FROM (
        SELECT
            email,
            REGEXP_REPLACE(
                LOWER(SPLIT_PART(email, '@', 1)),
                '[^a-z0-9._-]',
                '-',
                'g'
            ) AS cleaned_username
        FROM users
        WHERE username IS NULL OR username = ''
    ) source
),
numbered AS (
    SELECT
        email,
        base_username,
        ROW_NUMBER() OVER (
            PARTITION BY base_username
            ORDER BY email
        ) AS rn
    FROM prepared
),
generated AS (
    SELECT
        email,
        CASE
            WHEN rn = 1 THEN base_username
            ELSE LEFT(base_username, 25 - LENGTH(rn::text)) || rn::text
        END AS generated_username
    FROM numbered
)
UPDATE users u
SET username = generated.generated_username
FROM generated
WHERE u.email = generated.email;

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_lower_unique
ON users (LOWER(username));

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_users_username_format'
    ) THEN
        ALTER TABLE users
        ADD CONSTRAINT ck_users_username_format
        CHECK (
            username IS NULL OR (
                username = LOWER(username)
                AND LENGTH(username) BETWEEN 3 AND 25
                AND username ~ '^[a-z0-9._-]+$'
            )
        );
    END IF;
END $$;

COMMIT;