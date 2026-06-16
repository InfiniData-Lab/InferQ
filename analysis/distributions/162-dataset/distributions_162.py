"""
plot_distributions.py
=====================
Generates benchmark dataset characterization figures for SIGMOD paper.
Saves all figures to ./distributions/

Usage:
    python plot_distributions.py
    python plot_distributions.py --data path/to/data.parquet
"""

import argparse
import logging
import os
import sys
import warnings
from collections import Counter
from itertools import product

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import TwoSlopeNorm

warnings.filterwarnings("ignore")

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ── Feature definitions ───────────────────────────────────────────────────────
SQL = [
    "num_joins", "num_and_clauses", "num_select_columns",
    "num_agg_funcs", "num_where_clauses", "num_eq_predicates",
]
GRAPH = [
    "edge_count", "max_degree", "min_cut", "diameter", "radius",
    "average_degree", "average_clustering_coefficient",
    "average_shortest_path_length", "central_point_of_dominance",
    "std_dev_adjacency_matrix",
]
STATIC = [
    "num_qubits", "width", "depth", "circuit_size", "pauli_gate_count",
    "two_qubit_gate_count", "two_qubit_gate_percentage",
    "locality_ratio", "idling_score", "density_score",
]
DYNAMIC = ["statevector_saved_sparsity", "statevector_saved_shannon_entropy"]

RDBMS_METHODS  = ["sqlite", "ducksql", "psql"]
QISKIT_METHODS = ["density_matrix", "matrix_product_state",
                  "extended_stabilizer", "statevector"]

OUT_DIR = "distributions"

# ── Style ─────────────────────────────────────────────────────────────────────
PALETTE      = "muted"
ACCENT_COLOR = "#4C72B0"
FIG_DPI      = 150
HIST_BINS    = 30

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
    """Return only columns that actually exist in df."""
    return [c for c in cols if c in df.columns]


def find_method_cols(df: pd.DataFrame, methods: list[str],
                     suffixes: tuple[str, ...]) -> list[str]:
    return [c for m in methods for c in df.columns
            if m in c and c.endswith(suffixes)]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Gate-mix bar chart
