"""
Variant analysis — symmetric, baseline-free.

NAMI's corpus is seeded by songs that appear in multiple acoustic ``track_variants``
(re-uploads / sped-up / slowed / lofi). The sharpest, least-confounded question is
**within-song**: how do a song's renderings differ, and does that track virality.

This module deliberately has **no concept of an "original" / baseline**. The song/work is
only the entity that *binds* the variants (the ``songs.yaml`` → ``track_variants``
grouping); within a song the variants are compared **symmetrically** — how they differ
*from each other* — never anointing one as the reference. (We dropped the old
"baseline = variant whose label contains 'original'" heuristic: it was fragile — e.g. it
crowned a *club mix* as the original — and most "variants" here are duplicate re-uploads,
not transformations, so any single baseline was misleading.)

Three tidy CSV outputs (multi-variant songs only; single-variant songs are skipped):

* **pairs** (``variant_pairs.csv``) — one row per *unordered* variant pair: an octave-folded
  tempo-ratio *magnitude* (robust to a beat-tracker octave error; ≥1, order-free), a folded
  absolute key shift, and absolute spectral deltas. "How far apart are these renderings."
* **dispersion** (``variant_dispersion.csv``) — one row per song: the spread of tempo, key,
  brightness, loudness across its variants. "This song appears across renderings spanning…".
* **reach** (``variant_reach.csv``) — one row per variant: median impact, within-song rank,
  and ratio to the song's variant-median (a symmetric anchor, not a baseline).

Directionality ("which way the transformation goes") is intentionally absent; if ever
wanted it should be added as an optional, separately-sourced orientation label (upload date
/ external metadata), never as a load-bearing baseline.
"""

from __future__ import annotations

import itertools
import math
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .config import AvConfig, default_config

COLS_PAIRS = [
    "song_id", "asset_a", "label_a", "asset_b", "label_b",
    "tempo_a", "tempo_b", "tempo_ratio", "key_shift_semitones",
    "abs_delta_centroid", "abs_delta_rolloff", "abs_delta_bandwidth",
    "abs_delta_flatness", "abs_delta_loudness",
]
COLS_DISP = [
    "song_id", "n_variants", "tempo_min", "tempo_max", "tempo_spread_ratio",
    "n_distinct_keys", "centroid_min", "centroid_max", "centroid_range",
    "loudness_min", "loudness_max", "loudness_range",
]
COLS_REACH = [
    "song_id", "asset_id", "variant_label", "n_reels",
    "median_impact", "reach_rank", "ratio_to_song_median",
]
COLS_IDENTITY = [
    "song_id", "asset_id", "variant_label",
    "identity_group", "group_size", "is_representative",
]


def _num(x) -> float | None:
    """Coerce a possibly-NaN/None cell to a float or None."""
    return float(x) if pd.notna(x) else None


def _absd(a, b) -> float | None:
    """Absolute difference of two possibly-missing cells."""
    a, b = _num(a), _num(b)
    return abs(a - b) if a is not None and b is not None else None


def octave_fold(ratio: float | None) -> float | None:
    """Fold a tempo ratio into ``[1/√2, √2)`` so a factor-of-2 octave error cancels.

    A true 1.25× change still reads as ~1.25 even if one variant's tempo was detected an
    octave off (e.g. 0.625 → ×2 → 1.25). The variant claim uses the *folded* ratio, not
    absolute BPM.
    """
    if ratio is None or ratio <= 0:
        return None
    lo, hi = 1.0 / math.sqrt(2), math.sqrt(2)
    r = float(ratio)
    while r < lo:
        r *= 2
    while r >= hi:
        r /= 2
    return r


def _fold_ratio_magnitude(ta, tb) -> float | None:
    """Order-free, octave-robust tempo-ratio **magnitude** (≥1) between two tempos.

    Symmetric: ``fold(120/75)=0.8`` and ``fold(75/120)=1.25`` both report **1.25**, the true
    distance once the octave error is removed.
    """
    ta, tb = _num(ta), _num(tb)
    if not ta or not tb or ta <= 0 or tb <= 0:
        return None
    f = octave_fold(ta / tb)
    if f is None:
        return None
    return f if f >= 1.0 else 1.0 / f


def _key_pc(key_str) -> int | None:
    """Pitch-class index (0–11) of a key string like ``'C# Minor'``; None if unparseable."""
    if not isinstance(key_str, str) or not key_str.strip():
        return None
    try:
        return KEY_NAMES.index(key_str.split()[0])
    except ValueError:
        return None


def _semitone_shift(pc_a: int | None, pc_b: int | None) -> int | None:
    """Signed semitone shift a→b, folded to ``[-6, +6]`` (nearest direction)."""
    if pc_a is None or pc_b is None:
        return None
    d = (pc_b - pc_a) % 12
    return d - 12 if d > 6 else d


KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def load_variant_features(conn: sqlite3.Connection) -> pd.DataFrame:
    """track_variants joined to their level-A acoustics (only assets already analysed)."""
    return pd.read_sql(
        """
        SELECT tv.song_id, tv.asset_id, tv.variant_label,
               a.tempo, a.spectral_centroid, a.spectral_rolloff, a.spectral_bandwidth,
               a.spectral_flatness, a.loudness_lufs, a.est_key, a.audio_source
        FROM track_variants tv
        JOIN asset_acoustics a ON a.asset_id = tv.asset_id
        ORDER BY tv.song_id, tv.asset_id
        """,
        conn,
    )


def load_impact(conn: sqlite3.Connection) -> pd.DataFrame:
    """Per-asset reel count and median impact (NAMI's play→view→like coalesce rule)."""
    df = pd.read_sql(
        "SELECT reel_pk, asset_id, play_count, view_count, like_count "
        "FROM reels WHERE asset_id IS NOT NULL",
        conn,
    )
    if df.empty:
        return pd.DataFrame(columns=["asset_id", "n_reels", "median_impact"])
    pc = df["play_count"].fillna(0)
    vc = df["view_count"].fillna(0)
    lc = df["like_count"].fillna(0)
    df["impact"] = np.where(pc > 0, pc, np.where(vc > 0, vc, lc))
    g = df.groupby("asset_id")
    return pd.DataFrame({
        "n_reels": g.size(),
        "median_impact": g["impact"].median(),
    }).reset_index()


def _multi_variant_songs(df_feat: pd.DataFrame):
    """Yield (song_id, group) only for songs with ≥2 distinct assets, song-id ordered."""
    for song_id, grp in df_feat.groupby("song_id", sort=True):
        if grp["asset_id"].nunique() >= 2:
            yield song_id, grp


def _near_identical(a, b, tempo_tol: float, centroid_tol: float) -> bool:
    """True if two assets look like the SAME recording (octave-robust tempo, same key
    pitch-class, near-equal brightness). Missing features don't disqualify — they're skipped.
    """
    fr = _fold_ratio_magnitude(a.tempo, b.tempo)
    if fr is None or fr > 1.0 + tempo_tol:
        return False
    ka, kb = _key_pc(a.est_key), _key_pc(b.est_key)
    if ka is not None and kb is not None and ka != kb:
        return False
    ca, cb = _num(a.spectral_centroid), _num(b.spectral_centroid)
    if ca is not None and cb is not None and ca > 0 and cb > 0:
        if abs(ca - cb) / max(ca, cb) > centroid_tol:
            return False
    return True


def variant_identity(df_feat: pd.DataFrame, *,
                     tempo_tol: float = 0.02, centroid_tol: float = 0.05) -> pd.DataFrame:
    """Group a song's assets by acoustic near-identity (single-linkage / union-find).

    Near-identical assets ⇒ the same recording re-uploaded; distinct ⇒ a genuine variant.
    Baseline-free: groups are symmetric, and the representative is just the lexicographically
    smallest ``asset_id`` (stable, arbitrary — members are near-identical by construction).
    This is the symmetric replacement for identifying duplicates via an external ISRC.
    """
    rows = []
    for song_id, grp in _multi_variant_songs(df_feat):
        recs = list(grp.sort_values("asset_id").itertuples(index=False))
        n = len(recs)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, j in itertools.combinations(range(n), 2):
            if _near_identical(recs[i], recs[j], tempo_tol, centroid_tol):
                parent[find(i)] = find(j)

        comps: dict[int, list[int]] = {}
        for i in range(n):
            comps.setdefault(find(i), []).append(i)
        ordered = sorted(comps.values(), key=lambda ms: min(recs[m].asset_id for m in ms))
        for gi, members in enumerate(ordered):
            rep = min(recs[m].asset_id for m in members)
            gid = f"{song_id}#{gi}"
            for m in members:
                rec = recs[m]
                rows.append({
                    "song_id": song_id, "asset_id": rec.asset_id,
                    "variant_label": rec.variant_label, "identity_group": gid,
                    "group_size": len(members), "is_representative": rec.asset_id == rep,
                })
    return pd.DataFrame(rows, columns=COLS_IDENTITY)


def _collapse_to_representatives(df_feat: pd.DataFrame, **id_kwargs) -> pd.DataFrame:
    """Reduce each song to one representative per acoustic-identity group."""
    ident = variant_identity(df_feat, **id_kwargs)
    if ident.empty:
        return df_feat
    reps = set(ident.loc[ident["is_representative"], "asset_id"])
    covered = set(ident["song_id"])
    keep = df_feat["asset_id"].isin(reps) | ~df_feat["song_id"].isin(covered)
    return df_feat[keep]


