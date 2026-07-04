from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path

DEFAULT_ANALYSIS_OUT = "outputs/analysis"
DEFAULT_GRAPH_OUT = "outputs/graphs"
DEFAULT_VISUALS_OUT = "outputs/visuals"
DEFAULT_REPORT_OUT = "outputs/report_out"


class _VizArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        """
        Raise an error instead of quitting the program when the arguments are wrong.
        """
        raise ValueError(message)


def _parse_args(prog: str, arg: str, configure):
    """
    Parse a command's arguments using the given option setup, raising a plain error on bad input.
    """
    parser = _VizArgumentParser(prog=prog, add_help=True)
    configure(parser)
    try:
        return parser.parse_args(shlex.split(arg))
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def _analysis(name: str) -> Path:
    """
    Build a path for a file in the analysis output folder.
    """
    return Path(DEFAULT_ANALYSIS_OUT) / name


def _graph(name: str) -> Path:
    """
    Build a path for a file in the graph output folder.
    """
    return Path(DEFAULT_GRAPH_OUT) / name


def _visual(name: str) -> Path:
    """
    Build a path for a file in the visuals output folder.
    """
    return Path(DEFAULT_VISUALS_OUT) / name


def _print_written(path: Path) -> None:
    print(f"Visual written to {path}.")


def _png_data_uri(path: Path) -> str:
    import base64
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _write_visual_report(out_html: Path, sections, top: int, embed: bool = True) -> Path:
    """
    Bundle the rendered PNGs into one grouped HTML page. *sections* is a list of
    (group, title, png_path_or_None). With ``embed`` (default) each PNG is inlined
    as a base64 data-URI so the single HTML file can be passed to someone else and
    still render; with ``embed=False`` the <img> src is just the file name, which
    is lighter but only works next to the PNG folder.
    """
    import html as _html
    from datetime import datetime

    out_html.parent.mkdir(parents=True, exist_ok=True)
    n_ok = sum(1 for _, _, p in sections if p is not None)
    parts = [
        "<html><head><meta charset='utf-8'><title>NAMI visual report</title><style>",
        "body{background:#15151f;color:#e8e8ee;font-family:sans-serif;padding:24px;max-width:1100px;margin:auto}",
        "h1{color:#7fd1ff}h2{color:#ffd479;border-bottom:1px solid #3a3a4a;margin-top:44px;padding-bottom:4px}",
        "h3{color:#cdd;margin-top:26px;font-weight:normal}",
        ".sub{color:#9aa}.miss{color:#e0566f}",
        "img{max-width:100%;background:#fff;border-radius:8px;margin-top:6px;display:block}",
        "</style></head><body>",
        "<h1>📊 NAMI visual report</h1>",
        f"<p class='sub'>All NAMI visualizations ({n_ok}/{len(sections)} rendered, top {top}). "
        f"Generated {datetime.now():%Y-%m-%d %H:%M}.</p>",
    ]
    current = None
    for group, title, png in sections:
        if group != current:
            parts.append(f"<h2>{_html.escape(group)}</h2>")
            current = group
        parts.append(f"<h3>{_html.escape(title)}</h3>")
        if png is None:
            parts.append("<p class='miss'>(chart unavailable — input could not be computed)</p>")
        else:
            if embed:
                src = _png_data_uri(Path(png))
            else:
                rel = os.path.relpath(Path(png).resolve(), out_html.resolve().parent)
                src = _html.escape(rel.replace(os.sep, "/"))
            parts.append(f"<img src='{src}' alt='{_html.escape(title)}'>")
    parts.append("</body></html>")
    out_html.write_text("\n".join(parts), encoding="utf-8")
    return out_html


