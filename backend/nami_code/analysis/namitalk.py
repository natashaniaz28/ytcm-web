"""
NAMI-native caption and hashtag text helpers.
Derived from YTCM's TubeTalk module.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import math
import re
import sqlite3
import unicodedata
from typing import Any

import pandas as pd


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"(?<!\w)@[\w.]+", re.UNICODE)
HASHTAG_RE = re.compile(r"#([\wÀ-ÖØ-öø-ÿ一-龯ぁ-ゔァ-ヴー々〆〤]+)", re.UNICODE)
PUNCT_RE = re.compile(r"[\.,;:!\?\(\)\[\]\{\}\"'`´“”‘’•·…|/\\]+")
TOKEN_RE = re.compile(r"[\wÀ-ÖØ-öø-ÿ一-龯ぁ-ゔァ-ヴー々〆〤]+", re.UNICODE)

BASE_COLUMNS = [
    "reel_pk",
    "caption_text",
    "song_id",
    "song_title",
    "asset_id",
    "creator_pseudo",
    "hashtags",
]

BASIC_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "you", "are", "from",
    "und", "der", "die", "das", "ein", "eine", "mit", "ist", "für", "von",
    "に", "の", "は", "を", "が", "と", "で"
}


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


def _clean(value: Any) -> str:
    """
    Turn any value into a trimmed string, treating missing values as empty.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _empty_caption_frame() -> pd.DataFrame:
    """
    Return an empty table with the standard caption columns.
    """
    return pd.DataFrame(columns=BASE_COLUMNS)


def _song_label(row: Any) -> str:
    """
    Make a readable label for a song (its title, or its id).
    """
    title = _clean(row.get("song_title") if hasattr(row, "get") else getattr(row, "song_title", ""))
    song_id = _clean(row.get("song_id") if hasattr(row, "get") else getattr(row, "song_id", ""))
    return title or song_id


def _asset_label(row: Any) -> str:
    """
    Return the audio variant's id as its label.
    """
    asset_id = _clean(row.get("asset_id") if hasattr(row, "get") else getattr(row, "asset_id", ""))
    return asset_id


def _is_emoji_char(ch: str) -> bool:
    """
    Return whether a single character is an emoji.
    """
    code = ord(ch)
    if 0x1F300 <= code <= 0x1FAFF:
        return True
    if 0x2600 <= code <= 0x27BF:
        return True
    return False


def _safe_ratio(part: float, whole: float) -> float:
    """
    Divide two numbers, returning 0 when the bottom one is zero.
    """
    if whole <= 0:
        return 0.0
    return part / whole


def load_caption_dataframe(db_path: str) -> pd.DataFrame:
    """
    Load reel captions with song, asset, creator, and hashtag lists.

    Returned columns: reel_pk, caption_text, song_id, song_title, asset_id,
    creator_pseudo, hashtags.
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
                    r.caption_text,
                    r.song_id,
                    s.title AS song_title,
                    r.asset_id,
                    r.creator_pseudo
                FROM reels r
                LEFT JOIN songs s ON s.song_id = r.song_id
                ORDER BY r.reel_pk
            """
        else:
            query = """
                SELECT
                    reel_pk,
                    caption_text,
                    song_id,
                    NULL AS song_title,
                    asset_id,
                    creator_pseudo
                FROM reels
                ORDER BY reel_pk
            """

        df = pd.read_sql_query(query, conn)
        if df.empty:
            df = _empty_caption_frame()
        else:
            df["hashtags"] = [[] for _ in range(len(df))]

        if has_hashtags and not df.empty:
            rows = conn.execute(
                "SELECT reel_pk, hashtag FROM reel_hashtags ORDER BY reel_pk, hashtag"
            ).fetchall()
            tags_by_reel: dict[str, list[str]] = defaultdict(list)
            for row in rows:
                tag = _clean(row["hashtag"]).lstrip("#").lower()
                if tag:
                    tags_by_reel[row["reel_pk"]].append(tag)
            df["hashtags"] = df["reel_pk"].map(lambda reel_pk: tags_by_reel.get(reel_pk, []))

        for col in BASE_COLUMNS:
            if col not in df.columns:
                df[col] = [[] for _ in range(len(df))] if col == "hashtags" else None
        return df[BASE_COLUMNS]


