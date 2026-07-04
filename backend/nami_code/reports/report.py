"""
Combined NAMI report generator.

Merges the former report_a / report_b / report_c into a single styled HTML
page plus one CSV per analysis. Adjust the settings block at the bottom and run.
"""
from __future__ import annotations

import base64
import html
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from nami_code.reports.fonts import configure_plot_fonts

from nami_code.analysis import analyse as A
from nami_code.analysis.hashtag_network import run_network
from nami_code.analysis.manual_sampler import (
    close_reading_sample,
    curated_close_reading_sample,
    write_sample_html,
)
from nami_code.analysis.robustness_check import run_robustness
from nami_code.analysis.snapshot_churn import (snapshot_status, churn_summary,
                                               churn_interval_summary)
from nami_code.analysis.distinctive_hashtags import (
    top_distinctive_by_song,
    top_distinctive_by_asset,
)
from nami_code.analysis.asset_profile import (
    asset_profile,
    asset_vs_song_delta,
    asset_audio_filter_profile,
)
from nami_code.analysis.audio_filter_index import (
    add_audio_filter_scores,
    audio_filter_summary,
)
from nami_code.analysis.creator_structure import (
    creator_kpis,
    creator_summary,
    multi_song_creators,
)
from nami_code.analysis.caption_style import caption_style_summary
from nami_code.analysis.impact_by_theme import impact_by_theme
from nami_code.domain_config import DEFAULT_PATHS, load_nami_config


@dataclass
class ReportConfig:
    db_path: str = "data/corpus.db"
    schema_path: str = "config/schema.yaml"
    out_dir: str = "outputs/report_out"
    project_path: str = "config/project.yaml"
    domain_path: str = "config/domain.yaml"

    sources: list[str] = field(default_factory=lambda: ["keyword"])
    min_conf: float = 0.2

    only_vision_tagged: bool = False

    min_tag_count: int = 5
    min_edge_count: int = 3

    distinctive_min_count: int = 3
    distinctive_top_n_song: int = 15
    distinctive_top_n_asset: int = 10

    profile_dim: str = "context"
    impact_quantile: float = 0.90
    impact_group_col: str = "song_id"

    cooccurrence_min_count_floor: int = 3
    cooccurrence_top_n: int = 20

    table_max_rows: int = 20
    table_max_rows_wide: int = 40

    heatmap_min_share: float = 0.03




DEFAULT_REPORT_SECTIONS = [
    "scope",
    "classifiability",
    "audio_filter",
    "category_distribution",
    "category_share_by_song",
    "dimension_combinations",
    "song_distinctiveness",
    "distinctive_hashtags",
    "asset_profiles",
    "impact_by_theme",
    "creator_structure",
    "caption_style",
    "hashtag_network",
    "close_reading",
    "robustness",
    "snapshots",
]

GENERIC_REPORT_LABELS = {
    "audio_filter_section": "Music discourse vs. visual framing",
    "music_discourse": "Music discourse terms",
    "visual_world": "Visual-world terms",
    "audio_filter_share": "Visual framing without music terms",
}

GENERIC_SECTION_LABELS = {
    "scope": "Scope",
    "classifiability": "How much is classifiable",
    "audio_filter": "Music discourse vs. visual framing",
    "category_distribution": "Category distribution per dimension",
    "category_share_by_song": "Category share by song",
    "dimension_combinations": "Dimension combinations",
    "song_distinctiveness": "Range across songs",
    "distinctive_hashtags": "Distinctive hashtags",
    "asset_profiles": "Audio assets vs. song",
    "impact_by_theme": "Category share in the top-impact segment",
    "creator_structure": "Creator structure",
    "caption_style": "Caption style and classifiability",
    "hashtag_network": "Hashtag network",
    "close_reading": "Close-reading sample",
    "robustness": "Robustness checks",
    "snapshots": "Snapshot / churn status",
}


def _as_mapping(value) -> dict:
    """
    Return the value if it is a dictionary, otherwise an empty dictionary.
    """
    return value if isinstance(value, dict) else {}


def _schema_dimension_label(schema: dict, dim: str) -> str:
    """
    Return a readable label for a dimension, falling back to a tidied version of its id.
    """
    dim_cfg = _as_mapping(_as_mapping(schema.get("dimensions", {})).get(dim, {}))
    return str(dim_cfg.get("label") or dim.replace("_", " ").title())


def _first_schema_dimensions(schema: dict) -> list[str]:
    """
    List the dimension names defined in the schema, in order.
    """
    dims = _as_mapping(schema.get("dimensions", {}))
    return list(dims.keys())


