-- Migration: create block_assignments and drop blocks.table_id (SQLite)
PRAGMA foreign_keys=OFF;

-- 1) Ensure block_assignments exists
CREATE TABLE IF NOT EXISTS block_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id INTEGER NOT NULL,
    table_id INTEGER NOT NULL,
    created_at_utc DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(block_id, table_id),
    FOREIGN KEY(block_id) REFERENCES blocks(id) ON DELETE CASCADE,
    FOREIGN KEY(table_id) REFERENCES tables(id) ON DELETE CASCADE
);

-- 2) Recreate blocks without table_id
ALTER TABLE blocks RENAME TO blocks_old;

CREATE TABLE blocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    restaurant_id INTEGER NOT NULL,
    start_at DATETIME NOT NULL,
    end_at DATETIME NOT NULL,
    reason TEXT,
    created_by_user_id INTEGER,
    FOREIGN KEY(restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

INSERT INTO blocks (id, restaurant_id, start_at, end_at, reason, created_by_user_id)
SELECT id, restaurant_id, start_at, end_at, reason, created_by_user_id
FROM blocks_old;

DROP TABLE blocks_old;

-- 4) Index entspricht SQLAlchemy index=True auf restaurant_id
CREATE INDEX IF NOT EXISTS ix_blocks_restaurant_id ON blocks (restaurant_id);

PRAGMA foreign_keys=ON;
