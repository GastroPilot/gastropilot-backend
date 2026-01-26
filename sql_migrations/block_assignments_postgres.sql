-- Migration: create block_assignments and drop blocks.table_id (PostgreSQL/Neon)
BEGIN;

-- 1) Ensure block_assignments exists
CREATE TABLE IF NOT EXISTS block_assignments (
    id SERIAL PRIMARY KEY,
    block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
    table_id INTEGER NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
    created_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_block_assignment_table UNIQUE (block_id, table_id)
);

-- 2) Drop the old column
ALTER TABLE blocks DROP COLUMN IF EXISTS table_id;

COMMIT;
