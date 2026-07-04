"""
Audio-filter scoring based on configurable domain term lists.

The scoring logic is intentionally simple: captions and hashtags are checked
against configured term groups for music discourse and visual-world framing. The
terms live in config/domain.yaml so the same code can be reused by other NAMI
projects.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pandas as pd

from nami_code.domain_config import load_domain_config

DEFAULT_DOMAIN_PATH = "config/domain.yaml"


def _text(row: pd.Series) -> str:
    """
    Join a reel's caption and hashtags into one lowercased string.
    """
    return (str(row.get("caption_text", "")) + " " + " ".join(row.get("hashtags", []) or [])).lower()


def _term_hits(text: str, terms: list[str]) -> list[str]:
    """
    Return which of the given terms appear in the text.
    """
    hits = []
    for term in terms:
        t = term.lower()
        if re.search(re.escape(t), text):
            hits.append(term)
    return sorted(set(hits))


def _clean_terms(value: Any) -> list[str]:
    """
    Return a de-duplicated list of non-empty string terms.
    """

    if isinstance(value, dict):
        value = value.get("terms", [])
    if not isinstance(value, list):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        term = item.strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _resolve_ref(config: dict[str, Any], ref: Any) -> Any:
    """Resolve a simple dotted reference such as shared_terms.foo.terms."""

    if not isinstance(ref, str) or not ref.strip():
        return None

    current: Any = config
    for part in ref.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def load_audio_filter_terms(
    domain_config: dict[str, Any] | None = None,
    domain_path: str | Path | None = DEFAULT_DOMAIN_PATH,
) -> tuple[list[str], list[str]]:
    """Load music-discourse and visual-world terms from domain config.

    Missing config or missing terms is valid during the v4 migration and returns
    empty lists. This neutral fallback avoids keeping project-specific terms in
    Python.
    """

    config = domain_config if domain_config is not None else load_domain_config(domain_path or DEFAULT_DOMAIN_PATH)
    if not isinstance(config, dict) or not config:
        return [], []

    audio_cfg = config.get("audio_filter", {})
    if not isinstance(audio_cfg, dict) or audio_cfg.get("enabled", True) is False:
        return [], []

    music_terms = _clean_terms(audio_cfg.get("music_discourse_terms"))
    visual_terms = _clean_terms(audio_cfg.get("visual_world_terms"))

    if not music_terms:
        music_terms = _clean_terms(_resolve_ref(config, audio_cfg.get("music_discourse_terms_ref")))
    if not visual_terms:
        visual_terms = _clean_terms(_resolve_ref(config, audio_cfg.get("visual_world_terms_ref")))

    return music_terms, visual_terms


def add_audio_filter_scores(
    df: pd.DataFrame,
    music_terms: list[str] | None = None,
    visual_terms: list[str] | None = None,
    domain_config: dict[str, Any] | None = None,
    domain_path: str | Path | None = DEFAULT_DOMAIN_PATH,
) -> pd.DataFrame:
    """Add boolean and numeric audio-filter scores per reel."""

    out = df.copy()
    config_music_terms, config_visual_terms = load_audio_filter_terms(
        domain_config=domain_config,
        domain_path=domain_path,
    )
    mterms = music_terms if music_terms is not None else config_music_terms
    vterms = visual_terms if visual_terms is not None else config_visual_terms

    texts = out.apply(_text, axis=1)
    out["music_hits"] = texts.map(lambda t: _term_hits(t, mterms))
    out["visual_world_hits"] = texts.map(lambda t: _term_hits(t, vterms))
    out["music_discourse_score"] = out["music_hits"].map(len)
    out["visual_world_score"] = out["visual_world_hits"].map(len)
    out["has_music_discourse"] = out["music_discourse_score"] > 0
    out["has_visual_world"] = out["visual_world_score"] > 0
    out["audio_filter_use"] = out["has_visual_world"] & ~out["has_music_discourse"]
    out["audio_filter_index"] = out["visual_world_score"] - out["music_discourse_score"]
    return out


def audio_filter_summary(
    df: pd.DataFrame,
    group_col: str = "song_id",
    domain_config: dict[str, Any] | None = None,
    domain_path: str | Path | None = DEFAULT_DOMAIN_PATH,
) -> pd.DataFrame:
    """Aggregate audio-filter metrics per song or asset."""

    if df.empty:
        return pd.DataFrame()
    work = df if "audio_filter_use" in df.columns else add_audio_filter_scores(
        df,
        domain_config=domain_config,
        domain_path=domain_path,
    )
    rows = []
    for group, sub in work.groupby(group_col):
        n = len(sub)
        rows.append({
            group_col: group,
            "n_reels": n,
            "music_discourse_share": float(sub["has_music_discourse"].mean()) if n else 0.0,
            "visual_world_share": float(sub["has_visual_world"].mean()) if n else 0.0,
            "audio_filter_share": float(sub["audio_filter_use"].mean()) if n else 0.0,
            "median_audio_filter_index": float(sub["audio_filter_index"].median()) if n else 0.0,
            "median_plays": float(sub["play_count"].median()) if "play_count" in sub else 0.0,
        })
    return pd.DataFrame(rows).sort_values("audio_filter_share", ascending=False)
