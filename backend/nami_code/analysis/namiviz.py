"""
NAMI visualization helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _require_matplotlib():
    """
    Return matplotlib.pyplot or raise a clear RuntimeError.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        raise RuntimeError(
            "matplotlib is required for visualization commands. "
            "Install with: pip install matplotlib"
        ) from exc
    return plt


def matplotlib_available() -> bool:
    """
    Return whether the plotting library is installed.
    """
    try:
        _require_matplotlib()
        return True
    except RuntimeError:
        return False


def read_csv(path: str | Path) -> pd.DataFrame:
    """
    Read a CSV file into a table, failing clearly if it is missing.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing input: {csv_path}")
    return pd.read_csv(csv_path)


def _ensure_parent(path: str | Path) -> Path:
    """
    Make sure the folder for an output file exists, then return the path.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _save_empty_plot(out_path: str | Path, title: str, message: str = "No data") -> Path:
    """
    Save a placeholder image with a title and a 'no data' message.
    """
    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.axis("off")
    ax.text(0.5, 0.55, title, ha="center", va="center", fontsize=14)
    ax.text(0.5, 0.42, message, ha="center", va="center", fontsize=11)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _clean_label(value: Any, max_len: int = 48) -> str:
    """
    Tidy a label for a chart: one line, trimmed, and shortened with an ellipsis if long.
    """
    text = "" if pd.isna(value) else str(value)
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def plot_timeline(csv_path: str | Path, out_path: str | Path, top: int = 10) -> Path:
    """
    Draw a line chart of how the top entities' counts change over time.
    """
    df = read_csv(csv_path)
    required = {"period", "entity_label", "count"}
    if not required.issubset(df.columns):
        raise ValueError(f"Timeline CSV must contain columns: {sorted(required)}")
    if df.empty:
        return _save_empty_plot(out_path, "Timeline")

    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    work = df.copy()
    work["count"] = pd.to_numeric(work["count"], errors="coerce").fillna(0)
    top_labels = (
        work.groupby("entity_label", dropna=False)["count"]
        .sum()
        .sort_values(ascending=False)
        .head(top)
        .index
    )
    work = work[work["entity_label"].isin(top_labels)]
    pivot = work.pivot_table(index="period", columns="entity_label", values="count", aggfunc="sum", fill_value=0)
    pivot = pivot.sort_index()

    fig, ax = plt.subplots(figsize=(10, 6))
    for col in pivot.columns:
        ax.plot(pivot.index.astype(str), pivot[col], marker="o", label=_clean_label(col, 32))
    ax.set_title("Timeline")
    ax.set_xlabel("Period")
    ax.set_ylabel("Count")
    ax.tick_params(axis="x", rotation=45)
    if len(pivot.columns) <= 12:
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_distribution(csv_path: str | Path, out_path: str | Path) -> Path:
    """
    Draw a small bar chart of a value's spread (min, quartiles, max).
    """
    df = read_csv(csv_path)
    stats = ["min", "p25", "median", "p75", "max"]
    if not set(stats).issubset(df.columns):
        raise ValueError(f"Distribution CSV must contain columns: {stats}")
    if df.empty:
        return _save_empty_plot(out_path, "Distribution")

    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    row = df.iloc[0]
    values = [pd.to_numeric(row.get(k), errors="coerce") for k in stats]
    values = [0 if pd.isna(v) else float(v) for v in values]
    title_field = row.get("field", row.get("column", "distribution"))

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(stats, values)
    ax.set_title(f"Distribution: {title_field}")
    ax.set_ylabel("Value")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_top_reels(csv_path: str | Path, out_path: str | Path, top: int = 20) -> Path:
    """
    Draw a bar chart of the highest-scoring reels.
    """
    df = read_csv(csv_path)
    if df.empty:
        return _save_empty_plot(out_path, "Top reels")
    value_col = "score" if "score" in df.columns else None
    if value_col is None:
        for candidate in ["play_count", "like_count", "view_count", "comment_count", "impact"]:
            if candidate in df.columns:
                value_col = candidate
                break
    if value_col is None:
        raise ValueError("Top reels CSV needs a score or metric column")

    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    work = df.head(top).copy()
    labels = work.get("code", work.get("reel_pk", work.index)).map(lambda x: _clean_label(x, 32))
    values = pd.to_numeric(work[value_col], errors="coerce").fillna(0)

    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.35 * len(work))))
    ax.barh(labels.iloc[::-1], values.iloc[::-1])
    ax.set_title("Top reels")
    ax.set_xlabel(value_col)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_impact(csv_path: str | Path, out_path: str | Path, top: int = 20) -> Path:
    """
    Draw a bar chart of total impact per entity.
    """
    df = read_csv(csv_path)
    if df.empty:
        return _save_empty_plot(out_path, "Impact")
    value_col = "impact_sum" if "impact_sum" in df.columns else "play_count_sum"
    if value_col not in df.columns:
        raise ValueError("Impact CSV must contain impact_sum or play_count_sum")

    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    work = df.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0)
    work = work.sort_values(value_col, ascending=False).head(top)
    labels = work.get("entity_label", work.get("entity_id", work.index)).map(lambda x: _clean_label(x, 42))

    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.35 * len(work))))
    ax.barh(labels.iloc[::-1], work[value_col].iloc[::-1])
    ax.set_title("Impact")
    ax.set_xlabel(value_col)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_terms(
    csv_path: str | Path,
    out_path: str | Path,
    label_col: str | None = None,
    value_col: str = "count",
    top: int = 30,
) -> Path:
    """
    Draw a bar chart of the most frequent terms or hashtags.
    """
    df = read_csv(csv_path)
    if df.empty:
        return _save_empty_plot(out_path, "Terms")
    if label_col is None:
        for candidate in ["term", "hashtag", "entity_label"]:
            if candidate in df.columns:
                label_col = candidate
                break
    if label_col is None or label_col not in df.columns:
        raise ValueError("Terms CSV needs a term/hashtag/entity_label column")
    if value_col not in df.columns:
        value_col = "score" if "score" in df.columns else value_col
    if value_col not in df.columns:
        raise ValueError("Terms CSV needs a count or score column")

    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    work = df.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0)
    work = work.sort_values(value_col, ascending=False).head(top)
    labels = work[label_col].map(lambda x: _clean_label(x, 42))

    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.32 * len(work))))
    ax.barh(labels.iloc[::-1], work[value_col].iloc[::-1])
    ax.set_title("Terms")
    ax.set_xlabel(value_col)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_graph_edges(edges_csv: str | Path, out_path: str | Path, top: int = 30) -> Path:
    """
    Draw a bar chart of the strongest links in a network.
    """
    df = read_csv(edges_csv)
    if df.empty:
        return _save_empty_plot(out_path, "Graph edges")
    required = {"source", "target", "weight"}
    if not required.issubset(df.columns):
        raise ValueError(f"Edges CSV must contain columns: {sorted(required)}")

    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    work = df.copy()
    work["weight"] = pd.to_numeric(work["weight"], errors="coerce").fillna(0)
    work = work.sort_values("weight", ascending=False).head(top)
    labels = (work["source"].astype(str) + " → " + work["target"].astype(str)).map(lambda x: _clean_label(x, 56))

    fig, ax = plt.subplots(figsize=(10, max(4.5, 0.32 * len(work))))
    ax.barh(labels.iloc[::-1], work["weight"].iloc[::-1])
    ax.set_title("Top graph edges")
    ax.set_xlabel("weight")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_graph_nodes(nodes_csv: str | Path, out_path: str | Path, top: int = 30) -> Path:
    """
    Draw a bar chart of the most connected points in a network.
    """
    df = read_csv(nodes_csv)
    if df.empty:
        return _save_empty_plot(out_path, "Graph nodes")
    value_col = "weighted_degree" if "weighted_degree" in df.columns else "degree"
    if value_col not in df.columns:
        raise ValueError("Nodes CSV must contain weighted_degree or degree")

    plt = _require_matplotlib()
    out = _ensure_parent(out_path)
    work = df.copy()
    work[value_col] = pd.to_numeric(work[value_col], errors="coerce").fillna(0)
    work = work.sort_values(value_col, ascending=False).head(top)
    label_source = "label" if "label" in work.columns else "id"
    labels = work[label_source].map(lambda x: _clean_label(x, 42))

    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.32 * len(work))))
    ax.barh(labels.iloc[::-1], work[value_col].iloc[::-1])
    ax.set_title("Top graph nodes")
    ax.set_xlabel(value_col)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out
