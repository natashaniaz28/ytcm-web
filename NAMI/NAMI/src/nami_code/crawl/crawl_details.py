"""
Stage B: populate indexed Reel IDs with media_by_id_v1.

This module only fetches rows from reel_index where details_done = 0. It is
therefore already suitable after a refresh crawl: crawl_index adds new IDs,
crawl_details downloads only those new pending IDs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import hashlib
import hmac
import os
import re
import ssl
import time
import urllib.request

from dotenv import load_dotenv

from nami_code.db import get_conn


IMG_DIR = Path("data/thumbnails")
IMG_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_DIR = Path("data/reels")
DL_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

try:
    import certifi

    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()


_CLIENT = None
_SALT: bytes | None = None
HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def save_thumbnail(pk, url):
    """
    Download thumbnail while the Instagram CDN URL is still fresh.
    """
    if not url:
        return
    dest = IMG_DIR / f"{pk}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return
    try:
        req = urllib.request.Request(url, headers=DL_HEADERS)
        data = urllib.request.urlopen(req, timeout=15, context=SSL_CTX).read()
        if len(data) > 500:
            dest.write_bytes(data)
    except Exception:
        pass


def save_video(pk, url, out_dir=MEDIA_DIR):
    """
    Download the reel MP4 while the Instagram CDN URL is still fresh.

    Mirrors save_thumbnail: skips when a non-empty file already exists, uses the
    same SSL context and headers. CDN video_url expires within hours, so this must
    run inside the crawl window (fetch_media.py is the later best-effort recovery).
    Returns the local path string on success, else None.
    """
    if not url:
        return None
    out_dir = Path(out_dir)
    dest = out_dir / f"{pk}.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers=DL_HEADERS)
        data = urllib.request.urlopen(req, timeout=60, context=SSL_CTX).read()
        if len(data) > 500:
            dest.write_bytes(data)
            return str(dest)
    except Exception:
        pass
    return None


def get_client():
    """
    Create the HikerAPI client lazily so dry runs can import safely.
    """
    global _CLIENT
    if _CLIENT is None:
        load_dotenv()
        from hikerapi import Client

        token = os.environ.get("HIKER_TOKEN")
        if not token:
            raise RuntimeError("Missing HIKER_TOKEN in environment or .env")
        _CLIENT = Client(token=token)
    return _CLIENT


def get_salt() -> bytes:
    """
    Read the pseudonymization salt.
    """
    global _SALT
    if _SALT is None:
        load_dotenv()
        salt = os.environ.get("PSEUDO_SALT")
        if not salt:
            raise RuntimeError("Missing PSEUDO_SALT in environment or .env")
        _SALT = salt.encode()
    return _SALT


def pseudo(v):
    """
    Turn a real user id into a fixed anonymous code, so the corpus stores no real identities.
    """
    return hmac.new(get_salt(), str(v).encode(), hashlib.sha256).hexdigest()[:24]


def to_iso(ts):
    """
    Turn a Unix timestamp into a readable UTC date-and-time string.
    """
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def fetch_detail(pk):
    """
    Ask the API for one reel's full details, retrying a few times if it fails.
    """
    client = get_client()
    for attempt in range(5):
        try:
            res = client.media_by_id_v1(pk)
            return res.get("response", res) if isinstance(res, dict) else res
        except Exception as exc:
            wait_s = 2**attempt
            print(f"    ! {exc}, retry {wait_s}s", flush=True)
            time.sleep(wait_s)
    return None


def run(conn, sleep_s=0.25, limit=None):
    """
    Download the details, thumbnail and video for every reel still waiting, and save them. Commits after each reel so it can resume.
    """
    rows = conn.execute(
        """SELECT ri.reel_pk, ri.asset_id, tv.song_id, tv.variant_label
           FROM reel_index ri JOIN track_variants tv USING(asset_id)
           WHERE ri.details_done=0
           ORDER BY ri.rowid"""
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]

    total = len(rows)
    done = 0
    failed = 0
    print(f"{total} reels to be loaded\n", flush=True)

    if total == 0:
        print("Completed: 0 reels with details loaded.", flush=True)
        return

    for idx, (pk, asset_id, song_id, label) in enumerate(rows, start=1):
        print(f"Details [{idx}/{total}] reel {pk} / {song_id} / {label}", flush=True)
        media = fetch_detail(pk)
        if not media:
            failed += 1
            print(f"  Details [{idx}/{total}]: failed ({failed} errors up to now)", flush=True)
            continue

        cap = media.get("caption_text") or ""
        thumb = media.get("thumbnail_url")
        vurl = media.get("video_url")
        save_thumbnail(pk, thumb)
        media_path = save_video(pk, vurl)

        conn.execute(
            """INSERT OR REPLACE INTO reels
            (reel_pk, song_id, asset_id, variant_label, code, creator_pseudo, taken_at,
             caption_text, like_count, play_count, view_count, comment_count,
             video_duration, thumbnail_url, video_url, media_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pk,
                song_id,
                asset_id,
                label,
                media.get("code"),
                pseudo((media.get("user") or {}).get("pk", "?")),
                to_iso(media["taken_at_ts"]) if media.get("taken_at_ts") else media.get("taken_at"),
                cap,
                media.get("like_count"),
                media.get("play_count"),
                media.get("view_count"),
                media.get("comment_count"),
                media.get("video_duration"),
                thumb,
                vurl,
                media_path,
            ),
        )
        if media_path:
            conn.execute(
                "INSERT OR REPLACE INTO media_state (reel_pk, status, media_path, updated_at) "
                "VALUES (?, 'done', ?, datetime('now'))",
                (pk, media_path),
            )
        elif not vurl:
            conn.execute(
                "INSERT OR REPLACE INTO media_state (reel_pk, status, updated_at) "
                "VALUES (?, 'no_video', datetime('now'))",
                (pk,),
            )
        else:
            conn.execute(
                "INSERT OR REPLACE INTO media_state (reel_pk, status, updated_at) "
                "VALUES (?, 'pending', datetime('now'))",
                (pk,),
            )
        for tag in HASHTAG_RE.findall(cap):
            conn.execute("INSERT OR IGNORE INTO reel_hashtags VALUES (?, ?)", (pk, tag.lower()))
        conn.execute("UPDATE reel_index SET details_done=1 WHERE reel_pk=? AND asset_id=?", (pk, asset_id))
        conn.commit()

        done += 1
        print(f"  Details [{idx}/{total}]: {done} loaded, {failed} failed ... (~{idx} requests)", flush=True)
        time.sleep(sleep_s)

    print(f"\nDone: loaded {done} reels with details. Errors: {failed}.", flush=True)


if __name__ == "__main__":
    conn = get_conn()
    try:
        run(conn)
        try:
            import pandas as pd

            print(
                "\n",
                pd.read_sql(
                    "SELECT song_id, COUNT(*) AS n, MIN(taken_at) AS first_date, MAX(taken_at) AS last_date "
                    "FROM reels GROUP BY song_id",
                    conn,
                ).to_string(index=False),
            )
        except Exception:
            pass
    finally:
        conn.close()
