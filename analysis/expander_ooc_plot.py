"""
Expander Out-of-Core — Spill & CTE Figures
===========================================
Three SIGMOD-ready figures from an expander spilling results CSV.

  fig1_cte_sizes.pdf       CTE sizes (largest & total) per engine x cap_gb.
                           Single-column width, 3 engine panels.
  fig2_spill_vs_qubits.pdf Spill vs num_qubits, one panel per engine,
                           marker shape = cap_gb. Single-column width.
  fig3_spill_vs_cte.pdf    Spill vs CTE — 3 rows (cap_gb) x 3 cols (engine).
                           Log-log, filled = largest CTE, open = total CTE.
                           Spearman rho per panel. This is the main figure.

Usage
-----
  python expander_ooc_plot.py \
      --results expander_spilling.csv \
      [--outdir expander_ooc]

Notes
-----
- Warmup rows are excluded automatically.
- spill_proxy_bytes is the spill metric (median across run_idx).
- SIGMOD two-column: full=6.99in, single-col=3.33in, >=8pt, pdf.fonttype=42
- Spill data range: ~672 KB – 3.8 GB (log10: 5.8 – 9.6)
- CTE  data range: ~100 KB – 3.6 MB (log10: 5.0 – 6.6)
"""

import argparse
import os
import warnings

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Font ──────────────────────────────────────────────────────────────────────
def _best_serif():
    fm.fontManager.__init__()
    avail = {f.name for f in fm.fontManager.ttflist}
    for n in ["TeX Gyre Termes", "Times New Roman", "Liberation Serif", "DejaVu Serif"]:
        if n in avail:
            return n
    return "serif"

_SERIF = _best_serif()

# ── SIGMOD layout constants ───────────────────────────────────────────────────
_W_FULL = 6.99
_W_COL  = 3.33
_FS     = 8.0
_FSS    = 7.0
_FST    = 6.5

plt.rcParams.update({
    "font.family":           _SERIF,
    "font.size":             _FS,
    "axes.titlesize":        _FSS,
    "axes.titleweight":      "bold",
    "axes.labelsize":        _FSS,
    "axes.linewidth":        0.55,
    "axes.spines.top":       False,
    "axes.spines.right":     False,
    "xtick.labelsize":       _FST,
    "ytick.labelsize":       _FST,
    "xtick.major.width":     0.55,
    "ytick.major.width":     0.55,
    "xtick.minor.width":     0.35,
    "ytick.minor.width":     0.35,
    "xtick.major.size":      3.0,
    "ytick.major.size":      3.0,
    "xtick.minor.size":      1.8,
    "ytick.minor.size":      1.8,
    "xtick.direction":       "out",
    "ytick.direction":       "out",
    "legend.fontsize":       _FST,
    "legend.title_fontsize": _FST,
    "legend.framealpha":     0.0,
    "legend.edgecolor":      "none",
    "legend.borderpad":      0.3,
    "legend.labelspacing":   0.18,
    "legend.handlelength":   1.0,
    "legend.handleheight":   0.8,
    "axes.grid":             False,   # we set grid selectively per axis
    "figure.dpi":            300,
    "savefig.dpi":           600,
    "pdf.fonttype":          42,
    "ps.fonttype":           42,
})

# ── Palettes ──────────────────────────────────────────────────────────────────
ENGINES   = ["postgres", "duckdb", "sqlite"]
ENG_COLOR = {"postgres": "#2166AC", "duckdb": "#CB4335", "sqlite": "#1A7A40"}
ENG_LABEL = {"postgres": "PostgreSQL", "duckdb": "DuckDB", "sqlite": "SQLite"}

CAP_MARKS = {4: "^", 8: "s", 16: "o"}
CAP_LABEL = {4: "4 GB", 8: "8 GB", 16: "16 GB"}

QUBIT_CMAP = plt.cm.Blues
ZERO_SENT  = 4e3   # 4 KB sentinel for zero-spill

# ── Fine-grained axis ticks ───────────────────────────────────────────────────
# Spill: 672 KB – 3.8 GB  → show every decade + 2x/5x intermediates
# We'll use explicit tick values for both spill and CTE axes so labels are
# human-readable at the right granularity.

