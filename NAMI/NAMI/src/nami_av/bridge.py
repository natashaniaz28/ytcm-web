"""
NAMI bridge — derive coarse acoustic labels and write them into NAMI's ``annotations``
table as ``source='acoustic'``.

One reel-level annotation dimension is produced from AV's per-asset results:

* ``sonic`` — a coarse acoustic *family* per asset, binned from its level-A features
  (bright/warm × fast/slow relative to the corpus medians). A deterministic, interpretable
  bridge variable for cross-tabs against NAMI's context/format tags.

Annotations key on ``reel_pk`` (NAMI's PK is ``(reel_pk, dimension, category, source)``),
so an asset's label is written for each of its reels. The whole ``source='acoustic'`` set
is rewritten on each run (delete-then-insert, scoped to that source — keyword/vision rows
are never touched), so re-runs are idempotent and never leave stale categories.
"""

from __future__ import annotations

import sqlite3
from statistics import median, pstdev

import numpy as np

_ANNOTATIONS_DDL = """
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
"""

SOURCE = "acoustic"
MODEL = "nami_av"


def acoustic_families(conn: sqlite3.Connection) -> dict[str, tuple[str, float]]:
    """{asset_id: (family, confidence)} binned from tempo × spectral centroid.

    Families are ``{bright|warm}-{fast|slow}`` relative to the corpus medians; confidence
    grows with how far the asset sits from the dividing lines (clamped to [0.4, 1.0]).
    """
    rows = conn.execute(
        "SELECT asset_id, tempo, spectral_centroid FROM asset_acoustics "
        "WHERE tempo IS NOT NULL AND spectral_centroid IS NOT NULL"
    ).fetchall()
    if not rows:
        return {}
    tempos = [r[1] for r in rows]
    centroids = [r[2] for r in rows]
    t_med, c_med = median(tempos), median(centroids)
    t_sd, c_sd = pstdev(tempos) or 1.0, pstdev(centroids) or 1.0

    out: dict[str, tuple[str, float]] = {}
    for asset_id, tempo, centroid in rows:
        bright = "bright" if centroid >= c_med else "warm"
        fast = "fast" if tempo >= t_med else "slow"
        z = (abs((tempo - t_med) / t_sd) + abs((centroid - c_med) / c_sd)) / 2.0
        conf = float(np.clip(0.4 + z / 4.0, 0.4, 1.0))
        out[asset_id] = (f"{bright}-{fast}", round(conf, 3))
    return out


def _reels_of_asset(conn: sqlite3.Connection, asset_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT reel_pk FROM reels WHERE asset_id=?", (asset_id,)).fetchall()]


def write_annotations(conn: sqlite3.Connection) -> dict[str, int]:
    """Write the acoustic annotations into NAMI's table; return per-dimension row counts.

    Idempotent: deletes the existing ``source='acoustic'`` rows first, then inserts the
    current labels for every reel of each labelled asset. Keyword/vision rows are left
    untouched.
    """
    conn.executescript(_ANNOTATIONS_DDL)
    conn.execute("DELETE FROM annotations WHERE source=?", (SOURCE,))

    families = acoustic_families(conn)
    counts = {"sonic": 0}

    def _insert(reel_pk, dimension, category, confidence):
        conn.execute(
            "INSERT OR REPLACE INTO annotations "
            "(reel_pk, dimension, category, source, confidence, model) "
            "VALUES (?,?,?,?,?,?)",
            (reel_pk, dimension, category, SOURCE, confidence, MODEL))

    for asset_id, (family, conf) in families.items():
        for reel_pk in _reels_of_asset(conn, asset_id):
            _insert(reel_pk, "sonic", family, conf)
            counts["sonic"] += 1

    conn.commit()
    return counts
