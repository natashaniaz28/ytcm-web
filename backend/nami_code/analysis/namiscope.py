"""
NAMI-native scope/statistics helpers for Instagram Reel research.
Derived from YTCM's TubeScope module.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd


FIELD_MAP = {
    "likes": "like_count",
    "plays": "play_count",
    "views": "view_count",
    "comments": "comment_count",
    "duration": "video_duration",
}

CORRELATION_FIELD_MAP = {**FIELD_MAP, "impact": "impact"}

VALID_ENTITIES = {"songs", "assets", "hashtags", "creators"}
VALID_FREQS = {"D", "W", "M"}
VALID_DATE_FIELDS = {"taken_at", "ingested_at"}
VALID_IMPACT_BY = {"song", "asset", "hashtag", "creator"}


BASE_COLUMNS = [
    "reel_pk",
    "code",
    "creator_pseudo",
    "song_id",
    "song_title",
    "song_artist",
    "asset_id",
    "variant_label",
    "taken_at",
    "ingested_at",
    "like_count",
    "play_count",
    "view_count",
    "comment_count",
    "video_duration",
    "hashtags",
]


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """
    Open the database for reading, failing clearly if the file is missing.
    """
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """
    Return whether a table exists.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _empty_scope_frame() -> pd.DataFrame:
    """
    Return an empty table with the standard scope columns.
    """
    return pd.DataFrame(columns=BASE_COLUMNS)


def _clean_text(value: Any) -> str:
    """
    Turn any value into a trimmed string.
    """
    return str(value or "").strip()


def _field_column(field: str, *, allow_impact: bool = False) -> str:
    """
    Translate a friendly field name into its database column, or fail with the valid options.
    """
    key = _clean_text(field).lower()
    mapping = CORRELATION_FIELD_MAP if allow_impact else FIELD_MAP
    if key not in mapping:
        valid = ", ".join(sorted(mapping))
        raise ValueError(f"Unknown field: {field}. Expected one of: {valid}")
    return mapping[key]


