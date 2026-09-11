"""
Out-of-Core Inference — Spill & CTE Behaviour  (v5)
====================================================
SIGMOD-ready figures. Redesigned after inspecting actual data:

KEY INSIGHT: The 'sparse' bin (density~0) has near-zero entropy — these
are trivial circuits that produce tiny CTEs and zero/minimal spill.
'Medium' and 'dense' bins both contain high-entropy circuits and dominate
spill. The CTE size is the mechanistic link: large CTEs overflow the
memory budget and materialise as disk spill.

FIGURE GUIDE
  fig1_coverage.pdf        Sample: density & entropy per qubit group
  fig2_spill_vs_qubits.pdf Spill per circuit vs num_qubits — jittered
                           dots by engine, coloured by density bin
  fig3_spill_vs_entropy.pdf Spill vs entropy — scatter per engine,
                            coloured by density bin (continuous x)
  fig4_spill_vs_density.pdf Spill vs density — scatter, log y
                            (no connecting lines: many points share x=1.0)
  fig5_cte_vs_spill.pdf    CTE vs spill — log-log scatter, 2 rows ×
                            3 engine panels: top = largest CTE, bottom =
                            total CTE.  Spearman rho per panel; slope-1
                            guide.  Lets you compare which CTE metric
                            is the stronger spill predictor.
  fig6_cte_vs_entropy.pdf  CTE vs entropy — scatter, log y, per engine
  fig7_cte_vs_density.pdf  CTE vs density — scatter, log y, per engine
  fig8_walltime_vs_spill.pdf Wall time vs spill — log-log, per engine

Usage
-----
  python ooc_inferq_plot.py \
      --results ooc_sample_results_final.csv \
      --sampled new_sampled_output.csv \
      [--outdir ooc_figures]

Notes
-----
- density = statevector_saved_sparsity  (low=sparse, high=dense)
- SIGMOD two-column: 6.99in, >=8pt, TeX Gyre Termes, pdf.fonttype=42
"""

import argparse, os, warnings
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D
import numpy as np
import pandas as pd

# `plotting` is a sibling module: these scripts run as `python analysis/<name>.py`.
# The relative form is the fallback for when analysis/ is imported as a package.
try:
    from plotting import (
        ENG_COLOR, ENG_LABEL, ENG_MARK, ENGINES,
        best_serif, byte_formatter, log_fmt, spearman,
    )
    from plotting import FS as _FS
    from plotting import FSS as _FSS
    from plotting import FST as _FST
    from plotting import W_FULL as _W
    from plotting import save as _save
except ImportError:  # analysis/ imported as a package
    from .plotting import (
        ENG_COLOR, ENG_LABEL, ENG_MARK, ENGINES,
        best_serif, byte_formatter, log_fmt, spearman,
    )
    from .plotting import FS as _FS
    from .plotting import FSS as _FSS
    from .plotting import FST as _FST
    from .plotting import W_FULL as _W
    from .plotting import save as _save

warnings.filterwarnings("ignore", category=FutureWarning)

_SERIF = best_serif()

plt.rcParams.update({
    "font.family":        _SERIF,
    "font.size":          _FS,
    "axes.titlesize":     _FS,
    "axes.titleweight":   "bold",
    "axes.labelsize":     _FS,
    "axes.linewidth":     0.55,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
    "xtick.labelsize":    _FSS,
    "ytick.labelsize":    _FSS,
    "xtick.major.width":  0.55,
    "ytick.major.width":  0.55,
    "xtick.major.size":   3.0,
    "ytick.major.size":   3.0,
    "xtick.direction":    "out",
    "ytick.direction":    "out",
    "legend.fontsize":    _FSS,
    "legend.title_fontsize": _FSS,
    "legend.framealpha":  0.92,
    "legend.edgecolor":   "0.75",
    "legend.borderpad":   0.4,
    "legend.labelspacing":0.25,
    "legend.handlelength":1.4,
    "axes.grid":          True,
    "grid.color":         "0.90",
    "grid.linewidth":     0.35,
    "grid.linestyle":     "--",
    "figure.dpi":         300,
    "savefig.dpi":        600,
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
})

# ── Palettes unique to this script ────────────────────────────────────────────
# Bin colours: blue=sparse, orange=Medium, red=dense
BIN_COLOR = {"sparse": "#4393C3", "Medium": "#F4A582", "dense": "#B2182B"}
BIN_MARK  = {"sparse": "o",       "Medium": "s",       "dense": "^"}
BIN_LABEL = {
    "sparse": "Sparse  [0, 0.33)",
    "Medium":  "Medium   [0.33, 0.67)",
    "dense":  "Dense   [0.67, 1.0]",
}
BINS = ["sparse", "Medium", "dense"]

