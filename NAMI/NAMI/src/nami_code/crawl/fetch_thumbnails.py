from __future__ import annotations
import sqlite3, os, time, urllib.request, threading, ssl
from pathlib import Path

IMG_DIR = Path("data/thumbnails")
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


def _hiker_fresh_url(cl, pk, api_timeout):
    """
    Ask the API for a fresh thumbnail link for one reel, since the old links expire quickly.
    """
    result = {}
    def worker():
        """
        Background helper that fetches the fresh link, run separately so the call can time out.
        """
        try:
            res = cl.media_by_id_v1(pk)
            m = res.get("response", res) if isinstance(res, dict) else res
            result["url"] = (m or {}).get("thumbnail_url")
        except Exception as e:
            result["err"] = str(e)
    t = threading.Thread(target=worker, daemon=True)
    t.start(); t.join(api_timeout)
    if t.is_alive():
        return None
    return result.get("url")


def run(db_path, refresh_url=True, img_timeout=12, api_timeout=20, sleep_s=0.15):
    """
    Download any reel thumbnails still missing on disk, trying the stored link first and a fresh one as backup.
    """
    IMG_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT reel_pk, thumbnail_url FROM reels").fetchall()
    conn.close()

    cl = None
    if refresh_url:
        from dotenv import load_dotenv; from hikerapi import Client
        load_dotenv(); cl = Client(token=os.environ["HIKER_TOKEN"])

    total = len(rows)
    have = sum(1 for pk, _ in rows if (IMG_DIR / f"{pk}.jpg").exists())
    todo = total - have
    print(f"{total} reels, {have} thumbnails already saved, {todo} to fetch.\n")

    ok = skip = fail = 0
    t0 = time.time()
    for i, (pk, url) in enumerate(rows, 1):
        dest = IMG_DIR / f"{pk}.jpg"
        if dest.exists() and dest.stat().st_size > 0:
            skip += 1; continue

        got = False
        if url:
            try:
                got = _download(url, dest, img_timeout)
            except Exception:
                got = False
        if not got and refresh_url and cl is not None:
            fresh = _hiker_fresh_url(cl, pk, api_timeout)
            if fresh:
                try:
                    got = _download(fresh, dest, img_timeout)
                except Exception:
                    got = False

        if got: ok += 1
        else:   fail += 1

        if (ok + fail) % 2 == 0 and (ok + fail) > 0:
            rate = (ok + fail) / (time.time() - t0)
            eta = (todo - ok - fail) / rate / 60 if rate > 0 else 0
            print(f"  {i}/{total} | newly fetched: {ok}, failed: {fail} "
                  f"| {rate:.1f}/s | ETA ~{eta:.0f} min")
        time.sleep(sleep_s)

    print(f"\nDone. Newly fetched: {ok}, skipped: {skip}, failed: {fail}")
    print(f"Total number of thumbnails in {IMG_DIR}/: {sum(1 for p in IMG_DIR.glob('*.jpg'))}")


if __name__ == "__main__":
    DB_PATH     = "data/corpus.db"
    REFRESH_URL = True
    IMG_TIMEOUT = 12
    API_TIMEOUT = 20

    run(DB_PATH, refresh_url=REFRESH_URL, img_timeout=IMG_TIMEOUT, api_timeout=API_TIMEOUT)
