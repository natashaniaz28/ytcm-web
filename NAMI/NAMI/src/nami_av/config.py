"""
Paths and reproducibility helpers for AV.

Defaults mirror NAMI's layout (``data/corpus.db``, ``data/reels``) so the sidecar drops
straight into an existing checkout. Everything is overridable via :class:`AvConfig` so
tests can point at a temporary directory without touching the real corpus.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = "data/corpus.db"
DEFAULT_REELS_DIR = "data/reels"
DEFAULT_OUTPUT_DIR = "outputs/av"
DEFAULT_AUDIO_CACHE_DIR = "outputs/av/audio"
DEFAULT_ASSET_AUDIO_DIR = "data/asset_audio"


@dataclass(frozen=True)
class AvConfig:

    db_path: Path
    reels_dir: Path
    output_dir: Path
    audio_cache_dir: Path
    asset_audio_dir: Path

    @classmethod
    def create(
        cls,
        *,
        root: str | Path | None = None,
        db_path: str | Path | None = None,
        reels_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
        audio_cache_dir: str | Path | None = None,
        asset_audio_dir: str | Path | None = None,
    ) -> "AvConfig":
        base = Path(root) if root is not None else Path(".")
        return cls(
            db_path=Path(db_path) if db_path else base / DEFAULT_DB_PATH,
            reels_dir=Path(reels_dir) if reels_dir else base / DEFAULT_REELS_DIR,
            output_dir=Path(output_dir) if output_dir else base / DEFAULT_OUTPUT_DIR,
            audio_cache_dir=Path(audio_cache_dir) if audio_cache_dir
            else base / DEFAULT_AUDIO_CACHE_DIR,
            asset_audio_dir=Path(asset_audio_dir) if asset_audio_dir
            else base / DEFAULT_ASSET_AUDIO_DIR,
        )

    @property
    def data_dir(self) -> Path:
        return self.output_dir / "data"

    @property
    def figures_dir(self) -> Path:
        return self.output_dir / "figures"


def default_config() -> AvConfig:
    return AvConfig.create()


def param_hash(params: dict) -> str:
    blob = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
