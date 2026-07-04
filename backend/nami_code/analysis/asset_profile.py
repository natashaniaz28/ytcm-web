from __future__ import annotations
import pandas as pd
from nami_code.analysis import analyse as A
from nami_code.analysis.audio_filter_index import add_audio_filter_scores, audio_filter_summary


def asset_profile(df: pd.DataFrame, schema: dict, dim: str = "context") -> pd.DataFrame:
    """
    For each audio variant of each song, summarise its reels and how their categories are spread.
    """
    if df.empty:
        return pd.DataFrame()
    unk = schema["dimensions"][dim]["unknown_id"]
    labels = {cid: c["label"] for cid, c in schema["dimensions"][dim]["categories"].items()}
    rows = []
    for keys, sub in df.groupby(["song_id", "asset_id", "variant_label"], dropna=False):
        song_id, asset_id, variant_label = keys
        clf = sub[sub[f"{dim}_categories"].apply(lambda xs: set(xs) != {unk})]
        rec = {
            "song_id": song_id,
            "asset_id": asset_id,
            "variant_label": variant_label,
            "n_total": len(sub),
            "n_classifiable": len(clf),
            "creators": sub["creator_pseudo"].nunique() if "creator_pseudo" in sub else None,
            "median_plays": sub["play_count"].median(),
            "median_impact": sub["impact_metric"].median(),
            "first_date": sub["taken_at"].min(),
            "last_date": sub["taken_at"].max(),
        }
        counts = {}
        for cats in clf[f"{dim}_categories"]:
            for c in set(cats):
                if c != unk:
                    counts[c] = counts.get(c, 0) + 1
        for cid, label in labels.items():
            rec[label] = counts.get(cid, 0) / len(clf) if len(clf) else 0.0
        rows.append(rec)
    return pd.DataFrame(rows).sort_values(["song_id", "n_total"], ascending=[True, False])


def asset_vs_song_delta(df: pd.DataFrame, schema: dict, dim: str = "context") -> pd.DataFrame:
    """
    Show how much each audio variant's category mix differs from its song's overall mix.
    """
    ap = asset_profile(df, schema, dim=dim)
    sp = A.song_profile(df, dim, schema).reset_index()
    if ap.empty or sp.empty:
        return pd.DataFrame()
    cat_cols = [c for c in sp.columns if c not in ("song_id", "n_total", "n_classifiable")]
    merged = ap.merge(sp[["song_id"] + cat_cols], on="song_id", suffixes=("_asset", "_song"), how="left")
    rows = []
    for _, r in merged.iterrows():
        delta_sum = 0.0
        max_cat = None
        max_abs = -1.0
        for c in cat_cols:
            d = float(r.get(f"{c}_asset", 0) - r.get(f"{c}_song", 0))
            delta_sum += abs(d)
            if abs(d) > max_abs:
                max_abs = abs(d); max_cat = c
        rows.append({
            "song_id": r["song_id"],
            "asset_id": r["asset_id"],
            "variant_label": r["variant_label"],
            "n_total": r["n_total"],
            "delta_sum": delta_sum,
            "strongest_difference": max_cat,
            "strongest_abs_delta": max_abs,
        })
    return pd.DataFrame(rows).sort_values("delta_sum", ascending=False)


def asset_audio_filter_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score each audio variant on the music-versus-visual wording of its captions.
    """
    work = add_audio_filter_scores(df)
    return audio_filter_summary(work, group_col="asset_id")
