-- Migration: Extend current term and availability rules to end of 2026
-- Run this script against an existing database to apply these changes.
-- New databases created with init_db.py will have these automatically.

-- ============================================================
-- 1. Extend current term end date
-- ============================================================
UPDATE terms
SET end_date = '2026-12-31'
WHERE is_current = TRUE
  AND (end_date IS NULL OR end_date < '2026-12-31');

-- ============================================================
-- 2. Extend room availability rules valid_to
-- ============================================================
UPDATE room_availability_rules
SET valid_to = '2026-12-31'
WHERE valid_to < '2026-12-31';