QUBIT_COLORS = {20:"#92C5DE", 21:"#4393C3", 22:"#2166AC", 23:"#053061"}

ZERO_SENT = 0   # 4 KB sentinel for zero-spill on log y


# ── Helpers ───────────────────────────────────────────────────────────────────

def set_log_y(ax):
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(ticker.LogLocator(base=10, numticks=20))
    ax.yaxis.set_major_formatter(byte_formatter())
    ax.yaxis.set_minor_locator(ticker.NullLocator())
    # only horizontal grid lines — clean, no vertical clutter
    ax.grid(True,  axis="y", lw=0.35, ls="--", color="0.88", zorder=0)
    ax.grid(False, axis="x")

def set_log_x_bytes(ax):
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(byte_formatter())
    ax.xaxis.set_minor_locator(ticker.NullLocator())
    ax.grid(True, axis="x", lw=0.35, ls="--", color="0.88", zorder=0)

def save(fig, outdir, name):
    """These figures were tuned with 0.02in padding; keep it out of call sites."""
    return _save(fig, outdir, name, pad_inches=0.02)

def bin_legend(ax, loc="best", outside=False):
    handles = [
        Line2D([0],[0], marker=BIN_MARK[b], color=BIN_COLOR[b],
               lw=0, ms=5, mew=0.4, mec="white", label=BIN_LABEL[b])
        for b in BINS
    ]
    kw = dict(handles=handles, title="Density bin",
              handlelength=0.6, borderpad=0.45, labelspacing=0.22)
    if outside:
        ax.legend(**kw, loc="upper left",
                  bbox_to_anchor=(0, -0.32), ncol=3,
                  columnspacing=1.0)
    else:
        ax.legend(**kw, loc=loc)

def annotate_rho(ax, rho, pos=(0.97, 0.05)):
    if np.isfinite(rho):
        ax.annotate(f"ρ = {rho:+.2f}", xy=pos,
                    xycoords="axes fraction", ha="right",
                    fontsize=_FST, color="0.38")


# ── Scatter helper: plot per bin, filled + open-sentinel for zero ─────────────

def scatter_by_bin(ax, d, xcol, ycol, ms=22, alpha=0.80,
                   zero_sentinel=ZERO_SENT, annotate_n1=False):
    """
    Scatter points coloured by density bin.
    Zero/NaN y → open marker at zero_sentinel on log axis.
    No connecting lines (avoids spaghetti when x-values coincide).
    """
    for bname in BINS:
        bc = BIN_COLOR[bname]
        mk = BIN_MARK[bname]
        bd = d[d["sp_bin"] == bname].dropna(subset=[xcol])
        if bd.empty:
            continue
        nz = bd[bd[ycol] > 0]
        zr = bd[bd[ycol] == 0]
        if len(nz):
            ax.scatter(nz[xcol], nz[ycol], color=bc, marker=mk,
                       s=ms, alpha=alpha, edgecolors="white",
                       linewidths=0.4, zorder=4)
        if len(zr):
            ax.scatter(zr[xcol], np.full(len(zr), zero_sentinel),
                       color=bc, marker=mk, s=ms, alpha=alpha,
                       edgecolors=bc, facecolors="none",
                       linewidths=0.8, zorder=4)


# ── Data loading ──────────────────────────────────────────────────────────────

def load_data(results_path, sampled_path):
    res = pd.read_csv(results_path, low_memory=False)
    smp = pd.read_csv(sampled_path, low_memory=False).rename(
          columns={"RowKey": "circuit_hash"})

    res["engine"] = res["engine"].str.strip().str.lower()
    res["status"] = res["status"].str.strip().str.lower()
    res = res[res["run_idx"].astype(str) != "warmup"]

    for c in ["spill_proxy_bytes","wall_time_s",
              "largest_cte_bytes","total_cte_bytes","num_qubits"]:
        if c in res.columns:
            res[c] = pd.to_numeric(res[c], errors="coerce")

    res = res[res["engine"].isin(ENGINES) & (res["status"] == "success")]

    pc = (res.groupby(["engine","circuit_hash","num_qubits"])
            .agg(spill      =("spill_proxy_bytes","median"),
                 wall_time  =("wall_time_s","median"),
                 total_cte  =("total_cte_bytes","median"),
                 largest_cte=("largest_cte_bytes","median"))
            .reset_index())

    smp["density"]    = pd.to_numeric(smp["statevector_saved_sparsity"],  errors="coerce")
    smp["entropy"]    = pd.to_numeric(smp["statevector_shannon_entropy"],  errors="coerce")
    smp["num_qubits"] = pd.to_numeric(smp["num_qubits"], errors="coerce")

    pc = pc.merge(smp[["circuit_hash","num_qubits","density","entropy"]],
                  on=["circuit_hash","num_qubits"], how="left")

    pc["sp_bin"] = pd.cut(pc["density"], bins=[0,0.33,0.67,1.01],
                           labels=["sparse","Medium","dense"],
                           include_lowest=True)
    _print_summary(pc)
    return pc


