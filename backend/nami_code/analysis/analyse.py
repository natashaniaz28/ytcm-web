from __future__ import annotations
import sqlite3, yaml
from pathlib import Path
import pandas as pd
import numpy as np

DIMENSIONS = ["context", "format"]

KNOWN_SOURCES = ("keyword", "vision", "acoustic")


def validate_sources(sources: list[str]) -> list[str]:
    """
    Ensure every requested classification source is one we actually support.

    A typo such as ``keywords`` (plural) used to be split off and then silently
    dropped: ``classify`` only ever matched the exact string ``keyword``, so the
    keyword pass was skipped and only annotation sources remained. That quietly
    changed the report population and made coverage look like it *fell* when a
    source was added. We now fail loudly with the list of valid names instead.
    """
    if not sources:
        raise ValueError(
            "No classification sources given. "
            f"Valid sources are: {', '.join(KNOWN_SOURCES)}."
        )
    unknown = [s for s in sources if s not in KNOWN_SOURCES]
    if unknown:
        raise ValueError(
            f"Unknown classification source(s): {', '.join(unknown)}. "
            f"Valid sources are: {', '.join(KNOWN_SOURCES)}."
        )
    return sources


def available_sources(db_path: str) -> list[str]:
    """Every classification source usable for *db_path*, in canonical order.

    This is the default the report/robustness pipeline uses when ``--sources`` is
    not given — "all sources available" rather than keyword-only. ``keyword`` is
    always available (it is computed from captions/hashtags, not stored); any other
    KNOWN_SOURCES value (e.g. ``vision``) is included only when the ``annotations``
    table actually holds rows for it. So a corpus that was vision-tagged reports
    keyword+vision automatically, while one that never was stays keyword-only
    instead of showing an empty vision section. Falls back to ``["keyword"]`` if
    the annotations table is missing or unreadable.
    """
    present: set[str] = set()
    try:
        conn = sqlite3.connect(db_path)
        try:
            present = {r[0] for r in conn.execute(
                "SELECT DISTINCT source FROM annotations").fetchall()}
        finally:
            conn.close()
    except Exception:
        present = set()
    return ["keyword"] + [s for s in KNOWN_SOURCES if s != "keyword" and s in present]


def schema_dimensions(schema: dict | None) -> list[str]:
    """
    Return configured classification dimensions, preserving YAML order.

    Falls back to the legacy context/format pair when no schema dimensions are
    available so older callers keep working.
    """
    dims = []
    if isinstance(schema, dict):
        raw = schema.get("dimensions", {})
        if isinstance(raw, dict):
            dims = [str(dim) for dim in raw.keys()]
    return dims or list(DIMENSIONS)


def load_reels(db_path: str = "data/corpus.db", exclude_spam: bool = True) -> pd.DataFrame:
    """
    Load all reels from the database into a table, attach their hashtags, and add a few handy figures like engagement and a single combined 'impact' number.
    """
    conn = sqlite3.connect(db_path)
    has_spam_col = any(r[1] == "is_spam" for r in conn.execute("PRAGMA table_info(reels)"))
    spam_filter = "WHERE COALESCE(r.is_spam,0)=0" if (exclude_spam and has_spam_col) else ""
    df = pd.read_sql(f"""
        SELECT r.reel_pk, r.song_id, r.variant_label, r.asset_id, r.code,
               r.taken_at, r.caption_text, r.like_count, r.play_count,
               r.view_count, r.comment_count, r.video_duration, r.creator_pseudo,
               s.title AS song_title, s.artist AS song_artist
        FROM reels r LEFT JOIN songs s ON s.song_id = r.song_id
        {spam_filter}
    """, conn)
    try:
        ht = pd.read_sql("SELECT reel_pk, hashtag FROM reel_hashtags", conn)
    except Exception:
        ht = pd.DataFrame(columns=["reel_pk", "hashtag"])
    conn.close()

    df["taken_at"] = pd.to_datetime(df["taken_at"], utc=True, errors="coerce")
    df = df.dropna(subset=["taken_at"]).copy()
    df["caption_text"] = df["caption_text"].fillna("")
    df["song_title"] = df["song_title"].fillna(df["song_id"])

    tags = ht.groupby("reel_pk")["hashtag"].apply(list).to_dict()
    df["hashtags"] = df["reel_pk"].map(lambda pk: tags.get(pk, []))

    pc = df["play_count"].fillna(0)
    vc = df["view_count"].fillna(0)
    lc = df["like_count"].fillna(0)
    df["impact_metric"] = np.where(pc > 0, pc, np.where(vc > 0, vc, lc))
    df["engagement_rate"] = (lc / df["play_count"].replace(0, np.nan)).clip(upper=1)
    df["instagram_url"] = "https://www.instagram.com/reel/" + df["code"].fillna("")
    return df


