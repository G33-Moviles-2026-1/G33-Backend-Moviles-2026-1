-- Migration: Add friend_request_received and friend_request_accepted to notificationtype enum
-- Run this script against an existing database to apply these changes.
-- New databases created with init_db.py will have these automatically.

ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'friend_request_received';
ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'friend_request_accepted';