def _print_summary(pc):
    print(f"\n{'='*60}")
    g = pc.copy(); g["spill_gb"] = g["spill"]/1e9
    print("Spill by engine (GB):")
    print(g.groupby("engine")["spill_gb"]
           .agg(["min","median","max"]).round(3).to_string())
    print("\nCircuits per density bin:")
    print(pc[["circuit_hash","sp_bin"]].drop_duplicates()
           ["sp_bin"].value_counts().sort_index().to_string())
    print("\nSpearman(spill, predictor) — postgres:")
    sub = pc[pc["engine"]=="postgres"]
    for m in ["density","entropy","num_qubits","largest_cte","total_cte"]:
        r = spearman(sub[m].values, sub["spill"].values)
        print(f"  rho(spill, {m:12s}) = {r:+.3f}")
    # Direct comparison of the two CTE predictors
    r_lrg = spearman(sub["largest_cte"].values, sub["spill"].values)
    r_tot = spearman(sub["total_cte"].values,   sub["spill"].values)
    winner = "largest_cte" if abs(r_lrg) >= abs(r_tot) else "total_cte"
    print(f"\n  → stronger CTE predictor (postgres): {winner}"
          f"  (|ρ|={max(abs(r_lrg),abs(r_tot)):.3f} vs {min(abs(r_lrg),abs(r_tot)):.3f})")
    print("\nSpearman(largest_cte, predictor) — postgres:")
    for m in ["density","entropy","num_qubits"]:
        r = spearman(sub[m].values, sub["largest_cte"].values)
        print(f"  rho(cte,   {m:12s}) = {r:+.3f}")
    print(f"{'='*60}\n")


# ── F1 — Coverage ─────────────────────────────────────────────────────────────

def plot_coverage(pc, outdir):
    circ = (pc[["circuit_hash","num_qubits","density","entropy"]]
            .drop_duplicates("circuit_hash")
            .sort_values(["num_qubits","density"]))
    qubits = sorted(circ["num_qubits"].dropna().unique())

    fig, axes = plt.subplots(2, len(qubits), figsize=(_W, 3.2),
                              gridspec_kw={"hspace":0.50,"wspace":0.28})
    if len(qubits) == 1: axes = axes.reshape(2,1)

    for col, qb in enumerate(qubits):
        sub = circ[circ["num_qubits"]==qb].reset_index(drop=True)
        n   = len(sub)
        jit = (np.arange(n)-(n-1)/2)*0.07
        c   = QUBIT_COLORS[int(qb)]

        for row, (ycol, ylim, ylabel) in enumerate([
            ("density", (-0.06,1.09), "Density\n(low=sparse)"),
            ("entropy", (-0.5, qb+1.8), "Entropy (bits)"),
        ]):
            ax = axes[row, col]
            vals = sub[ycol]
            ax.scatter(jit, vals, s=38, color=c,
                       edgecolors="white", linewidths=0.6, zorder=4)
            if n > 1:
                ax.plot([0,0],[vals.min(),vals.max()],
                        color=c, lw=0.9, alpha=0.35, zorder=2)
            if ycol == "entropy":
                ax.axhline(qb, color="0.60", lw=0.7, ls="--", zorder=1)
            ax.set_xlim(-0.6,0.6); ax.set_ylim(*ylim)
            ax.set_xticks([])
            ax.grid(axis="y", lw=0.3, ls="--", color="0.88")
            ax.grid(axis="x", visible=False)
            if row == 0:
                ax.set_title(f"{int(qb)}q (n={n})", fontsize=_FS, fontweight="bold")
            if col == 0:
                ax.set_ylabel(ylabel, fontsize=_FS)

    fig.suptitle(
        "Sample coverage: density and entropy per qubit group"
        "  (dashed = entropy max = num_qubits)",
        fontsize=_FS, y=1.01)
    save(fig, outdir, "fig1_coverage.pdf")