def _load_report_framing(cfg: ReportConfig, schema: dict) -> dict:
    """
    Work out the report's titles, labels, chosen dimensions and which sections to show, from the project and domain config.
    """
    nami_config = load_nami_config(
        project_path=cfg.project_path,
        schema_path=cfg.schema_path,
        domain_path=cfg.domain_path,
    )
    project = _as_mapping(nami_config.get("project", {}))
    domain = _as_mapping(nami_config.get("domain", {}))
    report = _as_mapping(domain.get("report", {}))

    schema_dims = _first_schema_dimensions(schema)
    primary = str(report.get("primary_dimension") or (schema_dims[0] if schema_dims else "context"))
    secondary = str(report.get("secondary_dimension") or (schema_dims[1] if len(schema_dims) > 1 else primary))
    valid_dims = set(schema_dims)
    if primary not in valid_dims and schema_dims:
        primary = schema_dims[0]
    if secondary not in valid_dims and len(schema_dims) > 1:
        secondary = schema_dims[1]

    enabled = report.get("enabled_sections")
    if not isinstance(enabled, list) or not enabled:
        enabled = None

    section_labels = dict(GENERIC_SECTION_LABELS)
    section_labels.update(_as_mapping(report.get("sections", {})))

    labels = dict(GENERIC_REPORT_LABELS)
    labels.update(_as_mapping(report.get("labels", {})))

    title = str(report.get("title") or project.get("name") or "NAMI report")
    html_title = str(report.get("html_title") or title)
    subtitle = str(report.get("subtitle") or "Interactive research report")

    return {
        "title": title,
        "html_title": html_title,
        "subtitle": subtitle,
        "project_display_name": str(report.get("project_display_name") or project.get("name") or title),
        "primary_dimension": primary,
        "secondary_dimension": secondary,
        "dimensions": [d for d in [primary, secondary] if d in valid_dims] or schema_dims or list(A.DIMENSIONS),
        "enabled_sections": set(enabled) if enabled else None,
        "sections": section_labels,
        "labels": labels,
    }


def _enabled(framing: dict, section_id: str) -> bool:
    """
    Return whether a given report section should be shown.
    """
    enabled = framing.get("enabled_sections")
    return enabled is None or section_id in enabled


def _section_title(framing: dict, section_id: str, fallback: str) -> str:
    """
    Return the configured title for a section, or a fallback.
    """
    return str(_as_mapping(framing.get("sections", {})).get(section_id) or fallback)


def _report_label(framing: dict, key: str, fallback: str) -> str:
    """
    Return a configured wording label, or a fallback.
    """
    return str(_as_mapping(framing.get("labels", {})).get(key) or fallback)


PALETTE = [
    "#e8794a", "#c44e6e", "#5b6ba8",
    "#3a8a8c", "#d4a843", "#7a5a8e", "#b07d4a",
]
BG = "#1a1626"
FG = "#f4ece2"
GRID = "#3a3550"
MUTED = "#9a90a8"


def _apply_plot_theme() -> None:
    """
    Apply the report's dark colour theme and fonts to every chart.
    """
    configure_plot_fonts()
    plt.rcParams.update({
        "figure.facecolor": BG,
        "axes.facecolor": BG,
        "savefig.facecolor": BG,
        "text.color": FG,
        "axes.labelcolor": FG,
        "xtick.color": FG,
        "ytick.color": FG,
        "axes.edgecolor": GRID,
        "grid.color": GRID,
        "font.size": 10,
    })


def _b64(path: Path | None) -> str:
    """
    Embed an image file directly into the HTML as text, or return nothing if it is missing.
    """
    if not path or not Path(path).exists():
        return ""
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f'<img src="data:image/png;base64,{data}">'


def _fmt_pct(x):
    """
    Format a fraction as a percentage string.
    """
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return x


def _churn_headline(intervals: pd.DataFrame) -> str:
    """One-line summary of the most recent churn interval — the headline number."""
    if intervals is None or intervals.empty:
        return ""
    r = intervals.iloc[-1]
    return (
        f'<p class="lead"><b>Latest interval {r["from_date"]} → {r["to_date"]}:</b> '
        f'{int(r["n_assets"])} assets · retention {_fmt_pct(r["retention_pooled"])} '
        f'(reel-weighted) / {_fmt_pct(r["retention_median"])} (median per asset) · '
        f'new {_fmt_pct(r["new_rate_pooled"])} · '
        f'{int(r["retained"])} retained, {int(r["new"])} new, {int(r["lost"])} lost.</p>'
    )


def _table(df: pd.DataFrame, max_rows: int, pct_cols: list[str] | None = None) -> str:
    """
    Turn a table into an HTML table, trimmed to a row limit, showing chosen columns as percentages.
    """
    if df is None or df.empty:
        return '<p class="empty">No data.</p>'
    show = df.head(max_rows).copy()
    for c in pct_cols or []:
        if c in show:
            show[c] = show[c].map(_fmt_pct)
    return show.to_html(index=False, escape=True, classes="data", border=0)


def _save_csv(df: pd.DataFrame, tables: Path, name: str) -> None:
    """
    Save a table to a CSV file in the report's tables folder.
    """
    if df is None:
        return
    df.to_csv(tables / f"{name}.csv", index=False)