def variant_pairs(df_feat: pd.DataFrame, *, collapse_identity: bool = False) -> pd.DataFrame:
    """Per unordered variant pair within a song: symmetric acoustic distances.

    With ``collapse_identity=True``, near-identical re-uploads are first reduced to one
    representative each (see :func:`variant_identity`); default off so numbers don't shift.
    """
    if collapse_identity:
        df_feat = _collapse_to_representatives(df_feat)
    rows = []
    for song_id, grp in _multi_variant_songs(df_feat):
        recs = list(grp.sort_values("asset_id").itertuples(index=False))
        for a, b in itertools.combinations(recs, 2):
            ks = _semitone_shift(_key_pc(a.est_key), _key_pc(b.est_key))
            rows.append({
                "song_id": song_id,
                "asset_a": a.asset_id, "label_a": a.variant_label,
                "asset_b": b.asset_id, "label_b": b.variant_label,
                "tempo_a": _num(a.tempo), "tempo_b": _num(b.tempo),
                "tempo_ratio": _fold_ratio_magnitude(a.tempo, b.tempo),
                "key_shift_semitones": abs(ks) if ks is not None else None,
                "abs_delta_centroid": _absd(a.spectral_centroid, b.spectral_centroid),
                "abs_delta_rolloff": _absd(a.spectral_rolloff, b.spectral_rolloff),
                "abs_delta_bandwidth": _absd(a.spectral_bandwidth, b.spectral_bandwidth),
                "abs_delta_flatness": _absd(a.spectral_flatness, b.spectral_flatness),
                "abs_delta_loudness": _absd(a.loudness_lufs, b.loudness_lufs),
            })
    return pd.DataFrame(rows, columns=COLS_PAIRS)


def variant_dispersion(df_feat: pd.DataFrame, *, collapse_identity: bool = False) -> pd.DataFrame:
    """Per song: how widely its variants spread across tempo / key / brightness / loudness.

    With ``collapse_identity=True``, near-identical re-uploads are first collapsed to one
    representative each (so a song that is all duplicates reports no spread); default off.
    """
    if collapse_identity:
        df_feat = _collapse_to_representatives(df_feat)
    rows = []
    for song_id, grp in _multi_variant_songs(df_feat):
        tempos = [t for t in (_num(x) for x in grp["tempo"]) if t]
        cents = [c for c in (_num(x) for x in grp["spectral_centroid"]) if c is not None]
        louds = [l for l in (_num(x) for x in grp["loudness_lufs"]) if l is not None]
        keys = {k.strip() for k in grp["est_key"] if isinstance(k, str) and k.strip()}
        t_min = min(tempos) if tempos else None
        t_max = max(tempos) if tempos else None
        spread = _fold_ratio_magnitude(t_max, t_min) if (t_min and t_max) else None
        rows.append({
            "song_id": song_id,
            "n_variants": int(grp["asset_id"].nunique()),
            "tempo_min": t_min, "tempo_max": t_max, "tempo_spread_ratio": spread,
            "n_distinct_keys": len(keys),
            "centroid_min": min(cents) if cents else None,
            "centroid_max": max(cents) if cents else None,
            "centroid_range": (max(cents) - min(cents)) if cents else None,
            "loudness_min": min(louds) if louds else None,
            "loudness_max": max(louds) if louds else None,
            "loudness_range": (max(louds) - min(louds)) if louds else None,
        })
    return pd.DataFrame(rows, columns=COLS_DISP)


def variant_reach(df_feat: pd.DataFrame, df_imp: pd.DataFrame) -> pd.DataFrame:
    """Per variant: median impact, within-song rank, ratio to the song's variant-median."""
    merged = df_feat.merge(df_imp, on="asset_id", how="left")
    rows = []
    for song_id, grp in _multi_variant_songs(merged):
        meds = [m for m in (_num(x) for x in grp["median_impact"]) if m is not None]
        song_med = float(np.median(meds)) if meds else None
        ranked = grp.sort_values(["median_impact", "asset_id"],
                                ascending=[False, True], na_position="last")
        for rank, (_, v) in enumerate(ranked.iterrows(), start=1):
            mi = _num(v["median_impact"])
            rows.append({
                "song_id": song_id,
                "asset_id": v["asset_id"],
                "variant_label": v["variant_label"],
                "n_reels": int(v["n_reels"]) if pd.notna(v["n_reels"]) else 0,
                "median_impact": mi,
                "reach_rank": rank,
                "ratio_to_song_median": (mi / song_med)
                if (mi is not None and song_med) else None,
            })
    return pd.DataFrame(rows, columns=COLS_REACH)