# ── F2 — Spill vs num_qubits: jittered per-circuit dots ──────────────────────

def plot_spill_vs_qubits(pc, outdir):
    """
    One panel per engine.  X = num_qubits (integer).
    Single-column SIGMOD layout: 3.33" wide x 1.85" tall.
    """
    _WC = 3.33   # single SIGMOD column width
    qubits = sorted(pc["num_qubits"].dropna().unique())
    bin_offsets = {"sparse": -0.22, "Medium": 0.0, "dense": 0.22}
    np.random.seed(42)

    fig, axes = plt.subplots(1, 3, figsize=(_WC, 1.85), sharey=True,
                              gridspec_kw={"wspace": 0.04})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d = pc[pc["engine"]==eng]

        for bname in BINS:
            bc  = BIN_COLOR[bname]
            mk  = BIN_MARK[bname]
            bd  = d[d["sp_bin"]==bname]
            off = bin_offsets[bname]

            for qb in qubits:
                qd  = bd[bd["num_qubits"]==qb]
                n   = len(qd)
                if n == 0: continue
                jit = np.random.uniform(-0.06, 0.06, n)
                xpos = qb + off + jit
                yvals = qd["spill"].values.copy()
                nz_mask = yvals > 0
                zr_mask = ~nz_mask

                if nz_mask.any():
                    ax.scatter(xpos[nz_mask], yvals[nz_mask],
                               color=bc, marker=mk, s=10, alpha=0.85,
                               edgecolors="white", linewidths=0.25, zorder=4)
                if zr_mask.any():
                    ax.scatter(xpos[zr_mask], np.full(zr_mask.sum(), ZERO_SENT),
                               color=bc, marker=mk, s=10, alpha=0.85,
                               edgecolors=bc, facecolors="none",
                               linewidths=0.7, zorder=4)

                nz_vals = yvals[nz_mask]
                if len(nz_vals):
                    med = np.median(nz_vals)
                    ax.plot([qb+off-0.09, qb+off+0.09], [med, med],
                            color=bc, lw=1.4, zorder=5, solid_capstyle="butt")

        set_log_y(ax)
        ax.set_xticks(qubits)
        ax.set_xticklabels([str(int(q)) for q in qubits], fontsize=_FST)
        ax.tick_params(axis="y", labelsize=_FST)
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=2,
                     fontsize=_FSS, fontweight="bold")
        if col == 0:
            ax.set_ylabel("Spill (log scale)", fontsize=_FSS)
        else:
            ax.tick_params(labelleft=False)

    # shared x-label centred under middle panel
    fig.text(0.5, 0.1, "Number of qubits", ha="center", va="bottom",
             fontsize=_FSS)

    # single-line legend below, no frame, no title
    leg_handles = [
        Line2D([0],[0], marker=BIN_MARK[b], color=BIN_COLOR[b],
               lw=0, ms=4, mew=0.3, mec="white", label=BIN_LABEL[b])
        for b in BINS
    ]
    fig.legend(handles=leg_handles, loc="lower center",
               bbox_to_anchor=(0.5, -0.04), ncol=3,
               handlelength=0.5, borderpad=0.3, labelspacing=0.15,
               columnspacing=0.6, fontsize=_FST, frameon=False)

    fig.subplots_adjust(left=0.18, right=0.99, top=0.91, bottom=0.28)
    save(fig, outdir, "fig2_spill_vs_qubits.pdf")


# ── F3 — Spill vs entropy: scatter coloured by bin ───────────────────────────

def plot_spill_vs_entropy(pc, outdir):
    fig, axes = plt.subplots(1, 3, figsize=(_W, 2.7), sharey=True,
                              gridspec_kw={"wspace": 0.07})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d = pc[pc["engine"]==eng].dropna(subset=["entropy","spill"])
        scatter_by_bin(ax, d, "entropy", "spill")
        r = spearman(d["entropy"].values, d["spill"].values)
        annotate_rho(ax, r)
        set_log_y(ax)
        ax.set_xlabel("Shannon entropy (bits)")
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=4)
        if col == 0:
            ax.set_ylabel("Spill (log scale)")
            bin_legend(ax, outside=True)
        else:
            ax.tick_params(labelleft=False)

    fig.suptitle(
        "Spill vs Shannon entropy — higher entropy drives more spill"
        "  (open = zero spill at 4 KB sentinel)",
        fontsize=_FS, y=1.01)
    fig.subplots_adjust(left=0.09, right=0.995, top=0.88, bottom=0.28)
    save(fig, outdir, "fig3_spill_vs_entropy.pdf")


