"""
NAMI-native graph helpers for Instagram Reel research, derived from YTCM TubeGraph.
"""
from __future__ import annotations

import csv
import sqlite3
from collections import Counter, defaultdict, deque
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

try:
    import networkx as nx
except Exception:
    nx = None


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


def _clean_text(value: Any) -> str:
    """
    Turn any value into a trimmed string.
    """
    return str(value or "").strip()


def _node_id(kind: str, value: Any) -> str:
    """
    Build a node id by tagging a value with its kind, for example 'song:plastic_love'.
    """
    return f"{kind}:{_clean_text(value)}"


def _song_label(record: dict[str, Any]) -> str:
    """
    Make a readable label for a song (artist – title, or its id).
    """
    artist = _clean_text(record.get("song_artist"))
    title = _clean_text(record.get("song_title"))
    song_id = _clean_text(record.get("song_id"))
    if artist and title:
        return f"{artist} – {title}"
    return title or song_id


def _asset_label(record: dict[str, Any]) -> str:
    """
    Make a readable label for an audio variant.
    """
    variant = _clean_text(record.get("variant_label"))
    asset_id = _clean_text(record.get("asset_id"))
    if variant and asset_id:
        return f"{variant} ({asset_id})"
    return variant or asset_id


def _dedupe(values: Iterable[Any]) -> list[str]:
    """
    Return the values as a list with blanks and duplicates removed, order kept.
    """
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def load_graph_records(db_path: str) -> list[dict]:
    """
    Load graph-ready Reel records from the existing NAMI SQLite schema.

    Each record contains core Reel/song/asset fields, a list of hashtags, and
    optional annotation-derived ``vision_labels`` / ``vision_categories`` lists
    when the ``annotations`` table exists.
    """
    with _connect(db_path) as conn:
        if not _table_exists(conn, "reels"):
            raise RuntimeError("Missing required table: reels")

        has_songs = _table_exists(conn, "songs")
        has_hashtags = _table_exists(conn, "reel_hashtags")
        has_annotations = _table_exists(conn, "annotations")

        if has_songs:
            rows = conn.execute(
                """
                SELECT
                    r.reel_pk,
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
                    r.comment_count
                FROM reels r
                LEFT JOIN songs s ON s.song_id = r.song_id
                ORDER BY r.reel_pk
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    reel_pk,
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
                    comment_count
                FROM reels
                ORDER BY reel_pk
                """
            ).fetchall()

        records = [dict(row) for row in rows]
        by_reel = {record["reel_pk"]: record for record in records}
        for record in records:
            record["hashtags"] = []
            record["vision_labels"] = []
            record["vision_categories"] = []

        if has_hashtags and by_reel:
            for row in conn.execute("SELECT reel_pk, hashtag FROM reel_hashtags ORDER BY reel_pk, hashtag"):
                record = by_reel.get(row["reel_pk"])
                if record is not None:
                    record["hashtags"].append(_clean_text(row["hashtag"]))

        if has_annotations and by_reel:
            query = """
                SELECT reel_pk, dimension, category, source
                FROM annotations
                WHERE source = 'vision' OR source LIKE 'vision%'
                ORDER BY reel_pk, dimension, category
            """
            for row in conn.execute(query):
                record = by_reel.get(row["reel_pk"])
                if record is None:
                    continue
                category = _clean_text(row["category"])
                dimension = _clean_text(row["dimension"])
                if category:
                    record["vision_labels"].append(category)
                if dimension and category:
                    record["vision_categories"].append(f"{dimension}:{category}")

        for record in records:
            record["hashtags"] = _dedupe(record.get("hashtags", []))
            record["vision_labels"] = _dedupe(record.get("vision_labels", []))
            record["vision_categories"] = _dedupe(record.get("vision_categories", []))

        return records


