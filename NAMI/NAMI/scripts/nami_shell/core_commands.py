from __future__ import annotations

from .common import *


class NAMICoreCommands:
    def do_info(self, _):
        """
        Show unneccessary info about NAMI.
        Syntax: info
        """
        print("\n🌊 — NAMI — 波 — なみ: Network Analysis of Music on Instagram")
        print("Riding the wave, absolutely surreel :)\n")

        print("NAMI is a toolkit for collecting, enriching, exploring, and reporting")
        print("     Instagram Reels connected to music assets. It builds on HikerAPI.\n")

    def do_howto(self, _):
        """
        Show recommended workflows.
        Syntax: howto
        """
        print("This section is under construction.\n")

    def do_status(self, arg):
        """
        Show repository, database, and output status.
        Syntax: status [--db data/corpus.db]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("status"))
        db_path = opts.get("db", getattr(self, "db_path", DEFAULT_DB))
        repo_root = getattr(self, "repo_root", Path.cwd())
        print(f"Repository root: {repo_root}")
        print(f"Database       : {db_path} ({'exists' if Path(db_path).exists() else 'missing'})")
        print(f"Songs config   : {DEFAULT_SONGS} ({'exists' if Path(DEFAULT_SONGS).exists() else 'missing'})")
        print(f"Schema config  : {DEFAULT_SCHEMA} ({'exists' if Path(DEFAULT_SCHEMA).exists() else 'missing'})")
        print(f"Report output  : {DEFAULT_REPORT_OUT} ({'exists' if Path(DEFAULT_REPORT_OUT).exists() else 'missing'})")

        if not Path(db_path).exists():
            return

        try:
            conn = sqlite3.connect(db_path)
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            print(f"Tables ({len(tables)}):")
            if tables:
                for name in tables:
                    print(f"  - {name}")
            else:
                print("  (none)")
            for table in ["songs", "track_variants", "reel_index", "reels", "reel_hashtags", "annotations", "vision_state", "crawl_runs"]:
                if _table_exists(conn, table):
                    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    print(f"  {table:14s}: {n}")
            if _table_exists(conn, "reel_index"):
                todo = conn.execute("SELECT COUNT(*) FROM reel_index WHERE details_done=0").fetchone()[0]
                print(f"Pending details : {todo}")
            conn.close()
        except Exception as e:
            logger.error(f"Error reading status: {e}.")

    def do_paths(self, _):
        """
        Show important NAMI paths.
        Syntax: paths
        """
        for label, path in [
            ("DB", DEFAULT_DB),
            ("songs", DEFAULT_SONGS),
            ("schema", DEFAULT_SCHEMA),
            ("reels", "data/reels"),
            ("thumbnails", "data/thumbnails"),
            ("report", "outputs/report_out/report.html"),
            ("tables", "outputs/report_out/tables"),
            ("charts", "outputs/report_out/charts"),
        ]:
            p = Path(path)
            print(f"{label:11s}: {path} ({'exists' if p.exists() else 'missing'})")

    def do_open(self, arg):
        """
        Open a generated output in the browser.
        Syntax: open [report|spam|charts|sample|curated|visual|vision|path]
        All bundled reports live in outputs/report_out/.
        """
        key = (arg or "report").strip()
        targets = {
            "report": "outputs/report_out/report.html",
            "spam": "outputs/report_out/spam_report.html",
            "charts": "outputs/report_out/visual_report.html",
            "sample": "outputs/report_out/close_reading_sample.html",
            "curated": "outputs/report_out/close_reading_curated.html",
            "vision": "outputs/report_out/report.html",
            "visual": "outputs/report_out/validation_visual.html",
        }
        path = Path(targets.get(key, key)).resolve()
        if not path.exists():
            print(f"Missing file: {path}")
            return
        webbrowser.open(path.as_uri())
        print(f"Opened: {path}")

    def do_shell(self, arg):
        """
        Run an OS command from inside the shell.
        Syntax: shell COMMAND
        """
        if not arg.strip():
            print("Syntax: shell COMMAND")
            return
        subprocess.run(arg, shell=True, check=False)

    def do_exit(self, _):
        """
        Quit the program.
        Syntax: exit, quit, q
        """
        print("Goodbye!")
        return True

