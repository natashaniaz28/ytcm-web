"""
Index Instagram Reels for configured music assets via HikerAPI.
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from hikerapi import Client

import yaml
from dotenv import load_dotenv
from nami_code.db import get_conn, sync_songs_from_yaml
from nami_code.analysis.snapshot_churn import (
    ensure_snapshot_tables,
    finish_crawl_run,
    record_reel_seen,
    start_crawl_run,
)


DEFAULT_SONGS_YAML = "config/songs.yaml"


@dataclass
class VariantResult:
    asset_id: str
    label: str
    pages: int = 0
    seen_items: int = 0
    new_ids: int = 0
    stopped_reason: str = ""
    seen_rows: int = 0


_CLIENT: Any | None = None


def log(message: str = "") -> None:
    """
    Print a message immediately.
    """
    print(message, flush=True)


def get_client() -> "Client":
    """
    Create the HikerAPI client.
    """
    global _CLIENT
    if _CLIENT is None:
        from hikerapi import Client

        load_dotenv()
        token = os.environ.get("HIKER_TOKEN")
        if not token:
            raise RuntimeError("Missing HIKER_TOKEN in environment or .env")
        _CLIENT = Client(token=token)
    return _CLIENT


def load_config(path: str) -> dict[str, Any]:
    """
    Read a YAML config file into a dictionary.
    """
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def call_track_stream(asset_id: str, page_id: str | None) -> dict[str, Any]:
    """
    Call HikerAPI track_stream_by_id_v2 with retries.

    HikerAPI documents this endpoint as track_id + optional page_id. Some SDK
    versions accept the track ID positionally, so this function falls back to
    the positional call if keyword arguments are not accepted.
    """
    client = get_client()
    last_error: Exception | None = None

    for attempt in range(6):
        try:
            kwargs: dict[str, str] = {"track_id": str(asset_id)}
            if page_id:
                kwargs["page_id"] = str(page_id)
            try:
                return client.track_stream_by_id_v2(**kwargs)
            except TypeError:
                if page_id:
                    return client.track_stream_by_id_v2(str(asset_id), page_id=str(page_id))
                return client.track_stream_by_id_v2(str(asset_id))
        except Exception as exc:
            last_error = exc
            wait_s = 2**attempt
            log(f"      ! {exc}, retry in {wait_s}s")
            time.sleep(wait_s)

    raise RuntimeError(f"track_stream_by_id_v2 failed for asset {asset_id}: {last_error}")


def get_response(res: dict[str, Any]) -> dict[str, Any]:
    """
    Pull the 'response' part out of an API result, or return an empty dictionary.
    """
    response = res.get("response", res)
    return response if isinstance(response, dict) else {}


def get_next_page_id(res: dict[str, Any]) -> str:
    """
    Return next_page_id whether it is top-level or nested under response.
    """
    response = get_response(res)
    return str(res.get("next_page_id") or response.get("next_page_id") or "")


def iter_media_from_stream(res):
    response = get_response(res)
    seen = set()

    for row in response.get("stream_rows", []) or []:
        if row.get("is_media_preview"):
            continue

        for item in row.get("items", []) or []:
            media = item.get("media")
            if not isinstance(media, dict):
                continue

            reel_pk = media.get("pk") or media.get("id")
            if not reel_pk:
                continue

            reel_pk = str(reel_pk)
            if reel_pk in seen:
                continue

            seen.add(reel_pk)
            yield media


def insert_reel_index_row(conn, reel_pk: str, asset_id: str, play_count: Any) -> bool:
    """
    Insert one Reel ID. Return True only if it was new.
    """
    cur = conn.execute(
        "INSERT OR IGNORE INTO reel_index (reel_pk, asset_id, play_count) VALUES (?, ?, ?)",
        (str(reel_pk), str(asset_id), play_count),
    )
    return bool(cur.rowcount)


def ensure_index_state_row(conn, asset_id: str) -> None:
    """
    Make sure each audio asset has a progress-tracking row before it is crawled.
    """
    row = conn.execute("SELECT 1 FROM index_state WHERE asset_id=?", (str(asset_id),)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO index_state (asset_id, status, updated_at) VALUES (?, 'pending', datetime('now'))",
            (str(asset_id),),
        )
        conn.commit()


def index_variant_full(conn, asset_id: str, label: str, sleep_s: float) -> VariantResult:
    """
    Full/resume crawl behavior for initial backfills.
    """
    result = VariantResult(asset_id=str(asset_id), label=label)

    row = conn.execute(
        "SELECT next_page_id, pages_done, ids_seen, status FROM index_state WHERE asset_id=?",
        (str(asset_id),),
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO index_state (asset_id, status, updated_at) VALUES (?, 'pending', datetime('now'))",
            (str(asset_id),),
        )
        conn.commit()
        page_id, pages_done, ids_seen = None, 0, 0
    else:
        page_id, pages_done, ids_seen, status = row
        if status == "done":
            result.pages = int(pages_done or 0)
            result.seen_items = int(ids_seen or 0)
            result.stopped_reason = "already done"
            log(f"    [{label}] sone ({ids_seen}).")
            return result
        page_id = page_id or None
        log(f"    [{label}] continuation from page {int(pages_done or 0) + 1}.")

    while True:
        res = call_track_stream(str(asset_id), page_id)
        batch = 0
        new_ids = 0

        for media in iter_media_from_stream(res):
            reel_pk = media.get("pk") or media.get("id")
            if not reel_pk:
                continue
            batch += 1
            if insert_reel_index_row(conn, str(reel_pk), str(asset_id), media.get("play_count")):
                new_ids += 1

        ids_seen = int(ids_seen or 0) + batch
        pages_done = int(pages_done or 0) + 1
        next_page_id = get_next_page_id(res)

        conn.execute(
            "UPDATE index_state SET next_page_id=?, pages_done=?, ids_seen=?, "
            "status='running', updated_at=datetime('now') WHERE asset_id=?",
            (next_page_id, pages_done, ids_seen, str(asset_id)),
        )
        conn.commit()

        result.pages += 1
        result.seen_items += batch
        result.new_ids += new_ids
        log(f"      Page {pages_done}: +{batch} seen, new: {new_ids} (total {ids_seen})")

        if not next_page_id:
            conn.execute(
                "UPDATE index_state SET status='done', updated_at=datetime('now') WHERE asset_id=?",
                (str(asset_id),),
            )
            conn.commit()
            result.stopped_reason = "no next_page_id"
            break

        page_id = next_page_id
        time.sleep(sleep_s)

    return result


def index_variant_refresh(
    conn,
    asset_id: str,
    song_id: str,
    label: str,
    sleep_s: float,
    max_pages: int | None,
    empty_stop: int,
    crawl_id: str,
) -> VariantResult:
    """
    Refresh crawl: start from page 1 and insert only unknown Reel IDs.

    Default refresh reads all available pages until HikerAPI returns no
    next_page_id. Use --pages N to cap depth. Use --empty-stop N only when you
    explicitly want a cost-saving early stop after N consecutive pages with zero
    new Reel IDs.
    """
    result = VariantResult(asset_id=str(asset_id), label=label)
    ensure_index_state_row(conn, str(asset_id))

    if max_pages is None:
        log(f"    [{label}] refresh from page 1, all available pages.")
    else:
        log(f"    [{label}] refresh from page 1, max {max_pages} pages.")

    page_id: str | None = None
    empty_pages = 0
    page_no = 0

    while True:
        if max_pages is not None and page_no >= max_pages:
            result.stopped_reason = f"max pages reached ({max_pages})"
            break

        page_no += 1
        res = call_track_stream(str(asset_id), page_id)
        batch = 0
        new_ids = 0

        rank_base = result.seen_items
        for page_pos, media in enumerate(iter_media_from_stream(res), start=1):
            reel_pk = media.get("pk") or media.get("id")
            if not reel_pk:
                continue
            batch += 1
            play_count = media.get("play_count")
            if insert_reel_index_row(conn, str(reel_pk), str(asset_id), play_count):
                new_ids += 1
            record_reel_seen(
                conn,
                crawl_id=crawl_id,
                reel_pk=str(reel_pk),
                asset_id=str(asset_id),
                song_id=str(song_id),
                page_no=page_no,
                page_pos=page_pos,
                rank_pos=rank_base + page_pos,
                play_count=play_count,
            )

        conn.execute("UPDATE index_state SET updated_at=datetime('now') WHERE asset_id=?", (str(asset_id),))
        conn.commit()

        result.pages += 1
        result.seen_items += batch
        result.seen_rows += batch
        result.new_ids += new_ids
        empty_pages = empty_pages + 1 if new_ids == 0 else 0

        log(f"      Refresh page {page_no}: {batch} seen, new: {new_ids}")

        next_page_id = get_next_page_id(res)
        if not next_page_id:
            result.stopped_reason = "no next_page_id"
            break

        if empty_stop > 0 and empty_pages >= empty_stop:
            result.stopped_reason = f"{empty_pages} page(s) without new IDs"
            break

        page_id = next_page_id
        time.sleep(sleep_s)

    return result


def print_summary(results: list[VariantResult], crawl_id: str | None = None, seen_rows_for_run: int | None = None) -> None:
    """
    Print a readable summary of an indexing run: pages, items seen and new IDs per asset.
    """
    log("\n" + "=" * 60)
    log("INDEX SUMMARY")
    log("=" * 60)
    total_seen = sum(r.seen_items for r in results)
    total_new = sum(r.new_ids for r in results)
    total_pages = sum(r.pages for r in results)

    for r in results:
        log(
            f"{r.asset_id:>18s} | {r.label[:28]:28s} | "
            f"pages {r.pages:3d} | seen {r.seen_items:5d} | new {r.new_ids:5d} | {r.stopped_reason}"
        )

    log("-" * 60)
    log(f"Total pages: {total_pages}")
    log(f"Total seen items: {total_seen}")
    log(f"Total new Reel IDs: {total_new}")
    if crawl_id is not None:
        log(f"Refresh crawl_run ID: {crawl_id}")
        log(f"reel_seen rows for this run: {seen_rows_for_run if seen_rows_for_run is not None else total_seen}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Read the command-line options for the indexing crawl.
    """
    parser = argparse.ArgumentParser(description="Index Instagram Reel IDs for NAMI music assets.")
    parser.add_argument("--songs", default=DEFAULT_SONGS_YAML, help="Path to songs.yaml")
    parser.add_argument("--sleep", type=float, default=0.3, help="Sleep seconds between HikerAPI pages")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Start at page 1 for every asset and insert only unknown Reel IDs.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Optional maximum pages per asset in --refresh mode. Default: all pages.",
    )
    parser.add_argument(
        "--empty-stop",
        "--stop-after-empty-pages",
        dest="empty_stop",
        type=int,
        default=0,
        help="Optional refresh early stop after N consecutive pages with zero new Reel IDs. Default: 0, disabled.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """
    Run the indexing crawl: read the song list, collect reel IDs per asset, and save them.
    """
    args = parse_args(argv)
    if args.pages is not None and args.pages < 1:
        raise SystemExit("--pages must be >= 1 when provided")
    if args.empty_stop < 0:
        raise SystemExit("--empty-stop must be >= 0")

    cfg = load_config(args.songs)

    conn = get_conn()
    crawl_id: str | None = None
    try:
        sync_songs_from_yaml(conn, cfg)
        if args.refresh:
            ensure_snapshot_tables(conn)
            crawl_id = start_crawl_run(conn, mode="refresh", notes="crawlindex --refresh")

        results: list[VariantResult] = []
        variants = conn.execute(
            "SELECT asset_id, song_id, variant_label FROM track_variants ORDER BY song_id, variant_label"
        ).fetchall()
        total = len(variants)

        for idx, (asset_id, song_id, label) in enumerate(variants, start=1):
            log(f"\n=== INDEX [{idx}/{total}] {song_id} / {label} ({asset_id}) ===")
            if args.refresh:
                result = index_variant_refresh(
                    conn,
                    asset_id=str(asset_id),
                    song_id=str(song_id),
                    label=str(label),
                    sleep_s=args.sleep,
                    max_pages=args.pages,
                    empty_stop=args.empty_stop,
                    crawl_id=str(crawl_id),
                )
            else:
                result = index_variant_full(conn, asset_id=str(asset_id), label=str(label), sleep_s=args.sleep)
            results.append(result)
            log(
                f"--- Asset [{idx}/{total}] done: pages {result.pages}, "
                f"seen {result.seen_items}, new {result.new_ids}, {result.stopped_reason}"
            )

        seen_rows_for_run = None
        if crawl_id is not None:
            finish_crawl_run(conn, crawl_id, status="done")
            seen_rows_for_run = conn.execute(
                "SELECT COUNT(*) FROM reel_seen WHERE crawl_id=?", (crawl_id,)
            ).fetchone()[0]

        print_summary(results, crawl_id=crawl_id, seen_rows_for_run=seen_rows_for_run)

        todo = conn.execute("SELECT COUNT(*) FROM reel_index WHERE details_done=0").fetchone()[0]
        log(f"\n>>> Stage B will be needed for {todo} reels with details_done=0.")
    except Exception:
        if crawl_id is not None:
            finish_crawl_run(conn, crawl_id, status="failed")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
