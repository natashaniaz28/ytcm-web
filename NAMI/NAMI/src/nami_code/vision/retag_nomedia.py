"""
Re-queue reels that were skipped as 'no_media' once their MP4 is available.

After fetch_media.py (or a re-crawl) backfills videos, this flips matching
vision_state rows from 'no_media' back to 'pending' so the next tag_vision run
picks them up. Logic lives in run() (callable, no import side effects).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = "data/corpus.db"
MEDIA_DIR = Path("data/reels")


def run(db_path: str = DB_PATH, media_dir=MEDIA_DIR):
    """
    Flip 'no_media' reels back to 'pending' when a local {pk}.mp4 now exists.

    Returns (requeued, still_missing).
    """
    media_dir = Path(media_dir)
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT reel_pk FROM vision_state WHERE status='no_media'"
    ).fetchall()
    print(f"Total number of 'no_media' reels: {len(rows)}")

    requeued = still_missing = 0
    for (pk,) in rows:
        mp4 = media_dir / f"{pk}.mp4"
        if mp4.exists() and mp4.stat().st_size > 0:
            conn.execute(
                "UPDATE vision_state SET status='pending' WHERE reel_pk=?", (pk,))
            requeued += 1
        else:
            still_missing += 1
    conn.commit()
    conn.close()

    print(f"  -> Video now available, flagged 'pending'   : {requeued}")
    print(f"  -> Still without video (stays 'no_media')    : {still_missing}")
    print("\nNext step: run tag_vision with reset disabled to tag the re-queued reels.")
    return requeued, still_missing


if __name__ == "__main__":
    run()
