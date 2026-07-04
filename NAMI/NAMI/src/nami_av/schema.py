"""
Table roles:

* ``asset_acoustics``  — level-A acoustic features, **one row per asset_id**.
* ``asset_music_meta`` — per-asset canonical-audio metadata fetched from Instagram
  (title/artist/duration/lyrics/cover/Spotify + the downloaded audio path).
* ``asset_external_meta`` — per-asset cross-platform identity & stats, resolved off the
  Spotify track id Instagram already gives us: Spotify popularity/release/ISRC, then
  MusicBrainz (looked up *by ISRC* — the non-guesswork bridge) for genres/tags and the
  curated outbound links (Discogs / Wikidata / VGMdb / AllMusic).
* ``reel_acoustics``   — level-B per-reel audio (used-segment, overlay flag).
* ``reel_edits``       — per-reel cut times + the near-identical edit cluster they belong to.
* ``acoustic_state``   — resumable pending/done/failed per asset_id.
* ``external_state``   — resumable pending/done/failed per asset_id (the enrich-meta stage).
* ``edit_state``       — resumable pending/done/failed per reel_pk.

Foreign keys to NAMI tables are intentionally *omitted* (the relationship is by
``asset_id`` / ``reel_pk`` convention): an enforced FK would block inserts on a
partially-crawled corpus, which is exactly the situation the sidecar must tolerate.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

TABLES = (
    "asset_acoustics",
    "asset_music_meta",
    "asset_external_meta",
    "reel_acoustics",
    "reel_edits",
    "acoustic_state",
    "external_state",
    "align_state",
    "edit_state",
)

SCHEMA_SQL = """
-- ===== level-A: per asset_id =====================================
CREATE TABLE IF NOT EXISTS asset_acoustics (
    asset_id              TEXT PRIMARY KEY,   -- -> track_variants.asset_id (by convention)
    tempo                 REAL,
    tempo_confidence      REAL,
    est_key               TEXT,
    est_key_confidence    REAL,
    est_key_alt           TEXT,               -- second opinion (Krumhansl-Schmuckler)
    est_key_alt_confidence REAL,
    key_agreement         REAL,               -- 1 / 0.5 / 0 between the two key estimates
    spectral_centroid     REAL,
    spectral_rolloff      REAL,
    spectral_bandwidth    REAL,
    spectral_flatness     REAL,
    rms                   REAL,
    loudness_lufs         REAL,
    dynamic_range         REAL,
    mfcc_summary          TEXT,               -- json
    duration              REAL,
    n_segments            INTEGER,
    segment_boundaries    TEXT,               -- json list of seconds
    harmonic_change_rate  REAL,
    acoustic_cluster      INTEGER,            -- filled by clustering
    n_reels_consensus     INTEGER,            -- how many reels' audio fed the consensus
    extractor_version     TEXT,
    param_hash            TEXT,
    created_at            TEXT DEFAULT (datetime('now'))
);

-- ===== per-asset canonical-audio metadata ==================================
CREATE TABLE IF NOT EXISTS asset_music_meta (
    asset_id                TEXT PRIMARY KEY,   -- -> track_variants.asset_id (by convention)
    audio_asset_id          TEXT,               -- music_asset_info.audio_asset_id (sanity check)
    audio_cluster_id        TEXT,
    title                   TEXT,
    sanitized_title         TEXT,
    subtitle                TEXT,
    display_artist          TEXT,
    artist_id               TEXT,
    ig_username             TEXT,
    duration_ms             INTEGER,            -- claimed by Instagram
    duration_real_s         REAL,               -- measured from the downloaded file (ffprobe)
    is_explicit             INTEGER,
    has_lyrics              INTEGER,
    lyrics                  TEXT,               -- json or raw
    highlight_start_ms      TEXT,               -- json list (the hook offsets)
    spotify_track_metadata  TEXT,               -- json
    licensed_music_subtype  TEXT,
    allows_saving           INTEGER,
    cover_artwork_uri       TEXT,
    audio_path              TEXT,               -- data/asset_audio/{asset_id}.m4a
    cover_path              TEXT,               -- data/asset_audio/{asset_id}.jpg
    audio_source            TEXT,               -- canonical | preview | unavailable
    progressive_url_last    TEXT,               -- transient breadcrumb (expires in hours)
    source_reel_pk          TEXT,               -- reel used for the fallback fetch, if any
    audio_fetched_at        TEXT,
    extractor_version       TEXT,
    created_at              TEXT DEFAULT (datetime('now'))
);

