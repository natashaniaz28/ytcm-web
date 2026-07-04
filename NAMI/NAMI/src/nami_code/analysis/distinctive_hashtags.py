"""
Distinctive hashtags: song-/asset-specific hashtag signals.
"""

from __future__ import annotations

from collections import Counter
import math

import pandas as pd

from nami_code.domain_config import load_domain_config

GENERIC_STOPLIST_FALLBACK = {
    "fyp",
    "viral",
    "reels",
    "reel",
    "instagram",
    "insta",
    "explore",
    "explorepage",
    "trending",
    "trend",
}


def load_distinctive_hashtag_stoplist(
    domain_config: dict | None = None,
    domain_path: str = "config/domain.yaml",
) -> set[str]:
    """
    Load distinctive-hashtag stop terms from domain config.

    Missing domain config intentionally falls back to a short neutral list only;
    project-specific stop terms belong in config/domain.yaml.
    """

    if domain_config is None:
        domain_config = load_domain_config(domain_path)

    section = domain_config.get("hashtag_stoplist", {}) if isinstance(domain_config, dict) else {}
    terms: list[str] = []
    if isinstance(section, dict):
        value = section.get("distinctive", section.get("default", []))
        if isinstance(value, list):
            terms = value
    elif isinstance(section, list):
        terms = section

    if not terms:
        return set(GENERIC_STOPLIST_FALLBACK)
    return {str(term).lower().strip().lstrip("#") for term in terms if str(term).strip()}


def _flat_tags(rows, stoplist: set[str] | None = None) -> list[str]:
    """
    Flatten many reels' hashtag lists into one cleaned list, dropping stopwords and very short tags.
    """
    stop = stoplist or set()
    out: list[str] = []
    for tags in rows:
        for t in tags or []:
            t = str(t).lower().strip().lstrip("#")
            if t and t not in stop and len(t) > 1:
                out.append(t)
    return out


def distinctive_hashtags(
    df: pd.DataFrame,
    group_col: str = "song_id",
    min_count: int = 3,
    top_n: int = 25,
    stoplist: set[str] | None = None,
    alpha: float = 0.5,
    domain_config: dict | None = None,
    domain_path: str = "config/domain.yaml",
) -> pd.DataFrame:
    """
    Calculate distinctive hashtags per group against the rest of the corpus.
    """

    if df.empty or group_col not in df.columns:
        return pd.DataFrame()
    stop = load_distinctive_hashtag_stoplist(domain_config, domain_path) | (stoplist or set())
    all_tags = _flat_tags(df["hashtags"], stop)
    global_counts = Counter(all_tags)
    global_total = sum(global_counts.values())
    rows: list[dict] = []
    for group, sub in df.groupby(group_col):
        group_tags = _flat_tags(sub["hashtags"], stop)
        gc = Counter(group_tags)
        group_total = sum(gc.values())
        other_total = max(global_total - group_total, 0)
        if group_total == 0:
            continue
        vocab = set(gc) | set(global_counts)
        for tag in vocab:
            n_group = gc.get(tag, 0)
            if n_group < min_count:
                continue
            n_total = global_counts.get(tag, 0)
            n_other = max(n_total - n_group, 0)
            odds_group = (n_group + alpha) / (group_total - n_group + alpha)
            odds_other = (n_other + alpha) / (other_total - n_other + alpha)
            log_odds = math.log(odds_group / odds_other) if odds_other > 0 else 0.0
            share_group = n_group / group_total if group_total else 0.0
            share_other = n_other / other_total if other_total else 0.0
            lift = share_group / share_other if share_other > 0 else float("inf")
            rows.append({
                group_col: group,
                "hashtag": tag,
                "n_group": n_group,
                "n_other": n_other,
                "share_group": share_group,
                "share_other": share_other,
                "lift": lift,
                "log_odds": log_odds,
            })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out = out.sort_values([group_col, "log_odds", "n_group"], ascending=[True, False, False])
    return out.groupby(group_col, as_index=False).head(top_n).reset_index(drop=True)


def top_distinctive_by_song(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    Find the hashtags most distinctive to each song.
    """
    return distinctive_hashtags(df, group_col="song_id", **kwargs)


def top_distinctive_by_asset(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """
    Find the hashtags most distinctive to each audio variant.
    """
    return distinctive_hashtags(df, group_col="asset_id", **kwargs)
