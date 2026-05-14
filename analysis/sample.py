"""
sample_circuits.py

Loads the estimator training parquet, filters to num_qubits in {20..25},
then draws a stratified sample so that every (num_qubits, sparsity_bin) cell
contributes exactly SAMPLES_PER_CELL rows — giving a flat joint distribution.

Output columns: RowKey, num_qubits, statevector_saved_sparsity
"""

import argparse
import pandas as pd

# ── config ────────────────────────────────────────────────────────────────────
INPUT_PATH      = "training_data/estimator_training_data.parquet"
OUTPUT_PATH     = "sampled_output.csv"

SPARSITY_COL    = "statevector_saved_sparsity"
ROWKEY_COL      = "RowKey"
NQUBITS_COL     = "num_qubits"

VALID_QUBITS    = [20, 21, 22, 23, 24, 25]
N_SPARSITY_BINS = 3    # equal-width sparsity bins per qubit level
SAMPLES_PER_CELL = 6  # rows to draw per (num_qubits, sparsity_bin) cell
RANDOM_STATE    = 42
# ─────────────────────────────────────────────────────────────────────────────


def load_and_filter(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=[ROWKEY_COL, NQUBITS_COL, SPARSITY_COL])
    print(f"Loaded {len(df):,} rows from {path!r}")

    df = df[df[NQUBITS_COL].isin(VALID_QUBITS)].copy()
    print(f"After num_qubits filter ({VALID_QUBITS}): {len(df):,} rows")

    df = df.dropna(subset=[SPARSITY_COL])
    print(f"After dropping NaN sparsity: {len(df):,} rows")
    return df


def stratified_sample(df: pd.DataFrame, n_bins: int, samples_per_cell: int) -> pd.DataFrame:
    """
    For each num_qubits level, bin sparsity into n_bins equal-width buckets,
    then draw exactly samples_per_cell rows from every (qubit, sparsity_bin)
    cell (with replacement if a cell has fewer rows than needed).

    This produces a flat distribution over both dimensions.
    """
    df["_sparsity_bin"] = pd.cut(
        df[SPARSITY_COL], bins=n_bins, labels=False, duplicates="drop"
    )

    print(f"\nCell counts before sampling (qubit × sparsity_bin):")
    parts = []
    for qubit in sorted(df[NQUBITS_COL].unique()):
        q_df = df[df[NQUBITS_COL] == qubit]
        for bin_id, group in q_df.groupby("_sparsity_bin"):
            replace = len(group) < samples_per_cell
            tag = " [with replacement]" if replace else ""
            print(f"  q={qubit}  bin {int(bin_id)}: {len(group):>6,} rows{tag}")
            parts.append(
                group.sample(n=samples_per_cell, replace=replace,
                             random_state=RANDOM_STATE)
            )

    n_cells = len(parts)
    sampled = pd.concat(parts).drop(columns=["_sparsity_bin"])
    sampled = sampled.sample(frac=1, random_state=RANDOM_STATE)  # shuffle
    print(f"\nSampled {len(sampled):,} rows total "
          f"({n_cells} cells × {samples_per_cell})")
    return sampled


def main(input_path: str, output_path: str,
         n_bins: int = N_SPARSITY_BINS,
         samples_per_cell: int = SAMPLES_PER_CELL) -> None:
    df = load_and_filter(input_path)

    sampled = stratified_sample(df, n_bins=n_bins, samples_per_cell=samples_per_cell)

    out = sampled[[ROWKEY_COL, NQUBITS_COL, SPARSITY_COL]]
    out.to_csv(output_path, index=False)
    print(f"\nSaved {len(out):,} rows → {output_path!r}")
    print(out.describe())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stratified circuit sampler")
    parser.add_argument("--input",  default=INPUT_PATH,  help="Path to input parquet")
    parser.add_argument("--output", default=OUTPUT_PATH, help="Path for output CSV")
    parser.add_argument("--samples-per-cell", type=int, default=SAMPLES_PER_CELL,
                        help="Rows per (num_qubits, sparsity_bin) cell (default %(default)s)")
    parser.add_argument("--n-bins", type=int, default=N_SPARSITY_BINS,
                        help="Number of sparsity bins per qubit level (default %(default)s)")
    args = parser.parse_args()

    main(args.input, args.output,
         n_bins=args.n_bins, samples_per_cell=args.samples_per_cell)