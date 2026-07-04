"""
Hashtag network and semantic clustering utilities for NAMI.

The network construction is generic. Project-specific semantic hashtag rules are
loaded from ``config/domain.yaml`` when available.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
import math
import re
from typing import Any

import pandas as pd

from nami_code.domain_config import load_domain_config

DEFAULT_STOPWORDS: frozenset[str] = frozenset()
DEFAULT_OTHER_LABEL = "Other"


def normalize_hashtag(tag: str) -> str:
    """
    Normalize a hashtag for exact and substring matching.
    """

    tag = str(tag or "").strip().lower()
    tag = tag[1:] if tag.startswith("#") else tag
    return re.sub(r"\s+", "", tag)


def normalize_tag(tag: str) -> str:
    """
    Tidy a hashtag into a standard form (lowercase, no '#', no spaces).
    """
    return normalize_hashtag(tag)


def _as_list(value: Any) -> list[Any]:
    """
    Return the value as a list, or an empty list if it is not list-like.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple) or isinstance(value, set):
        return list(value)
    return []


def _normalize_terms(value: Any) -> set[str]:
    """
    Tidy a collection of hashtags into a set of standard forms.
    """
    return {normalize_hashtag(term) for term in _as_list(value) if normalize_hashtag(term)}


def load_hashtag_stopwords(
    domain_config: dict[str, Any] | None = None,
    domain_path: str = "config/domain.yaml",
) -> set[str]:
    """
    Load hashtag stopwords from domain config.

    Missing config intentionally returns an empty set. Caller-provided stopwords
    are still supported by the public functions below.
    """

    if domain_config is None:
        domain_config = load_domain_config(domain_path)
    if not isinstance(domain_config, dict):
        return set()

    stop_cfg = domain_config.get("hashtag_stoplist", {})
    if not isinstance(stop_cfg, dict):
        return set()
    return _normalize_terms(stop_cfg.get("default", []))


def is_noise_tag(tag: str, stopwords: set[str]) -> bool:
    """
    Decide whether a hashtag is junk: empty, a stopword, or a 'fyp'/'viral'-type tag.
    """
    t = normalize_hashtag(tag)
    return (
        not t
        or t in stopwords
        or t.startswith("fyp")
        or t.startswith("fypp")
        or t.startswith("viral")
    )


def reel_tag_sets(
    df: pd.DataFrame,
    stopwords: set[str] | None = None,
    min_len: int = 2,
    domain_config: dict[str, Any] | None = None,
    domain_path: str = "config/domain.yaml",
) -> list[set[str]]:
    """
    Turn each reel's hashtags into a cleaned set, dropping noise and very short tags.
    """
    configured_stopwords = load_hashtag_stopwords(domain_config=domain_config, domain_path=domain_path)
    stop = set(DEFAULT_STOPWORDS) | configured_stopwords | set(stopwords or set())
    sets: list[set[str]] = []
    for tags in df.get("hashtags", []):
        clean = {normalize_hashtag(t) for t in (tags or [])}
        clean = {t for t in clean if len(t) >= min_len and not is_noise_tag(t, stop)}
        if clean:
            sets.append(clean)
    return sets


