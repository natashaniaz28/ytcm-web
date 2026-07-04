from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from .common import DEFAULT_DB

DEFAULT_SCOPE_OUT = "outputs/analysis"


class _ScopeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        """
        Raise an error instead of quitting the program when the arguments are wrong.
        """
        raise ValueError(message)


def _parse_args(prog: str, arg: str, configure):
    """
    Parse a command's arguments using the given option setup, raising a plain error on bad input.
    """
    parser = _ScopeArgumentParser(prog=prog, add_help=True)
    configure(parser)
    try:
        return parser.parse_args(shlex.split(arg))
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def _default_out(filename: str) -> str:
    """
    Build a default output path for a file in the scope output folder.
    """
    return str(Path(DEFAULT_SCOPE_OUT) / filename)


def _write(df, path):
    """
    Write a table to a CSV file.
    """
    from nami_code.analysis.namiscope import write_csv

    return write_csv(df, path)


def _load(db_path):
    """
    Load the reel-level scope data from the database.
    """
    from nami_code.analysis.namiscope import load_scope_dataframe

    return load_scope_dataframe(db_path)


class NAMIScopeCommands:
    def do_timeline(self, arg):
        """
        Export timeline counts by entity.
        Syntax: timeline [songs|assets|hashtags|creators] [--freq D|W|M] [--db data/corpus.db] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("entity", nargs="?", choices=["songs", "assets", "hashtags", "creators"], default="songs")
            parser.add_argument("--freq", choices=["D", "W", "M"], default="M")
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("timeline", arg, configure)
            from nami_code.analysis.namiscope import make_timeline

            df = _load(args.db)
            out_df = make_timeline(df, args.entity, args.freq)
            out_path = args.out or _default_out(f"timeline_{args.entity}_{args.freq}.csv")
            path = _write(out_df, out_path)
            print(f"Timeline written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"timeline failed: {exc}")

    def do_dist(self, arg):
        """
        Export summary statistics for a numeric field.
        Syntax: dist FIELD [--db data/corpus.db] [--out PATH]
        FIELD: likes | plays | views | comments | duration
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("field", choices=["likes", "plays", "views", "comments", "duration"])
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("dist", arg, configure)
            from nami_code.analysis.namiscope import describe_distribution

            df = _load(args.db)
            out_df = describe_distribution(df, args.field)
            out_path = args.out or _default_out(f"dist_{args.field}.csv")
            path = _write(out_df, out_path)
            print(f"Distribution written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"dist failed: {exc}")

    def do_topreels(self, arg):
        """
        Export top reels by metric.
        Syntax: topreels FIELD [N] [--db data/corpus.db] [--out PATH]
        FIELD: likes | plays | views | comments | duration | impact
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("field", nargs="?", choices=["likes", "plays", "views", "comments", "duration", "impact"], default="impact")
            parser.add_argument("n", nargs="?", type=int, default=20)
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("topreels", arg, configure)
            from nami_code.analysis.namiscope import top_reels

            df = _load(args.db)
            out_df = top_reels(df, args.field, args.n)
            out_path = args.out or _default_out(f"topreels_{args.field}.csv")
            path = _write(out_df, out_path)
            print(f"Top reels written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"topreels failed: {exc}")

    def do_correlate(self, arg):
        """
        Export Pearson/Spearman correlation for two fields.
        Syntax: correlate FIELD1 FIELD2 [--db data/corpus.db] [--out PATH]
        FIELD: likes | plays | views | comments | duration | impact
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            fields = ["likes", "plays", "views", "comments", "duration", "impact"]
            parser.add_argument("field1", choices=fields)
            parser.add_argument("field2", choices=fields)
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("correlate", arg, configure)
            from nami_code.analysis.namiscope import correlate_fields

            df = _load(args.db)
            out_df = correlate_fields(df, args.field1, args.field2)
            out_path = args.out or _default_out(f"correlate_{args.field1}_{args.field2}.csv")
            path = _write(out_df, out_path)
            print(f"Correlation written: {path}")
            row = out_df.iloc[0].to_dict() if not out_df.empty else {}
            print(f"n={row.get('n', 0)} pearson={row.get('pearson')} spearman={row.get('spearman')}")
        except Exception as exc:
            print(f"correlate failed: {exc}")

    def do_weekdays(self, arg):
        """
        Export counts by weekday and hour.
        Syntax: weekdays [taken_at|ingested_at] [--db data/corpus.db] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("date_field", nargs="?", choices=["taken_at", "ingested_at"], default="taken_at")
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("weekdays", arg, configure)
            from nami_code.analysis.namiscope import weekday_counts

            df = _load(args.db)
            out_df = weekday_counts(df, args.date_field)
            out_path = args.out or _default_out(f"weekdays_{args.date_field}.csv")
            path = _write(out_df, out_path)
            print(f"Weekday counts written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"weekdays failed: {exc}")

    def do_impact(self, arg):
        """
        Export impact summaries.
        Syntax: impact [--by song|asset|hashtag|creator] [--db data/corpus.db] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--by", choices=["song", "asset", "hashtag", "creator"], default="song")
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("impact", arg, configure)
            from nami_code.analysis.namiscope import impact_summary

            df = _load(args.db)
            out_df = impact_summary(df, args.by)
            out_path = args.out or _default_out(f"impact_{args.by}.csv")
            path = _write(out_df, out_path)
            print(f"Impact summary written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"impact failed: {exc}")