# ── F4 — Spill vs density: scatter (NO connecting lines) ──────────────────────

def plot_spill_vs_density(pc, outdir):
    """
    Many circuits share density=1.0 exactly — connecting lines would be
    meaningless spaghetti.  Pure scatter, log y.
    """
    fig, axes = plt.subplots(1, 3, figsize=(_W, 2.7), sharey=True,
                              gridspec_kw={"wspace": 0.07})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d = pc[pc["engine"]==eng].dropna(subset=["density","spill"])
        scatter_by_bin(ax, d, "density", "spill")
        r = spearman(d["density"].values, d["spill"].values)
        annotate_rho(ax, r)
        set_log_y(ax)
        ax.set_xlabel("Output state density")
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=4)
        if col == 0:
            ax.set_ylabel("Spill (log scale)")
            bin_legend(ax, outside=True)
        else:
            ax.tick_params(labelleft=False)

    fig.suptitle(
        "Spill vs output state density — (low : sparse, high : dense)"
        "  (open = zero spill at 4 KB sentinel)",
        fontsize=_FS, y=1.01)
    fig.subplots_adjust(left=0.09, right=0.995, top=0.88, bottom=0.28)
    save(fig, outdir, "fig4_spill_vs_density.pdf")


# ── F5 — Largest CTE vs spill: the causal figure ─────────────────────────────

def plot_cte_vs_spill(pc, outdir):
    """
    Log-log scatter: both largest_cte and total_cte vs spill, overlaid in
    each panel.  Filled markers = largest CTE; open markers = total CTE.
    Colour = density bin (same palette as other figures).
    Slope-1 reference line anchored on largest-CTE non-zero points.
    Two Spearman rhos annotated per panel so the reader can compare directly.
    One panel per engine — clean 1×3 layout.
    """
    fig, axes = plt.subplots(1, 3, figsize=(_W, 2.9), sharey=True,
                              gridspec_kw={"wspace": 0.10})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d = pc[pc["engine"] == eng].dropna(
            subset=["largest_cte", "total_cte", "spill"])

        # ── draw points: filled = largest CTE, open = total CTE ──────────
        for bname in BINS:
            bc = BIN_COLOR[bname]
            mk = BIN_MARK[bname]
            bd = d[d["sp_bin"] == bname]
            if bd.empty:
                continue

            # largest CTE — filled, solid edge
            nz = bd[bd["spill"] > 0]
            zr = bd[bd["spill"] == 0]
            if len(nz):
                ax.scatter(nz["largest_cte"], nz["spill"],
                           color=bc, marker=mk, s=22, alpha=0.85,
                           edgecolors="white", linewidths=0.4, zorder=5)
            if len(zr):
                ax.scatter(zr["largest_cte"],
                           np.full(len(zr), ZERO_SENT),
                           color=bc, marker=mk, s=22, alpha=0.85,
                           edgecolors=bc, facecolors="none",
                           linewidths=0.8, zorder=5)

            # total CTE — open (white fill, coloured edge), slightly smaller
            if len(nz):
                ax.scatter(nz["total_cte"], nz["spill"],
                           color="none", marker=mk, s=16, alpha=0.90,
                           edgecolors=bc, linewidths=0.9, zorder=4)
            if len(zr):
                ax.scatter(zr["total_cte"],
                           np.full(len(zr), ZERO_SENT),
                           color="none", marker=mk, s=16, alpha=0.70,
                           edgecolors=bc, linewidths=0.7, zorder=4,
                           linestyle=":")

        # ── slope-1 guide anchored on largest-CTE non-zero points ────────
        nz_all = d[d["spill"] > 0]
        if len(nz_all) >= 2:
            ratio = np.median(
                nz_all["spill"].values / nz_all["largest_cte"].values)
            xl = np.array([d["largest_cte"].min(), d["largest_cte"].max()])
            ax.plot(xl, ratio * xl,
                    color="0.65", lw=0.8, ls="--", zorder=1)

        # ── Spearman rhos: two lines, top-right corner ────────────────────
        r_lrg = spearman(d["largest_cte"].values, d["spill"].values)
        r_tot = spearman(d["total_cte"].values,   d["spill"].values)
        # bold the stronger one
        def _rho_str(label, r, stronger):
            weight = "bold" if stronger else "normal"
            return label, f"{r:+.2f}", weight

        winner_lrg = np.isfinite(r_lrg) and (
            not np.isfinite(r_tot) or abs(r_lrg) >= abs(r_tot))
        for i, (label, val, w) in enumerate([
            _rho_str("ρ(largest)", r_lrg, winner_lrg),
            _rho_str("ρ(total)  ", r_tot, not winner_lrg),
        ]):
            ax.annotate(
                f"{label} = {val}",
                xy=(0.97, 0.05 + i * 0.10),
                xycoords="axes fraction", ha="right",
                fontsize=_FST, color="0.35",
                fontweight=w,
            )

        print(f"  {eng}: ρ(largest)={r_lrg:+.3f}  ρ(total)={r_tot:+.3f}"
              f"  → {'largest' if winner_lrg else 'total'} stronger")

        set_log_y(ax)
        set_log_x_bytes(ax)
        ax.set_xlabel("CTE size (bytes, log scale)")
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=4)

        if col == 0:
            ax.set_ylabel("Spill (log scale)")
        else:
            ax.tick_params(labelleft=False)

    # ── combined legend: density bins + filled/open encoding ─────────────
    bin_handles = [
        Line2D([0],[0], marker=BIN_MARK[b], color=BIN_COLOR[b],
               lw=0, ms=5, mew=0.4, mec="white", label=BIN_LABEL[b])
        for b in BINS
    ]
    type_handles = [
        Line2D([0],[0], marker="o", color="0.4", lw=0,
               ms=5, mew=0.4, mec="white",  label="Largest CTE (filled)"),
        Line2D([0],[0], marker="o", color="none", lw=0,
               ms=4, mew=0.9, mec="0.4",   label="Total CTE (open)"),
    ]
    axes[0].legend(
        handles=bin_handles + type_handles,
        loc="upper left", bbox_to_anchor=(0, -0.28),
        ncol=3, handlelength=0.6,
        borderpad=0.45, labelspacing=0.22, columnspacing=0.9,
        fontsize=_FST,
    )

    fig.suptitle(
        "Spill vs CTE size  (log-log) — filled = largest CTE, open = total CTE"
        "  (bolder ρ = stronger predictor)",
        fontsize=_FS, y=1.01)
    fig.subplots_adjust(left=0.09, right=0.995, top=0.89, bottom=0.30)
    save(fig, outdir, "fig5_cte_vs_spill.pdf")