def cooccurrence_edges(
    df: pd.DataFrame,
    min_tag_count: int = 5,
    min_edge_count: int = 3,
    stopwords: set[str] | None = None,
    domain_config: dict[str, Any] | None = None,
    domain_path: str = "config/domain.yaml",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Return nodes and edges with Jaccard/PMI style weights.
    """
    tagsets = reel_tag_sets(
        df,
        stopwords=stopwords,
        domain_config=domain_config,
        domain_path=domain_path,
    )
    tag_counts = Counter(t for s in tagsets for t in s)
    allowed = {t for t, c in tag_counts.items() if c >= min_tag_count}
    n_reels = len(tagsets) or 1

    pair_counts: Counter[tuple[str, str]] = Counter()
    for s in tagsets:
        s = sorted(t for t in s if t in allowed)
        for a, b in combinations(s, 2):
            pair_counts[(a, b)] += 1

    nodes = pd.DataFrame([
        {"hashtag": t, "count": c, "share": c / n_reels}
        for t, c in tag_counts.items() if t in allowed
    ]).sort_values("count", ascending=False) if allowed else pd.DataFrame(columns=["hashtag", "count", "share"])

    rows = []
    for (a, b), c in pair_counts.items():
        if c < min_edge_count:
            continue
        ca, cb = tag_counts[a], tag_counts[b]
        union = ca + cb - c
        jaccard = c / union if union else 0.0
        pmi = math.log2((c * n_reels) / (ca * cb)) if ca and cb and c else 0.0
        rows.append({
            "source": a,
            "target": b,
            "weight": c,
            "jaccard": jaccard,
            "pmi": pmi,
            "source_count": ca,
            "target_count": cb,
        })
    edges = pd.DataFrame(rows).sort_values(["weight", "jaccard"], ascending=False) if rows else pd.DataFrame(
        columns=["source", "target", "weight", "jaccard", "pmi", "source_count", "target_count"]
    )
    return nodes, edges


def cluster_hashtags(nodes: pd.DataFrame, edges: pd.DataFrame, max_edges: int = 400) -> pd.DataFrame:
    """
    Cluster hashtags. Uses networkx if available, otherwise connected components.
    """
    if nodes.empty:
        return pd.DataFrame(columns=["cluster_id", "hashtag", "count", "cluster_size", "cluster_label_suggestion"])
    counts = dict(zip(nodes["hashtag"], nodes["count"]))
    top_edges = edges.sort_values(["weight", "jaccard"], ascending=False).head(max_edges)

    try:
        import networkx as nx
        G = nx.Graph()
        for tag, count in counts.items():
            G.add_node(tag, count=count)
        for _, r in top_edges.iterrows():
            G.add_edge(r["source"], r["target"], weight=float(r["weight"]))
        comms = list(nx.algorithms.community.greedy_modularity_communities(G, weight="weight")) if G.number_of_edges() else [set(G.nodes())]
        clusters = [sorted(c, key=lambda t: counts.get(t, 0), reverse=True) for c in comms]
    except Exception:
        parent = {t: t for t in counts}

        def find(x):
            """
            Helper for grouping: return the leader of the group an item belongs to.
            """
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            """
            Helper for grouping: merge the groups that two items belong to.
            """
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for _, r in top_edges.iterrows():
            union(r["source"], r["target"])
        comps: dict[str, list[str]] = defaultdict(list)
        for t in counts:
            comps[find(t)].append(t)
        clusters = [sorted(v, key=lambda t: counts.get(t, 0), reverse=True) for v in comps.values()]

    rows = []
    clusters = sorted(clusters, key=lambda c: sum(counts.get(t, 0) for t in c), reverse=True)
    for i, cluster in enumerate(clusters, start=1):
        top = cluster[:5]
        label = ", ".join(top)
        for tag in cluster:
            rows.append({
                "cluster_id": i,
                "hashtag": tag,
                "count": counts.get(tag, 0),
                "cluster_size": len(cluster),
                "cluster_label_suggestion": label,
            })
    return pd.DataFrame(rows).sort_values(["cluster_id", "count"], ascending=[True, False])


def load_hashtag_semantic_rules(
    domain_config: dict[str, Any] | None = None,
    domain_path: str = "config/domain.yaml",
) -> dict[str, Any]:
    """
    Load semantic hashtag cluster rules from domain config.

    Supported YAML keys are ``exact``/``contains`` and the older v4 draft names
    ``terms``/``substring_terms``. Missing config returns only the generic
    fallback label.
    """

    if domain_config is None:
        domain_config = load_domain_config(domain_path)
    if not isinstance(domain_config, dict):
        domain_config = {}

    cfg = domain_config.get("hashtag_semantics", {})
    if not isinstance(cfg, dict):
        cfg = {}

    clusters = []
    for item in _as_list(cfg.get("clusters", [])):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("id") or "").strip()
        if not label:
            continue
        exact = _normalize_terms(item.get("exact", item.get("terms", [])))
        contains = _normalize_terms(item.get("contains", item.get("substring_terms", [])))
        clusters.append({
            "id": item.get("id"),
            "label": label,
            "exact": exact,
            "contains": contains,
        })

    priority_rules = []
    for item in _as_list(cfg.get("priority_substring_rules", [])):
        if not isinstance(item, dict):
            continue
        cluster_id = item.get("cluster_id")
        label = None
        for cluster in clusters:
            if cluster.get("id") == cluster_id:
                label = cluster.get("label")
                break
        if not label:
            label = item.get("label")
        if not label:
            continue
        contains = _normalize_terms(item.get("contains", []))
        if contains:
            priority_rules.append({"label": str(label), "contains": contains})

    return {
        "enabled": bool(cfg.get("enabled", True)),
        "other_label": str(cfg.get("other_label") or DEFAULT_OTHER_LABEL),
        "priority_substring_rules": priority_rules,
        "clusters": clusters,
    }


def semantic_cluster_for_tag(tag: str, rules: dict[str, Any] | None = None) -> str:
    """
    Map a hashtag to a configured semantic cluster label.
    """
    if rules is None:
        rules = load_hashtag_semantic_rules()

    t = normalize_hashtag(tag)
    other_label = str(rules.get("other_label") or DEFAULT_OTHER_LABEL) if isinstance(rules, dict) else DEFAULT_OTHER_LABEL
    if not t or not isinstance(rules, dict) or not rules.get("enabled", True):
        return other_label

    for rule in _as_list(rules.get("priority_substring_rules", [])):
        contains = rule.get("contains", set()) if isinstance(rule, dict) else set()
        if any(term and term in t for term in contains):
            return str(rule.get("label") or other_label)

    for cluster in _as_list(rules.get("clusters", [])):
        if not isinstance(cluster, dict):
            continue
        label = str(cluster.get("label") or other_label)
        if t in cluster.get("exact", set()):
            return label
        if any(term and term in t for term in cluster.get("contains", set())):
            return label
    return other_label


def semantic_cluster_summary(
    nodes: pd.DataFrame,
    top_n: int = 12,
    rules: dict[str, Any] | None = None,
    domain_config: dict[str, Any] | None = None,
    domain_path: str = "config/domain.yaml",
) -> pd.DataFrame:
    """
    Aggregate hashtag nodes into a small set of readable semantic clusters.
    """
    if nodes is None or nodes.empty:
        return pd.DataFrame(columns=["semantic_cluster", "n_tags", "total_count", "top_hashtags"])
    if rules is None:
        rules = load_hashtag_semantic_rules(domain_config=domain_config, domain_path=domain_path)
    tmp = nodes.copy()
    tmp["semantic_cluster"] = tmp["hashtag"].map(lambda tag: semantic_cluster_for_tag(tag, rules))
    rows = []
    for label, sub in tmp.groupby("semantic_cluster", dropna=False):
        sub = sub.sort_values("count", ascending=False)
        rows.append({
            "semantic_cluster": label,
            "n_tags": int(len(sub)),
            "total_count": int(sub["count"].sum()),
            "top_hashtags": ", ".join(sub["hashtag"].head(top_n).astype(str)),
        })
    return pd.DataFrame(rows).sort_values("total_count", ascending=False)


def run_network(
    df: pd.DataFrame,
    min_tag_count: int = 5,
    min_edge_count: int = 3,
    domain_config: dict[str, Any] | None = None,
    domain_path: str = "config/domain.yaml",
) -> dict[str, pd.DataFrame]:
    """
    Build the network of hashtags that appear together and return its points and links as tables.
    """
    nodes, edges = cooccurrence_edges(
        df,
        min_tag_count=min_tag_count,
        min_edge_count=min_edge_count,
        domain_config=domain_config,
        domain_path=domain_path,
    )
    clusters = cluster_hashtags(nodes, edges)
    semantic_rules = load_hashtag_semantic_rules(domain_config=domain_config, domain_path=domain_path)
    semantic = semantic_cluster_summary(nodes, rules=semantic_rules)
    return {"nodes": nodes, "edges": edges, "clusters": clusters, "semantic_clusters": semantic}
