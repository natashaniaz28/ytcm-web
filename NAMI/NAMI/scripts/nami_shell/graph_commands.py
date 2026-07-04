from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from .common import DEFAULT_DB

DEFAULT_GRAPH_OUT = "outputs/graphs"


class _GraphArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        """
        Raise an error instead of quitting the program when the arguments are wrong.
        """
        raise ValueError(message)


def _parse_args(prog: str, arg: str, configure):
    """
    Parse a command's arguments using the given option setup, raising a plain error on bad input.
    """
    parser = _GraphArgumentParser(prog=prog, add_help=True)
    configure(parser)
    try:
        return parser.parse_args(shlex.split(arg))
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def _common_graph_options(parser: argparse.ArgumentParser, default_out: str) -> None:
    """
    Add the options shared by the graph commands: database, minimum link weight, and output path.
    """
    parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
    parser.add_argument("--min-weight", type=int, default=1, help="Minimum edge weight")
    parser.add_argument("--out", default=default_out, help="Output path prefix without suffix")


def _paths(prefix: str | Path) -> tuple[Path, Path, Path]:
    """
    Work out the edges-CSV, nodes-CSV and GEXF file paths from one output prefix.
    """
    base = Path(prefix)
    return (
        base.with_name(base.name + "_edges.csv"),
        base.with_name(base.name + "_nodes.csv"),
        base.with_suffix(".gexf"),
    )


def _write_graph(prefix: str | Path, nodes, edges) -> dict[str, object]:
    """
    Write a graph's points and links to CSV (and GEXF when possible) and report what was written.
    """
    from nami_code.analysis.namigraph import (
        compute_node_metrics,
        write_edges_csv,
        write_gexf,
        write_nodes_csv,
    )

    edges_path, nodes_path, gexf_path = _paths(prefix)
    nodes_with_metrics = compute_node_metrics(nodes, edges)
    write_edges_csv(edges_path, edges)
    write_nodes_csv(nodes_path, nodes_with_metrics)
    gexf_written = False
    gexf_message = ""
    try:
        write_gexf(gexf_path, nodes_with_metrics, edges)
        gexf_written = True
    except RuntimeError as exc:
        gexf_message = str(exc)
    return {
        "edges_path": edges_path,
        "nodes_path": nodes_path,
        "gexf_path": gexf_path,
        "gexf_written": gexf_written,
        "gexf_message": gexf_message,
        "node_count": len(nodes_with_metrics),
        "edge_count": len(edges),
    }


def _print_export_summary(name: str, result: dict[str, object]) -> None:
    """
    Print where a graph's files were written.
    """
    print(f"Graph written: {name}")
    print(f"Nodes: {result['node_count']} -> {result['nodes_path']}")
    print(f"Edges: {result['edge_count']} -> {result['edges_path']}")
    if result.get("gexf_written"):
        print(f"GEXF : {result['gexf_path']}")
    elif result.get("gexf_message"):
        print(f"GEXF : skipped ({result['gexf_message']})")