_JP_SANS = [
    "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Hiragino Maru Gothic ProN",
    "Yu Gothic", "YuGothic", "AppleGothic", "Noto Sans CJK JP", "Noto Sans JP",
    "IPAexGothic", "IPAGothic", "Arial Unicode MS", "DejaVu Sans",
]


def _agg_plt():
    """Return a headless pyplot (Agg backend), or None if matplotlib is unavailable."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager as fm
        installed = {f.name for f in fm.fontManager.ttflist}
        chosen = [n for n in _JP_SANS if n in installed] or ["DejaVu Sans"]
        plt.rcParams["font.family"] = chosen
        return plt
    except Exception:
        return None


def _safe_filename(s) -> str:
    """Filesystem-safe token from a song_id (e.g. ``kimi_wa_1000%`` -> ``kimi_wa_1000_``)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s))


def plot_feature_space_per_song(df_feat: pd.DataFrame, out_dir, titles=None) -> list[Path]:
    """One arrowless scatter **per song**: its variants as labelled points in
    tempo × brightness space. No baseline, no centre marker (there is no anointed centre).
    Returns the written paths (``variant_feature_space_<song>.png``).
    """
    plt = _agg_plt()
    if plt is None:
        return []
    titles = titles or {}
    out_dir = Path(out_dir)
    paths: list[Path] = []
    for song_id, grp in _multi_variant_songs(df_feat):
        pts = [(r.variant_label, _num(r.tempo), _num(r.spectral_centroid))
               for r in grp.itertuples(index=False)]
        pts = [(lbl, t, c) for lbl, t, c in pts if t is not None and c is not None]
        if not pts:
            continue
        fig, ax = plt.subplots(figsize=(7, 5.5))
        for lbl, t, c in pts:
            ax.scatter([t], [c], s=50, color="#33aa77")
            ax.annotate(str(lbl), (t, c), fontsize=8,
                        xytext=(4, 4), textcoords="offset points")
        ax.set_xlabel("tempo (BPM)")
        ax.set_ylabel("spectral centroid / brightness (Hz)")
        ax.set_title(f"Variant transformation in acoustic feature space — {titles.get(song_id, song_id)}")
        path = out_dir / f"variant_feature_space_{_safe_filename(song_id)}.png"
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        paths.append(path)
    return paths


def plot_reach(reach: pd.DataFrame, path: Path) -> Path | None:
    """Bar of median impact per (song, variant) — no baseline, uniform colour."""
    plt = _agg_plt()
    if plt is None or reach.empty:
        return None
    labels = (reach["song_id"].astype(str) + "/" + reach["variant_label"].astype(str)).tolist()
    fig, ax = plt.subplots(figsize=(max(6, len(reach) * 0.7), 5))
    ax.bar(range(len(reach)), reach["median_impact"].fillna(0), color="#33aa77")
    ax.set_xticks(range(len(reach)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("median impact")
    ax.set_title("Median reach per variant (within-song)")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def run(conn: sqlite3.Connection, cfg: AvConfig | None = None) -> dict:
    """Compute the three symmetric outputs, write CSVs + the reach figure, return a summary."""
    cfg = cfg or default_config()
    data_dir = cfg.data_dir
    fig_dir = cfg.figures_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    df_feat = load_variant_features(conn)
    df_imp = load_impact(conn)
    pairs = variant_pairs(df_feat)
    disp = variant_dispersion(df_feat)
    reach = variant_reach(df_feat, df_imp)
    identity = variant_identity(df_feat)

    t_pairs = data_dir / "variant_pairs.csv"
    t_disp = data_dir / "variant_dispersion.csv"
    t_reach = data_dir / "variant_reach.csv"
    t_identity = data_dir / "variant_identity.csv"
    pairs.to_csv(t_pairs, index=False)
    disp.to_csv(t_disp, index=False)
    reach.to_csv(t_reach, index=False)
    identity.to_csv(t_identity, index=False)

    try:
        titles = dict(pd.read_sql("SELECT song_id, title FROM songs", conn).values)
    except Exception:  # noqa: BLE001
        titles = {}
    fig = plot_reach(reach, fig_dir / "variant_reach.png")
    space_figs = plot_feature_space_per_song(df_feat, fig_dir, titles)

    figures = ([str(fig)] if fig is not None else []) + [str(p) for p in space_figs]
    return {
        "n_pairs": len(pairs),
        "n_songs": len(disp),
        "n_reach_rows": len(reach),
        "n_identity_groups": int(identity["identity_group"].nunique()) if not identity.empty else 0,
        "n_duplicate_assets": int((identity["group_size"] > 1).sum()) if not identity.empty else 0,
        "tables": [str(t_pairs), str(t_disp), str(t_reach), str(t_identity)],
        "figures": figures,
    }