# ── F6 — CTE vs entropy ───────────────────────────────────────────────────────

def plot_cte_vs_entropy(pc, outdir):
    """
    CTE sizes differ per engine (each planner materialises CTEs differently).
    One panel per engine. Filled marker = total CTE; open = largest CTE.
    Colour = density bin.  Log y, linear x.
    """
    fig, axes = plt.subplots(1, 3, figsize=(_W, 2.7), sharey=True,
                              gridspec_kw={"wspace": 0.07})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        sub = pc[(pc["engine"]==eng)].dropna(
              subset=["entropy","total_cte","largest_cte"])

        for bname in BINS:
            bc = BIN_COLOR[bname]
            mk = BIN_MARK[bname]
            bd = sub[sub["sp_bin"]==bname]
            if bd.empty: continue
            ax.scatter(bd["entropy"], bd["total_cte"],
                       color=bc, marker=mk, s=26, alpha=0.85,
                       edgecolors="white", linewidths=0.4, zorder=4)
            ax.scatter(bd["entropy"], bd["largest_cte"],
                       color="none", marker=mk, s=18, alpha=0.85,
                       edgecolors=bc, linewidths=0.9, zorder=5)

        r_tot = spearman(sub["entropy"].values, sub["total_cte"].values)
        r_lrg = spearman(sub["entropy"].values, sub["largest_cte"].values)
        ax.annotate(f"ρ(total)={r_tot:+.2f}\nρ(largest)={r_lrg:+.2f}",
                    xy=(0.03, 0.97), xycoords="axes fraction",
                    ha="left", va="top", fontsize=_FST, color="0.38",
                    linespacing=1.5)

        set_log_y(ax)
        ax.set_xlabel("Shannon entropy (bits)")
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=4)
        if col == 0:
            ax.set_ylabel("CTE size")
            # Compact legend: bins + filled/open distinction
            bin_handles = [
                Line2D([0],[0], marker=BIN_MARK[b], color=BIN_COLOR[b],
                       lw=0, ms=5, mew=0.4, mec="white", label=BIN_LABEL[b])
                for b in BINS
            ]
            type_handles = [
                Line2D([0],[0], marker="o", color="0.4", lw=0,
                       ms=5, mew=0.4, mec="white", label="Total CTEs"),
                Line2D([0],[0], marker="o", color="none", lw=0,
                       ms=4, mew=0.9, mec="0.4",    label="Largest CTE"),
            ]
            ax.legend(handles=bin_handles + type_handles,
                      loc="upper left", bbox_to_anchor=(0, -0.32),
                      ncol=3, handlelength=0.6,
                      borderpad=0.45, labelspacing=0.22, columnspacing=0.8,
                      fontsize=_FST)
        else:
            ax.tick_params(labelleft=False)

    fig.suptitle(
        "CTE intermediate size vs Shannon entropy — filled = total, open = largest",
        fontsize=_FS, y=1.01)
    fig.subplots_adjust(left=0.09, right=0.995, top=0.88, bottom=0.30)
    save(fig, outdir, "fig6_cte_vs_entropy.pdf")


