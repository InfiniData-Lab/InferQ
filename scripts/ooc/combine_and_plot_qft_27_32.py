"""Combine the original q=27..32 statevector sweep with its disk-full rerun,
emit a per-(qubits, engine, cap) summary as Markdown, and plot wall-time +
status outcomes. Outputs land in this directory.

Usage (from repo root):
    uv run --with matplotlib --with pandas \
        python scripts/ooc/combine_and_plot_qft_27_32.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[2]
ANALYSIS = REPO_ROOT / "InferQ" / "analysis"

SRC = ANALYSIS / "res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.csv"
RERUN = ANALYSIS / "res7_qft_27_32_cpu1_split_allcaps_5runs_all_engines_statevec.rerun_disk_full.csv"

COMBINED = THIS_DIR / "res7_qft_27_32_combined.csv"
TABLE_MD = THIS_DIR / "res7_qft_27_32_per_engine_table.md"
PLOT_WALL = THIS_DIR / "res7_qft_27_32_walltime.png"
PLOT_STATUS = THIS_DIR / "res7_qft_27_32_status_heatmap.png"

KEY = ["circuit_hash", "cap_gb", "engine", "method", "run_idx", "mode"]


def load_combined() -> pd.DataFrame:
    """Prefer rerun rows over the original on the join key."""
    src = pd.read_csv(SRC)
    rerun = pd.read_csv(RERUN)
    src["__source__"] = "original"
    rerun["__source__"] = "rerun"
    src_idx = src.set_index(KEY)
    rerun_idx = rerun.set_index(KEY)
    only_old = src_idx.drop(index=rerun_idx.index.intersection(src_idx.index))
    combined = pd.concat([only_old, rerun_idx]).reset_index()
    combined = combined.sort_values(
        ["num_qubits", "engine", "cap_gb", "method", "run_idx"]
    ).reset_index(drop=True)
    return combined


def _short_reason(status: str, msg: str) -> str:
    if status == "success":
        return "ok"
    msg = msg or ""
    if "temp_file_limit" in msg:
        return "pg temp_file_limit"
    if "No space left on device" in msg:
        return "host disk full"
    if "database or disk is full" in msg:
        return "sqlite disk full"
    if "coupling_map" in msg:
        return "Aer >31 qubits"
    if "max_temp_directory" in msg:
        return "duckdb temp cap"
    if "Insufficient memory" in msg:
        return "aer needs >cap"
    if "Out of Memory" in msg:
        return "duckdb OOM"
    if status == "oom_kill":
        return "OOM-killed"
    if status == "timeout":
        return "wall-time >2h"
    if status == "oom_internal":
        return "engine OOM"
    if status == "error" and not msg.strip():
        return "silent error"
    return f"{status}: {msg[:40]}"


def per_cell_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    grouped = df.groupby(["num_qubits", "engine", "cap_gb"], sort=True)
    for (q, eng, cap), g in grouped:
        n = len(g)
        n_succ = int((g["status"] == "success").sum())
        succ_wall = g.loc[g["status"] == "success", "wall_time_s"]
        if not succ_wall.empty:
            wall_med = f"{succ_wall.median():.0f}"
            wall_min = f"{succ_wall.min():.0f}"
            wall_max = f"{succ_wall.max():.0f}"
        else:
            wall_med = wall_min = wall_max = "—"
        reasons = [
            _short_reason(s, m)
            for s, m in zip(g["status"], g["error_msg"].fillna(""))
            if s != "success"
        ]
        if reasons:
            counts: dict[str, int] = {}
            for r in reasons:
                counts[r] = counts.get(r, 0) + 1
            outcome = "; ".join(
                f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
            )
        else:
            outcome = "ok"
        rows.append(
            {
                "qubits": int(q),
                "engine": eng,
                "cap_gb": int(cap),
                "runs": n,
                "ok": f"{n_succ}/{n}",
                "wall_s (med)": wall_med,
                "wall_s (min-max)": f"{wall_min}–{wall_max}",
                "outcome": outcome,
            }
        )
    return pd.DataFrame(rows)


def render_markdown(summary: pd.DataFrame, df: pd.DataFrame) -> str:
    total_rows = len(df)
    cnt = df["status"].value_counts().to_dict()
    src_cnt = df["__source__"].value_counts().to_dict()
    lines = []
    lines.append("# QFT q=27..32 — per-(qubits, engine, cap) results")
    lines.append("")
    lines.append(
        f"Combined {total_rows} rows from `{SRC.name}` and `{RERUN.name}`; "
        f"rerun rows take precedence on `(circuit_hash, cap_gb, engine, method, run_idx, mode)`."
    )
    lines.append("")
    lines.append(
        f"- Source mix: " + ", ".join(f"{k}={v}" for k, v in src_cnt.items())
    )
    lines.append(
        f"- Status totals: " + ", ".join(f"{k}={v}" for k, v in cnt.items())
    )
    lines.append("")
    lines.append("## Per-cell summary")
    lines.append("")
    cols = ["qubits", "engine", "cap_gb", "runs", "ok", "wall_s (med)", "wall_s (min-max)", "outcome"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for _, r in summary.iterrows():
        lines.append(
            "| "
            + " | ".join(str(r[c]) for c in cols)
            + " |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- `pg temp_file_limit` means PG aborted because a single query's spill exceeded "
        "`OOC_PG_TEMP_FILE_LIMIT_MB=65536` (64 GiB). This is a real engine ceiling — not host disk."
    )
    lines.append(
        "- `duckdb temp cap` rows reference DuckDB's `max_temp_directory_size`; if that is not "
        "being scaled with `cap_gb`, those small-cap results don't measure memory pressure."
    )
    lines.append(
        "- `wall-time >2h` = OOC_TIMEOUT (7200 s). Real ceiling for sqlite at q≥30 is wall-time, not disk."
    )
    lines.append(
        "- `Aer >31 qubits` is a Qiskit coupling-map limit at q=32, not a memory result."
    )
    lines.append(
        "- `silent error` rows (Aer, q=28, cap=8/16) are a worker bug — reproducible across runs."
    )
    return "\n".join(lines)


def plot_walltime(df: pd.DataFrame) -> None:
    succ = df[df["status"] == "success"].copy()
    if succ.empty:
        return
    engines = sorted(succ["engine"].unique())
    caps = sorted(succ["cap_gb"].unique())
    cap_colors = {c: plt.cm.viridis(i / max(1, len(caps) - 1)) for i, c in enumerate(caps)}

    fig, axes = plt.subplots(1, len(engines), figsize=(4 * len(engines), 4),
                             sharey=True)
    if len(engines) == 1:
        axes = [axes]
    for ax, eng in zip(axes, engines):
        sub = succ[succ["engine"] == eng]
        for cap in caps:
            s = sub[sub["cap_gb"] == cap]
            if s.empty:
                continue
            agg = s.groupby("num_qubits")["wall_time_s"].agg(["median", "min", "max"]).reset_index()
            ax.errorbar(
                agg["num_qubits"],
                agg["median"],
                yerr=[agg["median"] - agg["min"], agg["max"] - agg["median"]],
                fmt="o-",
                color=cap_colors[cap],
                label=f"cap={cap} GB",
                capsize=3,
            )
        ax.set_title(eng)
        ax.set_xlabel("num qubits")
        ax.set_yscale("log")
        ax.grid(True, which="both", ls=":", alpha=0.4)
    axes[0].set_ylabel("wall time (s, log)")
    axes[-1].legend(loc="best", fontsize=8)
    fig.suptitle("QFT statevector — successful wall time by engine, cap", y=1.02)
    fig.tight_layout()
    fig.savefig(PLOT_WALL, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_status(df: pd.DataFrame) -> None:
    df = df.copy()
    df["reason"] = [
        _short_reason(s, m) for s, m in zip(df["status"], df["error_msg"].fillna(""))
    ]
    reasons_order = [
        "ok",
        "pg temp_file_limit",
        "sqlite disk full",
        "host disk full",
        "wall-time >2h",
        "aer needs >cap",
        "duckdb OOM",
        "duckdb temp cap",
        "OOM-killed",
        "engine OOM",
        "Aer >31 qubits",
        "silent error",
    ]
    other = [r for r in df["reason"].unique() if r not in reasons_order]
    reasons_order += other
    cmap = plt.cm.tab20
    color_lookup = {r: cmap(i % 20) for i, r in enumerate(reasons_order)}

    engines = sorted(df["engine"].unique())
    qubits = sorted(df["num_qubits"].unique())
    caps = sorted(df["cap_gb"].unique())

    fig, axes = plt.subplots(1, len(engines), figsize=(4 * len(engines), 4),
                             sharey=True)
    if len(engines) == 1:
        axes = [axes]
    for ax, eng in zip(axes, engines):
        # rows = qubits, cols = caps; cell = dominant reason
        grid_text = np.empty((len(qubits), len(caps)), dtype=object)
        grid_color = np.zeros((len(qubits), len(caps), 4))
        for i, q in enumerate(qubits):
            for j, c in enumerate(caps):
                sub = df[(df["engine"] == eng) & (df["num_qubits"] == q) & (df["cap_gb"] == c)]
                if sub.empty:
                    grid_text[i, j] = "—"
                    grid_color[i, j] = (0.9, 0.9, 0.9, 1.0)
                    continue
                vc = sub["reason"].value_counts()
                top = vc.idxmax()
                grid_text[i, j] = f"{vc[top]}/{len(sub)}"
                grid_color[i, j] = color_lookup[top]
        ax.imshow(grid_color, aspect="auto")
        ax.set_xticks(range(len(caps)))
        ax.set_xticklabels([f"{c}G" for c in caps])
        ax.set_yticks(range(len(qubits)))
        ax.set_yticklabels(qubits)
        ax.set_xlabel("cap")
        ax.set_title(eng)
        for i in range(len(qubits)):
            for j in range(len(caps)):
                ax.text(j, i, grid_text[i, j], ha="center", va="center",
                        fontsize=8, color="black")
    axes[0].set_ylabel("num qubits")

    used = {r for r in df["reason"].unique()}
    handles = [
        plt.Rectangle((0, 0), 1, 1, color=color_lookup[r], label=r)
        for r in reasons_order if r in used
    ]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=8,
               bbox_to_anchor=(0.5, -0.06))
    fig.suptitle("Dominant per-cell outcome (count / total runs)", y=1.02)
    fig.tight_layout()
    fig.savefig(PLOT_STATUS, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    df = load_combined()
    df.to_csv(COMBINED, index=False)

    summary = per_cell_summary(df)
    summary.to_csv(THIS_DIR / "res7_qft_27_32_per_engine_table.csv", index=False)
    TABLE_MD.write_text(render_markdown(summary, df))

    plot_walltime(df)
    plot_status(df)

    print(f"combined rows: {len(df)}")
    print(f"  wrote {COMBINED.relative_to(REPO_ROOT)}")
    print(f"  wrote {TABLE_MD.relative_to(REPO_ROOT)}")
    print(f"  wrote {PLOT_WALL.relative_to(REPO_ROOT)}")
    print(f"  wrote {PLOT_STATUS.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
