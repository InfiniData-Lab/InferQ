"""Produce the revision figures from results.csv.

Three plots + one table:

1. completion_rate_vs_cap.pdf  — stacked or grouped bars per (engine, cap).
   The headline: Aer's bar shrinks sharply at 8 GB / 4 GB while RDBMS bars stay
   at or near 1.0.
2. wall_time_vs_cap.pdf         — median wall time for circuits that completed
   on every cap (per-engine line). Shows graceful degradation ("spilling
   without killing performance").
3. spill_bytes_vs_cap.pdf       — median spill bytes per engine at each cap.
   Expected: zero for Aer (no spill), growing with tighter caps for RDBMSs.
4. aer_failure_table.tex        — LaTeX booktab: circuits where RDBMS completed
   but every Aer method failed. Drops directly into the revision text.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]

ENGINE_ORDER = ["aer", "postgres", "duckdb", "sqlite"]
ENGINE_COLORS = {
    "aer": "#d62728",
    "postgres": "#1f77b4",
    "duckdb": "#2ca02c",
    "sqlite": "#ff7f0e",
}


def plot_completion(summary: pd.DataFrame, out_path: Path) -> None:
    piv = summary.groupby(["engine", "cap_gb"])["completion_rate"].mean().unstack("cap_gb")
    piv = piv.reindex([e for e in ENGINE_ORDER if e in piv.index])
    ax = piv.plot(kind="bar", figsize=(7, 4.2), width=0.78,
                  color=[plt.cm.viridis(0.25), plt.cm.viridis(0.55), plt.cm.viridis(0.85)][:piv.shape[1]])
    ax.set_ylabel("Completion rate")
    ax.set_xlabel("Engine")
    ax.set_ylim(0, 1.02)
    ax.set_title("Completion rate vs. memory cap")
    ax.legend(title="cap (GB)", loc="lower left")
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def plot_wall_time(df: pd.DataFrame, out_path: Path) -> None:
    timed = df[(df["is_warmup"] == False) & (df["status"] == "success")].copy()  # noqa: E712
    # Restrict to circuits that completed on every (engine, cap) we compare.
    pivot = (timed.groupby(["circuit_hash", "engine", "cap_gb"])["wall_time_s"].median().reset_index())
    survivors_per_engine = {}
    for engine, g in pivot.groupby("engine"):
        by_circ = g.groupby("circuit_hash")["cap_gb"].nunique()
        survivors = set(by_circ[by_circ == g["cap_gb"].nunique()].index)
        survivors_per_engine[engine] = survivors

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for engine in ENGINE_ORDER:
        if engine not in survivors_per_engine:
            continue
        circs = survivors_per_engine[engine]
        if not circs:
            continue
        sub = pivot[(pivot["engine"] == engine) & (pivot["circuit_hash"].isin(circs))]
        by_cap = sub.groupby("cap_gb")["wall_time_s"].median().sort_index()
        ax.plot(by_cap.index, by_cap.values, marker="o",
                label=engine, color=ENGINE_COLORS.get(engine, "gray"))
    ax.set_xlabel("Memory cap (GB)")
    ax.set_ylabel("Median wall time (s)")
    ax.set_yscale("log")
    ax.invert_xaxis()
    ax.set_title("Wall-time degradation under tighter memory caps")
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def plot_spill(df: pd.DataFrame, out_path: Path) -> None:
    timed = df[(df["is_warmup"] == False) & (df["status"] == "success")]  # noqa: E712
    if timed.empty:
        return
    piv = (timed.groupby(["engine", "cap_gb"])["dbms_temp_bytes_written"].median()
                 .unstack("cap_gb"))
    piv = piv / (1 << 30)   # GB
    piv = piv.reindex([e for e in ENGINE_ORDER if e in piv.index])
    ax = piv.plot(kind="bar", figsize=(7, 4.2), width=0.78)
    ax.set_ylabel("Median spill bytes (GB, log scale)")
    ax.set_xlabel("Engine")
    ax.set_yscale("symlog", linthresh=1e-2)
    ax.set_title("Disk spill vs. memory cap")
    ax.legend(title="cap (GB)")
    plt.xticks(rotation=0)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def emit_aer_failure_tex(aer_table: pd.DataFrame, out_path: Path) -> None:
    headline = aer_table[aer_table["headline_case"] == True]  # noqa: E712
    if headline.empty:
        out_path.write_text("% no headline 'Aer fails / RDBMS completes' circuits\n")
        return
    rows = headline.sort_values(["cap_gb", "num_qubits"]).head(20)
    lines = [
        r"\begin{tabular}{lrrll}",
        r"\toprule",
        r"Circuit & Qubits & Cap (GB) & RDBMS engines & Aer status \\",
        r"\midrule",
    ]
    for _, r in rows.iterrows():
        lines.append(
            f"{r['circuit_hash'][:10]} & {int(r['num_qubits'])} & {int(r['cap_gb'])} & "
            f"{r['rdbms_success_engines']} & all methods failed \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    out_path.write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path,
                    default=REPO_ROOT / "InferQ" / "scripts" / "ooc" / "results")
    args = ap.parse_args()

    results_csv = args.results_dir / "results.csv"
    summary_csv = args.results_dir / "summary_by_engine_cap.csv"
    aer_csv = args.results_dir / "aer_failures.csv"
    for p in (results_csv, summary_csv, aer_csv):
        if not p.exists():
            raise SystemExit(f"missing {p} — run analyze.py first")

    df = pd.read_csv(results_csv)
    df["is_warmup"] = df["run_idx"].astype(str) == "warmup"
    summary = pd.read_csv(summary_csv)
    aer_table = pd.read_csv(aer_csv)

    out = args.results_dir / "figures"
    out.mkdir(parents=True, exist_ok=True)
    plot_completion(summary, out / "completion_rate_vs_cap.pdf")
    plot_wall_time(df, out / "wall_time_vs_cap.pdf")
    plot_spill(df, out / "spill_bytes_vs_cap.pdf")
    emit_aer_failure_tex(aer_table, out / "aer_failure_table.tex")
    print(f"[plot] wrote 4 artifacts to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
