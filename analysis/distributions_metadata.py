"""
distributions_metadata.py
=========================
Aggregate circuit/workload distribution figures over the full metadata corpus
(data/metadata/metadata_part_*.parquet). Companion to analysis/distributions.py
(which runs on the training_data parquet).

Addresses SIGMOD revision E4 (R2:O1, R2:O3): aggregate gate mix, depth/width,
and interaction-graph statistics across the benchmark dataset.

Outputs:
    analysis/distributions_metadata/
        01_gate_mix.png            -- top-N gate frequencies, by family
        02_circuit_structure.png   -- num_qubits, depth, size, 2Q gate stats, ...
        03_depth_vs_width.png      -- 2-D coverage heatmap (qubits x depth)
        04_graph_features.png      -- interaction-graph statistics
        05_dynamic_features.png    -- sparsity vs Shannon entropy
        06_family_breakdown.png    -- key metrics overlaid per workload family
        summary_stats.csv          -- per-feature count/median/p5/p95

Usage:
    python analysis/distributions_metadata.py
    python analysis/distributions_metadata.py --data 'data/metadata/metadata_part_*.parquet'
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import re
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
    ["name", "gate_counts"]
    + STRUCTURE + GRAPH + DYNAMIC
)

OUT_DIR = os.path.join(os.path.dirname(__file__), "distributions_metadata")

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

FAMILY_PALETTE = {
    "HierarchicalCircuit": "#4C72B0",
    "Random":              "#DD8452",
    "Other":               "#8172B2",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def save(fig: plt.Figure, name: str) -> None:
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    log.info("  saved → %s", path)


def present_cols(df: pd.DataFrame, cols: list[str]) -> list[str]:
    return [c for c in cols if c in df.columns]


def family_of(name: object) -> str:
    if not isinstance(name, str):
        return "Other"
    if name.startswith("HierarchicalCircuit"):
        return "HierarchicalCircuit"
    if re.match(r"^circuit-\d", name):
        return "Random"
    return "Other"


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

    df["family"] = df["name"].apply(family_of)
    log.info("Family counts: %s", df["family"].value_counts().to_dict())
    return df


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Gate-mix bar chart (overall + per family)
# ═══════════════════════════════════════════════════════════════════════════════
def plot_gate_mix(df: pd.DataFrame) -> None:
    log.info("[1/6] Gate-mix frequency chart …")
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

    families = list(df["family"].unique())
    family_counters: dict[str, Counter] = {f: Counter() for f in families}
    overall: Counter = Counter()

    for fam, row in zip(df["family"].values, df["gate_counts"].values):
        d = parse(row)
        if not d:
            continue
        family_counters[fam].update(d)
        overall.update(d)

    if not overall:
        log.warning("  No gate data found – skipping.")
        return

    top_n  = 20
    gates  = [g for g, _ in overall.most_common(top_n)]
    total  = sum(overall.values())
    pcts   = [100 * overall[g] / total for g in gates]

    fig, (ax_a, ax_b) = plt.subplots(
        1, 2, figsize=(15, 6),
        gridspec_kw={"width_ratios": [1.0, 1.1]},
    )

    bars = ax_a.barh(gates[::-1], pcts[::-1],
                     color=ACCENT_COLOR, alpha=0.85)
    ax_a.bar_label(bars, labels=[f"{p:.1f}%" for p in pcts[::-1]],
                   padding=3, fontsize=8)
    ax_a.set_xlabel("Share of total gate count (%)")
    ax_a.set_title(f"(a) Overall gate mix (top {top_n}, N={len(df):,} circuits)")

    # Per-family stacked shares for the same top-N gates.
    fam_order = [f for f in ["HierarchicalCircuit", "Random", "Other"]
                 if f in family_counters and sum(family_counters[f].values()) > 0]
    bottom = np.zeros(len(gates))
    for fam in fam_order:
        fc = family_counters[fam]
        fam_total = sum(fc.values()) or 1
        shares = np.array([100 * fc.get(g, 0) / fam_total for g in gates])
        ax_b.bar(gates, shares, bottom=bottom,
                 label=fam, color=FAMILY_PALETTE.get(fam, "#888"),
                 alpha=0.85)
        bottom += shares
    ax_b.set_ylabel("Within-family share (%)  — stacked")
    ax_b.set_title("(b) Gate-mix composition per workload family")
    ax_b.tick_params(axis="x", rotation=45)
    ax_b.legend(title="Family", loc="upper right", fontsize=8)

    fig.tight_layout()
    save(fig, "01_gate_mix.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Circuit structure histograms
# ═══════════════════════════════════════════════════════════════════════════════
def plot_structure(df: pd.DataFrame) -> None:
    log.info("[2/6] Circuit structure (depth/width/...) …")
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
    log.info("[3/6] Depth × width coverage heatmap …")
    if "num_qubits" not in df.columns or "depth" not in df.columns:
        log.warning("  num_qubits / depth missing – skipping.")
        return

    sub = df[["num_qubits", "depth", "family"]].dropna()
    sub = sub[(sub["num_qubits"] > 0) & (sub["depth"] > 0)]
    if sub.empty:
        log.warning("  No positive (qubits, depth) – skipping.")
        return

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # (a) Heatmap of all circuits.
    q_max = int(sub["num_qubits"].max())
    d_max = int(sub["depth"].max())
    x_edges = np.arange(1, q_max + 2) - 0.5  # integer qubits
    y_edges = np.logspace(0, np.log10(d_max + 1), 40)
    h, xe, ye = np.histogram2d(sub["num_qubits"], sub["depth"],
                               bins=[x_edges, y_edges])
    pcm = axes[0].pcolormesh(xe, ye, h.T,
                             norm=LogNorm(vmin=1, vmax=max(h.max(), 1)),
                             cmap="viridis")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("num_qubits")
    axes[0].set_ylabel("depth (log)")
    axes[0].set_title(f"(a) (qubits, depth) coverage — {len(sub):,} circuits")
    cbar = fig.colorbar(pcm, ax=axes[0])
    cbar.set_label("# circuits (log)")

    # (b) Family-coloured scatter w/ marginal medians.
    for fam, g in sub.groupby("family"):
        axes[1].scatter(g["num_qubits"], g["depth"],
                        s=4, alpha=0.18,
                        color=FAMILY_PALETTE.get(fam, "#666"),
                        label=f"{fam} (n={len(g):,})")
    axes[1].set_yscale("log")
    axes[1].set_xlabel("num_qubits")
    axes[1].set_ylabel("depth (log)")
    axes[1].set_title("(b) Coverage per workload family")
    leg = axes[1].legend(title="Family", fontsize=8, markerscale=2,
                         loc="lower right")
    for lh in leg.legend_handles:
        lh.set_alpha(0.9)

    fig.tight_layout()
    save(fig, "03_depth_vs_width.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Interaction-graph feature histograms
# ═══════════════════════════════════════════════════════════════════════════════
def plot_graph_features(df: pd.DataFrame) -> None:
    log.info("[4/6] Interaction-graph features …")
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
    log.info("[5/6] Dynamic feature joint plot …")
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
# 6. Family breakdown overlay (depth, width, edges, 2-q %)
# ═══════════════════════════════════════════════════════════════════════════════
def plot_family_breakdown(df: pd.DataFrame) -> None:
    log.info("[6/6] Per-family overlay on key metrics …")
    metrics = [
        ("num_qubits",              False, "(a) num_qubits"),
        ("depth",                   True,  "(b) depth (log)"),
        ("edge_count",              True,  "(c) edge_count (log)"),
        ("two_qubit_gate_percentage", False, "(d) 2-qubit gate %"),
    ]
    metrics = [m for m in metrics if m[0] in df.columns]
    if not metrics:
        log.warning("  No family-overlay metrics available.")
        return

    families = [f for f in ["HierarchicalCircuit", "Random", "Other"]
                if (df["family"] == f).any()]

    ncols = 2
    nrows = int(np.ceil(len(metrics) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 4 * nrows))
    axes = axes.flatten()

    for i, (col, use_log, title) in enumerate(metrics):
        ax = axes[i]
        full = df[col].dropna()
        if full.empty:
            ax.set_visible(False)
            continue

        if use_log:
            full_pos = full[full > 0]
            if full_pos.empty:
                ax.set_visible(False)
                continue
            bins = np.logspace(np.log10(full_pos.min()),
                               np.log10(full_pos.max() + 1), HIST_BINS)
            ax.set_xscale("log")
        else:
            bins = np.linspace(full.min(), full.max(), HIST_BINS)

        for fam in families:
            s = df.loc[df["family"] == fam, col].dropna()
            if use_log:
                s = s[s > 0]
            if s.empty:
                continue
            ax.hist(s, bins=bins,
                    color=FAMILY_PALETTE.get(fam, "#666"),
                    alpha=0.55, label=f"{fam} (n={len(s):,})",
                    edgecolor="white")

        ax.set_title(title, fontsize=11)
        ax.set_xlabel(col)
        ax.set_ylabel("# circuits")
        ax.legend(fontsize=8, loc="best")

    for j in range(len(metrics), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("Workload family comparison on key circuit metrics",
                 fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, "06_family_breakdown.png")


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
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    log.info("Output directory: %s/", OUT_DIR)

    df = load_corpus(args.data)

    plot_gate_mix(df)
    plot_structure(df)
    plot_depth_vs_width(df)
    plot_graph_features(df)
    plot_dynamic(df)
    plot_family_breakdown(df)
    write_summary(df)

    log.info("Done! Figures + stats in %s/", OUT_DIR)


if __name__ == "__main__":
    main()
