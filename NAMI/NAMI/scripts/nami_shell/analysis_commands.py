from __future__ import annotations
import re
import sqlite3
from pathlib import Path

from .common import *


class NAMIAnalysisCommands:
    def do_analyse(self, _):
        """
        Run the existing console analysis module.
        Syntax: analyse
        """
        try:
            runpy.run_module("nami_code.analysis.analyse", run_name="__main__")
        except Exception as e:
            logger.error(f"Error during analyse: {e}.")

    def do_checkspam(self, arg):
        """
        Run the spam checker and mark matches as is_spam=1 (excluded by analyse).
        Syntax: checkspam [--db data/corpus.db] [--include-blocked true|false]
        Matches caption spam terms (config/domain.yaml) and, by default, also marks
        reels the vision tagger flagged 'blocked' (content-policy refusals — adult/
        prohibited content that can never be tagged); their 'blocked' state is kept,
        so visionblocked still lists them. Pass --include-blocked false to mark only
        caption-term matches.
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("checkspam"))
        db_path = opts.get("db", DEFAULT_DB)
        include_blocked = _bool_from_flag(opts.get("include_blocked"), True)
        try:
            from nami_code.analysis.check_spam import run_check_spam
            run_check_spam(db_path=db_path, mark=True, include_blocked=include_blocked)
        except Exception as e:
            logger.error(f"Error during checkspam: {e}.")

    def do_spamreport(self, arg):
        """
        Build an HTML spam report: an embedded gallery of the flagged reels plus
        statistics (terms that fired, vision/Gemini blocks, which song/asset
        attracts spam, upload-timing spikes, uploader concentration, repeated
        captions, engagement).
        Syntax: spamreport [--db data/corpus.db] [--out outputs/report_out/spam_report.html]
                           [--limit 150] [--include-blocked true|false] [--silent]
        The spam set is recomputed the same way checkspam marks it (caption terms
        plus, by default, vision 'blocked' reels), so it works even before
        checkspam has been run. Read-only — it does not change the database.
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("spamreport"))
        db_path = opts.get("db", DEFAULT_DB)
        out_html = opts.get("out", "outputs/report_out/spam_report.html")
        gallery_limit = int(opts["limit"]) if opts.get("limit") else 150
        include_blocked = _bool_from_flag(opts.get("include_blocked"), True)
        try:
            from nami_code.analysis.spam_report import build
            path = build(db_path=db_path, out_html=out_html,
                         gallery_limit=gallery_limit, include_blocked=include_blocked)
            print(f"Report written to {path}.")
            if not _bool_from_flag(opts.get("silent"), False):
                webbrowser.open(Path(path).resolve().as_uri())
        except Exception as e:
            logger.error(f"Error during spamreport: {e}.")

    def do_snapshot(self, arg):
        """
        Store current reels table as a visibility snapshot.
        Syntax: snapshot [--db data/corpus.db] [--note "manual snapshot"]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("snapshot"))
        db_path = opts.get("db", DEFAULT_DB)
        note = opts.get("note", "manual snapshot")
        try:
            from nami_code.analysis.snapshot_churn import snapshot_current
            crawl_id = snapshot_current(db_path=db_path, note=note)
            print(f"Snapshot saved to {crawl_id}.")
        except Exception as e:
            logger.error(f"Error during snapshot: {e}.")

    def do_sample(self, _):
        """
        Generate close-reading sample CSV/HTML files.
        Syntax: sample
        """
        try:
            runpy.run_path(str(Path("scripts/manual_sampler.py")), run_name="__main__")
        except Exception as e:
            logger.error(f"Error during sample: {e}.")

    def do_robustness(self, arg):
        """
        Run robustness checks and write CSV outputs.
        Syntax: robustness [--db data/corpus.db] [--schema config/schema.yaml] [--out outputs/report_out/tables] [--sources keyword,vision] [--min-conf 0.2]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("robustness"))
        db_path = opts.get("db", DEFAULT_DB)
        schema_path = opts.get("schema", DEFAULT_SCHEMA)
        out_dir = Path(opts.get("out", "outputs/report_out/tables"))
        sources = [s.strip() for s in opts.get("sources", "keyword").split(",") if s.strip()]
        min_conf = _bounded_float(opts.get("min_conf"), "--min-conf", 0.0, 1.0, 0.2)

        try:
            from nami_code.analysis.analyse import load_reels, load_schema, classify, validate_sources
            validate_sources(sources)
            from nami_code.analysis.robustness_check import run_robustness

            df = load_reels(db_path=db_path)
            schema = load_schema(schema_path)
            df = classify(df, schema, sources=sources, db_path=db_path, min_conf=min_conf)

            tables = run_robustness(df, schema)

            out_dir.mkdir(parents=True, exist_ok=True)
            written = 0
            for name, table in tables.items():
                safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("_") or "robustness"
                table.to_csv(out_dir / f"{safe_name}.csv", index=False)
                written += 1

            print(f"Robustness tables written to {out_dir} ({written} files).")

        except Exception as e:
            logger.error(f"Error during robustness: {e}.")

    def do_concordance(self, arg):
        """
        Check whether keyword and vision classification agree, per dimension.
        Syntax: concordance [--db data/corpus.db] [--schema config/schema.yaml] [--out outputs/report_out/tables] [--min-conf 0.2]
        Read-only. Compares, for every vision-tagged reel (vision_state='done'), the
        keyword category set against the vision category set per dimension, using a
        confidence-weighted Jaccard. Prints a per-dimension summary and writes
        concordance_by_dimension.csv plus per-dimension confusion / disagreement
        tables. High mean concordance = the two independent signals converge.
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("concordance"))
        db_path = opts.get("db", DEFAULT_DB)
        schema_path = opts.get("schema", DEFAULT_SCHEMA)
        out_dir = Path(opts.get("out", "outputs/report_out/tables"))
        min_conf = _bounded_float(opts.get("min_conf"), "--min-conf", 0.0, 1.0, 0.2)

        try:
            from nami_code.analysis.analyse import load_reels, load_schema
            from nami_code.analysis.concordance import run_concordance

            df = load_reels(db_path=db_path)
            schema = load_schema(schema_path)
            tables = run_concordance(df, schema, db_path=db_path, min_conf=min_conf)

            summary = tables.get("concordance_by_dimension")
            if summary is None or summary.empty:
                print("No comparable (vision-tagged) reels found. Run tagvision first.")
                return

            print(f"Keyword-vs-vision concordance (min-conf {min_conf}):\n")
            for _, r in summary.iterrows():
                print(f"  {r['dimension']}: mean {r['mean_concordance']:.3f} "
                      f"(median {r['median_concordance']:.3f}) over {r['comparable_reels']} reels "
                      f"| exact {r['exact_agreement_share']:.0%}, none {r['zero_agreement_share']:.0%} "
                      f"| unknown: both {r['both_unknown']}, kw-only {r['keyword_only_unknown']}, "
                      f"vis-only {r['vision_only_unknown']}")

            out_dir.mkdir(parents=True, exist_ok=True)
            written = 0
            for name, table in tables.items():
                safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("_") or "concordance"
                table.to_csv(out_dir / f"{safe_name}.csv", index=False)
                written += 1
            print(f"\nConcordance tables written: {out_dir} ({written} files)")

        except Exception as e:
            logger.error(f"Error during concordance: {e}.")


    def do_report(self, arg):
        """
        Build the HTML report and CSV/chart outputs.
        Syntax: report [--db data/corpus.db] [--schema config/schema.yaml] [--out outputs/report_out] [--sources keyword,vision] [--min-conf 0.2] [--only-vision-tagged] [--silent]
        With no --sources flag the report includes every source available for the
        DB (keyword, plus vision when the corpus has been vision-tagged); pass
        --sources to restrict it (e.g. --sources keyword).
        --only-vision-tagged restricts the report to reels the vision tagger has
        processed (vision_state='done'); only takes effect when 'vision' is a source.
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("report"))
        db_path = opts.get("db", DEFAULT_DB)
        schema_path = opts.get("schema", DEFAULT_SCHEMA)
        out_dir = opts.get("out", DEFAULT_REPORT_OUT)
        sources_arg = opts.get("sources")
        min_conf = _bounded_float(opts.get("min_conf"), "--min-conf", 0.0, 1.0, 0.2)
        only_vision_tagged = _bool_from_flag(opts.get("only_vision_tagged"), False)
        try:
            from nami_code.analysis.analyse import validate_sources, available_sources
            if sources_arg:
                sources = [s.strip() for s in sources_arg.split(",") if s.strip()]
            else:
                sources = available_sources(db_path)
                print(f"Sources: {', '.join(sources)} (all available. Pass --sources to override).")
            validate_sources(sources)
            from nami_code.reports.report import ReportConfig, build
            config = ReportConfig(
                db_path=db_path,
                schema_path=schema_path,
                out_dir=out_dir,
                sources=sources,
                min_conf=min_conf,
                only_vision_tagged=only_vision_tagged,
            )
            path = build(config)
            print(f"Report written to {path}.")
            if not _bool_from_flag(opts.get("silent"), False):
                webbrowser.open(Path(path).resolve().as_uri())
        except Exception as e:
            logger.error(f"Error during report: {e}.")

