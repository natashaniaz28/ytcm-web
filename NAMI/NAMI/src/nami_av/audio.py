"""
Audio extraction — pull a mono WAV out of a reel MP4 with ffmpeg.

This is the one place the sidecar shells out. ffmpeg is located on ``PATH`` first, then
via the optional ``imageio-ffmpeg`` wheel (part of the ``[av]`` extra) so the sidecar
works even without a system ffmpeg. The extracted WAV is a regenerable artifact and so
lives under ``outputs/`` (see config), not in ``data/``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_SR = 22050


def find_ffmpeg() -> str:
    """Return a usable ffmpeg executable path, or raise if none can be found."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover
        raise RuntimeError(
            "ffmpeg not found. Install a system ffmpeg or `pip install imageio-ffmpeg`."
        )


def _has_audio(path: Path) -> bool:
    """A previously-extracted file counts only if it exists and is non-empty.

    Mirrors NAMI's ``_have_local`` size check (a zero-byte file is treated as missing,
    so a half-written WAV is re-extracted rather than trusted).
    """
    return path.exists() and path.stat().st_size > 0


def extract_audio(
    src_video: str | Path,
    out_wav: str | Path,
    *,
    sr: int = DEFAULT_SR,
    mono: bool = True,
    overwrite: bool = False,
    ffmpeg: str | None = None,
) -> Path:
    """Extract audio from *src_video* to *out_wav* (PCM WAV), and return its path.

    Skips the work when *out_wav* already exists and is non-empty (unless *overwrite*),
    so a re-run is cheap and idempotent. Raises ``FileNotFoundError`` if the source is
    missing and ``RuntimeError`` if ffmpeg fails.
    """
    src = Path(src_video)
    out = Path(out_wav)
    if _has_audio(out) and not overwrite:
        return out
    if not src.exists():
        raise FileNotFoundError(f"source video not found: {src}")

    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg or find_ffmpeg(),
        "-y",
        "-loglevel", "error",
        "-i", str(src),
        "-vn",
        "-ac", "1" if mono else "2",
        "-ar", str(sr),
        "-f", "wav",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not _has_audio(out):
        raise RuntimeError(
            f"ffmpeg failed to extract audio from {src} (code {proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return out
