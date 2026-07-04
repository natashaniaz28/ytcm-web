"""
The resumable state machine, in NAMI's ``media_state`` idiom.

Every long-running AV stage tracks per-unit progress in a state table
(``acoustic_state`` keyed on ``asset_id``, ``edit_state`` keyed on ``reel_pk``) so a
re-run skips ``done`` rows, can retry ``failed`` ones, and is idempotent. These helpers
are generic over (table, key column) so both stages share one implementation.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

STATES = ("pending", "done", "failed")

ACOUSTIC_STATE = ("acoustic_state", "asset_id")
EXTERNAL_STATE = ("external_state", "asset_id")
ALIGN_STATE = ("align_state", "reel_pk")
EDIT_STATE = ("edit_state", "reel_pk")


def _check(status: str) -> str:
    if status not in STATES:
        raise ValueError(f"invalid status {status!r}; expected one of {STATES}")
    return status


def init_state(conn: sqlite3.Connection, handle: tuple[str, str], keys) -> int:
    """Register *keys* as ``pending`` in the state table, leaving existing rows alone.

    Returns the number of newly-inserted rows. Safe to call repeatedly (uses
    ``INSERT OR IGNORE``), so newly-crawled assets/reels can be enrolled on each run.
    """
    table, key_col = handle
    before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.executemany(
        f"INSERT OR IGNORE INTO {table} ({key_col}, status, updated_at) "
        f"VALUES (?, 'pending', datetime('now'))",
        [(k,) for k in keys],
    )
    conn.commit()
    after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return after - before


def set_status(
    conn: sqlite3.Connection,
    handle: tuple[str, str],
    key: str,
    status: str,
    detail: str | None = None,
) -> None:
    """Upsert *key* to *status* (with optional *detail*) and stamp ``updated_at``."""
    table, key_col = handle
    _check(status)
    conn.execute(
        f"INSERT INTO {table} ({key_col}, status, detail, updated_at) "
        f"VALUES (?, ?, ?, datetime('now')) "
        f"ON CONFLICT({key_col}) DO UPDATE SET "
        f"status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at",
        (key, status, detail),
    )
    conn.commit()


def get_status(conn: sqlite3.Connection, handle: tuple[str, str], key: str) -> str | None:
    """Return the stored status for *key*, or ``None`` if it has no row yet."""
    table, key_col = handle
    row = conn.execute(
        f"SELECT status FROM {table} WHERE {key_col}=?", (key,)
    ).fetchone()
    return row[0] if row else None


def status_counts(conn: sqlite3.Connection, handle: tuple[str, str]) -> dict[str, int]:
    """Return a ``{status: count}`` tally for the table (all of STATES present, even 0)."""
    table, _ = handle
    counts = Counter(
        r[0] for r in conn.execute(f"SELECT status FROM {table}").fetchall()
    )
    return {s: counts.get(s, 0) for s in STATES}


def pending_keys(
    conn: sqlite3.Connection,
    handle: tuple[str, str],
    *,
    include_failed: bool = False,
    limit: int | None = None,
) -> list[str]:
    """List keys still to process: ``pending`` (plus ``failed`` when *include_failed*)."""
    table, key_col = handle
    statuses = ["pending"] + (["failed"] if include_failed else [])
    placeholders = ",".join("?" * len(statuses))
    sql = f"SELECT {key_col} FROM {table} WHERE status IN ({placeholders}) ORDER BY {key_col}"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(sql, statuses).fetchall()]
