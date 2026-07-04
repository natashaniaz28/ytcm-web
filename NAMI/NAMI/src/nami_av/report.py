from __future__ import annotations

import base64
import sqlite3
from pathlib import Path

import pandas as pd

from .config import AvConfig, default_config


def _table_has_rows(conn: sqlite3.Connection, name: str) -> bool:
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return bool(exists) and conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] > 0


def _section(title: str, lead: str, body: str) -> str:
    return f"<section>\n <h2>{title}</h2>\n <p>{lead}</p>\n {body}\n</section>"


def _table_html(df: pd.DataFrame, max_rows: int = 50) -> str:
    if df is None or df.empty:
        return "<p><em>(no rows)</em></p>"
    return df.head(max_rows).to_html(index=False, border=0, na_rep="—")


def _img_b64(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'<img src="data:image/png;base64,{data}" style="max-width:100%"/>'


def _variant_section(conn, cfg: AvConfig) -> str | None:
    if not _table_has_rows(conn, "asset_acoustics"):
        return None
    from . import variants

    feats = variants.load_variant_features(conn)
    disp = variants.variant_dispersion(feats)
    reach = variants.variant_reach(feats, variants.load_impact(conn))
    if disp.empty and reach.empty:
        return None
    show_disp = ["song_id", "n_variants", "tempo_min", "tempo_max", "tempo_spread_ratio",
                 "n_distinct_keys", "centroid_range", "loudness_range"]
    show_reach = ["song_id", "variant_label", "n_reels", "median_impact",
                  "reach_rank", "ratio_to_song_median"]
    body = "<h3>Per-song spread — how varied the renderings are</h3>" + _table_html(
        disp[[c for c in show_disp if c in disp.columns]])
    body += "<h3>Reach per variant — within-song rank</h3>" + _table_html(
        reach[[c for c in show_reach if c in reach.columns]])
    p = cfg.figures_dir / "variant_reach.png"
    if p.exists() and p.stat().st_size > 0:
        body += f"<h3>Median reach per variant (within-song)</h3>{_img_b64(p)}"
    if not reach.empty:
        song_order = list(reach.groupby("song_id")["median_impact"].sum()
                          .sort_values(ascending=False).index)
    else:
        song_order = sorted(disp["song_id"]) if not disp.empty else []
    figs = ""
    for song_id in song_order:
        fp = cfg.figures_dir / f"variant_feature_space_{variants._safe_filename(song_id)}.png"
        if fp.exists() and fp.stat().st_size > 0:
            figs += _img_b64(fp)
    if figs:
        body += ("<h3>Variant transformation in acoustic feature space "
                 "(one scatter per song)</h3>" + figs)
    return _section("Variant comparison (baseline-free)",
                    "How a song's variants differ from each other acoustically, and how "
                    "their reach compares within the song — no 'original' is assumed.", body)


def _families_section(conn) -> str | None:
    rows = conn.execute(
        "SELECT category, COUNT(*) AS reels FROM annotations "
        "WHERE source='acoustic' AND dimension='sonic' GROUP BY category ORDER BY reels DESC"
    ).fetchall() if _table_has_rows(conn, "annotations") else []
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["sonic family", "reels"])
    return _section("Acoustic families",
                    "Coarse bright/warm × fast/slow family per asset (the bridge variable "
                    "for sound × image cross-tabs).", _table_html(df))


