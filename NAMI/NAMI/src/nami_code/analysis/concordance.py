"""
Keyword-vs-vision concordance: do the two independent classification signals agree?

`report` *unions* the keyword and vision sources per axis, so the two analyses are
merged but never checked against each other. This module asks the opposite question:
for each reel and dimension, how much do the keyword category set and the vision
category set coalesce? Broad agreement is converging evidence; systematic divergence
flags a weak keyword vocabulary, a mis-described vision category, or a genuinely
ambiguous slice.

Both sources already live in the same shape — keyword categories are recomputed from
caption/hashtag text (no confidence, treated as weight 1.0), vision categories are read
from `annotations` (source='vision') with the model's 0-1 confidence. The per-(reel,
dimension) score is a **confidence-weighted (Ruzicka) Jaccard** of the two sets, with
optional partial credit for near-synonym categories via an adjacency map.

Read-only: it never writes to the database. Only reels the vision tagger has finished
(`vision_state='done'`) are comparable, so the denominator is honest.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

import pandas as pd

from nami_code.analysis import analyse as A


def load_vision_annotations_conf(db_path: str, min_conf: float = 0.0) -> dict:
    """Return ``{reel_pk: {dimension: {category: confidence}}}`` for vision rows.

    Only ``source='vision'`` rows with ``confidence >= min_conf`` are kept; the max
    confidence is used if a (reel, dim, category) somehow has duplicates.
    """
    out: dict = defaultdict(lambda: defaultdict(dict))
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT reel_pk, dimension, category, MAX(confidence) "
                "FROM annotations WHERE source='vision' AND confidence >= ? "
                "GROUP BY reel_pk, dimension, category",
                (min_conf,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return {}
    for pk, dim, cat, conf in rows:
        out[pk][dim][cat] = float(conf)
    return {pk: {dim: dict(cats) for dim, cats in dims.items()} for pk, dims in out.items()}


def vision_done_pks(db_path: str) -> set:
    """reel_pks the vision tagger has finished (``vision_state='done'``)."""
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT reel_pk FROM vision_state WHERE status='done'").fetchall()
        finally:
            conn.close()
    except Exception:
        return set()
    return {r[0] for r in rows}


def load_adjacency(schema: dict) -> dict:
    """Optional per-dimension category-similarity map for partial agreement credit.

    Read from an optional schema block::

        concordance:
          adjacent:
            context:
              - [cityscape_street, japan_travel, 0.5]
              - [food_cafe, food_review, 0.5]

    Returns ``{dimension: {(cat_a, cat_b): weight}}``. Absent/malformed entries are
    skipped, so v1 works with no map at all — the score then reduces to an exact
    confidence-weighted Jaccard.
    """
    out: dict[str, dict[tuple[str, str], float]] = {}
    if not isinstance(schema, dict):
        return out
    block = schema.get("concordance", {})
    adj = block.get("adjacent", {}) if isinstance(block, dict) else {}
    if not isinstance(adj, dict):
        return out
    for dim, pairs in adj.items():
        if not isinstance(pairs, list):
            continue
        dim_map: dict[tuple[str, str], float] = {}
        for entry in pairs:
            try:
                a, b, w = entry[0], entry[1], float(entry[2])
            except (TypeError, ValueError, IndexError):
                continue
            w = max(0.0, min(1.0, w))
            dim_map[(str(a), str(b))] = w
        if dim_map:
            out[str(dim)] = dim_map
    return out


def pair_concordance(kw_set: set, vis_conf: dict, sim: dict | None = None) -> float | None:
    """Confidence-weighted (Ruzicka) Jaccard between one reel/dimension's two sets.

    ``kw_set`` is the keyword categories (each weight 1.0); ``vis_conf`` maps vision
    categories to their 0-1 confidence. ``sim`` is an optional ``{(a, b): weight}``
    map giving partial credit to near-synonym categories.

    Returns a score in [0, 1], or ``None`` when both sides are empty (both-unknown):
    that is agreement-on-ignorance, not agreement on content, so callers exclude it
    from the content-concordance mean and count it separately.

    With no ``sim`` map (or identity), the soft formula below reduces exactly to the
    weighted Jaccard ``sum_c min(a_c, b_c) / sum_c max(a_c, b_c)``.
    """
    K = set(kw_set)
    V = dict(vis_conf)
    if not K and not V:
        return None
    sim = sim or {}

    def s(a: str, b: str) -> float:
        if a == b:
            return 1.0
        return max(sim.get((a, b), 0.0), sim.get((b, a), 0.0))

    inter = 0.0
    for k in K:
        inter += max((s(k, v) * c for v, c in V.items()), default=0.0)
    for v, c in V.items():
        inter += c * max((s(k, v) for k in K), default=0.0)
    inter *= 0.5

    union = len(K) + sum(V.values()) - inter
    return inter / union if union > 0 else 0.0


def _keyword_sets(df: pd.DataFrame, schema: dict, dims: list[str]) -> dict:
    """{reel_pk: {dim: set(categories)}} from the keyword matcher (unknown excluded)."""
    unk = {d: schema["dimensions"][d]["unknown_id"] for d in dims}
    out: dict = {}
    for _, row in df.iterrows():
        res = A._classify_row(A._theme_text(row), schema)
        out[row["reel_pk"]] = {
            d: {c for c in res.get(d, []) if c != unk[d]} for d in dims
        }
    return out


def run_concordance(
    df: pd.DataFrame,
    schema: dict,
    db_path: str = "data/corpus.db",
    min_conf: float = 0.0,
) -> dict[str, pd.DataFrame]:
    """Compute keyword-vs-vision concordance tables for every schema dimension.

    Returns a dict of DataFrames (mirroring ``run_robustness``):
      - ``concordance_by_dimension`` — one row per dimension: comparable-reel count,
        mean/median concordance, exact- and zero-agreement shares, and the
        unknown-handling breakdown (both-unknown, keyword-only-unknown,
        vision-only-unknown).
      - ``concordance_confusion_<dim>`` — long-form keyword_category x vision_category
        co-occurrence counts across comparable reels (``unknown`` shown explicitly).
      - ``concordance_disagreements_<dim>`` — per category, how often keyword asserted
        it but vision did not (and vice versa); ranked by total divergence to surface
        systematic mismatches (keyword/``vision_description`` tuning candidates).
    """
    dims = [d for d in A.schema_dimensions(schema) if d in schema.get("dimensions", {})]
    adjacency = load_adjacency(schema)
    vis = load_vision_annotations_conf(db_path, min_conf)
    done = vision_done_pks(db_path)
    comparable = done if done else set(vis)

    sub = df[df["reel_pk"].isin(comparable)].copy()
    kw_sets = _keyword_sets(sub, schema, dims)

    by_dim_rows = []
    out: dict[str, pd.DataFrame] = {}

    for dim in dims:
        unk = schema["dimensions"][dim]["unknown_id"]
        unk_label = schema["dimensions"][dim].get("unknown_label", unk)
        sim = adjacency.get(dim, {})

        scores: list[float] = []
        both_unknown = kw_only_unknown = vis_only_unknown = 0
        confusion: dict[tuple[str, str], int] = defaultdict(int)
        kw_only: dict[str, int] = defaultdict(int)
        vis_only: dict[str, int] = defaultdict(int)
        both: dict[str, int] = defaultdict(int)

        for pk in kw_sets:
            K = kw_sets[pk][dim]
            V = {c: conf for c, conf in vis.get(pk, {}).get(dim, {}).items() if c != unk}

            score = pair_concordance(K, V, sim)
            if score is None:
                both_unknown += 1
            else:
                scores.append(score)
                if K and not V:
                    kw_only_unknown += 1
                elif V and not K:
                    vis_only_unknown += 1

            k_tokens = sorted(K) if K else [unk]
            v_tokens = sorted(V) if V else [unk]
            for kt in k_tokens:
                for vt in v_tokens:
                    confusion[(kt, vt)] += 1

            for c in K | set(V):
                in_k, in_v = c in K, c in V
                if in_k and in_v:
                    both[c] += 1
                elif in_k:
                    kw_only[c] += 1
                else:
                    vis_only[c] += 1

        n = len(scores)
        by_dim_rows.append({
            "dimension": dim,
            "comparable_reels": n,
            "mean_concordance": round(sum(scores) / n, 4) if n else 0.0,
            "median_concordance": round(float(pd.Series(scores).median()), 4) if n else 0.0,
            "exact_agreement_share": round(sum(1 for s in scores if s >= 0.999) / n, 4) if n else 0.0,
            "zero_agreement_share": round(sum(1 for s in scores if s <= 1e-9) / n, 4) if n else 0.0,
            "keyword_only_unknown": kw_only_unknown,
            "vision_only_unknown": vis_only_unknown,
            "both_unknown": both_unknown,
        })

        labels = {cid: c.get("label", cid)
                  for cid, c in schema["dimensions"][dim].get("categories", {}).items()}
        labels[unk] = unk_label

        conf_rows = [
            {"dimension": dim, "keyword_category": k, "vision_category": v,
             "keyword_label": labels.get(k, k), "vision_label": labels.get(v, v),
             "n_reels": n_}
            for (k, v), n_ in confusion.items()
        ]
        conf_df = pd.DataFrame(conf_rows)
        if not conf_df.empty:
            conf_df = conf_df.sort_values("n_reels", ascending=False, ignore_index=True)
        out[f"concordance_confusion_{dim}"] = conf_df

        cats = set(kw_only) | set(vis_only) | set(both)
        dis_rows = []
        for c in cats:
            ko, vo, bo = kw_only.get(c, 0), vis_only.get(c, 0), both.get(c, 0)
            asserted = ko + vo + bo
            dis_rows.append({
                "dimension": dim,
                "category": c,
                "label": labels.get(c, c),
                "both": bo,
                "keyword_only": ko,
                "vision_only": vo,
                "divergence": ko + vo,
                "agreement_rate": round(bo / asserted, 4) if asserted else 0.0,
            })
        dis_df = pd.DataFrame(dis_rows)
        if not dis_df.empty:
            dis_df = dis_df.sort_values(
                ["divergence", "both"], ascending=[False, False], ignore_index=True)
        out[f"concordance_disagreements_{dim}"] = dis_df

    out["concordance_by_dimension"] = pd.DataFrame(by_dim_rows)
    return out
