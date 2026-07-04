"""
Cross-platform identity & stats — the ``enrich-meta`` stage.

Instagram hands us a **Spotify track id** per audio asset (in
``asset_music_meta.spotify_track_metadata``). That id is the thread we pull to attach
*external* statistics and **stable** links to other music databases, without any
artist+title guesswork. The Spotify Web API itself is **not** used by default — as of 2025
Spotify gates every data call behind the app owner holding a *Premium* subscription (a free
app gets a token but each call 403s "Active premium subscription required") — so the default
chain is built from **free, no-login** services instead:

  1. **Odesli / song.link** (``/v1-alpha.1/links``) — resolves the Spotify track to the
     *same recording* on other platforms (Deezer, Apple Music, YouTube, Tidal, Amazon…).
     These links are exact (Odesli matches by the platform id, not by name).
  2. **Deezer** (``api.deezer.com/track`` + ``/album``) — free & keyless; off the Deezer id
     from step 1 it returns the track's **ISRC** (the stable, unique-per-recording code),
     plus album, release date, a ``rank`` play-count proxy, BPM and album genres.
  3. **MusicBrainz** (``/ws/2/isrc/{ISRC}``) — looked up **by the ISRC** (the non-guesswork
     bridge): an exact match where the data exists, giving community genres/tags and the
     **curated** outbound links — Discogs, Wikidata, VGMdb (great for Japanese city pop),
     AllMusic.
  4. **Last.fm** (``track.getInfo``, free API key) — global **listeners** and **playcount**
     for the song (by artist+track). A more defensible "how known is this" figure than any
     single-platform popularity score, and free (no subscription).

Optionally (``with_spotify=True`` and Premium creds present) it also fetches Spotify's own
``popularity`` (0-100). Spotify's *audio-features* (tempo/energy) are deprecated for new apps
and never used — the sidecar measures those itself (:mod:`nami_av.features`).

This module mirrors :mod:`nami_av.asset_audio`'s contract: it is the **only** place this
feature touches the network; the HTTP entry points (:func:`http_get_json`,
:func:`get_spotify_token`) are module-level so the test suite monkeypatches them and runs
fully offline. Results are written **per asset** to ``asset_external_meta`` and the stage is
resumable via ``external_state`` (cached row = no re-fetch). Arrows point one way only:
``corpus.db → asset_external_meta``; nothing in NAMI reads it back.

Each external field is independently nullable and the outcome is recorded as a *state*
(``resolved`` / ``partial`` / ``unresolved``) so a dead-end at MusicBrainz — common for older
Japanese recordings whose ISRC isn't indexed there — reads as coverage, not a bug.

Credentials: **none required** for the Odesli→Deezer→MusicBrainz core. Set
``MUSICBRAINZ_CONTACT`` (an email/URL) so the MusicBrainz User-Agent identifies itself, as
their API etiquette asks. ``LASTFM_API_KEY`` (a free key, no subscription) enables the
listeners/playcount figures. ``SPOTIFY_CLIENT_ID`` / ``SPOTIFY_CLIENT_SECRET`` are only
consulted when ``with_spotify`` is on (and only useful if the app owner has Premium).
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import EXTRACTOR_VERSION, state
from .config import AvConfig, default_config

ODESLI_API = "https://api.song.link/v1-alpha.1/links"
DEEZER_API = "https://api.deezer.com"
LASTFM_API = "https://ws.audioscrobbler.com/2.0/"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API = "https://api.spotify.com/v1"
MUSICBRAINZ_API = "https://musicbrainz.org/ws/2"

MB_RATE_LIMIT_S = 1.1
ODESLI_RATE_LIMIT_S = 6.5
_DEFAULT_CONTACT = "https://github.com/ (set MUSICBRAINZ_CONTACT)"
_UA = "Mozilla/5.0 (compatible; NAMI-nami_av/%s)" % EXTRACTOR_VERSION

_ODESLI_PLATFORMS = {
    "appleMusic": "apple_music", "youtube": "youtube", "youtubeMusic": "youtube_music",
    "deezer": "deezer", "tidal": "tidal", "amazonMusic": "amazon_music",
    "soundcloud": "soundcloud", "pandora": "pandora",
}

_URL_SERVICES = {
    "discogs.com": "discogs", "wikidata.org": "wikidata", "vgmdb.net": "vgmdb",
    "allmusic.com": "allmusic", "open.spotify.com": "spotify", "youtube.com": "youtube",
}

try:
    import certifi

    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover
    SSL_CTX = ssl.create_default_context()


def http_get_json(url: str, *, headers: dict | None = None, timeout: int = 30) -> dict:
    """GET *url* and parse JSON. Raises on transport/HTTP/JSON failure (caller degrades)."""
    hdrs = {"User-Agent": _UA}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_spotify_token(client_id: str | None = None, client_secret: str | None = None) -> str:
    """Client-Credentials access token (no user login). Reads env when args omitted.

    Only needed for the optional Spotify-popularity fetch — and only useful if the app
    owner has Premium (else the token issues but data calls 403).
    """
    if client_id is None or client_secret is None:
        from dotenv import load_dotenv

        load_dotenv()
        client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET are not set")
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        SPOTIFY_TOKEN_URL, data=data,
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def _mb_user_agent(contact: str | None = None) -> str:
    contact = contact or os.environ.get("MUSICBRAINZ_CONTACT") or _DEFAULT_CONTACT
    return f"NAMI-nami_av/{EXTRACTOR_VERSION} ( {contact} )"


def spotify_track_id(raw) -> str | None:
    """Track id from the stored ``spotify_track_metadata`` json (id field or a track URL)."""
    if not raw:
        return None
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    tid = d.get("spotify_track_id") or d.get("spotify_id") or d.get("track_id") or d.get("id")
    if tid:
        return str(tid)
    for k in ("spotify_listen_uri", "spotify_uri", "uri", "url", "spotify_url"):
        v = d.get(k)
        if isinstance(v, str) and v:
            if v.startswith("spotify:track:"):
                return v.split(":")[-1]
            if "open.spotify.com/track/" in v:
                return v.split("/track/")[-1].split("?")[0]
    return None


def odesli_links(spotify_id: str) -> dict:
    """Raw Odesli payload for a Spotify track id."""
    url = f"{ODESLI_API}?url=" + urllib.parse.quote(f"spotify:track:{spotify_id}", safe="")
    return http_get_json(url)


def parse_odesli(payload: dict) -> dict:
    """Pull the Deezer id and a ``{platform: url}`` map out of an Odesli payload."""
    by = (payload or {}).get("linksByPlatform") or {}
    links: dict[str, str] = {}
    for plat, label in _ODESLI_PLATFORMS.items():
        url = (by.get(plat) or {}).get("url")
        if url:
            links[label] = url
    dz = (by.get("deezer") or {}).get("entityUniqueId") or ""
    deezer_id = dz.replace("DEEZER_SONG::", "") if dz.startswith("DEEZER_SONG::") else None
    return {"deezer_track_id": deezer_id,
            "platform_links": json.dumps(links, ensure_ascii=False) if links else None}


def deezer_track(deezer_id: str) -> dict:
    """Raw Deezer track payload (note: Deezer returns ``{"error": …}`` with HTTP 200)."""
    return http_get_json(f"{DEEZER_API}/track/{deezer_id}")


def deezer_album(album_id: str) -> dict:
    return http_get_json(f"{DEEZER_API}/album/{album_id}")


def _num_or_none(v):
    return v if isinstance(v, (int, float)) and v else None


def parse_deezer_track(payload: dict) -> dict:
    """Normalise a Deezer track payload to our columns (and surface the album id)."""
    p = payload or {}
    if p.get("error"):
        return {}
    album = p.get("album") or {}
    return {
        "isrc": p.get("isrc") or None,
        "deezer_rank": _num_or_none(p.get("rank")),
        "deezer_bpm": _num_or_none(p.get("bpm")),
        "deezer_release_date": p.get("release_date") or album.get("release_date") or None,
        "deezer_album": album.get("title"),
        "deezer_artist": (p.get("artist") or {}).get("name"),
        "_album_id": album.get("id"),
    }


def deezer_album_genres(album_payload: dict) -> list[str]:
    data = ((album_payload or {}).get("genres") or {}).get("data") or []
    return [g["name"] for g in data if isinstance(g, dict) and g.get("name")]


def lastfm_track(artist: str, track: str, api_key: str) -> dict:
    """Raw Last.fm ``track.getInfo`` payload (artist+track lookup, autocorrect on).

    ``autocorrect=1`` lets Last.fm fix minor spelling/romanisation differences. A miss
    returns ``{"error": 6, …}`` with HTTP 200, handled by :func:`parse_lastfm`.
    """
    params = {"method": "track.getInfo", "api_key": api_key, "format": "json",
              "autocorrect": "1", "artist": artist, "track": track}
    return http_get_json(LASTFM_API + "?" + urllib.parse.urlencode(params))


def parse_lastfm(payload: dict) -> dict:
    """Normalise a Last.fm track payload to our columns (missing/error → all None)."""
    t = (payload or {}).get("track")
    if not isinstance(t, dict):
        return {"lastfm_listeners": None, "lastfm_playcount": None, "lastfm_url": None}

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    return {"lastfm_listeners": _int(t.get("listeners")),
            "lastfm_playcount": _int(t.get("playcount")),
            "lastfm_url": t.get("url")}


def spotify_track(track_id: str, token: str) -> dict:
    return http_get_json(f"{SPOTIFY_API}/tracks/{track_id}",
                         headers={"Authorization": f"Bearer {token}"})


def musicbrainz_by_isrc(isrc: str, *, contact: str | None = None) -> dict:
    url = f"{MUSICBRAINZ_API}/isrc/{urllib.parse.quote(isrc)}?fmt=json"
    try:
        return http_get_json(url, headers={"User-Agent": _mb_user_agent(contact)})
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"recordings": []}
        raise


def musicbrainz_recording(mbid: str, *, contact: str | None = None) -> dict:
    inc = "url-rels+artist-credits+tags+genres+releases"
    url = f"{MUSICBRAINZ_API}/recording/{urllib.parse.quote(mbid)}?fmt=json&inc={inc}"
    return http_get_json(url, headers={"User-Agent": _mb_user_agent(contact)})


def _first_recording_mbid(isrc_payload: dict) -> str | None:
    recs = (isrc_payload or {}).get("recordings") or []
    return recs[0].get("id") if recs and isinstance(recs[0], dict) else None


def _extract_url_rels(relations) -> dict[str, str]:
    """Map MusicBrainz url-relations to ``{service: url}`` by recognised host."""
    out: dict[str, str] = {}
    for rel in relations or []:
        res = ((rel or {}).get("url") or {}).get("resource")
        if not res:
            continue
        for host, service in _URL_SERVICES.items():
            if host in res and service not in out:
                out[service] = res
    return out


def _mb_tags(payload: dict) -> list[str]:
    """Community genres+tags, de-duped and ordered by vote count then name."""
    scored: dict[str, int] = {}
    for key in ("genres", "tags"):
        for t in payload.get(key) or []:
            name = (t or {}).get("name")
            if name:
                scored[name] = max(scored.get(name, 0), int(t.get("count") or 0))
    return [n for n, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))]


def parse_mb_recording(payload: dict) -> dict:
    """Normalise a MusicBrainz recording payload to our columns (missing → None)."""
    p = payload or {}
    ac = p.get("artist-credit") or []
    artist = ac[0]["name"] if ac and isinstance(ac[0], dict) and ac[0].get("name") else None
    rels = _extract_url_rels(p.get("relations"))
    tags = _mb_tags(p)
    return {
        "mb_recording_mbid": p.get("id"),
        "mb_title": p.get("title"),
        "mb_artist": artist,
        "mb_first_release_date": p.get("first-release-date") or None,
        "mb_tags": json.dumps(tags, ensure_ascii=False) if tags else None,
        "mb_url_rels": json.dumps(rels, ensure_ascii=False) if rels else None,
        "discogs_url": rels.get("discogs"),
        "wikidata_url": rels.get("wikidata"),
        "vgmdb_url": rels.get("vgmdb"),
        "allmusic_url": rels.get("allmusic"),
    }


_EXT_COLS = (
    "asset_id", "spotify_track_id", "isrc",
    "deezer_track_id", "deezer_url", "deezer_rank", "deezer_bpm", "deezer_release_date",
    "deezer_album", "deezer_artist", "deezer_genres", "platform_links",
    "spotify_popularity", "lastfm_listeners", "lastfm_playcount", "lastfm_url",
    "mb_recording_mbid", "mb_title", "mb_artist", "mb_first_release_date", "mb_tags",
    "mb_url_rels", "discogs_url", "wikidata_url", "vgmdb_url", "allmusic_url",
    "external_state", "detail", "fetched_at", "extractor_version",
)


def upsert_external_meta(conn: sqlite3.Connection, row: dict) -> None:
    """Upsert one ``asset_external_meta`` row (known columns only; idempotent)."""
    placeholders = ",".join("?" * len(_EXT_COLS))
    conn.execute(
        f"INSERT OR REPLACE INTO asset_external_meta ({','.join(_EXT_COLS)}) "
        f"VALUES ({placeholders})",
        [row.get(c) for c in _EXT_COLS],
    )
    conn.commit()


def _stored_track_id(conn: sqlite3.Connection, asset_id: str) -> str | None:
    row = conn.execute(
        "SELECT spotify_track_metadata FROM asset_music_meta WHERE asset_id=?",
        (asset_id,)).fetchone()
    return spotify_track_id(row[0]) if row else None


def _stored_meta(conn: sqlite3.Connection, asset_id: str) -> tuple[str | None, str | None, str | None]:
    """``(spotify_track_id, title, display_artist)`` from ``asset_music_meta`` for an asset."""
    row = conn.execute(
        "SELECT spotify_track_metadata, title, display_artist FROM asset_music_meta "
        "WHERE asset_id=?", (asset_id,)).fetchone()
    if not row:
        return None, None, None
    return spotify_track_id(row[0]), row[1], row[2]


def enrich_asset(
    conn: sqlite3.Connection,
    asset_id: str,
    *,
    contact: str | None = None,
    mb_sleep_s: float = MB_RATE_LIMIT_S,
    spotify_token: str | None = None,
    lastfm_key: str | None = None,
) -> dict:
    """Resolve one asset's cross-platform stats + links; write its row, return it.

    Free chain: Spotify id → Odesli (other-platform links + Deezer id) → Deezer (ISRC,
    album, release, rank, genres) → MusicBrainz **by ISRC** (genres/tags + Discogs/Wikidata/
    VGMdb/AllMusic) → Last.fm (global listeners/playcount, by artist+track). Degrades
    field-by-field; *spotify_token* (Premium) adds ``popularity``; *lastfm_key* adds the
    Last.fm figures. Returns the written row dict; raises only if there is no Spotify track
    id to start from.
    """
    track_id, title, display_artist = _stored_meta(conn, asset_id)
    row: dict = {c: None for c in _EXT_COLS}
    row.update({
        "asset_id": asset_id,
        "spotify_track_id": track_id,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "extractor_version": EXTRACTOR_VERSION,
        "external_state": "unresolved",
    })

    if not track_id:
        row["detail"] = "no Spotify track id in asset_music_meta"
        upsert_external_meta(conn, row)
        return row

    notes: list[str] = []

    deezer_id = None
    try:
        od = parse_odesli(odesli_links(track_id))
        deezer_id = od.get("deezer_track_id")
        row["platform_links"] = od.get("platform_links")
        notes.append("odesli ok" if deezer_id else "odesli ok (no deezer)")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"odesli failed ({type(exc).__name__})")

    if deezer_id:
        try:
            dz = parse_deezer_track(deezer_track(deezer_id))
            if dz:
                album_id = dz.pop("_album_id", None)
                row.update(dz)
                row["deezer_track_id"] = deezer_id
                row["deezer_url"] = f"https://www.deezer.com/track/{deezer_id}"
                if album_id:
                    try:
                        genres = deezer_album_genres(deezer_album(album_id))
                        row["deezer_genres"] = json.dumps(genres, ensure_ascii=False) \
                            if genres else None
                    except Exception:  # noqa: BLE001
                        pass
                notes.append("deezer ok" if row.get("isrc") else "deezer ok (no isrc)")
            else:
                notes.append("deezer: no data")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"deezer failed ({type(exc).__name__})")

    if spotify_token:
        try:
            row["spotify_popularity"] = (spotify_track(track_id, spotify_token) or {}).get(
                "popularity")
            notes.append("spotify popularity ok")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"spotify failed ({type(exc).__name__})")

    isrc = row.get("isrc")
    if isrc:
        if mb_sleep_s:
            time.sleep(mb_sleep_s)
        try:
            mbid = _first_recording_mbid(musicbrainz_by_isrc(isrc, contact=contact))
            if mbid:
                if mb_sleep_s:
                    time.sleep(mb_sleep_s)
                row.update(parse_mb_recording(musicbrainz_recording(mbid, contact=contact)))
                notes.append("musicbrainz ok")
            else:
                notes.append("isrc not in musicbrainz")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"musicbrainz failed ({type(exc).__name__})")

    if lastfm_key:
        track_name = row.get("mb_title") or title
        artist_name = row.get("mb_artist") or row.get("deezer_artist") or display_artist
        if artist_name and track_name:
            try:
                lf = parse_lastfm(lastfm_track(artist_name, track_name, lastfm_key))
                row.update(lf)
                notes.append("lastfm ok" if lf.get("lastfm_listeners") is not None
                             else "lastfm: not found")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"lastfm failed ({type(exc).__name__})")
        else:
            notes.append("lastfm: no artist/title to query")

    if row.get("mb_recording_mbid"):
        row["external_state"] = "resolved"
    elif (row.get("isrc") or row.get("deezer_track_id") or row.get("platform_links")
          or row.get("spotify_popularity") is not None
          or row.get("lastfm_listeners") is not None):
        row["external_state"] = "partial"
    row["detail"] = "; ".join(notes)
    upsert_external_meta(conn, row)
    return row


def discover_assets(conn: sqlite3.Connection) -> list[str]:
    """Assets that have a Spotify track id worth resolving (the analysis units here)."""
    rows = conn.execute(
        "SELECT asset_id, spotify_track_metadata FROM asset_music_meta "
        "WHERE spotify_track_metadata IS NOT NULL ORDER BY asset_id").fetchall()
    return [a for a, raw in rows if spotify_track_id(raw)]


def run(
    conn: sqlite3.Connection,
    cfg: AvConfig | None = None,
    *,
    limit: int | None = None,
    include_failed: bool = False,
    contact: str | None = None,
    mb_sleep_s: float = MB_RATE_LIMIT_S,
    odesli_sleep_s: float = ODESLI_RATE_LIMIT_S,
    with_spotify: bool = False,
    lastfm_key: str | None = None,
    progress: bool = False,
) -> dict[str, int]:
    """Enrich all pending assets with external stats/links; return final state counts.

    The default chain needs **no credentials**. A ``LASTFM_API_KEY`` (env or *lastfm_key*)
    adds global listeners/playcount; ``with_spotify=True`` additionally fetches Spotify
    ``popularity`` (needs Premium creds, else skipped with a note). Odesli's free tier is
    rate-limited, so assets are paced *odesli_sleep_s* apart.
    """
    cfg = cfg or default_config()

    if lastfm_key is None:
        from dotenv import load_dotenv

        load_dotenv()
        lastfm_key = os.environ.get("LASTFM_API_KEY")
    if progress and not lastfm_key:
        print("  [enrich-meta] Last.fm listeners disabled: LASTFM_API_KEY not set", flush=True)

    spotify_token = None
    if with_spotify:
        try:
            spotify_token = get_spotify_token()
        except Exception as exc:  # noqa: BLE001
            if progress:
                print(f"  [enrich-meta] Spotify popularity disabled: {exc}", flush=True)

    state.init_state(conn, state.EXTERNAL_STATE, discover_assets(conn))
    todo = state.pending_keys(
        conn, state.EXTERNAL_STATE, include_failed=include_failed, limit=limit)
    total = len(todo)
    for i, asset_id in enumerate(todo, 1):
        if i > 1 and odesli_sleep_s:
            time.sleep(odesli_sleep_s)
        try:
            row = enrich_asset(conn, asset_id, contact=contact, mb_sleep_s=mb_sleep_s,
                               spotify_token=spotify_token, lastfm_key=lastfm_key)
            ext = row.get("external_state") or "unresolved"
            status = "failed" if ext == "unresolved" else "done"
            state.set_status(conn, state.EXTERNAL_STATE, asset_id, status,
                             detail=row.get("detail"))
            note = f"{ext} ({row.get('detail')})"
        except Exception as exc:  # noqa: BLE001
            state.set_status(conn, state.EXTERNAL_STATE, asset_id, "failed",
                             detail=f"{type(exc).__name__}: {exc}")
            note = f"FAILED ({type(exc).__name__})"
        if progress:
            print(f"  [{i}/{total}] {asset_id}: {note}", flush=True)
    return state.status_counts(conn, state.EXTERNAL_STATE)