# Bytes values for explicit major ticks (log spaced, human-readable)
_SPILL_TICKS = [
    1e5,   2e5,   5e5,           # 100 KB, 200 KB, 500 KB
    1e6,   2e6,   5e6,           # 1 MB, 2 MB, 5 MB
    1e7,   2e7,   5e7,           # 10 MB, 20 MB, 50 MB
    1e8,   2e8,   5e8,           # 100 MB, 200 MB, 500 MB
    1e9,   2e9,   5e9,           # 1 GB, 2 GB, 5 GB
]

_CTE_TICKS = [
    1e5,   2e5,   5e5,           # 100 KB, 200 KB, 500 KB
    1e6,   2e6,   4e6,           # 1 MB, 2 MB, 4 MB
]


def log_fmt(x, _):
    """Human-readable bytes label, compact for tight axes."""
    if x <= 0:    return "0"
    if x < 1e3:   return f"{x:.0f} B"
    if x < 1e6:   return f"{x/1e3:.0f} KB"
    if x < 1e9:   return f"{x/1e6:.0f} MB"  if (x/1e6) == int(x/1e6) else f"{x/1e6:.1f} MB"
    return                f"{x/1e9:.0f} GB"  if (x/1e9) == int(x/1e9) else f"{x/1e9:.1f} GB"


def _apply_spill_yaxis(ax, ticks=None):
    """Set log y-axis with fine-grained explicit ticks for spill."""
    ax.set_yscale("log")
    t = ticks if ticks is not None else _SPILL_TICKS
    ax.set_yticks(t)
    ax.set_yticklabels([log_fmt(v, None) for v in t], fontsize=_FST)
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True,  axis="y", lw=0.30, ls=":", color="0.85", zorder=0)
    ax.grid(False, axis="x")


def _apply_cte_xaxis(ax, ticks=None):
    """Set log x-axis with fine-grained explicit ticks for CTE size."""
    ax.set_xscale("log")
    t = ticks if ticks is not None else _CTE_TICKS
    ax.set_xticks(t)
    ax.set_xticklabels([log_fmt(v, None) for v in t], fontsize=_FST,
                       rotation=30, ha="right", rotation_mode="anchor")
    ax.xaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True, axis="x", lw=0.30, ls=":", color="0.85", zorder=0)


def _apply_cte_yaxis(ax, ticks=None):
    """Set log y-axis with fine-grained explicit ticks for CTE size."""
    ax.set_yscale("log")
    t = ticks if ticks is not None else _CTE_TICKS
    ax.set_yticks(t)
    ax.set_yticklabels([log_fmt(v, None) for v in t], fontsize=_FST)
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True,  axis="y", lw=0.30, ls=":", color="0.85", zorder=0)
    ax.grid(False, axis="x")


def save(fig, outdir, name):
    p = os.path.join(outdir, name)
    fig.savefig(p, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)
    print(f"  saved -> {p}")


