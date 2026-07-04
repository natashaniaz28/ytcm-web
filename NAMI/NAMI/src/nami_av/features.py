"""
Level-A acoustic feature extraction — per ``asset_id``.

This ports TubeSound's librosa logic (``ytcm-AV.ipynb`` cells 14–53) into a headless,
robust extractor. Two layers:

* :func:`extract_features` — pure DSP: a loaded mono signal in, a flat feature dict out.
  Every feature group is individually guarded, so a short or degenerate signal yields
  ``None`` for the features it can't support instead of raising.
* :func:`run` / :func:`extract_asset` — orchestration: for each ``asset_id`` it measures
  level-A features on the asset's **canonical audio** (one file fetched once from Instagram;
  see :mod:`nami_av.asset_audio`), writing one row to ``asset_acoustics``
  and driving ``acoustic_state``. When canonical audio is unavailable (deleted /
  user-original / ``--no-fetch`` with nothing cached) it falls back to a **consensus**
  (median / modal key) over up to ``max_reels`` reel slices. The chosen
  path is recorded in ``asset_acoustics.audio_source`` (``canonical`` | ``preview`` |
  ``reel_consensus``).

Key is the shakiest of these estimates, so it gets a second opinion: alongside the
chroma-peak guess (``est_key``) we run a Krumhansl-Schmuckler template match
(``est_key_alt``) and store how well the two agree (``key_agreement``). Agreement isn't a
guarantee of correctness, but a disagreement is a reliable "look here" flag — the
``validate`` export sorts those to the top.

Unit discipline (§0): features are stored **per asset**, never averaged over reels as if
they were a reel-level property — the canonical-audio measurement (or, in fallback, the
consensus) *is* the asset's value.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import median

import numpy as np

from . import EXTRACTOR_VERSION, asset_audio, state
from .audio import DEFAULT_SR, extract_audio
from .config import AvConfig, default_config, param_hash

N_MFCC = 13
ROLL_PERCENT = 0.85
SEG_MAX_K = 8
SMOOTH_WINDOW_S = 3.0
DEFAULT_MAX_REELS = 7

KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

KRUMHANSL_MAJOR = np.array(
    [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MINOR = np.array(
    [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

_SCALAR_FEATURES = (
    "tempo", "tempo_confidence", "est_key_confidence", "est_key_alt_confidence",
    "spectral_centroid", "spectral_rolloff", "spectral_bandwidth", "spectral_flatness",
    "rms", "loudness_lufs", "dynamic_range", "duration", "harmonic_change_rate",
)

FEATURE_KEYS = _SCALAR_FEATURES + (
    "est_key", "est_key_alt", "key_agreement",
    "mfcc_summary", "n_segments", "segment_boundaries",
)


def extraction_params() -> dict:
    """The parameter set hashed into ``param_hash`` for provenance."""
    return {
        "sr": DEFAULT_SR, "n_mfcc": N_MFCC, "roll_percent": ROLL_PERCENT,
        "seg_max_k": SEG_MAX_K, "smooth_window_s": SMOOTH_WINDOW_S,
        "extractor_version": EXTRACTOR_VERSION,
    }


def _f(x) -> float | None:
    """Coerce to a finite python float, or None for NaN/inf/empty."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _loudness_lufs(y: np.ndarray, sr: int) -> float | None:
    """Integrated loudness (ITU-R BS.1770) via pyloudnorm; dBFS-RMS proxy as fallback.

    Real LUFS needs ≥400 ms of signal; on shorter or degenerate input we fall back to a
    simple RMS-based dBFS figure so the column is always populated with a comparable
    loudness number (documented as approximate when the proxy is used).
    """
    try:
        import pyloudnorm as pyln

        meter = pyln.Meter(sr)
        return _f(meter.integrated_loudness(y.astype(np.float64)))
    except Exception:
        rms = float(np.sqrt(np.mean(np.square(y)))) if y.size else 0.0
        return _f(20.0 * np.log10(rms + 1e-10))