# ── F7 — CTE vs density ───────────────────────────────────────────────────────

def plot_cte_vs_density(pc, outdir):
    """
    One panel per engine. Filled = total CTE; open = largest CTE.
    Single-column SIGMOD layout: 3.33" wide x 1.65" tall.
    """
    _WC = 3.33
    fig, axes = plt.subplots(1, 3, figsize=(_WC, 1.65), sharey=True,
                              gridspec_kw={"wspace": 0.04})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        sub = pc[(pc["engine"]==eng)].dropna(
              subset=["density","total_cte","largest_cte"])

        for bname in BINS:
            bc = BIN_COLOR[bname]
            mk = BIN_MARK[bname]
            bd = sub[sub["sp_bin"]==bname]
            if bd.empty: continue
            ax.scatter(bd["density"], bd["total_cte"],
                       color=bc, marker=mk, s=14, alpha=0.85,
                       edgecolors="white", linewidths=0.3, zorder=4)
            ax.scatter(bd["density"], bd["largest_cte"],
                       color="none", marker=mk, s=10, alpha=0.85,
                       edgecolors=bc, linewidths=0.7, zorder=5)

        r_tot = spearman(sub["density"].values, sub["total_cte"].values)
        r_lrg = spearman(sub["density"].values, sub["largest_cte"].values)
        ax.annotate(f"ρ(tot)={r_tot:+.2f}\nρ(lrg)={r_lrg:+.2f}",
                    xy=(0.97, 0.03), xycoords="axes fraction",
                    ha="right", va="bottom", fontsize=_FST, color="0.38",
                    linespacing=1.4)

        set_log_y(ax)
        ax.tick_params(axis="both", labelsize=_FST)
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=2,
                     fontsize=_FSS, fontweight="bold")
        if col == 0:
            ax.set_ylabel("CTE size", fontsize=_FSS)
        else:
            ax.tick_params(labelleft=False)

    # shared x-label — sits just above the legend
    fig.text(0.5, 0.13, "Output density  (0=sparse, 1=dense)",
             ha="center", va="bottom", fontsize=_FSS)

    # single-line legend, no frame, no title — below the x-label
    bin_handles = [
        Line2D([0],[0], marker=BIN_MARK[b], color=BIN_COLOR[b],
               lw=0, ms=4, mew=0.3, mec="white", label=BIN_LABEL[b])
        for b in BINS
    ]
    type_handles = [
        Line2D([0],[0], marker="o", color="0.4", lw=0,
               ms=4, mew=0.3, mec="white", label="Total CTEs"),
        Line2D([0],[0], marker="o", color="none", lw=0,
               ms=3.5, mew=0.7, mec="0.4", label="Largest CTE"),
    ]
    fig.legend(handles=bin_handles + type_handles,
               loc="lower center", bbox_to_anchor=(0.5, 0.0),
               ncol=5, handlelength=0.5, borderpad=0.3,
               labelspacing=0.15, columnspacing=0.5,
               fontsize=_FST, frameon=False)

    fig.subplots_adjust(left=0.17, right=0.99, top=0.97, bottom=0.32)
    save(fig, outdir, "fig7_cte_vs_density.pdf")