class NAMIGraphCommands:
    def do_graphstatus(self, arg):
        """
        Show NAMI graph readiness.
        Syntax: graphstatus [--db data/corpus.db]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")

        try:
            args = _parse_args("graphstatus", arg, configure)
            from nami_code.analysis.namigraph import graph_status

            status = graph_status(args.db)
            print("Graph status")
            print("------------")
            print(f"DB       : {status.get('db_path')}")
            print(f"DB exists: {status.get('db_exists')}")
            print(f"networkx : {status.get('networkx')}")
            if not status.get("db_exists"):
                print("Available graphs: no database found")
                return
            print(f"reels    : {status.get('reels_count', 0)}")
            print(f"creators : {status.get('creator_count', 0)}")
            print(f"songs    : {status.get('song_count', 0)}")
            print(f"assets   : {status.get('asset_count', 0)}")
            print(f"hashtags : {status.get('hashtag_count', 0)}")
            print(f"annotations: {status.get('annotations_count', 0)}")
            print("Available graphs:")
            print(f"- hashtags      : {bool(status.get('has_reel_hashtags'))}")
            print(f"- creator_song  : {bool(status.get('has_reels'))}")
            print(f"- creator_asset : {bool(status.get('has_reels'))}")
            print(f"- song_hashtag  : {bool(status.get('has_reels')) and bool(status.get('has_reel_hashtags'))}")
        except Exception as exc:
            print(f"graphstatus failed: {exc}")

    def do_taggraph(self, arg):
        """
        Export hashtag co-occurrence graph.
        Syntax: taggraph [--db data/corpus.db] [--min-weight N] [--out outputs/graphs/hashtags]
        """
        try:
            args = _parse_args(
                "taggraph",
                arg,
                lambda parser: _common_graph_options(parser, f"{DEFAULT_GRAPH_OUT}/hashtags"),
            )
            from nami_code.analysis.namigraph import build_hashtag_cooccurrence, load_graph_records

            records = load_graph_records(args.db)
            nodes, edges = build_hashtag_cooccurrence(records, min_weight=args.min_weight)
            result = _write_graph(args.out, nodes, edges)
            _print_export_summary("hashtags", result)
        except Exception as exc:
            print(f"taggraph failed: {exc}")

    def do_creatorgraph(self, arg):
        """
        Export creator-song or creator-asset graph.
        Syntax: creatorgraph [--kind song|asset] [--db data/corpus.db] [--min-weight N] [--out outputs/graphs/creator_song]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--kind", choices=["song", "asset"], default="song", help="Creator graph target")
            _common_graph_options(parser, f"{DEFAULT_GRAPH_OUT}/creator_song")

        try:
            args = _parse_args("creatorgraph", arg, configure)
            from nami_code.analysis.namigraph import (
                build_creator_asset_graph,
                build_creator_song_graph,
                load_graph_records,
            )

            records = load_graph_records(args.db)
            if args.kind == "asset":
                nodes, edges = build_creator_asset_graph(records, min_weight=args.min_weight)
                name = "creator_asset"
                out = args.out if args.out != f"{DEFAULT_GRAPH_OUT}/creator_song" else f"{DEFAULT_GRAPH_OUT}/creator_asset"
            else:
                nodes, edges = build_creator_song_graph(records, min_weight=args.min_weight)
                name = "creator_song"
                out = args.out
            result = _write_graph(out, nodes, edges)
            _print_export_summary(name, result)
        except Exception as exc:
            print(f"creatorgraph failed: {exc}")

    def do_songtaggraph(self, arg):
        """
        Export song-hashtag graph.
        Syntax: songtaggraph [--db data/corpus.db] [--min-weight N] [--out outputs/graphs/song_hashtag]
        """
        try:
            args = _parse_args(
                "songtaggraph",
                arg,
                lambda parser: _common_graph_options(parser, f"{DEFAULT_GRAPH_OUT}/song_hashtag"),
            )
            from nami_code.analysis.namigraph import build_song_hashtag_graph, load_graph_records

            records = load_graph_records(args.db)
            nodes, edges = build_song_hashtag_graph(records, min_weight=args.min_weight)
            result = _write_graph(args.out, nodes, edges)
            _print_export_summary("song_hashtag", result)
        except Exception as exc:
            print(f"songtaggraph failed: {exc}")

    def do_exportgraph(self, arg):
        """
        Export a named graph type.
        Syntax: exportgraph TYPE [PATH] [--db data/corpus.db] [--min-weight N]
        TYPE: hashtags | creator_song | creator_asset | song_hashtag
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("type", choices=["hashtags", "creator_song", "creator_asset", "song_hashtag"])
            parser.add_argument("path", nargs="?", help="Output path prefix without suffix")
            parser.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite database")
            parser.add_argument("--min-weight", type=int, default=1, help="Minimum edge weight")

        try:
            args = _parse_args("exportgraph", arg, configure)
            from nami_code.analysis.namigraph import (
                build_creator_asset_graph,
                build_creator_song_graph,
                build_hashtag_cooccurrence,
                build_song_hashtag_graph,
                load_graph_records,
            )

            records = load_graph_records(args.db)
            if args.type == "hashtags":
                nodes, edges = build_hashtag_cooccurrence(records, min_weight=args.min_weight)
                default_path = f"{DEFAULT_GRAPH_OUT}/hashtags"
            elif args.type == "creator_song":
                nodes, edges = build_creator_song_graph(records, min_weight=args.min_weight)
                default_path = f"{DEFAULT_GRAPH_OUT}/creator_song"
            elif args.type == "creator_asset":
                nodes, edges = build_creator_asset_graph(records, min_weight=args.min_weight)
                default_path = f"{DEFAULT_GRAPH_OUT}/creator_asset"
            else:
                nodes, edges = build_song_hashtag_graph(records, min_weight=args.min_weight)
                default_path = f"{DEFAULT_GRAPH_OUT}/song_hashtag"
            result = _write_graph(args.path or default_path, nodes, edges)
            _print_export_summary(args.type, result)
        except Exception as exc:
            print(f"exportgraph failed: {exc}")
