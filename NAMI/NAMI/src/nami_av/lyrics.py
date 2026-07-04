"""
Refrain detection from timestamped lyrics (experimental).

Instagram's ``music_asset_info.lyrics`` stores ``{"phrases": [{"phrase", "start_time_in_ms",
"end_time_in_ms", "word_offsets":[...]}, …]}``. We treat the phrases as a line sequence,
find the **dominant repeated contiguous block** (the refrain) with *fuzzy* line matching, and
return the start time (seconds) of each occurrence — for marking on the tonnetz panel.

"Security" against coincidental matches: the repeated block must reach a minimum word count
and occur at least twice. Pure-Python (``difflib``), deterministic, unit-testable offline.
"""

from __future__ import annotations

import difflib
import json
import sqlite3
from collections import defaultdict

DEFAULT_SIM = 0.85
DEFAULT_MIN_WORDS = 6
DEFAULT_MIN_OCCURRENCES = 2
DEFAULT_MIN_LINES = 2
_SINGLE_LINE_WORDS = 8


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def parse_phrases(raw) -> list[tuple[str, float, int]]:
    """``lyrics`` json → ``[(text, start_ms, n_words), …]`` (empty if absent/unparseable)."""
    if not raw:
        return []
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    phrases = d.get("phrases") if isinstance(d, dict) else None
    if not isinstance(phrases, list):
        return []
    out = []
    for p in phrases:
        if not isinstance(p, dict):
            continue
        text, st = p.get("phrase"), p.get("start_time_in_ms")
        if text is None or st is None:
            continue
        wo = p.get("word_offsets")
        n_words = len(wo) if isinstance(wo, list) and wo else max(1, len(str(text).split()))
        out.append((str(text), float(st), int(n_words)))
    return out


def _fuzzy_labels(texts: list[str], sim: float) -> list[int]:
    """Assign each line an int label; fuzzily-similar lines share a label (greedy clustering)."""
    reps: list[str] = []
    labels: list[int] = []
    for t in texts:
        lab = None
        for i, rep in enumerate(reps):
            if difflib.SequenceMatcher(None, t, rep).ratio() >= sim:
                lab = i
                break
        if lab is None:
            lab = len(reps)
            reps.append(t)
        labels.append(lab)
    return labels


def _nonoverlap_occurrences(labels: list[int], pattern: tuple[int, ...]) -> list[int]:
    """Start indices of *pattern* in *labels*, scanning left→right without overlap."""
    n, m = len(labels), len(pattern)
    occ, i = [], 0
    while i <= n - m:
        if tuple(labels[i:i + m]) == pattern:
            occ.append(i)
            i += m
        else:
            i += 1
    return occ


def detect_refrain_starts(
    phrases: list[tuple[str, float, int]],
    *,
    sim_threshold: float = DEFAULT_SIM,
    min_words: int = DEFAULT_MIN_WORDS,
    min_occurrences: int = DEFAULT_MIN_OCCURRENCES,
    min_lines: int = DEFAULT_MIN_LINES,
) -> list[float]:
    """Start times (seconds) of each occurrence of the **dominant** repeated line-block.

    Dominant = max coverage (occurrences × block length), tie-broken by length then words.
    Returns ``[]`` when nothing passes the security threshold.
    """
    if len(phrases) < 2:
        return []
    texts = [_norm(p[0]) for p in phrases]
    starts_ms = [p[1] for p in phrases]
    words = [p[2] for p in phrases]
    labels = _fuzzy_labels(texts, sim_threshold)
    n = len(labels)

    candidates: set[tuple[int, ...]] = set()
    for i in range(n):
        for j in range(i + 1, n):
            if labels[i] != labels[j]:
                continue
            k = 0
            while j + k < n and i + k < j and labels[i + k] == labels[j + k]:
                k += 1
                candidates.add(tuple(labels[i:i + k]))

    best = None
    for pat in candidates:
        occ = _nonoverlap_occurrences(labels, pat)
        if len(occ) < min_occurrences:
            continue
        length = len(pat)
        total_words = sum(words[occ[0]:occ[0] + length])
        if length < min_lines and total_words < _SINGLE_LINE_WORDS:
            continue
        if total_words < min_words:
            continue
        cand = (len(occ) * length, length, total_words, occ)
        if best is None or cand[:3] > best[:3]:
            best = cand

    if best is None:
        return []
    return [starts_ms[i] / 1000.0 for i in best[3]]


def refrain_start_times(conn: sqlite3.Connection, asset_id: str,
                        **kw) -> tuple[list[float], bool]:
    """``(refrain_start_seconds, had_synced_lyrics)`` for *asset_id* from ``asset_music_meta``."""
    row = conn.execute(
        "SELECT lyrics FROM asset_music_meta WHERE asset_id=?", (asset_id,)).fetchone()
    phrases = parse_phrases(row[0]) if row else []
    if not phrases:
        return [], False
    return detect_refrain_starts(phrases, **kw), True
