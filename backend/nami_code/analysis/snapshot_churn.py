from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_DB = "data/corpus.db"


def _utc_now() -> str:
    """
    Return the current UTC time as a standard text timestamp.
    """
    return datetime.now(timezone.utc).isoformat()


def _new_crawl_id() -> str:
    """
    Make a unique id for a crawl run from the current time plus a short random suffix.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]


def _coerce_conn(conn_or_path: sqlite3.Connection | str | Path | None = None) -> tuple[sqlite3.Connection, bool]:
    """
    Accept either an open database connection or a path, and return a connection plus whether we opened it ourselves.
    """
    if isinstance(conn_or_path, sqlite3.Connection):
        return conn_or_path, False
    return sqlite3.connect(str(conn_or_path or DEFAULT_DB)), True


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """
    Return whether a table exists.
    """
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """
    Return the set of column names of a table.
    """
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """
    Add a column to a table only if it is not already there.
    """
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def ensure_snapshot_tables(conn_or_path: sqlite3.Connection | str | Path | None = None) -> None:
    """
    Create/migrate optional crawl_runs and reel_seen tables idempotently.
    """
    conn, should_close = _coerce_conn(conn_or_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crawl_runs (
              crawl_id TEXT PRIMARY KEY,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              mode TEXT,
              status TEXT,
              notes TEXT,
              note TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reel_seen (
              crawl_id TEXT NOT NULL,
              reel_pk TEXT NOT NULL,
              asset_id TEXT,
              song_id TEXT,
              seen_at TEXT NOT NULL,
              page_no INTEGER,
              page_pos INTEGER,
              rank_pos INTEGER,
              play_count INTEGER,
              like_count INTEGER,
              comment_count INTEGER,
              PRIMARY KEY (crawl_id, reel_pk, asset_id)
            )
        """)

        for col, ddl in {
            "finished_at": "finished_at TEXT",
            "mode": "mode TEXT",
            "status": "status TEXT",
            "notes": "notes TEXT",
            "note": "note TEXT",
        }.items():
            _add_column_if_missing(conn, "crawl_runs", col, ddl)

        for col, ddl in {
            "page_no": "page_no INTEGER",
            "page_pos": "page_pos INTEGER",
            "rank_pos": "rank_pos INTEGER",
            "play_count": "play_count INTEGER",
            "like_count": "like_count INTEGER",
            "comment_count": "comment_count INTEGER",
        }.items():
            _add_column_if_missing(conn, "reel_seen", col, ddl)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_crawl_runs_mode_status_started ON crawl_runs(mode, status, started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reel_seen_crawl_asset ON reel_seen(crawl_id, asset_id)")
        conn.commit()
    finally:
        if should_close:
            conn.close()


def start_crawl_run(
    conn_or_path: sqlite3.Connection | str | Path | None = None,
    mode: str = "refresh",
    notes: str | None = None,
) -> str:
    """
    Open a new crawl-run record and return its id.
    """
    ensure_snapshot_tables(conn_or_path)
    conn, should_close = _coerce_conn(conn_or_path)
    crawl_id = _new_crawl_id()
    now = _utc_now()
    try:
        conn.execute(
            """
            INSERT INTO crawl_runs(crawl_id, started_at, mode, status, notes, note)
            VALUES (?, ?, ?, 'running', ?, ?)
            """,
            (crawl_id, now, mode, notes, notes),
        )
        conn.commit()
        return crawl_id
    finally:
        if should_close:
            conn.close()


def finish_crawl_run(
    conn_or_path: sqlite3.Connection | str | Path | None,
    crawl_id: str,
    status: str = "done",
) -> None:
    """
    Mark a crawl run as finished with the given status.
    """
    if not isinstance(conn_or_path, sqlite3.Connection):
        ensure_snapshot_tables(conn_or_path)
    conn, should_close = _coerce_conn(conn_or_path)
    try:
        conn.execute(
            "UPDATE crawl_runs SET finished_at=?, status=? WHERE crawl_id=?",
            (_utc_now(), status, crawl_id),
        )
        conn.commit()
    finally:
        if should_close:
            conn.close()


def record_reel_seen(
    conn_or_path: sqlite3.Connection | str | Path | None,
    crawl_id: str,
    reel_pk: str,
    asset_id: str,
    song_id: str | None,
    seen_at: str | None = None,
    page_no: int | None = None,
    page_pos: int | None = None,
    rank_pos: int | None = None,
    play_count: Any | None = None,
) -> None:
    """
    Record that a reel was seen during a crawl run, with its position and play count.

    Commit contract: this commits only when it opened the connection itself (i.e.
    when given a path). When the caller passes its own open connection, the write is
    left uncommitted on purpose so many rows can be batched — the caller is then
    responsible for committing. crawl_index's refresh loop relies on this and commits
    its connection once at the end.
    """
    if not isinstance(conn_or_path, sqlite3.Connection):
        ensure_snapshot_tables(conn_or_path)
    conn, should_close = _coerce_conn(conn_or_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO reel_seen(
                crawl_id, reel_pk, asset_id, song_id, seen_at,
                page_no, page_pos, rank_pos, play_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                crawl_id,
                str(reel_pk),
                str(asset_id),
                str(song_id) if song_id is not None else None,
                seen_at or _utc_now(),
                page_no,
                page_pos,
                rank_pos,
                play_count,
            ),
        )
    finally:
        if should_close:
            conn.commit()
            conn.close()


def snapshot_current(db_path: str = DEFAULT_DB, note: str = "manual corpus snapshot") -> str:
    """
    Take a snapshot of the whole current corpus, recording every reel as seen right now.
    """
    ensure_snapshot_tables(db_path)
    conn = sqlite3.connect(db_path)
    try:
        crawl_id = start_crawl_run(conn, mode="snapshot", notes=note)
        now = _utc_now()
        rows = conn.execute("""
            SELECT r.reel_pk, r.asset_id, r.song_id, r.play_count, r.like_count, r.comment_count
            FROM reels r
        """).fetchall()
        for pos, (pk, asset, song, play, like, comm) in enumerate(rows, start=1):
            conn.execute("""
              INSERT OR REPLACE INTO reel_seen(
                  crawl_id, reel_pk, asset_id, song_id, seen_at,
                  rank_pos, play_count, like_count, comment_count
              ) VALUES (?,?,?,?,?,?,?,?,?)
            """, (crawl_id, pk, asset, song, now, pos, play, like, comm))
        finish_crawl_run(conn, crawl_id, status="done")
        conn.commit()
        return crawl_id
    except Exception:
        if 'crawl_id' in locals():
            finish_crawl_run(conn, crawl_id, status="failed")
        raise
    finally:
        conn.close()


def load_snapshots(db_path: str = DEFAULT_DB) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load snapshot tables without creating them. Report calls remain read-only.
    """
    conn = sqlite3.connect(db_path)
    try:
        if not _table_exists(conn, "crawl_runs") or not _table_exists(conn, "reel_seen"):
            return (
                pd.DataFrame(columns=["crawl_id", "started_at", "finished_at", "mode", "status", "notes", "note"]),
                pd.DataFrame(columns=["crawl_id", "reel_pk", "asset_id", "song_id", "seen_at", "page_no", "page_pos", "rank_pos", "play_count", "like_count", "comment_count"]),
            )
        runs = pd.read_sql("SELECT * FROM crawl_runs ORDER BY started_at", conn)
        seen = pd.read_sql("SELECT * FROM reel_seen", conn)
        return runs, seen
    finally:
        conn.close()


def _refresh_done_runs(runs: pd.DataFrame) -> pd.DataFrame:
    """
    Return only the finished refresh runs, oldest first.
    """
    if runs.empty:
        return runs
    mode = runs["mode"] if "mode" in runs.columns else pd.Series([None] * len(runs))
    status = runs["status"] if "status" in runs.columns else pd.Series([None] * len(runs))
    return runs[(mode == "refresh") & (status == "done")].sort_values("started_at")


def churn_summary(db_path: str = DEFAULT_DB) -> pd.DataFrame:
    """
    Compute churn from consecutive completed refresh runs only.
    """
    runs, seen = load_snapshots(db_path)
    refresh_runs = _refresh_done_runs(runs)
    if refresh_runs.empty or seen.empty or refresh_runs["crawl_id"].nunique() < 2:
        return pd.DataFrame([{
            "status": "needs_refresh_runs",
            "message": "Churn needs at least two finished crawlindex --refresh runs. Manual snapshots do not suffice.",
        }])

    out = []
    ids = list(refresh_runs["crawl_id"])
    for prev, cur in zip(ids[:-1], ids[1:]):
        prev_df = seen[seen["crawl_id"] == prev]
        cur_df = seen[seen["crawl_id"] == cur]
        keys = sorted(set(prev_df["asset_id"].dropna()) | set(cur_df["asset_id"].dropna()))
        for asset in keys:
            p = prev_df[prev_df["asset_id"] == asset]
            c = cur_df[cur_df["asset_id"] == asset]
            ps = set(zip(p["reel_pk"].astype(str), p["asset_id"].astype(str)))
            cs = set(zip(c["reel_pk"].astype(str), c["asset_id"].astype(str)))
            retained = len(ps & cs)
            new = len(cs - ps)
            lost = len(ps - cs)
            song = c["song_id"].dropna().iloc[0] if not c.empty and c["song_id"].notna().any() else (p["song_id"].dropna().iloc[0] if not p.empty and p["song_id"].notna().any() else None)
            out.append({
                "from_crawl": prev,
                "to_crawl": cur,
                "asset_id": asset,
                "song_id": song,
                "n_from": len(ps),
                "n_to": len(cs),
                "retained": retained,
                "new": new,
                "lost": lost,
                "retention_rate": retained / len(ps) if ps else None,
                "new_rate": new / len(cs) if cs else None,
            })
    return pd.DataFrame(out)


def _crawl_date(crawl_id: str) -> str:
    """'20260603T101941Z_bd70b3' -> '2026-06-03' (falls back to the raw id)."""
    try:
        return f"{crawl_id[0:4]}-{crawl_id[4:6]}-{crawl_id[6:8]}"
    except Exception:
        return str(crawl_id)


def churn_interval_summary(churn: pd.DataFrame) -> pd.DataFrame:
    """Collapse the per-asset churn table to one row per refresh interval (headline numbers).

    Columns: from_date, to_date, n_assets, retention_pooled (reel-weighted), retention_median
    (per-asset), new_rate_pooled, retained, new, lost. One row per (from_crawl, to_crawl),
    ordered in time. Returns an empty frame when churn has no comparable intervals yet — which
    is also what feeds the report's churn time-series chart once enough intervals exist.
    """
    if churn is None or churn.empty or "retention_rate" not in churn.columns:
        return pd.DataFrame()
    rows = []
    for (frm, to), g in churn.groupby(["from_crawl", "to_crawl"], sort=True):
        n_from = int(g["n_from"].sum())
        n_to = int(g["n_to"].sum())
        retained = int(g["retained"].sum())
        new = int(g["new"].sum())
        lost = int(g["lost"].sum())
        rows.append({
            "from_date": _crawl_date(frm),
            "to_date": _crawl_date(to),
            "n_assets": int(len(g)),
            "retention_pooled": retained / n_from if n_from else None,
            "retention_median": float(g["retention_rate"].median()),
            "new_rate_pooled": new / n_to if n_to else None,
            "retained": retained,
            "new": new,
            "lost": lost,
        })
    return pd.DataFrame(rows)


def snapshot_status(db_path: str = DEFAULT_DB) -> pd.DataFrame:
    """
    Summarise each saved crawl run: how many reels, assets and songs it captured.
    """
    runs, seen = load_snapshots(db_path)
    if runs.empty:
        return pd.DataFrame([{"status": "no_runs", "message": "No crawl runs or snapshots saved yet."}])
    agg = seen.groupby("crawl_id").agg(
        n_reels=("reel_pk", "nunique"),
        n_seen_rows=("reel_pk", "size"),
        n_assets=("asset_id", "nunique"),
        n_songs=("song_id", "nunique"),
    ).reset_index()
    return runs.merge(agg, on="crawl_id", how="left")