def _esc(v) -> str:
    if v is None:
        return ""
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _heatmap_assets_ordered(conn) -> list:
    """Assets grouped by song for the heatmaps file.

    Returns ``[(song_id, [asset_row, …]), …]`` ordered so a song's assets stay together,
    songs by total reel count (descending), and assets within a song by reel count
    (descending = most popular first). ``asset_row`` =
    (asset_id, song_id, song_title, song_artist, variant_label, asset_title, n_reels).
    Assets with no song land in a trailing group.
    """
    from collections import defaultdict

    rows = conn.execute(
        """
        SELECT ra.asset_id, tv.song_id, s.title, s.artist, tv.variant_label, amm.title,
               (SELECT COUNT(*) FROM reels r WHERE r.asset_id = ra.asset_id) AS n_reels
        FROM (SELECT DISTINCT asset_id FROM reel_acoustics WHERE asset_id IS NOT NULL) ra
        LEFT JOIN track_variants tv ON tv.asset_id = ra.asset_id
        LEFT JOIN songs s ON s.song_id = tv.song_id
        LEFT JOIN asset_music_meta amm ON amm.asset_id = ra.asset_id
        """
    ).fetchall()

    groups: dict = defaultdict(list)
    for r in rows:
        groups[r[1]].append(r)

    def song_total(g):
        return sum((x[6] or 0) for x in g)

    ordered = sorted(groups.items(),
                     key=lambda kv: (kv[0] is None, -song_total(kv[1]), kv[0] or ""))
    return [(song_id, sorted(g, key=lambda x: (-(x[6] or 0), x[0]))) for song_id, g in ordered]


def _heatmaps_page(body: str) -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<title>NAMI — usage heatmaps + acoustic panels</title>"
            "<style>body{font-family:sans-serif;margin:2rem;max-width:1100px}"
            "h1{border-bottom:2px solid #333}h2{border-bottom:1px solid #999;margin-top:2.2rem}"
            "h4{margin:1.1rem 0 .25rem;font-weight:normal}img{max-width:100%}</style>"
            "</head><body>"
            "<h1>NAMI — segment-usage heatmaps + acoustic panels</h1>"
            "<p>Per audio asset, on one shared time axis: which part of the track the corpus "
            "uses (heat strip), then waveform, spectrogram, loudness and tonnetz. Grouped by "
            "song; assets ordered by descending popularity (reel count).</p>"
            + body + "</body></html>")


def _panel_caption(info: dict) -> str:
    """The per-figure caption: Y-axis meanings + boundaries, then the marker-colour legend."""
    hook = info.get("hook_s")
    hook_txt = f"{hook:.1f}s" if hook is not None else "not provided"
    refrain_txt = (f"{info.get('n_refrains', 0)}, fuzzy lyric-repeat detection, experimental"
                   if info.get("has_lyrics") else "no synced lyrics")
    return (
        "<div style='font-size:.85rem;color:#333;margin:.15rem 0 1.3rem;line-height:1.5'>"
        "<b>Y axes (top→bottom):</b> "
        f"<b>1 segment usage</b> — colour = #reels using that moment (0–{info['heat_max']:.0f}); "
        f"<b>2 waveform</b> — amplitude [{info['wave_min']:.2f}, {info['wave_max']:.2f}]; "
        f"<b>3 spectrogram</b> — log frequency 0–{info['nyquist']:.0f} Hz, "
        f"colour = magnitude {info['spec_db_lo']:.0f} to {info['spec_db_hi']:.0f} dB; "
        f"<b>4 loudness</b> — RMS [{info['loud_min']:.1f}, {info['loud_max']:.1f}] dB; "
        "<b>5 tonnetz</b> — 6 tonal-centroid dimensions (rows), values [−1, 1], "
        "colour blue→red.<br>"
        "<b>Vertical lines:</b> "
        f"<span style='color:#d40000'>▮ hook start</span> ({hook_txt}, on waveform) · "
        f"<span style='color:#0090a8'>▮ beats</span> ({info['n_beats']}, librosa beat_track, "
        "on spectrogram) · "
        f"<span style='color:#1faa00'>▮ onsets</span> ({info['n_onsets']}, librosa "
        "onset_detect, on loudness). "
        "<span style='color:#0090a8'>┄ dashed cyan</span> (heat strip) — structural segment "
        "boundaries (approx. section changes, from MFCC segmentation). "
        f"<span style='color:#c000c0'>▮ refrain starts</span> ({refrain_txt}, on tonnetz)."
        "</div>"
    )


