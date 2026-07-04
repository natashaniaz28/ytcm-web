"""
Per-asset metadata report — ``nami-av assetreport``.

A standalone, self-contained HTML + CSV that surfaces the rich canonical-audio metadata
fetched per ``asset_id`` (``asset_music_meta``) joined with our measured acoustics
(``asset_acoustics``), our ``songs.yaml`` grouping (``track_variants`` / ``songs``), and
reach (NAMI's play→view→like via :mod:`nami_av.variants`).

This is valuable on its own — it pairs Instagram's *real* title/artist/Spotify/lyrics/hook
with our labels (a direct audit of the ``songs.yaml`` grouping) and with the per-asset
acoustic profile and within-song impact. Like the acoustic report it **gates**: with no
``asset_music_meta`` rows it renders a graceful placeholder. The cover art is embedded as
base64 so the HTML is portable.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pandas as pd

from .config import AvConfig, default_config

CSV_COLS = [
    "asset_id", "song_id", "variant_label", "title", "display_artist",
    "song_title", "song_artist", "audio_source", "duration_real_s",
    "tempo", "tempo_confidence", "est_key", "est_key_confidence",
    "est_key_alt", "key_agreement",
    "spectral_centroid", "loudness_lufs", "highlight_start_s", "is_explicit",
    "licensed_music_subtype", "has_lyrics", "n_reels", "median_impact",
    "reach_rank", "ratio_to_song_median", "spotify_url",
    "isrc", "deezer_rank", "deezer_bpm", "deezer_release_date", "deezer_album",
    "deezer_genres", "platform_links", "spotify_popularity",
    "lastfm_listeners", "lastfm_playcount",
    "mb_recording_mbid", "mb_first_release_date", "mb_tags",
    "discogs_url", "wikidata_url", "vgmdb_url", "allmusic_url", "external_state",
]


def _esc(v) -> str:
    """Minimal HTML escape for text cells."""
    if v is None:
        return "—"
    s = str(v)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _num(v, nd: int = 1) -> str:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "—"
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def _key_fact(r) -> str:
    """The key estimate, with the second opinion shown when it doesn't fully agree."""
    primary = f'{_esc(r.get("est_key"))} (conf {_num(r.get("est_key_confidence"), 2)})'
    agreement = r.get("key_agreement")
    alt = r.get("est_key_alt")
    if alt is None or pd.isna(agreement) or agreement is None:
        return primary
    if agreement >= 1.0:
        return primary + ' <span class="muted">— the Krumhansl-Schmuckler method agrees</span>'
    note = "near miss" if agreement >= 0.5 else "disagrees"
    return primary + (f' <span class="muted">— the Krumhansl-Schmuckler method says '
                      f'{_esc(alt)} ({note})</span>')


def _first_highlight_s(raw) -> float | None:
    """First hook offset (seconds) from the json ``highlight_start_ms`` list."""
    if not raw:
        return None
    try:
        arr = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(arr, (list, tuple)) and arr:
            return round(float(arr[0]) / 1000.0, 2)
    except (TypeError, ValueError):
        pass
    return None


def _spotify_link(raw) -> str | None:
    """Best-effort open.spotify.com URL from the stored ``spotify_track_metadata`` json."""
    if not raw:
        return None
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    tid = (d.get("spotify_track_id") or d.get("spotify_id")
           or d.get("track_id") or d.get("id"))
    if tid:
        return f"https://open.spotify.com/track/{tid}"
    for k in ("spotify_listen_uri", "spotify_uri", "uri", "external_url", "url", "spotify_url"):
        v = d.get(k)
        if isinstance(v, str) and v:
            if v.startswith("spotify:track:"):
                return "https://open.spotify.com/track/" + v.split(":")[-1]
            return v
    return None


def _cover_img(cover_path) -> str:
    """An embedded <img> for the cover, or empty string if the file is missing."""
    if not cover_path:
        return ""
    p = Path(cover_path)
    if not (p.exists() and p.stat().st_size > 0):
        return ""
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return (f'<img class="cover" src="data:{mime};base64,{data}" '
            f'alt="cover" style="width:120px;height:120px;object-fit:cover;border-radius:6px"/>')