def _section(title: str, lead: str, *blocks: str) -> str:
    """
    Wrap a heading, intro line and content blocks into one HTML report section.
    """
    body = "\n".join(b for b in blocks if b)
    lead_html = f'<p class="lead">{lead}</p>' if lead else ""
    return f"<section>\n <h2>{title}</h2>\n {lead_html}\n {body}\n</section>"


def _grid(*imgs: str) -> str:
    """
    Lay several images out side by side in a grid.
    """
    cells = "".join(f"<div>{im}</div>" for im in imgs if im)
    return f'<div class="grid">{cells}</div>' if cells else ""


def chart_classifiable(df, schema, charts: Path, dims: list[str]) -> Path:
    """
    Draw a bar chart of what share of reels could be classified on each dimension.
    """
    rates = [A.classifiable_rate(df, schema, d) for d in dims]
    fig, ax = plt.subplots(figsize=(7, 2.4))
    labels = [_schema_dimension_label(schema, d) for d in dims]
    vals = [r["rate"] * 100 for r in rates]
    bars = ax.barh(labels, vals, color=PALETTE[:len(dims)])
    for b, r in zip(bars, rates):
        ax.text(b.get_width() + 1.5, b.get_y() + b.get_height() / 2,
                f"{r['n_classifiable']} / {r['n_total']} ({r['rate'] * 100:.0f}%)",
                va="center", color=FG, fontsize=9)
    ax.set_xlim(0, 105)
    ax.set_xlabel("% of reels with a category-bearing caption")
    fig.tight_layout()
    p = charts / "classifiable.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def chart_distribution(df, dim, schema, charts: Path) -> Path | None:
    """
    Draw a chart of how reels are spread across the categories of a dimension.
    """
    d = A.distribution_classifiable(df, dim, schema)
    if d.empty:
        return None
    sub = d.head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, max(2.5, .45 * len(sub))))
    ax.barh(sub["label"], sub["share_of_classifiable"] * 100,
            color=PALETTE[(A.DIMENSIONS.index(dim) if dim in A.DIMENSIONS else 0) % len(PALETTE)])
    ax.set_xlabel("% of classifiable reels")
    ax.grid(alpha=.25, axis="x")
    ax.set_title(dim.capitalize(), color=FG, loc="left", fontsize=12)
    fig.tight_layout()
    p = charts / f"dist_{dim}.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


MIN_CHURN_POINTS = 3


def chart_churn(intervals: pd.DataFrame, charts: Path) -> Path | None:
    """Line chart of retention / new-rate across refresh intervals; None until enough points.

    Plots the per-interval headline rates over time, so a month of every-other-day refresh
    crawls reads as a trend rather than a wall of per-asset tables. Returns None (→ the report
    renders a stub note) until at least ``MIN_CHURN_POINTS`` intervals exist.
    """
    if intervals is None or len(intervals) < MIN_CHURN_POINTS:
        return None
    fig, ax = plt.subplots(figsize=(8, 3))
    x = list(range(len(intervals)))
    ax.plot(x, intervals["retention_pooled"] * 100, marker="o", color=PALETTE[0],
            label="retention (reel-weighted)")
    ax.plot(x, intervals["new_rate_pooled"] * 100, marker="s",
            color=PALETTE[1 % len(PALETTE)], label="new rate")
    ax.set_xticks(x)
    ax.set_xticklabels([r.to_date for r in intervals.itertuples()],
                       rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, 105)
    ax.set_ylabel("% of reels")
    ax.grid(alpha=.25, axis="y")
    ax.legend(fontsize=8, loc="lower left")
    ax.set_title("Churn across refresh intervals", color=FG, loc="left", fontsize=12)
    fig.tight_layout()
    p = charts / "churn_timeseries.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def chart_song_heatmap(df, dim, schema, charts: Path, min_share: float) -> Path | None:
    """
    Draw a heatmap of each song's category mix.
    """
    prof = A.song_profile(df, dim, schema)
    cat_cols = [c for c in prof.columns if c not in ("n_total", "n_classifiable")]
    keep = [c for c in cat_cols if prof[c].max() > min_share]
    if not keep or len(prof) < 2:
        return None
    M = prof[keep].T.values
    fig, ax = plt.subplots(figsize=(max(6, .9 * len(prof) + 3), max(3, .4 * len(keep) + 1)))
    im = ax.imshow(M, aspect="auto", cmap="magma", vmin=0)
    ax.set_xticks(range(len(prof)))
    ax.set_xticklabels(prof.index, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(keep)))
    ax.set_yticklabels(keep, fontsize=8)
    cb = fig.colorbar(im, ax=ax, shrink=.8)
    cb.set_label("Share of classifiable reels", color=FG)
    cb.ax.yaxis.set_tick_params(color=FG)
    plt.setp(cb.ax.get_yticklabels(), color=FG)
    ax.set_title(dim.capitalize(), color=FG, loc="left", fontsize=12)
    fig.tight_layout()
    p = charts / f"songheat_{dim}.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return p