def load_schema(path: str = "config/schema.yaml") -> dict:
    """
    Read the classification scheme (the dimensions and their categories) from the schema file.
    """
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _theme_text(row) -> str:
    """
    Join a reel's caption and hashtags into one lowercased string for keyword matching.
    """
    return (str(row["caption_text"]) + " " + " ".join(row["hashtags"])).lower()


def _classify_row(text: str, schema: dict) -> dict:
    """
    Decide which categories a single reel's text falls into, per dimension, by matching the configured keywords.
    """
    result = {}
    for dim in schema_dimensions(schema):
        spec = schema["dimensions"][dim]
        hits = []
        for cat_id, cat in spec["categories"].items():
            for kw in cat["keywords"]:
                if str(kw).lower() in text:
                    hits.append(cat_id); break
        result[dim] = hits or [spec["unknown_id"]]
    if schema.get("infer_aesthetics"):
        result = _infer(result, schema)
    return result


def _infer(result: dict, schema: dict) -> dict:
    """
    Optionally add an aesthetic label to a reel based on rules that look at its context and format categories.
    """
    if "aesthetic" not in schema.get("dimensions", {}):
        return result
    unk = schema["dimensions"]["aesthetic"]["unknown_id"]
    aes = set(result["aesthetic"])
    if aes and aes != {unk}:
        return result
    aes.discard(unk)
    ctx, fmt = set(result.get("context", [])), set(result.get("format", []))
    for rule in schema.get("inference_rules", []):
        ctx_ok = any(c in ctx for c in rule.get("if_context_any", [])) if "if_context_any" in rule else True
        fmt_ok = any(f in fmt for f in rule.get("and_format_any", [])) if "and_format_any" in rule else True
        if ctx_ok and fmt_ok:
            aes.add(rule["add_aesthetic"])
    result["aesthetic"] = sorted(aes) if aes else [unk]
    return result


def _load_annotations(db_path: str, sources: list[str], min_conf: float) -> dict:
    """
    Read saved category tags (for example from vision) out of the database, for the chosen sources and above a confidence cut-off.
    """
    import sqlite3
    out: dict = {}
    try:
        conn = sqlite3.connect(db_path)
        q = ("SELECT reel_pk, dimension, category FROM annotations "
             "WHERE source IN (%s) AND confidence >= ?" % ",".join("?" * len(sources)))
        rows = conn.execute(q, (*sources, min_conf)).fetchall()
        conn.close()
    except Exception:
        return out
    for pk, dim, cat in rows:
        out.setdefault(pk, {}).setdefault(dim, set()).add(cat)
    return out


def classify(df: pd.DataFrame, schema: dict,
             sources: list[str] | None = None,
             db_path: str = "data/corpus.db",
             min_conf: float = 0.0) -> pd.DataFrame:
    """
    Give every reel its categories per dimension, combining keyword matches with any saved tags from other sources.
    """
    df = df.copy()
    sources = sources or ["keyword"]
    validate_sources(sources)

    classified = [_classify_row(_theme_text(r), schema) for _, r in df.iterrows()]
    dims = schema_dimensions(schema)
    for dim in dims:
        df[f"{dim}_keyword"] = [c[dim] for c in classified]

    ext_sources = [s for s in sources if s != "keyword"]
    ext = _load_annotations(db_path, ext_sources, min_conf) if ext_sources else {}
    for dim in dims:
        df[f"{dim}_vision"] = df["reel_pk"].map(
            lambda pk: sorted(ext.get(pk, {}).get(dim, set())))

    unk = {dim: schema["dimensions"][dim]["unknown_id"] for dim in dims}
    for dim in dims:
        fused = []
        for _, row in df.iterrows():
            cats: set = set()
            if "keyword" in sources:
                kw = set(row[f"{dim}_keyword"])
                kw.discard(unk[dim])
                cats |= kw
            for s in ext_sources:
                if s == "vision":
                    cats |= set(row[f"{dim}_vision"])
            fused.append(sorted(cats) if cats else [unk[dim]])
        df[f"{dim}_categories"] = fused

    if schema.get("infer_aesthetics"):
        new_aes = []
        for _, row in df.iterrows():
            res = {d: list(row[f"{d}_categories"]) for d in dims}
            res = _infer(res, schema)
            new_aes.append(res["aesthetic"])
        df["aesthetic_categories"] = new_aes
    return df


