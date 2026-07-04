from __future__ import annotations
import pandas as pd


def creator_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise each anonymous creator: how many reels, songs and assets they posted, and their play counts.
    """
    if df.empty or "creator_pseudo" not in df:
        return pd.DataFrame()
    g = df.groupby("creator_pseudo")
    creators = g.agg(
        n_reels=("reel_pk", "nunique"),
        n_songs=("song_id", "nunique"),
        n_assets=("asset_id", "nunique"),
        total_plays=("play_count", "sum"),
        median_plays=("play_count", "median"),
    ).reset_index()
    return creators.sort_values("n_reels", ascending=False)


def creator_kpis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Report headline figures about the creator base, such as one-time posters and how concentrated activity is among the busiest 1%.
    """
    cs = creator_summary(df)
    if cs.empty:
        return pd.DataFrame()
    n_creators = len(cs)
    n_reels = df["reel_pk"].nunique()
    top_1pct_n = max(1, int(round(n_creators * 0.01)))
    top_1pct = cs.head(top_1pct_n)
    rows = [
        {"metric": "creators", "value": n_creators},
        {"metric": "reels", "value": n_reels},
        {"metric": "one_time_creator_share", "value": float((cs["n_reels"] == 1).mean())},
        {"metric": "creators_with_multiple_songs", "value": int((cs["n_songs"] > 1).sum())},
        {"metric": "top_1pct_share_reels", "value": float(top_1pct["n_reels"].sum() / n_reels) if n_reels else 0.0},
        {"metric": "top_1pct_share_plays", "value": float(top_1pct["total_plays"].sum() / cs["total_plays"].sum()) if cs["total_plays"].sum() else 0.0},
    ]
    return pd.DataFrame(rows)


def multi_song_creators(df: pd.DataFrame, min_songs: int = 2) -> pd.DataFrame:
    """
    List creators who posted for more than one song.
    """
    cs = creator_summary(df)
    return cs[cs["n_songs"] >= min_songs].sort_values(["n_songs", "n_reels"], ascending=False)