def krumhansl_key(chroma_mean: np.ndarray) -> tuple[str | None, float | None]:
    """A second opinion on the key, by the Krumhansl-Schmuckler method.

    Where the primary estimate just picks the loudest chroma bin and checks one third,
    this correlates the whole 12-bin profile against Krumhansl's 24 major/minor key
    templates and takes the best fit. The confidence is how far the winner pulls ahead of
    the runner-up key — a comfortable margin means the two methods that disagree are worth
    looking at, a thin one means even this estimator was nearly a coin toss.
    """
    x = np.asarray(chroma_mean, dtype=float)
    if x.size != 12 or not np.any(x):
        return None, None
    x = x - x.mean()
    xn = np.linalg.norm(x)
    if xn == 0:
        return None, None

    scored = []
    for quality, profile in (("Major", KRUMHANSL_MAJOR), ("Minor", KRUMHANSL_MINOR)):
        p = profile - profile.mean()
        pn = np.linalg.norm(p)
        for tonic in range(12):
            r = float(np.dot(x, np.roll(p, tonic)) / (xn * pn + 1e-10))
            scored.append((r, tonic, quality))
    scored.sort(key=lambda t: t[0], reverse=True)
    r_best, tonic_best, quality_best = scored[0]
    margin = r_best - scored[1][0]
    return f"{KEY_NAMES[tonic_best]} {quality_best}", _f(max(0.0, min(1.0, margin)))


def _parse_key(text) -> tuple[int, str] | None:
    """Split a key label like ``"C# Minor"`` into (pitch-class, quality), or None."""
    if not isinstance(text, str):
        return None
    parts = text.split()
    if len(parts) != 2 or parts[0] not in KEY_NAMES:
        return None
    return KEY_NAMES.index(parts[0]), parts[1]


def key_agreement(key_a, key_b) -> float | None:
    """How well two key labels agree, on a 1 / 0.5 / 0 scale (None if either is missing).

    1.0 means they name the same tonic and mode. 0.5 is reserved for the classic near
    misses — a parallel pair (same tonic, major vs minor) or a relative pair (e.g. C major
    and A minor, which share a key signature), the disagreements that are musically a hair's
    breadth apart rather than genuinely wrong. Anything else is 0.0.
    """
    a, b = _parse_key(key_a), _parse_key(key_b)
    if a is None or b is None:
        return None
    (pc_a, q_a), (pc_b, q_b) = a, b
    if pc_a == pc_b and q_a == q_b:
        return 1.0
    if pc_a == pc_b:
        return 0.5
    relatives = {
        ("Major", "Minor"): (pc_a + 9) % 12,
        ("Minor", "Major"): (pc_a + 3) % 12,
    }
    if relatives.get((q_a, q_b)) == pc_b:
        return 0.5
    return 0.0


