"""
Canonical per-asset audio fetch + download.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path

from .audio import find_ffmpeg
from .config import AvConfig, default_config

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
MIN_AUDIO_BYTES = 2000
MIN_COVER_BYTES = 500

try:
    import certifi

    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover
    SSL_CTX = ssl.create_default_context()


def build_client():
    """Build a HikerAPI client from ``HIKER_TOKEN`` (mirrors ``crawl/fetch_media``).

    Imported lazily so this module is import-safe without ``hikerapi`` and so the test
    suite (which always injects a stub ``client``) never needs the package or a token.
    """
    from dotenv import load_dotenv
    from hikerapi import Client

    load_dotenv()
    token = os.environ.get("HIKER_TOKEN")
    if not token:
        raise RuntimeError(
            "HIKER_TOKEN is not set — cannot fetch canonical audio. Set it in .env, or run "
            "extract-acoustic with --no-fetch to use the local reel-consensus fallback.")
    return Client(token=token)


def _music_asset_info(obj) -> dict | None:
    """
    Locate ``music_asset_info`` in either response shape (track or reel endpoint).
    """
    if not isinstance(obj, dict):
        return None
    obj = obj.get("response", obj) if isinstance(obj.get("response"), dict) else obj
    for container in ("metadata", "clips_metadata"):
        block = obj.get(container)
        if isinstance(block, dict):
            music_info = block.get("music_info")
            if isinstance(music_info, dict):
                mai = music_info.get("music_asset_info")
                if isinstance(mai, dict):
                    return mai
    if isinstance(obj.get("music_asset_info"), dict):
        return obj["music_asset_info"]
    if "progressive_download_url" in obj or "audio_asset_id" in obj:
        return obj
    return None


def _as_json(v) -> str | None:
    """
    JSON-encode a structured value for storage; pass strings through; None stays None.
    """
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return str(v)


def _as_int_bool(v) -> int | None:
    return None if v is None else int(bool(v))


def parse_music_asset_info(payload) -> dict | None:
    """
    Flatten a ``music_asset_info`` block (or a response containing one) to our columns.
    """
    mai = _music_asset_info(payload)
    if mai is None:
        return None
    return {
        "audio_asset_id": mai.get("audio_asset_id"),
        "audio_cluster_id": mai.get("audio_cluster_id"),
        "title": mai.get("title"),
        "sanitized_title": mai.get("sanitized_title"),
        "subtitle": mai.get("subtitle"),
        "display_artist": mai.get("display_artist"),
        "artist_id": mai.get("artist_id"),
        "ig_username": mai.get("ig_username"),
        "duration_ms": mai.get("duration_in_ms"),
        "is_explicit": _as_int_bool(mai.get("is_explicit")),
        "has_lyrics": _as_int_bool(mai.get("has_lyrics")),
        "lyrics": _as_json(mai.get("lyrics")),
        "highlight_start_ms": _as_json(mai.get("highlight_start_times_in_ms")),
        "spotify_track_metadata": _as_json(mai.get("spotify_track_metadata")),
        "licensed_music_subtype": mai.get("licensed_music_subtype"),
        "allows_saving": _as_int_bool(mai.get("allows_saving")),
        "cover_artwork_uri": mai.get("cover_artwork_uri") or mai.get("cover_artwork_thumbnail_uri"),
        "_progressive_url": mai.get("progressive_download_url")
        or mai.get("fast_start_progressive_download_url"),
        "_preview_url": mai.get("web_30s_preview_download_url"),
    }


def pick_source_reels(conn, asset_id: str, cfg: AvConfig | None = None) -> list[str]:
    cfg = cfg or default_config()
    rows = conn.execute(
        "SELECT reel_pk FROM reels WHERE asset_id=? ORDER BY reel_pk", (asset_id,)
    ).fetchall()
    pks = [r[0] for r in rows]
    local = [pk for pk in pks if (cfg.reels_dir / f"{pk}.mp4").exists()]
    remote = [pk for pk in pks if pk not in set(local)]
    return local + remote


def _call_with_retries(fn, *, retries: int, sleep_s: float):
    last = None
    for attempt in range(max(1, retries)):
        try:
            return fn(), None
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt + 1 < retries:
                time.sleep(sleep_s)
    return None, last


def resolve_music_asset_info(
    conn,
    asset_id: str,
    *,
    client,
    cfg: AvConfig | None = None,
    retries: int = 5,
    sleep_s: float = 3.0,
    max_reels_tried: int = 8,
) -> tuple[dict | None, str | None]:
    """Return ``(parsed_meta, source_reel_pk)`` via the resolution ladder, or ``(None, None)``.

    Tier 1 (``source_reel_pk`` is ``None``): the direct track endpoint. Tier 2: the first
    reel whose detail carries a music-asset block.
    """
    cfg = cfg or default_config()

    res, _ = _call_with_retries(
        lambda: client.track_by_canonical_id_v2(asset_id), retries=retries, sleep_s=sleep_s)
    if res is not None:
        parsed = parse_music_asset_info(res)
        if parsed is not None:
            return parsed, None

    for pk in pick_source_reels(conn, asset_id, cfg)[:max_reels_tried]:
        res, _ = _call_with_retries(
            lambda pk=pk: client.media_by_id_v1(pk), retries=2, sleep_s=sleep_s)
        if res is not None:
            parsed = parse_music_asset_info(res)
            if parsed is not None:
                return parsed, pk

    return None, None


def download(url: str, dest: Path, *, timeout: int = 60, min_bytes: int = MIN_AUDIO_BYTES) -> Path:
    """Fetch *url* to *dest* (idempotent: skip a present, large-enough file). Raises on failure.

    Module-level so tests can monkeypatch ``asset_audio.download`` to stay offline.
    """
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size >= min_bytes:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=HEADERS)
    data = urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX).read()
    if len(data) < min_bytes:
        raise RuntimeError(f"download too small ({len(data)} bytes) from {url[:80]}…")
    dest.write_bytes(data)
    return dest


def measure_duration_s(path: Path) -> float | None:
    """Real audio duration in seconds via ffprobe (alongside ffmpeg), or ``None``."""
    path = Path(path)
    if not (path.exists() and path.stat().st_size > 0):
        return None
    ffmpeg = find_ffmpeg()
    ffprobe = ffmpeg[:-6] + "ffprobe" if ffmpeg.endswith("ffmpeg") else "ffprobe"
    for exe in (ffprobe, "ffprobe"):
        try:
            out = subprocess.run(
                [exe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                capture_output=True, text=True)
            if out.returncode == 0 and out.stdout.strip():
                return round(float(out.stdout.strip()), 4)
        except (FileNotFoundError, ValueError):
            continue
    return None


_META_COLS = (
    "asset_id", "audio_asset_id", "audio_cluster_id", "title", "sanitized_title", "subtitle",
    "display_artist", "artist_id", "ig_username", "duration_ms", "duration_real_s",
    "is_explicit", "has_lyrics", "lyrics", "highlight_start_ms", "spotify_track_metadata",
    "licensed_music_subtype", "allows_saving", "cover_artwork_uri", "audio_path", "cover_path",
    "audio_source", "progressive_url_last", "source_reel_pk", "audio_fetched_at",
    "extractor_version",
)


def upsert_music_meta(conn, row: dict) -> None:
    """Upsert one ``asset_music_meta`` row (only the known columns; idempotent)."""
    placeholders = ",".join("?" * len(_META_COLS))
    conn.execute(
        f"INSERT OR REPLACE INTO asset_music_meta ({','.join(_META_COLS)}) "
        f"VALUES ({placeholders})",
        [row.get(c) for c in _META_COLS],
    )
    conn.commit()


def _existing_meta(conn, asset_id: str) -> dict | None:
    cur = conn.execute("SELECT * FROM asset_music_meta WHERE asset_id=?", (asset_id,))
    r = cur.fetchone()
    if r is None:
        return None
    return {d[0]: v for d, v in zip(cur.description, r)}


def asset_audio_path(cfg: AvConfig, asset_id: str) -> Path:
    return cfg.asset_audio_dir / f"{asset_id}.m4a"


def fetch_asset_audio(
    conn,
    cfg: AvConfig | None = None,
    asset_id: str | None = None,
    *,
    client=None,
    refresh: bool = False,
    retries: int = 5,
) -> dict:
    """Resolve → download → measure the canonical audio for one asset; write its meta row.

    Returns the ``asset_music_meta`` row dict (with ``audio_source`` ∈
    {``canonical``, ``preview``, ``unavailable``} and an ``audio_path`` that is ``None`` when
    unavailable). Idempotent: a cached file + meta row short-circuits with **zero** client
    calls unless *refresh* is set. Never raises on a fetch/network failure — it degrades to
    ``unavailable`` so the caller can fall back to the reel-consensus path.
    """
    assert asset_id is not None, "asset_id is required"
    cfg = cfg or default_config()
    audio_path = asset_audio_path(cfg, asset_id)
    cover_path = cfg.asset_audio_dir / f"{asset_id}.jpg"

    if not refresh:
        existing = _existing_meta(conn, asset_id)
        if existing and (
            (existing.get("audio_source") == "unavailable")
            or (audio_path.exists() and audio_path.stat().st_size >= MIN_AUDIO_BYTES)
        ):
            return existing

    client = client or build_client()
    parsed, source_reel = resolve_music_asset_info(
        conn, asset_id, client=client, cfg=cfg, retries=retries)

    row: dict = {c: None for c in _META_COLS}
    row.update({
        "asset_id": asset_id,
        "source_reel_pk": source_reel,
        "audio_fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "extractor_version": __import__("nami_av").EXTRACTOR_VERSION,
        "audio_source": "unavailable",
    })

    if parsed is None:
        upsert_music_meta(conn, row)
        return row

    progressive, preview = parsed.pop("_progressive_url"), parsed.pop("_preview_url")
    row.update(parsed)
    row["progressive_url_last"] = progressive or preview

    for url, source in ((progressive, "canonical"), (preview, "preview")):
        if not url:
            continue
        try:
            download(url, audio_path)
            row["audio_source"] = source
            row["audio_path"] = str(audio_path)
            row["duration_real_s"] = measure_duration_s(audio_path)
            break
        except Exception:  # noqa: BLE001
            continue

    if row.get("cover_artwork_uri"):
        try:
            download(row["cover_artwork_uri"], cover_path, min_bytes=MIN_COVER_BYTES)
            row["cover_path"] = str(cover_path)
        except Exception:  # noqa: BLE001
            pass

    upsert_music_meta(conn, row)
    return row
