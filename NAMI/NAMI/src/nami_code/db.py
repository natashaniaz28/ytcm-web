import sqlite3

DB_PATH = "data/corpus.db"

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS songs (
    song_id      TEXT PRIMARY KEY,
    title        TEXT,
    artist       TEXT,
    release_year INTEGER
);

CREATE TABLE IF NOT EXISTS track_variants (
    asset_id      TEXT PRIMARY KEY,
    song_id       TEXT NOT NULL REFERENCES songs(song_id),
    variant_label TEXT
);

CREATE TABLE IF NOT EXISTS reel_index (
    reel_pk      TEXT NOT NULL,
    asset_id     TEXT NOT NULL REFERENCES track_variants(asset_id),
    play_count   INTEGER,
    details_done INTEGER DEFAULT 0,
    seen_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (reel_pk, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_idx_todo ON reel_index(details_done);

CREATE TABLE IF NOT EXISTS reels (
    reel_pk        TEXT PRIMARY KEY,
    song_id        TEXT NOT NULL REFERENCES songs(song_id),
    asset_id       TEXT,
    variant_label  TEXT,
    code           TEXT,
    creator_pseudo TEXT,
    taken_at       TEXT,
    caption_text   TEXT,
    like_count     INTEGER,
    play_count     INTEGER,
    view_count     INTEGER,
    comment_count  INTEGER,
    video_duration REAL,
    thumbnail_url  TEXT,
    video_url      TEXT,
    media_path     TEXT,
    ingested_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reels_song  ON reels(song_id, taken_at);
CREATE INDEX IF NOT EXISTS idx_reels_taken ON reels(taken_at);

CREATE TABLE IF NOT EXISTS reel_hashtags (
    reel_pk TEXT, hashtag TEXT,
    PRIMARY KEY (reel_pk, hashtag)
);
CREATE INDEX IF NOT EXISTS idx_rh_tag ON reel_hashtags(hashtag);

CREATE TABLE IF NOT EXISTS index_state (
    asset_id     TEXT PRIMARY KEY,
    next_page_id TEXT,
    pages_done   INTEGER DEFAULT 0,
    ids_seen     INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'pending',
    updated_at   TEXT
);

-- media_state tracks the inline MP4 download during crawldetails, so it is part
-- of the core schema (the vision tables in db_annotations.py mirror it for the
-- standalone `annotations` setup command).
CREATE TABLE IF NOT EXISTS media_state (
    reel_pk     TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'pending',
    media_path  TEXT,
    updated_at  TEXT
);
"""

def get_conn():
    """
    Open the project database, creating any tables that are missing first.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(DDL)
    conn.commit()
    return conn

def sync_songs_from_yaml(conn, cfg):
    """
    Copy the songs and their audio variants from the config file into the database.
    """
    for song_id, s in cfg["songs"].items():
        conn.execute("INSERT OR REPLACE INTO songs VALUES (?,?,?,?)",
                     (song_id, s["title"], s["artist"], s.get("release_year")))
        for v in s["variants"]:
            conn.execute("INSERT OR REPLACE INTO track_variants VALUES (?,?,?)",
                         (v["asset_id"], song_id, v["label"]))
    conn.commit()

def migrate_old_reels(conn):
    """
    Placeholder kept for older setups. It does nothing now.
    """
    pass
