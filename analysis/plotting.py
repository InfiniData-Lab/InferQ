"""Shared plotting primitives for the SIGMOD out-of-core figure scripts.

`expander_ooc_plot.py`, `ooc_inferq_plot.py` and `ooc_dynamic.py` each grew
their own copy of the same font pick, engine palette, byte-axis formatter,
figure writer and Spearman helper. They are collected here so a change to the
engine colours or the byte labels happens once.

Deliberately NOT shared: the ``plt.rcParams`` blocks and `ooc_dynamic`'s
engine palette. Those three scripts produce figures for different papers and
their styles genuinely differ (serif vs sans, grid on vs off, distinct engine
hexes). Unifying them would silently change published figures, so each script
keeps its own style block.
"""

from __future__ import annotations

import os

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

# ── Font ──────────────────────────────────────────────────────────────────────

SERIF_PREFERENCE = (
    "TeX Gyre Termes",
    "Times New Roman",
    "Liberation Serif",
    "DejaVu Serif",
)


def best_serif() -> str:
    """Return the best available serif family, so matplotlib never warns."""
    fm.fontManager.__init__()
    avail = {f.name for f in fm.fontManager.ttflist}
    for name in SERIF_PREFERENCE:
        if name in avail:
            return name
    return "serif"


# ── SIGMOD layout constants ───────────────────────────────────────────────────

W_FULL = 6.99  # full text width (in)
W_COL = 3.33   # single column width (in)
FS = 8.0       # base font
FSS = 7.0      # small
FST = 6.5      # tiny annotations


# ── Engine palette ────────────────────────────────────────────────────────────

ENGINES = ["postgres", "duckdb", "sqlite"]
ENG_COLOR = {"postgres": "#2166AC", "duckdb": "#CB4335", "sqlite": "#1A7A40"}
ENG_LABEL = {"postgres": "PostgreSQL", "duckdb": "DuckDB", "sqlite": "SQLite"}
ENG_MARK = {"postgres": "o", "duckdb": "s", "sqlite": "^"}


# ── Byte axis formatting ──────────────────────────────────────────────────────

def log_fmt(x, _=None) -> str:
    """Compact human-readable byte label for a log axis (one decimal on GB)."""
    if x <= 0:
        return "0"
    if x < 1e3:
        return f"{x:.0f} B"
    if x < 1e6:
        return f"{x / 1e3:.0f} KB"
    if x < 1e9:
        return f"{x / 1e6:.0f} MB"
    return f"{x / 1e9:.1f} GB"


def log_fmt_exact(x, _=None) -> str:
    """Byte label that drops the decimal when the value is a whole MB/GB.

    Used where explicit ticks land on round values (2 MB, not 2.0 MB).
    """
    if x <= 0:
        return "0"
    if x < 1e3:
        return f"{x:.0f} B"
    if x < 1e6:
        return f"{x / 1e3:.0f} KB"
    if x < 1e9:
        return f"{x / 1e6:.0f} MB" if (x / 1e6) == int(x / 1e6) else f"{x / 1e6:.1f} MB"
    return f"{x / 1e9:.0f} GB" if (x / 1e9) == int(x / 1e9) else f"{x / 1e9:.1f} GB"


def byte_formatter(exact: bool = False) -> ticker.FuncFormatter:
    """`log_fmt` (or `log_fmt_exact`) wrapped as a matplotlib formatter."""
    return ticker.FuncFormatter(log_fmt_exact if exact else log_fmt)


# ── Output ────────────────────────────────────────────────────────────────────

def save(fig, outdir: str, name: str, pad_inches: float | None = None) -> str:
    """Write `fig` to ``outdir/name``, close it, and report the path.

    `pad_inches` is left per-caller: the figure scripts were tuned with
    different padding and the value is visible in the published PDFs.
    """
    path = os.path.join(outdir, name)
    kwargs = {"bbox_inches": "tight"}
    if pad_inches is not None:
        kwargs["pad_inches"] = pad_inches
    fig.savefig(path, **kwargs)
    plt.close(fig)
    print(f"  saved -> {path}")
    return path


# ── Statistics ────────────────────────────────────────────────────────────────

def spearman(a, b) -> float:
    """Spearman rho over the pairwise-finite entries; NaN below 3 points."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 3:
        return np.nan
    return pd.Series(a[mask]).corr(pd.Series(b[mask]), method="spearman")