def _filter_edges(counter: Counter[tuple[str, str]], min_weight: int, relation: str) -> list[dict[str, Any]]:
    """
    Keep only the links at or above a minimum weight and tag them with the relation type.
    """
    edges: list[dict[str, Any]] = []
    for (source, target), weight in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
        if weight < min_weight:
            continue
        edges.append({"source": source, "target": target, "weight": weight, "relation": relation})
    return edges


def build_hashtag_cooccurrence(records, min_weight=1):
    """
    Build weighted hashtag-hashtag co-occurrence nodes and edges.
    """
    tag_counts: Counter[str] = Counter()
    edge_counts: Counter[tuple[str, str]] = Counter()

    for record in records:
        tags = sorted(_dedupe(record.get("hashtags", [])))
        tag_counts.update(tags)
        for left, right in combinations(tags, 2):
            edge_counts[(_node_id("hashtag", left), _node_id("hashtag", right))] += 1

    nodes = [
        {"id": _node_id("hashtag", tag), "label": tag, "kind": "hashtag", "reel_count": count}
        for tag, count in sorted(tag_counts.items())
    ]
    edges = _filter_edges(edge_counts, int(min_weight), "cooccurs_in_reel")
    return nodes, edges


def build_creator_song_graph(records, min_weight=1):
    """
    Build weighted bipartite creator-song nodes and edges.
    """
    creator_counts: Counter[str] = Counter()
    songs: dict[str, dict[str, Any]] = {}
    edge_counts: Counter[tuple[str, str]] = Counter()

    for record in records:
        creator = _clean_text(record.get("creator_pseudo"))
        song_id = _clean_text(record.get("song_id"))
        if not creator or not song_id:
            continue
        creator_counts[creator] += 1
        song_node = _node_id("song", song_id)
        songs[song_node] = {
            "id": song_node,
            "label": _song_label(record),
            "kind": "song",
            "bipartite": "song",
            "song_id": song_id,
            "song_title": _clean_text(record.get("song_title")),
            "song_artist": _clean_text(record.get("song_artist")),
        }
        edge_counts[(_node_id("creator", creator), song_node)] += 1

    nodes = [
        {"id": _node_id("creator", creator), "label": creator, "kind": "creator", "bipartite": "creator", "reel_count": count}
        for creator, count in sorted(creator_counts.items())
    ] + [songs[key] for key in sorted(songs)]
    edges = _filter_edges(edge_counts, int(min_weight), "creator_uses_song")
    return nodes, edges


def build_creator_asset_graph(records, min_weight=1):
    """
    Build weighted bipartite creator-asset nodes and edges.
    """
    creator_counts: Counter[str] = Counter()
    assets: dict[str, dict[str, Any]] = {}
    edge_counts: Counter[tuple[str, str]] = Counter()

    for record in records:
        creator = _clean_text(record.get("creator_pseudo"))
        asset_id = _clean_text(record.get("asset_id"))
        if not creator or not asset_id:
            continue
        creator_counts[creator] += 1
        asset_node = _node_id("asset", asset_id)
        assets[asset_node] = {
            "id": asset_node,
            "label": _asset_label(record),
            "kind": "asset",
            "bipartite": "asset",
            "asset_id": asset_id,
            "variant_label": _clean_text(record.get("variant_label")),
        }
        edge_counts[(_node_id("creator", creator), asset_node)] += 1

    nodes = [
        {"id": _node_id("creator", creator), "label": creator, "kind": "creator", "bipartite": "creator", "reel_count": count}
        for creator, count in sorted(creator_counts.items())
    ] + [assets[key] for key in sorted(assets)]
    edges = _filter_edges(edge_counts, int(min_weight), "creator_uses_asset")
    return nodes, edges