# ── F8 — Wall time vs spill ───────────────────────────────────────────────────
def plot_walltime_vs_spill(pc, outdir):
    _WC = 3.33
    BREAK_X = 1e7   # fake x position for zero-spill points (10 MB, left of real data)

    fig, axes = plt.subplots(1, 3, figsize=(_WC, 1.65), sharey=True,
                              gridspec_kw={"wspace": 0.04})

    for col, (ax, eng) in enumerate(zip(axes, ENGINES)):
        d = pc[pc["engine"] == eng].dropna(subset=["wall_time", "spill"])

        # Split zero and non-zero spill
        nz = d[d["spill"] > 0]
        zr = d[d["spill"] == 0]

        # Plot non-zero spill normally
        scatter_by_bin(ax, nz, "spill", "wall_time", ms=14, zero_sentinel=ZERO_SENT)
        r = spearman(d["spill"].values, d["wall_time"].values)
        annotate_rho(ax, r, pos=(0.97, 0.05))

        set_log_x_bytes(ax)

        # Plot zero-spill points at BREAK_X with open markers
        if not zr.empty:
            for bname in BINS:
                bd = zr[zr["sp_bin"] == bname]
                if bd.empty:
                    continue
                ax.scatter([BREAK_X] * len(bd), bd["wall_time"],
                        color="none", marker=BIN_MARK[bname],
                        s=14, edgecolors=BIN_COLOR[bname],
                        linewidths=0.7, zorder=5)
            ax.axvline(BREAK_X * 3, color="0.70", lw=0.6, ls=":", zorder=1)
            # label the zero-spill column
            ax.text(BREAK_X, 0.06, "0", ha="center", va="bottom",
                    fontsize=_FST, color="0.40", transform=ax.transData)

        set_log_y(ax)
        ax.set_ylim(bottom=0.05)
        ax.yaxis.set_major_formatter(
            ticker.FuncFormatter(lambda x, _: f"{x:.0f}" if x >= 1 else f"{x:.1f}"))
        ax.yaxis.set_minor_locator(ticker.NullLocator())
        ax.tick_params(axis="both", labelsize=_FST)
        ax.set_title(ENG_LABEL[eng], color=ENG_COLOR[eng], pad=2,
                     fontsize=_FSS, fontweight="bold")
        if col == 0:
            ax.set_ylabel("Time (s)", fontsize=_FSS)
        else:
            ax.tick_params(labelleft=False)

    fig.text(0.5, 0.13, "Spill", ha="center", va="bottom", fontsize=_FSS)

    bin_handles = [
        Line2D([0], [0], marker=BIN_MARK[b], color=BIN_COLOR[b],
               lw=0, ms=4, mew=0.3, mec="white", label=BIN_LABEL[b])
        for b in BINS
    ]
    fig.legend(handles=bin_handles,
               loc="lower center", bbox_to_anchor=(0.5, 0.0),
               ncol=3, handlelength=0.5, borderpad=0.3,
               labelspacing=0.15, columnspacing=0.5,
               fontsize=_FST, frameon=False)

    fig.subplots_adjust(left=0.17, right=0.99, top=0.97, bottom=0.32)
    save(fig, outdir, "fig8_walltime_vs_spill.pdf")
# ── Export ────────────────────────────────────────────────────────────────────

def export_summary(pc, outdir):
    out = pc.copy()
    for c in ["spill","total_cte","largest_cte"]:
        if c in out.columns:
            out[f"{c}_gb"] = (out[c]/1e9).round(6)
    p = os.path.join(outdir, "spill_summary.csv")
    out.to_csv(p, index=False)
    print(f"  saved -> {p}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="OOC spill -- SIGMOD figures v5")
    ap.add_argument("--results", default="ooc_sample_results_final.csv",
                    help="Benchmark results CSV")
    ap.add_argument("--sampled", default="new_sampled_output.csv",
                    help="Circuit properties CSV (RowKey, sparsity, shannon_entropy, ...)")
    ap.add_argument("--outdir",  default="ooc_figures",
                    help="Output directory")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    pc = load_data(args.results, args.sampled)

    steps = [
        ("Fig 1  coverage",                plot_coverage),
        ("Fig 2  spill vs qubits",         plot_spill_vs_qubits),
        ("Fig 3  spill vs entropy",        plot_spill_vs_entropy),
        ("Fig 4  spill vs density",        plot_spill_vs_density),
        ("Fig 5  spill vs largest CTE",    plot_cte_vs_spill),
        ("Fig 6  CTE vs entropy",          plot_cte_vs_entropy),
        ("Fig 7  CTE vs density",          plot_cte_vs_density),
        ("Fig 8  wall time vs spill",      plot_walltime_vs_spill),
    ]
    for label, fn in steps:
        print(label)
        try:
            fn(pc, args.outdir)
        except Exception:
            import traceback
            print(f"  [WARN] failed:\n{traceback.format_exc()}")

    print("\nExports")
    export_summary(pc, args.outdir)
    print(f"\nDone -> {args.outdir}/")

if __name__ == "__main__":
    main()