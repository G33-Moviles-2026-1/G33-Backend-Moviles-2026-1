-- Migration: Add share_schedule column to users table
-- Run this script against an existing database to apply these changes.
-- New databases created with init_db.py will have these automatically.

-- ============================================================
-- 1. Add share_schedule column
-- ============================================================
ALTER TABLE users 
ADD COLUMN IF NOT EXISTS share_schedule BOOLEAN NOT NULL DEFAULT TRUE;