def build_song_hashtag_graph(records, min_weight=1):
    """
    Build weighted bipartite song-hashtag nodes and edges.
    """
    songs: dict[str, dict[str, Any]] = {}
    tag_counts: Counter[str] = Counter()
    edge_counts: Counter[tuple[str, str]] = Counter()

    for record in records:
        song_id = _clean_text(record.get("song_id"))
        if not song_id:
            continue
        song_node = _node_id("song", song_id)
        songs[song_node] = {
            "id": song_node,
            "label": _song_label(record),
            "kind": "song",
            "bipartite": "song",
            "song_id": song_id,
            "song_title": _clean_text(record.get("song_title")),
            "song_artist": _clean_text(record.get("song_artist")),
        }
        for tag in _dedupe(record.get("hashtags", [])):
            tag_counts[tag] += 1
            edge_counts[(song_node, _node_id("hashtag", tag))] += 1

    nodes = [songs[key] for key in sorted(songs)] + [
        {"id": _node_id("hashtag", tag), "label": tag, "kind": "hashtag", "bipartite": "hashtag", "reel_count": count}
        for tag, count in sorted(tag_counts.items())
    ]
    edges = _filter_edges(edge_counts, int(min_weight), "song_hashtag")
    return nodes, edges


def _edge_weight(edge: dict[str, Any]) -> float:
    """
    Read a link's weight as a number, defaulting to 1.
    """
    try:
        return float(edge.get("weight", 1) or 1)
    except (TypeError, ValueError):
        return 1.0


def _component_ids(node_ids: list[str], edges: list[dict[str, Any]]) -> dict[str, tuple[int, int]]:
    """
    Group connected points together and give each its group id and group size.
    """
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        source = _clean_text(edge.get("source"))
        target = _clean_text(edge.get("target"))
        if source in adjacency and target in adjacency:
            adjacency[source].add(target)
            adjacency[target].add(source)

    result: dict[str, tuple[int, int]] = {}
    seen: set[str] = set()
    component_id = 0
    for start in node_ids:
        if start in seen:
            continue
        queue: deque[str] = deque([start])
        seen.add(start)
        component: list[str] = []
        while queue:
            node = queue.popleft()
            component.append(node)
            for neighbour in adjacency[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        for node in component:
            result[node] = (component_id, len(component))
        component_id += 1
    return result


def _to_networkx(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]):
    """
    Build a networkx graph from the points and links, if networkx is installed.
    """
    if nx is None:
        return None
    graph = nx.Graph()
    for node in nodes:
        node_id = _clean_text(node.get("id"))
        if not node_id:
            continue
        graph.add_node(node_id, **{k: v for k, v in node.items() if k != "id"})
    for edge in edges:
        source = _clean_text(edge.get("source"))
        target = _clean_text(edge.get("target"))
        if source and target:
            graph.add_edge(source, target, **{k: v for k, v in edge.items() if k not in {"source", "target"}})
    return graph


def compute_node_metrics(nodes, edges):
    """
    Compute degree, weighted_degree and connected-component metadata.
    """
    node_by_id = {_clean_text(node.get("id")): dict(node) for node in nodes if _clean_text(node.get("id"))}
    degree: Counter[str] = Counter()
    weighted_degree: Counter[str] = Counter()

    for edge in edges:
        source = _clean_text(edge.get("source"))
        target = _clean_text(edge.get("target"))
        if source not in node_by_id or target not in node_by_id:
            continue
        weight = _edge_weight(edge)
        degree[source] += 1
        degree[target] += 1
        weighted_degree[source] += weight
        weighted_degree[target] += weight

    if nx is not None:
        graph = _to_networkx(list(node_by_id.values()), edges)
        component_info: dict[str, tuple[int, int]] = {}
        if graph is not None:
            for idx, component in enumerate(nx.connected_components(graph)):
                size = len(component)
                for node_id in component:
                    component_info[str(node_id)] = (idx, size)
        else:
            component_info = _component_ids(list(node_by_id), edges)
    else:
        component_info = _component_ids(list(node_by_id), edges)

    metrics: list[dict[str, Any]] = []
    for node_id in sorted(node_by_id):
        row = dict(node_by_id[node_id])
        comp_id, comp_size = component_info.get(node_id, (-1, 1))
        row["degree"] = int(degree.get(node_id, 0))
        row["weighted_degree"] = weighted_degree.get(node_id, 0)
        row["component_id"] = comp_id
        row["component_size"] = comp_size
        metrics.append(row)
    return metrics


