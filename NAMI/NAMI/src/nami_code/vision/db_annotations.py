import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS annotations (
    reel_pk    TEXT NOT NULL,
    dimension  TEXT NOT NULL,
    category   TEXT NOT NULL,
    source     TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    model      TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (reel_pk, dimension, category, source)
);
CREATE INDEX IF NOT EXISTS idx_ann_reel   ON annotations(reel_pk);
CREATE INDEX IF NOT EXISTS idx_ann_source ON annotations(source);
CREATE INDEX IF NOT EXISTS idx_ann_dim    ON annotations(dimension, category);

CREATE TABLE IF NOT EXISTS vision_state (
    reel_pk     TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'pending',
    media_path  TEXT,
    updated_at  TEXT
);
-- media_state lives in the core schema (nami_code.db) because crawldetails
-- writes it during a normal crawl; it is created there by get_conn().
"""

def upgrade(db_path):
    """
    Create the tagging-related tables if they are missing and print what the database now holds.

    Applies the core schema first (which owns media_state), then the
    vision-only tables, so the command is self-sufficient on a fresh DB.
    """
    from nami_code import db as core_db

    conn = sqlite3.connect(db_path)
    conn.executescript(core_db.DDL)
    conn.executescript(DDL)
    conn.commit()
    tabs = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print("Tables now:", tabs)
    print("'annotations' rows:", [r[1] for r in conn.execute("PRAGMA table_info(annotations)")])
    conn.close()

if __name__ == "__main__":
    DB_PATH = "data/corpus.db"

    upgrade(DB_PATH)
