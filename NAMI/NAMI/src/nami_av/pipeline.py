"""
Full-pipeline orchestration — the ``av all`` command.

Runs every stage in order against one open connection / config:
extract-acoustic → variants → align → detect-edits → group-edits → annotate+report →
validate. Each stage is wrapped so a failure is recorded and the run *continues* (an
overnight job should complete as much as it can rather than abort on the first hiccup),
and every stage is resumable, so a re-run picks up where the last one stopped.

``retry_failed=True`` by default: stages reprocess assets/reels previously marked
``failed`` (the sensible default for an unattended completion pass).
"""

from __future__ import annotations

import sqlite3
import time

from . import (alignment, assetreport, bridge, editing, edits, external_ids, features,
               report, validate, variants)
from .config import AvConfig, default_config


def run_all(
    conn: sqlite3.Connection,
    cfg: AvConfig | None = None,
    *,
    max_reels: int | None = None,
    threshold: float | None = None,
    retry_failed: bool = True,
    no_fetch: bool = False,
    refresh_audio: bool = False,
    enrich: bool = False,
    progress: bool = False,
) -> dict[str, object]:
    """Run the whole sidecar pipeline; return a per-stage result/error summary."""
    cfg = cfg or default_config()
    results: dict[str, object] = {}

    def stage(name: str, fn):
        if progress:
            print(f"\n===== av all: {name} =====", flush=True)
        t = time.time()
        try:
            results[name] = fn()
            ok = True
        except Exception as exc:  # noqa: BLE001
            results[name] = f"FAILED: {type(exc).__name__}: {exc}"
            ok = False
        if progress:
            print(f"----- {name} {'done' if ok else 'FAILED'} in {time.time() - t:.0f}s",
                  flush=True)

    f_kw = {} if max_reels is None else {"max_reels": max_reels}
    e_kw = {} if threshold is None else {"threshold": threshold}

    stage("extract-acoustic",
          lambda: features.run(conn, cfg, include_failed=retry_failed, progress=progress,
                               fetch=not no_fetch, refresh_audio=refresh_audio, **f_kw))
    stage("variants", lambda: variants.run(conn, cfg))
    if enrich:
        stage("enrich-meta",
              lambda: external_ids.run(conn, cfg, include_failed=retry_failed, progress=progress))
    stage("align",
          lambda: alignment.run(conn, cfg, include_failed=retry_failed, progress=progress))
    stage("detect-edits",
          lambda: edits.run(conn, cfg, include_failed=retry_failed, progress=progress, **e_kw))
    stage("group-edits",
          lambda: edits.run_grouping(conn, cfg, progress=progress))
    stage("annotate+report",
          lambda: {"annotations": bridge.write_annotations(conn),
                   "report": str(report.build(conn, cfg)),
                   "usage_heatmaps": str(report.build_usage_heatmaps(conn, cfg, progress=progress)),
                   "video_editing": str(editing.build_video_editing(conn, cfg, progress=progress))})
    stage("assetreport", lambda: {"asset_report": str(assetreport.build(conn, cfg))})
    stage("validate", lambda: validate.export(conn, cfg, progress=progress))
    return results
