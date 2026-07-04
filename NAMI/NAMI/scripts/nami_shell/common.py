from __future__ import annotations

import csv
import difflib
import json
from datetime import datetime, timezone
import logging
import os
import shutil
import random
import re
import runpy
import shlex
import sqlite3
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_DB = "data/corpus.db"
DEFAULT_SCHEMA = "config/schema.yaml"
DEFAULT_SONGS = "config/songs.yaml"
DEFAULT_REPORT_OUT = "outputs/report_out"


FIELD_ALIASES = {
    "caption": "caption_text",
    "text": "caption_text",
    "creator": "creator_pseudo",
    "user": "creator_pseudo",
    "shortcode": "code",
    "urlcode": "code",
    "song": "song_id",
    "title": "song_title",
    "artist": "song_artist",
    "likes": "like_count",
    "plays": "play_count",
    "views": "view_count",
    "comments": "comment_count",
    "duration": "video_duration",
    "date": "taken_at",
    "hashtags": "hashtags",
    "hashtag": "hashtags",
    "vision": "vision_labels",
    "tags": "vision_labels"
}

TEXT_SEARCH_FIELDS = [
    "caption_text",
    "hashtags",
    "song_id",
    "song_title",
    "song_artist",
    "asset_id",
    "variant_label",
    "code",
    "creator_pseudo",
    "vision_labels",
    "vision_dimensions"
]

DISPLAY_FIELDS = [
    "reel_pk",
    "code",
    "song_id",
    "song_title",
    "song_artist",
    "asset_id",
    "creator_pseudo",
    "taken_at",
    "caption_text",
    "hashtags",
    "like_count",
    "play_count",
    "view_count",
    "comment_count",
    "video_duration",
    "vision_labels"
]

def _field_name(name: str) -> str:
    return FIELD_ALIASES.get((name or "").strip().lower(), (name or "").strip())

def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify(v) for v in value)

    return str(value)

def _needle_match(record: dict[str, Any], terms: list[str], mode: str = "and") -> bool:
    haystack = " \n".join(_stringify(record.get(field, "")) for field in TEXT_SEARCH_FIELDS).casefold()
    checks = [term.casefold() in haystack for term in terms]

    return all(checks) if mode == "and" else any(checks)