# ═══════════════════════════════════════════════════════════════════════════════
def plot_gate_mix(df: pd.DataFrame) -> None:
    log.info("[1/7] Gate-mix frequency chart …")
    if "gate_counts" not in df.columns:
        log.warning("  'gate_counts' column not found – skipping.")
        return

    counter: Counter = Counter()
    for row in df["gate_counts"].dropna():
        d = row if isinstance(row, dict) else {}
        counter.update(d)

    if not counter:
        log.warning("  No gate data found – skipping.")
        return

    top_n   = 20
    gates   = [g for g, _ in counter.most_common(top_n)]
    counts  = [counter[g] for g in gates]
    total   = sum(counter.values())
    pcts    = [100 * c / total for c in counts]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(gates[::-1], pcts[::-1], color=ACCENT_COLOR, alpha=0.85)
    ax.bar_label(bars, labels=[f"{p:.1f}%" for p in pcts[::-1]],
                 padding=3, fontsize=8)
    ax.set_xlabel("Share of total gate count (%)")
    ax.set_title(f"Gate-type distribution (top {top_n}, N={len(df)} circuits)")
    fig.tight_layout()
    save(fig, "01_gate_mix.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Circuit structure histograms (STATIC)
# ═══════════════════════════════════════════════════════════════════════════════
def plot_circuit_structure(df: pd.DataFrame) -> None:
    log.info("[2/7] Circuit structure (static features) histograms …")
    cols = present_cols(df, STATIC)
    if not cols:
        log.warning("  No STATIC columns found – skipping.")
        return

    ncols = 4
    nrows = int(np.ceil(len(cols) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows))
    axes = axes.flatten()

    for i, col in enumerate(cols):
        series = df[col].dropna()
        axes[i].hist(series, bins=HIST_BINS, color=ACCENT_COLOR,
                     edgecolor="white", alpha=0.85)
        axes[i].set_title(col.replace("_", " "), fontsize=9)
        axes[i].set_xlabel("value", fontsize=8)
        axes[i].set_ylabel("count",  fontsize=8)
        axes[i].tick_params(labelsize=7)

    for j in range(len(cols), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("Static circuit feature distributions", fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, "02_static_features.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Graph feature histograms
# ═══════════════════════════════════════════════════════════════════════════════
def plot_graph_features(df: pd.DataFrame) -> None:
    log.info("[3/7] Interaction-graph feature histograms …")
    cols = present_cols(df, GRAPH)
    if not cols:
        log.warning("  No GRAPH columns found – skipping.")
        return

    ncols = 4
    nrows = int(np.ceil(len(cols) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows))
    axes = axes.flatten()

    for i, col in enumerate(cols):
        series = df[col].dropna()
        axes[i].hist(series, bins=HIST_BINS, color="#E88B4E",
                     edgecolor="white", alpha=0.85)
        axes[i].set_title(col.replace("_", " "), fontsize=9)
        axes[i].set_xlabel("value", fontsize=8)
        axes[i].set_ylabel("count",  fontsize=8)
        axes[i].tick_params(labelsize=7)

    for j in range(len(cols), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("Interaction-graph feature distributions", fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, "03_graph_features.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SQL complexity histograms
# ═══════════════════════════════════════════════════════════════════════════════
def plot_sql_features(df: pd.DataFrame) -> None:
    log.info("[4/7] SQL complexity feature histograms …")
    cols = present_cols(df, SQL)
    if not cols:
        log.warning("  No SQL columns found – skipping.")
        return

    ncols = 3
    nrows = int(np.ceil(len(cols) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3 * nrows))
    axes = axes.flatten()

    for i, col in enumerate(cols):
        series = df[col].dropna().astype(int)
        axes[i].hist(series, bins=max(series.max(), 1),
                     color="#5BAD6F", edgecolor="white", alpha=0.85)
        axes[i].set_title(col.replace("_", " "), fontsize=10)
        axes[i].set_xlabel("count",  fontsize=9)
        axes[i].set_ylabel("# circuits", fontsize=9)
        axes[i].xaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    for j in range(len(cols), len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("SQL query complexity distributions", fontsize=13, y=1.01)
    fig.tight_layout()
    save(fig, "04_sql_features.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Dynamic features scatter + marginal histograms
# ═══════════════════════════════════════════════════════════════════════════════
def plot_dynamic_features(df: pd.DataFrame) -> None:
    log.info("[5/7] Dynamic features (sparsity vs entropy) …")
    sp_col  = "statevector_saved_sparsity"
    ent_col = "statevector_saved_shannon_entropy"
    if sp_col not in df.columns or ent_col not in df.columns:
        log.warning("  Dynamic columns not found – skipping.")
        return

    sub = df[[sp_col, ent_col]].dropna()
    g   = sns.jointplot(data=sub, x=sp_col, y=ent_col,
                        kind="hex", height=6,
                        marginal_kws={"bins": HIST_BINS},
                        joint_kws={"gridsize": 35, "cmap": "Blues"})
    g.set_axis_labels("Sparsity", "Shannon Entropy", fontsize=11)
    g.figure.suptitle("Statevector dynamic feature distribution", y=1.01)
    save(g.figure, "05_dynamic_features.png")


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Execution time / memory box plots per method
# ═══════════════════════════════════════════════════════════════════════════════
def plot_method_perf(df: pd.DataFrame) -> None:
    log.info("[6/7] Per-method execution time & memory box plots …")
    all_methods = RDBMS_METHODS + QISKIT_METHODS
    tcols = find_method_cols(df, all_methods, ("time_s", "execution_time"))
    mcols = find_method_cols(df, all_methods, ("memory_usage", "mb"))

    for metric_cols, label, unit, fname in [
        (tcols, "Execution time", "s",  "06a_time_boxplot.png"),
        (mcols, "Memory usage",   "MB", "06b_memory_boxplot.png"),
    ]:
        if not metric_cols:
            log.warning("  No %s columns found – skipping.", label.lower())
            continue

        plot_df = df[metric_cols].copy()
        # Tidy column names for display
        plot_df.columns = [c.replace("_execution_time", "")
                            .replace("_time_s", "")
                            .replace("_memory_usage", "")
                            .replace("_mb", "")
                           for c in plot_df.columns]

        melted = plot_df.melt(var_name="Method", value_name=label).dropna()

        # Colour by RDBMS vs Qiskit
        rdbms_set   = set(RDBMS_METHODS)
        method_type = melted["Method"].apply(
            lambda m: "RDBMS" if any(r in m for r in rdbms_set) else "Qiskit"
        )
        palette = {"RDBMS": "#4C72B0", "Qiskit": "#DD8452"}

        fig, ax = plt.subplots(figsize=(max(8, len(plot_df.columns) * 1.2), 5))
        sns.boxplot(data=melted, x="Method", y=label,
                    hue=method_type, palette=palette,
                    order=melted["Method"].unique(),
                    flierprops={"marker": ".", "alpha": 0.4},
                    ax=ax)
        ax.set_yscale("log")
        ax.set_ylabel(f"{label} ({unit}, log scale)")
        ax.set_xlabel("")
        ax.set_title(f"{label} distribution per method")
        ax.tick_params(axis="x", rotation=30)
        ax.legend(title="System type", loc="upper right")
        fig.tight_layout()
        save(fig, fname)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. RDBMS vs Qiskit — ratio vs dynamic metrics
# ═══════════════════════════════════════════════════════════════════════════════
def plot_rdbms_vs_qiskit_dynamic(df: pd.DataFrame) -> None:
    """
    For every (rdbms_method, qiskit_method) pair, compute log2 ratio of
    time (and memory) and scatter-plot against sparsity & entropy.
    Colour encodes sign: blue = RDBMS faster/cheaper, orange = Qiskit better.
    """
    log.info("[7/7] RDBMS vs Qiskit ratio plots against dynamic features …")

    sp_col  = "statevector_saved_sparsity"
    ent_col = "statevector_saved_shannon_entropy"
    if sp_col not in df.columns or ent_col not in df.columns:
        log.warning("  Dynamic columns missing – skipping ratio plots.")
        return

    all_methods = RDBMS_METHODS + QISKIT_METHODS
    tcols = find_method_cols(df, all_methods, ("time_s", "execution_time"))
    mcols = find_method_cols(df, all_methods, ("memory_usage", "mb"))

    def method_col(cols, method):
        return next((c for c in cols if method in c), None)

    for metric_cols, metric_label, unit, prefix in [
        (tcols, "Time",   "s",  "07_time"),
        (mcols, "Memory", "MB", "07_mem"),
    ]:
        if not metric_cols:
            log.warning("  No %s columns for ratio plot – skipping.", metric_label)
            continue

        pairs = list(product(RDBMS_METHODS, QISKIT_METHODS))
        valid_pairs = [
            (r, q) for r, q in pairs
            if method_col(metric_cols, r) and method_col(metric_cols, q)
        ]
        if not valid_pairs:
            log.warning("  No complete (RDBMS, Qiskit) pairs for %s.", metric_label)
            continue

        log.info("  Building %d pair plots for %s …", len(valid_pairs), metric_label)

        for dynamic_col, dyn_label in [(sp_col, "Sparsity"), (ent_col, "Shannon Entropy")]:

            ncols = min(3, len(valid_pairs))
            nrows = int(np.ceil(len(valid_pairs) / ncols))
            fig, axes = plt.subplots(nrows, ncols,
                                     figsize=(5 * ncols, 4 * nrows),
                                     squeeze=False)
            axes = axes.flatten()

            for idx, (rm, qm) in enumerate(valid_pairs):
                rc = method_col(metric_cols, rm)
                qc = method_col(metric_cols, qm)

                sub = df[[dynamic_col, rc, qc]].dropna().copy()
                sub = sub[(sub[rc] > 0) & (sub[qc] > 0)]
                if sub.empty:
                    axes[idx].set_visible(False)
                    continue

                ratio = np.log2(sub[rc] / sub[qc])  # >0 means RDBMS slower

                # Symmetric colour scale centred at 0
                vmax  = np.abs(ratio).quantile(0.98)
                norm  = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)
                cmap  = "RdBu_r"   # red=RDBMS worse, blue=RDBMS better

                sc = axes[idx].scatter(
                    sub[dynamic_col], ratio,
                    c=ratio, cmap=cmap, norm=norm,
                    alpha=0.55, s=18, linewidths=0,
                )
                axes[idx].axhline(0, color="grey", linewidth=0.8, linestyle="--")
                axes[idx].set_xlabel(dyn_label, fontsize=9)
                axes[idx].set_ylabel(f"log₂({rm}/{qm})", fontsize=9)
                axes[idx].set_title(f"{rm} vs {qm}", fontsize=10)

                cb = fig.colorbar(sc, ax=axes[idx], pad=0.02)
                cb.set_label("log₂ ratio", fontsize=7)
                cb.ax.tick_params(labelsize=6)

            for j in range(len(valid_pairs), len(axes)):
                axes[j].set_visible(False)

            dyn_slug = dyn_label.lower().replace(" ", "_")
            fname = f"{prefix}_rdbms_vs_qiskit_{dyn_slug}.png"
            fig.suptitle(
                f"{metric_label}: RDBMS vs Qiskit — coloured by advantage\n"
                f"x-axis: {dyn_label}   |   blue = RDBMS faster, red = Qiskit faster",
                fontsize=11, y=1.01,
            )
            fig.tight_layout()
            save(fig, fname)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark distribution figures.")
    parser.add_argument(
        "--data", default="training_data/rdbms_all_methods_training_data.parquet",
        help="Path to the parquet file (default: training_data/rdbms_all_methods_training_data.parquet)",
    )
    args = parser.parse_args()

    # ── Output directory ──────────────────────────────────────────────────────
    os.makedirs(OUT_DIR, exist_ok=True)
    log.info("Output directory: %s/", OUT_DIR)

    # ── Load data ─────────────────────────────────────────────────────────────
    log.info("Loading data from %s …", args.data)
    df_full = pd.read_parquet(args.data)    
    print(f"Dataset size : {len(df_full)}")
    log.info("  Loaded %d rows × %d columns", *df_full.shape)
    log.info("  Columns: %s", list(df_full.columns[:10]) + (["…"] if len(df_full.columns) > 10 else []))

    # ── Drop statevector_saved_e* and statevector_saved_m* columns ────────────
    drop_cols = [c for c in df_full.columns
                 if "statevector_saved_e" in c or "statevector_saved_m" in c]
    if drop_cols:
        df_full.drop(columns=drop_cols, inplace=True)
        log.info("  Dropped %d column(s): %s", len(drop_cols), drop_cols)
    else:
        log.info("  No statevector_saved_e*/m* columns found to drop.")

    # ── Run all plots ─────────────────────────────────────────────────────────
    plot_gate_mix(df_full)
    plot_circuit_structure(df_full)
    plot_graph_features(df_full)
    plot_sql_features(df_full)
    plot_dynamic_features(df_full)
    plot_method_perf(df_full)
    plot_rdbms_vs_qiskit_dynamic(df_full)

    log.info("Done! All figures saved to ./%s/", OUT_DIR)


if __name__ == "__main__":
    main()