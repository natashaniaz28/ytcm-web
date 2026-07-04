from __future__ import annotations

import json
import os
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

from .config import AvConfig, default_config

PX_PER_S = 14.0
MAX_W = 1000
BAR_H = 54
LINK_CAP = 200
CONSENSUS_BIN_S = 0.5
ENV_BINS = 240
WAVE_FILL = "#c9d3dd"
CUT_COLOR = "#cc2222"
BEAT_COLOR = "#f59e0b"
SOFT_COLOR = "#2563eb"


def _esc(v) -> str:
    if v is None:
        return ""
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _reel_link(cfg: AvConfig, reel_pk: str) -> str:
    target = cfg.reels_dir / f"{reel_pk}.mp4"
    try:
        return os.path.relpath(target, cfg.output_dir)
    except ValueError:
        return str(target)


def asset_audio(conn, cfg: AvConfig, asset_id: str, cache: dict):
    """``(y, sr, beat_times)`` for the asset's canonical audio, or ``None`` if unavailable.

    Loaded live from the local ``.m4a`` (same source the usage-heatmap panels use), cached
    per asset so an asset with several groups is only decoded once. Any failure — missing
    file, decode error, no librosa — degrades silently to ``None`` (the strip then draws
    without a waveform/beats), so the report never breaks on audio.
    """
    if asset_id in cache:
        return cache[asset_id]
    res = None
    try:
        import librosa

        from . import alignment
        from .audio import DEFAULT_SR

        path = alignment._canonical_audio_path(conn, asset_id, cfg)
        if path is not None:
            y, sr = librosa.load(str(path), sr=DEFAULT_SR, mono=True)
            _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beats = librosa.frames_to_time(beat_frames, sr=sr).tolist()
            res = (y, sr, beats)
    except Exception:  # noqa: BLE001
        res = None
    cache[asset_id] = res
    return res


def segment_envelope(y, sr: int, t0: float, dur: float, *, n: int = ENV_BINS) -> list[float] | None:
    """Per-bin peak amplitude (0..1) of ``y`` over the window ``[t0, t0+dur]`` seconds."""
    import numpy as np

    a = max(0, int(t0 * sr))
    b = min(len(y), int((t0 + dur) * sr))
    seg = y[a:b]
    if seg.size < 2:
        return None
    edges = np.linspace(0, seg.size, n + 1).astype(int)
    env = np.array([np.abs(seg[edges[i]:edges[i + 1]]).max() if edges[i + 1] > edges[i] else 0.0
                    for i in range(n)])
    peak = float(env.max())
    if peak <= 0:
        return None
    return (env / peak).tolist()