def _lyrics_block(raw) -> str:
    if not raw:
        return ""
    try:
        val = json.loads(raw) if isinstance(raw, str) else raw
        text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False, indent=1)
    except (TypeError, ValueError):
        text = str(raw)
    return f"<details><summary>lyrics</summary><pre>{_esc(text)}</pre></details>"


def _tags_text(raw) -> str | None:
    """Comma-joined MusicBrainz genres/tags from the stored json list."""
    if not raw:
        return None
    try:
        arr = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if isinstance(arr, (list, tuple)) and arr:
        return ", ".join(str(t) for t in arr)
    return None


_LINK_FIELDS = [
    ("_mb_url", "MusicBrainz"),
    ("discogs_url", "Discogs"),
    ("vgmdb_url", "VGMdb"),
    ("allmusic_url", "AllMusic"),
    ("wikidata_url", "Wikidata"),
    ("deezer_url", "Deezer"),
]

_PLATFORM_LABELS = {
    "apple_music": "Apple Music", "youtube": "YouTube", "youtube_music": "YouTube Music",
    "deezer": "Deezer", "tidal": "Tidal", "amazon_music": "Amazon Music",
    "soundcloud": "SoundCloud", "pandora": "Pandora",
}


def _links_html(r) -> str:
    """A · -joined row of database links for whatever resolved (empty string if none)."""
    mbid = r.get("mb_recording_mbid")
    r = dict(r)
    if mbid and not (isinstance(mbid, float) and pd.isna(mbid)):
        r["_mb_url"] = f"https://musicbrainz.org/recording/{mbid}"
    links = []
    for field, label in _LINK_FIELDS:
        url = r.get(field)
        if isinstance(url, str) and url:
            links.append(f'<a href="{_esc(url)}">{label}</a>')
    return (" · ".join(links)) if links else ""


def _platform_links_html(raw) -> str:
    """A · -joined row of streaming-platform links from the stored Odesli json."""
    if not raw or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return ""
    if not isinstance(d, dict):
        return ""
    links = [f'<a href="{_esc(u)}">{_PLATFORM_LABELS.get(k, k)}</a>'
             for k, u in d.items() if isinstance(u, str) and u]
    return " · ".join(links)


def _has(v) -> bool:
    return v is not None and not (isinstance(v, float) and pd.isna(v))


def _external_facts(r) -> list[tuple[str, str]]:
    """The cross-platform stat rows, only those that resolved (keeps the card honest)."""
    facts: list[tuple[str, str]] = []
    listeners = r.get("lastfm_listeners")
    if _has(listeners):
        plays = r.get("lastfm_playcount")
        url = r.get("lastfm_url")
        plays_txt = f" · {int(plays):,} plays" if _has(plays) else ""
        val = f"{int(listeners):,} listeners{plays_txt} (global, Last.fm)"
        if _has(url):
            val = f'<a href="{_esc(url)}">{val}</a>'
        facts.append(("listeners", val))
    pop = r.get("spotify_popularity")
    if _has(pop):
        facts.append(("Spotify popularity", f"{int(pop)} / 100"))
    rank = r.get("deezer_rank")
    if _has(rank):
        facts.append(("Deezer rank", f"{int(rank):,} (play-count proxy; higher = more played)"))
    rel = r.get("deezer_release_date") or r.get("mb_first_release_date")
    if _has(rel):
        album = r.get("deezer_album")
        extra = f' — {_esc(album)}' if _has(album) else ""
        facts.append(("release", f"{_esc(rel)}{extra}"))
    isrc = r.get("isrc")
    if _has(isrc):
        facts.append(("ISRC", _esc(isrc)))
    tags = _tags_text(r.get("mb_tags")) or _tags_text(r.get("deezer_genres"))
    if tags:
        src = "MusicBrainz" if _tags_text(r.get("mb_tags")) else "Deezer"
        facts.append((f"genres/tags ({src})", _esc(tags)))
    links = _links_html(r)
    if links:
        facts.append(("databases", links))
    plinks = _platform_links_html(r.get("platform_links"))
    if plinks:
        facts.append(("also on", plinks))
    return facts


