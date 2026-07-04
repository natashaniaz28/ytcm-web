
from __future__ import annotations

from .common import *

DEFAULT_VISION_MODEL = "gemini-2.5-flash"


class NAMIVisionCommands:
    def do_tagvision(self, arg):
        """
        Tag reel media with vision labels (MP4 via VLM, thumbnail fallback).
        Syntax: tagvision [--db data/corpus.db] [--stub true|false] [--limit N]
                          [--reset true|false] [--model MODEL]
                          [--resolution default|low] [--fps N] [--workers N]
                          [--min-interval SECONDS]
        Defaults to --model gemini-2.5-flash; pass --model to override.
        --workers sets how many reels are tagged in parallel (default 8 for the
        cloud Gemini backend, 1 for local GPU models). Override explicitly if needed.
        --min-interval spaces request starts apart to avoid burst 429s (default 0.2s
        for Gemini, 0 otherwise); raise it (e.g. 0.3) if you still see burst 429s.
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("tagvision"))
        db_path = opts.get("db", DEFAULT_DB)
        stub = _bool_from_flag(opts.get("stub"), False)
        limit = int(opts["limit"]) if opts.get("limit") else None
        reset = _bool_from_flag(opts.get("reset"), False)
        model = opts.get("model") or DEFAULT_VISION_MODEL
        resolution = opts.get("resolution")
        if resolution is not None and resolution.lower() not in {"default", "low"}:
            raise ValueError(
                f"--resolution must be one of: default, low (got {resolution!r}).")
        fps = int(opts["fps"]) if opts.get("fps") else None
        is_gemini = "gemini" in model.lower()
        default_workers = 8 if is_gemini else 1
        workers = int(opts["workers"]) if opts.get("workers") else default_workers
        default_interval = 0.2 if is_gemini else 0.0
        min_interval = float(opts["min_interval"]) if opts.get("min_interval") else default_interval
        try:
            from nami_code.vision.db_annotations import upgrade
            from nami_code.vision import tag_vision as tv
            upgrade(db_path)
            tv.MODEL_NAME = model
            if reset:
                conn = sqlite3.connect(db_path)
                conn.execute("DELETE FROM annotations WHERE source='vision'")
                conn.execute("UPDATE vision_state SET status='pending'")
                conn.commit(); conn.close()
                print("RESET: old vision tags deleted, all reels set to pending.\n")
            tv.run(db_path, stub=stub, limit=limit, resolution=resolution, fps=fps,
                   workers=1 if stub else workers,
                   min_interval=0.0 if stub else min_interval)
        except Exception as e:
            logger.error(f"Error during tagvision: {e}.")

    def do_visionstatus(self, arg):
        """
        Show how many reels are vision-tagged vs. still open, at a glance.
        Syntax: visionstatus [--db data/corpus.db]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("visionstatus"))
        db_path = opts.get("db", DEFAULT_DB)
        try:
            conn = sqlite3.connect(db_path)
            total = conn.execute("SELECT COUNT(*) FROM reels").fetchone()[0]
            counts = dict(conn.execute(
                "SELECT status, COUNT(*) FROM vision_state GROUP BY status").fetchall())
            has_row = conn.execute("SELECT COUNT(*) FROM vision_state").fetchone()[0]
            models = [r[0] for r in conn.execute(
                "SELECT DISTINCT model FROM annotations "
                "WHERE source='vision' AND model IS NOT NULL ORDER BY model")]
            conn.close()
        except Exception as e:
            logger.error(f"Error during visionstatus: {e}.")
            return

        done = counts.get("done", 0)
        pending = counts.get("pending", 0)
        no_media = counts.get("no_media", 0)
        failed = counts.get("failed", 0)
        blocked = counts.get("blocked", 0)
        no_record = total - has_row
        still_open = total - done

        def pct(n):
            return f"{(100.0 * n / total):.1f}%" if total else "n/a"

        print(f"\nVision tagging status ({db_path})")
        print(f"  reels total          : {total}")
        print(f"  done (tagged)        : {done}  ({pct(done)})")
        print(f"  still open           : {still_open}  ({pct(still_open)})")
        print(f"    pending            : {pending}")
        print(f"    no_media           : {no_media}")
        print(f"    blocked (terminal) : {blocked}")
        print(f"    failed             : {failed}")
        print(f"    no record yet      : {no_record}")
        print(f"  models in annotations: {', '.join(models) if models else '(none)'}\n")

    def do_visionblocked(self, arg):
        """
        List reels whose vision tagging hit a terminal content-policy block.
        Syntax: visionblocked [--db data/corpus.db] [--limit N] [--csv PATH]

        'blocked' is the terminal state for reels Gemini's safety / prohibited-
        content filter refused (see tagvision); they are never retried. For each
        blocked reel this prints its id, shortcode/URL, song & variant, creator,
        any keyword tags (vision tags don't exist for blocked reels) and a caption
        snippet — enough to eyeball what tripped the filter. --csv writes the full
        rows to a file instead of truncating.
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("visionblocked"))
        db_path = opts.get("db", DEFAULT_DB)
        limit = int(opts["limit"]) if opts.get("limit") else None
        csv_path = opts.get("csv")
        try:
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                """SELECT v.reel_pk, r.code, r.song_id, r.variant_label,
                          r.creator_pseudo, r.caption_text, v.updated_at
                   FROM vision_state v
                   JOIN reels r ON r.reel_pk = v.reel_pk
                   WHERE v.status='blocked'
                   ORDER BY v.updated_at DESC""").fetchall()
            kw = dict(conn.execute(
                """SELECT reel_pk, group_concat(dimension||':'||category, ', ')
                   FROM annotations WHERE source!='vision' GROUP BY reel_pk"""))
            conn.close()
        except Exception as e:
            logger.error(f"Error during visionblocked: {e}.")
            return

        if not rows:
            print("\nNo blocked reels — nothing has tripped a content-policy block.\n")
            return

        total = len(rows)
        shown = rows[:limit] if limit else rows
        print(f"\nBlocked reels (terminal content-policy blocks): {total}\n")
        for pk, code, song_id, variant, creator, caption, updated in shown:
            url = f"https://www.instagram.com/reel/{code}/" if code else "(no shortcode)"
            cap = " ".join((caption or "").split())
            if len(cap) > 80:
                cap = cap[:77] + "..."
            print(f"  {pk}  [{song_id or '?'}/{variant or '?'}]  @{creator or '?'}  blocked {updated}")
            print(f"      {url}")
            print(f"      tags   : {kw.get(pk) or '(no keyword tags)'}")
            print(f"      caption: {cap or '(none)'}")
        if limit and total > limit:
            print(f"\n  ... {total - limit} more (raise --limit, or use --csv to export all).")
        if csv_path:
            import csv as _csv
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = _csv.writer(f)
                w.writerow(["reel_pk", "code", "song_id", "variant_label",
                            "creator_pseudo", "keyword_tags", "updated_at", "caption_text"])
                for pk, code, song_id, variant, creator, caption, updated in rows:
                    w.writerow([pk, code, song_id, variant, creator,
                                kw.get(pk, ""), updated, " ".join((caption or "").split())])
            print(f"\n  Wrote {total} rows to {csv_path}")
        print()

    def do_validatevisual(self, _):
        """
        Build the visual HTML gallery for checking vision tags.
        Syntax: validatevisual
        """
        try:
            from nami_code.vision.validate_visual import build
            build()
        except Exception as e:
            logger.error(f"Error during validatevisual: {e}.")

    def do_validatetags(self, arg):
        """
        Create or score the CSV sample for vision-tag validation.
        Syntax: validatetags [sample|score]
        """
        mode = (arg or "sample").strip().lower()
        try:
            from nami_code.diagnostics.validate_tags import sample, score, DB_PATH, CSV_PATH
            if mode == "score":
                score(CSV_PATH)
            else:
                sample(DB_PATH)
        except Exception as e:
            logger.error(f"Error during validatetags: {e}.")

    def do_visionreport(self, _):
        """
        Run the current schema-driven report.
        Syntax: visionreport
        """
        try:
            from nami_code.reports.report import ReportConfig, build
            build(ReportConfig())
        except Exception as e:
            logger.error(f"Error during visionreport: {e}.")

