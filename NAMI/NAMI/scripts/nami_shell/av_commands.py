from __future__ import annotations

import shlex

_DB_SUBCOMMANDS = {
    "init-db", "status", "extract-acoustic", "variants", "align",
    "detect-edits", "group-edits", "report", "assetreport", "validate", "all",
}


class NAMIAcousticCommands:
    """Shell access to the acoustic / audio-visual functions (``nami_av``).

    Forwards the AV's own CLI so the whole pipeline is reachable from the NAMI shell.
    """

    def do_av(self, arg):
        """Run the acoustic / audio-visual functions.

        Usage: av <subcommand> [options]
          av all               run the whole pipeline end-to-end (overnight; resumable)
          av status            show AV state tallies
          av extract-acoustic  level-A acoustic features per asset
          av variants          variant transformation & impact
          av align             per-reel segment alignment + heat strips
          av detect-edits      cut detection (+ cross-reel alignment)
          av group-edits       group an asset's reels into near-identical edit clusters
          av report            write acoustic annotations + build the report
          av assetreport       per-asset metadata report (title/artist/Spotify × acoustics)
          av validate          export the hand-check sample (+ --set-overlay-threshold X)
          av --help            full AV help

        Runs against this shell's database (--db) by default; pass --db to override.
        """
        argv = shlex.split(arg) if arg.strip() else ["--help"]
        try:
            from nami_av.cli import main as av_main
        except Exception as exc:  # noqa: BLE001
            print(f"nami_av unavailable: {exc}\n"
                  f"Install it with: pip install -e '.[av]'")
            return
        if argv and argv[0] in _DB_SUBCOMMANDS and "--db" not in argv:
            argv = [argv[0], "--db", self.db_path, *argv[1:]]
        try:
            av_main(argv)
        except SystemExit:
            pass
        except Exception as exc:  # noqa: BLE001
            print(f"Error: {exc}")