def normalize_caption_text(text: str) -> str:
    """
    Normalize caption text for lightweight term extraction.
    """
    value = unicodedata.normalize("NFKC", _clean(text))
    value = URL_RE.sub(" ", value)
    value = MENTION_RE.sub(" ", value)
    value = value.replace("#", " ")
    value = PUNCT_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip().lower()


def _caption_tokens(text: Any, min_len: int = 3) -> list[str]:
    """
    Split a caption into clean word tokens, dropping very short words, stopwords and numbers.
    """
    normalized = normalize_caption_text(_clean(text))
    tokens: list[str] = []
    for token in TOKEN_RE.findall(normalized):
        token = token.strip("_").lower()
        if len(token) < min_len:
            continue
        if token in BASIC_STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens


def _caption_hashtags(text: Any) -> list[str]:
    """
    Pull the hashtags out of a caption as lowercased words.
    """
    return [tag.lower() for tag in HASHTAG_RE.findall(_clean(text)) if tag.strip()]


def extract_caption_terms(df: pd.DataFrame, min_len: int = 3, top: int = 50) -> pd.DataFrame:
    """
    Return frequent terms in caption_text.
    """
    columns = ["term", "count", "reel_count"]
    if df.empty:
        return pd.DataFrame(columns=columns)

    total = Counter()
    reel_counts = Counter()
    for text in df.get("caption_text", pd.Series(dtype="object")):
        tokens = _caption_tokens(text, min_len=min_len)
        total.update(tokens)
        reel_counts.update(set(tokens))

    rows = [
        {"term": term, "count": count, "reel_count": reel_counts.get(term, 0)}
        for term, count in total.items()
    ]
    out = pd.DataFrame(rows, columns=columns)
    if out.empty:
        return out
    out = out.sort_values(["count", "term"], ascending=[False, True])
    if top and top > 0:
        out = out.head(top)
    return out.reset_index(drop=True)


def extract_hashtag_terms(df: pd.DataFrame, top: int = 50) -> pd.DataFrame:
    """
    Return frequent hashtags from the reel_hashtags-derived list column.
    """
    columns = ["hashtag", "count", "reel_count"]
    if df.empty:
        return pd.DataFrame(columns=columns)

    total = Counter()
    reel_counts = Counter()
    for tags in df.get("hashtags", pd.Series(dtype="object")):
        clean_tags = [_clean(tag).lstrip("#").lower() for tag in (tags or [])]
        clean_tags = [tag for tag in clean_tags if tag]
        total.update(clean_tags)
        reel_counts.update(set(clean_tags))

    rows = [
        {"hashtag": tag, "count": count, "reel_count": reel_counts.get(tag, 0)}
        for tag, count in total.items()
    ]
    out = pd.DataFrame(rows, columns=columns)
    if out.empty:
        return out
    out = out.sort_values(["count", "hashtag"], ascending=[False, True])
    if top and top > 0:
        out = out.head(top)
    return out.reset_index(drop=True)


def _entity_fields(by: str) -> tuple[str, str]:
    """
    Return the id and label columns for grouping by song or by asset.
    """
    key = _clean(by).lower() or "song"
    if key == "song":
        return "song_id", "song_title"
    if key == "asset":
        return "asset_id", "asset_id"
    raise ValueError("Unknown by value: {by}. Expected song or asset".format(by=by))


def _terms_for_source(row: pd.Series, source: str) -> list[str]:
    """
    Return a reel's terms, taken either from its hashtags or its caption words.
    """
    if source == "hashtags":
        return [_clean(tag).lstrip("#").lower() for tag in (row.get("hashtags") or []) if _clean(tag)]
    if source == "captions":
        return _caption_tokens(row.get("caption_text"), min_len=3)
    raise ValueError("Unknown source: {source}. Expected hashtags or captions".format(source=source))