def chart_audio_filter(af: pd.DataFrame, charts: Path, framing: dict | None = None) -> Path | None:
    """
    Draw a chart of the music-versus-visual wording scores.
    """
    if af is None or af.empty:
        return None
    sub = af.sort_values("audio_filter_share", ascending=True)
    fig, ax = plt.subplots(figsize=(8, max(3.0, 0.42 * len(sub))))
    ax.barh(sub["song_id"], sub["audio_filter_share"] * 100, color=PALETTE[0])
    ax.set_xlabel("% of reels: " + _report_label(framing or {}, "audio_filter_share", "Visual framing without music terms"))
    ax.grid(axis="x", alpha=.3)
    fig.tight_layout()
    p = charts / "audio_filter_by_song.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def chart_music_vs_visual(af: pd.DataFrame, charts: Path, framing: dict | None = None) -> Path | None:
    """
    Draw a chart contrasting music-talk reels with visual-world reels.
    """
    if af is None or af.empty:
        return None
    fig, ax = plt.subplots(figsize=(6.5, 5))
    ax.scatter(af["music_discourse_share"] * 100, af["visual_world_share"] * 100,
               s=70, color=PALETTE[1])
    for _, r in af.iterrows():
        ax.text(r["music_discourse_share"] * 100 + .6, r["visual_world_share"] * 100 + .6,
                str(r["song_id"]), fontsize=8, color=FG)
    ax.set_xlabel("% with " + _report_label(framing or {}, "music_discourse", "music discourse terms"))
    ax.set_ylabel("% with " + _report_label(framing or {}, "visual_world", "visual-world terms"))
    ax.grid(alpha=.3)
    fig.tight_layout()
    p = charts / "music_vs_visual.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def chart_creator_distribution(cs: pd.DataFrame, charts: Path) -> Path | None:
    """
    Draw a chart of how reels are spread across creators.
    """
    if cs is None or cs.empty:
        return None
    dist = cs["n_reels"].value_counts().sort_index().head(10)
    fig, ax = plt.subplots(figsize=(6.5, 3.5))
    ax.bar(dist.index.astype(str), dist.values, color=PALETTE[2])
    ax.set_xlabel("Reels per creator")
    ax.set_ylabel("Creators")
    ax.grid(axis="y", alpha=.3)
    fig.tight_layout()
    p = charts / "creator_distribution.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def chart_semantic_clusters(semantic: pd.DataFrame, charts: Path) -> Path | None:
    """
    Draw a chart of the main hashtag clusters.
    """
    if semantic is None or semantic.empty:
        return None
    c = semantic.sort_values("total_count", ascending=True)
    fig, ax = plt.subplots(figsize=(8, max(3, .45 * len(c))))
    ax.barh(c["semantic_cluster"], c["total_count"], color=PALETTE[3])
    ax.set_xlabel("Sum of hashtag occurrences")
    ax.grid(axis="x", alpha=.3)
    fig.tight_layout()
    p = charts / "semantic_hashtag_clusters.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def chart_cluster_sizes(clusters: pd.DataFrame, charts: Path) -> Path | None:
    """
    Draw a chart of how big each hashtag cluster is.
    """
    if clusters is None or clusters.empty:
        return None
    c = (clusters.groupby("cluster_id")
         .agg(size=("hashtag", "count"), total_count=("count", "sum"),
              label=("cluster_label_suggestion", "first"))
         .reset_index()
         .sort_values("total_count", ascending=True)
         .tail(12))
    fig, ax = plt.subplots(figsize=(8, max(3, .38 * len(c))))
    ax.barh(c["label"], c["total_count"], color=PALETTE[5])
    ax.set_xlabel("Sum of hashtag occurrences")
    ax.grid(axis="x", alpha=.3)
    fig.tight_layout()
    p = charts / "hashtag_cluster_sizes.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def chart_network_edges(edges: pd.DataFrame, charts: Path) -> Path | None:
    """
    Draw a chart of the strongest hashtag links.
    """
    if edges is None or edges.empty:
        return None
    e = edges.head(25).sort_values("weight", ascending=True)
    labels = e.apply(lambda r: f"{r['source']} + {r['target']}", axis=1)
    fig, ax = plt.subplots(figsize=(9, max(4, .32 * len(e))))
    ax.barh(labels, e["weight"], color=PALETTE[6])
    ax.set_xlabel("Shared reels")
    ax.grid(axis="x", alpha=.3)
    fig.tight_layout()
    p = charts / "top_hashtag_edges.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def chart_combinations(combo: pd.DataFrame, charts: Path) -> Path | None:
    """
    Draw a chart of the most common category combinations.
    """
    if combo is None or combo.empty:
        return None
    c = combo.head(15).iloc[::-1]
    fig, ax = plt.subplots(figsize=(9, max(3, .42 * len(c))))
    ax.barh(c["combo_label"], c["reels"], color=PALETTE[4])
    ax.set_xlabel("Reels")
    ax.grid(axis="x", alpha=.3)
    fig.tight_layout()
    p = charts / "dimension_combinations.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    return p


