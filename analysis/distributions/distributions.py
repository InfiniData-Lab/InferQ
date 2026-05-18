"""
distributions.py
================
Aggregate circuit/workload distribution figures over a benchmark parquet
corpus (defaults to data/metadata/metadata_part_*.parquet).

Addresses SIGMOD revision E4 (R2:O1, R2:O3): aggregate gate mix, depth/width,
and interaction-graph statistics across the benchmark dataset.

Outputs (default `analysis/distributions/`, override with --out):
    01_gate_mix.png            -- top-N gate frequencies
    02_circuit_structure.png   -- num_qubits, depth, size, 2Q gate stats, ...
    03_depth_vs_width.png      -- 2-D coverage heatmap (qubits x depth)
    04_graph_features.png      -- interaction-graph statistics
    05_dynamic_features.png    -- sparsity vs Shannon entropy
    summary_stats.csv          -- per-feature count/median/p5/p95

Usage:
    python analysis/distributions/distributions.py
    python analysis/distributions/distributions.py \\
        --data analysis/training_data/estimator_training_data.parquet \\
        --out  analysis/distributions_estimator
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys
import warnings
from collections import Counter

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import LogNorm

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Feature groups ────────────────────────────────────────────────────────────
STRUCTURE = [
    "num_qubits", "width", "depth", "circuit_size",
    "two_qubit_gate_count", "two_qubit_gate_percentage",
    "pauli_gate_count", "locality_ratio", "idling_score", "density_score",
]
GRAPH = [
    "node_count", "edge_count", "max_degree", "average_degree",
    "average_clustering_coefficient", "average_shortest_path_length",
    "diameter", "radius", "min_cut_upper",
    "central_point_of_dominance", "std_dev_adjacency_matrix", "igdepth",
]
DYNAMIC = ["statevector_saved_sparsity", "statevector_saved_shannon_entropy"]

# Columns we read; everything else stays on disk.
NEEDED_COLS = (
    ["gate_counts"]
    + STRUCTURE + GRAPH + DYNAMIC
)

DEFAULT_OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = DEFAULT_OUT_DIR

ACCENT_COLOR = "#4C72B0"
GRAPH_COLOR  = "#E88B4E"
STRUCT_COLOR = "#5BAD6F"
FIG_DPI      = 150
HIST_BINS    = 40

plt.rcParams.update({
    "font.family":       "DejaVu Sans",
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.grid":         True,
    "grid.alpha":        0.3,
    "grid.linestyle":    "--",
    "figure.dpi":        FIG_DPI,
})

# ── Helpers ───────────────────────────────────────────────────────────────────
def save(fig: plt.Figure, name: str) -> None:
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    log.info("  saved → %s", path)


def present_cols(df: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if c in df.columns]


def load_corpus(pattern: str) -> pd.DataFrame:
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No metadata parquet files match: {pattern}")
    log.info("Loading %d parquet file(s) …", len(files))

    # Probe one file to keep only existing columns.
    sample = pd.read_parquet(files[0])
    keep = [c for c in NEEDED_COLS if c in sample.columns]
    missing = [c for c in NEEDED_COLS if c not in sample.columns]
    if missing:
        log.warning("  Columns not present in source, skipping: %s", missing)

    parts = []
    for f in files:
        parts.append(pd.read_parquet(f, columns=keep))
        log.info("  %s: %d rows", os.path.basename(f), len(parts[-1]))
    df = pd.concat(parts, ignore_index=True)
    log.info("Corpus: %d rows × %d columns", *df.shape)
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Gate-mix bar chart
# ═══════════════════════════════════════════════════════════════════════════════
def plot_gate_mix(df: pd.DataFrame) -> None:
    log.info("[1/5] Gate-mix frequency chart …")
    if "gate_counts" not in df.columns:
        log.warning("  'gate_counts' column not present – skipping.")
        return

    def parse(row: object) -> dict:
        if isinstance(row, dict):
            return row
        if isinstance(row, str):
            try:
                d = json.loads(row)
                return d if isinstance(d, dict) else {}
            except Exception:
                return {}
        return {}

    overall: Counter = Counter()
    for row in df["gate_counts"].values:
        d = parse(row)
        if d:
            overall.update(d)

    if not overall:
        log.warning("  No gate data found – skipping.")
        return

    top_n  = 20
    gates  = [g for g, _ in overall.most_common(top_n)]
    total  = sum(overall.values())
    pcts   = [100 * overall[g] / total for g in gates]

    fig, ax = plt.subplots(figsize=(9, 6))
    bars = ax.barh(gates[::-1], pcts[::-1],
                   color=ACCENT_COLOR, alpha=0.85)
    ax.bar_label(bars, labels=[f"{p:.1f}%" for p in pcts[::-1]],
                 padding=3, fontsize=8)
    ax.set_xlabel("Share of total gate count (%)")
    ax.set_title(f"Overall gate mix (top {top_n}, N={len(df):,} circuits)")

    fig.tight_layout()
    save(fig, "01_gate_mix.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Circuit structure histograms
# ═══════════════════════════════════════════════════════════════════════════════
def plot_structure(df: pd.DataFrame) -> None:
    log.info("[2/5] Circuit structure (depth/width/...) …")
    cols = present_cols(df, STRUCTURE)
    if not cols:
        log.warning("  No structural columns – skipping.")
        return

    ncols = 4
    nrows = int(np.ceil(len(cols) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows))
    axes = axes.flatten()

    log_scale = {"depth", "circuit_size", "two_qubit_gate_count", "pauli_gate_count"}

    for i, col in enumerate(cols):
        s = df[col].dropna()
        if s.empty:
            axes[i].set_visible(False)
            continue
        ax = axes[i]

        if col in log_scale and (s > 0).any():
            s_pos = s[s > 0]
            if not s_pos.empty:
                bins = np.logspace(np.log10(max(s_pos.min(), 1)),
                                   np.log10(s_pos.max() + 1), HIST_BINS)
                ax.hist(s_pos, bins=bins, color=STRUCT_COLOR,
                        edgecolor="white", alpha=0.85)
                ax.set_xscale("log")
        else:
            ax.hist(s, bins=HIST_BINS, color=STRUCT_COLOR,
                    edgecolor="white", alpha=0.85)

        ax.set_title(col.replace("_", " "), fontsize=10)
        ax.set_xlabel("value", fontsize=8)
        ax.set_ylabel("# circuits", fontsize=8)
        ax.tick_params(labelsize=7)

        med = float(s.median())
        ax.axvline(med, color="black", linestyle="--", linewidth=0.8, alpha=0.7)
        ax.text(0.97, 0.95, f"median={med:g}", transform=ax.transAxes,
                fontsize=7, ha="right", va="top",
                bbox=dict(boxstyle="round,pad=0.2", fc="white",
                          ec="grey", alpha=0.7))

    for j in range(len(cols), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("Circuit structural feature distributions "
                 f"(N={len(df):,})", fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, "02_circuit_structure.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Depth × width 2-D coverage heatmap
# ═══════════════════════════════════════════════════════════════════════════════
def plot_depth_vs_width(df: pd.DataFrame) -> None:
    log.info("[3/5] Depth × width coverage heatmap …")
    if "num_qubits" not in df.columns or "depth" not in df.columns:
        log.warning("  num_qubits / depth missing – skipping.")
        return

    sub = df[["num_qubits", "depth"]].dropna()
    sub = sub[(sub["num_qubits"] > 0) & (sub["depth"] > 0)]
    if sub.empty:
        log.warning("  No positive (qubits, depth) – skipping.")
        return

    fig, ax = plt.subplots(figsize=(7, 5.5))

    q_max = int(sub["num_qubits"].max())
    d_max = int(sub["depth"].max())
    x_edges = np.arange(1, q_max + 2) - 0.5  # integer qubits
    y_edges = np.logspace(0, np.log10(d_max + 1), 40)
    h, xe, ye = np.histogram2d(sub["num_qubits"], sub["depth"],
                               bins=[x_edges, y_edges])
    pcm = ax.pcolormesh(xe, ye, h.T,
                        norm=LogNorm(vmin=1, vmax=max(h.max(), 1)),
                        cmap="viridis")
    ax.set_yscale("log")
    ax.set_xlabel("num_qubits")
    ax.set_ylabel("depth (log)")
    ax.set_title(f"(qubits, depth) coverage — {len(sub):,} circuits")
    cbar = fig.colorbar(pcm, ax=ax)
    cbar.set_label("# circuits (log)")

    fig.tight_layout()
    save(fig, "03_depth_vs_width.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Interaction-graph feature histograms
# ═══════════════════════════════════════════════════════════════════════════════
def plot_graph_features(df: pd.DataFrame) -> None:
    log.info("[4/5] Interaction-graph features …")
    cols = present_cols(df, GRAPH)
    if not cols:
        log.warning("  No graph columns – skipping.")
        return

    ncols = 4
    nrows = int(np.ceil(len(cols) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows))
    axes = axes.flatten()

    log_scale = {"edge_count", "max_degree", "igdepth"}

    for i, col in enumerate(cols):
        s = df[col].dropna()
        if s.empty:
            axes[i].set_visible(False)
            continue
        ax = axes[i]

        if col in log_scale and (s > 0).any():
            s_pos = s[s > 0]
            bins = np.logspace(np.log10(max(s_pos.min(), 1)),
                               np.log10(s_pos.max() + 1), HIST_BINS)
            ax.hist(s_pos, bins=bins, color=GRAPH_COLOR,
                    edgecolor="white", alpha=0.85)
            ax.set_xscale("log")
        else:
            ax.hist(s, bins=HIST_BINS, color=GRAPH_COLOR,
                    edgecolor="white", alpha=0.85)

        ax.set_title(col.replace("_", " "), fontsize=10)
        ax.set_xlabel("value", fontsize=8)
        ax.set_ylabel("# circuits", fontsize=8)
        ax.tick_params(labelsize=7)

        med = float(s.median())
        ax.axvline(med, color="black", linestyle="--", linewidth=0.8, alpha=0.7)
        ax.text(0.97, 0.95, f"median={med:.3g}", transform=ax.transAxes,
                fontsize=7, ha="right", va="top",
                bbox=dict(boxstyle="round,pad=0.2", fc="white",
                          ec="grey", alpha=0.7))

    for j in range(len(cols), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle(f"Interaction-graph feature distributions (N={len(df):,})",
                 fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, "04_graph_features.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Dynamic features: sparsity vs Shannon entropy
# ═══════════════════════════════════════════════════════════════════════════════
def plot_dynamic(df: pd.DataFrame) -> None:
    log.info("[5/5] Dynamic feature joint plot …")
    sp_col, ent_col = DYNAMIC
    if sp_col not in df.columns or ent_col not in df.columns:
        log.warning("  Dynamic columns missing – skipping.")
        return

    sub = df[[sp_col, ent_col]].dropna()
    if sub.empty:
        log.warning("  No dynamic samples – skipping.")
        return

    g = sns.jointplot(data=sub, x=sp_col, y=ent_col,
                      kind="hex", height=6,
                      marginal_kws={"bins": HIST_BINS},
                      joint_kws={"gridsize": 40, "cmap": "Blues"})
    g.set_axis_labels("Statevector sparsity", "Shannon entropy", fontsize=11)
    g.figure.suptitle(
        f"Statevector dynamic features (n={len(sub):,} of {len(df):,})",
        y=1.01)
    save(g.figure, "05_dynamic_features.png")


# ═══════════════════════════════════════════════════════════════════════════════
# Summary stats table
# ═══════════════════════════════════════════════════════════════════════════════
def write_summary(df: pd.DataFrame) -> None:
    log.info("Writing summary_stats.csv …")
    feats = present_cols(df, STRUCTURE + GRAPH + DYNAMIC)
    rows = []
    for f in feats:
        s = df[f].dropna()
        if s.empty:
            continue
        rows.append({
            "feature": f,
            "n":       int(s.shape[0]),
            "mean":    float(s.mean()),
            "std":     float(s.std()),
            "min":     float(s.min()),
            "p05":     float(s.quantile(0.05)),
            "median":  float(s.median()),
            "p95":     float(s.quantile(0.95)),
            "max":     float(s.max()),
        })
    out = pd.DataFrame(rows)
    path = os.path.join(OUT_DIR, "summary_stats.csv")
    out.to_csv(path, index=False)
    log.info("  saved → %s  (%d features)", path, len(out))


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate distribution figures for the metadata corpus.")
    parser.add_argument(
        "--data", default="data/metadata/metadata_part_*.parquet",
        help="Glob for metadata parquet files "
             "(default: data/metadata/metadata_part_*.parquet)",
    )
    parser.add_argument(
        "--out", default=DEFAULT_OUT_DIR,
        help=f"Output directory for figures + CSV (default: {DEFAULT_OUT_DIR})",
    )
    args = parser.parse_args()

    global OUT_DIR
    OUT_DIR = args.out
    os.makedirs(OUT_DIR, exist_ok=True)
    log.info("Output directory: %s/", OUT_DIR)

    df = load_corpus(args.data)

    plot_gate_mix(df)
    plot_structure(df)
    plot_depth_vs_width(df)
    plot_graph_features(df)
    plot_dynamic(df)
    write_summary(df)

    log.info("Done! Figures + stats in %s/", OUT_DIR)


if __name__ == "__main__":
    main()