def extract_features(y: np.ndarray, sr: int) -> dict:
    """Extract level-A acoustic features from a mono signal *y* at rate *sr*.

    Returns a dict with every key in :data:`FEATURE_KEYS`; any feature that cannot be
    computed on this signal is ``None``. Never raises on signal content.
    """
    import librosa

    res: dict = {k: None for k in FEATURE_KEYS}
    y = np.asarray(y, dtype=np.float32)
    if y.size == 0:
        return res

    res["duration"] = _f(len(y) / sr)

    beat_frames = np.array([], dtype=int)
    beat_times = np.array([], dtype=float)
    try:
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
        res["tempo"] = _f(np.atleast_1d(tempo)[0])
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        if beat_times.size >= 3:
            intervals = np.diff(beat_times)
            cv = float(np.std(intervals) / (np.mean(intervals) + 1e-10))
            res["tempo_confidence"] = _f(max(0.0, 1.0 - cv))
        else:
            res["tempo_confidence"] = 0.0
    except Exception:
        pass

    try:
        res["spectral_centroid"] = _f(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
        res["spectral_rolloff"] = _f(np.mean(
            librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=ROLL_PERCENT)))
        res["spectral_bandwidth"] = _f(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr)))
        res["spectral_flatness"] = _f(np.mean(librosa.feature.spectral_flatness(y=y)))
    except Exception:
        pass

    try:
        res["rms"] = _f(np.mean(librosa.feature.rms(y=y)))
    except Exception:
        pass
    res["loudness_lufs"] = _loudness_lufs(y, sr)
    try:
        peak = float(np.max(np.abs(y)))
        if peak > 0:
            res["dynamic_range"] = _f(20.0 * np.log10(peak / (np.mean(np.abs(y)) + 1e-10)))
    except Exception:
        pass

    mfcc = None
    try:
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC)
        res["mfcc_summary"] = json.dumps({
            "mean": [round(float(v), 4) for v in np.mean(mfcc, axis=1)],
            "std": [round(float(v), 4) for v in np.std(mfcc, axis=1)],
        })
    except Exception:
        pass

    try:
        if mfcc is not None and beat_frames.size >= 2:
            mfcc_sync = librosa.util.sync(mfcc, beat_frames)
            n_cols = mfcc_sync.shape[1]
            if n_cols >= 2:
                k = max(2, min(SEG_MAX_K, n_cols - 1))
                bounds = librosa.segment.agglomerative(mfcc_sync, k=k)
                valid = bounds < len(beat_times)
                btimes = beat_times[bounds[valid]]
                res["segment_boundaries"] = json.dumps(
                    [round(float(t), 3) for t in np.sort(btimes)])
                res["n_segments"] = int(len(btimes) + 1)
    except Exception:
        pass

    try:
        y_harm = librosa.effects.harmonic(y)
        chroma = librosa.feature.chroma_cens(y=y_harm, sr=sr)
        try:
            width = int(librosa.time_to_frames(SMOOTH_WINDOW_S, sr=sr))
            width = min(max(1, width), chroma.shape[1])
            chroma_smooth = librosa.decompose.nn_filter(
                chroma, aggregate=np.median, metric="cosine", width=width)
        except Exception:
            chroma_smooth = chroma

        chroma_mean = np.mean(chroma_smooth, axis=1)
        if np.any(chroma_mean):
            key_idx = int(np.argmax(chroma_mean))
            major_third, minor_third = chroma_mean[(key_idx + 4) % 12], chroma_mean[(key_idx + 3) % 12]
            quality = "Major" if major_third >= minor_third else "Minor"
            res["est_key"] = f"{KEY_NAMES[key_idx]} {quality}"
            ordered = np.sort(chroma_mean)[::-1]
            res["est_key_confidence"] = _f(
                (ordered[0] - ordered[1]) / (ordered[0] + 1e-10)) if ordered.size > 1 else 0.0

            alt_key, alt_conf = krumhansl_key(chroma_mean)
            res["est_key_alt"] = alt_key
            res["est_key_alt_confidence"] = alt_conf
            res["key_agreement"] = key_agreement(res["est_key"], alt_key)

        try:
            _, beats_h = librosa.beat.beat_track(y=y_harm, sr=sr)
            tonnetz = librosa.feature.tonnetz(chroma=chroma_smooth, sr=sr)
            tonnetz_beat = librosa.util.sync(tonnetz, beats_h, aggregate=np.median)
            if tonnetz_beat.shape[1] >= 2:
                change = np.linalg.norm(np.diff(tonnetz_beat, axis=1), axis=0)
                res["harmonic_change_rate"] = _f(np.mean(change))
        except Exception:
            pass
    except Exception:
        pass

    return res


def extract_features_from_file(path: str | Path, sr: int = DEFAULT_SR) -> dict:
    """Load *path* as mono at *sr* and return :func:`extract_features`."""
    import librosa

    y, sr_loaded = librosa.load(str(path), sr=sr, mono=True)
    return extract_features(y, sr_loaded)