def distinctive_terms(df: pd.DataFrame, by: str = "song", source: str = "hashtags", top: int = 30) -> pd.DataFrame:
    """
    Return lightweight distinctive term scores by song or asset.

    Score is a smoothed ratio: term share within entity divided by global term
    share. It is intended as an exploratory cue, not an inferential statistic.
    """
    by = _clean(by).lower() or "song"
    source = _clean(source).lower() or "hashtags"
    entity_col, label_col = _entity_fields(by)
    if source not in {"hashtags", "captions"}:
        raise ValueError("Unknown source: {source}. Expected hashtags or captions".format(source=source))

    columns = [
        "by",
        "entity_id",
        "entity_label",
        "source",
        "term",
        "count",
        "entity_total_terms",
        "global_count",
        "global_total_terms",
        "score",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    global_counts: Counter[str] = Counter()
    entity_counts: dict[str, Counter[str]] = defaultdict(Counter)
    entity_totals: Counter[str] = Counter()
    labels: dict[str, str] = {}

    for _, row in df.iterrows():
        entity_id = _clean(row.get(entity_col))
        if not entity_id:
            continue
        if by == "song":
            label = _song_label(row)
        else:
            label = _asset_label(row)
        labels[entity_id] = label or entity_id
        terms = [term for term in _terms_for_source(row, source) if term]
        if not terms:
            continue
        global_counts.update(terms)
        entity_counts[entity_id].update(terms)
        entity_totals[entity_id] += len(terms)

    global_total = sum(global_counts.values())
    rows: list[dict[str, Any]] = []
    for entity_id, counts in entity_counts.items():
        entity_total = entity_totals[entity_id]
        entity_rows = []
        for term, count in counts.items():
            global_count = global_counts[term]
            entity_share = _safe_ratio(count + 1, entity_total + len(global_counts) or 1)
            global_share = _safe_ratio(global_count + 1, global_total + len(global_counts) or 1)
            score = entity_share / global_share if global_share else math.nan
            entity_rows.append({
                "by": by,
                "entity_id": entity_id,
                "entity_label": labels.get(entity_id, entity_id),
                "source": source,
                "term": term,
                "count": int(count),
                "entity_total_terms": int(entity_total),
                "global_count": int(global_count),
                "global_total_terms": int(global_total),
                "score": round(float(score), 6) if not math.isnan(score) else None,
            })
        entity_rows.sort(key=lambda item: (-float(item["score"] or 0), -int(item["count"]), str(item["term"])))
        rows.extend(entity_rows[:top] if top and top > 0 else entity_rows)

    out = pd.DataFrame(rows, columns=columns)
    if out.empty:
        return out
    return out.sort_values(["entity_id", "score", "count", "term"], ascending=[True, False, False, True]).reset_index(drop=True)


def caption_markers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return simple caption marker columns per reel.
    """
    columns = [
        "reel_pk",
        "has_url",
        "mention_count",
        "hashtag_count_in_caption",
        "caption_length",
        "is_empty_caption",
        "emoji_count",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        text = _clean(row.get("caption_text"))
        rows.append({
            "reel_pk": _clean(row.get("reel_pk")),
            "has_url": bool(URL_RE.search(text)),
            "mention_count": len(MENTION_RE.findall(text)),
            "hashtag_count_in_caption": len(_caption_hashtags(text)),
            "caption_length": len(text),
            "is_empty_caption": text == "",
            "emoji_count": sum(1 for ch in text if _is_emoji_char(ch)),
        })
    return pd.DataFrame(rows, columns=columns)


def write_csv(df: pd.DataFrame, path: str | Path) -> Path:
    """
    Write a DataFrame as UTF-8 CSV and create parent folders.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    return out