def _coerce_for_compare(value: Any) -> Any:
    """
    Turn a value into a number for comparison when possible, else lowercased text.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = _stringify(value).strip()
    if text == "":
        return None
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text.casefold()

def _compare_values(left: Any, operator: str, right_text: str) -> bool:
    """
    Compare two values with an operator such as =, >, or 'contains'.
    """
    operator = operator.lower()
    if operator == "contains":
        return right_text.casefold() in _stringify(left).casefold()
    left_value = _coerce_for_compare(left)
    right_value = _coerce_for_compare(right_text)
    if operator in {"=", "=="}:
        return left_value == right_value
    if operator == "!=":
        return left_value != right_value
    if left_value is None or right_value is None:
        return False
    try:
        if operator == ">":
            return left_value > right_value
        if operator == ">=":
            return left_value >= right_value
        if operator == "<":
            return left_value < right_value
        if operator == "<=":
            return left_value <= right_value

    except TypeError:
        left_s = _stringify(left_value)
        right_s = _stringify(right_value)
        if operator == ">":
            return left_s > right_s
        if operator == ">=":
            return left_s >= right_s
        if operator == "<":
            return left_s < right_s
        if operator == "<=":
            return left_s <= right_s

    raise ValueError(f"Unsupported operator: {operator}")

def _flatten_for_csv(record: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, list):
            flat[key] = "; ".join(_stringify(v) for v in value)
        else:
            flat[key] = value
    return flat

def _field_values(record: dict[str, Any], field_name: str) -> list[str]:
    value = record.get(field_name)
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    return [_stringify(value)]

def _record_search_matches(record: dict[str, Any], terms: list[str], mode: str = "and", fields: list[str] | None = None) -> bool:
    search_fields = fields or TEXT_SEARCH_FIELDS
    haystack = " \n".join(_stringify(record.get(field, "")) for field in search_fields).casefold()
    checks = [term.casefold() in haystack for term in terms]
    return all(checks) if mode == "and" else any(checks)

def _extract_hit_snippets(record: dict[str, Any], terms: list[str], fields: list[str] | None = None, width: int = 72) -> list[tuple[str, str]]:
    snippets: list[tuple[str, str]] = []
    search_fields = fields or TEXT_SEARCH_FIELDS
    lower_terms = [t.casefold() for t in terms if t]
    if not lower_terms:
        return snippets
    for field in search_fields:
        text = _stringify(record.get(field, ""))
        if not text:
            continue
        text_cf = text.casefold()
        hit_positions = [text_cf.find(term) for term in lower_terms if term in text_cf]
        if not hit_positions:
            continue
        pos = min(p for p in hit_positions if p >= 0)
        start = max(0, pos - width // 2)
        end = min(len(text), pos + width // 2)
        snippet = text[start:end].replace("\n", " ")
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet = snippet + "…"
        for term in sorted(lower_terms, key=len, reverse=True):
            snippet = re.sub(re.escape(term), lambda m: f"[{m.group(0)}]", snippet, flags=re.IGNORECASE)
        snippets.append((field, snippet))

    return snippets

def _value_counts(records: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(field_name)
        values = value if isinstance(value, list) else [value]
        for item in values:
            label = _stringify(item).strip()
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1

    return counts

def _write_records(path: Path, records: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows = [_flatten_for_csv(record) for record in records]
        fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else DISPLAY_FIELDS
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return
    if suffix == ".json":
        payload: Any = records
        if metadata is not None:
            payload = {**metadata, "items": records}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if suffix in {".md", ".markdown"}:
        lines = ["# NAMI Explorer Export", ""]
        if metadata:
            for key, value in metadata.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")
        for i, record in enumerate(records, start=1):
            code = record.get("code") or record.get("reel_pk") or i
            title = record.get("song_title") or record.get("song_id") or "Unknown song"
            lines.append(f"## {i}. {code} — {title}")
            for field in DISPLAY_FIELDS:
                value = record.get(field)
                if value not in (None, "", []):
                    lines.append(f"- **{field}**: {_stringify(value)}")
            if record.get("url"):
                lines.append(f"- **url**: {record['url']}")
            for field in ("manual_tags", "manual_notes_count", "manual_notes", "manual_keep", "manual_spam", "manual_exclude", "manual_reviewed"):
                value = record.get(field)
                if value not in (None, "", []):
                    lines.append(f"- **{field}**: {_stringify(value)}")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    raise ValueError("Supported output formats: .json, .csv, .md")

def _bool_from_flag(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "n", "off"}

def _norm_key(key: str) -> str:
    return key.replace("-", "_")


def _reject_unknown_opts(opts: dict[str, str], allowed: set[str]) -> None:
    """
    Raise ValueError when an option key is not one this command accepts.
    """
    allowed_norm = {_norm_key(a) for a in allowed}
    unknown = [k for k in opts if k not in allowed_norm]
    if not unknown:
        return

    def _flag(name: str) -> str:
        return "--" + name.replace("_", "-")

    parts = []
    for key in unknown:
        near = difflib.get_close_matches(key, allowed_norm, n=1)
        hint = f" (did you mean {_flag(near[0])}?)" if near else ""
        parts.append(f"{_flag(key)}{hint}")
    valid = ", ".join(_flag(a) for a in sorted(allowed_norm))
    raise ValueError(
        f"Unknown option(s): {', '.join(parts)}. Valid options: {valid}."
    )


def _parse_kv_args(arg: str, allowed: set[str] | None = None) -> tuple[list[str], dict[str, str]]:
    """
    Parse shell args into positional tokens and --key value / --key=value options.
    """
    tokens = shlex.split(arg or "")
    pos: list[str] = []
    opts: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            body = tok[2:]
            if "=" in body:
                key, value = body.split("=", 1)
                opts[_norm_key(key)] = value
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                opts[_norm_key(body)] = tokens[i + 1]
                i += 1
            else:
                opts[_norm_key(body)] = "true"
        else:
            pos.append(tok)
        i += 1
    if allowed is not None:
        _reject_unknown_opts(opts, allowed)

    return pos, opts


def _bounded_float(value: str | None, name: str, lo: float, hi: float, default: float) -> float:
    """
    Parse a numeric option and require it to fall within [lo, hi].
    """
    if value is None:
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number between {lo} and {hi}, got {value!r}.")
    if not (lo <= num <= hi):
        raise ValueError(f"{name} must be between {lo} and {hi}, got {num}.")
    return num

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None



_PATH_FLAGS = {"db", "schema", "out"}
_BOOL_FLAGS = {"refresh", "stub", "reset", "silent", "only_vision_tagged",
               "no_crawl", "no_vision", "no_av"}

COMMAND_OPTIONS: dict[str, dict] = {
    "status":       {"flags": {"db"}},
    "setupdb":      {"flags": {"db"}},
    "refresh":      {"flags": {"no_crawl", "no_vision", "no_av",
                               "refresh", "pages", "empty_stop", "sleep"}},
    "annotations":  {"flags": {"db"}},
    "snapshot":     {"flags": {"db", "note"}},
    "robustness":   {"flags": {"db", "schema", "out", "sources", "min_conf"},
                     "values": {"sources": ["keyword", "vision", "keyword,vision"]}},
    "concordance":  {"flags": {"db", "schema", "out", "min_conf"}},
    "report":       {"flags": {"db", "schema", "out", "sources", "min_conf",
                               "only_vision_tagged", "silent"},
                     "values": {"sources": ["keyword", "vision", "keyword,vision"]}},
    "crawldetails": {"flags": {"db", "limit", "sleep"}},
    "fetchthumbs":  {"flags": {"db", "refresh", "img_timeout", "api_timeout"}},
    "fetchmedia":   {"flags": {"db", "refresh", "vid_timeout", "api_timeout"}},
    "tagvision":    {"flags": {"db", "stub", "limit", "reset", "model",
                               "resolution", "fps", "workers", "min_interval"},
                     "values": {"resolution": ["default", "low"],
                                "model": ["gemini-2.5-flash", "gemini-2.5-pro"]}},
    "visionstatus": {"flags": {"db"}},
    "visionblocked": {"flags": {"db", "limit", "csv"}},
    "checkspam":    {"flags": {"db", "include_blocked"}},
    "spamreport":   {"flags": {"db", "out", "limit", "include_blocked", "silent"}},
    "load":         {"flags": {"db"}},
    "filter":       {"flags": {"and", "or"}},
    "fieldfilter":  {"flags": {"and", "or"}},
}


def command_flags(command: str) -> set[str] | None:
    """
    Return the option keys a command accepts, or None when unregistered.
    """
    spec = COMMAND_OPTIONS.get(command)
    return set(spec["flags"]) if spec else None


def _complete_path(text: str) -> list[str]:
    import glob
    matches = glob.glob(text + "*")
    return [m + os.sep if os.path.isdir(m) else m for m in matches]


def complete_command_options(command: str, text: str, line: str, begidx: int) -> list[str]:
    """
    Suggest option flags and values for a registered command (tab completion).
    """
    spec = COMMAND_OPTIONS.get(command)
    if not spec:
        return []
    flags = spec.get("flags", set())
    values = spec.get("values", {})

    try:
        before = shlex.split(line[:begidx])
    except ValueError:
        before = line[:begidx].split()

    prev = before[-1] if before else ""
    if prev.startswith("--"):
        key = _norm_key(prev[2:])
        if key in values:
            return [v for v in values[key] if v.startswith(text)]
        if key in _BOOL_FLAGS:
            return [v for v in ("true", "false") if v.startswith(text)]
        if key in _PATH_FLAGS:
            return _complete_path(text)

    if text.startswith("--") or text == "":
        used = {_norm_key(t[2:]) for t in before if t.startswith("--")}
        cands = ["--" + f.replace("_", "-") for f in sorted(flags) if f not in used]
        return [c for c in cands if c.startswith(text)] if text else cands
    return []


__all__ = [name for name in globals() if not name.startswith("__")]