def consensus(feature_dicts: list[dict]) -> dict:
    """Reduce per-reel feature dicts to one canonical per-asset dict.

    Median for numeric features (robust to one overlay-contaminated reel), modal value
    for the estimated key, element-wise median for the MFCC summary, and the longest
    reel as the representative for the (structure-dependent) segmentation.
    """
    valid = [d for d in feature_dicts if d]
    out: dict = {k: None for k in FEATURE_KEYS}
    if not valid:
        return out

    for key in _SCALAR_FEATURES:
        vals = [d[key] for d in valid if d.get(key) is not None]
        out[key] = float(median(vals)) if vals else None

    keys = [d["est_key"] for d in valid if d.get("est_key")]
    if keys:
        out["est_key"] = Counter(keys).most_common(1)[0][0]

    alt_keys = [d["est_key_alt"] for d in valid if d.get("est_key_alt")]
    if alt_keys:
        out["est_key_alt"] = Counter(alt_keys).most_common(1)[0][0]
    out["key_agreement"] = key_agreement(out["est_key"], out["est_key_alt"])

    mfccs = [json.loads(d["mfcc_summary"]) for d in valid if d.get("mfcc_summary")]
    if mfccs:
        means = np.array([m["mean"] for m in mfccs])
        stds = np.array([m["std"] for m in mfccs])
        out["mfcc_summary"] = json.dumps({
            "mean": [round(float(v), 4) for v in np.median(means, axis=0)],
            "std": [round(float(v), 4) for v in np.median(stds, axis=0)],
        })

    rep = max(valid, key=lambda d: d.get("duration") or 0.0)
    out["segment_boundaries"] = rep.get("segment_boundaries")
    out["n_segments"] = rep.get("n_segments")
    return out


def discover_assets(conn: sqlite3.Connection) -> list[str]:
    """Distinct, non-null ``asset_id`` values that have reels — the analysis units."""
    rows = conn.execute(
        "SELECT DISTINCT asset_id FROM reels WHERE asset_id IS NOT NULL ORDER BY asset_id"
    ).fetchall()
    return [r[0] for r in rows]


def _reel_media(conn: sqlite3.Connection, cfg: AvConfig, asset_id: str) -> list[tuple[str, Path]]:
    """(reel_pk, media_path) pairs for an asset whose MP4 exists on disk."""
    rows = conn.execute(
        "SELECT reel_pk FROM reels WHERE asset_id=? ORDER BY reel_pk", (asset_id,)
    ).fetchall()
    out = []
    for (pk,) in rows:
        mp4 = cfg.reels_dir / f"{pk}.mp4"
        if mp4.exists() and mp4.stat().st_size > 0:
            out.append((pk, mp4))
    return out


def _canonical_meta(
    conn: sqlite3.Connection,
    cfg: AvConfig,
    asset_id: str,
    *,
    fetch: bool,
    refresh_audio: bool,
    client,
) -> dict | None:
    """Best-effort canonical-audio metadata for an asset.

    When *fetch* is set, resolve+download via the network ladder (a token/network failure
    degrades to ``None`` instead of raising). When *fetch* is off (``--no-fetch``), use only
    an already-downloaded canonical file — never touch the network.
    """
    if fetch:
        try:
            return asset_audio.fetch_asset_audio(
                conn, cfg, asset_id, client=client, refresh=refresh_audio)
        except Exception:  # noqa: BLE001
            return None
    return asset_audio._existing_meta(conn, asset_id)


def _canonical_usable(meta: dict | None, cfg: AvConfig, asset_id: str) -> str | None:
    """Return the canonical audio file path if *meta* points at a present file, else None."""
    if not meta or meta.get("audio_source") not in ("canonical", "preview"):
        return None
    path = meta.get("audio_path") or str(asset_audio.asset_audio_path(cfg, asset_id))
    return path if Path(path).exists() and Path(path).stat().st_size > 0 else None


