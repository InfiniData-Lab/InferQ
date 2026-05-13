"""
sample_circuits.py

Loads the estimator training parquet, filters to num_qubits in {25..30},
then draws a stratified sample so that sparsity bins are equally represented.

Output columns: rowkey, num_qubits, statevector_saved_sparsity
"""

import argparse
import pandas as pd
import numpy as np

# ── config ────────────────────────────────────────────────────────────────────
INPUT_PATH   = "training_data/estimator_training_data.parquet"
OUTPUT_PATH  = "sampled_output.csv"

SPARSITY_COL = "statevector_saved_sparsity"
ROWKEY_COL   = "RowKey"
NQUBITS_COL  = "num_qubits"

VALID_QUBITS = [25, 26, 27, 28, 29, 30]
N_SPARSITY_BINS = 3          # number of equal-width sparsity bins
SAMPLES_PER_BIN = 10       # how many rows to draw per sparsity bin
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


def stratified_sample(df: pd.DataFrame, n_bins: int, samples_per_bin: int) -> pd.DataFrame:
    """
    Bin sparsity into n_bins equal-width buckets and draw up to
    samples_per_bin rows from each bin (with replacement if a bin is smaller).
    This makes the output distribution uniform across sparsity.
    """
    df["_sparsity_bin"] = pd.cut(df[SPARSITY_COL], bins=n_bins, labels=False,
                                 duplicates="drop")

    bin_counts = df["_sparsity_bin"].value_counts().sort_index()
    print(f"\nSparsity bin counts before sampling:")
    for b, c in bin_counts.items():
        print(f"  bin {b:2d}: {c:>8,} rows")

    parts = []
    for bin_id, group in df.groupby("_sparsity_bin"):
        n = min(samples_per_bin, len(group))
        replace = len(group) < samples_per_bin
        if replace:
            print(f"  [warn] bin {bin_id} has only {len(group)} rows "
                  f"(< {samples_per_bin}); sampling with replacement")
        parts.append(group.sample(n=samples_per_bin, replace=replace,
                                  random_state=RANDOM_STATE))

    sampled = pd.concat(parts).drop(columns=["_sparsity_bin"])
    sampled = sampled.sample(frac=1, random_state=RANDOM_STATE)   # shuffle
    print(f"\nSampled {len(sampled):,} rows total  "
          f"({len(parts)} bins × {samples_per_bin})")
    return sampled


def main(input_path: str, output_path: str,
         n_bins: int = N_SPARSITY_BINS,
         samples_per_bin: int = SAMPLES_PER_BIN) -> None:
    df = load_and_filter(input_path)

    sampled = stratified_sample(df, n_bins=n_bins,
                                 samples_per_bin=samples_per_bin)

    # keep only the three relevant columns
    out = sampled[[ROWKEY_COL, NQUBITS_COL, SPARSITY_COL]]

    out.to_csv(output_path, index=False)
    print(f"\nSaved {len(out):,} rows → {output_path!r}")
    print(out.describe())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stratified circuit sampler")
    parser.add_argument("--input",  default=INPUT_PATH,  help="Path to input parquet")
    parser.add_argument("--output", default=OUTPUT_PATH, help="Path for output CSV")
    parser.add_argument("--samples-per-bin", type=int, default=SAMPLES_PER_BIN,
                        help="Rows to draw per sparsity bin (default %(default)s)")
    parser.add_argument("--n-bins", type=int, default=N_SPARSITY_BINS,
                        help="Number of sparsity bins (default %(default)s)")
    args = parser.parse_args()

    main(args.input, args.output, n_bins=args.n_bins, samples_per_bin=args.samples_per_bin)