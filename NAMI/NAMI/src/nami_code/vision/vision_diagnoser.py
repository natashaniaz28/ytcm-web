"""
Inspect a vision backend's raw per-category output for a few reels.

Read-only diagnostic helper: it never writes to the database. It routes through
tag_vision.get_model(), so it works with any backend — the StubModel (offline, no
GPU/network), the legacy CLIP VisionModel, or the Gemini VLM — and reads the same
media the tagger does (the reel MP4, thumbnail fallback). The schema (dimensions,
categories, descriptions) is loaded from config/schema.yaml.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from nami_code.vision import tag_vision as T


def diagnose(
    db_path: str = "data/corpus.db",
    n: int = 5,
    model_name: str | None = None,
    stub: bool = False,
    media_dir: str | Path | None = None,
) -> None:
    """
    Print each reel's per-dimension (category, confidence) picks for up to *n*
    reels. Does not write to the database.
    """

    schema = T.load_schema()
    if not schema.get("dimensions"):
        print("No dimensions configured in schema.yaml.")
        return

    if media_dir is not None:
        T.MEDIA_DIR = Path(media_dir)
        T.IMG_DIR = Path(media_dir)

    if model_name:
        T.MODEL_NAME = model_name

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT reel_pk, caption_text FROM reels LIMIT ?", (n,)).fetchall()
    finally:
        conn.close()

    model = T.get_model(stub, T.MODEL_NAME)

    for pk, caption in rows:
        media = T.local_media(pk)
        if not media:
            print(f"\n[{pk}] no local media; skipped")
            continue

        print(f"\n=== Reel {pk} ===")
        print("Caption:", (caption or "")[:70])
        print("Media:  ", media)

        results = model.classify(media, schema) or {}
        for dim in schema.get("dimensions", {}):
            picks = sorted(results.get(dim, []), key=lambda cp: -cp[1])
            if picks:
                print(f"  {dim:10s}:", ", ".join(f"{c}={s:.3f}" for c, s in picks))
            else:
                print(f"  {dim:10s}: (none)")


def main() -> None:
    """
    Read the command-line options and print a few reels' raw category scores.
    """
    parser = argparse.ArgumentParser(description="Inspect raw vision backend output for a few reels.")
    parser.add_argument("--db", default="data/corpus.db", help="Path to SQLite database")
    parser.add_argument("--limit", type=int, default=5, help="Number of reels to inspect")
    parser.add_argument("--model", default=None, help="Backend model id (gemini*/qwen*/CLIP)")
    parser.add_argument("--stub", action="store_true", help="Use the offline StubModel")
    parser.add_argument("--media-dir", default=None, help="Directory holding reel media")
    args = parser.parse_args()
    diagnose(db_path=args.db, n=args.limit, model_name=args.model,
             stub=args.stub, media_dir=args.media_dir)


if __name__ == "__main__":
    main()
