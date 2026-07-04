from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from . import EXTRACTOR_VERSION, state
from .audio import DEFAULT_SR, extract_audio
from .config import AvConfig, default_config, param_hash

DEFAULT_OVERLAY_THRESHOLD = 0.5
DEFAULT_METHOD = "onset"
DEFAULT_HOP = 512


def alignment_params(overlay_threshold: float, method: str = DEFAULT_METHOD,
                     hop: int = DEFAULT_HOP) -> dict:
    return {"sr": DEFAULT_SR, "method": method, "hop": hop,
            "overlay_threshold": overlay_threshold, "extractor_version": EXTRACTOR_VERSION}


def _ncc_curve(ref: np.ndarray, query: np.ndarray) -> np.ndarray:
    from scipy.signal import correlate

    ref = np.asarray(ref, dtype=np.float64)
    q = np.asarray(query, dtype=np.float64)
    n, m = ref.size, q.size
    if n == 0 or m == 0:
        return np.asarray([], dtype=np.float64)
    if m > n:
        q = q[:n]
        m = n

    num = correlate(ref, q, mode="valid")
    csum = np.concatenate([[0.0], np.cumsum(ref * ref)])
    win_energy = csum[m:] - csum[: csum.size - m]
    q_norm = float(np.sqrt(np.sum(q * q)))
    denom = np.sqrt(np.clip(win_energy, 0.0, None)) * q_norm
    return np.where(denom > 1e-9, num / np.where(denom > 1e-9, denom, 1.0), 0.0)


def _ncc_slide(ref: np.ndarray, query: np.ndarray) -> tuple[int, float]:
    ncc = _ncc_curve(ref, query)
    if ncc.size == 0:
        return 0, 0.0
    lag = int(np.argmax(ncc))
    return lag, float(np.clip(ncc[lag], -1.0, 1.0))


def find_offset(ref: np.ndarray, query: np.ndarray, sr: int) -> tuple[float, float]:
    lag, peak = _ncc_slide(ref, query)
    return lag / sr, peak


