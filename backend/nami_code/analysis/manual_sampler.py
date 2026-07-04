from __future__ import annotations

from pathlib import Path
from typing import Any
import html
import warnings

import pandas as pd

from nami_code.domain_config import load_domain_config, load_schema_config


def _cats(row, dim: str) -> list[str]:
    """
    Return a reel's category list for a dimension, or an empty list.
    """
    val = row.get(f"{dim}_categories", [])
    return val if isinstance(val, list) else []


DEFAULT_DOMAIN_PATH = "config/domain.yaml"
DEFAULT_SCHEMA_PATH = "config/schema.yaml"


def _resolve_config_ref(config: dict[str, Any], ref: str | None) -> Any:
    """
    Resolve a simple dot-path reference inside a config mapping.
    """

    if not ref or not isinstance(config, dict):
        return None
    cur: Any = config
    for part in str(ref).split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _load_sampling_domain(domain_config: dict[str, Any] | None = None, domain_path: str | Path = DEFAULT_DOMAIN_PATH) -> dict[str, Any]:
    """
    Return the domain settings, using the ones passed in or loading them from disk.
    """
    if domain_config is not None:
        return domain_config if isinstance(domain_config, dict) else {}
    return load_domain_config(domain_path)


def _load_sampling_schema(schema: dict[str, Any] | None = None, schema_path: str | Path = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    """
    Return the schema, using the one passed in or loading it from disk.
    """
    if schema is not None:
        return schema if isinstance(schema, dict) else {}
    return load_schema_config(schema_path)


def _schema_category_ids(schema: dict[str, Any], dimension: str = "context") -> set[str]:
    """
    Return the valid category ids for one dimension of the schema.
    """
    dim = schema.get("dimensions", {}).get(dimension, {}) if isinstance(schema, dict) else {}
    cats = dim.get("categories", {}) if isinstance(dim, dict) else {}
    return set(cats) if isinstance(cats, dict) else set()


def _filter_valid_contexts(contexts: list[str], valid_contexts: set[str], source: str) -> list[str]:
    """
    Keep only the context ids that exist in the schema, warning about any unknown ones.
    """
    if not contexts:
        return []
    if not valid_contexts:
        return [str(c) for c in contexts if c]
    valid: list[str] = []
    invalid: list[str] = []
    for ctx in contexts:
        ctx_str = str(ctx)
        if ctx_str in valid_contexts:
            valid.append(ctx_str)
        else:
            invalid.append(ctx_str)
    if invalid:
        warnings.warn(
            f"Sampling config {source} contains unknown context id(s): {', '.join(invalid)}",
            RuntimeWarning,
            stacklevel=2,
        )
    return valid


def _coerce_terms(value: Any) -> list[str]:
    """
    Return the value as a clean lowercased list of terms, or an empty list.
    """
    if not isinstance(value, list):
        return []
    return [str(v).lower() for v in value if str(v)]


def load_sampling_config(
    domain_config: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    domain_path: str | Path = DEFAULT_DOMAIN_PATH,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
) -> dict[str, Any]:
    """
    Load and validate close-reading sampling settings from domain.yaml.

    Invalid context ids warn and are ignored. Missing domain.yaml yields neutral
    empty sampling lists so the regular non-curated sampling path still works.
    """

    domain = _load_sampling_domain(domain_config, domain_path)
    schema_cfg = _load_sampling_schema(schema, schema_path)
    sampling = domain.get("sampling", {}) if isinstance(domain, dict) else {}
    if not isinstance(sampling, dict):
        sampling = {}

    valid_contexts = _schema_category_ids(schema_cfg, "context")
    default_contexts = _filter_valid_contexts(
        [str(c) for c in sampling.get("default_contexts", []) if str(c)],
        valid_contexts,
        "sampling.default_contexts",
    )

    raw_visual_contexts = sampling.get("visual_contexts", sampling.get("visual_world_contexts", []))
    visual_contexts = _filter_valid_contexts(
        [str(c) for c in raw_visual_contexts if str(c)] if isinstance(raw_visual_contexts, list) else [],
        valid_contexts,
        "sampling.visual_contexts",
    )

    raw_music_terms = sampling.get("music_discourse_terms")
    if raw_music_terms is None:
        raw_music_terms = _resolve_config_ref(domain, sampling.get("music_discourse_terms_ref"))
    if raw_music_terms is None:
        audio_filter = domain.get("audio_filter", {}) if isinstance(domain, dict) else {}
        if isinstance(audio_filter, dict):
            raw_music_terms = audio_filter.get("music_discourse_terms")
            if raw_music_terms is None:
                raw_music_terms = _resolve_config_ref(domain, audio_filter.get("music_discourse_terms_ref"))
    music_terms = _coerce_terms(raw_music_terms)

    raw_slots = sampling.get("curated_slots", [])
    slots: list[dict[str, Any]] = []
    if isinstance(raw_slots, list):
        for idx, raw in enumerate(raw_slots):
            if not isinstance(raw, dict):
                warnings.warn(f"Sampling config curated_slots[{idx}] is not a mapping", RuntimeWarning, stacklevel=2)
                continue
            slot = dict(raw)
            contexts = slot.get("contexts", [])
            if not isinstance(contexts, list):
                warnings.warn(
                    f"Sampling config slot '{slot.get('slot', idx)}' has non-list contexts",
                    RuntimeWarning,
                    stacklevel=2,
                )
                contexts = []
            slot["contexts"] = _filter_valid_contexts(
                [str(c) for c in contexts if str(c)],
                valid_contexts,
                f"sampling.curated_slots[{slot.get('slot', idx)}].contexts",
            )
            keywords = slot.get("keywords", [])
            slot["keywords"] = [str(k).lower() for k in keywords if str(k)] if isinstance(keywords, list) else []
            try:
                slot["n"] = int(slot.get("n", 3))
            except (TypeError, ValueError):
                warnings.warn(
                    f"Sampling config slot '{slot.get('slot', idx)}' has invalid n; using 3",
                    RuntimeWarning,
                    stacklevel=2,
                )
                slot["n"] = 3
            slots.append(slot)
    elif raw_slots is not None:
        warnings.warn("Sampling config sampling.curated_slots must be a list", RuntimeWarning, stacklevel=2)

    return {
        "random_state": int(sampling.get("random_state", 42) or 42),
        "default_contexts": default_contexts,
        "visual_contexts": visual_contexts,
        "music_discourse_terms": music_terms,
        "curated_slots": slots,
    }


def validate_sampling_config(
    domain_config: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
    domain_path: str | Path = DEFAULT_DOMAIN_PATH,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
) -> list[str]:
    """
    Return validation warnings for sampling settings without raising.
    """

    found: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        load_sampling_config(domain_config, schema, domain_path, schema_path)
    for warning in caught:
        found.append(str(warning.message))
    return found


def sample_by_song(df: pd.DataFrame, n_top: int = 3, n_median: int = 2, n_random: int = 3, random_state: int = 42) -> pd.DataFrame:
    """
    Pick example reels for each song: a few top performers, a few middling, and a few at random.
    """
    rows = []
    for song_id, sub in df.groupby("song_id", dropna=False):
        sub = sub.copy().sort_values("impact_metric", ascending=False)
        if sub.empty:
            continue
        top = sub.head(n_top).assign(sample_reason="top_impact")
        rows.append(top)
        if len(sub) > 2:
            mid_idx = (sub["impact_metric"] - sub["impact_metric"].median()).abs().sort_values().head(n_median).index
            rows.append(sub.loc[mid_idx].assign(sample_reason="median_impact"))
        remain = sub.drop(index=pd.concat(rows).index.intersection(sub.index), errors="ignore") if rows else sub
        if not remain.empty:
            rows.append(remain.sample(min(n_random, len(remain)), random_state=random_state).assign(sample_reason="random"))
    out = pd.concat(rows, ignore_index=False).drop_duplicates("reel_pk") if rows else pd.DataFrame()
    return _format_sample(out)


def sample_by_context(
    df: pd.DataFrame,
    contexts: list[str] | None = None,
    n_per_context: int = 5,
    random_state: int = 42,
    domain_config: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Pick the top example reels for each named context category.
    """
    if contexts is None:
        contexts = load_sampling_config(domain_config=domain_config, schema=schema)["default_contexts"]
    rows = []
    for ctx in contexts:
        mask = df["context_categories"].apply(lambda xs: ctx in set(xs or [])) if "context_categories" in df else pd.Series(False, index=df.index)
        sub = df.loc[mask].sort_values("impact_metric", ascending=False)
        if not sub.empty:
            rows.append(sub.head(n_per_context).assign(sample_reason=f"context:{ctx}"))
    out = pd.concat(rows, ignore_index=False).drop_duplicates("reel_pk") if rows else pd.DataFrame()
    return _format_sample(out)


def close_reading_sample(
    df: pd.DataFrame,
    domain_config: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Build a mixed sample of reels for close reading, combining per-song and per-context picks.
    """
    parts = [
        sample_by_song(df, n_top=2, n_median=1, n_random=1),
        sample_by_context(df, n_per_context=3, domain_config=domain_config, schema=schema),
    ]
    out = pd.concat([p for p in parts if not p.empty], ignore_index=True).drop_duplicates("reel_pk") if parts else pd.DataFrame()
    return out.sort_values(["song_id", "sample_reason", "impact_metric"], ascending=[True, True, False]) if not out.empty else out


def _format_sample(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tidy a sample into readable columns: categories joined, hashtags formatted, link included.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["sample_reason", "song_id", "variant_label", "asset_id", "reel_pk", "impact_metric", "context", "format", "caption_text", "hashtags", "instagram_url"])
    out = df.copy()
    out["context"] = out.apply(lambda r: ", ".join(_cats(r, "context")), axis=1)
    out["format"] = out.apply(lambda r: ", ".join(_cats(r, "format")), axis=1)
    out["hashtags"] = out["hashtags"].apply(lambda xs: " ".join(f"#{x}" for x in (xs or [])))
    cols = [c for c in ["sample_reason", "song_id", "variant_label", "asset_id", "reel_pk", "impact_metric", "like_count", "play_count", "comment_count", "context", "format", "caption_text", "hashtags", "instagram_url"] if c in out.columns]
    return out[cols]


def write_sample_html(sample: pd.DataFrame, out_path: str | Path) -> Path:
    """
    Write a sample of reels to a simple HTML page for qualitative review.
    """
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for _, r in sample.iterrows():
        cap = html.escape(str(r.get("caption_text", "")))[:1200]
        tags = html.escape(str(r.get("hashtags", "")))
        url = html.escape(str(r.get("instagram_url", "")))
        rows.append(f"""
        <article>
          <h3>{html.escape(str(r.get('song_id','')))} · {html.escape(str(r.get('sample_reason','')))}</h3>
          <p><b>Asset:</b> {html.escape(str(r.get('variant_label','')))} / {html.escape(str(r.get('asset_id','')))} · <b>Impact:</b> {html.escape(str(r.get('impact_metric','')))}</p>
          <p><b>Context:</b> {html.escape(str(r.get('context','')))}<br><b>Format:</b> {html.escape(str(r.get('format','')))}</p>
          <p>{cap}</p>
          <p class='tags'>{tags}</p>
          <p><a href='{url}'>Instagram Reel</a></p>
        </article>
        """)
    doc = """<!doctype html><meta charset='utf-8'><title>Close-reading sample</title>
    <style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:980px;margin:36px auto;line-height:1.5;padding:0 20px}article{border-top:1px solid #ddd;padding:18px 0}.tags{color:#555}</style>
    <h1>Close-reading sample</h1><p>Automatically generated selection for qualitative review.</p>
    """ + "\n".join(rows)
    p.write_text(doc, encoding="utf-8")
    return p


def _text_blob(row) -> str:
    """
    Join a reel's caption and hashtags into one lowercased string.
    """
    tags = row.get("hashtags", []) or []
    if not isinstance(tags, list):
        tags = []
    return (str(row.get("caption_text", "")) + " " + " ".join(str(t) for t in tags)).lower()


def _mask_context(df: pd.DataFrame, contexts: list[str]) -> pd.Series:
    """
    Return a yes/no marker selecting reels that fall in any of the given context categories.
    """
    if not contexts or "context_categories" not in df:
        return pd.Series(True, index=df.index)
    wanted = set(contexts)
    return df["context_categories"].apply(lambda xs: bool(wanted.intersection(set(xs or []))))


def _mask_keywords(df: pd.DataFrame, keywords: list[str]) -> pd.Series:
    """
    Return a yes/no marker selecting reels whose text contains any of the given keywords.
    """
    if not keywords:
        return pd.Series(True, index=df.index)
    pats = [str(k).lower() for k in keywords]
    return df.apply(lambda r: any(k in _text_blob(r) for k in pats), axis=1)


def _has_music_discourse(row, terms: list[str]) -> bool:
    """
    Return whether a reel's text mentions any music-talk term.
    """
    blob = _text_blob(row)
    return any(t in blob for t in terms)


def _has_visual_world(row, visual_contexts: list[str]) -> bool:
    """
    Return whether a reel falls into any of the visual-world context categories.
    """
    cats = set(row.get("context_categories", []) or [])
    return bool(cats.intersection(set(visual_contexts)))


def curated_close_reading_sample(
    df: pd.DataFrame,
    random_state: int = 42,
    domain_config: dict[str, Any] | None = None,
    schema: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Build a hand-designed close-reading sample, following the slots defined in the config.
    """
    sampling_config = load_sampling_config(domain_config=domain_config, schema=schema)
    slots = sampling_config.get("curated_slots", [])
    music_terms = sampling_config.get("music_discourse_terms", [])
    visual_contexts = sampling_config.get("visual_contexts", [])

    used: set = set()
    rows = []
    for slot in slots:
        sub = df.copy()
        if slot.get("song"):
            sub = sub[sub["song_id"] == slot["song"]]
        mode = slot.get("mode", "top")
        if mode == "random_visual_no_music":
            mask = sub.apply(
                lambda r: _has_visual_world(r, visual_contexts) and not _has_music_discourse(r, music_terms),
                axis=1,
            )
            sub = sub.loc[mask]
        else:
            sub = sub.loc[_mask_context(sub, slot.get("contexts", []))]
            kw_mask = _mask_keywords(sub, slot.get("keywords", []))
            sub_kw = sub.loc[kw_mask]
            if not sub_kw.empty:
                sub = sub_kw
        if "reel_pk" in sub:
            sub = sub[~sub["reel_pk"].isin(used)]
        if sub.empty:
            continue
        n = int(slot.get("n", 3))
        if mode.startswith("random"):
            pick = sub.sample(min(n, len(sub)), random_state=random_state)
        elif mode == "median":
            idx = (sub["impact_metric"] - sub["impact_metric"].median()).abs().sort_values().head(n).index
            pick = sub.loc[idx]
        else:
            pick = sub.sort_values("impact_metric", ascending=False).head(n)
        used.update(pick.get("reel_pk", pd.Series(dtype=str)).astype(str).tolist())
        rows.append(pick.assign(sample_reason="curated:" + str(slot["slot"])))
    out = pd.concat(rows, ignore_index=False).drop_duplicates("reel_pk") if rows else pd.DataFrame()
    return _format_sample(out.sort_values(["song_id", "sample_reason", "impact_metric"], ascending=[True, True, False]) if not out.empty else out)