def build_usage_heatmaps(conn: sqlite3.Connection, cfg: AvConfig | None = None,
                         out_path: str | Path | None = None, *, progress: bool = False) -> Path:
    """Write ``usage_heatmaps.html`` — the per-asset heat strip + acoustic panels, grouped
    by song and ordered by descending popularity. Self-contained (figures base64-embedded).

    The per-asset figure (load audio → STFT spectrogram, beats, onsets, tonnetz, refrain
    detection) is the heavy part; with *progress* it prints a line per asset.
    """
    cfg = cfg or default_config()
    out = Path(out_path) if out_path else cfg.output_dir / "usage_heatmaps.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    if not _table_has_rows(conn, "reel_acoustics"):
        out.write_text(_heatmaps_page(
            "<p><em>No alignment data yet — run align first.</em></p>"), encoding="utf-8")
        return out

    from . import assetfigures
    seg_dir = cfg.output_dir / "segments"
    groups = _heatmap_assets_ordered(conn)
    total = sum(len(assets) for _, assets in groups)
    if progress:
        print(f"  usage-heatmaps: building {total} per-asset figures "
              f"(loads + analyses each track's audio)…", flush=True)

    parts = []
    done = 0
    for song_id, assets in groups:
        s_title = assets[0][2] or song_id or "(unknown song)"
        s_artist = assets[0][3]
        header = _esc(s_title) + (f" <span style='color:#666'>— {_esc(s_artist)}</span>"
                                  if s_artist else "")
        parts.append(f"<h2>{header}</h2>")
        for aid, _sid, _st, _sa, variant_label, a_title, n_reels in assets:
            done += 1
            if progress:
                print(f"  [{done}/{total}] {aid} — {(a_title or variant_label or s_title)[:48]}",
                      flush=True)
            label = _esc(a_title or variant_label or aid)
            sub = (f"{label} <span style='color:#888'>— {_esc(aid)} · "
                   f"{n_reels or 0} reels</span>")
            info = assetfigures.build_panel_figure(conn, cfg, aid, seg_dir / f"{aid}_panels.png")
            if info is not None:
                body = _img_b64(Path(info["path"])) + _panel_caption(info)
            else:
                heat = seg_dir / f"{aid}.png"
                body = _img_b64(heat) if heat.exists() else "<p><em>(no canonical audio)</em></p>"
            parts.append(f"<div><h4>{sub}</h4>{body}</div>")
    out.write_text(_heatmaps_page("".join(parts)), encoding="utf-8")
    if progress:
        print(f"  usage-heatmaps: wrote {out}", flush=True)
    return out


def build(conn: sqlite3.Connection, cfg: AvConfig | None = None,
          out_path: str | Path | None = None) -> Path:
    """Assemble the sidecar HTML report (present sections only) and write it to disk."""
    cfg = cfg or default_config()
    out = Path(out_path) if out_path else cfg.output_dir / "acoustic_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)

    sections = [s for s in (
        _variant_section(conn, cfg),
        _families_section(conn),
    ) if s]
    if not sections:
        sections = ["<section><p><em>No acoustic data yet — run extract-acoustic / align "
                    "/ detect-edits / group-edits first.</em></p></section>"]

    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>NAMI — acoustic / audio-visual report</title>"
        "<style>body{font-family:sans-serif;margin:2rem;max-width:1000px}"
        "table{border-collapse:collapse;margin:1rem 0}th,td{padding:4px 8px;"
        "border-bottom:1px solid #ddd;text-align:left}h2{border-bottom:2px solid #333}"
        "</style></head><body>"
        "<h1>NAMI — acoustic / audio-visual report</h1>"
        + "".join(sections) + "</body></html>"
    )
    out.write_text(html, encoding="utf-8")
    return out
