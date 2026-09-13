"""
Expander Out-of-Core — Spill & CTE Figures (16 GB cap only)
============================================================
Produces the same four figures as the original script, but filtered
to cap_gb == 16 only.  Fig 3 becomes a single row (1×3) instead of
3×3.  All other layout logic is preserved.

  fig1_cte_sizes.pdf           CTE sizes (largest & total) per engine, 16 GB cap.
  fig2_spill_vs_qubits.pdf     Spill vs num_qubits, 16 GB cap only.
  fig3_spill_vs_cte.pdf        Spill vs CTE — 1 row x 3 cols (engine). Log-log.
  fig4a_walltime_vs_qubits.pdf Wall time vs qubits, 16 GB cap.
  fig4b_walltime_vs_spill.pdf  Wall time vs spill, 16 GB cap.

Usage
-----
  python expander_ooc_plot_16gb.py \
      --results expander_spilling.csv \
      [--outdir expander_ooc_16gb]
"""

import argparse
import os
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from experiments.analysis.plotting import ENG_COLOR, ENG_LABEL, ENGINES, best_serif, spearman
from experiments.analysis.plotting import FS as _FS
from experiments.analysis.plotting import FSS as _FSS
from experiments.analysis.plotting import FST as _FST
from experiments.analysis.plotting import W_COL as _W_COL
from experiments.analysis.plotting import log_fmt_exact as log_fmt
from experiments.analysis.plotting import save as _save

warnings.filterwarnings("ignore", category=FutureWarning)

CAP_FILTER = 16   # only this cap_gb value is used

_SERIF = best_serif()

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
    "axes.grid":             False,
    "figure.dpi":            300,
    "savefig.dpi":           600,
    "pdf.fonttype":          42,
    "ps.fonttype":           42,
})

# ── Palettes not shared with the other figure scripts ─────────────────────────
CAP_MARKS = {4: "^", 8: "s", 16: "o"}
CAP_LABEL = {4: "4 GB", 8: "8 GB", 16: "16 GB"}

QUBIT_CMAP = plt.cm.Blues
ZERO_SENT  = 4e3   # 4 KB sentinel for zero-spill

_SPILL_TICKS = [
    1e5,   2e5,   5e5,
    1e6,   2e6,   5e6,
    1e7,   2e7,   5e7,
    1e8,   2e8,   5e8,
    1e9,   2e9,   5e9,
]

_CTE_TICKS = [
    1e5,   2e5,   5e5,
    1e6,   2e6,   4e6,
]


def _apply_spill_yaxis(ax, ticks=None):
    ax.set_yscale("log")
    t = ticks if ticks is not None else _SPILL_TICKS
    ax.set_yticks(t)
    ax.set_yticklabels([log_fmt(v, None) for v in t], fontsize=_FST)
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True,  axis="y", lw=0.30, ls=":", color="0.85", zorder=0)
    ax.grid(False, axis="x")


def _apply_cte_xaxis(ax, ticks=None):
    ax.set_xscale("log")
    t = ticks if ticks is not None else _CTE_TICKS
    ax.set_xticks(t)
    ax.set_xticklabels([log_fmt(v, None) for v in t], fontsize=_FST,
                       rotation=30, ha="right", rotation_mode="anchor")
    ax.xaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True, axis="x", lw=0.30, ls=":", color="0.85", zorder=0)


def _apply_cte_yaxis(ax, ticks=None):
    ax.set_yscale("log")
    t = ticks if ticks is not None else _CTE_TICKS
    ax.set_yticks(t)
    ax.set_yticklabels([log_fmt(v, None) for v in t], fontsize=_FST)
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True,  axis="y", lw=0.30, ls=":", color="0.85", zorder=0)
    ax.grid(False, axis="x")


def save(fig, outdir, name):
    """These figures were tuned with 0.03in padding; keep it out of call sites."""
    return _save(fig, outdir, name, pad_inches=0.03)


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

    # ── Filter to 16 GB cap only ──────────────────────────────────────────
    df = df[df["cap_gb"] == CAP_FILTER]

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
    print(f"Filtered to cap_gb == {CAP_FILTER} GB only.")
    print("Spill by engine x cap_gb (GB):")
    print(g.groupby(["engine", "cap_gb"])["spill_gb"]
           .agg(["min", "median", "max"]).round(3).to_string())
    print(f"\nnum_qubits: {sorted(pc['num_qubits'].unique())}")
    print(f"{'='*60}\n")


