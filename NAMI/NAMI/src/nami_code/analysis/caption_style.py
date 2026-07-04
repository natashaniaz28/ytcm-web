from __future__ import annotations
import re
import pandas as pd
from nami_code.analysis import analyse as A

EMOJI_RE = re.compile("[\U00010000-\U0010ffff]", flags=re.UNICODE)
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")


def add_caption_features(df: pd.DataFrame, schema: dict | None = None) -> pd.DataFrame:
    """
    Add columns describing each caption: its length, hashtag count, emoji and script use, and a rough caption 'type'.
    """
    out = df.copy()
    cap = out["caption_text"].fillna("").astype(str)
    out["caption_len"] = cap.str.len()
    out["has_caption"] = out["caption_len"] > 0
    out["n_hashtags"] = out["hashtags"].map(lambda xs: len(xs or []))
    out["emoji_count"] = cap.map(lambda x: len(EMOJI_RE.findall(x)))
    out["has_japanese_script"] = cap.map(lambda x: bool(JAPANESE_RE.search(x)))
    out["has_latin_script"] = cap.map(lambda x: bool(LATIN_RE.search(x)))
    out["caption_type"] = "sentence_or_mixed"
    out.loc[~out["has_caption"], "caption_type"] = "no_caption"
    out.loc[(out["has_caption"]) & (out["n_hashtags"] > 0) & (out["caption_len"] <= out["n_hashtags"] * 25), "caption_type"] = "mostly_hashtags"
    out.loc[(out["has_japanese_script"]) & ~(out["has_latin_script"]), "caption_type"] = "japanese_script"
    if schema is not None:
        for dim in A.schema_dimensions(schema):
            col = f"{dim}_categories"
            if col not in out:
                continue
            unk = schema["dimensions"][dim]["unknown_id"]
            out[f"{dim}_classifiable"] = out[col].apply(lambda xs: set(xs) != {unk})
    return out


def caption_style_summary(df: pd.DataFrame, schema: dict) -> pd.DataFrame:
    """
    Summarise reels grouped by caption type, including how often each type can be classified.
    """
    work = add_caption_features(df, schema)
    rows = []
    for ctype, sub in work.groupby("caption_type"):
        rec = {
            "caption_type": ctype,
            "n_reels": len(sub),
            "median_caption_len": sub["caption_len"].median(),
            "median_hashtags": sub["n_hashtags"].median(),
            "japanese_script_share": float(sub["has_japanese_script"].mean()) if len(sub) else 0.0,
        }
        for dim in A.schema_dimensions(schema):
            col = f"{dim}_classifiable"
            if col in sub:
                rec[f"{dim}_classifiable_share"] = float(sub[col].mean()) if len(sub) else 0.0
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("n_reels", ascending=False)
