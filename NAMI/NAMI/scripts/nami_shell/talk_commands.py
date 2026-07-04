from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from .common import DEFAULT_DB

DEFAULT_TALK_OUT = "outputs/analysis"


class _TalkArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        """
        Raise an error instead of quitting the program when the arguments are wrong.
        """
        raise ValueError(message)


def _parse_args(prog: str, arg: str, configure):
    """
    Parse a command's arguments using the given option setup, raising a plain error on bad input.
    """
    parser = _TalkArgumentParser(prog=prog, add_help=True)
    configure(parser)
    try:
        return parser.parse_args(shlex.split(arg))
    except SystemExit as exc:
        raise ValueError(str(exc)) from exc


def _default_out(filename: str) -> str:
    """
    Build a default output path for a file in the analysis output folder.
    """
    return str(Path(DEFAULT_TALK_OUT) / filename)


def _load(db_path):
    """
    Load reel captions and their hashtags from the database.
    """
    from nami_code.analysis.namitalk import load_caption_dataframe

    return load_caption_dataframe(db_path)


def _write(df, path):
    """
    Write a table to a CSV file.
    """
    from nami_code.analysis.namitalk import write_csv

    return write_csv(df, path)


class NAMITalkCommands:
    def do_captionterms(self, arg):
        """
        Export frequent caption terms.
        Syntax: captionterms [--top N] [--db data/corpus.db] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--top", type=int, default=50)
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("captionterms", arg, configure)
            from nami_code.analysis.namitalk import extract_caption_terms

            df = _load(args.db)
            out_df = extract_caption_terms(df, top=args.top)
            path = _write(out_df, args.out or _default_out("caption_terms.csv"))
            print(f"Caption terms written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"captionterms failed: {exc}")

    def do_hashtagterms(self, arg):
        """
        Export frequent hashtags.
        Syntax: hashtagterms [--top N] [--db data/corpus.db] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--top", type=int, default=50)
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("hashtagterms", arg, configure)
            from nami_code.analysis.namitalk import extract_hashtag_terms

            df = _load(args.db)
            out_df = extract_hashtag_terms(df, top=args.top)
            path = _write(out_df, args.out or _default_out("hashtag_terms.csv"))
            print(f"Hashtag terms written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"hashtagterms failed: {exc}")

    def do_distinctiveterms(self, arg):
        """
        Export lightweight distinctive terms by song or asset.
        Syntax: distinctiveterms [--by song|asset] [--source hashtags|captions] [--top N] [--db data/corpus.db] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--by", choices=["song", "asset"], default="song")
            parser.add_argument("--source", choices=["hashtags", "captions"], default="hashtags")
            parser.add_argument("--top", type=int, default=30)
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("distinctiveterms", arg, configure)
            from nami_code.analysis.namitalk import distinctive_terms

            df = _load(args.db)
            out_df = distinctive_terms(df, by=args.by, source=args.source, top=args.top)
            path = _write(out_df, args.out or _default_out("distinctive_terms.csv"))
            print(f"Distinctive terms written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"distinctiveterms failed: {exc}")

    def do_captionmarkers(self, arg):
        """
        Export simple caption markers.
        Syntax: captionmarkers [--db data/corpus.db] [--out PATH]
        """
        def configure(parser):
            """
            Add this command's options to the argument parser.
            """
            parser.add_argument("--db", default=DEFAULT_DB)
            parser.add_argument("--out")

        try:
            args = _parse_args("captionmarkers", arg, configure)
            from nami_code.analysis.namitalk import caption_markers

            df = _load(args.db)
            out_df = caption_markers(df)
            path = _write(out_df, args.out or _default_out("caption_markers.csv"))
            print(f"Caption markers written: {path}")
            print(f"Rows: {len(out_df)}")
        except Exception as exc:
            print(f"captionmarkers failed: {exc}")