def _qubit_colors(qubits):
    n = len(qubits)
    return {q: QUBIT_CMAP(0.38 + 0.52 * i / max(n - 1, 1))
            for i, q in enumerate(qubits)}


# ── Fig 1 — CTE sizes per engine (16 GB cap) ─────────────────────────────────

def plot_cte_sizes(pc, caps, qubits, outdir):
    """
    Single-column (3.33in). 1 row x 3 engine panels.
    X = cap_gb (only 16 GB). Filled circle = largest_cte, open square = total_cte.
    Colour = num_qubits (sequential blues).
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


# ── Fig 2 — Spill vs num_qubits (16 GB cap) ──────────────────────────────────

def plot_spill_vs_qubits(pc, caps, qubits, outdir):
    """
    Single-column (3.33in). 1 row x 3 engine panels.
    X = num_qubits. Marker shape = cap_gb (only 16 GB). Colour = engine.
    """
    np.random.seed(42)
    n_caps  = len(caps)
    offsets = np.linspace(-0.22, 0.22, n_caps) if n_caps > 1 else [0.0]

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


# ── Fig 3 — Spill vs CTE: 1 row x 3 cols (16 GB cap only) ───────────────────

def plot_spill_vs_cte(pc, caps, qubits, outdir):
    """
    Single row (1×3) at single-column width (3.33in).
    Only cap_gb == 16 GB. Cols = engine.
    Filled circle = largest_cte, open square = total_cte.
    Colour = num_qubits (sequential blues).
    Spearman r per panel. Slope-1 guide.
    """
    q_colors = _qubit_colors(qubits)
    n_q      = len(qubits)

    cte_ticks   = [2e5, 5e5, 1e6, 3e6]
    spill_ticks = [1e6, 1e8, 1e9, 4e9]

    # Taller figure: gives panels enough height so rotated x-tick labels,
    # the legend strip, and the r-value annotations never overlap.
    _FW3 = _W_COL   # 3.33 in  (SIGMOD single col)
    _FH3 = 1.50     # compact: panel height similar to original cropped image

    fig, axes = plt.subplots(
        1, 3,
        figsize=(_FW3, _FH3),
        sharex=True, sharey=True,
        gridspec_kw={"hspace": 0.10, "wspace": 0.12},
    )

    cap = CAP_FILTER
    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d = pc[(pc["engine"] == eng) & (pc["cap_gb"] == cap)].dropna(
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

        # Spearman rhos — placed at vertical mid-point of the axes (0.54 / 0.44)
        # so they sit in the empty middle band and never clash with the data
        # cluster (which lives near 1 MB at the bottom) or the title at the top.
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
                    xy=(0.05, 1.0 - i * 0.14),   # vertical mid, not top-left corner
                    xycoords="axes fraction", ha="left", va="top",
                    fontsize=_FST*0.8, color="0.22",
                    fontweight="bold" if bold else "normal",
                )

        # Axes
        ax.set_yscale("log")
        ax.set_yticks(spill_ticks)
        ax.set_yticklabels([log_fmt(v, None) for v in spill_ticks], fontsize=_FST)
        ax.yaxis.set_minor_locator(ticker.NullLocator())
        ax.grid(True,  axis="y", lw=0.25, ls=":", color="0.86", zorder=0)

        ax.set_xscale("log")
        ax.set_xticks(cte_ticks)
        ax.set_xticklabels([log_fmt(v, None) for v in cte_ticks],
                           fontsize=_FST, rotation=40,
                           ha="right", rotation_mode="anchor")
        ax.xaxis.set_minor_locator(ticker.NullLocator())
        ax.grid(True, axis="x", lw=0.25, ls=":", color="0.86", zorder=0)
        ax.tick_params(axis="both", length=2.0, width=0.45)

        if col != 0:
            ax.tick_params(labelleft=False)

        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng],
                     fontsize=_FSS, fontweight="bold", pad=3)

        if col == 0:
            ax.set_ylabel(f"{int(cap)} GB\nSpill", fontsize=_FST, labelpad=2)

        ax.set_xlabel("CTE size", fontsize=_FST, labelpad=2)

        print(f"  {eng} cap={int(cap)} GB: "
              f"r(lrg)={r_lrg:+.3f}  r(tot)={r_tot:+.3f}")

    # ── Legend — single centred row below the panels in reserved white space ──
    # Split into two fig.legend calls so qubit colours sit left and
    # marker-type / slope sit right, both well clear of the x-axis labels.
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
    # bottom=0.30 reserves enough canvas for rotated x-tick labels,
    # the "CTE size" axis label, and one legend row — all cleanly separated.
    fig.subplots_adjust(left=0.19, right=0.99, top=0.91, bottom=0.44)

    # bbox_to_anchor y=-0.06 puts both legend groups just below the figure bottom,
    # so they never overlap the axis labels.
    fig.legend(handles=q_handles,
               loc="lower center", bbox_to_anchor=(0.35, -0.06),
               ncol=n_q, handlelength=0.40,
               borderpad=0.15, labelspacing=0.10, columnspacing=0.30,
               fontsize=_FST - 0.5, frameon=False)
    fig.legend(handles=type_handles,
               loc="lower center", bbox_to_anchor=(0.78, -0.06),
               ncol=3, handlelength=0.45,
               borderpad=0.15, labelspacing=0.10, columnspacing=0.35,
               fontsize=_FST - 0.5, frameon=False)

    save(fig, outdir, "fig3_spill_vs_cte.pdf")


# ── Fig 4 — Wall-time (16 GB cap only) ───────────────────────────────────────

def plot_runtime(pc, qubits, outdir):
    """
    Single-column width (3.33in). Squeezed to match CTE/spill figure height.
    16 GB cap only.

    fig4a_walltime_vs_qubits.pdf  — grouped bar chart: median time per
                                    (engine, num_qubits). Error bars = IQR.
    fig4b_walltime_vs_spill.pdf   — time vs spill (log-log), one panel,
                                    engines by colour. Spearman rho per engine.
    """
    TARGET_CAP = 16
    pc_16 = pc[pc["cap_gb"] == TARGET_CAP]

    wt_ticks = [2, 5, 10, 20, 50, 100]   # seconds, log scale

    eng_handles = [
        Line2D([0], [0], marker="s", color=ENG_COLOR[e], lw=0,
               ms=5, mec="white", mew=0.3, label=ENG_LABEL[e])
        for e in ENGINES
    ]

    # ── 4a: grouped bar chart ─────────────────────────────────────────────
    n_eng         = len(ENGINES)
    n_qubits      = len(qubits)
    bar_w         = 0.22
    group_centres = np.arange(n_qubits)
    bar_offsets   = np.linspace(-(n_eng - 1) / 2, (n_eng - 1) / 2, n_eng) * bar_w

    fig, ax = plt.subplots(figsize=(_W_COL, 1.90))   # squeezed

    for ei, eng in enumerate(ENGINES):
        d   = pc_16[pc_16["engine"] == eng].dropna(subset=["wall_time"])
        cc  = ENG_COLOR[eng]
        off = bar_offsets[ei]

        medians, q25s, q75s = [], [], []
        for qb in qubits:
            vals = d[d["num_qubits"] == qb]["wall_time"].values
            if len(vals):
                medians.append(np.median(vals))
                q25s.append(np.percentile(vals, 25))
                q75s.append(np.percentile(vals, 75))
            else:
                medians.append(np.nan)
                q25s.append(np.nan)
                q75s.append(np.nan)

        medians = np.array(medians)
        q25s    = np.array(q25s)
        q75s    = np.array(q75s)
        xpos    = group_centres + off

        ax.bar(xpos, medians, width=bar_w * 0.88,
               color=cc, alpha=0.85, zorder=3, label=ENG_LABEL[eng])

        yerr_lo = np.where(np.isfinite(medians), medians - q25s, 0)
        yerr_hi = np.where(np.isfinite(medians), q75s - medians, 0)
        ax.errorbar(xpos, medians, yerr=[yerr_lo, yerr_hi],
                    fmt="none", ecolor="0.25", elinewidth=0.7,
                    capsize=2.0, capthick=0.7, zorder=4)

    ax.set_yscale("log")
    ax.set_yticks(wt_ticks)
    ax.set_yticklabels([str(v) for v in wt_ticks], fontsize=_FST)
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True,  axis="y", lw=0.28, ls=":", color="0.86", zorder=0)
    ax.grid(False, axis="x")
    ax.set_xticks(group_centres)
    ax.set_xticklabels([str(q) for q in qubits], fontsize=_FST)
    ax.set_xlabel("Number of qubits", fontsize=_FSS)
    ax.set_ylabel("Time (s)", fontsize=_FSS)
    ax.set_title(f"Runtime Performance ({CAP_LABEL[TARGET_CAP]})",
                 fontsize=_FSS, fontweight="bold", pad=4)
    ax.legend(handles=eng_handles, loc="upper left", fontsize=_FST,
              frameon=False, borderpad=0.2, labelspacing=0.2, handletextpad=0.3)

    fig.subplots_adjust(left=0.20, right=0.99, top=0.88, bottom=0.28)
    save(fig, outdir, "fig4a_walltime_vs_qubits.pdf")

    # ── 4b: time vs spill ─────────────────────────────────────────────────
    np.random.seed(11)
    sp_ticks = [1e6, 1e8, 1e9, 4e9]

    fig, ax = plt.subplots(figsize=(_W_COL, 1.90))   # squeezed

    rho_y_positions = [0.97, 0.87, 0.77]

    for ei, eng in enumerate(ENGINES):
        d  = pc_16[pc_16["engine"] == eng].dropna(subset=["wall_time", "spill"])
        if d.empty:
            continue
        cc = ENG_COLOR[eng]

        ax.scatter(d["spill"], d["wall_time"],
                   color=cc, marker="o", s=11, alpha=0.85,
                   edgecolors="white", linewidths=0.25, zorder=4)

        r = spearman(d["spill"].values, d["wall_time"].values)
        if np.isfinite(r):
            ax.annotate(f"{ENG_LABEL[eng]}: r={r:+.2f}",
                        xy=(0.04, rho_y_positions[ei]),
                        xycoords="axes fraction", ha="left", va="top",
                        fontsize=_FST, color=cc, fontweight="bold")

    ax.set_xscale("log")
    ax.set_xticks(sp_ticks)
    ax.set_xticklabels([log_fmt(v, None) for v in sp_ticks],
                       fontsize=_FST, rotation=30,
                       ha="right", rotation_mode="anchor")
    ax.xaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True, axis="x", lw=0.28, ls=":", color="0.86", zorder=0)

    spill_vals = pc_16["spill"].dropna()
    if not spill_vals.empty:
        ax.set_xlim(spill_vals.min() * 0.5, spill_vals.max() * 2.5)

    ax.set_yscale("log")
    ax.set_yticks(wt_ticks)
    ax.set_yticklabels([str(v) for v in wt_ticks], fontsize=_FST)
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True, axis="y", lw=0.28, ls=":", color="0.86", zorder=0)
    ax.set_ylabel("Time (s)", fontsize=_FSS)
    ax.set_xlabel("Spill", fontsize=_FSS, labelpad=4)
    ax.set_title(f"Spill ({CAP_LABEL[TARGET_CAP]})",
                 fontsize=_FSS, fontweight="bold", pad=4)
    ax.legend(handles=eng_handles, loc="lower right", fontsize=_FST,
              frameon=False, borderpad=0.2, labelspacing=0.2, handletextpad=0.3)

    fig.subplots_adjust(left=0.20, right=0.99, top=0.88, bottom=0.32)
    save(fig, outdir, "fig4b_walltime_vs_spill.pdf")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Expander OOC spill figures (16 GB cap only)")
    ap.add_argument("--results", default="expander_spilling.csv",
                    help="Expander spilling results CSV")
    ap.add_argument("--outdir",  default="expander_ooc_16gb",
                    help="Output directory (created if absent)")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    pc, caps, qubits = load_data(args.results)

    steps = [
        ("Fig 1  CTE sizes (16 GB cap)",         lambda p, o: plot_cte_sizes(p, caps, qubits, o)),
        ("Fig 2  spill vs num_qubits (16 GB)",    lambda p, o: plot_spill_vs_qubits(p, caps, qubits, o)),
        ("Fig 3  spill vs CTE (1×3, 16 GB)",      lambda p, o: plot_spill_vs_cte(p, caps, qubits, o)),
        ("Fig 4  wall-time (qubits + spill)",      lambda p, o: plot_runtime(p, qubits, o)),
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