def _ensure_impact(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make sure the table has a combined 'impact' column, building it from plays, likes and comments if needed.
    """
    out = df.copy()
    if "impact" not in out.columns:
        out["impact"] = (
            pd.to_numeric(out.get("play_count"), errors="coerce").fillna(0)
            + pd.to_numeric(out.get("like_count"), errors="coerce").fillna(0)
            + pd.to_numeric(out.get("comment_count"), errors="coerce").fillna(0)
        )
    return out


def _song_label(row: Any) -> str:
    """
    Make a readable label for a song (artist – title, or its id).
    """
    artist = _clean_text(row.get("song_artist") if hasattr(row, "get") else getattr(row, "song_artist", ""))
    title = _clean_text(row.get("song_title") if hasattr(row, "get") else getattr(row, "song_title", ""))
    song_id = _clean_text(row.get("song_id") if hasattr(row, "get") else getattr(row, "song_id", ""))
    if artist and title:
        return f"{artist} – {title}"
    return title or song_id


def _asset_label(row: Any) -> str:
    """
    Make a readable label for an audio variant.
    """
    variant = _clean_text(row.get("variant_label") if hasattr(row, "get") else getattr(row, "variant_label", ""))
    asset_id = _clean_text(row.get("asset_id") if hasattr(row, "get") else getattr(row, "asset_id", ""))
    if variant and asset_id:
        return f"{variant} ({asset_id})"
    return variant or asset_id


def _period_series(series: pd.Series, freq: str) -> pd.Series:
    """
    Turn a column of dates into period labels such as weeks or months.
    """
    dates = pd.to_datetime(series, errors="coerce", utc=True)
    dates = dates.dt.tz_convert(None)
    return dates.dt.to_period(freq).astype(str)


def load_scope_dataframe(db_path: str) -> pd.DataFrame:
    """
    Load Reel-level scope data with hashtags as a list per Reel.

    The returned DataFrame contains at least: reel_pk, creator_pseudo, song_id,
    song_title, asset_id, variant_label, taken_at, ingested_at, like_count,
    play_count, view_count, comment_count, video_duration, hashtags.
    """
    with _connect(db_path) as conn:
        if not _table_exists(conn, "reels"):
            raise RuntimeError("Missing required table: reels")

        has_songs = _table_exists(conn, "songs")
        has_hashtags = _table_exists(conn, "reel_hashtags")

        if has_songs:
            query = """
                SELECT
                    r.reel_pk,
                    r.code,
                    r.creator_pseudo,
                    r.song_id,
                    s.title AS song_title,
                    s.artist AS song_artist,
                    r.asset_id,
                    r.variant_label,
                    r.taken_at,
                    r.ingested_at,
                    r.like_count,
                    r.play_count,
                    r.view_count,
                    r.comment_count,
                    r.video_duration
                FROM reels r
                LEFT JOIN songs s ON s.song_id = r.song_id
                ORDER BY r.reel_pk
            """
        else:
            query = """
                SELECT
                    reel_pk,
                    code,
                    creator_pseudo,
                    song_id,
                    NULL AS song_title,
                    NULL AS song_artist,
                    asset_id,
                    variant_label,
                    taken_at,
                    ingested_at,
                    like_count,
                    play_count,
                    view_count,
                    comment_count,
                    video_duration
                FROM reels
                ORDER BY reel_pk
            """

        df = pd.read_sql_query(query, conn)
        if df.empty:
            df = _empty_scope_frame()
        else:
            df["hashtags"] = [[] for _ in range(len(df))]

        if has_hashtags and not df.empty:
            tag_rows = conn.execute(
                "SELECT reel_pk, hashtag FROM reel_hashtags ORDER BY reel_pk, hashtag"
            ).fetchall()
            tags_by_reel: dict[str, list[str]] = {}
            for row in tag_rows:
                tag = _clean_text(row["hashtag"])
                if not tag:
                    continue
                tags_by_reel.setdefault(row["reel_pk"], []).append(tag)
            df["hashtags"] = df["reel_pk"].map(lambda reel_pk: tags_by_reel.get(reel_pk, []))

        for col in BASE_COLUMNS:
            if col not in df.columns:
                df[col] = [[] for _ in range(len(df))] if col == "hashtags" else None
        return df[BASE_COLUMNS]


def make_timeline(df: pd.DataFrame, entity: str, freq: str) -> pd.DataFrame:
    """
    Return count by period and entity for songs, assets, hashtags, or creators.
    """
    entity = _clean_text(entity).lower() or "songs"
    freq = (_clean_text(freq).upper() or "M")
    if entity not in VALID_ENTITIES:
        raise ValueError(f"Unknown entity: {entity}. Expected one of: {', '.join(sorted(VALID_ENTITIES))}")
    if freq not in VALID_FREQS:
        raise ValueError("Unknown frequency: {freq}. Expected D, W, or M".format(freq=freq))

    columns = ["period", "entity_type", "entity_id", "entity_label", "count"]
    if df.empty:
        return pd.DataFrame(columns=columns)

    work = df.copy()
    work["period"] = _period_series(work["taken_at"], freq)
    work = work[work["period"].notna() & (work["period"] != "NaT")]
    if work.empty:
        return pd.DataFrame(columns=columns)

    if entity == "hashtags":
        work = work.explode("hashtags")
        work["entity_id"] = work["hashtags"].map(_clean_text)
        work["entity_label"] = work["entity_id"]
    elif entity == "songs":
        work["entity_id"] = work["song_id"].map(_clean_text)
        work["entity_label"] = work.apply(_song_label, axis=1)
    elif entity == "assets":
        work["entity_id"] = work["asset_id"].map(_clean_text)
        work["entity_label"] = work.apply(_asset_label, axis=1)
    else:
        work["entity_id"] = work["creator_pseudo"].map(_clean_text)
        work["entity_label"] = work["entity_id"]

    work = work[work["entity_id"] != ""]
    if work.empty:
        return pd.DataFrame(columns=columns)

    out = (
        work.groupby(["period", "entity_id", "entity_label"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    out.insert(1, "entity_type", entity)
    return out[columns].sort_values(["period", "count", "entity_label"], ascending=[True, False, True])


def describe_distribution(df: pd.DataFrame, field: str) -> pd.DataFrame:
    """
    Return compact summary statistics for a numeric scope field.
    """
    column = _field_column(field)
    output_field = _clean_text(field).lower()
    values = pd.to_numeric(df.get(column, pd.Series(dtype="float64")), errors="coerce")
    valid = values.dropna()
    data: dict[str, Any] = {
        "field": output_field,
        "column": column,
        "count": int(valid.count()),
        "missing": int(values.isna().sum()),
        "mean": None,
        "std": None,
        "min": None,
        "p25": None,
        "median": None,
        "p75": None,
        "max": None,
    }
    if not valid.empty:
        data.update(
            {
                "mean": float(valid.mean()),
                "std": float(valid.std()) if valid.count() > 1 else 0.0,
                "min": float(valid.min()),
                "p25": float(valid.quantile(0.25)),
                "median": float(valid.median()),
                "p75": float(valid.quantile(0.75)),
                "max": float(valid.max()),
            }
        )
    return pd.DataFrame([data])


def top_reels(df: pd.DataFrame, field: str, n: int) -> pd.DataFrame:
    """
    Return top-N reels by likes, plays, views, comments, duration, or impact.
    """
    column = _field_column(field, allow_impact=True)
    n = max(int(n), 0)
    columns = [
        "rank",
        "reel_pk",
        "code",
        "creator_pseudo",
        "song_id",
        "song_label",
        "asset_id",
        "variant_label",
        "taken_at",
        "like_count",
        "play_count",
        "view_count",
        "comment_count",
        "video_duration",
        "impact",
        "score_field",
        "score",
    ]
    if df.empty or n == 0:
        return pd.DataFrame(columns=columns)

    work = _ensure_impact(df)
    work["song_label"] = work.apply(_song_label, axis=1)
    work["score"] = pd.to_numeric(work[column], errors="coerce")
    work = work.dropna(subset=["score"]).sort_values("score", ascending=False).head(n).copy()
    work["rank"] = range(1, len(work) + 1)
    work["score_field"] = _clean_text(field).lower()
    for col in columns:
        if col not in work.columns:
            work[col] = None
    return work[columns]


def correlate_fields(df: pd.DataFrame, field1: str, field2: str) -> pd.DataFrame:
    """
    Return Pearson and Spearman correlations for two numeric fields.
    """
    col1 = _field_column(field1, allow_impact=True)
    col2 = _field_column(field2, allow_impact=True)
    work = _ensure_impact(df)
    x = pd.to_numeric(work.get(col1, pd.Series(dtype="float64")), errors="coerce")
    y = pd.to_numeric(work.get(col2, pd.Series(dtype="float64")), errors="coerce")
    paired = pd.DataFrame({"x": x, "y": y}).dropna()

    pearson = None
    spearman = None
    note = "ok"
    if len(paired) < 2:
        note = "not enough paired observations"
    elif paired["x"].nunique() < 2 or paired["y"].nunique() < 2:
        note = "constant input"
    else:
        pearson = float(paired["x"].corr(paired["y"], method="pearson"))
        spearman = float(paired["x"].corr(paired["y"], method="spearman"))
        note = "spearman computed with pandas"

    return pd.DataFrame(
        [
            {
                "field1": _clean_text(field1).lower(),
                "field2": _clean_text(field2).lower(),
                "column1": col1,
                "column2": col2,
                "n": int(len(paired)),
                "pearson": pearson,
                "spearman": spearman,
                "method_note": note,
            }
        ]
    )


def weekday_counts(df: pd.DataFrame, date_field: str) -> pd.DataFrame:
    """
    Return Reel counts by weekday and hour for taken_at or ingested_at.
    """
    date_field = _clean_text(date_field).lower() or "taken_at"
    if date_field not in VALID_DATE_FIELDS:
        raise ValueError("Unknown date field: {field}. Expected taken_at or ingested_at".format(field=date_field))
    columns = ["date_field", "weekday", "weekday_name", "hour", "count"]
    if df.empty or date_field not in df.columns:
        return pd.DataFrame(columns=columns)

    dates = pd.to_datetime(df[date_field], errors="coerce", utc=True).dt.tz_convert(None)
    work = pd.DataFrame({"dt": dates}).dropna()
    if work.empty:
        return pd.DataFrame(columns=columns)
    work["date_field"] = date_field
    work["weekday"] = work["dt"].dt.weekday
    work["weekday_name"] = work["dt"].dt.day_name()
    work["hour"] = work["dt"].dt.hour
    out = (
        work.groupby(["date_field", "weekday", "weekday_name", "hour"], dropna=False)
        .size()
        .reset_index(name="count")
    )
    return out[columns].sort_values(["weekday", "hour"])


def impact_summary(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """
    Return impact summaries by song, asset, hashtag, or creator.
    """
    by = _clean_text(by).lower() or "song"
    if by not in VALID_IMPACT_BY:
        raise ValueError(f"Unknown impact grouping: {by}. Expected one of: {', '.join(sorted(VALID_IMPACT_BY))}")

    columns = [
        "by",
        "entity_id",
        "entity_label",
        "count",
        "play_count_sum",
        "play_count_mean",
        "play_count_max",
        "like_count_sum",
        "like_count_mean",
        "like_count_max",
        "comment_count_sum",
        "comment_count_mean",
        "comment_count_max",
        "impact_sum",
        "impact_mean",
        "impact_max",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    work = _ensure_impact(df)
    if by == "hashtag":
        work = work.explode("hashtags")
        work["entity_id"] = work["hashtags"].map(_clean_text)
        work["entity_label"] = work["entity_id"]
    elif by == "song":
        work["entity_id"] = work["song_id"].map(_clean_text)
        work["entity_label"] = work.apply(_song_label, axis=1)
    elif by == "asset":
        work["entity_id"] = work["asset_id"].map(_clean_text)
        work["entity_label"] = work.apply(_asset_label, axis=1)
    else:
        work["entity_id"] = work["creator_pseudo"].map(_clean_text)
        work["entity_label"] = work["entity_id"]

    work = work[work["entity_id"] != ""].copy()
    if work.empty:
        return pd.DataFrame(columns=columns)

    for col in ["play_count", "like_count", "comment_count", "impact"]:
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0)

    grouped = work.groupby(["entity_id", "entity_label"], dropna=False)
    out = grouped.agg(
        count=("reel_pk", "count"),
        play_count_sum=("play_count", "sum"),
        play_count_mean=("play_count", "mean"),
        play_count_max=("play_count", "max"),
        like_count_sum=("like_count", "sum"),
        like_count_mean=("like_count", "mean"),
        like_count_max=("like_count", "max"),
        comment_count_sum=("comment_count", "sum"),
        comment_count_mean=("comment_count", "mean"),
        comment_count_max=("comment_count", "max"),
        impact_sum=("impact", "sum"),
        impact_mean=("impact", "mean"),
        impact_max=("impact", "max"),
    ).reset_index()
    out.insert(0, "by", by)
    return out[columns].sort_values(["impact_sum", "count", "entity_label"], ascending=[False, False, True])


def write_csv(df: pd.DataFrame, path: str | Path) -> Path:
    """
    Write a DataFrame to CSV and create parent directories automatically.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    return out
