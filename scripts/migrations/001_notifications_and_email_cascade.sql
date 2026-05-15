-- Migration 001: Add notifications table, email cooldown column, and ON UPDATE CASCADE to user FKs
-- Run this script against an existing database to apply these changes.
-- New databases created with init_db.py will have these automatically.

-- ============================================================
-- 1. Add email_changed_at column to users
-- ============================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_changed_at TIMESTAMPTZ;

-- ============================================================
-- 2. Create notifications table
-- ============================================================
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_type') THEN
        CREATE TYPE notification_type AS ENUM ('friend_booking');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email VARCHAR NOT NULL,
    type notification_type NOT NULL,
    payload JSONB NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT notifications_user_email_fkey
        FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_notification_user_read ON notifications(user_email, is_read);
CREATE INDEX IF NOT EXISTS ix_notification_user_created ON notifications(user_email, created_at);

-- ============================================================
-- 3. Add ON UPDATE CASCADE to all FKs referencing users.email
-- ============================================================

-- sessions
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_user_email_fkey;
ALTER TABLE sessions ADD CONSTRAINT sessions_user_email_fkey
    FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE;

-- bookings
ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_user_email_fkey;
ALTER TABLE bookings ADD CONSTRAINT bookings_user_email_fkey
    FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE;

-- favorites
ALTER TABLE favorites DROP CONSTRAINT IF EXISTS favorites_user_email_fkey;
ALTER TABLE favorites ADD CONSTRAINT favorites_user_email_fkey
    FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE;

-- friendships (two FKs)
ALTER TABLE friendships DROP CONSTRAINT IF EXISTS friendships_correo_amigo_1_fkey;
ALTER TABLE friendships ADD CONSTRAINT friendships_correo_amigo_1_fkey
    FOREIGN KEY (correo_amigo_1) REFERENCES users(email) ON UPDATE CASCADE;

ALTER TABLE friendships DROP CONSTRAINT IF EXISTS friendships_correo_amigo_2_fkey;
ALTER TABLE friendships ADD CONSTRAINT friendships_correo_amigo_2_fkey
    FOREIGN KEY (correo_amigo_2) REFERENCES users(email) ON UPDATE CASCADE;

-- reports
ALTER TABLE reports DROP CONSTRAINT IF EXISTS reports_user_email_fkey;
ALTER TABLE reports ADD CONSTRAINT reports_user_email_fkey
    FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE;

-- schedules
ALTER TABLE schedules DROP CONSTRAINT IF EXISTS schedules_user_email_fkey;
ALTER TABLE schedules ADD CONSTRAINT schedules_user_email_fkey
    FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE;

-- analytics_events
ALTER TABLE analytics_events DROP CONSTRAINT IF EXISTS analytics_events_user_email_fkey;
ALTER TABLE analytics_events ADD CONSTRAINT analytics_events_user_email_fkey
    FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE;

-- chat_sessions
ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS chat_sessions_user_email_fkey;
ALTER TABLE chat_sessions ADD CONSTRAINT chat_sessions_user_email_fkey
    FOREIGN KEY (user_email) REFERENCES users(email) ON UPDATE CASCADE;
