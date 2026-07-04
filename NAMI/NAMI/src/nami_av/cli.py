from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from . import __version__
from . import schema, state
from .audio import extract_audio
from .config import default_config

_STUBS: dict[str, str] = {}


def _add_db_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--db", default=str(default_config().db_path),
        help="path to corpus.db (default: data/corpus.db)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nami-av",
        description="NAMI acoustic / audio-visual module (writes into corpus.db).",
    )
    parser.add_argument("--version", action="version", version=f"nami-av {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_init = sub.add_parser("init-db", help="create the module tables in corpus.db")
    _add_db_arg(p_init)

    p_status = sub.add_parser("status", help="show state-table tallies")
    _add_db_arg(p_status)

    p_audio = sub.add_parser("extract-audio", help="extract a mono WAV from a video file")
    p_audio.add_argument("video", help="path to a reel MP4")
    p_audio.add_argument("out", help="path to write the WAV")
    p_audio.add_argument("--overwrite", action="store_true")

    p_acoustic = sub.add_parser(
        "extract-acoustic", help="level-A acoustic features per asset")
    _add_db_arg(p_acoustic)
    p_acoustic.add_argument("--limit", type=int, default=None,
                            help="process at most N pending assets")
    p_acoustic.add_argument("--max-reels", type=int, default=None,
                            help="reels sampled per asset for the consensus fallback")
    p_acoustic.add_argument("--retry-failed", action="store_true",
                            help="also re-attempt assets previously marked failed")
    p_acoustic.add_argument("--no-fetch", action="store_true",
                            help="don't fetch canonical audio; use cached files or the "
                                 "reel-slice consensus only (offline)")
    p_acoustic.add_argument("--refresh-audio", action="store_true",
                            help="re-download canonical audio even if already cached")

    p_variants = sub.add_parser(
        "variants", help="symmetric, baseline-free variant comparison (pairs/dispersion/reach)")
    _add_db_arg(p_variants)

    p_align = sub.add_parser("align", help="per-reel segment alignment (Q3)")
    _add_db_arg(p_align)
    p_align.add_argument("--limit", type=int, default=None,
                         help="process at most N pending reels")
    p_align.add_argument("--max-reels", type=int, default=None,
                         help="reels aligned per asset")
    p_align.add_argument("--overlay-threshold", type=float, default=None,
                         help="align_confidence below which a reel is flagged has_overlay")
    p_align.add_argument("--retry-failed", action="store_true")

    p_edits = sub.add_parser(
        "detect-edits", help="cut detection + cross-reel alignment")
    _add_db_arg(p_edits)
    p_edits.add_argument("--limit", type=int, default=None,
                         help="process at most N pending reels")
    p_edits.add_argument("--threshold", type=float, default=None,
                         help="ContentDetector threshold (lower = more cuts)")
    p_edits.add_argument("--retry-failed", action="store_true")

    p_grp = sub.add_parser(
        "group-edits", help="group an asset's reels into near-identical edit clusters")
    _add_db_arg(p_grp)
    p_grp.add_argument("--eps", type=float, default=None,
                       help="Chamfer tolerance in seconds (DBSCAN eps)")
    p_grp.add_argument("--min-samples", type=int, default=None,
                       help="min reels to call an edit shared (default 2)")

    p_enrich = sub.add_parser(
        "enrich-meta",
        help="per-asset cross-platform stats + links via free DBs (Odesli→Deezer→MusicBrainz)")
    _add_db_arg(p_enrich)
    p_enrich.add_argument("--limit", type=int, default=None,
                          help="process at most N pending assets")
    p_enrich.add_argument("--retry-failed", action="store_true",
                          help="also re-attempt assets previously marked failed/unresolved")
    p_enrich.add_argument("--with-spotify", action="store_true",
                          help="also fetch Spotify popularity (needs SPOTIFY_* keys AND a "
                               "Premium app owner; the rest of the chain is free)")
    p_enrich.add_argument("--mb-contact", default=None,
                          help="contact (email/URL) for the MusicBrainz User-Agent "
                               "(else $MUSICBRAINZ_CONTACT)")
    p_enrich.add_argument("--mb-sleep", type=float, default=None,
                          help="seconds between MusicBrainz calls (default 1.1; their rate limit)")
    p_enrich.add_argument("--odesli-sleep", type=float, default=None,
                          help="seconds between assets to respect Odesli's ~10/min free tier "
                               "(default 6.5)")

    p_report = sub.add_parser(
        "report", help="write acoustic annotations & build the report")
    _add_db_arg(p_report)
    p_report.add_argument("--no-annotate", action="store_true",
                          help="skip writing source='acoustic' annotations into the DB")
    p_report.add_argument("--out", default=None, help="output HTML path")

    p_validate = sub.add_parser(
        "validate", help="export a hand-check sample (tempo/key + template gallery)")
    _add_db_arg(p_validate)
    p_validate.add_argument("--set-overlay-threshold", type=float, default=None,
                            help="recompute reel_acoustics.has_overlay as "
                                 "align_confidence < THRESHOLD (no re-align)")

    p_assetreport = sub.add_parser(
        "assetreport", help="per-asset metadata report (title/artist/Spotify/lyrics × acoustics)")
    _add_db_arg(p_assetreport)
    p_assetreport.add_argument("--out", default=None, help="output HTML path")

    p_all = sub.add_parser(
        "all", help="run the whole pipeline end-to-end (overnight run; resumable)")
    _add_db_arg(p_all)
    p_all.add_argument("--max-reels", type=int, default=None,
                       help="reels sampled per asset for the acoustic consensus")
    p_all.add_argument("--threshold", type=float, default=None,
                       help="ContentDetector threshold for cut detection")
    p_all.add_argument("--no-fetch", action="store_true",
                       help="don't fetch canonical audio; cached files or reel-consensus only")
    p_all.add_argument("--refresh-audio", action="store_true",
                       help="re-download canonical audio even if already cached")
    p_all.add_argument("--enrich", action="store_true",
                       help="also run enrich-meta (network: Odesli/Deezer/MusicBrainz; "
                            "off by default as it is rate-limited and slow)")

    for name, desc in _STUBS.items():
        sub.add_parser(name, help=desc)
    return parser


def _cmd_init_db(args) -> int:
    conn = schema.connect(args.db)
    print(f"Module tables present in {args.db}: {sorted(schema.sidecar_tables(conn))}")
    conn.close()
    return 0


def _cmd_status(args) -> int:
    conn = sqlite3.connect(args.db)
    try:
        schema.apply_schema(conn)
        for label, handle in (("acoustic", state.ACOUSTIC_STATE),
                              ("external", state.EXTERNAL_STATE), ("edit", state.EDIT_STATE)):
            print(f"{label:9s}: {state.status_counts(conn, handle)}")
        cov = dict(conn.execute(
            "SELECT COALESCE(audio_source,'(unset)'), COUNT(*) FROM asset_acoustics "
            "GROUP BY audio_source").fetchall())
        if cov:
            print(f"coverage : {cov}")
        ext = dict(conn.execute(
            "SELECT COALESCE(external_state,'(unset)'), COUNT(*) FROM asset_external_meta "
            "GROUP BY external_state").fetchall())
        if ext:
            print(f"external : {ext}")
    finally:
        conn.close()
    return 0


def _cmd_extract_audio(args) -> int:
    out = extract_audio(args.video, args.out, overwrite=args.overwrite)
    print(f"Wrote {out} ({Path(out).stat().st_size} bytes)")
    return 0


def _cmd_extract_acoustic(args) -> int:
    from . import features
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        kwargs = {"limit": args.limit, "include_failed": args.retry_failed, "progress": True,
                  "fetch": not args.no_fetch, "refresh_audio": args.refresh_audio}
        if args.max_reels is not None:
            kwargs["max_reels"] = args.max_reels
        counts = features.run(conn, cfg, **kwargs)
        print(f"acoustic state: {counts}")
    finally:
        conn.close()
    return 0


def _cmd_variants(args) -> int:
    from . import variants
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        summary = variants.run(conn, cfg)
        print(f"variant pairs      : {summary['n_pairs']}")
        print(f"songs (dispersion) : {summary['n_songs']}")
        print(f"reach rows         : {summary['n_reach_rows']}")
        for p in summary["tables"] + summary["figures"]:
            print(f"  wrote {p}")
    finally:
        conn.close()
    return 0


def _cmd_align(args) -> int:
    from . import alignment
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        kwargs = {"limit": args.limit, "include_failed": args.retry_failed, "progress": True}
        if args.max_reels is not None:
            kwargs["max_reels"] = args.max_reels
        if args.overlay_threshold is not None:
            kwargs["overlay_threshold"] = args.overlay_threshold
        summary = alignment.run(conn, cfg, **kwargs)
        print(f"align state: {summary['state']}")
        for p in summary["heat_strips"]:
            print(f"  heat strip {p}")
    finally:
        conn.close()
    return 0


def _cmd_detect_edits(args) -> int:
    from . import edits
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        kwargs = {"limit": args.limit, "include_failed": args.retry_failed, "progress": True}
        if args.threshold is not None:
            kwargs["threshold"] = args.threshold
        counts = edits.run(conn, cfg, **kwargs)
        print(f"edit state: {counts}")
    finally:
        conn.close()
    return 0


def _cmd_group_edits(args) -> int:
    from . import edits
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        kwargs = {"progress": True}
        if args.eps is not None:
            kwargs["eps"] = args.eps
        if args.min_samples is not None:
            kwargs["min_samples"] = args.min_samples
        summary = edits.run_grouping(conn, cfg, **kwargs)
        print(f"assets analysed: {summary['n_assets']}")
        print(f"edit clusters: {summary['n_groups']} "
              f"({summary['n_grouped_reels']} reels grouped)")
    finally:
        conn.close()
    return 0


def _cmd_enrich_meta(args) -> int:
    from . import external_ids
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        kwargs = {"limit": args.limit, "include_failed": args.retry_failed,
                  "contact": args.mb_contact, "with_spotify": args.with_spotify,
                  "progress": True}
        if args.mb_sleep is not None:
            kwargs["mb_sleep_s"] = args.mb_sleep
        if args.odesli_sleep is not None:
            kwargs["odesli_sleep_s"] = args.odesli_sleep
        counts = external_ids.run(conn, cfg, **kwargs)
        print(f"external state: {counts}")
    finally:
        conn.close()
    return 0


def _cmd_report(args) -> int:
    from . import bridge, report
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        if not args.no_annotate:
            print("writing acoustic annotations…", flush=True)
            counts = bridge.write_annotations(conn)
            print(f"acoustic annotations written: {counts}")
        print("building acoustic report (variant / provenance / families)…", flush=True)
        out = report.build(conn, cfg, out_path=args.out)
        print(f"wrote {out}")
        heat = report.build_usage_heatmaps(conn, cfg, progress=True)
        print(f"wrote {heat}")
        from . import editing
        print("building video-editing clusters report…", flush=True)
        edit_html = editing.build_video_editing(conn, cfg, progress=True)
        print(f"wrote {edit_html}")
    finally:
        conn.close()
    return 0


def _cmd_validate(args) -> int:
    from . import alignment, validate
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        if args.set_overlay_threshold is not None:
            tally = alignment.apply_overlay_threshold(conn, args.set_overlay_threshold)
            print(f"applied overlay threshold {args.set_overlay_threshold}: {tally}")
        paths = validate.export(conn, cfg, progress=True)
        for label, p in paths.items():
            print(f"  {label}: {p}")
    finally:
        conn.close()
    return 0


def _cmd_assetreport(args) -> int:
    from . import assetreport
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        out = assetreport.build(conn, cfg, out_path=args.out)
        print(f"wrote {out}")
        print(f"wrote {cfg.data_dir / 'asset_report.csv'}")
    finally:
        conn.close()
    return 0


def _cmd_all(args) -> int:
    from . import pipeline
    from .config import AvConfig

    conn = schema.connect(args.db)
    try:
        cfg = AvConfig.create(db_path=args.db)
        results = pipeline.run_all(
            conn, cfg, max_reels=args.max_reels, threshold=args.threshold,
            no_fetch=args.no_fetch, refresh_audio=args.refresh_audio,
            enrich=args.enrich, progress=True)
        print("\n===== av all complete =====")
        for stage, result in results.items():
            print(f"  {stage}: {result}")
    finally:
        conn.close()
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command in _STUBS:
        print(f"`{args.command}` is not implemented yet — {_STUBS[args.command]}.")
        return 2
    handlers = {
        "init-db": _cmd_init_db,
        "status": _cmd_status,
        "extract-audio": _cmd_extract_audio,
        "extract-acoustic": _cmd_extract_acoustic,
        "variants": _cmd_variants,
        "enrich-meta": _cmd_enrich_meta,
        "align": _cmd_align,
        "detect-edits": _cmd_detect_edits,
        "group-edits": _cmd_group_edits,
        "report": _cmd_report,
        "validate": _cmd_validate,
        "assetreport": _cmd_assetreport,
        "all": _cmd_all,
    }
    return handlers[args.command](args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