def spearman(a, b):
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 3:
        return np.nan
    return pd.Series(a[mask]).corr(pd.Series(b[mask]), method="spearman")


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(results_path: str):
    df = pd.read_csv(results_path, low_memory=False)
    df["engine"] = df["engine"].astype(str).str.strip().str.lower()
    df["status"] = df["status"].astype(str).str.strip().str.lower()
    df = df[df["run_idx"].astype(str) != "warmup"]

    for c in ["spill_proxy_bytes", "wall_time_s",
              "largest_cte_bytes", "total_cte_bytes",
              "num_qubits", "cap_gb"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df[df["engine"].isin(ENGINES) & (df["status"] == "success")]

    pc = (df.groupby(["engine", "circuit_hash", "num_qubits", "cap_gb"])
            .agg(
                spill      =("spill_proxy_bytes", "median"),
                wall_time  =("wall_time_s",       "median"),
                total_cte  =("total_cte_bytes",   "median"),
                largest_cte=("largest_cte_bytes", "median"),
            )
            .reset_index())

    caps   = sorted(int(c) for c in pc["cap_gb"].dropna().unique())
    qubits = sorted(int(q) for q in pc["num_qubits"].dropna().unique())

    _print_summary(pc)
    return pc, caps, qubits


def _print_summary(pc):
    print(f"\n{'='*60}")
    g = pc.copy(); g["spill_gb"] = g["spill"] / 1e9
    print("Spill by engine x cap_gb (GB):")
    print(g.groupby(["engine", "cap_gb"])["spill_gb"]
           .agg(["min", "median", "max"]).round(3).to_string())
    print(f"\nnum_qubits: {sorted(pc['num_qubits'].unique())}")
    print(f"{'='*60}\n")


def _qubit_colors(qubits):
    n = len(qubits)
    return {q: QUBIT_CMAP(0.38 + 0.52 * i / max(n - 1, 1))
            for i, q in enumerate(qubits)}


# ── Fig 1 — CTE sizes per engine x cap ───────────────────────────────────────

def plot_cte_sizes(pc, caps, qubits, outdir):
    """
    Single-column (3.33in). 1 row x 3 engine panels.
    X = cap_gb. Filled circle = largest_cte, open square = total_cte.
    Colour = num_qubits (sequential blues). Fine-grained log y.
    """
    q_colors = _qubit_colors(qubits)
    np.random.seed(0)

    fig, axes = plt.subplots(1, 3, figsize=(_W_COL, 1.90), sharey=True,
                             gridspec_kw={"wspace": 0.06})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d = pc[pc["engine"] == eng]

        for ci, cap in enumerate(caps):
            dc = d[d["cap_gb"] == cap]
            if dc.empty:
                continue
            for _, row in dc.iterrows():
                qb  = int(row["num_qubits"])
                cc  = q_colors[qb]
                jit = np.random.uniform(-0.13, 0.13)
                xc  = ci + jit
                if np.isfinite(row["largest_cte"]) and row["largest_cte"] > 0:
                    ax.scatter(xc, row["largest_cte"],
                               color=cc, marker="o", s=11, alpha=0.88,
                               edgecolors="white", linewidths=0.3, zorder=5)
                if np.isfinite(row["total_cte"]) and row["total_cte"] > 0:
                    ax.scatter(xc, row["total_cte"],
                               color="none", marker="s", s=9, alpha=0.92,
                               edgecolors=cc, linewidths=0.75, zorder=4)

        ax.set_xticks(range(len(caps)))
        ax.set_xticklabels([f"{c} GB" for c in caps], fontsize=_FST)
        ax.set_xlim(-0.55, len(caps) - 0.45)
        _apply_cte_yaxis(ax)
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=5,
                     fontsize=_FSS, fontweight="bold")
        if col == 0:
            ax.set_ylabel("CTE size", fontsize=_FSS)
        else:
            ax.tick_params(labelleft=False)

    fig.text(0.57, 0.02, "Memory cap", ha="center", fontsize=_FSS)

    # ── Legend: two rows, left-anchored under the panels ─────────────────
    q_handles = [
        Line2D([0], [0], marker="o", color=q_colors[q], lw=0,
               ms=4, mew=0.3, mec="white", label=f"{q}q")
        for q in qubits
    ]
    type_handles = [
        Line2D([0], [0], marker="o", color="0.35", lw=0,
               ms=4, mew=0.3, mec="white", label="Largest"),
        Line2D([0], [0], marker="s", color="none", lw=0,
               ms=3.5, mew=0.75, mec="0.35", label="Total"),
    ]
    fig.legend(handles=q_handles,
               loc="lower left", bbox_to_anchor=(0.17, -0.06),
               ncol=len(qubits), handlelength=0.5,
               borderpad=0.2, labelspacing=0.12, columnspacing=0.45,
               fontsize=_FST, frameon=False)
    fig.legend(handles=type_handles,
               loc="lower right", bbox_to_anchor=(0.99, -0.06),
               ncol=2, handlelength=0.5,
               borderpad=0.2, labelspacing=0.12, columnspacing=0.5,
               fontsize=_FST, frameon=False)

    fig.subplots_adjust(left=0.20, right=0.99, top=0.88, bottom=0.28)
    save(fig, outdir, "fig1_cte_sizes.pdf")


# ── Fig 2 — Spill vs num_qubits ───────────────────────────────────────────────