-- ===== per-asset cross-platform identity & stats (enrich-meta) ==============
-- Resolved from the Spotify track id Instagram already hands us. ISRC (from Spotify) is
-- the stable per-recording key MusicBrainz is then looked up by, so the platform links
-- are exact, not fuzzy artist+title matches. Each external field is independently nullable:
-- an asset may resolve on Spotify but dead-end at MusicBrainz (sparse coverage for older
-- Japanese recordings), which is recorded as a state, not hidden.
CREATE TABLE IF NOT EXISTS asset_external_meta (
    asset_id                TEXT PRIMARY KEY,   -- -> asset_music_meta.asset_id (by convention)
    spotify_track_id        TEXT,               -- the id we resolved from (audit breadcrumb)
    isrc                    TEXT,               -- the cross-platform recording key (via Deezer)
    -- free stats source: Deezer (keyless), reached via Odesli off the Spotify id
    deezer_track_id         TEXT,
    deezer_url              TEXT,
    deezer_rank             INTEGER,            -- Deezer play-count proxy (higher = more played)
    deezer_bpm              REAL,
    deezer_release_date     TEXT,               -- YYYY-MM-DD
    deezer_album            TEXT,
    deezer_artist           TEXT,
    deezer_genres           TEXT,               -- json list (Deezer album genres)
    platform_links          TEXT,               -- json {platform: url} from Odesli (Apple/YT/…)
    spotify_popularity      INTEGER,            -- 0-100, Spotify's own (only if Premium creds)
    lastfm_listeners        INTEGER,            -- global unique listeners (Last.fm, free key)
    lastfm_playcount        INTEGER,            -- global scrobble count (Last.fm)
    lastfm_url              TEXT,
    mb_recording_mbid       TEXT,               -- MusicBrainz recording (the hub id)
    mb_title                TEXT,
    mb_artist               TEXT,
    mb_first_release_date   TEXT,
    mb_tags                 TEXT,               -- json list (community genres/tags by count)
    mb_url_rels             TEXT,               -- json {service: url} (discogs/wikidata/vgmdb/…)
    discogs_url             TEXT,               -- convenience extracts from mb_url_rels
    wikidata_url            TEXT,
    vgmdb_url               TEXT,
    allmusic_url            TEXT,
    external_state          TEXT,               -- resolved | partial | unresolved
    detail                  TEXT,               -- plain-words note on what (didn't) resolve
    fetched_at              TEXT,
    extractor_version       TEXT,
    created_at              TEXT DEFAULT (datetime('now'))
);

-- ===== level-B: per reel_pk ======================================
CREATE TABLE IF NOT EXISTS reel_acoustics (
    reel_pk               TEXT PRIMARY KEY,   -- -> reels.reel_pk (by convention)
    asset_id              TEXT,
    used_segment_start    REAL,               -- offset (s) into the canonical track
    used_segment_end      REAL,
    align_confidence      REAL,
    has_overlay           INTEGER,            -- 0/1: likely voiceover / added audio
    extractor_version     TEXT,
    param_hash            TEXT,
    created_at            TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reel_acoustics_asset ON reel_acoustics(asset_id);

-- ===== per-reel edits: cut times + near-identical edit cluster ====
CREATE TABLE IF NOT EXISTS reel_edits (
    reel_pk               TEXT PRIMARY KEY,   -- -> reels.reel_pk (by convention)
    asset_id              TEXT,
    cut_times             TEXT,               -- json list (reel-local seconds)
    cut_times_aligned     TEXT,               -- json list (shared audio timeline)
    n_cuts                INTEGER,
    soft_times            TEXT,               -- json list: gradual transitions (reel-local)
    soft_times_aligned    TEXT,               -- json list: soft transitions on shared timeline
    n_soft                INTEGER,
    fps                   REAL,
    duration              REAL,
    edit_cluster          INTEGER,            -- near-identical edit group within the asset
                                              --   (>=0 = group id, -1 = one-off, NULL = no cuts)
    detector_threshold    REAL,
    extractor_version     TEXT,
    param_hash            TEXT,
    created_at            TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reel_edits_asset ON reel_edits(asset_id);

-- ===== resumable state machines (media_state idiom) ==========================
CREATE TABLE IF NOT EXISTS acoustic_state (
    asset_id    TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'pending',   -- pending | done | failed
    detail      TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS external_state (
    asset_id    TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'pending',   -- pending | done | failed
    detail      TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS align_state (
    reel_pk     TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'pending',   -- pending | done | failed
    detail      TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS edit_state (
    reel_pk     TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'pending',   -- pending | done | failed
    detail      TEXT,
    updated_at  TEXT
);
"""


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, decl: str
) -> None:
    """``ALTER TABLE ... ADD COLUMN`` only when *column* is absent (SQLite lacks IF NOT
    EXISTS for columns). Idempotent and additive — never drops or rewrites the table."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in have:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def apply_schema(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Create the sidecar's tables on *conn* if missing, then commit. Idempotent."""
    conn.executescript(SCHEMA_SQL)
    _add_column_if_missing(conn, "asset_acoustics", "audio_source", "TEXT")
    for col, decl in (
        ("est_key_alt", "TEXT"), ("est_key_alt_confidence", "REAL"),
        ("key_agreement", "REAL"),
    ):
        _add_column_if_missing(conn, "asset_acoustics", col, decl)
    for col, decl in (
        ("soft_times", "TEXT"), ("soft_times_aligned", "TEXT"), ("n_soft", "INTEGER"),
    ):
        _add_column_if_missing(conn, "reel_edits", col, decl)
    for col, decl in (
        ("deezer_track_id", "TEXT"), ("deezer_url", "TEXT"), ("deezer_rank", "INTEGER"),
        ("deezer_bpm", "REAL"), ("deezer_release_date", "TEXT"), ("deezer_album", "TEXT"),
        ("deezer_artist", "TEXT"), ("deezer_genres", "TEXT"), ("platform_links", "TEXT"),
        ("lastfm_listeners", "INTEGER"), ("lastfm_playcount", "INTEGER"), ("lastfm_url", "TEXT"),
    ):
        _add_column_if_missing(conn, "asset_external_meta", col, decl)
    conn.commit()
    return conn


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open *db_path* and ensure the sidecar schema is present.

    Does not run NAMI's core DDL — the sidecar expects to attach to an existing
    ``corpus.db``. On a brand-new file it simply yields the sidecar tables.
    """
    conn = sqlite3.connect(str(db_path))
    return apply_schema(conn)


def sidecar_tables(conn: sqlite3.Connection) -> set[str]:
    """Return which of the sidecar's tables currently exist in the database."""
    present = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    return present & set(TABLES)
