"""Matplotlib font helpers.

Keeps plots readable when labels contain Japanese text (Kanji/Kana). The helper
only references system fonts; it does not bundle or distribute font files.
"""
from __future__ import annotations

from matplotlib import font_manager as fm
import matplotlib.pyplot as plt

PREFERRED_SANS_FONTS = [
    "Hiragino Sans",
    "Hiragino Kaku Gothic ProN",
    "Hiragino Maru Gothic ProN",
    "Yu Gothic",
    "YuGothic",
    "AppleGothic",
    "Noto Sans CJK JP",
    "Noto Sans JP",
    "IPAexGothic",
    "IPAGothic",
    "Arial Unicode MS",
    "DejaVu Sans",
]


def available_font_families() -> set[str]:
    """Return installed Matplotlib font family names."""
    return {f.name for f in fm.fontManager.ttflist}


def choose_plot_fonts(preferred: list[str] | None = None) -> list[str]:
    """Return a fallback list of installed sans fonts, preserving preference."""
    installed = available_font_families()
    names = preferred or PREFERRED_SANS_FONTS
    chosen = [name for name in names if name in installed]
    if "DejaVu Sans" not in chosen:
        chosen.append("DejaVu Sans")
    return chosen


def configure_plot_fonts(preferred: list[str] | None = None) -> list[str]:
    """Configure Matplotlib globally for Japanese-capable sans-serif output."""
    chosen = choose_plot_fonts(preferred)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = chosen
    plt.rcParams["axes.unicode_minus"] = False
    return chosen
