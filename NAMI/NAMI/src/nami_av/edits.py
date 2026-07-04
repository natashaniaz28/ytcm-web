"""
Template / edit-provenance detection, part 1 — cut detection + cross-reel alignment.

Per reel we detect the visual **cuts** (PySceneDetect ``ContentDetector``, ported from
``ytcm-AV.ipynb`` cell 55 and re-tuned for short reels), then place those cut times on the
asset's **shared audio timeline** by adding the reel's alignment offset
(``reel_acoustics.used_segment_start``). Results land in ``reel_edits``, driven by
``edit_state``.

Part 2 groups an asset's reels into **near-identical edit clusters** — DBSCAN over the
Chamfer distance between their **song-aligned** cut patterns, restricted to confidently
aligned reels — writing ``reel_edits.edit_cluster``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from . import EXTRACTOR_VERSION, state
from .config import AvConfig, default_config, param_hash

DEFAULT_THRESHOLD = 27.0

DEFAULT_EPS = 0.5
DEFAULT_MIN_SAMPLES = 2
_EMPTY_DISTANCE = 999.0

SOFT_SAMPLE_FPS = 4.0
SOFT_DIFF_THRESHOLD = 0.15
SOFT_MIN_SPAN_S = 0.4
SOFT_MERGE_TOL_S = 0.5


def edit_params(threshold: float) -> dict:
    return {"detector": "ContentDetector", "threshold": threshold,
            "soft_sample_fps": SOFT_SAMPLE_FPS, "soft_diff_threshold": SOFT_DIFF_THRESHOLD,
            "soft_min_span_s": SOFT_MIN_SPAN_S, "soft_merge_tol_s": SOFT_MERGE_TOL_S,
            "extractor_version": EXTRACTOR_VERSION}


def _video_meta(path: Path) -> tuple[float, float]:
    """(fps, duration_seconds) read straight from the container via OpenCV."""
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0.0
    finally:
        cap.release()
    return fps, (frames / fps if fps else 0.0)


def detect_cuts(video_path: str | Path, threshold: float = DEFAULT_THRESHOLD
                ) -> tuple[list[float], float, float]:
    """Return (cut_times_seconds, fps, duration) for *video_path*.

    Cut times are the boundaries *between* detected scenes (reel-local seconds); a video
    with no detected scene change yields an empty list. fps/duration come from the
    container so they are populated even when there are zero cuts.
    """
    from scenedetect import ContentDetector, detect

    path = Path(video_path)
    scenes = detect(str(path), ContentDetector(threshold=threshold))
    cuts = [round(scenes[i][0].seconds, 4) for i in range(1, len(scenes))]
    fps, duration = _video_meta(path)
    return cuts, fps, duration


def _frame_hists(frame) -> list:
    """Normalised hue / saturation / value histograms for one BGR frame.

    Three channels rather than one so the pass notices both a hue crossfade (two scenes of
    similar brightness dissolving) and a brightness fade or zoom (composition shifting while
    the colours stay put) — whichever channel moves, we see it.
    """
    import cv2

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hists = []
    for ch, bins, rng in ((0, 50, [0, 180]), (1, 60, [0, 256]), (2, 64, [0, 256])):
        h = cv2.calcHist([hsv], [ch], None, [bins], rng)
        cv2.normalize(h, h, 0, 1, cv2.NORM_MINMAX)
        hists.append(h)
    return hists


def _runs_to_soft_times(times: list[float], diffs: list[float],
                        threshold: float, min_span: float) -> list[float]:
    """Collapse runs of sustained histogram drift into one soft-transition time each.

    A single elevated sample is a hard cut's signature and is ignored here; only a run that
    stays elevated across at least *min_span* seconds — a change that takes time, i.e. a
    dissolve or zoom — is kept, reported at the run's midpoint.
    """
    out: list[float] = []
    run: list[float] = []

    def _flush():
        if len(run) >= 2 and (run[-1] - run[0]) >= min_span:
            out.append(0.5 * (run[0] + run[-1]))

    for t, d in zip(times, diffs):
        if d >= threshold:
            run.append(t)
        else:
            _flush()
            run = []
    _flush()
    return out


def detect_soft_transitions(
    video_path: str | Path,
    cuts: list[float] | None = None,
    *,
    threshold: float = SOFT_DIFF_THRESHOLD,
    sample_fps: float = SOFT_SAMPLE_FPS,
    min_span: float = SOFT_MIN_SPAN_S,
    merge_tol: float = SOFT_MERGE_TOL_S,
) -> list[float]:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
        if fps <= 0:
            return []
        stride = max(1, int(round(fps / sample_fps)))
        prev = None
        times: list[float] = []
        diffs: list[float] = []
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % stride == 0:
                hists = _frame_hists(frame)
                if prev is not None:
                    d = max(
                        float(cv2.compareHist(prev[c], hists[c], cv2.HISTCMP_BHATTACHARYYA))
                        for c in range(len(hists)))
                    diffs.append(d)
                    times.append(idx / fps)
                prev = hists
            idx += 1
    finally:
        cap.release()

    soft = _runs_to_soft_times(times, diffs, threshold, min_span)
    if cuts:
        soft = [t for t in soft if min(abs(t - c) for c in cuts) > merge_tol]
    return [round(t, 4) for t in soft]


def _audio_offset(conn: sqlite3.Connection, reel_pk: str) -> float:
    """The reel's audio offset on the shared timeline, or 0.0 if not aligned."""
    row = conn.execute(
        "SELECT used_segment_start FROM reel_acoustics WHERE reel_pk=?", (reel_pk,)
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else 0.0


def align_cuts(cuts: list[float], offset: float) -> list[float]:
    """Shift reel-local cut times onto the shared timeline by the audio *offset*."""
    return [round(c + offset, 4) for c in cuts]


def _reels_with_media(conn: sqlite3.Connection, cfg: AvConfig) -> list[tuple[str, str, Path]]:
    """(reel_pk, asset_id, mp4) for reels whose MP4 exists on disk."""
    rows = conn.execute(
        "SELECT reel_pk, asset_id FROM reels WHERE asset_id IS NOT NULL ORDER BY reel_pk"
    ).fetchall()
    out = []
    for pk, asset_id in rows:
        mp4 = cfg.reels_dir / f"{pk}.mp4"
        if mp4.exists() and mp4.stat().st_size > 0:
            out.append((pk, asset_id, mp4))
    return out


def _write_reel_edits(conn: sqlite3.Connection, row: dict) -> None:
    cols = ["reel_pk", "asset_id", "cut_times", "cut_times_aligned", "n_cuts",
            "soft_times", "soft_times_aligned", "n_soft",
            "fps", "duration", "detector_threshold", "extractor_version", "param_hash"]
    conn.execute(
        f"INSERT OR REPLACE INTO reel_edits ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})",
        [row.get(c) for c in cols],
    )
    conn.commit()


def detect_reel(conn: sqlite3.Connection, reel_pk: str, asset_id: str, mp4: Path,
                *, threshold: float = DEFAULT_THRESHOLD) -> int:
    """Detect + align one reel's cuts and soft transitions, write its ``reel_edits`` row.

    Returns the hard-cut count. The histogram-based soft transitions are stored alongside in
    their own columns; they never change ``cut_times`` or the count the clustering relies on.
    """
    cuts, fps, duration = detect_cuts(mp4, threshold)
    offset = _audio_offset(conn, reel_pk)
    aligned = align_cuts(cuts, offset)
    soft = detect_soft_transitions(mp4, cuts)
    soft_aligned = align_cuts(soft, offset)
    _write_reel_edits(conn, {
        "reel_pk": reel_pk, "asset_id": asset_id,
        "cut_times": json.dumps(cuts), "cut_times_aligned": json.dumps(aligned),
        "n_cuts": len(cuts),
        "soft_times": json.dumps(soft), "soft_times_aligned": json.dumps(soft_aligned),
        "n_soft": len(soft),
        "fps": round(fps, 4), "duration": round(duration, 4),
        "detector_threshold": threshold, "extractor_version": EXTRACTOR_VERSION,
        "param_hash": param_hash(edit_params(threshold)),
    })
    return len(cuts)


def run(
    conn: sqlite3.Connection,
    cfg: AvConfig | None = None,
    *,
    limit: int | None = None,
    include_failed: bool = False,
    threshold: float = DEFAULT_THRESHOLD,
    progress: bool = False,
) -> dict[str, int]:
    """Detect + align cuts for all pending reels; return final ``edit_state`` counts."""
    cfg = cfg or default_config()
    targets = _reels_with_media(conn, cfg)
    state.init_state(conn, state.EDIT_STATE, [pk for pk, _, _ in targets])
    pending = set(state.pending_keys(
        conn, state.EDIT_STATE, include_failed=include_failed, limit=limit))
    todo = [t for t in targets if t[0] in pending]
    for i, (pk, asset_id, mp4) in enumerate(todo, 1):
        try:
            detect_reel(conn, pk, asset_id, mp4, threshold=threshold)
            state.set_status(conn, state.EDIT_STATE, pk, "done")
        except Exception as exc:  # noqa: BLE001
            state.set_status(conn, state.EDIT_STATE, pk, "failed",
                             f"{type(exc).__name__}: {exc}")
        if progress and (i % 50 == 0 or i == len(todo)):
            print(f"  detect-edits: {i}/{len(todo)} reels", flush=True)
    return state.status_counts(conn, state.EDIT_STATE)


def chamfer_distance(a: list[float], b: list[float]) -> float:
    """Symmetric Chamfer distance (mean nearest-neighbour) between two cut-time sets.

    Two identical patterns -> 0; both empty -> 0 (same "no-cut" pattern); exactly one
    empty -> a large constant so they never cluster together.
    """
    if not a and not b:
        return 0.0
    if not a or not b:
        return _EMPTY_DISTANCE
    a_arr, b_arr = np.asarray(a, float), np.asarray(b, float)
    a_to_b = np.mean([np.min(np.abs(b_arr - x)) for x in a_arr])
    b_to_a = np.mean([np.min(np.abs(a_arr - x)) for x in b_arr])
    return float(0.5 * (a_to_b + b_to_a))


def _distance_matrix(cut_lists: list[list[float]]) -> np.ndarray:
    n = len(cut_lists)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            d = chamfer_distance(cut_lists[i], cut_lists[j])
            D[i, j] = D[j, i] = d
    return D


def cluster_cut_patterns(cut_lists: list[list[float]], *, eps: float = DEFAULT_EPS,
                         min_samples: int = DEFAULT_MIN_SAMPLES) -> np.ndarray:
    """DBSCAN labels over the Chamfer distance matrix; -1 = noise (one-off / organic)."""
    from sklearn.cluster import DBSCAN

    if not cut_lists:
        return np.array([], dtype=int)
    D = _distance_matrix(cut_lists)
    return DBSCAN(eps=eps, min_samples=min_samples, metric="precomputed").fit_predict(D)


def cluster_asset_edits(conn: sqlite3.Connection, asset_id: str, *,
                        eps: float = DEFAULT_EPS,
                        min_samples: int = DEFAULT_MIN_SAMPLES) -> dict:
    """Group one asset's reels into near-identical edit clusters by **song-aligned** cuts.

    A reel takes part only if it (a) has >=1 detected cut — a static / single-shot reel has
    no edit to share — **and** (b) is confidently placed on the song's timeline: it has a
    ``reel_acoustics`` segment offset and is not flagged ``has_overlay`` (added audio makes
    its alignment, hence its segment, untrustworthy). Matching is on **song-aligned** cut
    times (``cut_times_aligned`` = reel-local cut + the reel's segment offset), so two reels
    that merely share an *elapsed-time* cadence while using **different parts of the song** do
    NOT group — only reels editing the *same passage the same way* do. Among the eligible
    reels, DBSCAN over the Chamfer distance groups near-identical patterns (cuts within
    ``eps`` seconds count as the same); a reel matching no group is noise (``-1``). Reels that
    are zero-cut or not confidently aligned get ``edit_cluster = NULL`` and sit out.
    """
    rows = conn.execute(
        "SELECT re.reel_pk, re.cut_times_aligned, ra.used_segment_start, ra.has_overlay "
        "FROM reel_edits re LEFT JOIN reel_acoustics ra ON ra.reel_pk = re.reel_pk "
        "WHERE re.asset_id=? ORDER BY re.reel_pk", (asset_id,)).fetchall()
    cut_pks: list[str] = []
    cut_lists: list[list[float]] = []
    ungrouped_pks: list[str] = []
    for pk, cta, seg_start, has_overlay in rows:
        cuts = json.loads(cta) if cta else []
        aligned_ok = seg_start is not None and not has_overlay
        if cuts and aligned_ok:
            cut_pks.append(pk)
            cut_lists.append(cuts)
        else:
            ungrouped_pks.append(pk)

    labels = (cluster_cut_patterns(cut_lists, eps=eps, min_samples=min_samples)
              if cut_lists else [])
    for pk, lab in zip(cut_pks, labels):
        conn.execute("UPDATE reel_edits SET edit_cluster=? WHERE reel_pk=?", (int(lab), pk))
    for pk in ungrouped_pks:
        conn.execute("UPDATE reel_edits SET edit_cluster=NULL WHERE reel_pk=?", (pk,))
    conn.commit()

    group_labels = {int(lab) for lab in labels if lab != -1}
    return {
        "asset_id": asset_id,
        "n_reels": len(rows),
        "n_groups": len(group_labels),
        "n_grouped_reels": int(sum(1 for lab in labels if lab != -1)),
    }


def run_grouping(
    conn: sqlite3.Connection,
    cfg: AvConfig | None = None,
    *,
    eps: float = DEFAULT_EPS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    progress: bool = False,
) -> dict:
    """Group every asset's reels into near-identical edit clusters; return run totals."""
    assets = [r[0] for r in conn.execute(
        "SELECT DISTINCT asset_id FROM reel_edits WHERE asset_id IS NOT NULL ORDER BY asset_id"
    ).fetchall()]
    totals = {"n_assets": len(assets), "n_groups": 0, "n_grouped_reels": 0}
    for i, asset_id in enumerate(assets, 1):
        s = cluster_asset_edits(conn, asset_id, eps=eps, min_samples=min_samples)
        totals["n_groups"] += s["n_groups"]
        totals["n_grouped_reels"] += s["n_grouped_reels"]
        if progress and (i % 25 == 0 or i == len(assets)):
            print(f"  group-edits: clustered {i}/{len(assets)} assets", flush=True)
    return totals
