"""
Robustness and diagnostic checks for keyword classification.
"""

from __future__ import annotations

from collections import Counter
import pandas as pd

from nami_code.analysis import analyse as A
from nami_code.domain_config import load_domain_config

GENERIC_BROAD_KEYWORDS_FALLBACK = {"ai", "jp"}
DEFAULT_BROAD_KEYWORD_MAX_LENGTH = 3


def load_robustness_config(
    domain_config: dict | None = None,
    domain_path: str = "config/domain.yaml",
) -> dict:
    """
    Load robustness settings from domain config with neutral fallbacks.
    """

    if domain_config is None:
        domain_config = load_domain_config(domain_path)
    section = domain_config.get("robustness", {}) if isinstance(domain_config, dict) else {}
    if not isinstance(section, dict):
        section = {}

    terms = section.get("broad_keywords", section.get("broad_keyword_audit_terms", []))
    if isinstance(terms, list) and terms:
        broad_keywords = {str(term).lower().strip() for term in terms if str(term).strip()}
    else:
        broad_keywords = set(GENERIC_BROAD_KEYWORDS_FALLBACK)

    max_length = section.get("broad_keyword_max_length", DEFAULT_BROAD_KEYWORD_MAX_LENGTH)
    try:
        max_length = int(max_length)
    except (TypeError, ValueError):
        max_length = DEFAULT_BROAD_KEYWORD_MAX_LENGTH

    return {
        "broad_keyword_max_length": max_length,
        "broad_keywords": broad_keywords,
    }


def unknown_hashtags(df: pd.DataFrame, schema: dict, dim: str, top_n: int = 40) -> pd.DataFrame:
    """
    List the most common hashtags on reels that could not be classified on a dimension.
    """
    unk = schema["dimensions"][dim]["unknown_id"]
    mask = df[f"{dim}_categories"].apply(lambda xs: set(xs or []) == {unk}) if f"{dim}_categories" in df else pd.Series(False, index=df.index)
    c = Counter(t for tags in df.loc[mask, "hashtags"] for t in (tags or []))
    return pd.DataFrame([{"hashtag": k, "count": v} for k, v in c.most_common(top_n)])


def multicategory_reels(df: pd.DataFrame, dim: str, min_categories: int = 3, top_n: int = 100) -> pd.DataFrame:
    """
    Find reels that landed in many categories at once, which can signal over-broad keywords.
    """
    col = f"{dim}_categories"
    if col not in df:
        return pd.DataFrame()
    out = df[df[col].apply(lambda xs: len(set(xs or [])) >= min_categories)].copy()
    out["n_categories"] = out[col].apply(lambda xs: len(set(xs or [])))
    out["categories"] = out[col].apply(lambda xs: ", ".join(xs or []))
    cols = [c for c in ["reel_pk", "song_id", "variant_label", "impact_metric", "n_categories", "categories", "caption_text", "hashtags", "instagram_url"] if c in out]
    return out.sort_values("n_categories", ascending=False)[cols].head(top_n)


def keyword_audit(
    schema: dict,
    domain_config: dict | None = None,
    domain_path: str = "config/domain.yaml",
) -> pd.DataFrame:
    """
    List every keyword in the schema and flag the ones that look too short or too broad.
    """
    cfg = load_robustness_config(domain_config, domain_path)
    broad_keywords = cfg["broad_keywords"]
    max_length = cfg["broad_keyword_max_length"]
    rows = []
    for dim, spec in schema.get("dimensions", {}).items():
        for cat_id, cat in spec.get("categories", {}).items():
            for kw in cat.get("keywords", []):
                kw = str(kw)
                rows.append({
                    "dimension": dim,
                    "category": cat_id,
                    "keyword": kw,
                    "length": len(kw),
                    "tokens": len(kw.split()),
                    "potentially_broad": len(kw) <= max_length or kw.lower() in broad_keywords,
                })
    return pd.DataFrame(rows).sort_values(["potentially_broad", "dimension", "category", "keyword"], ascending=[False, True, True, True])


def validation_sample(df: pd.DataFrame, schema: dict, dim: str, n_per_category: int = 5, random_state: int = 42) -> pd.DataFrame:
    """
    Pick a few example reels per category so a person can check the keyword tagging by hand.
    """
    rows = []
    for cat_id in schema["dimensions"][dim].get("categories", {}).keys():
        mask = df[f"{dim}_categories"].apply(lambda xs: cat_id in set(xs or [])) if f"{dim}_categories" in df else pd.Series(False, index=df.index)
        sub = df.loc[mask]
        if not sub.empty:
            rows.append(sub.sample(min(n_per_category, len(sub)), random_state=random_state).assign(validation_category=cat_id, validation_dimension=dim))
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if out.empty:
        return out
    out["hashtags"] = out["hashtags"].apply(lambda xs: " ".join(f"#{x}" for x in (xs or [])))
    category_cols = [f"{d}_categories" for d in A.schema_dimensions(schema)]
    cols = [c for c in ["validation_dimension", "validation_category", "song_id", "reel_pk", *category_cols, "caption_text", "hashtags", "instagram_url"] if c in out]
    return out[cols]


def run_robustness(
    df: pd.DataFrame,
    schema: dict,
    domain_config: dict | None = None,
    domain_path: str = "config/domain.yaml",
    dimensions: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Run robustness diagnostics for configured schema dimensions.
    """
    dims = [d for d in (dimensions or A.schema_dimensions(schema)) if d in schema.get("dimensions", {})]
    out: dict[str, pd.DataFrame] = {
        "keyword_audit": keyword_audit(schema, domain_config=domain_config, domain_path=domain_path),
    }
    for dim in dims:
        out[f"unknown_{dim}_hashtags"] = unknown_hashtags(df, schema, dim)
        out[f"multicategory_{dim}_reels"] = multicategory_reels(df, dim)
        out[f"validation_sample_{dim}"] = validation_sample(df, schema, dim)
    return out
