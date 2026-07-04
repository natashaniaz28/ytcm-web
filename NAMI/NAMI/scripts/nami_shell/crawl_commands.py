from __future__ import annotations

import shlex
import sys
import time

from .common import *


def _pop_flag(tokens: list[str], flag: str) -> bool:
    if flag in tokens:
        tokens.remove(flag)
        return True
    return False


class NAMICrawlCommands:
    def do_crawlindex(self, arg):
        """
        Stage A crawl: collect Reel IDs for configured track variants.

        Syntax:
          crawlindex
          crawlindex --refresh [--pages N] [--sleep 0.3] [--empty-stop N]

        Default mode continues the full/backfill crawl and respects index_state.

        Refresh mode starts again at page 1 for every configured asset and, by
        default, reads all available pages. It inserts only unknown Reel IDs via
        INSERT OR IGNORE and leaves existing rows untouched. Use --pages N only
        for a deliberate test/saving cap. Use --empty-stop N only for deliberate
        early stopping after N consecutive pages without new IDs.
        """
        argv = ["crawl_index.py"] + shlex.split(arg or "")
        old_argv = sys.argv[:]
        try:
            sys.argv = argv
            runpy.run_module("nami_code.crawl.crawl_index", run_name="__main__")
        except SystemExit as e:
            if getattr(e, "code", 0) not in (0, None):
                logger.error(f"crawlindex exited with status {e.code}.")
        except Exception as e:
            logger.error(f"Error during crawlindex: {e}.")
        finally:
            sys.argv = old_argv

    def do_crawldetails(self, arg):
        """
        Stage B crawl: fetch Reel metadata for pending Reel IDs.
        Syntax: crawldetails [--db data/corpus.db] [--limit N] [--sleep 0.25]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("crawldetails"))
        db_path = opts.get("db", DEFAULT_DB)
        limit = int(opts["limit"]) if opts.get("limit") else None
        sleep_s = float(opts.get("sleep", 0.25))
        try:
            from nami_code import db as dbmod
            from nami_code.crawl.crawl_details import run

            old_path = dbmod.DB_PATH
            dbmod.DB_PATH = db_path
            try:
                conn = dbmod.get_conn()
                try:
                    run(conn, sleep_s=sleep_s, limit=limit)
                finally:
                    conn.close()
            finally:
                dbmod.DB_PATH = old_path
        except Exception as e:
            logger.error(f"Error during crawldetails: {e}.")

    def do_fetchthumbs(self, arg):
        """
        Fetch missing thumbnails from stored or refreshed URLs.
        Syntax: fetchthumbs [--db data/corpus.db] [--refresh true|false] [--img-timeout 12] [--api-timeout 20]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("fetchthumbs"))
        db_path = opts.get("db", DEFAULT_DB)
        refresh = _bool_from_flag(opts.get("refresh"), True)
        img_timeout = int(opts.get("img_timeout", 12))
        api_timeout = int(opts.get("api_timeout", 20))
        try:
            from nami_code.crawl.fetch_thumbnails import run

            run(db_path, refresh_url=refresh, img_timeout=img_timeout, api_timeout=api_timeout)
        except Exception as e:
            logger.error(f"Error during fetchthumbs: {e}.")

    def do_fetchmedia(self, arg):
        """
        Fetch missing reel videos (MP4) from stored or refreshed URLs.

        Best-effort recovery for reels without a local data/reels/{pk}.mp4; the
        primary capture happens inline during crawldetails (URLs expire fast).
        Syntax: fetchmedia [--db data/corpus.db] [--refresh true|false]
                           [--vid-timeout 60] [--api-timeout 20]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("fetchmedia"))
        db_path = opts.get("db", DEFAULT_DB)
        refresh = _bool_from_flag(opts.get("refresh"), True)
        vid_timeout = int(opts.get("vid_timeout", 60))
        api_timeout = int(opts.get("api_timeout", 20))
        try:
            from nami_code.crawl.fetch_media import run

            run(db_path, refresh_url=refresh, vid_timeout=vid_timeout, api_timeout=api_timeout)
        except Exception as e:
            logger.error(f"Error during fetchmedia: {e}.")

    def do_crawl(self, arg):
        """
        Run setupdb, crawlindex, crawldetails, and report.

        Syntax:
          crawl
          crawl --refresh
          crawl --refresh --pages N

        Any arguments are passed to crawlindex. The normal weekly update is
        `crawl --refresh`, which creates a real refresh crawl_run for churn,
        reads all available pages for each asset, and then downloads newly
        indexed Reel IDs. In refresh mode this command does not create a
        separate cumulative snapshot. Non-refresh crawl still creates the
        legacy/manual corpus snapshot before the report.
        """
        self.do_setupdb("")
        self.do_crawlindex(arg or "")
        self.do_crawldetails("")
        if "--refresh" not in shlex.split(arg or ""):
            self.do_snapshot("")
        self.do_report("")

    def do_refresh(self, arg):
        """
        One-shot end-to-end update: crawl new reels, process everything, build all reports.

        Syntax:
          refresh                  # crawl --refresh + full processing + all reports
          refresh --pages N        # extra args (after the skip flags) pass through to crawlindex
          refresh --no-crawl       # skip the crawl; just (re)process what's already on disk
          refresh --no-vision      # skip vision tagging (no paid Gemini calls)
          refresh --no-av          # skip the acoustic / edit sidecar (av all)

        Runs, in this order:

          setupdb -> crawlindex --refresh -> crawldetails -> fetchmedia -> fetchthumbs
          -> tagvision -> checkspam -> av all -> report -> spamreport -> vizall
        """
        tokens = shlex.split(arg or "")
        no_crawl = _pop_flag(tokens, "--no-crawl")
        no_vision = _pop_flag(tokens, "--no-vision")
        no_av = _pop_flag(tokens, "--no-av")
        crawl_args = " ".join(tokens)
        if "--refresh" not in tokens:
            crawl_args = ("--refresh " + crawl_args).strip()

        stages = [
            ("setupdb",      lambda: self.do_setupdb(""),            False),
            ("crawlindex",   lambda: self.do_crawlindex(crawl_args), no_crawl),
            ("crawldetails", lambda: self.do_crawldetails(""),       no_crawl),
            ("fetchmedia",   lambda: self.do_fetchmedia(""),         no_crawl),
            ("fetchthumbs",  lambda: self.do_fetchthumbs(""),        no_crawl),
            ("tagvision",    lambda: self.do_tagvision(""),          no_vision),
            ("checkspam",    lambda: self.do_checkspam(""),          False),
            ("av all",       lambda: self.do_av("all"),              no_av),
            ("report",       lambda: self.do_report(""),             False),
            ("spamreport",   lambda: self.do_spamreport("--silent"), False),
            ("vizall",       lambda: self.do_vizall("--silent"),     False),
        ]

        print("\n=== refresh: full end-to-end update ===")
        print("plan: " + " -> ".join(lbl for lbl, _, skip in stages if not skip) + "\n")
        results, t_all = [], time.time()
        for label, action, skip in stages:
            if skip:
                print(f"--- refresh: SKIP {label}")
                results.append((label, "skipped", 0.0))
                continue
            print(f"\n===== refresh: {label} =====", flush=True)
            t = time.time()
            try:
                action()
                status = "ok"
            except Exception as e:  # noqa: BLE001
                logger.error(f"refresh: stage '{label}' raised: {e}.")
                status = "FAILED"
            dt = time.time() - t
            results.append((label, status, dt))
            print(f"----- {label}: {status} ({dt:.0f}s)")

        print(f"\n=== refresh complete in {time.time() - t_all:.0f}s ===")
        for label, status, dt in results:
            print(f"  {label:14}{status:9}{dt:.0f}s")
        print("\nDraft reports: outputs/report_out/{report,spam_report,visual_report}.html "
              "and outputs/av/*.html")                          ### THIS IS STILL HARD-CODED
        print("Stages log their own errors above; re-run `refresh` (resumable) to finish any "
              "that FAILED. Curation (validatetags, keep/markspam/exclude) is still manual.\n")
