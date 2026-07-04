"""
Per-asset combined acoustic figure for the report.

One PNG per asset, stacking five panels that **share the same time axis** (so a vertical
line at time *t* lands at the same horizontal position in every panel):

    0. segment-usage heat strip — which part of the track the corpus's reels use
    1. waveform
    2. spectrogram (log-frequency, dB)
    3. loudness curve (short-term RMS, dB)
    4. tonnetz (harmonic / tonal-centroid space)

All measured on the asset's **canonical audio** via librosa. Y-axes are deliberately
unlabeled and tick-free so every panel has an identical left margin and the panels align
exactly; only the bottom panel carries the time axis. Returns ``None`` (caller falls back to
the standalone heat strip) when canonical audio is absent or plotting deps are unavailable.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .audio import DEFAULT_SR
from .config import AvConfig

HOP = 512

HOOK_COLOR = "#ff2d2d"
BEAT_COLOR = "#00d5ff"
ONSET_COLOR = "#1faa00"
REFRAIN_COLOR = "#e000e0"


def _hook_seconds(conn: sqlite3.Connection, asset_id: str) -> float | None:
    """First 'hook starts at' offset (s) from ``asset_music_meta.highlight_start_ms``."""
    row = conn.execute(
        "SELECT highlight_start_ms FROM asset_music_meta WHERE asset_id=?", (asset_id,)
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        arr = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(arr, (list, tuple)) and arr:
            return float(arr[0]) / 1000.0
    except (TypeError, ValueError):
        pass
    return None


def build_panel_figure(conn: sqlite3.Connection, cfg: AvConfig, asset_id: str,
                       out_path: str | Path) -> dict | None:
    """Render the 5-panel, time-aligned figure for *asset_id*.

    Returns an info dict (``path`` + the per-panel Y-axis boundaries and marker counts the
    HTML caption needs), or ``None`` when canonical audio is absent / plotting deps missing.
    Reads only the **local** canonical ``.m4a`` (no download); beats/onsets are computed by
    librosa on that signal.
    """
    from . import alignment

    audio = alignment._canonical_audio_path(conn, asset_id, cfg)
    if audio is None:
        return None
    try:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import librosa
        import librosa.display
    except Exception:  # noqa: BLE001
        return None

    try:
        y, sr = librosa.load(str(audio), sr=DEFAULT_SR, mono=True)
    except Exception:  # noqa: BLE001
        return None
    if y.size == 0:
        return None
    dur = len(y) / sr

    used = conn.execute(
        "SELECT used_segment_start, used_segment_end FROM reel_acoustics "
        "WHERE asset_id=? AND used_segment_start IS NOT NULL", (asset_id,)
    ).fetchall()
    _, boundaries = alignment._asset_timeline(conn, asset_id, used)
    bins = 600
    edges = np.linspace(0.0, dur, bins + 1)
    coverage = np.zeros(bins)
    for s, e in used:
        lo = np.searchsorted(edges, max(0.0, s), side="right") - 1
        hi = np.searchsorted(edges, min(dur, e), side="left")
        coverage[max(0, lo):max(0, hi)] += 1

    hook_s = _hook_seconds(conn, asset_id)
    try:
        _, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=HOP)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)
    except Exception:  # noqa: BLE001
        beat_times = np.array([])
    try:
        onset_times = librosa.onset.onset_detect(y=y, sr=sr, hop_length=HOP, units="time")
    except Exception:  # noqa: BLE001
        onset_times = np.array([])

    from . import lyrics
    refrains, has_lyrics = lyrics.refrain_start_times(conn, asset_id)

    rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
    rms_db = 20.0 * np.log10(rms + 1e-6)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig = None
    try:
        fig, axes = plt.subplots(
            5, 1, figsize=(11, 9), sharex=True,
            gridspec_kw={"height_ratios": [1.0, 1.3, 2.0, 1.2, 1.6]})

        ax = axes[0]
        ax.imshow(coverage[np.newaxis, :], aspect="auto", cmap="magma",
                  extent=[0, dur, 0, 1])
        for b in boundaries:
            if 0 < b < dur:
                ax.axvline(b, color="cyan", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.set_title(f"segment usage (n={len(used)} reels)", loc="left", fontsize=9)

        ax = axes[1]
        librosa.display.waveshow(y, sr=sr, ax=ax)
        if hook_s is not None and 0 <= hook_s <= dur:
            ax.vlines([hook_s], 0, 1.08, transform=ax.get_xaxis_transform(),
                      color=HOOK_COLOR, linewidth=1.6, clip_on=False)
        ax.set_title("waveform", loc="left", fontsize=9)

        ax = axes[2]
        S = librosa.amplitude_to_db(np.abs(librosa.stft(y, hop_length=HOP)), ref=np.max)
        librosa.display.specshow(S, sr=sr, hop_length=HOP, x_axis="time", y_axis="log",
                                 ax=ax, cmap="magma")
        if len(beat_times):
            ax.vlines(beat_times, 0, 1.08, transform=ax.get_xaxis_transform(),
                      color=BEAT_COLOR, linewidth=0.5, alpha=0.45, clip_on=False)
        ax.set_title("spectrogram (log-f, dB)", loc="left", fontsize=9)

        ax = axes[3]
        t = librosa.times_like(rms, sr=sr, hop_length=HOP)
        if len(onset_times):
            ax.vlines(onset_times, 0, 1.08, transform=ax.get_xaxis_transform(),
                      color=ONSET_COLOR, linewidth=0.5, alpha=0.45, clip_on=False)
        ax.plot(t, rms_db, linewidth=0.8, color="#1565c0")
        ax.set_title("loudness (RMS, dB)", loc="left", fontsize=9)

        ax = axes[4]
        tonnetz = librosa.feature.tonnetz(y=librosa.effects.harmonic(y), sr=sr)
        librosa.display.specshow(tonnetz, sr=sr, x_axis="time", ax=ax, cmap="coolwarm")
        refr_in = [r for r in refrains if 0 <= r <= dur]
        if refr_in:
            ax.vlines(refr_in, 0, 1.08, transform=ax.get_xaxis_transform(),
                      color=REFRAIN_COLOR, linewidth=1.5, clip_on=False)
        ax.set_title("tonnetz", loc="left", fontsize=9)

        for ax in axes:
            ax.set_ylabel("")
            ax.set_yticks([])
            ax.set_xlim(0.0, dur)
            ax.label_outer()
        axes[-1].set_xlabel("time in track (s)")

        fig.subplots_adjust(left=0.035, right=0.99, top=0.97, bottom=0.06, hspace=0.28)
        fig.savefig(out, dpi=110)
        plt.close(fig)
    except Exception:  # noqa: BLE001
        if fig is not None:
            plt.close(fig)
        return None

    return {
        "path": out,
        "duration": round(dur, 2),
        "heat_max": float(coverage.max()) if coverage.size else 0.0,
        "wave_min": float(y.min()), "wave_max": float(y.max()),
        "nyquist": sr / 2.0, "spec_db_lo": -80.0, "spec_db_hi": 0.0,
        "loud_min": float(rms_db.min()), "loud_max": float(rms_db.max()),
        "hook_s": hook_s, "n_beats": int(len(beat_times)), "n_onsets": int(len(onset_times)),
        "n_refrains": len(refrains), "has_lyrics": bool(has_lyrics),
    }