def plot_spill_vs_qubits(pc, caps, qubits, outdir):
    """
    Single-column (3.33in). 1 row x 3 engine panels.
    X = num_qubits. Marker shape = cap_gb. Colour = engine.
    Fine-grained log y with 2x/5x intermediate ticks.
    Median tick per cap per qubit group.
    """
    np.random.seed(42)
    n_caps  = len(caps)
    offsets = np.linspace(-0.22, 0.22, n_caps) if n_caps > 1 else [0.0]

    # only ticks in the actual spill data range (~672 KB – 3.8 GB)
    spill_ticks = [5e5, 1e6, 2e6, 5e6, 1e7, 2e7, 5e7,
                   1e8, 2e8, 5e8, 1e9, 2e9, 5e9]

    fig, axes = plt.subplots(1, 3, figsize=(_W_COL, 1.90), sharey=True,
                             gridspec_kw={"wspace": 0.04})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d  = pc[pc["engine"] == eng]
        cc = ENG_COLOR[eng]

        for ci, cap in enumerate(caps):
            dc  = d[d["cap_gb"] == cap]
            mk  = CAP_MARKS[cap]
            off = offsets[ci]

            for qb in qubits:
                qd = dc[dc["num_qubits"] == qb]
                n  = len(qd)
                if n == 0:
                    continue
                jit  = np.random.uniform(-0.035, 0.035, n)
                xpos = qb + off + jit
                yv   = qd["spill"].values.copy()
                nz   = yv > 0
                zr   = ~nz

                if nz.any():
                    ax.scatter(xpos[nz], yv[nz],
                               color=cc, marker=mk, s=11, alpha=0.87,
                               edgecolors="white", linewidths=0.25, zorder=4)
                if zr.any():
                    ax.scatter(xpos[zr], np.full(zr.sum(), ZERO_SENT),
                               color=cc, marker=mk, s=11, alpha=0.87,
                               edgecolors=cc, facecolors="none",
                               linewidths=0.6, zorder=4)
                nz_vals = yv[nz]
                if len(nz_vals):
                    med = np.median(nz_vals)
                    ax.plot([qb + off - 0.07, qb + off + 0.07],
                            [med, med], color=cc, lw=1.3, zorder=5,
                            solid_capstyle="butt")

        _apply_spill_yaxis(ax, ticks=spill_ticks)
        ax.set_xticks(qubits)
        ax.set_xticklabels([str(q) for q in qubits], fontsize=_FST)
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=5,
                     fontsize=_FSS, fontweight="bold")
        if col == 0:
            ax.set_ylabel("Spill", fontsize=_FSS)
        else:
            ax.tick_params(labelleft=False)

    fig.text(0.57, 0.02, "Number of qubits", ha="center", fontsize=_FSS)

    cap_handles = [
        Line2D([0], [0], marker=CAP_MARKS[c], color="0.30", lw=0,
               ms=4.5, mew=0.3, mec="white", label=CAP_LABEL[c])
        for c in caps
    ]
    fig.legend(handles=cap_handles,
               loc="lower center", bbox_to_anchor=(0.57, -0.06),
               ncol=len(caps), handlelength=0.5,
               borderpad=0.2, labelspacing=0.12, columnspacing=0.55,
               fontsize=_FST, frameon=False)

    fig.subplots_adjust(left=0.20, right=0.99, top=0.88, bottom=0.28)
    save(fig, outdir, "fig2_spill_vs_qubits.pdf")


# ── Fig 3 — Spill vs CTE: 3 (cap) x 3 (engine) ──────────────────────────────