def _zscore(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return x
    sd = float(x.std())
    return (x - x.mean()) / sd if sd > 1e-9 else x - x.mean()


def _onset_env(y: np.ndarray, sr: int, hop: int) -> np.ndarray:
    import librosa

    oenv = librosa.onset.onset_strength(y=np.asarray(y, dtype=np.float32), sr=sr, hop_length=hop)
    return _zscore(oenv)


def _chroma(y: np.ndarray, sr: int, hop: int) -> np.ndarray:
    import librosa

    return librosa.feature.chroma_cens(y=np.asarray(y, dtype=np.float32), sr=sr, hop_length=hop)


def _chroma_sim(chroma_ref: np.ndarray | None, chroma_q: np.ndarray | None,
                lag: int) -> float | None:
    if chroma_ref is None or chroma_q is None:
        return None
    if chroma_ref.shape[1] == 0 or chroma_q.shape[1] == 0:
        return None
    w = chroma_q.shape[1]
    seg = chroma_ref[:, lag:lag + w]
    m = min(seg.shape[1], chroma_q.shape[1])
    if m < 2:
        return None
    a, b = seg[:, :m], chroma_q[:, :m]
    den = np.linalg.norm(a, axis=0) * np.linalg.norm(b, axis=0)
    sims = (a * b).sum(axis=0) / np.where(den > 1e-9, den, 1.0)
    return float(np.clip(np.mean(sims), 0.0, 1.0))


def _offset_from_ref(oenv_ref: np.ndarray, chroma_ref: np.ndarray | None,
                     query: np.ndarray, sr: int, hop: int,
                     *, top_k: int = 6) -> tuple[float, float]:
    oenv_q = _onset_env(query, sr, hop)
    if oenv_ref.size == 0 or oenv_q.size == 0:
        return 0.0, 0.0
    ncc = _ncc_curve(oenv_ref, oenv_q)
    if ncc.size == 0:
        return 0.0, 0.0

    k = min(top_k, ncc.size)
    candidates = np.argsort(ncc)[::-1][:k]

    chroma_q = None
    if chroma_ref is not None:
        try:
            chroma_q = _chroma(query, sr, hop)
        except Exception:  # noqa: BLE001
            chroma_q = None

    best_lag = int(candidates[0])
    best_score = -1.0
    for lag in candidates:
        lag = int(lag)
        onset_peak = float(np.clip(ncc[lag], 0.0, 1.0))
        sim = _chroma_sim(chroma_ref, chroma_q, lag) if chroma_q is not None else None
        score = min(onset_peak, sim) if sim is not None else onset_peak
        if score > best_score:
            best_score, best_lag = score, lag

    return best_lag * hop / sr, float(np.clip(best_score, 0.0, 1.0))


def find_offset_features(ref: np.ndarray, query: np.ndarray, sr: int,
                         *, hop: int = DEFAULT_HOP) -> tuple[float, float]:
    """
    Encode-robust offset (seconds) of *query* inside *ref* + a [0,1] confidence.
    """
    ref = np.asarray(ref, dtype=np.float32)
    query = np.asarray(query, dtype=np.float32)
    if ref.size == 0 or query.size == 0:
        return 0.0, 0.0
    oenv_ref = _onset_env(ref, sr, hop)
    try:
        chroma_ref = _chroma(ref, sr, hop)
    except Exception:  # noqa: BLE001
        chroma_ref = None
    return _offset_from_ref(oenv_ref, chroma_ref, query, sr, hop)


def _segment_edges(boundaries, duration: float) -> list[float]:
    interior = sorted(b for b in (boundaries or []) if 0.0 < b < duration)
    return [0.0] + interior + [float(duration)]


def map_to_segment(t: float, boundaries, duration: float) -> int:
    """
    Index of the structural segment containing time.
    """
    edges = _segment_edges(boundaries, duration)
    for i in range(len(edges) - 1):
        if edges[i] <= t < edges[i + 1]:
            return i
    return max(0, len(edges) - 2)


def _asset_timeline(conn: sqlite3.Connection, asset_id: str,
                    used_rows: list[tuple[float, float]]) -> tuple[float, list[float]]:
    """Track duration + structural boundaries for an asset.
    """
    meta = conn.execute(
        "SELECT duration_real_s FROM asset_music_meta WHERE asset_id=?", (asset_id,)
    ).fetchone()
    row = conn.execute(
        "SELECT duration, segment_boundaries FROM asset_acoustics WHERE asset_id=?",
        (asset_id,),
    ).fetchone()
    boundaries = json.loads(row[1]) if (row and row[1]) else []
    if meta and meta[0]:
        return float(meta[0]), boundaries
    if row and row[0]:
        return float(row[0]), boundaries
    duration = max((e for _, e in used_rows), default=0.0)
    return duration, []


def segment_usage(conn: sqlite3.Connection, asset_id: str) -> tuple[list[int], list[float]]:
    """Per-structural-segment count of reels whose used-segment midpoint lands there."""
    used = conn.execute(
        "SELECT used_segment_start, used_segment_end FROM reel_acoustics "
        "WHERE asset_id=? AND used_segment_start IS NOT NULL", (asset_id,)
    ).fetchall()
    duration, boundaries = _asset_timeline(conn, asset_id, used)
    edges = _segment_edges(boundaries, duration)
    counts = [0] * (len(edges) - 1)
    if duration <= 0:
        return counts, edges
    for s, e in used:
        mid = (s + e) / 2.0
        counts[map_to_segment(mid, boundaries, duration)] += 1
    return counts, edges


def plot_segment_heat(conn: sqlite3.Connection, asset_id: str, path: Path,
                      *, bins: int = 120) -> Path | None:
    """Render a usage heat strip over the track timeline (boundaries marked)."""
    used = conn.execute(
        "SELECT used_segment_start, used_segment_end FROM reel_acoustics "
        "WHERE asset_id=? AND used_segment_start IS NOT NULL", (asset_id,)
    ).fetchall()
    if not used:
        return None
    duration, boundaries = _asset_timeline(conn, asset_id, used)
    if duration <= 0:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    edges = np.linspace(0.0, duration, bins + 1)
    coverage = np.zeros(bins)
    for s, e in used:
        lo = np.searchsorted(edges, max(0.0, s), side="right") - 1
        hi = np.searchsorted(edges, min(duration, e), side="left")
        coverage[max(0, lo):max(0, hi)] += 1

    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 2.2))
    ax.imshow(coverage[np.newaxis, :], aspect="auto", cmap="magma",
              extent=[0, duration, 0, 1])
    for b in boundaries:
        if 0 < b < duration:
            ax.axvline(b, color="cyan", linestyle="--", linewidth=1, alpha=0.7)
    ax.set_yticks([])
    ax.set_xlabel("time in track (s)")
    ax.set_title(f"Segment usage heat strip -- {asset_id} (n={len(used)} reels)")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def _alignable_by_asset(conn: sqlite3.Connection, cfg: AvConfig) -> dict[str, list[tuple[str, Path]]]:
    """{asset_id: [(reel_pk, mp4), …]} for reels whose MP4 exists on disk."""
    rows = conn.execute(
        "SELECT reel_pk, asset_id FROM reels WHERE asset_id IS NOT NULL "
        "ORDER BY asset_id, reel_pk"
    ).fetchall()
    out: dict[str, list[tuple[str, Path]]] = {}
    for pk, asset_id in rows:
        mp4 = cfg.reels_dir / f"{pk}.mp4"
        if mp4.exists() and mp4.stat().st_size > 0:
            out.setdefault(asset_id, []).append((pk, mp4))
    return out