def extract_asset(
    conn: sqlite3.Connection,
    cfg: AvConfig,
    asset_id: str,
    *,
    max_reels: int = DEFAULT_MAX_REELS,
    overwrite_audio: bool = False,
    fetch: bool = True,
    refresh_audio: bool = False,
    client=None,
) -> tuple[int, str]:
    """Write one ``asset_acoustics`` row, measured on canonical audio when available.

    Preferred path: measure level-A features on the asset's **canonical audio**
    (one file, no consensus). Fallback: the reel-slice **consensus** over up to *max_reels*
    reels — used when canonical audio is unavailable (deleted / user-original / ``--no-fetch``
    with nothing cached). Returns ``(n_signals_used, audio_source)``; raises only when neither
    canonical audio nor reel media exists (so the caller marks the asset ``failed``).
    """
    meta = _canonical_meta(
        conn, cfg, asset_id, fetch=fetch, refresh_audio=refresh_audio, client=client)
    canonical_path = _canonical_usable(meta, cfg, asset_id)

    if canonical_path:
        row = extract_features_from_file(canonical_path)
        source = meta["audio_source"]
        if meta.get("duration_real_s"):
            row["duration"] = meta["duration_real_s"]
        row["n_reels_consensus"] = None
        n = 1
    else:
        media = _reel_media(conn, cfg, asset_id)
        if not media:
            raise FileNotFoundError(f"no canonical audio and no reel media for asset {asset_id}")
        feats: list[dict] = []
        for pk, mp4 in media[:max_reels]:
            wav = cfg.audio_cache_dir / f"{pk}.wav"
            extract_audio(mp4, wav, overwrite=overwrite_audio)
            feats.append(extract_features_from_file(wav))
        row = consensus(feats)
        row["n_reels_consensus"] = len(feats)
        source = "reel_consensus"
        n = len(feats)

    row["asset_id"] = asset_id
    row["audio_source"] = source
    row["extractor_version"] = EXTRACTOR_VERSION
    row["param_hash"] = param_hash(extraction_params())
    _write_asset_acoustics(conn, row)
    return n, source


def _write_asset_acoustics(conn: sqlite3.Connection, row: dict) -> None:
    """Upsert one row into ``asset_acoustics`` (keeps acoustic_cluster, filled later)."""
    cols = [
        "asset_id", "tempo", "tempo_confidence", "est_key", "est_key_confidence",
        "est_key_alt", "est_key_alt_confidence", "key_agreement",
        "spectral_centroid", "spectral_rolloff", "spectral_bandwidth", "spectral_flatness",
        "rms", "loudness_lufs", "dynamic_range", "mfcc_summary", "duration",
        "n_segments", "segment_boundaries", "harmonic_change_rate",
        "n_reels_consensus", "audio_source", "extractor_version", "param_hash",
    ]
    placeholders = ",".join("?" * len(cols))
    conn.execute(
        f"INSERT OR REPLACE INTO asset_acoustics ({','.join(cols)}) VALUES ({placeholders})",
        [row.get(c) for c in cols],
    )
    conn.commit()


def run(
    conn: sqlite3.Connection,
    cfg: AvConfig | None = None,
    *,
    limit: int | None = None,
    include_failed: bool = False,
    max_reels: int = DEFAULT_MAX_REELS,
    fetch: bool = True,
    refresh_audio: bool = False,
    client=None,
    progress: bool = False,
) -> dict[str, int]:
    """Extract level-A features for all pending assets; return final state counts.

    By default each asset is measured on its **canonical audio**, fetched once via the
    network ladder. ``fetch=False`` (``--no-fetch``) uses only already-downloaded
    canonical files, else the reel-slice consensus — and never touches the network.
    """
    cfg = cfg or default_config()

    if fetch and client is None:
        try:
            client = asset_audio.build_client()
        except Exception as exc:  # noqa: BLE001
            if progress:
                print(f"  [extract-acoustic] canonical-audio fetch disabled: {exc}", flush=True)
            fetch = False

    state.init_state(conn, state.ACOUSTIC_STATE, discover_assets(conn))
    todo = state.pending_keys(
        conn, state.ACOUSTIC_STATE, include_failed=include_failed, limit=limit)
    total = len(todo)
    for i, asset_id in enumerate(todo, 1):
        try:
            n, source = extract_asset(
                conn, cfg, asset_id, max_reels=max_reels,
                fetch=fetch, refresh_audio=refresh_audio, client=client)
            unit = "reels" if source == "reel_consensus" else "file"
            state.set_status(conn, state.ACOUSTIC_STATE, asset_id, "done",
                             detail=f"{source} ({n} {unit})")
            note = f"done [{source}] ({n} {unit})"
        except Exception as exc:  # noqa: BLE001
            state.set_status(conn, state.ACOUSTIC_STATE, asset_id, "failed",
                             detail=f"{type(exc).__name__}: {exc}")
            note = f"FAILED ({type(exc).__name__})"
        if progress:
            print(f"  [{i}/{total}] {asset_id}: {note}", flush=True)
    return state.status_counts(conn, state.ACOUSTIC_STATE)
