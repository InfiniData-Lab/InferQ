"""Run the sparse OOC manifest through the Qiskit/Aer-only capped pipeline.

This is a thin, reproducible wrapper around experiments.ooc.run_experiment:

1. Read data/ooc/circuits_sparse.jsonl.
2. Resolve each stale/foreign qpy_path to a local QPY file.
3. Write a generated manifest with those local paths.
4. Run the existing OOC orchestrator with engine=aer under memory caps.

The output CSV uses the same schema as run_experiment.py, including wall time,
tracemalloc peak, process VmPeak, and cgroup memory/IO counters.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

from inferq import paths
from inferq.config import get_ooc_config

DEFAULT_SEARCH_DIRS = (
    paths.data_dir() / "downloaded_circuits",
    paths.circuits_dir(),
    paths.out_dir() / "finetuned_rdbms_116" / "qpy",
    paths.data_dir() / "extremes",
)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_qpy(circuit_hash: str, original: str | None, search_dirs: Iterable[Path]) -> Path | None:
    if original:
        original_path = Path(original).expanduser()
        if original_path.exists():
            return original_path.resolve()

    candidates: list[Path] = []
    for base in search_dirs:
        base = base.expanduser()
        candidates.append(base / f"{circuit_hash}.qpy")
        candidates.append(base / circuit_hash[:2] / f"{circuit_hash}.qpy")

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _load_manifest(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON in {path}:{line_no}: {exc}") from exc
    if not rows:
        raise SystemExit(f"manifest is empty: {path}")
    return rows


def _write_resolved_manifest(
    source: Path,
    output: Path,
    search_dirs: Iterable[Path],
    allow_missing: bool,
    stage_dir: Path,
) -> tuple[int, list[str]]:
    missing: list[str] = []
    resolved_rows: list[dict] = []
    rows = _load_manifest(source)

    for row in rows:
        circuit_hash = str(row.get("hash") or row.get("circuit_hash") or "")
        if not circuit_hash:
            raise SystemExit(f"manifest row has no hash: {row}")
        qpy_path = _resolve_qpy(circuit_hash, row.get("qpy_path"), search_dirs)
        if qpy_path is None:
            missing.append(circuit_hash)
            continue
        try:
            qpy_path.relative_to(paths.repo_root())
        except ValueError:
            stage_dir.mkdir(parents=True, exist_ok=True)
            staged = stage_dir / f"{circuit_hash}.qpy"
            if not staged.exists():
                shutil.copy2(qpy_path, staged)
            qpy_path = staged.resolve()
        row = dict(row)
        row["qpy_path"] = str(qpy_path)
        resolved_rows.append(row)

    if missing and not allow_missing:
        output.parent.mkdir(parents=True, exist_ok=True)
        missing_file = output.with_suffix(".missing_hashes.txt")
        missing_file.write_text("\n".join(missing) + "\n")
        searched = "\n  ".join(str(p.expanduser()) for p in search_dirs)
        raise SystemExit(
            f"missing {len(missing)} QPY files; wrote hashes to {missing_file}\n"
            f"searched:\n  {searched}\n"
            "place flat <hash>.qpy files or sharded <hash[:2]>/<hash>.qpy files in one of "
            "those directories, or pass --qpy-dir."
        )

    if not resolved_rows:
        raise SystemExit("no circuits resolved; refusing to launch an empty run")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as out:
        for row in resolved_rows:
            out.write(json.dumps(row, sort_keys=True) + "\n")
    return len(resolved_rows), missing


def _build_env(args: argparse.Namespace, cfg: dict) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(paths.repo_root()))
    env["OOC_TMP_ROOT"] = str(args.tmp_root)
    env["OOC_N_RUNS"] = str(args.n_runs)
    env["OOC_WARMUP"] = str(args.warmup)
    env["OOC_TIMEOUT"] = str(args.timeout_seconds)
    env["OOC_DROP_CACHE"] = "1" if args.drop_page_cache else "0"
    env["OOC_CONTAINER_CPUS"] = str(args.container_cpus)
    env["OOC_RUNNER"] = args.runner
    env["OOC_WORKER_IMAGE"] = args.worker_image or cfg["worker_image"]
    env["OOC_AER_THREADS"] = str(args.aer_threads)
    return env


def main() -> None:
    cfg = get_ooc_config()
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    ap = argparse.ArgumentParser(
        description="Run data/ooc/circuits_sparse.jsonl with Qiskit/Aer only under memory caps."
    )
    ap.add_argument("--manifest", type=Path,
                    default=paths.data_dir() / "ooc" / "circuits_sparse.jsonl")
    ap.add_argument("--resolved-manifest", type=Path,
                    default=paths.out_dir() / "ooc" /
                    f"circuits_sparse_qiskit_resolved_{timestamp}.jsonl")
    ap.add_argument("--stage-qpy-dir", type=Path,
                    default=paths.out_dir() / "ooc" /
                    f"circuits_sparse_qpy_{timestamp}",
                    help="Repo-local directory used to copy QPYs found outside the repo.")
    ap.add_argument("--results-csv", type=Path,
                    default=paths.out_dir() / "ooc" /
                    f"sparse_qiskit_caps_{timestamp}.csv")
    ap.add_argument("--qpy-dir", type=Path, action="append", default=[],
                    help="Extra directory to search for flat or sharded QPY files. May be repeated.")
    ap.add_argument("--allow-missing", action="store_true",
                    help="Skip manifest rows whose QPY file cannot be found. Default: fail.")
    ap.add_argument("--caps-gb", default=",".join(str(c) for c in cfg["caps_gb"]),
                    help="Comma-separated Docker memory caps, e.g. 16,8,4.")
    ap.add_argument("--aer-methods", default="statevector",
                    help="Comma-separated Qiskit Aer methods. Use 'automatic,statevector,...' for a sweep.")
    ap.add_argument("--n-runs", type=int, default=cfg["n_runs"])
    ap.add_argument("--warmup", type=int, default=cfg["warmup_runs"])
    ap.add_argument("--timeout-seconds", type=int, default=cfg["timeout_seconds"])
    ap.add_argument("--container-cpus", type=float, default=cfg.get("container_cpus") or 0)
    ap.add_argument("--aer-threads", type=int, default=0,
                    help="Qiskit Aer max_parallel_threads. 0 lets Aer use all available CPUs.")
    ap.add_argument("--tmp-root", type=Path, default=Path(cfg["tmp_root"]))
    ap.add_argument("--worker-image", default=cfg["worker_image"])
    ap.add_argument("--runner", choices=["docker", "none"], default=cfg.get("runner", "docker"),
                    help="docker enforces memory caps; none is only for local smoke tests.")
    ap.add_argument("--drop-page-cache", action="store_true",
                    help="Ask run_experiment.py to drop the OS page cache between triples.")
    ap.add_argument("--resume", action="store_true",
                    help="Resume into --results-csv instead of rerunning completed triples.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Resolve the manifest and print worker commands without executing simulations.")
    args = ap.parse_args()

    search_dirs = [*args.qpy_dir, *DEFAULT_SEARCH_DIRS]
    resolved_count, missing = _write_resolved_manifest(
        args.manifest,
        args.resolved_manifest,
        search_dirs,
        args.allow_missing,
        args.stage_qpy_dir,
    )

    caps = ",".join(_split_csv(args.caps_gb))
    aer_methods = ",".join(_split_csv(args.aer_methods))
    if not caps:
        raise SystemExit("--caps-gb resolved to an empty cap list")
    if not aer_methods:
        raise SystemExit("--aer-methods resolved to an empty method list")

    cmd = [
        sys.executable, "-m", "experiments.ooc.run_experiment",
        "--manifest", str(args.resolved_manifest),
        "--results-csv", str(args.results_csv),
        "--caps-gb", caps,
        "--engines", "aer",
        "--aer-methods", aer_methods,
        "--mode", "split",
        "--runner", args.runner,
    ]
    if args.resume:
        cmd.append("--resume")
    if args.dry_run:
        cmd.append("--dry-run")

    print(
        f"[sparse-qiskit] resolved {resolved_count} circuits"
        + (f"; skipped {len(missing)} missing" if missing else ""),
        file=sys.stderr,
    )
    print(f"[sparse-qiskit] manifest: {args.resolved_manifest}", file=sys.stderr)
    print(f"[sparse-qiskit] results:  {args.results_csv}", file=sys.stderr)
    print(f"[sparse-qiskit] command:  {' '.join(cmd)}", file=sys.stderr)

    env = _build_env(args, cfg)
    raise SystemExit(subprocess.run(cmd, cwd=paths.repo_root(), env=env).returncode)


if __name__ == "__main__":
    main()
