"""
Spill Behaviour Analysis – SIGMOD Out-of-Core Evaluation
=========================================================
Joins results.csv with sampled_output.csv (sparsity + Shannon entropy) and
produces publication-quality figures covering:

  Circuit-level predictors
    1.  spill_vs_qubits.pdf              – median spill vs qubit count (log y, IQR band)
    2.  spill_vs_sparsity_scatter.pdf    – scatter: sparsity → spill, per engine (log y)
    3.  spill_vs_sparsity_bins.pdf       – binned sparsity ribbon, per engine
    4.  spill_vs_entropy_scatter.pdf     – scatter: Shannon entropy → spill, per engine
    5.  spill_vs_entropy_bins.pdf        – binned entropy ribbon, per engine
    6.  entropy_vs_sparsity_joint.pdf    – 2-D scatter coloured by spill (per engine)

  Distribution / statistical
    7.  boxplot_by_engine.pdf            – overall spill distribution per engine
    8.  boxplot_by_qubits_engine.pdf     – grouped: qubit × engine
    9.  boxplot_by_cap.pdf               – grouped: memory cap × engine

  Heat-maps
    10. heatmap_qubit_sparsity.pdf       – median spill: qubit × sparsity bin
    11. heatmap_qubit_entropy.pdf        – median spill: qubit × entropy bin

  Meta
    12. summary_stats.csv               – descriptive stats table (inc. cap_gb breakdown)

Usage:
    python spill_analysis.py \\
        --results results.csv \\
        --sampled sampled_output.csv \\
        [--outdir figures]
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
from matplotlib.colors import LogNorm

warnings.filterwarnings("ignore", category=FutureWarning)

# ── Aesthetics ────────────────────────────────────────────────────────────────
ENGINE_PALETTE = {
    "postgres": "#2166AC",
    "duckdb":   "#D6604D",
    "sqlite":   "#1A9850",
}
ENGINE_MARKERS = {"postgres": "o", "duckdb": "s", "sqlite": "^"}
ENGINE_ORDER   = ["postgres", "duckdb", "sqlite"]

CMAP_HEAT = "YlOrRd"

plt.rcParams.update({
    "font.family":       "DejaVu Sans",
    "font.size":         11,
    "axes.titlesize":    12,
    "axes.titleweight":  "bold",
    "axes.labelsize":    11,
    "axes.labelweight":  "bold",
    "legend.fontsize":   9,
    "legend.framealpha": 0.9,
    "legend.edgecolor":  "0.75",
    "xtick.labelsize":   9,
    "ytick.labelsize":   9,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.color":        "0.88",
    "grid.linewidth":    0.6,
    "figure.dpi":        180,
    "savefig.dpi":       300,
})

BYTES_TO_GB = 1 / (1024 ** 3)


# ── Helpers ───────────────────────────────────────────────────────────────────
def log_fmt(x, _):
    """Compact human-readable byte labels for log axes."""
    if x <= 0:    return "0"
    if x < 1e3:   return f"{x:.0f} B"
    if x < 1e6:   return f"{x/1e3:.0f} KB"
    if x < 1e9:   return f"{x/1e6:.0f} MB"
    return             f"{x/1e9:.1f} GB"


def apply_log_y(ax):
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(log_fmt))
    ax.grid(axis="y", which="both", linestyle="--", linewidth=0.5, alpha=0.6)
    ax.grid(axis="x", which="major", linestyle=":", linewidth=0.4, alpha=0.4)


def save(fig, outdir, name):
    path = os.path.join(outdir, name)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved -> {path}")


def ribbon(ax, x, med, q25, q75, color, label, marker="o"):
    """Plot median line + IQR shading, tolerating NaNs."""
    med  = np.asarray(med,  dtype=float)
    q25  = np.asarray(q25,  dtype=float)
    q75  = np.asarray(q75,  dtype=float)
    x    = np.asarray(x,    dtype=float)
    mask = np.isfinite(med) & np.isfinite(q25) & np.isfinite(q75)
    if not mask.any():
        return
    ax.plot(x[mask], med[mask], marker=marker, color=color, label=label,
            linewidth=2.2, markersize=6, zorder=4)
    ax.fill_between(x[mask], q25[mask], q75[mask],
                    alpha=0.18, color=color, zorder=2)


def add_engine_legend(ax, title="Engine", loc="best"):
    ax.legend(title=title, loc=loc, frameon=True)


def binned_agg(df, xcol, n_bins, x_range=None):
    """Add an '_bin' column with evenly-spaced labels; return (df, labels)."""
    lo, hi = x_range if x_range else (df[xcol].min(), df[xcol].max())
    edges  = np.linspace(lo, hi, n_bins + 1)
    labels = [f"{edges[i]:.2g}–{edges[i+1]:.2g}" for i in range(n_bins)]
    df     = df.copy()
    df["_bin"] = pd.cut(df[xcol], bins=edges, labels=labels,
                        include_lowest=True)
    return df, labels


# ── Data loading ──────────────────────────────────────────────────────────────
def load_data(results_path, sampled_path):
    res = pd.read_csv(results_path)
    smp = pd.read_csv(sampled_path).rename(columns={"RowKey": "circuit_hash"})

    join_cols = ["circuit_hash", "statevector_saved_sparsity"]
    if "statevector_shannon_entropy" in smp.columns:
        join_cols.append("statevector_shannon_entropy")

    df = res.merge(smp[join_cols], on="circuit_hash", how="left")

    # Keep only successful, non-warmup runs
    df = df[(df["status"] == "success") &
            (df["run_idx"].notna()) &
            (df["run_idx"] != "warmup")].copy()

    # Numeric coercions
    for col in ["spill_proxy_bytes", "num_qubits", "cap_gb",
                "statevector_saved_sparsity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "statevector_shannon_entropy" in df.columns:
        df["statevector_shannon_entropy"] = pd.to_numeric(
            df["statevector_shannon_entropy"], errors="coerce")

    df["spill_gb"] = df["spill_proxy_bytes"] * BYTES_TO_GB
    df["engine"]   = df["engine"].str.strip().str.lower()

    # Only rows with measurable spill and a known engine
    df = df[(df["spill_proxy_bytes"] > 0) &
            (df["engine"].isin(ENGINE_ORDER))].copy()

    print(f"Loaded {len(df):,} usable rows")
    print("  Engine counts:", df["engine"].value_counts().to_dict())
    print("  Qubit range:  ",
          int(df["num_qubits"].min()), "–", int(df["num_qubits"].max()))
    has_entropy = ("statevector_shannon_entropy" in df.columns and
                   df["statevector_shannon_entropy"].notna().any())
    print(f"  Shannon entropy: {'present' if has_entropy else 'NOT FOUND'}")
    return df


# ── Plot 1 – Spill vs qubit count ─────────────────────────────────────────────
def plot_spill_vs_qubits(df, outdir):
    agg = (df.groupby(["engine", "num_qubits"])["spill_proxy_bytes"]
             .agg(med="median",
                  q25=lambda x: x.quantile(0.25),
                  q75=lambda x: x.quantile(0.75))
             .reset_index())

    fig, ax = plt.subplots(figsize=(8, 5))
    for eng in ENGINE_ORDER:
        s = agg[agg["engine"] == eng].sort_values("num_qubits")
        if s.empty: continue
        ribbon(ax, s["num_qubits"], s["med"], s["q25"], s["q75"],
               ENGINE_PALETTE[eng], eng.capitalize(), ENGINE_MARKERS[eng])

    apply_log_y(ax)
    ax.set_xlabel("Number of Qubits")
    ax.set_ylabel("Spill (log scale)")
    ax.set_title("Median Spill vs Qubit Count  [shaded = IQR]")
    add_engine_legend(ax, loc="upper left")
    fig.tight_layout()
    save(fig, outdir, "spill_vs_qubits.pdf")


# ── Plot 2 – Scatter: sparsity vs spill ───────────────────────────────────────
def plot_spill_vs_sparsity_scatter(df, outdir):
    sub = df.dropna(subset=["statevector_saved_sparsity"])
    if sub.empty: return

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True,
                             gridspec_kw={"wspace": 0.08})
    for ax, eng in zip(axes, ENGINE_ORDER):
        d = sub[sub["engine"] == eng]
        c = ENGINE_PALETTE[eng]
        ax.scatter(d["statevector_saved_sparsity"], d["spill_proxy_bytes"],
                   alpha=0.35, s=16, color=c, rasterized=True, edgecolors="none")
        # Overlay median trend
        tmp, labs = binned_agg(d, "statevector_saved_sparsity", 10, (0, 1))
        magg = (tmp.groupby("_bin", observed=True)["spill_proxy_bytes"]
                   .median().reindex(labs))
        xc    = np.linspace(0.05, 0.95, len(labs))
        valid = magg.notna()
        if valid.any():
            ax.plot(xc[valid], magg.values[valid], color=c,
                    linewidth=2.2, zorder=5, label="Median")
        apply_log_y(ax)
        ax.set_xlabel("Sparsity")
        ax.set_title(eng.capitalize(), color=c, fontweight="bold")
        ax.set_xlim(-0.03, 1.03)
    axes[0].set_ylabel("Spill (log scale)")
    fig.suptitle("Spill vs Statevector Sparsity", fontsize=13, y=1.01)
    save(fig, outdir, "spill_vs_sparsity_scatter.pdf")


# ── Plot 3 – Binned sparsity ribbon ───────────────────────────────────────────
def plot_spill_vs_sparsity_bins(df, outdir):
    sub = df.dropna(subset=["statevector_saved_sparsity"])
    if sub.empty: return

    N = 10
    tmp, labs = binned_agg(sub, "statevector_saved_sparsity", N, (0, 1))
    agg = (tmp.groupby(["engine", "_bin"], observed=True)["spill_proxy_bytes"]
              .agg(med="median",
                   q25=lambda x: x.quantile(0.25),
                   q75=lambda x: x.quantile(0.75))
              .reset_index())

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(N)
    for eng in ENGINE_ORDER:
        se = agg[agg["engine"] == eng].set_index("_bin").reindex(labs)
        ribbon(ax, x, se["med"].values, se["q25"].values, se["q75"].values,
               ENGINE_PALETTE[eng], eng.capitalize(), ENGINE_MARKERS[eng])

    apply_log_y(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labs, rotation=38, ha="right", fontsize=8)
    ax.set_xlabel("Sparsity Bin")
    ax.set_ylabel("Spill (log scale)")
    ax.set_title("Median Spill vs Sparsity Bin  [shaded = IQR]")
    add_engine_legend(ax)
    fig.tight_layout()
    save(fig, outdir, "spill_vs_sparsity_bins.pdf")


# ── Plot 4 – Scatter: Shannon entropy vs spill ────────────────────────────────
def plot_spill_vs_entropy_scatter(df, outdir):
    if "statevector_shannon_entropy" not in df.columns:
        print("  [skip] no entropy column"); return
    sub = df.dropna(subset=["statevector_shannon_entropy"])
    if sub.empty: return

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True,
                             gridspec_kw={"wspace": 0.08})
    for ax, eng in zip(axes, ENGINE_ORDER):
        d = sub[sub["engine"] == eng]
        c = ENGINE_PALETTE[eng]
        ax.scatter(d["statevector_shannon_entropy"], d["spill_proxy_bytes"],
                   alpha=0.35, s=16, color=c, rasterized=True, edgecolors="none")
        tmp, labs = binned_agg(d, "statevector_shannon_entropy", 10)
        magg = (tmp.groupby("_bin", observed=True)["spill_proxy_bytes"]
                   .median().reindex(labs))
        elo   = d["statevector_shannon_entropy"].min()
        ehi   = d["statevector_shannon_entropy"].max()
        xc    = np.linspace(elo + (ehi - elo) * 0.05,
                            ehi - (ehi - elo) * 0.05, len(labs))
        valid = magg.notna()
        if valid.any():
            ax.plot(xc[valid], magg.values[valid], color=c,
                    linewidth=2.2, zorder=5)
        apply_log_y(ax)
        ax.set_xlabel("Shannon Entropy (bits)")
        ax.set_title(eng.capitalize(), color=c, fontweight="bold")
    axes[0].set_ylabel("Spill (log scale)")
    fig.suptitle("Spill vs Statevector Shannon Entropy", fontsize=13, y=1.01)
    save(fig, outdir, "spill_vs_entropy_scatter.pdf")


# ── Plot 5 – Binned entropy ribbon ────────────────────────────────────────────
def plot_spill_vs_entropy_bins(df, outdir):
    if "statevector_shannon_entropy" not in df.columns:
        print("  [skip] no entropy column"); return
    sub = df.dropna(subset=["statevector_shannon_entropy"])
    if sub.empty: return

    N   = 10
    elo = sub["statevector_shannon_entropy"].min()
    ehi = sub["statevector_shannon_entropy"].max()
    tmp, labs = binned_agg(sub, "statevector_shannon_entropy", N, (elo, ehi))
    agg = (tmp.groupby(["engine", "_bin"], observed=True)["spill_proxy_bytes"]
              .agg(med="median",
                   q25=lambda x: x.quantile(0.25),
                   q75=lambda x: x.quantile(0.75))
              .reset_index())

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(N)
    for eng in ENGINE_ORDER:
        se = agg[agg["engine"] == eng].set_index("_bin").reindex(labs)
        ribbon(ax, x, se["med"].values, se["q25"].values, se["q75"].values,
               ENGINE_PALETTE[eng], eng.capitalize(), ENGINE_MARKERS[eng])

    apply_log_y(ax)
    ax.set_xticks(x)
    ax.set_xticklabels(labs, rotation=38, ha="right", fontsize=8)
    ax.set_xlabel("Shannon Entropy Bin (bits)")
    ax.set_ylabel("Spill (log scale)")
    ax.set_title("Median Spill vs Shannon Entropy Bin  [shaded = IQR]")
    add_engine_legend(ax)
    fig.tight_layout()
    save(fig, outdir, "spill_vs_entropy_bins.pdf")


# ── Plot 6 – Joint 2-D: entropy × sparsity coloured by spill ─────────────────
def plot_entropy_vs_sparsity_joint(df, outdir):
    if "statevector_shannon_entropy" not in df.columns:
        print("  [skip] no entropy column"); return
    sub = df.dropna(subset=["statevector_saved_sparsity",
                             "statevector_shannon_entropy"])
    if sub.empty: return

    # Per-circuit median per engine to collapse repeated runs
    per_circ = (sub.groupby(["engine", "circuit_hash",
                              "statevector_saved_sparsity",
                              "statevector_shannon_entropy"])
                   ["spill_proxy_bytes"].median().reset_index())

    vals = per_circ["spill_proxy_bytes"]
    vmin = max(vals.quantile(0.02), 1)
    vmax = vals.quantile(0.98)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8),
                             gridspec_kw={"wspace": 0.38})
    for ax, eng in zip(axes, ENGINE_ORDER):
        d  = per_circ[per_circ["engine"] == eng]
        sc = ax.scatter(d["statevector_saved_sparsity"],
                        d["statevector_shannon_entropy"],
                        c=d["spill_proxy_bytes"],
                        norm=LogNorm(vmin=vmin, vmax=vmax),
                        cmap="plasma", s=45, alpha=0.82,
                        edgecolors="0.3", linewidths=0.3)
        cb = plt.colorbar(sc, ax=ax, pad=0.03)
        cb.set_label("Median Spill", fontsize=8)
        cb.ax.yaxis.set_major_formatter(ticker.FuncFormatter(log_fmt))
        cb.ax.tick_params(labelsize=7)
        ax.set_xlabel("Sparsity")
        ax.set_ylabel("Shannon Entropy (bits)")
        ax.set_title(eng.capitalize(), color=ENGINE_PALETTE[eng],
                     fontweight="bold")
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)

    fig.suptitle("Sparsity × Entropy  [colour = Median Spill]",
                 fontsize=13, y=1.01)
    save(fig, outdir, "entropy_vs_sparsity_joint.pdf")


# ── Plot 7 – Box plots per engine ─────────────────────────────────────────────
def plot_boxplot_by_engine(df, outdir):
    fig, ax = plt.subplots(figsize=(7, 5))
    data = [df[df["engine"] == e]["spill_proxy_bytes"].dropna().values
            for e in ENGINE_ORDER]
    bp = ax.boxplot(data, patch_artist=True, notch=False,
                    medianprops={"color": "black", "linewidth": 2},
                    flierprops={"marker": ".", "alpha": 0.25, "markersize": 4},
                    widths=0.5)
    for patch, eng in zip(bp["boxes"], ENGINE_ORDER):
        patch.set_facecolor(ENGINE_PALETTE[eng])
        patch.set_alpha(0.72)
    apply_log_y(ax)
    ax.set_xticks(range(1, len(ENGINE_ORDER) + 1))
    ax.set_xticklabels([e.capitalize() for e in ENGINE_ORDER], fontsize=11)
    ax.set_ylabel("Spill (log scale)")
    ax.set_title("Spill Distribution per Engine")
    save(fig, outdir, "boxplot_by_engine.pdf")


# ── Plot 8 – Grouped boxes: qubit × engine ───────────────────────────────────
def plot_boxplot_by_qubits_engine(df, outdir):
    qubits  = sorted(df["num_qubits"].dropna().unique())
    n_q, n_e = len(qubits), len(ENGINE_ORDER)
    width   = 0.22
    offsets = np.linspace(-(n_e - 1) * width / 2,
                           (n_e - 1) * width / 2, n_e)

    fig, ax = plt.subplots(figsize=(max(10, n_q * 1.8), 6))
    for i, eng in enumerate(ENGINE_ORDER):
        vals, pos = [], []
        for j, q in enumerate(qubits):
            d = df[(df["engine"] == eng) &
                   (df["num_qubits"] == q)]["spill_proxy_bytes"].dropna()
            if len(d) >= 3:
                vals.append(d.values)
                pos.append(j + offsets[i])
        if not vals: continue
        bp = ax.boxplot(vals, positions=pos, widths=width * 0.88,
                        patch_artist=True, notch=False,
                        medianprops={"color": "black", "linewidth": 1.6},
                        flierprops={"marker": ".", "alpha": 0.18, "markersize": 3},
                        manage_ticks=False)
        for patch in bp["boxes"]:
            patch.set_facecolor(ENGINE_PALETTE[eng])
            patch.set_alpha(0.72)
        ax.plot([], [], color=ENGINE_PALETTE[eng], linewidth=7,
                alpha=0.72, label=eng.capitalize())

    apply_log_y(ax)
    ax.set_xticks(range(n_q))
    ax.set_xticklabels([int(q) for q in qubits])
    ax.set_xlabel("Number of Qubits")
    ax.set_ylabel("Spill (log scale)")
    ax.set_title("Spill by Qubit Count and Engine")
    add_engine_legend(ax, loc="upper left")
    fig.tight_layout()
    save(fig, outdir, "boxplot_by_qubits_engine.pdf")


# ── Plot 9 – Grouped boxes: memory cap × engine ──────────────────────────────
def plot_boxplot_by_cap(df, outdir):
    caps = sorted(df["cap_gb"].dropna().unique())
    if len(caps) < 2:
        print("  [skip] fewer than 2 distinct cap_gb values"); return

    fig, axes = plt.subplots(1, len(ENGINE_ORDER), figsize=(14, 5), sharey=True,
                             gridspec_kw={"wspace": 0.06})
    for ax, eng in zip(axes, ENGINE_ORDER):
        sub  = df[df["engine"] == eng]
        data = [sub[sub["cap_gb"] == c]["spill_proxy_bytes"].dropna().values
                for c in caps]
        bp = ax.boxplot(data, patch_artist=True, notch=False,
                        medianprops={"color": "black", "linewidth": 1.8},
                        flierprops={"marker": ".", "alpha": 0.2, "markersize": 3},
                        widths=0.5)
        for patch in bp["boxes"]:
            patch.set_facecolor(ENGINE_PALETTE[eng])
            patch.set_alpha(0.72)
        apply_log_y(ax)
        ax.set_xticks(range(1, len(caps) + 1))
        ax.set_xticklabels([f"{c:.0f} GB" for c in caps],
                           rotation=30, ha="right")
        ax.set_xlabel("Memory Cap")
        ax.set_title(eng.capitalize(), color=ENGINE_PALETTE[eng],
                     fontweight="bold")
    axes[0].set_ylabel("Spill (log scale)")
    fig.suptitle("Spill Distribution by Memory Cap per Engine",
                 fontsize=13, y=1.01)
    save(fig, outdir, "boxplot_by_cap.pdf")


# ── Plots 10 & 11 – Heat-maps ─────────────────────────────────────────────────
def _heatmap(df, xcol, x_range, n_bins, xlabel, outfile, outdir):
    sub = df.dropna(subset=[xcol])
    if sub.empty: return

    tmp, labs = binned_agg(sub, xcol, n_bins, x_range)
    n_eng = len(ENGINE_ORDER)
    fig, axes = plt.subplots(1, n_eng, figsize=(5.5 * n_eng, 4.5),
                             gridspec_kw={"wspace": 0.45})

    for ax, eng in zip(axes, ENGINE_ORDER):
        pivot = (tmp[tmp["engine"] == eng]
                 .groupby(["num_qubits", "_bin"], observed=True)["spill_proxy_bytes"]
                 .median()
                 .unstack("_bin")
                 .reindex(columns=labs))
        if pivot.empty:
            ax.set_visible(False); continue

        arr  = pivot.values.astype(float)
        mask = (arr > 0) & np.isfinite(arr)
        if not mask.any(): continue
        vmin = arr[mask].min()
        vmax = arr[mask].max()

        im = ax.imshow(arr, aspect="auto", cmap=CMAP_HEAT,
                       norm=LogNorm(vmin=vmin, vmax=vmax),
                       interpolation="nearest")
        cb = plt.colorbar(im, ax=ax, pad=0.03, shrink=0.88)
        cb.set_label("Median Spill", fontsize=8)
        cb.ax.yaxis.set_major_formatter(ticker.FuncFormatter(log_fmt))
        cb.ax.tick_params(labelsize=7)

        ax.set_xticks(range(len(labs)))
        ax.set_xticklabels(labs, rotation=45, ha="right", fontsize=7)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([int(q) for q in pivot.index], fontsize=8)
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel("Qubits", fontsize=9)
        ax.set_title(eng.capitalize(), color=ENGINE_PALETTE[eng],
                     fontweight="bold")

    fig.suptitle(f"Median Spill Heat-Map  (Qubits × {xlabel})",
                 fontsize=13, y=1.01)
    save(fig, outdir, outfile)


def plot_heatmap_qubit_sparsity(df, outdir):
    _heatmap(df, "statevector_saved_sparsity", (0, 1), 8,
             "Sparsity", "heatmap_qubit_sparsity.pdf", outdir)


def plot_heatmap_qubit_entropy(df, outdir):
    if "statevector_shannon_entropy" not in df.columns:
        print("  [skip] no entropy column"); return
    sub = df.dropna(subset=["statevector_shannon_entropy"])
    if sub.empty: return
    elo = sub["statevector_shannon_entropy"].min()
    ehi = sub["statevector_shannon_entropy"].max()
    _heatmap(df, "statevector_shannon_entropy", (elo, ehi), 8,
             "Shannon Entropy (bits)", "heatmap_qubit_entropy.pdf", outdir)


# ── Summary stats ─────────────────────────────────────────────────────────────
def export_summary(df, outdir):
    agg = (df.groupby(["engine", "num_qubits", "cap_gb"])["spill_proxy_bytes"]
             .agg(n="count",
                  mean="mean",
                  median="median",
                  std="std",
                  p25=lambda x: x.quantile(0.25),
                  p75=lambda x: x.quantile(0.75),
                  p95=lambda x: x.quantile(0.95),
                  max="max")
             .reset_index())
    for col in ["mean", "median", "std", "p25", "p75", "p95", "max"]:
        agg[f"{col}_gb"] = (agg[col] * BYTES_TO_GB).round(5)

    path = os.path.join(outdir, "summary_stats.csv")
    agg.to_csv(path, index=False)
    print(f"  saved -> {path}")
    print(agg[["engine", "num_qubits", "cap_gb", "n",
               "median_gb", "p25_gb", "p75_gb", "p95_gb", "max_gb"]]
          .to_string(index=False))


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Spill behaviour analysis – SIGMOD OOC evaluation")
    ap.add_argument("--results", default="results.csv")
    ap.add_argument("--sampled", default="sampled_output.csv")
    ap.add_argument("--outdir",  default="figures")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    print("=" * 60)
    print("Loading data ...")
    df = load_data(args.results, args.sampled)
    print("=" * 60)

    steps = [
        (" [1/11] Spill vs qubit count",        plot_spill_vs_qubits),
        (" [2/11] Sparsity scatter",             plot_spill_vs_sparsity_scatter),
        (" [3/11] Sparsity bins",                plot_spill_vs_sparsity_bins),
        (" [4/11] Entropy scatter",              plot_spill_vs_entropy_scatter),
        (" [5/11] Entropy bins",                 plot_spill_vs_entropy_bins),
        (" [6/11] Entropy x sparsity joint",     plot_entropy_vs_sparsity_joint),
        (" [7/11] Box plots by engine",          plot_boxplot_by_engine),
        (" [8/11] Box plots by qubit x engine",  plot_boxplot_by_qubits_engine),
        (" [9/11] Box plots by cap x engine",    plot_boxplot_by_cap),
        ("[10/11] Heat-map qubit x sparsity",    plot_heatmap_qubit_sparsity),
        ("[11/11] Heat-map qubit x entropy",     plot_heatmap_qubit_entropy),
    ]

    for label, fn in steps:
        print(label)
        fn(df, args.outdir)

    print("=" * 60)
    print("Summary statistics ...")
    export_summary(df, args.outdir)
    print("=" * 60)
    print(f"Done. All outputs in ./{args.outdir}/")


if __name__ == "__main__":
    main()