def load_asset_rows(conn: sqlite3.Connection) -> pd.DataFrame:
    """One row per asset: canonical metadata × acoustics × grouping × reach (sorted by reach)."""
    meta = pd.read_sql("SELECT * FROM asset_music_meta", conn)
    if meta.empty:
        return meta

    ac = pd.read_sql(
        "SELECT asset_id, tempo, tempo_confidence, est_key, est_key_confidence, "
        "est_key_alt, key_agreement, "
        "spectral_centroid, loudness_lufs, duration AS acoustic_duration FROM asset_acoustics",
        conn)
    tv = pd.read_sql(
        "SELECT tv.asset_id, tv.song_id, tv.variant_label, s.title AS song_title, "
        "s.artist AS song_artist FROM track_variants tv "
        "LEFT JOIN songs s ON s.song_id = tv.song_id", conn)

    df = meta.merge(ac, on="asset_id", how="left").merge(tv, on="asset_id", how="left")

    try:
        ext = pd.read_sql(
            "SELECT asset_id, isrc, deezer_rank, deezer_bpm, deezer_release_date, "
            "deezer_album, deezer_genres, platform_links, spotify_popularity, "
            "lastfm_listeners, lastfm_playcount, lastfm_url, "
            "mb_recording_mbid, mb_title, mb_artist, mb_first_release_date, mb_tags, "
            "mb_url_rels, discogs_url, wikidata_url, vgmdb_url, allmusic_url, external_state "
            "FROM asset_external_meta", conn)
        df = df.merge(ext, on="asset_id", how="left")
    except Exception:  # noqa: BLE001
        pass

    from . import variants
    try:
        imp = variants.load_impact(conn)
        df = df.merge(imp, on="asset_id", how="left")
    except Exception:  # noqa: BLE001
        df["n_reels"] = None
        df["median_impact"] = None
    try:
        feats = variants.load_variant_features(conn)
        reach = variants.variant_reach(feats, variants.load_impact(conn))
        df = df.merge(reach[["asset_id", "reach_rank", "ratio_to_song_median"]],
                      on="asset_id", how="left")
    except Exception:  # noqa: BLE001
        df["reach_rank"] = None
        df["ratio_to_song_median"] = None

    df["highlight_start_s"] = df.get("highlight_start_ms").map(_first_highlight_s) \
        if "highlight_start_ms" in df.columns else None
    df["spotify_url"] = df.get("spotify_track_metadata").map(_spotify_link) \
        if "spotify_track_metadata" in df.columns else None

    sort_col = "median_impact" if "median_impact" in df.columns else "asset_id"
    return df.sort_values(sort_col, ascending=False, na_position="last").reset_index(drop=True)


_STYLE = (
    "body{font-family:sans-serif;margin:2rem;max-width:1000px}"
    "h1{border-bottom:2px solid #333}"
    ".card{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0;display:flex;gap:1rem}"
    ".card .body{flex:1}"
    ".badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:.78rem;color:#fff}"
    ".canonical{background:#2e7d32}.preview{background:#ef6c00}.reel_consensus{background:#757575}"
    ".unavailable{background:#b71c1c}"
    "table{border-collapse:collapse;margin:.4rem 0}td,th{padding:2px 8px;border-bottom:1px solid #eee;"
    "text-align:left;font-size:.9rem}.muted{color:#666}pre{white-space:pre-wrap;font-size:.8rem}"
    "details{margin-top:.4rem}"
    ".ext{margin-top:.6rem;padding-top:.4rem;border-top:1px dashed #ddd}"
    ".ext-h{font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}"
    ".note{background:#f6f8fa;border:1px solid #e1e4e8;border-radius:6px;padding:.6rem .8rem;"
    "font-size:.82rem;color:#444;margin:.6rem 0}"
)


def _badge(source) -> str:
    s = source or "unavailable"
    cls = s if s in ("canonical", "preview", "reel_consensus", "unavailable") else "unavailable"
    return f'<span class="badge {cls}">{_esc(s)}</span>'


