"""
Validation sampler — export a hand-check sample.

Mirrors NAMI's vision-validation discipline (the honesty rule): the acoustic
estimates that are only Tier-2/3 reliable (tempo, key) get a human-checkable export
rather than being trusted blind.

* ``acoustic_validation.csv`` — one row per asset with tempo/key + their confidences, a
  sample reel to *listen to* (local downloaded media path), sorted **lowest
  confidence first** so the riskiest estimates are checked first.
* ``align_confidence.csv`` — per-reel canonical-track match confidence, to pick the
  ``has_overlay`` cutoff.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .config import AvConfig, default_config


def acoustic_sample(conn: sqlite3.Connection) -> pd.DataFrame:
    """Per-asset tempo/key estimates + a sample reel to listen to, riskiest first."""
    df = pd.read_sql(
        """
        SELECT a.asset_id, tv.song_id, tv.variant_label, a.audio_source,
               a.tempo, a.tempo_confidence, a.est_key, a.est_key_confidence,
               a.est_key_alt, a.key_agreement,
               a.n_reels_consensus
        FROM asset_acoustics a
        LEFT JOIN track_variants tv ON tv.asset_id = a.asset_id
        """,
        conn,
    )
    if df.empty:
        return df

    def _sample(asset_id):
        return conn.execute(
            "SELECT reel_pk, code FROM reels WHERE asset_id=? ORDER BY reel_pk LIMIT 1",
            (asset_id,)).fetchone()

    samples = {a: _sample(a) for a in df["asset_id"]}
    df["sample_reel_pk"] = df["asset_id"].map(lambda a: samples[a][0] if samples[a] else None)
    df["sample_media"] = df["sample_reel_pk"].map(
        lambda pk: f"data/reels/{pk}.mp4" if pk else None)
    df["min_confidence"] = df[["tempo_confidence", "est_key_confidence"]].min(axis=1)
    df["_trust"] = (df["audio_source"] == "canonical").astype(int)
    df = df.sort_values(
        ["_trust", "key_agreement", "min_confidence"], na_position="first")
    return df.drop(columns="_trust").reset_index(drop=True)


def confidence_calibration(conn: sqlite3.Connection) -> pd.DataFrame:
    """Per-reel ``align_confidence`` + offsets + a listen-to URL, sorted ascending.

    The export used to choose the data-driven ``has_overlay`` threshold: a
    bimodal distribution has a valley between "different content" (low) and "same content"
    (high) — pick the threshold there, then `validate --set-overlay-threshold` applies it.
    """
    df = pd.read_sql(
        "SELECT ra.reel_pk, ra.asset_id, ra.align_confidence, ra.used_segment_start, "
        "ra.used_segment_end, ra.has_overlay, r.code "
        "FROM reel_acoustics ra LEFT JOIN reels r ON r.reel_pk = ra.reel_pk "
        "WHERE ra.align_confidence IS NOT NULL ORDER BY ra.align_confidence, ra.reel_pk",
        conn)
    if df.empty:
        return df
    df["sample_file"] = df["reel_pk"].map(lambda pk: f"data/reels/{pk}.mp4")
    return df.drop(columns=["code"])


def _suggest_overlay_threshold(confidences) -> float | None:
    """A starting-point overlay threshold: the valley between the low and high modes."""
    import numpy as np

    v = np.asarray([c for c in confidences if c is not None], dtype=float)
    if v.size < 20:
        return None
    h, edges = np.histogram(v, bins=20, range=(0.0, 1.0))
    centers = (edges[:-1] + edges[1:]) / 2.0
    lo_peak = int(np.argmax(h[:10]))
    hi_peak = 10 + int(np.argmax(h[10:]))
    if h[lo_peak] == 0 or h[hi_peak] == 0 or lo_peak >= hi_peak:
        return None
    valley = lo_peak + int(np.argmin(h[lo_peak:hi_peak + 1]))
    return round(float(centers[valley]), 2)


def _print_validation_guide(paths: dict, cal: pd.DataFrame, suggestion: float | None) -> None:
    """A short, plain-English 'how to read this / what to do' printed after export."""
    print("\n──────── how to read this validation export ────────")
    print("These are the machine's *estimates*; the shakiest are flagged so you can")
    print("spot-check rather than trust blindly. What to look at:")
    if "acoustic_csv" in paths:
        print("• acoustic_validation.csv — tempo/key per asset, the ones to doubt first,")
        print("  each with the local reel file. Open the top few; if those are right, the rest")
        print("  are safer. Two independent key estimates sit side by side (est_key and")
        print("  est_key_alt); key_agreement is 1 when they match, 0.5 for a near miss")
        print("  (relative/parallel), 0 when they part ways — the 0s are worth a listen.")
    if "align_confidence_csv" in paths and cal is not None and not cal.empty:
        q = list(cal["align_confidence"].quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(2))
        print("• align_confidence.csv — how well each reel matched the canonical track.")
        print(f"  distribution (10/25/50/75/90%): {q}")
        print("  Scores split into a LOW group (different/overlaid audio) and a HIGH group")
        print("  (clean match). Pick the cutoff in the gap between them, then apply it")
        print("  (sets has_overlay = confidence < cutoff; no re-align):")
        sug = f"{suggestion}" if suggestion is not None else "<value>"
        print(f"      av validate --set-overlay-threshold {sug}"
              + ("   (suggested starting point — confirm against the CSV)"
                 if suggestion is not None else ""))
    print("────────────────────────────────────────────────────")


def export(conn: sqlite3.Connection, cfg: AvConfig | None = None,
           *, progress: bool = False) -> dict[str, str]:
    """Write the validation CSVs under ``outputs/av/validation/``; return paths."""
    cfg = cfg or default_config()
    vdir = cfg.output_dir / "validation"
    vdir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    df = acoustic_sample(conn)
    if not df.empty:
        p = vdir / "acoustic_validation.csv"
        df.to_csv(p, index=False)
        paths["acoustic_csv"] = str(p)

    cal = confidence_calibration(conn)
    suggestion = None
    if not cal.empty:
        cp = vdir / "align_confidence.csv"
        cal.to_csv(cp, index=False)
        paths["align_confidence_csv"] = str(cp)
        suggestion = _suggest_overlay_threshold(list(cal["align_confidence"]))

    if progress:
        _print_validation_guide(paths, cal, suggestion)
    return paths
