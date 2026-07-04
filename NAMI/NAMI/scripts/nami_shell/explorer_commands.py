from __future__ import annotations

from .common import *
from .state import NAMIExplorerState


class NAMIExplorerCommands:
    """
    Interactive explorer commands over already collected NAMI Reel data.
    """

    def _explorer(self) -> NAMIExplorerState:
        """
        Return the explorer's in-memory state, creating it the first time.
        """
        if not hasattr(self, "explorer") or getattr(self, "explorer") is None:
            self.explorer = NAMIExplorerState()
        return self.explorer

    def _load_reels_from_db(self, db_path: str) -> list[dict[str, Any]]:
        """
        Load all reels from the database into plain records, attaching hashtags, any saved tags, and an Instagram link.
        """
        if not Path(db_path).exists():
            raise FileNotFoundError(f"Database {db_path} not found.")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            if not _table_exists(conn, "reels"):
                raise RuntimeError("Table 'reels' does not exist. Run setupdb/crawling first or choose another DB.")
            rows = conn.execute(
                """
                SELECT
                    r.*,
                    COALESCE(s.title, r.song_id) AS song_title,
                    COALESCE(s.artist, '') AS song_artist
                FROM reels r
                LEFT JOIN songs s ON s.song_id = r.song_id
                ORDER BY COALESCE(r.taken_at, ''), r.reel_pk
                """
            ).fetchall()
            records = [dict(row) for row in rows]

            hashtags: dict[str, list[str]] = {str(r.get("reel_pk")): [] for r in records}
            if _table_exists(conn, "reel_hashtags"):
                for row in conn.execute("SELECT reel_pk, hashtag FROM reel_hashtags ORDER BY hashtag"):
                    hashtags.setdefault(str(row["reel_pk"]), []).append(row["hashtag"])

            vision_labels: dict[str, list[str]] = {}
            vision_dimensions: dict[str, list[str]] = {}
            if _table_exists(conn, "annotations"):
                cols = {r[1] for r in conn.execute("PRAGMA table_info(annotations)")}
                if {"reel_pk", "category"}.issubset(cols):
                    for row in conn.execute("SELECT reel_pk, dimension, category FROM annotations ORDER BY dimension, category"):
                        pk = str(row["reel_pk"])
                        cat = row["category"]
                        dim = row["dimension"] if "dimension" in row.keys() else None
                        if cat:
                            vision_labels.setdefault(pk, []).append(cat)
                        if dim:
                            vision_dimensions.setdefault(pk, []).append(dim)

            for record in records:
                pk = str(record.get("reel_pk"))
                record["hashtags"] = hashtags.get(pk, [])
                record["vision_labels"] = sorted(set(vision_labels.get(pk, [])))
                record["vision_dimensions"] = sorted(set(vision_dimensions.get(pk, [])))
                if record.get("code"):
                    record["url"] = f"https://www.instagram.com/reel/{record['code']}/"
            return records
        finally:
            conn.close()

    def _load_records_from_file(self, path: Path) -> list[dict[str, Any]]:
        """
        Load records from a JSON or CSV file the user exported earlier.
        """
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        suffix = path.suffix.lower()
        if suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and "items" in payload:
                payload = payload["items"]
            if not isinstance(payload, list):
                raise ValueError("JSON input must be a list of records or an object with an 'items' list.")
            return [dict(item) for item in payload]
        if suffix == ".csv":
            with path.open("r", encoding="utf-8", newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        raise ValueError("Supported file formats: .json, .csv")

    def _require_loaded(self) -> NAMIExplorerState | None:
        """
        Return the loaded explorer data, or print a hint and return nothing if none is loaded.
        """
        state = self._explorer()
        if not state.data:
            print("No Explorer data loaded. Use: load [reels|PATH] [--db data/corpus.db]")
            return None
        return state

    def _print_record_brief(self, record: dict[str, Any], index: int | None = None) -> None:
        """
        Print a one- or two-line summary of a single reel.
        """
        prefix = f"[{index}] " if index is not None else ""
        song = record.get("song_title") or record.get("song_id") or "?"
        code = record.get("code") or record.get("reel_pk") or "?"
        creator = record.get("creator_pseudo") or "?"
        likes = record.get("like_count")
        plays = record.get("play_count") or record.get("view_count")
        caption = _stringify(record.get("caption_text"))[:120].replace("\n", " ")
        print(f"{prefix}{code} | {song} | creator={creator} | likes={likes} | plays={plays}")
        if caption:
            print(f"    {caption}{'…' if len(_stringify(record.get('caption_text'))) > 120 else ''}")

    def _views_path(self) -> Path:
        """
        Return the file path where saved views are stored.
        """
        return Path("outputs/explorer/views.json")

    def _backup_existing_json(self, path: Path) -> Path | None:
        """
        Create a timestamped backup before overwriting Explorer JSON state.
        """
        if not path.exists():
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.stem}.{timestamp}.backup{path.suffix}")
        shutil.copy2(path, backup)
        return backup

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        """
        Write JSON to a file safely, by writing a temporary file first and then swapping it in.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _load_views(self) -> dict[str, Any]:
        """
        Load the saved views from disk, tolerating a missing or broken file.
        """
        path = self._views_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"View storage is not valid JSON: {path} ({e}). Treating it as empty.")
            return {}
        except OSError as e:
            print(f"Could not read view storage: {e}")
            return {}
        if payload in (None, ""):
            return {}
        if not isinstance(payload, dict):
            print(f"View storage has unexpected format: {path}. Treating it as empty.")
            return {}
        return payload

    def _save_views(self, views: dict[str, Any]) -> None:
        """
        Save the views to disk, backing up the previous file first.
        """
        path = self._views_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._last_views_backup = self._backup_existing_json(path)
        self._write_json_atomic(path, views)

    def _validate_view_name(self, name: str) -> bool:
        """
        Return whether a view name uses only safe characters.
        """
        return bool(re.fullmatch(r"[A-Za-z0-9_-]+", name or ""))

    def _record_identifier(self, record: dict[str, Any]) -> str | None:
        """
        Return a stable id for a record (its reel id, code, or shortcode).
        """
        for key in ("reel_pk", "code", "shortcode"):
            value = record.get(key)
            if value not in (None, ""):
                return _stringify(value)
        return None

    def _views_for_record(self, record: dict[str, Any]) -> list[str]:
        """
        Return the names of saved views that contain a given record.
        """
        candidates = {
            _stringify(record.get(key))
            for key in ("reel_pk", "code", "shortcode")
            if record.get(key) not in (None, "")
        }
        if not candidates:
            return []
        found: list[str] = []
        for name, view in self._load_views().items():
            if not isinstance(view, dict):
                continue
            ids = view.get("ids") or []
            if isinstance(ids, list) and any(_stringify(item) in candidates for item in ids):
                found.append(_stringify(name))
        return sorted(found, key=str.casefold)

    def _restore_records_by_ids(self, ids: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Match a list of saved ids back to loaded records, returning the ones found and the ones missing.
        """
        state = self._explorer()
        indexes: dict[str, dict[str, dict[str, Any]]] = {"reel_pk": {}, "code": {}, "shortcode": {}}
        for record in state.data:
            for key in indexes:
                value = record.get(key)
                if value not in (None, ""):
                    indexes[key].setdefault(_stringify(value), record)
        restored: list[dict[str, Any]] = []
        missing: list[str] = []
        seen: set[int] = set()
        for raw_id in ids:
            ident = _stringify(raw_id)
            record = None
            for key in ("reel_pk", "code", "shortcode"):
                record = indexes[key].get(ident)
                if record is not None:
                    break
            if record is None:
                missing.append(ident)
                continue
            marker = id(record)
            if marker not in seen:
                restored.append(record)
                seen.add(marker)
        return restored, missing

    def _annotations_path(self) -> Path:
        """
        Return the file path where manual annotations are stored.
        """
        return Path("outputs/explorer/manual_annotations.json")

    def _empty_manual_annotations(self) -> dict[str, Any]:
        """
        Return a fresh, empty manual-annotations structure.
        """
        return {"version": 1, "updated_at": None, "records": {}}

    def _manual_annotations(self) -> dict[str, Any]:
        """
        Return the in-memory manual annotations, creating and repairing the structure as needed.
        """
        if not hasattr(self, "manual_annotations") or getattr(self, "manual_annotations") is None:
            self.manual_annotations = self._empty_manual_annotations()
        payload = self.manual_annotations
        if not isinstance(payload, dict):
            payload = self._empty_manual_annotations()
            self.manual_annotations = payload
        records = payload.get("records")
        if not isinstance(records, dict):
            payload["records"] = {}
        payload.setdefault("version", 1)
        payload.setdefault("updated_at", None)
        return payload

    def _load_manual_annotations(self, *, silent_missing: bool = False) -> dict[str, Any] | None:
        """
        Load manual annotations from disk, tolerating a missing or broken file.
        """
        path = self._annotations_path()
        if not path.exists():
            if not silent_missing:
                print(f"No manual annotation file found: {path}")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"Manual annotation file is not valid JSON: {path} ({e}).")
            return None
        except OSError as e:
            print(f"Could not read manual annotation file: {e}")
            return None
        if not isinstance(payload, dict):
            print(f"Manual annotation file has unexpected format: {path}")
            return None
        records = payload.get("records")
        if not isinstance(records, dict):
            print(f"Manual annotation file has no valid 'records' object: {path}")
            return None
        payload.setdefault("version", 1)
        payload.setdefault("updated_at", None)
        self.manual_annotations = payload
        return payload

    def _save_manual_annotations(self) -> None:
        """
        Drop empty entries, stamp the time, back up the old file, and save the manual annotations.
        """
        payload = self._manual_annotations()
        self._prune_manual_annotations()
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = self._annotations_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._last_annotations_backup = self._backup_existing_json(path)
        self._write_json_atomic(path, payload)

    def _manual_record_id(self, record: dict[str, Any]) -> str | None:
        """
        Return a stable id to key a record's manual annotations by.
        """
        for key in ("reel_pk", "code", "shortcode", "pk", "id"):
            value = record.get(key)
            if value not in (None, ""):
                return _stringify(value)
        return None

    def _normalize_tag(self, tag: str) -> str | None:
        """
        Tidy a tag into a safe lowercase form, or return nothing if it is invalid.
        """
        normalized = re.sub(r"\s+", "_", (tag or "").strip().casefold())
        if not normalized:
            return None
        if not re.fullmatch(r"[a-z0-9_:\-]+", normalized):
            return None
        return normalized

    def _record_label(self, record: dict[str, Any]) -> str:
        """
        Return a short human-friendly label for a record.
        """
        return _stringify(record.get("code") or record.get("shortcode") or record.get("reel_pk") or self._manual_record_id(record) or "record")

    def _ensure_manual_entry(self, record: dict[str, Any]) -> tuple[str, dict[str, Any]] | tuple[None, None]:
        """
        Find or create the manual-annotation entry for a record, with its tags, notes and flags set up.
        """
        record_id = self._manual_record_id(record)
        if record_id is None:
            return None, None
        annotations = self._manual_annotations()
        records = annotations["records"]
        entry = records.setdefault(record_id, {})
        entry.setdefault("reel_pk", _stringify(record.get("reel_pk") or ""))
        entry.setdefault("code", _stringify(record.get("code") or record.get("shortcode") or ""))
        entry.setdefault("tags", [])
        entry.setdefault("notes", [])
        flags = entry.get("flags")
        if not isinstance(flags, dict):
            flags = {}
        entry["flags"] = {
            "keep": bool(flags.get("keep", False)),
            "spam": bool(flags.get("spam", False)),
            "exclude": bool(flags.get("exclude", False)),
            "reviewed": bool(flags.get("reviewed", False)),
        }
        return record_id, entry

    def _manual_entry_for_record(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """
        Return the existing manual-annotation entry for a record, or nothing.
        """
        record_id = self._manual_record_id(record)
        if record_id is None:
            return None
        entry = self._manual_annotations().get("records", {}).get(record_id)
        return entry if isinstance(entry, dict) else None

    def _manual_entry_is_active(self, entry: dict[str, Any]) -> bool:
        """
        Return whether a manual entry actually holds any tags, notes or set flags.
        """
        if not isinstance(entry, dict):
            return False
        tags = entry.get("tags") or []
        notes = entry.get("notes") or []
        flags = entry.get("flags") or {}
        return (
            (isinstance(tags, list) and bool(tags))
            or (isinstance(notes, list) and bool(notes))
            or (isinstance(flags, dict) and any(bool(value) for value in flags.values()))
        )

    def _prune_manual_entry_if_empty(self, record_id: str) -> None:
        """
        Remove a record's manual entry if it has nothing left in it.
        """
        records = self._manual_annotations().get("records", {})
        entry = records.get(record_id)
        if isinstance(entry, dict) and not self._manual_entry_is_active(entry):
            records.pop(record_id, None)

    def _prune_manual_annotations(self) -> None:
        """
        Remove every manual entry that has nothing left in it.
        """
        records = self._manual_annotations().get("records", {})
        empty_ids = [
            record_id
            for record_id, entry in records.items()
            if isinstance(entry, dict) and not self._manual_entry_is_active(entry)
        ]
        for record_id in empty_ids:
            records.pop(record_id, None)

    def _resolve_record_target(self, target: str) -> dict[str, Any] | None:
        """
        Find the record the user means, whether they gave a list number or an id/code.
        """
        state = self._require_loaded()
        if state is None:
            return None
        key = (target or "").strip()
        if not key:
            return None
        active = state.active()
        if key.isdigit():
            idx = int(key) - 1
            if 0 <= idx < len(active):
                return active[idx]
        key_cf = key.casefold()
        for pool in (active, state.data if active is not state.data else []):
            for item in pool:
                candidates = [
                    item.get("reel_pk"),
                    item.get("code"),
                    item.get("shortcode"),
                    item.get("pk"),
                    item.get("id"),
                ]
                if any(_stringify(candidate).casefold() == key_cf for candidate in candidates if candidate is not None):
                    return item
        return None

    def _manual_annotation_counts(self) -> tuple[int, int, int]:
        """
        Count how many records have manual annotations, and the total tags and notes.
        """
        records = self._manual_annotations().get("records", {})
        record_count = 0
        tag_count = 0
        note_count = 0
        for entry in records.values():
            if not isinstance(entry, dict):
                continue
            tags = entry.get("tags") or []
            notes = entry.get("notes") or []
            if isinstance(tags, list):
                tag_count += len(tags)
            if isinstance(notes, list):
                note_count += len(notes)
            if self._manual_entry_is_active(entry):
                record_count += 1
        return record_count, tag_count, note_count

    def _manual_review_counts(self) -> dict[str, int]:
        """
        Count how many records carry each review flag (reviewed, keep, spam, exclude).
        """
        records = self._manual_annotations().get("records", {})
        counts = {"reviewed": 0, "keep": 0, "spam": 0, "exclude": 0}
        for entry in records.values():
            if not isinstance(entry, dict):
                continue
            flags = entry.get("flags") or {}
            if not isinstance(flags, dict):
                continue
            for key in counts:
                if bool(flags.get(key, False)):
                    counts[key] += 1
        return counts

    def _set_manual_flag(self, target: str, flag: str, value: bool, *, reviewed_decision: bool = False) -> None:
        """
        Set or clear a review flag on a record, warning about contradictory flags.
        """
        if self._require_loaded() is None:
            return
        target = (target or "").strip()
        if not target:
            print(f"Syntax: {flag if value else 'un' + flag} TARGET")
            return
        record = self._resolve_record_target(target)
        if record is None:
            print(f"No Explorer record found for {target}.")
            return
        record_id, entry = self._ensure_manual_entry(record)
        if record_id is None or entry is None:
            print("Could not create a stable manual annotation ID for this record.")
            return
        flags = entry.setdefault("flags", {})
        if not isinstance(flags, dict):
            flags = {}
            entry["flags"] = flags
        flags[flag] = bool(value)
        if reviewed_decision and value:
            flags["reviewed"] = True
        if not value:
            self._prune_manual_entry_if_empty(record_id)
        label = self._record_label(record)
        state_word = "set" if value else "cleared"
        print(f"Manual flag {flag}={bool(value)} {state_word} for {label}")
        if value:
            warnings = []
            if flag == "keep":
                if bool(flags.get("spam", False)):
                    warnings.append("spam")
                if bool(flags.get("exclude", False)):
                    warnings.append("exclude")
            elif flag in {"spam", "exclude"} and bool(flags.get("keep", False)):
                warnings.append("keep")
            if warnings:
                print(f"Warning: record is also marked {', '.join(warnings)}.")

    def _format_review_flags(self, record: dict[str, Any]) -> str:
        """
        Return a record's active review flags as a short comma-separated string.
        """
        entry = self._manual_entry_for_record(record) or {}
        flags = entry.get("flags") if isinstance(entry, dict) else {}
        if not isinstance(flags, dict):
            flags = {}
        active = [key for key in ("keep", "spam", "exclude", "reviewed") if bool(flags.get(key, False))]
        return ",".join(active) if active else "-"

    def _format_review_tags(self, record: dict[str, Any]) -> str:
        """
        Return a record's manual tags as a short comma-separated string.
        """
        entry = self._manual_entry_for_record(record) or {}
        tags = entry.get("tags") if isinstance(entry, dict) else []
        if not isinstance(tags, list) or not tags:
            return "-"
        return ",".join(_stringify(tag) for tag in tags if _stringify(tag)) or "-"

    def _annotation_record_lookup(self) -> dict[str, dict[str, Any]]:
        """
        Build a lookup from every id of every loaded record to the record itself.
        """
        state = self._explorer()
        lookup: dict[str, dict[str, Any]] = {}
        for record in state.data:
            for key in ("reel_pk", "code", "shortcode", "pk", "id"):
                value = record.get(key)
                if value not in (None, ""):
                    lookup.setdefault(_stringify(value), record)
        return lookup

    def _augment_record_with_manual_annotations(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Return a copy of a record with its manual tags, notes and flags merged in.
        """
        out = dict(record)
        entry = self._manual_entry_for_record(record) or {}
        tags = entry.get("tags") if isinstance(entry, dict) else []
        notes = entry.get("notes") if isinstance(entry, dict) else []
        flags = entry.get("flags") if isinstance(entry, dict) else {}
        if not isinstance(tags, list):
            tags = []
        if not isinstance(notes, list):
            notes = []
        if not isinstance(flags, dict):
            flags = {}
        out["manual_tags"] = sorted(_stringify(t) for t in tags if _stringify(t))
        out["manual_notes_count"] = len(notes)
        out["manual_notes"] = [
            f"{_stringify(note.get('created_at') if isinstance(note, dict) else '')}: {_stringify(note.get('text') if isinstance(note, dict) else note)}".strip()
            for note in notes
        ]
        out["manual_keep"] = bool(flags.get("keep", False))
        out["manual_spam"] = bool(flags.get("spam", False))
        out["manual_exclude"] = bool(flags.get("exclude", False))
        out["manual_reviewed"] = bool(flags.get("reviewed", False))
        return out

    def do_load(self, arg):
        """
        Load Reel data into the interactive Explorer.
        Syntax: load [reels|PATH] [--db data/corpus.db]
        Examples: load | load reels --db data/corpus.db | load outputs/view.json
        """
        pos, opts = _parse_kv_args(arg, allowed=command_flags("load"))
        target = pos[0] if pos else "reels"
        state = self._explorer()
        try:
            if target in {"reels", "db", "database"}:
                db_path = opts.get("db", getattr(self, "db_path", DEFAULT_DB))
                records = self._load_reels_from_db(db_path)
                state.source = db_path
            else:
                path = Path(target)
                records = self._load_records_from_file(path)
                state.source = str(path)
            state.data = records
            state.reset_filter()
            self._load_manual_annotations(silent_missing=True)
            print(f"Explorer loaded: {len(records)} records from {state.source}")
        except Exception as e:
            logger.error(f"Error during Explorer load: {e}.")
            print(f"Explorer load failed: {e}")

    def do_xstatus(self, _):
        """
        Show Explorer state without colliding with the repository status command.
        Syntax: xstatus
        """
        state = self._explorer()
        print("Explorer status")
        print(f"  source        : {state.source or '(none)'}")
        print(f"  total records : {state.total_count}")
        print(f"  active records: {state.active_count}")
        print(f"  filter        : {state.last_filter or '(none)'}")
        views = self._load_views()
        print(f"  views         : {len(views)}")
        n_records, n_tags, n_notes = self._manual_annotation_counts()
        review_counts = self._manual_review_counts()
        print(f"  manual annotations: {n_records} records")
        print(f"  manual tags  : {n_tags}")
        print(f"  manual notes : {n_notes}")
        print(f"  reviewed     : {review_counts['reviewed']}")
        print(f"  kept         : {review_counts['keep']}")
        print(f"  manual spam  : {review_counts['spam']}")
        print(f"  excluded     : {review_counts['exclude']}")
        print(f"  annotations file: {self._annotations_path()}")
        if state.data:
            keys = sorted({key for record in state.data[:25] for key in record.keys()})
            print(f"  fields        : {', '.join(keys)}")

    def do_filter(self, arg):
        """
        Text-filter the active Explorer set across captions, hashtags, songs, creators and vision tags.
        Syntax: filter [--and|--or] TERM...
        Examples: filter remix retro | filter --and dance challenge
        """
        state = self._require_loaded()
        if state is None:
            return
        pos, opts = _parse_kv_args(arg, allowed=command_flags("filter"))
        mode = "or" if "or" in opts else "and"
        terms = pos
        if not terms:
            print("Syntax: filter [--and|--or] TERM...")
            return
        base = state.active()
        state.filtered = [record for record in base if _record_search_matches(record, terms, mode=mode)]
        state.last_filter = f"filter --{mode} {' '.join(terms)}"
        state.last_query = {"type": "text", "terms": terms, "mode": mode, "fields": TEXT_SEARCH_FIELDS}
        print(f"Filter matched {state.active_count} of {len(base)} active records ({state.total_count} total).")

    def do_fieldfilter(self, arg):
        """
        Filter the active Explorer set in one specific field.
        Syntax: fieldfilter FIELD TERM... [--and|--or]
        Examples: fieldfilter hashtag dance | fieldfilter caption "official audio" | fieldfilter vision performance
        """
        state = self._require_loaded()
        if state is None:
            return
        pos, opts = _parse_kv_args(arg, allowed=command_flags("fieldfilter"))
        if len(pos) < 2:
            print("Syntax: fieldfilter FIELD TERM... [--and|--or]")
            return
        field_name = _field_name(pos[0])
        terms = pos[1:]
        mode = "or" if "or" in opts else "and"
        base = state.active()
        fields = [field_name]
        state.filtered = [record for record in base if _record_search_matches(record, terms, mode=mode, fields=fields)]
        state.last_filter = f"fieldfilter {field_name} --{mode} {' '.join(terms)}"
        state.last_query = {"type": "field", "terms": terms, "mode": mode, "fields": fields}
        print(f"Fieldfilter matched {state.active_count} of {len(base)} active records ({state.total_count} total).")

    def do_where(self, arg):
        """
        Structured-filter the active Explorer set by field/operator/value.
        Syntax: where FIELD OP VALUE
        Operators: = != > >= < <= contains between
        Examples: where likes > 1000 | where hashtag contains dance | where taken_at between 2024-01-01 2024-12-31
        """
        state = self._require_loaded()
        if state is None:
            return
        tokens = shlex.split(arg or "")
        if len(tokens) < 3:
            print("Syntax: where FIELD OP VALUE")
            return
        field_name = _field_name(tokens[0])
        op = tokens[1].lower()
        base = state.active()
        try:
            if op == "between":
                if len(tokens) < 4:
                    print("Syntax: where FIELD between LOW HIGH")
                    return
                low = tokens[2]
                high = tokens[3]
                matched = [r for r in base if _compare_values(r.get(field_name), ">=", low) and _compare_values(r.get(field_name), "<=", high)]
            else:
                value = " ".join(tokens[2:])
                matched = [r for r in base if _compare_values(r.get(field_name), op, value)]
            state.filtered = matched
            state.last_filter = f"where {field_name} {op} {' '.join(tokens[2:])}"
            state.last_query = {"type": "where", "field": field_name, "operator": op, "value": " ".join(tokens[2:])}
            print(f"Where matched {state.active_count} of {len(base)} active records ({state.total_count} total).")
        except Exception as e:
            print(f"where failed: {e}")

    def do_unfilter(self, _):
        """
        Reset the Explorer to the full loaded set.
        Syntax: unfilter
        """
        state = self._require_loaded()
        if state is None:
            return
        state.reset_filter()
        print(f"Explorer filter reset. Active records: {state.active_count}")

    def do_xsample(self, arg):
        """
        Show a random sample from the active Explorer set.
        Syntax: xsample [N]
        """
        state = self._require_loaded()
        if state is None:
            return
        n = int((arg or "5").strip() or 5)
        active = state.active()
        if not active:
            print("No active records to sample.")
            return
        for i, record in enumerate(random.sample(active, min(n, len(active))), start=1):
            self._print_record_brief(record, i)

    def do_inspect(self, arg):
        """
        Inspect one Explorer record in detail.

        Syntax:
          inspect INDEX
          inspect REEL_PK
          inspect SHORTCODE

        Notes:
          - INDEX is 1-based and refers to the current active Explorer set.
          - REEL_PK and SHORTCODE are searched in the active set first.
        """
        state = self._require_loaded()
        if state is None:
            return

        key = (arg or "").strip()
        if not key:
            print("Syntax: inspect INDEX_OR_ID")
            return

        active = state.active()
        record = None
        origin = "active set"

        if key.isdigit():
            idx = int(key) - 1
            if 0 <= idx < len(active):
                record = active[idx]
                origin = f"active index {idx + 1}"

        if record is None:
            key_cf = key.casefold()
            for item in active:
                candidates = [
                    item.get("reel_pk"),
                    item.get("pk"),
                    item.get("id"),
                    item.get("code"),
                    item.get("shortcode"),
                ]
                if any(_stringify(candidate).casefold() == key_cf for candidate in candidates if candidate is not None):
                    record = item
                    origin = "active set"
                    break

        if record is None and active is not state.data:
            key_cf = key.casefold()
            for item in state.data:
                candidates = [
                    item.get("reel_pk"),
                    item.get("pk"),
                    item.get("id"),
                    item.get("code"),
                    item.get("shortcode"),
                ]
                if any(_stringify(candidate).casefold() == key_cf for candidate in candidates if candidate is not None):
                    record = item
                    origin = "all loaded records"
                    break

        if record is None:
            print(f"No Explorer record found for: {key}")
            return

        def _is_empty(value):
            """
            Return whether a value is empty (none, blank, or an empty list).
            """
            return value is None or value == "" or value == []

        def _short(value, limit=1600):
            """
            Shorten text to a length limit, adding an ellipsis if it was cut.
            """
            text = _stringify(value).strip()
            if len(text) <= limit:
                return text
            return text[: limit - 1] + "…"

        def _as_items(value):
            """
            Turn a value into a list, splitting strings on commas or parsing a JSON list.
            """
            if value is None:
                return []
            if isinstance(value, list):
                return value
            if isinstance(value, tuple):
                return list(value)
            if isinstance(value, set):
                return sorted(value)

            text = str(value).strip()
            if not text:
                return []

            if text.startswith("[") and text.endswith("]"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    pass

            if "," in text:
                return [part.strip() for part in text.split(",") if part.strip()]

            return [text]

        def _list_text(value, limit=80):
            """
            Turn a list-like value into a readable comma-separated string, capped in length.
            """
            items = [_stringify(item).strip() for item in _as_items(value)]
            items = [item for item in items if item]
            if not items:
                return ""
            shown = items[:limit]
            suffix = f" … (+{len(items) - limit} more)" if len(items) > limit else ""
            return ", ".join(shown) + suffix

        def _print_value(label, value, limit=1600):
            """
            Print a labelled value, skipping it if empty.
            """
            if _is_empty(value):
                return
            print(f"{label:<16}: {_short(value, limit)}")

        code = record.get("code") or record.get("shortcode") or ""
        url = record.get("url") or (f"https://www.instagram.com/reel/{code}/" if code else "")

        print("=" * 72)
        print("Explorer record")
        print("=" * 72)

        print(f"{'origin':<16}: {origin}")
        _print_value("reel_pk", record.get("reel_pk"))
        _print_value("code", code)
        _print_value("url", url)
        _print_value("taken_at", record.get("taken_at"))
        _print_value("ingested_at", record.get("ingested_at"))
        print()

        print("Song / asset")
        print("-" * 72)
        _print_value("song_id", record.get("song_id"))
        _print_value("song_title", record.get("song_title"))
        _print_value("song_artist", record.get("song_artist"))
        _print_value("asset_id", record.get("asset_id"))
        _print_value("variant_label", record.get("variant_label"))
        print()

        print("Creator / engagement")
        print("-" * 72)
        _print_value("creator_pseudo", record.get("creator_pseudo"))
        _print_value("like_count", record.get("like_count"))
        _print_value("play_count", record.get("play_count"))
        _print_value("view_count", record.get("view_count"))
        _print_value("comment_count", record.get("comment_count"))
        _print_value("video_duration", record.get("video_duration"))
        _print_value("is_spam", record.get("is_spam"))
        print()

        print("Caption")
        print("-" * 72)
        caption = _short(record.get("caption_text"), 1800)
        print(caption if caption else "(empty)")
        print()

        print("Hashtags")
        print("-" * 72)
        hashtags = _list_text(record.get("hashtags"), limit=100)
        print(hashtags if hashtags else "(none)")
        print()

        print("Vision")
        print("-" * 72)
        vision_labels = _list_text(record.get("vision_labels"), limit=100)
        vision_dimensions = _list_text(record.get("vision_dimensions"), limit=100)
        print(f"{'vision_labels':<16}: {vision_labels if vision_labels else '(none)'}")
        print(f"{'vision_dimensions':<16}: {vision_dimensions if vision_dimensions else '(none)'}")
        print()

        manual_entry = self._manual_entry_for_record(record)
        if manual_entry:
            tags = manual_entry.get("tags") or []
            notes = manual_entry.get("notes") or []
            flags = manual_entry.get("flags") or {}
            if not isinstance(tags, list):
                tags = []
            if not isinstance(notes, list):
                notes = []
            if not isinstance(flags, dict):
                flags = {}
            if tags or notes or any(bool(flags.get(k, False)) for k in ("keep", "spam", "exclude", "reviewed")):
                print("Manual annotations")
                print("-" * 72)
                print(f"{'tags':<16}: {', '.join(tags) if tags else '(none)'}")
                print(
                    f"{'flags':<16}: "
                    f"keep={bool(flags.get('keep', False))}, "
                    f"spam={bool(flags.get('spam', False))}, "
                    f"exclude={bool(flags.get('exclude', False))}, "
                    f"reviewed={bool(flags.get('reviewed', False))}"
                )
                if notes:
                    print("notes:")
                    for note in notes:
                        if isinstance(note, dict):
                            print(f"  - {note.get('created_at', '')}: {note.get('text', '')}")
                        else:
                            print(f"  - {note}")
                print()

        view_names = self._views_for_record(record)
        if view_names:
            print("Saved views")
            print("-" * 72)
            print(f"{'views':<16}: {', '.join(view_names)}")
            print()

        print("Media")
        print("-" * 72)
        _print_value("thumbnail_url", record.get("thumbnail_url"), limit=2000)
        print()

        shown_fields = {
            "reel_pk", "pk", "id",
            "code", "shortcode", "url",
            "taken_at", "ingested_at",
            "song_id", "song_title", "song_artist",
            "asset_id", "variant_label",
            "creator_pseudo",
            "like_count", "play_count", "view_count", "comment_count",
            "video_duration", "is_spam",
            "caption_text", "hashtags",
            "vision_labels", "vision_dimensions",
            "thumbnail_url",
        }

        extra_keys = sorted(
            key for key, value in record.items()
            if key not in shown_fields and not _is_empty(value)
        )

        if extra_keys:
            print("Extra fields")
            print("-" * 72)
            for extra_key in extra_keys:
                value = record.get(extra_key)
                if isinstance(value, (list, tuple, set)):
                    value = _list_text(value)
                else:
                    value = _short(value, 300)
                print(f"{extra_key:<16}: {value}")
            print()


    def do_top(self, arg):
        """
        Show the most frequent values for a field in the active Explorer set.
        Syntax: top FIELD [N]
        Examples: top hashtags 20 | top songs | top creators
        """
        state = self._require_loaded()
        if state is None:
            return
        tokens = shlex.split(arg or "")
        if not tokens:
            print("Syntax: top FIELD [N]")
            return
        requested = tokens[0].lower()
        field_name = _field_name(requested)
        if requested in {"songs"}:
            field_name = "song_title"
        elif requested in {"creators"}:
            field_name = "creator_pseudo"
        elif requested in {"hashtags", "hashtag"}:
            field_name = "hashtags"
        n = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 10
        counts: dict[str, int] = {}
        for record in state.active():
            value = record.get(field_name)
            values = value if isinstance(value, list) else [value]
            for item in values:
                label = _stringify(item).strip()
                if not label:
                    continue
                counts[label] = counts.get(label, 0) + 1
        if not counts:
            print(f"No values found for field: {field_name}")
            return
        for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold()))[:n]:
            print(f"{count:5d}  {label}")

    def do_filtersave(self, arg):
        """
        Save the active Explorer set as JSON or CSV.
        Syntax: filtersave [PATH]
        Defaults to outputs/explorer/filter.json. File suffix controls format: .json or .csv.
        """
        state = self._require_loaded()
        if state is None:
            return
        target = (arg or "").strip() or "outputs/explorer/filter.json"
        path = Path(target)
        if not path.suffix:
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        active = state.active()
        try:
            _write_records(path, active, metadata={
                "source": state.source,
                "last_filter": state.last_filter,
                "total_records": state.total_count,
                "active_records": len(active),
            })
            print(f"Saved {len(active)} Explorer records: {path}")
        except Exception as e:
            print(f"filtersave failed: {e}")
    def do_hits(self, arg):
        """
        Show matching snippets for the last text or field filter.
        Syntax: hits [N]
        """
        state = self._require_loaded()
        if state is None:
            return
        query = state.last_query or {}
        terms = query.get("terms") or []
        fields = query.get("fields")
        limit = int((arg or "10").strip() or 10)
        active = state.active()
        if not active:
            print("No active records.")
            return
        if not terms:
            print("No text/field filter available for hits. Use filter or fieldfilter first.")
            for i, record in enumerate(active[:limit], start=1):
                self._print_record_brief(record, i)
            return
        shown = 0
        for i, record in enumerate(active, start=1):
            snippets = _extract_hit_snippets(record, terms, fields=fields)
            if not snippets:
                continue
            self._print_record_brief(record, i)
            for field, snippet in snippets[:3]:
                print(f"    {field}: {snippet}")
            shown += 1
            if shown >= limit:
                break
        print(f"Shown hits: {shown} of {len(active)} active records.")

    def do_compare(self, arg):
        """
        Compare value frequencies in the active Explorer set against the full loaded set.
        Syntax: compare FIELD [N]
        Examples: compare hashtags 20 | compare songs | compare vision
        """
        state = self._require_loaded()
        if state is None:
            return
        tokens = shlex.split(arg or "")
        if not tokens:
            print("Syntax: compare FIELD [N]")
            return
        requested = tokens[0].lower()
        field_name = _field_name(requested)
        if requested in {"songs"}:
            field_name = "song_title"
        elif requested in {"creators"}:
            field_name = "creator_pseudo"
        elif requested in {"hashtags", "hashtag"}:
            field_name = "hashtags"
        elif requested in {"vision", "labels"}:
            field_name = "vision_labels"
        n = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 10
        active = state.active()
        total = state.data
        if not active or not total:
            print("No records to compare.")
            return
        active_counts = _value_counts(active, field_name)
        total_counts = _value_counts(total, field_name)
        if not active_counts:
            print(f"No values found for field: {field_name}")
            return
        rows = []
        for label, active_count in active_counts.items():
            total_count = total_counts.get(label, 0)
            active_share = active_count / max(1, len(active))
            total_share = total_count / max(1, len(total))
            lift = active_share / total_share if total_share else float("inf")
            delta = active_share - total_share
            rows.append((label, active_count, total_count, active_share, total_share, lift, delta))
        rows.sort(key=lambda r: (-r[5], -r[1], r[0].casefold()))
        print(f"Compare field={field_name} | active={len(active)} | total={len(total)}")
        print(" active  total  active%  total%   lift  value")
        for label, ac, tc, ash, tsh, lift, _delta in rows[:n]:
            lift_s = "inf" if lift == float("inf") else f"{lift:5.2f}"
            print(f"{ac:7d} {tc:6d} {ash*100:7.1f} {tsh*100:7.1f} {lift_s:>6s}  {label}")

    def do_saveview(self, arg):
        """
        Save the active Explorer subset as a named persistent View.
        Syntax: saveview NAME
        Example: saveview high_impact_reels
        """
        state = self._require_loaded()
        if state is None:
            return
        name = (arg or "").strip()
        if not name:
            print("Syntax: saveview NAME")
            return
        if not self._validate_view_name(name):
            print("Invalid view name. Use only letters, numbers, underscores, and hyphens.")
            return

        active = state.active()
        if not active:
            print("Warning: active Explorer subset is empty. Saving an empty View.")

        ids: list[str] = []
        skipped = 0
        for record in active:
            ident = self._record_identifier(record)
            if ident is None:
                skipped += 1
            else:
                ids.append(ident)

        views = self._load_views()
        existed = name in views
        views[name] = {
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": state.source,
            "total_records": state.total_count,
            "active_records": len(active),
            "last_filter": state.last_filter,
            "ids": ids,
        }
        try:
            self._save_views(views)
        except Exception as e:
            print(f"saveview failed: {e}")
            return

        verb = "Overwrote" if existed else "Saved"
        print(f"{verb} view '{name}' with {len(ids)} IDs: {self._views_path()}")
        backup = getattr(self, "_last_views_backup", None)
        if backup:
            print(f"Backup created: {backup}")
        if skipped:
            print(f"Warning: {skipped} active records had no reel_pk/code/shortcode and were not saved.")

    def do_useview(self, arg):
        """
        Restore a saved View against the currently loaded Explorer records.
        Syntax: useview NAME
        Example: useview high_impact_reels
        """
        state = self._require_loaded()
        if state is None:
            return
        name = (arg or "").strip()
        if not name:
            print("Syntax: useview NAME")
            return
        views = self._load_views()
        view = views.get(name)
        if not isinstance(view, dict):
            print(f"No saved view named: {name}")
            return
        ids = view.get("ids") or []
        if not isinstance(ids, list):
            print(f"Saved view '{name}' is malformed: ids is not a list.")
            return

        restored, missing = self._restore_records_by_ids(ids)
        state.filtered = restored
        state.last_filter = f"view {name}"
        state.last_query = {"type": "view", "name": name, "ids": ids}

        print(f"View             : {name}")
        print(f"Stored IDs       : {len(ids)}")
        print(f"Restored records : {len(restored)}")
        print(f"Missing records  : {len(missing)}")
        if missing:
            preview = ", ".join(missing[:10])
            suffix = f" … (+{len(missing) - 10} more)" if len(missing) > 10 else ""
            print(f"Missing IDs      : {preview}{suffix}")

    def do_views(self, _):
        """
        List saved Explorer Views.
        Syntax: views
        Example: views
        """
        views = self._load_views()
        if not views:
            print("No saved Explorer views found.")
            return
        print("Saved Explorer views")
        print("name                 created_at                  active/ids  source  last_filter")
        print("-" * 96)
        for name in sorted(views):
            view = views.get(name) or {}
            if not isinstance(view, dict):
                continue
            ids = view.get("ids") or []
            ids_count = len(ids) if isinstance(ids, list) else 0
            active_records = view.get("active_records", ids_count)
            created_at = _stringify(view.get("created_at") or "")[:25]
            source = _stringify(view.get("source") or "")
            last_filter = _stringify(view.get("last_filter") or "")
            print(f"{name[:20]:20s} {created_at:27s} {active_records:>6}/{ids_count:<6} {source[:24]:24s} {last_filter[:28]}")

    def do_dropview(self, arg):
        """
        Delete a saved Explorer View.
        Syntax: dropview NAME
        Example: dropview high_impact_reels
        """
        name = (arg or "").strip()
        if not name:
            print("Syntax: dropview NAME")
            return
        views = self._load_views()
        if name not in views:
            print(f"No saved view named: {name}")
            return
        del views[name]
        try:
            self._save_views(views)
        except Exception as e:
            print(f"dropview failed: {e}")
            return
        print(f"Dropped view '{name}'.")
        backup = getattr(self, "_last_views_backup", None)
        if backup:
            print(f"Backup created: {backup}")

    def do_review(self, arg):
        """
        Show the next active records in compact review form.
        Syntax: review [N]
        Default N is 10. Maximum N is 50.
        Example: review 15
        """
        state = self._require_loaded()
        if state is None:
            return
        raw = (arg or "").strip()
        if raw:
            tokens = shlex.split(raw)
            if len(tokens) != 1 or not tokens[0].isdigit():
                print("Syntax: review [N]")
                return
            n = int(tokens[0])
        else:
            n = 10
        n = max(1, min(n, 50))
        active = state.active()
        if not active:
            print("No active Explorer records to review.")
            return
        shown = active[:n]
        print(f"Review records: showing {len(shown)} of {len(active)} active records")
        for i, record in enumerate(shown, start=1):
            code = self._record_label(record)
            song = _stringify(record.get("song_title") or record.get("song_id") or "?")
            likes = record.get("like_count")
            plays = record.get("play_count") or record.get("view_count")
            tags = self._format_review_tags(record)
            flags = self._format_review_flags(record)
            caption = _stringify(record.get("caption_text") or "").replace("\n", " ").strip()
            if len(caption) > 140:
                caption = caption[:139] + "…"
            print(f"[{i}] {code} | {song} | likes={likes} | plays={plays} | tags={tags} | flags={flags}")
            if caption:
                print(f"    {caption}")
        print("Use: keep INDEX, markspam INDEX, exclude INDEX, tag INDEX TAG, note INDEX TEXT, inspect INDEX")

    def do_keep(self, arg):
        """
        Mark a record as keep=true and reviewed=true.
        Syntax: keep TARGET
        Example: keep 1
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: keep TARGET")
            return
        self._set_manual_flag(target, "keep", True, reviewed_decision=True)

    def do_unkeep(self, arg):
        """
        Clear keep on a record.
        Syntax: unkeep TARGET
        Example: unkeep 1
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: unkeep TARGET")
            return
        self._set_manual_flag(target, "keep", False)

    def do_markspam(self, arg):
        """
        Mark a record as manual spam and reviewed=true.
        Syntax: markspam TARGET
        Example: markspam 2
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: markspam TARGET")
            return
        self._set_manual_flag(target, "spam", True, reviewed_decision=True)

    def do_unmarkspam(self, arg):
        """
        Clear manual spam on a record.
        Syntax: unmarkspam TARGET
        Example: unmarkspam 2
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: unmarkspam TARGET")
            return
        self._set_manual_flag(target, "spam", False)

    def do_exclude(self, arg):
        """
        Mark a record as manually excluded and reviewed=true.
        Syntax: exclude TARGET
        Example: exclude 3
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: exclude TARGET")
            return
        self._set_manual_flag(target, "exclude", True, reviewed_decision=True)

    def do_unexclude(self, arg):
        """
        Clear manual exclude on a record.
        Syntax: unexclude TARGET
        Example: unexclude 3
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: unexclude TARGET")
            return
        self._set_manual_flag(target, "exclude", False)

    def do_reviewed(self, arg):
        """
        Mark a record as reviewed.
        Syntax: reviewed TARGET
        Example: reviewed 4
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: reviewed TARGET")
            return
        self._set_manual_flag(target, "reviewed", True)

    def do_unreviewed(self, arg):
        """
        Clear reviewed on a record.
        Syntax: unreviewed TARGET
        Example: unreviewed 4
        """
        target = (arg or "").strip()
        if not target:
            print("Syntax: unreviewed TARGET")
            return
        self._set_manual_flag(target, "reviewed", False)

    def do_annotationstatus(self, _):
        """
        Show manual annotation and review status.
        Syntax: annotationstatus
        Example: annotationstatus
        """
        n_records, n_tags, n_notes = self._manual_annotation_counts()
        review_counts = self._manual_review_counts()
        state = self._explorer()
        views = self._load_views()
        path = self._annotations_path()
        print("Manual annotation status")
        print(f"  data loaded          : {bool(state.data)}")
        print(f"  source               : {state.source or '(none)'}")
        print(f"  total records        : {state.total_count}")
        print(f"  active records       : {state.active_count}")
        print(f"  saved views          : {len(views)}")
        print(f"  annotations file path: {path}")
        print(f"  annotations file exists: {path.exists()}")
        print(f"  annotated records    : {n_records}")
        print(f"  tags total           : {n_tags}")
        print(f"  notes total          : {n_notes}")
        print(f"  reviewed             : {review_counts['reviewed']}")
        print(f"  keep                 : {review_counts['keep']}")
        print(f"  spam                 : {review_counts['spam']}")
        print(f"  exclude              : {review_counts['exclude']}")

    def do_tag(self, arg):
        """
        Add a manual tag to one Explorer record.
        Syntax: tag TARGET TAG
        TARGET may be active index, reel_pk, code, or shortcode.
        Example: tag 1 context:dance_challenge
        """
        tokens = shlex.split(arg or "")
        if len(tokens) != 2:
            print("Syntax: tag TARGET TAG")
            return
        target, raw_tag = tokens
        if self._require_loaded() is None:
            return
        record = self._resolve_record_target(target)
        if record is None:
            print(f"No Explorer record found for: {target}")
            return
        tag = self._normalize_tag(raw_tag)
        if tag is None:
            print("Invalid tag. Use only a-z, 0-9, underscore, hyphen, and colon; spaces are converted to underscores.")
            return
        record_id, entry = self._ensure_manual_entry(record)
        if record_id is None or entry is None:
            print("Could not create a stable manual annotation ID for this record.")
            return
        tags = entry.setdefault("tags", [])
        if not isinstance(tags, list):
            tags = []
            entry["tags"] = tags
        if tag in tags:
            print(f"Tag already present: {tag}")
            return
        tags.append(tag)
        tags.sort()
        print(f"Added tag '{tag}' to {self._record_label(record)}")

    def do_untag(self, arg):
        """
        Remove a manual tag from one Explorer record.
        Syntax: untag TARGET TAG
        TARGET may be active index, reel_pk, code, or shortcode.
        Example: untag 1 context:dance_challenge
        """
        tokens = shlex.split(arg or "")
        if len(tokens) != 2:
            print("Syntax: untag TARGET TAG")
            return
        target, raw_tag = tokens
        if self._require_loaded() is None:
            return
        record = self._resolve_record_target(target)
        if record is None:
            print(f"No Explorer record found for: {target}")
            return
        tag = self._normalize_tag(raw_tag)
        if tag is None:
            print("Invalid tag. Use only a-z, 0-9, underscore, hyphen, and colon; spaces are converted to underscores.")
            return
        entry = self._manual_entry_for_record(record)
        if not entry:
            print(f"No manual annotations found for {self._record_label(record)}.")
            return
        tags = entry.get("tags") or []
        if not isinstance(tags, list) or tag not in tags:
            print(f"Tag not present: {tag}")
            return
        tags = [item for item in tags if item != tag]
        entry["tags"] = tags
        record_id = self._manual_record_id(record)
        if record_id is not None:
            self._prune_manual_entry_if_empty(record_id)
        print(f"Removed tag '{tag}' from {self._record_label(record)}")

    def do_tags(self, _):
        """
        Show manual tag frequencies.
        Syntax: tags
        Example: tags
        """
        records = self._manual_annotations().get("records", {})
        counts: dict[str, int] = {}
        for entry in records.values():
            if not isinstance(entry, dict):
                continue
            tags = entry.get("tags") or []
            if not isinstance(tags, list):
                continue
            for tag in tags:
                label = _stringify(tag).strip()
                if label:
                    counts[label] = counts.get(label, 0) + 1
        if not counts:
            print("No manual tags found.")
            return
        print("Manual tags")
        for tag, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].casefold())):
            print(f"{count:5d}  {tag}")

    def do_note(self, arg):
        """
        Add a free-text manual note to one Explorer record.
        Syntax: note TARGET TEXT
        TARGET may be active index, reel_pk, code, or shortcode.
        Example: note 1 "strong visual framing"
        """
        parts = shlex.split(arg or "")
        if len(parts) < 2:
            print("Syntax: note TARGET TEXT")
            return
        target = parts[0]
        text = " ".join(parts[1:]).strip()
        if not text:
            print("Syntax: note TARGET TEXT")
            return
        if self._require_loaded() is None:
            return
        record = self._resolve_record_target(target)
        if record is None:
            print(f"No Explorer record found for: {target}")
            return
        record_id, entry = self._ensure_manual_entry(record)
        if record_id is None or entry is None:
            print("Could not create a stable manual annotation ID for this record.")
            return
        notes = entry.setdefault("notes", [])
        if not isinstance(notes, list):
            notes = []
            entry["notes"] = notes
        notes.append({
            "created_at": datetime.now(timezone.utc).isoformat(),
            "text": text,
        })
        print(f"Added note to {self._record_label(record)}")

    def do_notes(self, arg):
        """
        Show manual notes.
        Syntax: notes [TARGET]
        Without TARGET, shows all records with notes. With TARGET, shows all notes for one record.
        Example: notes 1
        """
        target = (arg or "").strip()
        annotations = self._manual_annotations()
        records = annotations.get("records", {})
        if target:
            if self._require_loaded() is None:
                return
            record = self._resolve_record_target(target)
            if record is None:
                print(f"No Explorer record found for: {target}")
                return
            entry = self._manual_entry_for_record(record)
            notes = entry.get("notes") if isinstance(entry, dict) else []
            if not isinstance(notes, list) or not notes:
                print(f"No manual notes found for {self._record_label(record)}.")
                return
            print(f"Manual notes for {self._record_label(record)}")
            for note in notes:
                if isinstance(note, dict):
                    print(f"- {note.get('created_at', '')}: {note.get('text', '')}")
                else:
                    print(f"- {note}")
            return

        lookup = self._annotation_record_lookup()
        rows: list[tuple[str, str, int, str]] = []
        for record_id, entry in records.items():
            if not isinstance(entry, dict):
                continue
            notes = entry.get("notes") or []
            if not isinstance(notes, list) or not notes:
                continue
            record = lookup.get(_stringify(record_id)) or lookup.get(_stringify(entry.get("reel_pk"))) or lookup.get(_stringify(entry.get("code")))
            label = self._record_label(record) if record else (_stringify(entry.get("code") or entry.get("reel_pk") or record_id))
            song = _stringify((record or {}).get("song_title") or (record or {}).get("song_id") or "")
            last = notes[-1]
            last_text = _stringify(last.get("text") if isinstance(last, dict) else last).replace("\n", " ")
            if len(last_text) > 90:
                last_text = last_text[:89] + "…"
            rows.append((label, song, len(notes), last_text))
        if not rows:
            print("No manual notes found.")
            return
        print("Manual notes")
        print("record               song                      n  last note")
        print("-" * 88)
        for label, song, n, last_text in sorted(rows, key=lambda r: r[0].casefold()):
            print(f"{label[:20]:20s} {song[:24]:24s} {n:2d} {last_text}")

    def do_annotationsave(self, _):
        """
        Save manual tags, notes, and review flags to outputs/explorer/manual_annotations.json.
        Syntax: annotationsave
        Example: annotationsave
        """
        try:
            self._save_manual_annotations()
        except Exception as e:
            print(f"annotationsave failed: {e}")
            return
        n_records, n_tags, n_notes = self._manual_annotation_counts()
        print(f"Manual annotations saved: {self._annotations_path()}")
        backup = getattr(self, "_last_annotations_backup", None)
        if backup:
            print(f"Backup created: {backup}")
        print(f"Records with annotations: {n_records}")
        print(f"Tags total              : {n_tags}")
        print(f"Notes total             : {n_notes}")
        review_counts = self._manual_review_counts()
        print(f"Reviewed                : {review_counts['reviewed']}")
        print(f"Kept                    : {review_counts['keep']}")
        print(f"Manual spam             : {review_counts['spam']}")
        print(f"Excluded                : {review_counts['exclude']}")

    def do_annotationload(self, _):
        """
        Load manual tags, notes, and review flags from outputs/explorer/manual_annotations.json.
        Syntax: annotationload
        Example: annotationload
        """
        payload = self._load_manual_annotations(silent_missing=False)
        if payload is None:
            return
        n_records, n_tags, n_notes = self._manual_annotation_counts()
        print(f"Manual annotations loaded: {self._annotations_path()}")
        print(f"Records with annotations: {n_records}")
        print(f"Tags total              : {n_tags}")
        print(f"Notes total             : {n_notes}")
        review_counts = self._manual_review_counts()
        print(f"Reviewed                : {review_counts['reviewed']}")
        print(f"Kept                    : {review_counts['keep']}")
        print(f"Manual spam             : {review_counts['spam']}")
        print(f"Excluded                : {review_counts['exclude']}")

    def do_exportview(self, arg):
        """
        Export the active Explorer set as JSON, CSV, or Markdown.
        Syntax: exportview [json|csv|md] [PATH]
        Examples: exportview csv outputs/explorer/current.csv | exportview markdown close_reading.md
        """
        state = self._require_loaded()
        if state is None:
            return
        tokens = shlex.split(arg or "")
        fmt = "json"
        target = "outputs/explorer/view.json"
        if tokens:
            first = tokens[0].lower()
            if first in {"json", "csv", "md", "markdown"}:
                fmt = "md" if first == "markdown" else first
                if len(tokens) > 1:
                    target = tokens[1]
                else:
                    target = f"outputs/explorer/view.{fmt}"
            else:
                target = tokens[0]
                suffix = Path(target).suffix.lower().lstrip(".")
                fmt = "md" if suffix in {"md", "markdown"} else (suffix or "json")
        path = Path(target)
        if not path.suffix:
            path = path.with_suffix(f".{fmt}")
        active = state.active()
        export_records = [self._augment_record_with_manual_annotations(record) for record in active]
        try:
            _write_records(path, export_records, metadata={
                "source": state.source,
                "last_filter": state.last_filter,
                "total_records": state.total_count,
                "active_records": len(active),
                "export_format": fmt,
            })
            print(f"Exported {len(export_records)} Explorer records: {path}")
        except Exception as e:
            print(f"exportview failed: {e}")