def _canonical_audio_path(conn: sqlite3.Connection, asset_id: str, cfg: AvConfig) -> Path | None:
    """The asset's downloaded canonical audio file, if present (else ``None``).
    """
    row = conn.execute(
        "SELECT audio_path, audio_source FROM asset_music_meta WHERE asset_id=?", (asset_id,)
    ).fetchone()
    candidates = []
    if row and row[0] and (row[1] in ("canonical", "preview")):
        candidates.append(Path(row[0]))
    candidates.append(cfg.asset_audio_dir / f"{asset_id}.m4a")
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _reference(conn: sqlite3.Connection, asset_id: str, items: list[tuple[str, Path]],
               cfg: AvConfig, overwrite: bool):
    """
    The alignment reference signal — canonical audio when available, else longest reel.
    """
    import librosa
    import soundfile as sf

    canonical = _canonical_audio_path(conn, asset_id, cfg)
    if canonical is not None:
        y, _ = librosa.load(str(canonical), sr=DEFAULT_SR, mono=True)
        return f"asset:{asset_id}", y, DEFAULT_SR

    best = None
    for pk, mp4 in items:
        wav = cfg.audio_cache_dir / f"{pk}.wav"
        extract_audio(mp4, wav, overwrite=overwrite)
        dur = sf.info(str(wav)).duration
        if best is None or dur > best[0]:
            best = (dur, pk, wav)
    _, ref_pk, ref_wav = best
    y, _ = librosa.load(str(ref_wav), sr=DEFAULT_SR, mono=True)
    return ref_pk, y, DEFAULT_SR


def apply_overlay_threshold(conn: sqlite3.Connection, threshold: float) -> dict[str, int]:
    """
    Recompute reel_acoustics.has_overlay as align_confidence < threshold in place.
    """
    conn.execute(
        "UPDATE reel_acoustics SET has_overlay = CASE "
        "WHEN align_confidence IS NULL THEN has_overlay "
        "WHEN align_confidence < ? THEN 1 ELSE 0 END",
        (float(threshold),))
    conn.commit()
    flagged = conn.execute(
        "SELECT COALESCE(has_overlay,0), COUNT(*) FROM reel_acoustics GROUP BY has_overlay"
    ).fetchall()
    return {("overlay" if k == 1 else "clean"): n for k, n in flagged}


