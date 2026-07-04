from __future__ import annotations
import pandas as pd


def add_top_quantile_flag(df: pd.DataFrame, group_col: str = "song_id", metric: str = "impact_metric", q: float = 0.90) -> pd.DataFrame:
    """
    Mark, within each group, the reels whose impact is in the top slice (by default the top 10%).
    """
    out = df.copy()
    out["is_top_quantile"] = False
    for group, sub in out.groupby(group_col):
        threshold = sub[metric].quantile(q)
        out.loc[sub.index, "is_top_quantile"] = sub[metric] >= threshold
    return out


def impact_by_theme(
    df: pd.DataFrame,
    schema: dict,
    dim: str = "context",
    group_col: str = "song_id",
    q: float = 0.90,
) -> pd.DataFrame:

    """
    For each category, compare how often it appears among the top-performing reels versus the rest.
    """
    if df.empty:
        return pd.DataFrame()
    work = add_top_quantile_flag(df, group_col=group_col, q=q)
    unk = schema["dimensions"][dim]["unknown_id"]
    labels = {cid: c["label"] for cid, c in schema["dimensions"][dim]["categories"].items()}
    rows = []
    for group, sub in work.groupby(group_col):
        for cat, label in labels.items():
            if cat == unk:
                continue
            top = sub[sub["is_top_quantile"]]
            rest = sub[~sub["is_top_quantile"]]
            top_share = top[f"{dim}_categories"].apply(lambda xs: cat in xs).mean() if len(top) else 0.0
            rest_share = rest[f"{dim}_categories"].apply(lambda xs: cat in xs).mean() if len(rest) else 0.0
            rows.append({
                group_col: group,
                "dimension": dim,
                "category": cat,
                "label": label,
                "n_top": len(top),
                "n_rest": len(rest),
                "share_top": float(top_share),
                "share_rest": float(rest_share),
                "delta": float(top_share - rest_share),
            })
    return pd.DataFrame(rows).sort_values([group_col, "delta"], ascending=[True, False])