def plot_spill_vs_cte(pc, caps, qubits, outdir):
    """
    Main figure. Full text width (6.99in), squeezed row height.
    Rows = cap_gb (separate experiments), Cols = engine.
    Filled circle = largest_cte, open square = total_cte.
    Colour = num_qubits (sequential blues).
    Both axes use same byte-scale ticks (500 KB → 5 GB), no rotation.
    Spearman r per panel (bolder = stronger). Slope-1 guide. Shared x/y.
    """
    q_colors = _qubit_colors(qubits)
    n_q      = len(qubits)
    n_rows   = len(caps)

    # Compact 3×3 grid at single-column width (3.33in), readable fonts (~6.5pt).
    cte_ticks   = [2e5, 5e5, 1e6, 3e6]    # 200 KB, 500 KB, 1 MB, 3 MB
    spill_ticks = [1e6, 1e8, 1e9, 4e9]    # 1 MB, 100 MB, 1 GB, 4 GB

    # Slightly taller to accommodate larger fonts without crowding.
    _FW3 = _W_COL   # 3.33in
    _FH3 = 4.20     # panels ~0.85in wide × 0.85in tall with new margins

    fig, axes = plt.subplots(
        n_rows, 3,
        figsize=(_FW3, _FH3),
        sharex=True, sharey=True,
        gridspec_kw={"hspace": 0.10, "wspace": 0.10},
    )
    if n_rows == 1:
        axes = axes[np.newaxis, :]

    for row, cap in enumerate(caps):
        for col, eng in enumerate(ENGINES):
            ax = axes[row, col]
            d  = pc[(pc["engine"] == eng) & (pc["cap_gb"] == cap)].dropna(
                     subset=["largest_cte", "total_cte", "spill"])

            for _, r in d.iterrows():
                qb = int(r["num_qubits"])
                cc = q_colors[qb]
                sp = r["spill"]
                y  = sp if sp > 0 else ZERO_SENT

                if np.isfinite(r["largest_cte"]) and r["largest_cte"] > 0:
                    ax.scatter(r["largest_cte"], y,
                               color=cc, marker="o", s=11,
                               alpha=0.88 if sp > 0 else 0.45,
                               edgecolors="white", linewidths=0.22, zorder=5)

                if np.isfinite(r["total_cte"]) and r["total_cte"] > 0:
                    ax.scatter(r["total_cte"], y,
                               color="none", marker="s", s=8,
                               alpha=0.92 if sp > 0 else 0.40,
                               edgecolors=cc, linewidths=0.55, zorder=4)

            # slope-1 guide
            nz = d[d["spill"] > 0]
            if len(nz) >= 2:
                ratio = np.median(nz["spill"].values / nz["largest_cte"].values)
                xl = np.array([d["largest_cte"].min(), d["largest_cte"].max()])
                ax.plot(xl, ratio * xl,
                        color="0.65", lw=0.55, ls="--", zorder=1)

            # Spearman rhos
            r_lrg = spearman(d["largest_cte"].values, d["spill"].values)
            r_tot  = spearman(d["total_cte"].values,   d["spill"].values)
            win_lrg = (np.isfinite(r_lrg) and
                       (not np.isfinite(r_tot) or abs(r_lrg) >= abs(r_tot)))
            for i, (lbl, rv, bold) in enumerate([
                ("r(lrg)", r_lrg, win_lrg),
                ("r(tot)", r_tot, not win_lrg),
            ]):
                if np.isfinite(rv):
                    ax.annotate(
                        f"{lbl}={rv:+.2f}",
                        xy=(0.04, 0.98 - i * 0.14),
                        xycoords="axes fraction", ha="left", va="top",
                        fontsize=_FST, color="0.22",
                        fontweight="bold" if bold else "normal",
                    )

            # ── Axes ─────────────────────────────────────────────────────
            ax.set_yscale("log")
            ax.set_yticks(spill_ticks)
            ax.set_yticklabels([log_fmt(v, None) for v in spill_ticks],
                               fontsize=_FST)
            ax.yaxis.set_minor_locator(ticker.NullLocator())
            ax.grid(True,  axis="y", lw=0.25, ls=":", color="0.86", zorder=0)

            ax.set_xscale("log")
            ax.set_xticks(cte_ticks)
            ax.set_xticklabels([log_fmt(v, None) for v in cte_ticks],
                               fontsize=_FST, rotation=30,
                               ha="right", rotation_mode="anchor")
            ax.xaxis.set_minor_locator(ticker.NullLocator())
            ax.grid(True, axis="x", lw=0.25, ls=":", color="0.86", zorder=0)
            ax.tick_params(axis="both", length=2.0, width=0.45)

            if col != 0:
                ax.tick_params(labelleft=False)
            if row != n_rows - 1:
                ax.tick_params(labelbottom=False)

            if row == 0:
                ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng],
                             fontsize=_FSS, fontweight="bold", pad=3)

            if col == 0:
                ax.set_ylabel(f"{int(cap)} GB\nSpill",
                              fontsize=_FST, labelpad=2)

            if row == n_rows - 1:
                ax.set_xlabel("CTE size", fontsize=_FST, labelpad=1)

            print(f"  {eng} cap={int(cap)} GB: "
                  f"r(lrg)={r_lrg:+.3f}  r(tot)={r_tot:+.3f}")

    # ── Legend ────────────────────────────────────────────────────────────
    q_handles = [
        Line2D([0], [0], marker="o", color=q_colors[q], lw=0,
               ms=3.5, mew=0.22, mec="white", label=f"{q}q")
        for q in qubits
    ]
    type_handles = [
        Line2D([0], [0], marker="o", color="0.35", lw=0,
               ms=3.5, mew=0.22, mec="white", label="Largest"),
        Line2D([0], [0], marker="s", color="none", lw=0,
               ms=3.0, mew=0.55, mec="0.35", label="Total"),
        Line2D([0], [0], color="0.60", lw=0.65, ls="--", label="Slope-1"),
    ]
    fig.legend(handles=q_handles,
               loc="lower left", bbox_to_anchor=(0.19, 0.01),
               ncol=n_q, handlelength=0.40,
               borderpad=0.15, labelspacing=0.10, columnspacing=0.35,
               fontsize=_FST - 0.5, frameon=False)
    fig.legend(handles=type_handles,
               loc="lower right", bbox_to_anchor=(0.99, 0.01),
               ncol=3, handlelength=0.45,
               borderpad=0.15, labelspacing=0.10, columnspacing=0.40,
               fontsize=_FST - 0.5, frameon=False)

    fig.subplots_adjust(left=0.19, right=0.99, top=0.93, bottom=0.15)
    save(fig, outdir, "fig3_spill_vs_cte.pdf")