def build(cfg: ReportConfig) -> Path:
    """
    Build the full HTML research report, with all its charts and tables, and save it.
    """
    _apply_plot_theme()

    out = Path(cfg.out_dir)
    charts = out / "charts"
    tables = out / "tables"
    charts.mkdir(parents=True, exist_ok=True)
    tables.mkdir(parents=True, exist_ok=True)

    schema = A.load_schema(cfg.schema_path)
    framing = _load_report_framing(cfg, schema)
    report_dims = list(framing.get("dimensions") or A.DIMENSIONS)
    primary_dim = str(framing.get("primary_dimension") or report_dims[0])
    secondary_dim = str(framing.get("secondary_dimension") or (report_dims[1] if len(report_dims) > 1 else primary_dim))
    df = A.load_reels(cfg.db_path)
    vision_subset_note = ""
    if cfg.only_vision_tagged and "vision" in cfg.sources:
        import sqlite3
        n_before = len(df)
        try:
            conn = sqlite3.connect(cfg.db_path)
            done_pks = {r[0] for r in conn.execute(
                "SELECT reel_pk FROM vision_state WHERE status='done'")}
            conn.close()
        except Exception:
            done_pks = set()
        df = df[df["reel_pk"].isin(done_pks)].reset_index(drop=True)
        vision_subset_note = (
            f"Restricted to {len(df)} vision-processed reels (vision_state='done') "
            f"of {n_before} total — not corpus-representative.")
        print(f"  [only-vision-tagged] {vision_subset_note}")
    df = A.classify(df, schema, sources=cfg.sources, db_path=cfg.db_path, min_conf=cfg.min_conf)
    df_af = add_audio_filter_scores(df)

    ver = schema.get("version", "?")
    n = len(df)
    ns = df["song_id"].nunique()
    n_assets = df["asset_id"].nunique() if "asset_id" in df else 0
    n_creators = df["creator_pseudo"].nunique() if "creator_pseudo" in df else 0

    summary = A.summary(df)
    primary_profile = A.song_profile(df, primary_dim, schema).reset_index()
    secondary_profile = A.song_profile(df, secondary_dim, schema).reset_index() if secondary_dim != primary_dim else pd.DataFrame()
    distinctiveness = {d: A.song_distinctiveness(df, d, schema) for d in report_dims}
    combos = A.combination_summary(df, schema, top=cfg.table_max_rows_wide, primary_dim=primary_dim, secondary_dim=secondary_dim)

    af_song = audio_filter_summary(df_af, group_col="song_id")
    af_asset = asset_audio_filter_profile(df)

    distinct_song = top_distinctive_by_song(
        df, min_count=cfg.distinctive_min_count, top_n=cfg.distinctive_top_n_song)
    distinct_asset = top_distinctive_by_asset(
        df, min_count=cfg.distinctive_min_count, top_n=cfg.distinctive_top_n_asset)

    profile_dim = cfg.profile_dim or primary_dim
    if profile_dim not in report_dims:
        profile_dim = primary_dim
    ap = asset_profile(df, schema, dim=profile_dim)
    adelta = asset_vs_song_delta(df, schema, dim=profile_dim)

    ckpi = creator_kpis(df)
    cs = creator_summary(df)
    msg = multi_song_creators(df)
    capsum = caption_style_summary(df, schema)
    impact = impact_by_theme(df, schema, dim=profile_dim, group_col=cfg.impact_group_col,
                             q=cfg.impact_quantile)

    net = run_network(df, min_tag_count=cfg.min_tag_count, min_edge_count=cfg.min_edge_count)
    semantic = net.get("semantic_clusters", pd.DataFrame())

    sample = close_reading_sample(df)
    curated = curated_close_reading_sample(df)
    robust = run_robustness(df, schema, dimensions=report_dims)
    snap = snapshot_status(cfg.db_path)
    churn = churn_summary(cfg.db_path)
    churn_intervals = churn_interval_summary(churn)

    csv_outputs = {
        "summary": summary,
        f"{primary_dim}_profile": primary_profile,
        f"{secondary_dim}_profile": secondary_profile,
        **{f"song_distinctiveness_{d}": distinctiveness[d] for d in distinctiveness},
        f"{primary_dim}_{secondary_dim}_combinations": combos,
        "audio_filter_by_song": af_song,
        "audio_filter_by_asset": af_asset,
        "distinctive_hashtags_by_song": distinct_song,
        "distinctive_hashtags_by_asset": distinct_asset,
        "asset_profile": ap,
        "asset_vs_song_delta": adelta,
        "creator_kpis": ckpi,
        "creator_summary": cs,
        "multi_song_creators": msg,
        "caption_style_summary": capsum,
        "impact_by_theme": impact,
        "hashtag_network_nodes": net["nodes"],
        "hashtag_network_edges": net["edges"],
        "hashtag_network_clusters": net["clusters"],
        "semantic_hashtag_clusters": semantic,
        "close_reading_sample": sample,
        "close_reading_curated": curated,
        "snapshot_status": snap,
        "snapshot_churn": churn,
        "snapshot_churn_intervals": churn_intervals,
        **{f"robustness_{k}": v for k, v in robust.items()},
    }
    for name, table in csv_outputs.items():
        _save_csv(table, tables, name)

    sample_html = write_sample_html(sample, out / "close_reading_sample.html")
    curated_html = write_sample_html(curated, out / "close_reading_curated.html")

    clf_img = _b64(chart_classifiable(df, schema, charts, report_dims))
    dist_imgs = [_b64(chart_distribution(df, d, schema, charts)) for d in report_dims]
    heat_imgs = [_b64(chart_song_heatmap(df, d, schema, charts, cfg.heatmap_min_share))
                 for d in report_dims]
    audio_img = _b64(chart_audio_filter(af_song, charts, framing))
    scatter_img = _b64(chart_music_vs_visual(af_song, charts, framing))
    creator_img = _b64(chart_creator_distribution(cs, charts))
    semantic_img = _b64(chart_semantic_clusters(semantic, charts))
    cluster_img = _b64(chart_cluster_sizes(net["clusters"], charts))
    edges_img = _b64(chart_network_edges(net["edges"], charts))
    combo_img = _b64(chart_combinations(combos, charts))

    sections = []

    def append_section(section_id: str, title: str, lead: str, *blocks: str) -> None:
        """
        Add one section to the report, but only if it is switched on.
        """
        if _enabled(framing, section_id):
            sections.append(_section(_section_title(framing, section_id, title), lead, *blocks))

    primary_label = _schema_dimension_label(schema, primary_dim)
    secondary_label = _schema_dimension_label(schema, secondary_dim)

    append_section(
        "scope",
        "Scope",
        "",
        f"""<div class="note">
        Built from reel captions and hashtags, not from video content; it reflects how
        creators describe their reels. Percentages are taken over <b>classifiable</b> reels
        (those whose caption or hashtags map to at least one category), with the reference
        count shown alongside. Reels flagged as spam are excluded. Repeated-crawl
        (snapshot) comparison only becomes meaningful once at least two snapshots exist.
        </div>""")

    append_section(
        "classifiability",
        "How much is classifiable",
        "Share of reels per dimension whose caption or hashtags map to at least one "
        "category. The remainder is excluded from the distributions below.",
        clf_img)

    append_section(
        "audio_filter",
        "Music discourse vs. visual framing",
        "Per song: share of reels mentioning music-related terms, share mentioning "
        "visual-world terms, and the share with visual framing but no music terms.",
        _grid(audio_img, scatter_img),
        _table(af_song, cfg.table_max_rows,
               pct_cols=["music_discourse_share", "visual_world_share", "audio_filter_share"]))

    append_section(
        "category_distribution",
        "Category distribution per dimension",
        "Across all songs combined, over classifiable reels only.",
        _grid(*dist_imgs))

    append_section(
        "category_share_by_song",
        "Category share by song",
        "Per song, the share of its classifiable reels in each category. Brighter cells "
        "mark categories used more by that song.",
        _grid(*heat_imgs))

    append_section(
        "dimension_combinations",
        f"{primary_label} × {secondary_label} combinations",
        f"How often each {primary_label.lower()} category co-occurs with each "
        f"{secondary_label.lower()} category, with the number of songs and median impact "
        "per combination.",
        combo_img,
        _table(combos, cfg.table_max_rows_wide))

    dist_blocks = []
    for d in report_dims:
        dist_blocks.append(f"<h3>{html.escape(_schema_dimension_label(schema, d))}</h3>")
        dist_blocks.append(_table(distinctiveness[d], cfg.table_max_rows))
    append_section(
        "song_distinctiveness",
        "Range across songs",
        "Per category: the difference between the highest and lowest per-song share, the "
        "range, and the song with the highest share. A larger range means the category is "
        "more song-specific.",
        *dist_blocks)

    append_section(
        "distinctive_hashtags",
        "Distinctive hashtags",
        "Hashtags over-represented for a song or audio asset relative to the rest of the "
        "corpus (smoothed log-odds and lift); generic reach tags are filtered.",
        "<h3>By song</h3>",
        _table(
            distinct_song[["song_id", "hashtag", "n_group", "n_other", "lift", "log_odds"]]
            if not distinct_song.empty else distinct_song, 60),
        "<h3>By audio asset</h3>",
        _table(
            distinct_asset[["asset_id", "hashtag", "n_group", "n_other", "lift", "log_odds"]]
            if not distinct_asset.empty else distinct_asset, 60))

    append_section(
        "asset_profiles",
        "Audio assets vs. song",
        "The platform splits each song into several audio objects. These tables show each "
        "asset's category profile and how far it deviates from its song's average.",
        "<h3>Largest asset deviations</h3>",
        _table(adelta, cfg.table_max_rows_wide),
        "<h3>Asset profile</h3>",
        _table(ap, cfg.table_max_rows_wide),
        "<h3>Audio framing per asset</h3>",
        _table(af_asset, cfg.table_max_rows,
               pct_cols=["music_discourse_share", "visual_world_share", "audio_filter_share"]))

    imp_show = impact.sort_values("delta", ascending=False) if not impact.empty else impact
    append_section(
        "impact_by_theme",
        "Category share in the top-impact segment",
        f"Within each {cfg.impact_group_col}, the top {int(cfg.impact_quantile * 100)}% of "
        "reels by impact vs. the rest. Positive delta means the category appears more in the "
        "top segment.",
        _table(imp_show, cfg.table_max_rows_wide,
               pct_cols=["share_top", "share_rest", "delta"]))

    append_section(
        "creator_structure",
        "Creator structure",
        "Distribution of reels per creator, summary metrics, and creators posting across "
        "more than one song.",
        creator_img,
        "<h3>Metrics</h3>",
        _table(ckpi, cfg.table_max_rows),
        "<h3>Multi-song creators</h3>",
        _table(msg, cfg.table_max_rows_wide))

    append_section(
        "caption_style",
        "Caption style and classifiability",
        "By caption type: counts, length, hashtag count, share in Japanese script, and "
        "the share classifiable per dimension.",
        _table(capsum, cfg.table_max_rows,
               pct_cols=["japanese_script_share"]
               + [f"{d}_classifiable_share" for d in report_dims]))

    append_section(
        "hashtag_network",
        "Hashtag network",
        "Co-occurring hashtags grouped into interpretable semantic clusters, the raw "
        "algorithmic clusters, and the strongest pairwise connections.",
        "<h3>Semantic clusters</h3>",
        semantic_img,
        _table(semantic, cfg.table_max_rows),
        "<h3>Algorithmic clusters</h3>",
        cluster_img,
        _table(net["clusters"], cfg.table_max_rows_wide),
        "<h3>Strongest connections</h3>",
        edges_img,
        _table(net["edges"], cfg.table_max_rows_wide))

    append_section(
        "close_reading",
        "Close-reading sample",
        "Reels selected for qualitative reading: a broad automatic selection and a curated "
        "selection covering specific case types. Full exports are written separately.",
        f'<p class="files">Exports: <code>{html.escape(sample_html.name)}</code> · '
        f'<code>{html.escape(curated_html.name)}</code></p>',
        "<h3>Automatic selection</h3>",
        _table(sample, cfg.table_max_rows),
        "<h3>Curated selection</h3>",
        _table(curated, cfg.table_max_rows_wide))

    kw_audit = robust["keyword_audit"]
    if not kw_audit.empty and "potentially_broad" in kw_audit:
        kw_show = kw_audit[kw_audit["potentially_broad"] == True]
        if kw_show.empty:
            kw_show = kw_audit
    else:
        kw_show = kw_audit
    robustness_blocks = [
        "<h3>Potentially broad keywords</h3>",
        _table(kw_show, cfg.table_max_rows_wide),
    ]
    for dim in report_dims:
        dim_label = html.escape(_schema_dimension_label(schema, dim))
        robustness_blocks.extend([
            f"<h3>Unclassified {dim_label}: frequent hashtags</h3>",
            _table(robust.get(f"unknown_{dim}_hashtags", pd.DataFrame()), cfg.table_max_rows_wide),
            f"<h3>Reels with many {dim_label} categories</h3>",
            _table(robust.get(f"multicategory_{dim}_reels", pd.DataFrame()), cfg.table_max_rows),
            f"<h3>Validation sample ({dim_label})</h3>",
            _table(robust.get(f"validation_sample_{dim}", pd.DataFrame()), cfg.table_max_rows),
        ])
    append_section(
        "robustness",
        "Robustness checks",
        "Diagnostics for the keyword classification: frequent hashtags among unclassified "
        "reels, keywords broad enough to risk false positives, reels matching many "
        "categories at once, and a per-category validation sample.",
        *robustness_blocks)

    snap_note = ("No repeated snapshots stored yet."
                 if (snap.empty or "status" in snap.columns)
                 else "Snapshots present.")
    churn_chart = chart_churn(churn_intervals, charts)
    if churn_chart:
        churn_chart_block = _b64(churn_chart)
    else:
        n_int = 0 if churn_intervals is None or churn_intervals.empty else len(churn_intervals)
        churn_chart_block = (
            f'<p class="empty">Time-series chart appears once ≥{MIN_CHURN_POINTS} refresh '
            f'intervals are recorded (currently {n_int}). Keep running <code>refresh</code> '
            f'crawls at a consistent depth.</p>')
    append_section(
        "snapshots",
        "Snapshot / churn status",
        "State of repeated crawling. Churn compares which reels remain, appear, or "
        "disappear between consecutive refresh crawls. Retention is the share of the earlier "
        "crawl's reels still present in the later one.",
        f'<p class="lead">{snap_note}</p>',
        _churn_headline(churn_intervals),
        "<h3>Churn by interval</h3>",
        _table(churn_intervals, cfg.table_max_rows,
               pct_cols=["retention_pooled", "retention_median", "new_rate_pooled"]),
        churn_chart_block,
        "<h3>Snapshots</h3>",
        _table(snap, cfg.table_max_rows),
        "<h3>Churn detail (per asset)</h3>",
        _table(churn, cfg.table_max_rows_wide,
               pct_cols=["retention_rate", "new_rate"]))

    body = "\n".join(sections)
    subtitle = html.escape(str(framing.get("subtitle") or "Interactive research report"))
    subline = (f"{subtitle} · {n} reels · {ns} song(s) · "
               f"{n_assets} audio assets · {n_creators} creators · schema v{ver}")

    css = f"""
 @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=DM+Mono:wght@400;500&display=swap');
 *{{box-sizing:border-box;margin:0;padding:0}}
 body{{background:{BG};color:{FG};font-family:'Fraunces',Georgia,serif;line-height:1.6;padding:0 0 80px}}
 header{{padding:48px 7vw 32px;border-bottom:1px solid {GRID};background:linear-gradient(160deg,#241d33,{BG})}}
 h1{{font-size:2.4rem;font-weight:600;letter-spacing:-.02em}}
 .sub{{color:{MUTED};font-family:'DM Mono',monospace;font-size:.85rem;margin-top:10px}}
 main{{padding:0 7vw}} section{{margin:44px 0}}
 h2{{font-size:1.5rem;font-weight:600;margin-bottom:8px;color:{PALETTE[0]}}}
 h2::before{{content:"";display:inline-block;width:28px;height:3px;background:{PALETTE[0]};vertical-align:middle;margin-right:12px}}
 h3{{font-size:1.05rem;font-weight:600;margin:22px 0 6px;color:{PALETTE[3]}}}
 p.lead{{color:#d8cfc4;max-width:68ch;margin-bottom:18px}}
 p.files{{color:{MUTED};font-family:'DM Mono',monospace;font-size:.8rem;margin-bottom:12px}}
 p.empty{{color:{MUTED};font-style:italic;margin:8px 0 18px}}
 .grid{{display:flex;flex-wrap:wrap;gap:20px}} .grid>div{{flex:1 1 380px}}
 img{{width:100%;border-radius:10px;border:1px solid {GRID};margin:6px 0}}
 table.data{{width:100%;border-collapse:collapse;font-family:'DM Mono',monospace;font-size:.8rem;margin:10px 0 22px;display:block;overflow-x:auto}}
 th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid {GRID};white-space:nowrap}}
 th{{color:{PALETTE[3]};font-weight:500}}
 .note{{background:#241d33;border-left:3px solid {PALETTE[1]};padding:16px 20px;border-radius:6px;
        font-size:.92rem;color:#d8cfc4;max-width:78ch}}
 .note b{{color:{FG}}}
 code{{background:#241d33;padding:1px 6px;border-radius:4px;font-family:'DM Mono',monospace}}
 footer{{padding:32px 7vw 0;color:{MUTED};font-family:'DM Mono',monospace;font-size:.78rem;border-top:1px solid {GRID};margin-top:50px}}
"""

    subset_banner = (
        '<div class="sub" style="background:#fde68a;color:#7c2d12;padding:8px 12px;'
        'border-radius:6px;margin-top:8px;font-weight:600;">'
        f'⚠ {html.escape(vision_subset_note)}</div>'
    ) if vision_subset_note else ""

    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(str(framing.get("html_title") or framing.get("title") or "NAMI report"))}</title>
<style>{css}</style></head><body>
<header>
 <h1>{html.escape(str(framing.get("title") or "NAMI report"))}</h1>
 <div class="sub">{subline}</div>
 {subset_banner}
</header>
<main>
{body}
</main>
<footer>
 Generated offline from {html.escape(Path(cfg.db_path).name)} · schema v{ver} ·
 sources: {", ".join(cfg.sources)} · tables exported as CSV under tables/.
</footer>
</body></html>"""

    report_path = out / "report.html"
    report_path.write_text(html_doc, encoding="utf-8")
    print(f"Report: {report_path}")
    return report_path


if __name__ == "__main__":
    config = ReportConfig(
        db_path="data/corpus.db",
        schema_path="config/schema.yaml",
        out_dir="outputs/report_out",
        sources=["keyword"],
        min_conf=0.2,
    )

    build(config)