def consensus_cuts(member_cuts: list[list[float]], size: int,
                   *, bin_s: float = CONSENSUS_BIN_S) -> list[float]:
    """The group's shared cut positions: bins hit by ≥ half the members, each a median.

    Members are near-identical by construction, so this collapses their (slightly jittered)
    cut times into one representative set to draw.
    """
    pooled = [t for cuts in member_cuts for t in cuts]
    if not pooled:
        return []
    buckets: dict[int, list[float]] = defaultdict(list)
    for t in pooled:
        buckets[round(t / bin_s)].append(t)
    need = max(2, (size + 1) // 2)
    cons = [statistics.median(ts) for ts in buckets.values() if len(ts) >= need]
    return sorted(cons)


def _timeline_svg(duration: float, cuts: list[float], *,
                  beats: list[float] | None = None,
                  envelope: list[float] | None = None,
                  soft: list[float] | None = None) -> str:
    """
    One strip: the segment's waveform (if any), full-height red cuts, short orange beats.
    """
    if duration <= 0:
        duration = max((cuts[-1] if cuts else 0.0), 1.0)
    w = max(60.0, min(float(MAX_W), duration * PX_PER_S))

    def x(t: float) -> float:
        return round(min(max(t, 0.0), duration) / duration * w, 1)

    mid = BAR_H / 2
    body = []
    if envelope:
        amp = mid - 4.0
        n = len(envelope)
        top = [f"{round(i / (n - 1) * w, 1) if n > 1 else 0},{round(mid - v * amp, 1)}"
               for i, v in enumerate(envelope)]
        bot = [f"{round(i / (n - 1) * w, 1) if n > 1 else 0},{round(mid + v * amp, 1)}"
               for i, v in reversed(list(enumerate(envelope)))]
        body.append(f'<polygon points="{" ".join(top + bot)}" fill="{WAVE_FILL}"/>')
    body.append(f'<line x1="0" y1="{mid}" x2="{w:.1f}" y2="{mid}" '
                f'stroke="#9aa7b3" stroke-width="0.6"/>')
    for b in (beats or []):
        xx = x(b)
        body.append(f'<line x1="{xx}" y1="{BAR_H - 11}" x2="{xx}" y2="{BAR_H}" '
                    f'stroke="{BEAT_COLOR}" stroke-width="1"/>')
    for t in (soft or []):
        xx = x(t)
        body.append(f'<line x1="{xx}" y1="0" x2="{xx}" y2="{BAR_H}" '
                    f'stroke="{SOFT_COLOR}" stroke-width="1.2" stroke-dasharray="3,3"/>')
    for t in cuts:
        xx = x(t)
        body.append(f'<line x1="{xx}" y1="0" x2="{xx}" y2="{BAR_H}" '
                    f'stroke="{CUT_COLOR}" stroke-width="1.4"/>')
    svg = (f'<svg width="{w:.1f}" height="{BAR_H}" '
           f'style="max-width:100%;height:auto">{"".join(body)}</svg>')
    return svg + f'<div style="font-size:.7rem;color:#888">0s … {duration:.1f}s</div>'


def _asset_groups(conn, asset_id: str) -> dict:
    rows = conn.execute(
        "SELECT re.reel_pk, r.code, re.edit_cluster, re.cut_times, re.duration, "
        "ra.used_segment_start, re.soft_times "
        "FROM reel_edits re LEFT JOIN reels r ON r.reel_pk = re.reel_pk "
        "LEFT JOIN reel_acoustics ra ON ra.reel_pk = re.reel_pk "
        "WHERE re.asset_id=? AND re.edit_cluster IS NOT NULL AND re.edit_cluster >= 0 "
        "ORDER BY re.edit_cluster, re.reel_pk", (asset_id,)).fetchall()
    out: dict = defaultdict(list)
    for pk, code, cl, ct, dur, seg_start, st in rows:
        cuts = json.loads(ct) if ct else []
        soft = json.loads(st) if st else []
        out[int(cl)].append((pk, code, cuts, dur or 0.0, seg_start, soft))
    return out


def _links_block(cfg: AvConfig, members: list) -> str:
    links = []
    for pk, code, *_ in members[:LINK_CAP]:
        href = _esc(_reel_link(cfg, pk))
        links.append(f'<a href="{href}">{_esc(code or pk)}</a>')
    more = f" … and {len(members) - LINK_CAP} more" if len(members) > LINK_CAP else ""
    return (f"<details><summary>{len(members)} videos</summary>"
            f"<div style='font-size:.8rem;line-height:1.8'>{' · '.join(links)}{more}</div>"
            f"</details>")


def _group_block(cfg: AvConfig, label: str, members: list, audio=None) -> str:
    member_cuts = [m[2] for m in members]
    member_soft = [m[5] for m in members]
    durations = [m[3] for m in members if m[3]]
    duration = statistics.median(durations) if durations else 0.0
    n_cuts = [len(c) for c in member_cuts]
    med_cuts = statistics.median(n_cuts) if n_cuts else 0
    med_soft = statistics.median([len(s) for s in member_soft]) if member_soft else 0
    cons = consensus_cuts(member_cuts, len(members))
    cons_soft = consensus_cuts(member_soft, len(members))

    envelope = beats = None
    seg_starts = [m[4] for m in members if m[4] is not None]
    if audio is not None and seg_starts and duration > 0:
        y, sr, beat_times = audio
        seg_start = statistics.median(seg_starts)
        envelope = segment_envelope(y, sr, seg_start, duration)
        beats = [b - seg_start for b in beat_times if seg_start <= b <= seg_start + duration]

    head = f"<h4>{_esc(label)} — {len(members)} videos</h4>"
    soft_stat = f" · median {med_soft:.0f} soft" if med_soft else ""
    stats = (f"<div class='st'>median {med_cuts:.0f} cuts{soft_stat} · "
             f"~{duration:.1f}s long</div>")
    svg = _timeline_svg(duration, cons, beats=beats, envelope=envelope, soft=cons_soft)
    return (f"<div class='cl'>{head}{stats}{svg}{_links_block(cfg, members)}</div>")


def _assets_ordered(conn) -> list:
    """Assets that have edit data, grouped by song, **assets ascending by asset_id**.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT re.asset_id, tv.song_id, s.title, s.artist, amm.title
        FROM reel_edits re
        LEFT JOIN track_variants tv ON tv.asset_id = re.asset_id
        LEFT JOIN songs s ON s.song_id = tv.song_id
        LEFT JOIN asset_music_meta amm ON amm.asset_id = re.asset_id
        """
    ).fetchall()

    groups: dict = defaultdict(list)
    titles: dict = {}
    for asset_id, song_id, s_title, s_artist, a_title in rows:
        groups[song_id].append((asset_id, a_title))
        titles[song_id] = (s_title, s_artist)

    def song_key(song_id):
        s_title, _ = titles.get(song_id, (None, None))
        return (song_id is None, (s_title or song_id or "").lower())

    ordered = []
    for song_id in sorted(groups, key=song_key):
        s_title, s_artist = titles.get(song_id, (None, None))
        assets = sorted(groups[song_id], key=lambda a: a[0])
        ordered.append((song_id, s_title, s_artist, assets))
    return ordered


