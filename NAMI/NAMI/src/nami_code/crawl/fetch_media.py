"""
Best-effort recovery stage for reel MP4s, parallel to fetch_thumbnails.py.

The primary place video is captured is crawl_details.save_video (during the crawl
window, while the CDN URL is fresh). This stage backfills any reel missing a local
`data/reels/{pk}.mp4`: it tries the stored `reels.video_url` first, then a fresh
HikerAPI `media_by_id_v1(...).video_url`. Video URLs expire faster than thumbnails,
so this is a safety net, not the main path. It updates `media_state` as it goes.
"""

from __future__ import annotations
import sqlite3, os, time, urllib.request, threading, ssl
from pathlib import Path

from nami_code.vision.db_annotations import upgrade

MEDIA_DIR = Path("data/reels")
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = ssl.create_default_context()


def _download(url, dest, timeout):
    """
    Fetch a file from a web link and save it. Returns whether it worked.
    """
    req = urllib.request.Request(url, headers=HEADERS)
    data = urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX).read()
    if len(data) > 500:
        dest.write_bytes(data); return True
    return False


def _get_client():
    """
    Create the HikerAPI client (lazy, factored out so tests can monkeypatch it).
    """
    from dotenv import load_dotenv
    from hikerapi import Client
    load_dotenv()
    return Client(token=os.environ["HIKER_TOKEN"])


def _hiker_fresh_url(cl, pk, api_timeout):
    """
    Ask the API for a fresh video link for one reel, since the old links expire quickly.
    """
    result = {}
    def worker():
        """
        Background helper that fetches the fresh link, run separately so the call can time out.
        """
        try:
            res = cl.media_by_id_v1(pk)
            m = res.get("response", res) if isinstance(res, dict) else res
            result["url"] = (m or {}).get("video_url")
        except Exception as e:
            result["err"] = str(e)
    t = threading.Thread(target=worker, daemon=True)
    t.start(); t.join(api_timeout)
    if t.is_alive():
        return None
    return result.get("url")


def _set_state(conn, pk, status, media_path):
    """
    Record whether a reel's video was downloaded, so the work can be resumed later.
    """
    conn.execute(
        "INSERT OR REPLACE INTO media_state (reel_pk, status, media_path, updated_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (pk, status, media_path),
    )


def run(db_path, refresh_url=True, vid_timeout=60, api_timeout=20, sleep_s=0.15):
    """
    Download any reel videos still missing on disk, trying the stored link first and a fresh one as backup.
    """
    upgrade(db_path)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """SELECT r.reel_pk, r.video_url
           FROM reels r
           LEFT JOIN media_state m ON m.reel_pk = r.reel_pk
           WHERE m.status IS NULL OR m.status != 'no_video'"""
    ).fetchall()

    cl = None
    if refresh_url:
        cl = _get_client()

    total = len(rows)
    def _have_local(pk):
        p = MEDIA_DIR / f"{pk}.mp4"
        return p.exists() and p.stat().st_size > 0
    have = sum(1 for pk, _ in rows if _have_local(pk))
    todo = total - have
    print(f"{total} reels, {have} videos already saved, {todo} to fetch.\n")

    ok = skip = fail = 0
    t0 = time.time()
    for i, (pk, url) in enumerate(rows, 1):
        dest = MEDIA_DIR / f"{pk}.mp4"
        if dest.exists() and dest.stat().st_size > 0:
            _set_state(conn, pk, "done", str(dest)); conn.commit()
            skip += 1; continue

        got = False
        if url:
            try:
                got = _download(url, dest, vid_timeout)
            except Exception:
                got = False
        if not got and refresh_url and cl is not None:
            fresh = _hiker_fresh_url(cl, pk, api_timeout)
            if fresh:
                try:
                    got = _download(fresh, dest, vid_timeout)
                except Exception:
                    got = False

        if got:
            _set_state(conn, pk, "done", str(dest)); ok += 1
        else:
            _set_state(conn, pk, "failed", None); fail += 1
        conn.commit()

        if (ok + fail) % 2 == 0 and (ok + fail) > 0:
            rate = (ok + fail) / (time.time() - t0)
            eta = (todo - ok - fail) / rate / 60 if rate > 0 else 0
            print(f"  {i}/{total} | newly fetched: {ok}, failed: {fail} "
                  f"| {rate:.1f}/s | ETA ~{eta:.0f} min")
        time.sleep(sleep_s)

    conn.close()
    print(f"\nDone. Newly fetched: {ok}, skipped: {skip}, failed: {fail}")
    print(f"Total number of videos in {MEDIA_DIR}/: {sum(1 for p in MEDIA_DIR.glob('*.mp4'))}")


if __name__ == "__main__":
    DB_PATH     = "data/corpus.db"
    REFRESH_URL = True
    VID_TIMEOUT = 60
    API_TIMEOUT = 20

    run(DB_PATH, refresh_url=REFRESH_URL, vid_timeout=VID_TIMEOUT, api_timeout=API_TIMEOUT)