def explode_dimension(df: pd.DataFrame, dim: str) -> pd.DataFrame:
    """
    Spread a reel's list of categories for one dimension into separate rows, one category each.
    """
    col = f"{dim}_categories"
    return df.explode(col).rename(columns={col: dim})


def dimension_distribution(df: pd.DataFrame, dim: str, schema: dict) -> pd.DataFrame:
    """
    Count, per song, how many reels fall into each category of a dimension and what share that is.
    """
    rows = []
    labels = {cid: c["label"] for cid, c in schema["dimensions"][dim]["categories"].items()}
    labels[schema["dimensions"][dim]["unknown_id"]] = schema["dimensions"][dim]["unknown_label"]
    for song_id, sub in df.groupby("song_id"):
        n = len(sub); counts = {}
        for cats in sub[f"{dim}_categories"]:
            for c in set(cats):
                counts[c] = counts.get(c, 0) + 1
        for cat, cnt in counts.items():
            rows.append({"song_id": song_id, "dimension": dim, "category": cat,
                         "label": labels.get(cat, cat), "count": cnt,
                         "share": cnt / n if n else 0})
    out = pd.DataFrame(rows)
    return out.sort_values(["song_id", "count"], ascending=[True, False]) if not out.empty else out


def unknown_share(df: pd.DataFrame, schema: dict) -> pd.DataFrame:
    """
    For each dimension, report how many reels could not be placed into any real category.
    """
    rows = []
    for dim in schema_dimensions(schema):
        unk = schema["dimensions"][dim]["unknown_id"]
        only_unk = df[f"{dim}_categories"].apply(lambda xs: set(xs) == {unk})
        rows.append({"dimension": dim, "unknown_only": int(only_unk.sum()),
                     "total": len(df), "share": float(only_unk.mean()) if len(df) else 0})
    return pd.DataFrame(rows)


def combination_summary(
    df: pd.DataFrame,
    schema: dict,
    top: int = 25,
    primary_dim: str | None = None,
    secondary_dim: str | None = None,
) -> pd.DataFrame:
    """Summarise category co-occurrence for two configured dimensions.

    The legacy report used context × format. Callers may now pass the two
    report dimensions from domain.yaml; defaults still resolve to the first two
    schema dimensions, normally context and format.
    """
    dims = schema_dimensions(schema)
    if not dims:
        return pd.DataFrame()
    primary = primary_dim if primary_dim in dims else dims[0]
    if secondary_dim in dims:
        secondary = secondary_dim
    elif len(dims) > 1:
        secondary = dims[1]
    else:
        secondary = primary

    lab = {dim: {**{cid: c["label"] for cid, c in schema["dimensions"][dim]["categories"].items()},
                 schema["dimensions"][dim]["unknown_id"]: schema["dimensions"][dim]["unknown_label"]}
           for dim in {primary, secondary}}
    primary_col = f"{primary}_categories"
    secondary_col = f"{secondary}_categories"
    if primary_col not in df or secondary_col not in df:
        return pd.DataFrame()

    rows = []
    for _, r in df.iterrows():
        for c in r[primary_col]:
            for f in r[secondary_col]:
                rows.append({primary: c, secondary: f,
                             "primary_dimension": primary,
                             "secondary_dimension": secondary,
                             "song_id": r["song_id"], "reel_pk": r["reel_pk"],
                             "impact": r["impact_metric"]})
    if not rows:
        return pd.DataFrame()
    cdf = pd.DataFrame(rows)
    group_cols = [primary] if primary == secondary else [primary, secondary]
    agg = (cdf.groupby(group_cols)
              .agg(reels=("reel_pk", "count"), songs=("song_id", "nunique"),
                   median_impact=("impact", "median"))
              .reset_index().sort_values("reels", ascending=False))
    if primary == secondary:
        agg["combo_label"] = agg[primary].map(lab[primary])
    else:
        agg["combo_label"] = (agg[primary].map(lab[primary]) + " + " +
                              agg[secondary].map(lab[secondary]))
    return agg.head(top)