# ── Fig 4 — Wall-time: vs qubits and vs spill ────────────────────────────────

def plot_runtime(pc, caps, qubits, outdir):
    """
    Single-column width (3.33in).  1 row x 3 engine panels, two sub-figures:
      fig4a_walltime_vs_qubits.pdf  — wall time vs num_qubits, shape=cap_gb
      fig4b_walltime_vs_spill.pdf   — wall time vs spill (log-log), colour=engine
    Wall time range: 1.3s – 98s.  Spearman rho annotated on fig4b.
    """
    # ── 4a: wall time vs qubits ───────────────────────────────────────────
    np.random.seed(7)
    n_caps  = len(caps)
    offsets = np.linspace(-0.22, 0.22, n_caps) if n_caps > 1 else [0.0]
    wt_ticks = [2, 5, 10, 20, 50, 100]   # seconds, log scale

    fig, axes = plt.subplots(1, 3, figsize=(_W_COL, 1.90), sharey=True,
                             gridspec_kw={"wspace": 0.04})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d  = pc[pc["engine"] == eng].dropna(subset=["wall_time"])
        cc = ENG_COLOR[eng]

        for ci, cap in enumerate(caps):
            dc  = d[d["cap_gb"] == cap]
            mk  = CAP_MARKS[cap]
            off = offsets[ci]

            for qb in qubits:
                qd = dc[dc["num_qubits"] == qb]
                n  = len(qd)
                if n == 0:
                    continue
                jit  = np.random.uniform(-0.035, 0.035, n)
                xpos = qb + off + jit
                yv   = qd["wall_time"].values

                ax.scatter(xpos, yv, color=cc, marker=mk, s=11, alpha=0.87,
                           edgecolors="white", linewidths=0.25, zorder=4)
                med = np.median(yv)
                ax.plot([qb + off - 0.07, qb + off + 0.07],
                        [med, med], color=cc, lw=1.3, zorder=5,
                        solid_capstyle="butt")

        ax.set_yscale("log")
        ax.set_yticks(wt_ticks)
        ax.set_yticklabels([f"{v}s" for v in wt_ticks], fontsize=_FST)
        ax.yaxis.set_minor_locator(ticker.NullLocator())
        ax.grid(True, axis="y", lw=0.28, ls=":", color="0.86", zorder=0)
        ax.grid(False, axis="x")
        ax.set_xticks(qubits)
        ax.set_xticklabels([str(q) for q in qubits], fontsize=_FST)
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=5,
                     fontsize=_FSS, fontweight="bold")
        if col == 0:
            ax.set_ylabel("Wall time", fontsize=_FSS)
        else:
            ax.tick_params(labelleft=False)

    fig.text(0.57, 0.02, "Number of qubits", ha="center", fontsize=_FSS)

    cap_handles = [
        Line2D([0], [0], marker=CAP_MARKS[c], color="0.30", lw=0,
               ms=4.5, mew=0.3, mec="white", label=CAP_LABEL[c])
        for c in caps
    ]
    fig.legend(handles=cap_handles,
               loc="lower center", bbox_to_anchor=(0.57, -0.06),
               ncol=len(caps), handlelength=0.5,
               borderpad=0.2, labelspacing=0.12, columnspacing=0.55,
               fontsize=_FST, frameon=False)
    fig.subplots_adjust(left=0.20, right=0.99, top=0.88, bottom=0.28)
    save(fig, outdir, "fig4a_walltime_vs_qubits.pdf")

    # ── 4b: wall time vs spill (log-log, all caps together) ───────────────
    np.random.seed(11)
    sp_ticks = [1e6, 1e8, 1e9, 4e9]    # bytes: 1 MB, 100 MB, 1 GB, 4 GB

    fig, axes = plt.subplots(1, 3, figsize=(_W_COL, 1.90), sharey=True,
                             gridspec_kw={"wspace": 0.06})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d  = pc[pc["engine"] == eng].dropna(subset=["wall_time", "spill"])
        cc = ENG_COLOR[eng]

        for ci, cap in enumerate(caps):
            dc = d[d["cap_gb"] == cap]
            if dc.empty:
                continue
            mk = CAP_MARKS[cap]
            ax.scatter(dc["spill"], dc["wall_time"],
                       color=cc, marker=mk, s=11, alpha=0.85,
                       edgecolors="white", linewidths=0.25, zorder=4,
                       label=CAP_LABEL[cap] if col == 0 else None)

        r = spearman(d["spill"].values, d["wall_time"].values)
        if np.isfinite(r):
            ax.annotate(f"r={r:+.2f}", xy=(0.04, 0.97),
                        xycoords="axes fraction", ha="left", va="top",
                        fontsize=_FST, color="0.25", fontweight="bold")

        ax.set_xscale("log")
        ax.set_xticks(sp_ticks)
        ax.set_xticklabels([log_fmt(v, None) for v in sp_ticks],
                           fontsize=_FST, rotation=30,
                           ha="right", rotation_mode="anchor")
        ax.xaxis.set_minor_locator(ticker.NullLocator())
        ax.grid(True, axis="x", lw=0.28, ls=":", color="0.86", zorder=0)
        # set tight x limits to prevent excess whitespace
        d_all = pc[pc["engine"] == eng].dropna(subset=["spill"])
        ax.set_xlim(d_all["spill"].min() * 0.5, d_all["spill"].max() * 2.5)

        ax.set_yscale("log")
        ax.set_yticks(wt_ticks)
        ax.set_yticklabels([f"{v}s" for v in wt_ticks], fontsize=_FST)
        ax.yaxis.set_minor_locator(ticker.NullLocator())
        ax.grid(True, axis="y", lw=0.28, ls=":", color="0.86", zorder=0)

        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=5,
                     fontsize=_FSS, fontweight="bold")
        if col == 0:
            ax.set_ylabel("Wall time", fontsize=_FSS)
        else:
            ax.tick_params(labelleft=False)
        ax.set_xlabel("Spill", fontsize=_FSS, labelpad=6)

    cap_handles = [
        Line2D([0], [0], marker=CAP_MARKS[c], color="0.30", lw=0,
               ms=4.5, mew=0.3, mec="white", label=CAP_LABEL[c])
        for c in caps
    ]
    fig.legend(handles=cap_handles,
               loc="lower center", bbox_to_anchor=(0.57, -0.06),
               ncol=len(caps), handlelength=0.5,
               borderpad=0.2, labelspacing=0.12, columnspacing=0.55,
               fontsize=_FST, frameon=False)
    fig.subplots_adjust(left=0.20, right=0.99, top=0.88, bottom=0.35)
    save(fig, outdir, "fig4b_walltime_vs_spill.pdf")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Expander OOC spill figures")
    ap.add_argument("--results", default="expander_spilling.csv",
                    help="Expander spilling results CSV")
    ap.add_argument("--outdir",  default="expander_ooc",
                    help="Output directory (created if absent)")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    pc, caps, qubits = load_data(args.results)

    steps = [
        ("Fig 1  CTE sizes vs cap_gb",       lambda p, o: plot_cte_sizes(p, caps, qubits, o)),
        ("Fig 2  spill vs num_qubits",        lambda p, o: plot_spill_vs_qubits(p, caps, qubits, o)),
        ("Fig 3  spill vs CTE (3x3 grid)",   lambda p, o: plot_spill_vs_cte(p, caps, qubits, o)),
        ("Fig 4  wall-time (qubits + spill)", lambda p, o: plot_runtime(p, caps, qubits, o)),
    ]
    for label, fn in steps:
        print(label)
        try:
            fn(pc, args.outdir)
        except Exception:
            import traceback
            print(f"  [WARN] failed:\n{traceback.format_exc()}")

    print(f"\nDone -> {args.outdir}/")


if __name__ == "__main__":
    main()