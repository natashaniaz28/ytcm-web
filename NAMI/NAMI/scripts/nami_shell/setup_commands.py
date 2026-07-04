from __future__ import annotations

from .common import *


class NAMISetupCommands:
    def do_setupdb(self, arg):
        """
        Create/update database schema and sync songs.yaml into the DB.
        Syntax: setupdb [--db data/corpus.db]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("setupdb"))
        db_path = opts.get("db", DEFAULT_DB)
        try:
            from nami_code import db as dbmod
            import yaml

            old_path = dbmod.DB_PATH
            dbmod.DB_PATH = db_path
            try:
                conn = dbmod.get_conn()
                cfg = yaml.safe_load(Path(DEFAULT_SONGS).read_text(encoding="utf-8"))
                dbmod.sync_songs_from_yaml(conn, cfg)
                conn.close()
            finally:
                dbmod.DB_PATH = old_path
            print(f"Database initialized and songs synced: {db_path}")
        except Exception as e:
            logger.error(f"Error during setupdb: {e}.")

    def do_annotations(self, arg):
        """
        Add the annotations and vision_state tables used by vision tagging.
        Syntax: annotations [--db data/corpus.db]
        """
        _pos, opts = _parse_kv_args(arg, allowed=command_flags("annotations"))
        db_path = opts.get("db", DEFAULT_DB)
        try:
            from nami_code.vision.db_annotations import upgrade
            upgrade(db_path)
        except Exception as e:
            logger.error(f"Error during annotations setup: {e}.")

    def do_addsongs(self, _):
        """
        Search Instagram music and add selected variants to config/songs.yaml.
        Syntax: addsongs
        """
        try:
            from nami_code.crawl.add_songs_to_yaml import search_and_add
            search_and_add()
        except Exception as e:
            logger.error(f"Error during addsongs: {e}.")