def trend_series(df: pd.DataFrame, song_id: str, freq: str = "W") -> pd.Series:
    """
    Build a count, week by week (or another interval), of how many reels used a given song over time.
    """
    sub = df[df["song_id"] == song_id]
    if sub.empty:
        return pd.Series(dtype=float)
    s = sub.set_index("taken_at").sort_index().assign(one=1)["one"].resample(freq).sum()
    return s.asfreq(freq, fill_value=0)


def detect_peaks(series: pd.Series, prominence_factor: float = 1.0) -> dict:
    """
    Find the busy spikes in a time series, plus the date activity first took off and the biggest peak.
    """
    from scipy.signal import find_peaks
    if len(series) < 3 or series.max() == 0:
        return {"peaks": [], "peak_dates": [], "onset": None, "main_peak": None}
    vals = series.values.astype(float)
    prom = max(1.0, prominence_factor * np.std(vals))
    peaks, _ = find_peaks(vals, prominence=prom, distance=max(1, len(vals)//20))
    onset_thr = 0.10 * series.max()
    onset_i = next((i for i, v in enumerate(vals) if v >= onset_thr), None)
    return {"peaks": list(peaks), "peak_dates": [series.index[p] for p in peaks],
            "onset": series.index[onset_i] if onset_i is not None else None,
            "main_peak": series.index[int(np.argmax(vals))]}


def top_examples(df: pd.DataFrame, dim: str, category: str, n: int = 5) -> pd.DataFrame:
    """
    Return the highest-impact example reels for one category.
    """
    mask = df[f"{dim}_categories"].apply(lambda xs: category in xs)
    sub = df[mask].sort_values("impact_metric", ascending=False).head(n)
    return sub[["song_id", "impact_metric", "caption_text", "instagram_url"]]


def top_hashtags(df: pd.DataFrame, song_id=None, n: int = 20) -> pd.Series:
    """
    List the most common hashtags, optionally limited to a single song.
    """
    sub = df if song_id is None else df[df["song_id"] == song_id]
    flat = [h for tags in sub["hashtags"] for h in tags]
    return pd.Series(flat, dtype=str).value_counts().head(n)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Give a per-song overview: reel count, date span, and typical plays, likes and engagement.
    """
    g = df.groupby("song_id")
    return pd.DataFrame({
        "n_reels": g.size(),
        "from": g["taken_at"].min().dt.date,
        "to": g["taken_at"].max().dt.date,
        "median_plays": g["play_count"].median(),
        "median_likes": g["like_count"].median(),
        "median_engagement": g["engagement_rate"].median().round(4),
    }).reset_index()


def classifiable_rate(df: pd.DataFrame, schema: dict, dim: str) -> dict:
    """
    Report what fraction of reels could be placed into a real category on a dimension.
    """
    unk = schema["dimensions"][dim]["unknown_id"]
    is_clf = df[f"{dim}_categories"].apply(lambda xs: set(xs) != {unk})
    n_total = len(df)
    n_clf = int(is_clf.sum())
    return {"dimension": dim, "n_total": n_total, "n_classifiable": n_clf,
            "rate": n_clf / n_total if n_total else 0.0}


def distribution_classifiable(df: pd.DataFrame, dim: str, schema: dict) -> pd.DataFrame:
    """
    Among the reels that could be classified on a dimension, show how the categories are spread.
    """
    unk = schema["dimensions"][dim]["unknown_id"]
    labels = {cid: c["label"] for cid, c in schema["dimensions"][dim]["categories"].items()}
    clf = df[df[f"{dim}_categories"].apply(lambda xs: set(xs) != {unk})]
    n_clf = len(clf)
    counts = {}
    for cats in clf[f"{dim}_categories"]:
        for c in set(cats):
            if c == unk:
                continue
            counts[c] = counts.get(c, 0) + 1
    rows = [{"category": c, "label": labels.get(c, c), "count": n,
             "share_of_classifiable": n / n_clf if n_clf else 0} for c, n in counts.items()]
    out = pd.DataFrame(rows).sort_values("count", ascending=False) if rows else pd.DataFrame()
    return out


def song_profile(df: pd.DataFrame, dim: str, schema: dict) -> pd.DataFrame:
    """
    For each song, show what share of its classifiable reels fall into each category.
    """
    unk = schema["dimensions"][dim]["unknown_id"]
    labels = {cid: c["label"] for cid, c in schema["dimensions"][dim]["categories"].items()}
    rows = []
    for song_id, sub in df.groupby("song_id"):
        clf = sub[sub[f"{dim}_categories"].apply(lambda xs: set(xs) != {unk})]
        n_clf = len(clf)
        rec = {"song_id": song_id, "n_total": len(sub), "n_classifiable": n_clf}
        counts = {}
        for cats in clf[f"{dim}_categories"]:
            for c in set(cats):
                if c != unk:
                    counts[c] = counts.get(c, 0) + 1
        for cid, lab in labels.items():
            rec[lab] = counts.get(cid, 0) / n_clf if n_clf else 0.0
        rows.append(rec)
    return pd.DataFrame(rows).set_index("song_id")


def song_distinctiveness(df: pd.DataFrame, dim: str, schema: dict) -> pd.DataFrame:
    """
    Show which categories vary the most across songs, and which song leads each one.
    """
    prof = song_profile(df, dim, schema)
    cat_cols = [c for c in prof.columns if c not in ("n_total", "n_classifiable")]
    rows = []
    for c in cat_cols:
        vals = prof[c]
        rows.append({"category": c, "min": round(vals.min(), 3), "max": round(vals.max(), 3),
                     "range": round(vals.max() - vals.min(), 3),
                     "strongest_song": vals.idxmax()})
    return pd.DataFrame(rows).sort_values("range", ascending=False)


def hashtag_cooccurrence(df: pd.DataFrame, top_n: int = 25, min_count: int = 5) -> pd.DataFrame:
    """
    Find pairs of hashtags that often appear together.
    """
    from itertools import combinations
    from collections import Counter
    pair_counts = Counter()
    tag_counts = Counter()
    for tags in df["hashtags"]:
        uniq = sorted(set(t.lower() for t in tags if t))
        for t in uniq:
            tag_counts[t] += 1
        for a, b in combinations(uniq, 2):
            pair_counts[(a, b)] += 1
    rows = [{"tag_a": a, "tag_b": b, "shared": n,
             "count_a": tag_counts[a], "count_b": tag_counts[b]}
            for (a, b), n in pair_counts.items() if n >= min_count]
    out = pd.DataFrame(rows)
    return out.sort_values("shared", ascending=False).head(top_n) if not out.empty else out


if __name__ == "__main__":
    DB_PATH  = "data/corpus.db"
    SOURCES  = ["keyword"]
    MIN_CONF = 0.2

    df = load_reels(DB_PATH); schema = load_schema()
    df = classify(df, schema, sources=SOURCES, db_path=DB_PATH, min_conf=MIN_CONF)
    print(f"Loaded: {len(df)} reels, {df['song_id'].nunique()} song(s) | Sources: {SOURCES}\n")

    print("=== Classifiability per dimension ===")
    for dim in schema_dimensions(schema):
        r = classifiable_rate(df, schema, dim)
        print(f"  {dim:8s}: {r['n_classifiable']}/{r['n_total']} classifiable "
              f"({r['rate']*100:.0f}%) — others without classifiable caption")

    for dim in schema_dimensions(schema):
        print(f"\n=== Distribution {dim} (only classifiable reels) ===")
        d = distribution_classifiable(df, dim, schema)
        if not d.empty:
            for _, row in d.head(8).iterrows():
                print(f"  {row['label']:32s} {row['count']:5d}  {row['share_of_classifiable']*100:5.1f}%")
        else:
            print("  (empty)")

    print("\n=== Do the songs differ? ===")
    primary_dim = (schema_dimensions(schema) or ["context"])[0]
    prof = song_profile(df, primary_dim, schema)
    show_cols = [c for c in prof.columns if c not in ("n_total", "n_classifiable")]

    keep = [c for c in show_cols if prof[c].max() > 0.05]
    print(prof[["n_classifiable"] + keep].round(2).to_string())

    print(f"\n=== Where do the songs differ most ({primary_dim})? ===")
    dist = song_distinctiveness(df, primary_dim, schema)
    print(dist.head(8).to_string(index=False))

    print("\n=== Hashtag co-occurrence ===")
    co = hashtag_cooccurrence(df, top_n=15, min_count=2)
    if not co.empty:
        for _, row in co.iterrows():
            print(f"  {row['tag_a']:20s} + {row['tag_b']:20s}  {row['shared']}x")
    else:
        print("  (not enough hashtag data in the database)")
