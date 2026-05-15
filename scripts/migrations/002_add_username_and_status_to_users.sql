-- Migration 002: Add username and status columns to users table
-- Run this script against an existing database to apply these changes.
-- New databases created with init_db.py will have these automatically.

-- ============================================================
-- 1. Create user_status enum if it doesn't exist
-- ============================================================
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_status') THEN
        CREATE TYPE user_status AS ENUM (
            'incognito',
            'busy',
            'exercising',
            'free',
            'hanging_out',
            'at_home',
            'lunching'
        );
    END IF;
END $$;

-- ============================================================
-- 2. Add username column (temporarily nullable to backfill)
-- ============================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(25);

-- Backfill existing rows using the local part of their email
UPDATE users SET username = LOWER(REGEXP_REPLACE(SPLIT_PART(email, '@', 1), '[^a-z0-9._-]', '-', 'g'))
WHERE username IS NULL;

-- Make it NOT NULL now that all rows have a value
ALTER TABLE users ALTER COLUMN username SET NOT NULL;

-- ============================================================
-- 3. Add status column
-- ============================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS status user_status NOT NULL DEFAULT 'incognito';

-- ============================================================
-- 4. Create unique index on lower(username)
-- ============================================================
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_lower_unique
    ON users (LOWER(username));