def _card(r) -> str:
    title = r.get("title") or r.get("song_title")
    artist = r.get("display_artist") or r.get("song_artist")
    spotify = r.get("spotify_url")
    spotify_html = (f' · <a href="{_esc(spotify)}">Spotify</a>') if spotify else ""
    rank = r.get("reach_rank")
    ratio = r.get("ratio_to_song_median")
    parts = []
    if rank is not None and not pd.isna(rank):
        parts.append(f"rank {int(rank)} in song")
    if ratio is not None and not pd.isna(ratio):
        parts.append(f"{_num(ratio, 2)}× song median")
    reach_extra = (" · " + " · ".join(parts)) if parts else ""

    facts = [
        ("label", f'{_esc(r.get("song_id"))} / {_esc(r.get("variant_label"))}'),
        ("audio source", _badge(r.get("audio_source"))),
        ("duration", f'{_num(r.get("duration_real_s"))} s'),
        ("tempo", f'{_num(r.get("tempo"))} BPM (conf {_num(r.get("tempo_confidence"), 2)})'),
        ("key", _key_fact(r)),
        ("brightness (centroid)", f'{_num(r.get("spectral_centroid"), 0)} Hz'),
        ("loudness", f'{_num(r.get("loudness_lufs"))} LUFS'),
        ("hook starts at", f'{_num(r.get("highlight_start_s"), 1)} s'),
        ("explicit", "yes" if r.get("is_explicit") else "no"),
        ("license", _esc(r.get("licensed_music_subtype"))),
        ("reach", f'{_esc(r.get("n_reels"))} reels · median impact '
                  f'{_num(r.get("median_impact"), 0)}{reach_extra}'),
        ("audio_asset_id", _esc(r.get("audio_asset_id"))),
    ]
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in facts)
    head = (f'<h3>{_esc(title)} <span class="muted">— {_esc(artist)}{spotify_html}</span></h3>')

    ext_facts = _external_facts(r)
    ext_html = ""
    if ext_facts:
        ext_rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in ext_facts)
        st = r.get("external_state")
        st_note = f' <span class="muted">({_esc(st)})</span>' if st and not (
            isinstance(st, float) and pd.isna(st)) else ""
        ext_html = (f'<div class="ext"><div class="muted ext-h">cross-platform{st_note}</div>'
                    f'<table>{ext_rows}</table></div>')

    return (f'<div class="card">{_cover_img(r.get("cover_path"))}'
            f'<div class="body">{head}<table>{rows}</table>{ext_html}'
            f'{_lyrics_block(r.get("lyrics"))}</div></div>')


def _page(body: str) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<title>NAMI — per-asset audio report</title>"
            "<base target='_blank'>"
            f"<style>{_STYLE}</style></head><body>"
            "<h1>NAMI — per-asset audio report</h1>"
            "<p class='muted'>Instagram's canonical-audio metadata × our measured acoustics × "
            "reach, one card per audio asset (sorted by reach).</p>"
            "<div class='note'><b>About the cross-platform block.</b> Instagram gives us each "
            "track's <b>Spotify id</b>; from it the <code>enrich-meta</code> stage follows a "
            "chain of free databases — <b>Odesli</b> (the same recording on Apple Music / "
            "YouTube / Deezer / Tidal / …), then <b>Deezer</b> for the track's <b>ISRC</b> (the "
            "international, unique-per-recording code) plus release/rank/genres, then "
            "<b>MusicBrainz</b> looked up <i>by that ISRC</i> so the Discogs / Wikidata / VGMdb / "
            "AllMusic links and tags are an <b>exact</b> match, not an artist+title guess, and "
            "<b>Last.fm</b> for global listeners/playcount (a free, cross-artist popularity "
            "figure). Where a block is missing, that recording simply isn't indexed (common for "
            "older Japanese releases) — it is left blank, not faked. (Spotify's own popularity "
            "is shown only if enriched with Premium credentials; its deprecated audio-features "
            "are never used — this report's tempo/key/loudness are NAMI's own measurements.)</div>"
            f"{body}</body></html>")


def build(conn: sqlite3.Connection, cfg: AvConfig | None = None,
          out_path: str | Path | None = None) -> Path:
    """Write ``asset_report.html`` and return its path; the CSV table goes under ``data/``."""
    cfg = cfg or default_config()
    out = Path(out_path) if out_path else cfg.output_dir / "asset_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = cfg.data_dir / "asset_report.csv"

    df = load_asset_rows(conn)
    if df.empty:
        pd.DataFrame(columns=CSV_COLS).to_csv(csv_path, index=False)
        out.write_text(_page(
            "<section><p><em>No canonical-audio metadata yet — run extract-acoustic "
            "(which fetches it) first.</em></p></section>"), encoding="utf-8")
        return out

    df.reindex(columns=CSV_COLS).to_csv(csv_path, index=False)
    cards = "\n".join(_card(r) for _, r in df.iterrows())
    out.write_text(_page(cards), encoding="utf-8")
    return out