class NAMIVizCommands:
    def do_vizstatus(self, arg):
        """
        Show available visualization inputs.
        Syntax: vizstatus
        """
        try:
            from nami_code.analysis.namiviz import matplotlib_available

            print("Visualization status")
            print("--------------------")
            print(f"matplotlib     : {matplotlib_available()}")
            print(f"analysis inputs: {DEFAULT_ANALYSIS_OUT}")
            print(f"graph inputs   : {DEFAULT_GRAPH_OUT}")
            print(f"visual outputs : {DEFAULT_VISUALS_OUT}")
            for path in [Path(DEFAULT_ANALYSIS_OUT), Path(DEFAULT_GRAPH_OUT)]:
                if not path.exists():
                    print(f"{path}: missing")
                    continue
                files = sorted(path.glob("*.csv"))
                print(f"{path}: {len(files)} CSV files")
                for file in files[:12]:
                    print(f"  - {file.name}")
                if len(files) > 12:
                    print(f"  ... {len(files) - 12} more")
        except Exception as exc:
            print(f"vizstatus failed: {exc}")

    def do_viztimeline(self, arg):
        """
        Plot a timeline CSV.
        Syntax: viztimeline [songs|assets|hashtags|creators] [--freq D|W|M] [--top N] [--in PATH] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("entity", nargs="?", choices=["songs", "assets", "hashtags", "creators"], default="songs")
            parser.add_argument("--freq", choices=["D", "W", "M"], default="M")
            parser.add_argument("--top", type=int, default=10)
            parser.add_argument("--in", dest="in_path")
            parser.add_argument("--out")

        try:
            args = _parse_args("viztimeline", arg, configure)
            from nami_code.analysis.namiviz import plot_timeline

            in_path = Path(args.in_path) if args.in_path else _analysis(f"timeline_{args.entity}_{args.freq}.csv")
            out_path = Path(args.out) if args.out else _visual(f"timeline_{args.entity}_{args.freq}.png")
            _print_written(plot_timeline(in_path, out_path, top=args.top))
        except Exception as exc:
            print(f"viztimeline failed: {exc}")

    def do_vizdist(self, arg):
        """
        Plot distribution summary stats.
        Syntax: vizdist FIELD [--in PATH] [--out PATH]
        FIELD: likes | plays | views | comments | duration
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("field", choices=["likes", "plays", "views", "comments", "duration"])
            parser.add_argument("--in", dest="in_path")
            parser.add_argument("--out")

        try:
            args = _parse_args("vizdist", arg, configure)
            from nami_code.analysis.namiviz import plot_distribution

            in_path = Path(args.in_path) if args.in_path else _analysis(f"dist_{args.field}.csv")
            out_path = Path(args.out) if args.out else _visual(f"dist_{args.field}.png")
            _print_written(plot_distribution(in_path, out_path))
        except Exception as exc:
            print(f"vizdist failed: {exc}")

    def do_viztopreels(self, arg):
        """
        Plot top reels.
        Syntax: viztopreels FIELD [--top N] [--in PATH] [--out PATH]
        FIELD: likes | plays | views | comments | duration | impact
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("field", nargs="?", choices=["likes", "plays", "views", "comments", "duration", "impact"], default="plays")
            parser.add_argument("--top", type=int, default=20)
            parser.add_argument("--in", dest="in_path")
            parser.add_argument("--out")

        try:
            args = _parse_args("viztopreels", arg, configure)
            from nami_code.analysis.namiviz import plot_top_reels

            in_path = Path(args.in_path) if args.in_path else _analysis(f"topreels_{args.field}.csv")
            out_path = Path(args.out) if args.out else _visual(f"topreels_{args.field}.png")
            _print_written(plot_top_reels(in_path, out_path, top=args.top))
        except Exception as exc:
            print(f"viztopreels failed: {exc}")

    def do_vizimpact(self, arg):
        """
        Plot impact summaries.
        Syntax: vizimpact [--by song|asset|hashtag|creator] [--top N] [--in PATH] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--by", choices=["song", "asset", "hashtag", "creator"], default="song")
            parser.add_argument("--top", type=int, default=20)
            parser.add_argument("--in", dest="in_path")
            parser.add_argument("--out")

        try:
            args = _parse_args("vizimpact", arg, configure)
            from nami_code.analysis.namiviz import plot_impact

            in_path = Path(args.in_path) if args.in_path else _analysis(f"impact_{args.by}.csv")
            out_path = Path(args.out) if args.out else _visual(f"impact_{args.by}.png")
            _print_written(plot_impact(in_path, out_path, top=args.top))
        except Exception as exc:
            print(f"vizimpact failed: {exc}")

    def do_vizterms(self, arg):
        """
        Plot caption/hashtag/distinctive term CSVs.
        Syntax: vizterms [captions|hashtags|distinctive] [--top N] [--in PATH] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("kind", nargs="?", choices=["captions", "hashtags", "distinctive"], default="captions")
            parser.add_argument("--top", type=int, default=30)
            parser.add_argument("--in", dest="in_path")
            parser.add_argument("--out")

        try:
            args = _parse_args("vizterms", arg, configure)
            from nami_code.analysis.namiviz import plot_terms

            defaults = {
                "captions": ("caption_terms.csv", "caption_terms.png", "term", "count"),
                "hashtags": ("hashtag_terms.csv", "hashtag_terms.png", "hashtag", "count"),
                "distinctive": ("distinctive_terms.csv", "distinctive_terms.png", "term", "score"),
            }
            csv_name, png_name, label_col, value_col = defaults[args.kind]
            in_path = Path(args.in_path) if args.in_path else _analysis(csv_name)
            out_path = Path(args.out) if args.out else _visual(png_name)
            _print_written(plot_terms(in_path, out_path, label_col=label_col, value_col=value_col, top=args.top))
        except Exception as exc:
            print(f"vizterms failed: {exc}")

    def do_vizgraph(self, arg):
        """
        Plot top graph nodes and edges from graph CSVs.
        Syntax: vizgraph [hashtags|creator_song|creator_asset|song_hashtag] [--top N] [--out-dir PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("kind", nargs="?", choices=["hashtags", "creator_song", "creator_asset", "song_hashtag"], default="hashtags")
            parser.add_argument("--top", type=int, default=30)
            parser.add_argument("--out-dir", default=DEFAULT_VISUALS_OUT)

        try:
            args = _parse_args("vizgraph", arg, configure)
            from nami_code.analysis.namiviz import plot_graph_edges, plot_graph_nodes

            edges_in = _graph(f"{args.kind}_edges.csv")
            nodes_in = _graph(f"{args.kind}_nodes.csv")
            out_dir = Path(args.out_dir)
            edges_out = out_dir / f"graph_{args.kind}_edges.png"
            nodes_out = out_dir / f"graph_{args.kind}_nodes.png"
            _print_written(plot_graph_edges(edges_in, edges_out, top=args.top))
            _print_written(plot_graph_nodes(nodes_in, nodes_out, top=args.top))
        except Exception as exc:
            print(f"vizgraph failed: {exc}")

    def do_vizall(self, arg):
        """
        Recompute every analysis input, render all NAMI visualizations, and bundle
        them into one HTML report.
        Syntax: vizall [--top N] [--no-recompute] [--out PATH] [--silent]
        vizall covers the full set — timelines (songs/assets/hashtags/creators),
        distributions and top-reels for every numeric field, impact by every
        dimension, caption/hashtag/distinctive terms, and all four network graphs
        (edges + nodes). By default it first re-runs the underlying analysis and
        graph-export commands so the charts reflect the *current* database, then
        writes outputs/report_out/visual_report.html (alongside report.html and
        spam_report.html) and opens it. The PNGs go to outputs/visuals/. The charts are
        base64-embedded so the single HTML file can be shared/passed on as-is; use
        --link-images for a lighter file that references the PNGs (local only).
        Pass --no-recompute to plot whatever CSVs already exist (the old behaviour);
        --silent to skip opening the browser.
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--top", type=int, default=20)
            parser.add_argument("--no-recompute", dest="no_recompute", action="store_true")
            parser.add_argument("--link-images", dest="link_images", action="store_true")
            parser.add_argument("--out")
            parser.add_argument("--silent", action="store_true")

        try:
            args = _parse_args("vizall", arg, configure)
            top = args.top
            import webbrowser
            from nami_code.analysis import namiviz

            TL = ["songs", "assets", "hashtags", "creators"]
            DIST = ["likes", "plays", "views", "comments", "duration"]
            TOP = ["likes", "plays", "views", "comments", "duration", "impact"]
            IMP = ["song", "asset", "hashtag", "creator"]
            GRAPHS = ["hashtags", "creator_song", "creator_asset", "song_hashtag"]

            if not args.no_recompute:
                print("Recomputing analysis inputs (this runs every analysis + graph export) ...")
                recompute = (
                    [(f"timeline {e}", self.do_timeline, f"{e} --freq M") for e in TL]
                    + [(f"dist {f}", self.do_dist, f) for f in DIST]
                    + [(f"topreels {f}", self.do_topreels, f) for f in TOP]
                    + [(f"impact {b}", self.do_impact, f"--by {b}") for b in IMP]
                    + [("caption terms", self.do_captionterms, ""),
                       ("hashtag terms", self.do_hashtagterms, ""),
                       ("distinctive terms", self.do_distinctiveterms, "")]
                    + [(f"graph {g}", self.do_exportgraph, g) for g in GRAPHS]
                )
                for label, fn, fn_arg in recompute:
                    try:
                        fn(fn_arg)
                    except Exception as exc:
                        print(f"  compute failed ({label}): {exc}")
                print()

            jobs: list[tuple] = []
            for e in TL:
                jobs.append(("Timelines", f"Monthly timeline — {e}", namiviz.plot_timeline,
                             _analysis(f"timeline_{e}_M.csv"), _visual(f"timeline_{e}_M.png"), {"top": top}))
            for f in DIST:
                jobs.append(("Distributions", f"{f.title()} distribution", namiviz.plot_distribution,
                             _analysis(f"dist_{f}.csv"), _visual(f"dist_{f}.png"), {}))
            for f in TOP:
                jobs.append(("Top reels", f"Top reels by {f}", namiviz.plot_top_reels,
                             _analysis(f"topreels_{f}.csv"), _visual(f"topreels_{f}.png"), {"top": top}))
            for b in IMP:
                jobs.append(("Impact", f"Engagement impact by {b}", namiviz.plot_impact,
                             _analysis(f"impact_{b}.csv"), _visual(f"impact_{b}.png"), {"top": top}))
            jobs += [
                ("Terms", "Top caption terms", namiviz.plot_terms, _analysis("caption_terms.csv"),
                 _visual("caption_terms.png"), {"label_col": "term", "value_col": "count", "top": top}),
                ("Terms", "Top hashtags", namiviz.plot_terms, _analysis("hashtag_terms.csv"),
                 _visual("hashtag_terms.png"), {"label_col": "hashtag", "value_col": "count", "top": top}),
                ("Terms", "Distinctive terms", namiviz.plot_terms, _analysis("distinctive_terms.csv"),
                 _visual("distinctive_terms.png"), {"label_col": "term", "value_col": "score", "top": top}),
            ]
            for g in GRAPHS:
                jobs.append(("Networks", f"{g} graph — top edges", namiviz.plot_graph_edges,
                             _graph(f"{g}_edges.csv"), _visual(f"graph_{g}_edges.png"), {"top": top}))
                jobs.append(("Networks", f"{g} graph — top nodes", namiviz.plot_graph_nodes,
                             _graph(f"{g}_nodes.csv"), _visual(f"graph_{g}_nodes.png"), {"top": top}))

            written = skipped = 0
            sections: list[tuple[str, str, Path | None]] = []
            for group, title, func, in_path, out_path, kwargs in jobs:
                if not in_path.exists():
                    print(f"Skipped missing input: {in_path}")
                    skipped += 1
                    sections.append((group, title, None))
                    continue
                try:
                    _print_written(func(in_path, out_path, **kwargs))
                    written += 1
                    sections.append((group, title, out_path))
                except Exception as exc:
                    print(f"Skipped {in_path}: {exc}")
                    skipped += 1
                    sections.append((group, title, None))

            out_html = Path(args.out) if args.out else Path(DEFAULT_REPORT_OUT) / "visual_report.html"
            _write_visual_report(out_html, sections, top, embed=not args.link_images)
            kind = "linked PNGs (local only)" if args.link_images else "PNGs embedded (shareable)"
            print(f"vizall complete: {written} written, {skipped} skipped ({len(jobs)} charts; {kind})")
            print(f"Report written: {out_html}")
            if not args.silent:
                webbrowser.open(out_html.resolve().as_uri())
        except Exception as exc:
            print(f"vizall failed: {exc}")