def _all_keys(rows: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    """
    Collect all column names across the rows, with the preferred ones first.
    """
    keys: list[str] = []
    for key in preferred:
        if any(key in row for row in rows):
            keys.append(key)
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return keys


def _csv_value(value: Any) -> Any:
    """
    Make a value safe to write to a CSV cell (join lists, blank for missing).
    """
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(v) for v in value)
    if value is None:
        return ""
    return value


def write_edges_csv(path, edges):
    """
    Write the network's links to a CSV file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = _all_keys(list(edges), ["source", "target", "weight", "relation"])
    if not fields:
        fields = ["source", "target", "weight", "relation"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for edge in edges:
            writer.writerow({key: _csv_value(edge.get(key, "")) for key in fields})


def write_nodes_csv(path, nodes):
    """
    Write the network's points to a CSV file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = _all_keys(list(nodes), ["id", "label", "kind", "degree", "weighted_degree", "component_id", "component_size"])
    if not fields:
        fields = ["id", "label", "kind", "degree", "weighted_degree", "component_id", "component_size"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for node in nodes:
            writer.writerow({key: _csv_value(node.get(key, "")) for key in fields})


def _safe_attr(value: Any) -> str | int | float | bool:
    """
    Convert a value into something a graph file can store.
    """
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(v) for v in value)
    return str(value)


def write_gexf(path, nodes, edges):
    """
    Write a GEXF graph if networkx is available.

    Raises RuntimeError with a clear message when networkx is missing.
    """
    if nx is None:
        raise RuntimeError("GEXF export requires networkx. CSV files were written.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    graph = nx.Graph()
    for node in nodes:
        node_id = _clean_text(node.get("id"))
        if not node_id:
            continue
        attrs = {key: _safe_attr(value) for key, value in node.items() if key != "id"}
        graph.add_node(node_id, **attrs)
    for edge in edges:
        source = _clean_text(edge.get("source"))
        target = _clean_text(edge.get("target"))
        if not source or not target:
            continue
        attrs = {key: _safe_attr(value) for key, value in edge.items() if key not in {"source", "target"}}
        graph.add_edge(source, target, **attrs)
    nx.write_gexf(graph, path)


def graph_status(db_path: str) -> dict[str, Any]:
    """
    Return lightweight graph-readiness information.
    """
    status: dict[str, Any] = {"db_path": db_path, "db_exists": Path(db_path).exists(), "networkx": nx is not None}
    if not status["db_exists"]:
        return status
    with _connect(db_path) as conn:
        tables = ["reels", "reel_hashtags", "songs", "track_variants", "annotations", "crawl_runs", "reel_seen"]
        for table in tables:
            exists = _table_exists(conn, table)
            status[f"has_{table}"] = exists
            if exists:
                status[f"{table}_count"] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        if _table_exists(conn, "reels"):
            status["creator_count"] = conn.execute("SELECT COUNT(DISTINCT creator_pseudo) AS n FROM reels WHERE creator_pseudo IS NOT NULL AND creator_pseudo != ''").fetchone()["n"]
            status["song_count"] = conn.execute("SELECT COUNT(DISTINCT song_id) AS n FROM reels WHERE song_id IS NOT NULL AND song_id != ''").fetchone()["n"]
            status["asset_count"] = conn.execute("SELECT COUNT(DISTINCT asset_id) AS n FROM reels WHERE asset_id IS NOT NULL AND asset_id != ''").fetchone()["n"]
        if _table_exists(conn, "reel_hashtags"):
            status["hashtag_count"] = conn.execute("SELECT COUNT(DISTINCT hashtag) AS n FROM reel_hashtags WHERE hashtag IS NOT NULL AND hashtag != ''").fetchone()["n"]
    return status


def networkx_available() -> bool:
    """
    Return whether the optional networkx library is installed.
    """
    return nx is not None