def _page(body: str) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<title>NAMI — near-identical edits</title>"
            "<style>body{font-family:sans-serif;margin:2rem;max-width:1100px}"
            "h1{border-bottom:2px solid #333}h2{border-bottom:1px solid #999;margin-top:2.2rem}"
            "h3{margin-top:1.4rem}h4{margin:1rem 0 .2rem;font-weight:normal}"
            ".cl{border-left:3px solid #eee;padding-left:.8rem;margin:.8rem 0}"
            ".st{font-size:.82rem;color:#333;margin:.1rem 0 .3rem}"
            "details{margin:.3rem 0 .6rem}summary{cursor:pointer;font-size:.85rem}"
            "a{color:#1565c0;text-decoration:none}</style></head><body>"
            "<h1>NAMI — near-identical edits</h1>"
            "<p>Per audio asset, the groups of reels that are <b>edited identically or nearly "
            "so</b> (same cuts at the same points of the song). Each strip is the videos' "
            "length on the song's timeline: the grey <b>waveform</b> is that segment's audio, "
            "<b style='color:#cc2222'>red lines</b> are the shared cut positions, "
            "<b style='color:#2563eb'>dashed blue lines</b> are gradual transitions "
            "(crossfades/zooms), and "
            "<b style='color:#f59e0b'>short orange ticks</b> are the beats — so you can see "
            "whether cuts land on- or off-beat. Expand a group to reach every member video on "
            "disk. Static / single-shot reels and one-offs are not shown. Grouped by song, "
            "assets ascending. <span style='color:#888'>(Beats/tempo are librosa estimates — "
            "indicative, not metronomic.)</span></p>"
            + body + "</body></html>")


def build_video_editing(conn: sqlite3.Connection, cfg: AvConfig | None = None,
                        out_path: str | Path | None = None, *, progress: bool = False) -> Path:
    """Write ``video_editing.html`` from ``reel_edits`` + each grouped asset's local audio."""
    cfg = cfg or default_config()
    out = Path(out_path) if out_path else cfg.output_dir / "video_editing.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    has = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reel_edits'"
                       ).fetchone()
    if not has or conn.execute("SELECT COUNT(*) FROM reel_edits").fetchone()[0] == 0:
        out.write_text(_page("<p><em>No edit data yet — run detect-edits / group-edits "
                             "first.</em></p>"), encoding="utf-8")
        return out

    ordered = _assets_ordered(conn)
    if progress:
        total = sum(len(a) for _, _, _, a in ordered)
        print(f"  video-editing: {total} assets", flush=True)

    audio_cache: dict = {}
    parts, done = [], 0
    for song_id, s_title, s_artist, assets in ordered:
        song_parts = []
        for aid, a_title in assets:
            done += 1
            groups = _asset_groups(conn, aid)
            if not groups:
                continue
            audio = asset_audio(conn, cfg, aid, audio_cache)
            label = _esc(a_title or aid)
            song_parts.append(f"<h3>{label} <span style='color:#888'>— {_esc(aid)}</span></h3>")
            for cl in sorted(groups):
                song_parts.append(_group_block(cfg, f"Group {cl}", groups[cl], audio))
            if progress:
                print(f"  [{done}] {aid} — {len(groups)} group(s)", flush=True)
        if song_parts:
            title = s_title or song_id or "(unknown song)"
            parts.append(f"<h2>{_esc(title)}"
                         + (f" <span style='color:#666'>— {_esc(s_artist)}</span>"
                            if s_artist else "")
                         + "</h2>")
            parts.extend(song_parts)

    body = "".join(parts) or "<p><em>No near-identical edit groups found.</em></p>"
    out.write_text(_page(body), encoding="utf-8")
    if progress:
        print(f"  video-editing: wrote {out}", flush=True)
    return out