def _write_reel_acoustics(conn: sqlite3.Connection, row: dict) -> None:
    cols = ["reel_pk", "asset_id", "used_segment_start", "used_segment_end",
            "align_confidence", "has_overlay", "extractor_version", "param_hash"]
    conn.execute(
        f"INSERT OR REPLACE INTO reel_acoustics ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})",
        [row.get(c) for c in cols],
    )
    conn.commit()


def run(
    conn: sqlite3.Connection,
    cfg: AvConfig | None = None,
    *,
    limit: int | None = None,
    include_failed: bool = False,
    max_reels: int | None = None,
    overlay_threshold: float = DEFAULT_OVERLAY_THRESHOLD,
    method: str = DEFAULT_METHOD,
    hop: int = DEFAULT_HOP,
    overwrite_audio: bool = False,
    render_heat: bool = True,
    progress: bool = False,
) -> dict:
    """
    Align all pending reels to their asset reference; write rows, render heat strips.
    """
    import librosa

    cfg = cfg or default_config()
    by_asset = _alignable_by_asset(conn, cfg)
    all_reels = [pk for items in by_asset.values() for pk, _ in items]
    state.init_state(conn, state.ALIGN_STATE, all_reels)
    pending = set(state.pending_keys(
        conn, state.ALIGN_STATE, include_failed=include_failed, limit=limit))

    phash = param_hash(alignment_params(overlay_threshold, method, hop))
    heat_paths: list[str] = []
    n_assets = sum(1 for items in by_asset.values() if any(pk in pending for pk, _ in items))
    done_assets = 0
    for asset_id, items in by_asset.items():
        if max_reels:
            items = items[:max_reels]
        if not any(pk in pending for pk, _ in items):
            continue
        try:
            _, ref_y, sr = _reference(conn, asset_id, items, cfg, overwrite_audio)
            oenv_ref = chroma_ref = None
            if method == "onset":
                oenv_ref = _onset_env(ref_y, sr, hop)
                try:
                    chroma_ref = _chroma(ref_y, sr, hop)
                except Exception:  # noqa: BLE001
                    chroma_ref = None
        except Exception as exc:  # noqa: BLE001
            for pk, _ in items:
                if pk in pending:
                    state.set_status(conn, state.ALIGN_STATE, pk, "failed", f"reference: {exc}")
            continue

        for pk, mp4 in items:
            if pk not in pending:
                continue
            try:
                wav = cfg.audio_cache_dir / f"{pk}.wav"
                extract_audio(mp4, wav, overwrite=overwrite_audio)
                y, _ = librosa.load(str(wav), sr=sr, mono=True)
                if method == "onset":
                    offset, conf = _offset_from_ref(oenv_ref, chroma_ref, y, sr, hop)
                else:
                    offset, conf = find_offset(ref_y, y, sr)
                dur = len(y) / sr
                _write_reel_acoustics(conn, {
                    "reel_pk": pk, "asset_id": asset_id,
                    "used_segment_start": round(offset, 4),
                    "used_segment_end": round(offset + dur, 4),
                    "align_confidence": round(conf, 4),
                    "has_overlay": int(conf < overlay_threshold),
                    "extractor_version": EXTRACTOR_VERSION, "param_hash": phash,
                })
                state.set_status(conn, state.ALIGN_STATE, pk, "done",
                                 f"offset={offset:.2f}s conf={conf:.2f}")
            except Exception as exc:  # noqa: BLE001
                state.set_status(conn, state.ALIGN_STATE, pk, "failed",
                                 f"{type(exc).__name__}: {exc}")

        if render_heat:
            p = plot_segment_heat(conn, asset_id, cfg.output_dir / "segments" / f"{asset_id}.png")
            if p:
                heat_paths.append(str(p))

        done_assets += 1
        if progress:
            print(f"  align: asset {done_assets}/{n_assets} ({asset_id}, {len(items)} reels)",
                  flush=True)

    return {"state": state.status_counts(conn, state.ALIGN_STATE), "heat_strips": heat_paths}
