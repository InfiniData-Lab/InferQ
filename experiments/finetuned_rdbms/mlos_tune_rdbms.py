#!/usr/bin/env python3
"""Tune raw monolithic RDBMS runs with MLOS.

This driver keeps the existing finetuned_rdbms workload shape: load .qpy,
generate one InfiniQuantumSim SQL query, and execute that query unchanged.
MLOS only chooses engine tuning parameters.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from experiments.finetuned_rdbms.run_all_116 import (
    index_qpy_files,
    select_all_engine_baselines,
    write_text_lines,
)
from experiments.finetuned_rdbms.run_finetuned_rdbms import (
    CSV_FIELDS,
    ENGINES,
    PROFILES,
    RUNNERS,
    build_iqs_query_with_timeout,
    flatten_error,
    load_qpy,
    query_shape,
    read_qpy_list,
    run_with_tracemalloc,
    tuning_for,
)
from inferq import paths

TRIAL_FIELDS = CSV_FIELDS + ["phase", "trial_id", "score", "params"]
FAILURE_SCORE = 1_000_000_000.0


@dataclass(frozen=True)
class CandidateCircuit:
    qpy_path: Path
    metadata: dict[str, Any]

    @property
    def circuit_hash(self) -> str:
        return self.qpy_path.stem


@dataclass
class QueryBundle:
    query: str
    num_qubits: int
    num_gates: int
    query_gen_time_s: float
    query_bytes: int
    total_ctes: int
    tensor_ctes: int
    contraction_ctes: int


def parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def read_json(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def discover_candidates(args) -> list[CandidateCircuit]:
    if args.qpy_list:
        paths = read_qpy_list(args.qpy_list)
        return [CandidateCircuit(p.resolve(), {}) for p in paths]

    selected = select_all_engine_baselines(args.parquet)
    roots = args.qpy_root or [paths.circuits_dir(), paths.data_dir() / "extremes"]
    qpy_index = index_qpy_files(roots)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    full_manifest = args.out_dir / "all_116_manifest.csv"
    selected.to_csv(full_manifest, index=False)

    wanted_hashes = [str(x) for x in selected["RowKey"]]
    found: list[CandidateCircuit] = []
    missing: list[str] = []
    for row in selected.to_dict(orient="records"):
        h = str(row["RowKey"])
        if h in qpy_index:
            found.append(CandidateCircuit(qpy_index[h], row))
        else:
            missing.append(h)

    write_text_lines(args.out_dir / "all_116_hashes.txt", wanted_hashes)
    write_text_lines(args.out_dir / "found_qpy_paths.txt", [str(c.qpy_path) for c in found])
    write_text_lines(args.out_dir / "missing_hashes.txt", missing)
    write_json(args.out_dir / "mlos_selection_summary.json", {
        "parquet": str(args.parquet),
        "qpy_roots": [str(p) for p in roots],
        "selected_hashes": len(wanted_hashes),
        "found_qpy": len(found),
        "missing_qpy": len(missing),
        "full_manifest": str(full_manifest),
    })
    return found


def select_pilot(candidates: list[CandidateCircuit], pilot_size: int) -> list[CandidateCircuit]:
    if pilot_size <= 0 or len(candidates) <= pilot_size:
        return list(candidates)

    def key(c: CandidateCircuit) -> tuple[float, float, str]:
        meta = c.metadata
        return (
            float(meta.get("num_qubits") or math.inf),
            float(meta.get("circuit_size") or math.inf),
            c.circuit_hash,
        )

    ordered = sorted(candidates, key=key)
    if pilot_size == 1:
        return [ordered[len(ordered) // 2]]
    indexes = sorted({
        round(i * (len(ordered) - 1) / (pilot_size - 1))
        for i in range(pilot_size)
    })
    return [ordered[i] for i in indexes]


def get_query_bundle(
    candidate: CandidateCircuit,
    cache: dict[str, QueryBundle],
    query_timeout_s: int,
) -> QueryBundle:
    if candidate.circuit_hash in cache:
        return cache[candidate.circuit_hash]
    qc = load_qpy(candidate.qpy_path)
    query, num_qubits, num_gates, query_gen_s = build_iqs_query_with_timeout(qc, query_timeout_s)
    shape = query_shape(query)
    bundle = QueryBundle(
        query=query,
        num_qubits=num_qubits,
        num_gates=num_gates,
        query_gen_time_s=query_gen_s,
        query_bytes=len(query),
        total_ctes=shape.total_ctes,
        tensor_ctes=shape.tensor_ctes,
        contraction_ctes=shape.contraction_ctes,
    )
    cache[candidate.circuit_hash] = bundle
    return bundle


def clean_json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return value


def params_to_tuning(engine: str, params: dict[str, Any], tmp_root: Path) -> dict[str, Any]:
    params = {k: clean_json_value(v) for k, v in params.items()}
    if engine == "duckdb":
        return {
            "threads": int(params["threads"]),
            "memory_limit": f"{int(params['memory_limit_mb'])}MB",
            "temp_directory": str(tmp_root / "duckdb"),
            "preserve_insertion_order": bool(params["preserve_insertion_order"]),
            "max_temp_directory_size": f"{int(params['max_temp_directory_size_gb'])}GB",
        }
    if engine == "sqlite":
        return {
            "cache_mb": int(params["cache_mb"]),
            "temp_store": str(params["temp_store"]),
            "mmap_mb": int(params["mmap_mb"]),
            "threads": int(params["threads"]),
            "db_path": str(tmp_root / "sqlite" / "bench.db"),
        }
    if engine == "postgres":
        return {
            "work_mem": f"{int(params['work_mem_mb'])}MB",
            "temp_buffers": f"{int(params['temp_buffers_mb'])}MB",
            "max_parallel_workers_per_gather": int(params["max_parallel_workers_per_gather"]),
            "effective_cache_size": f"{int(params['effective_cache_size_gb'])}GB",
            "hash_mem_multiplier": f"{float(params['hash_mem_multiplier']):.2f}",
            "jit": str(params["jit"]),
            "join_collapse_limit": int(params["join_collapse_limit"]),
            "from_collapse_limit": int(params["from_collapse_limit"]),
            "temp_file_limit": "-1",
        }
    raise ValueError(f"unknown engine {engine!r}")


def make_optimizer(engine: str, seed: int, trials: int, optimizer_name: str):
    try:
        from ConfigSpace import (  # type: ignore
            CategoricalHyperparameter,
            ConfigurationSpace,
            UniformFloatHyperparameter,
            UniformIntegerHyperparameter,
        )
        from mlos_core.optimizers import OptimizerFactory, OptimizerType  # type: ignore
        from mlos_core.spaces.adapters import SpaceAdapterType  # type: ignore
    except ImportError as e:
        raise SystemExit(
            "MLOS dependencies are not installed. Install with "
            "`python -m pip install 'mlos-core[flaml,smac]'` or use the repo environment "
            "after syncing the new dependency."
        ) from e

    cs = ConfigurationSpace(seed=seed)
    if engine == "duckdb":
        cs.add(UniformIntegerHyperparameter("memory_limit_mb", lower=512, upper=16384, log=True))
        cs.add(CategoricalHyperparameter("threads", [1, 2, 4, 8]))
        cs.add(CategoricalHyperparameter("max_temp_directory_size_gb", [32, 64, 128, 256, 512]))
        cs.add(CategoricalHyperparameter("preserve_insertion_order", [False, True]))
    elif engine == "sqlite":
        cs.add(UniformIntegerHyperparameter("cache_mb", lower=128, upper=4096, log=True))
        cs.add(CategoricalHyperparameter("temp_store", ["MEMORY", "FILE"]))
        cs.add(CategoricalHyperparameter("mmap_mb", [0, 256, 512, 1024, 2048]))
        cs.add(CategoricalHyperparameter("threads", [1, 2, 4, 8]))
    elif engine == "postgres":
        cs.add(UniformIntegerHyperparameter("work_mem_mb", lower=16, upper=1024, log=True))
        cs.add(UniformIntegerHyperparameter("temp_buffers_mb", lower=32, upper=512, log=True))
        cs.add(CategoricalHyperparameter("max_parallel_workers_per_gather", [0, 1, 2, 4, 8]))
        cs.add(UniformIntegerHyperparameter("effective_cache_size_gb", lower=1, upper=32, log=True))
        cs.add(UniformFloatHyperparameter("hash_mem_multiplier", lower=1.0, upper=4.0))
        cs.add(CategoricalHyperparameter("jit", ["off", "on"]))
        cs.add(CategoricalHyperparameter("join_collapse_limit", [1, 4, 8]))
        cs.add(CategoricalHyperparameter("from_collapse_limit", [1, 4, 8]))
    else:
        raise ValueError(f"unknown engine {engine!r}")

    optimizer_type = {
        "flaml": OptimizerType.FLAML,
        "smac": OptimizerType.SMAC,
    }[optimizer_name]
    optimizer_kwargs: dict[str, Any] = {"seed": seed}
    if optimizer_name == "smac":
        optimizer_kwargs["max_trials"] = trials

    return OptimizerFactory.create(
        parameter_space=cs,
        optimization_targets=["score"],
        optimizer_type=optimizer_type,
        optimizer_kwargs=optimizer_kwargs,
        space_adapter_type=SpaceAdapterType.IDENTITY,
        space_adapter_kwargs={},
    )


def timed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        r for r in rows
        if str(r.get("run_idx", "")) and not str(r.get("run_idx", "")).startswith("warmup")
    ]


def score_rows(rows: list[dict[str, Any]]) -> float:
    scored = [r for r in rows if not str(r.get("run_idx", "")).startswith("warmup")]
    failures = [r for r in scored if r.get("status") != "success"]
    successes = [
        float(r["wall_time_s"])
        for r in timed_rows(rows)
        if r.get("status") == "success" and str(r.get("wall_time_s", ""))
    ]
    if failures or not successes:
        return FAILURE_SCORE + len(failures) * 1_000_000.0 + sum(successes)
    successes.sort()
    mid = len(successes) // 2
    if len(successes) % 2:
        return successes[mid]
    return (successes[mid - 1] + successes[mid]) / 2.0


def _engine_child(
    queue,
    engine: str,
    query: str,
    tuning: dict[str, Any],
    timeout_s: int,
    fetch_chunk_size: int,
) -> None:
    try:
        runner = RUNNERS[engine]
        result = run_with_tracemalloc(
            lambda runner=runner, tuning=tuning: runner(
                query, tuning, timeout_s, fetch_chunk_size
            )
        )
    except Exception as e:
        result = {
            "status": "error",
            "wall_time_s": "",
            "rows_consumed": "",
            "tracemalloc_peak_bytes": "",
            "error_msg": flatten_error(f"{e}\n{traceback.format_exc(limit=4)}"),
        }
    queue.put(result)


def run_engine_isolated(
    engine: str,
    query: str,
    tuning: dict[str, Any],
    timeout_s: int,
    fetch_chunk_size: int,
) -> dict[str, Any]:
    """Run one engine invocation in a child process with a hard timeout.

    The in-process runners use threads because that is convenient for normal
    benchmarking. During autotuning, some suggested monolithic configurations
    can block inside DuckDB/SQLite cancellation paths, so the optimizer needs a
    stronger process boundary.
    """
    ctx = mp.get_context("spawn")
    queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_engine_child,
        args=(queue, engine, query, tuning, timeout_s, fetch_chunk_size),
        daemon=True,
    )
    start = time.perf_counter()
    proc.start()
    proc.join(timeout_s + 5)
    if proc.is_alive():
        proc.terminate()
        proc.join(3)
        if proc.is_alive():
            proc.kill()
            proc.join(3)
        return {
            "status": "timeout",
            "wall_time_s": time.perf_counter() - start,
            "rows_consumed": 0,
            "tracemalloc_peak_bytes": 0,
            "error_msg": f"{engine} subprocess timed out after {timeout_s}s",
        }
    if proc.exitcode != 0 and queue.empty():
        return {
            "status": "error",
            "wall_time_s": time.perf_counter() - start,
            "rows_consumed": 0,
            "tracemalloc_peak_bytes": 0,
            "error_msg": f"{engine} subprocess exited with rc={proc.exitcode}",
        }
    try:
        return queue.get_nowait()
    except Exception:
        return {
            "status": "error",
            "wall_time_s": time.perf_counter() - start,
            "rows_consumed": 0,
            "tracemalloc_peak_bytes": 0,
            "error_msg": f"{engine} subprocess produced no result",
        }


def run_trial(
    *,
    phase: str,
    trial_id: str,
    engine: str,
    tuning: dict[str, Any],
    params: dict[str, Any] | None,
    candidates: list[CandidateCircuit],
    query_cache: dict[str, QueryBundle],
    query_timeout_s: int,
    timeout_s: int,
    warmup: int,
    n_runs: int,
    fetch_chunk_size: int,
    writer: csv.DictWriter,
) -> tuple[float, list[dict[str, Any]]]:
    profile = trial_id
    tuning_json = json.dumps(tuning, sort_keys=True)
    params_json = json.dumps(params or {}, sort_keys=True)
    labels = [f"warmup{i}" for i in range(warmup)] + [str(i) for i in range(n_runs)]
    rows: list[dict[str, Any]] = []

    for idx, candidate in enumerate(candidates, 1):
        print(
            f"    [{idx}/{len(candidates)}] {engine} {trial_id} {candidate.circuit_hash[:8]}",
            file=sys.stderr,
        )
        try:
            bundle = get_query_bundle(candidate, query_cache, query_timeout_s)
        except Exception as e:
            row = {
                "circuit_hash": candidate.circuit_hash,
                "qpy_path": str(candidate.qpy_path),
                "num_qubits": "",
                "num_gates": "",
                "query_gen_time_s": "",
                "query_bytes": "",
                "total_ctes": "",
                "tensor_ctes": "",
                "contraction_ctes": "",
                "engine": engine,
                "profile": profile,
                "run_idx": "",
                "status": "query_error",
                "wall_time_s": "",
                "rows_consumed": "",
                "tracemalloc_peak_bytes": "",
                "tuning": tuning_json,
                "error_msg": flatten_error(f"{e}\n{traceback.format_exc(limit=4)}"),
                "phase": phase,
                "trial_id": trial_id,
                "score": "",
                "params": params_json,
            }
            rows.append(row)
            continue

        for run_idx in labels:
            result = run_engine_isolated(
                engine, bundle.query, tuning, timeout_s, fetch_chunk_size
            )
            row = {
                "circuit_hash": candidate.circuit_hash,
                "qpy_path": str(candidate.qpy_path),
                "num_qubits": bundle.num_qubits,
                "num_gates": bundle.num_gates,
                "query_gen_time_s": bundle.query_gen_time_s,
                "query_bytes": bundle.query_bytes,
                "total_ctes": bundle.total_ctes,
                "tensor_ctes": bundle.tensor_ctes,
                "contraction_ctes": bundle.contraction_ctes,
                "engine": engine,
                "profile": profile,
                "run_idx": run_idx,
                "status": result["status"],
                "wall_time_s": result["wall_time_s"],
                "rows_consumed": result["rows_consumed"],
                "tracemalloc_peak_bytes": result["tracemalloc_peak_bytes"],
                "tuning": tuning_json,
                "error_msg": result["error_msg"],
                "phase": phase,
                "trial_id": trial_id,
                "score": "",
                "params": params_json,
            }
            rows.append(row)

    score = score_rows(rows)
    for row in rows:
        row["score"] = score
        writer.writerow(row)
    return score, rows


def profile_seed_trials(engine: str, tmp_root: Path, profiles: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for profile in profiles:
        if profile not in PROFILES:
            raise ValueError(f"unknown seed profile {profile!r}")
        out.append((f"seed_{profile}", tuning_for(profile, engine, tmp_root)))
    return out


def tune(args, candidates: list[CandidateCircuit]) -> dict[str, Any]:
    import pandas as pd

    engines = parse_csv(args.engines)
    invalid = sorted(set(engines) - set(ENGINES))
    if invalid:
        raise SystemExit(f"unsupported engines: {invalid}")
    if not candidates:
        raise SystemExit(
            "No .qpy circuits were found. Pass --qpy-root pointing at the 116 .qpy files "
            "or pass --qpy-list."
        )

    pilot = select_pilot(candidates, args.pilot_size)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_text_lines(args.out_dir / "mlos_pilot_qpy_paths.txt", [str(c.qpy_path) for c in pilot])

    trial_csv = args.trials_csv or (args.out_dir / "mlos_trials.csv")
    write_header = not trial_csv.exists() or trial_csv.stat().st_size == 0
    best: dict[str, Any] = {
        "created_at": time.time(),
        "pilot_size": len(pilot),
        "trial_csv": str(trial_csv),
        "engines": {},
    }
    query_cache: dict[str, QueryBundle] = {}

    with trial_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRIAL_FIELDS)
        if write_header:
            writer.writeheader()

        for engine in engines:
            print(f"[mlos] tuning {engine} on {len(pilot)} pilot circuits", file=sys.stderr)
            opt = make_optimizer(engine, args.seed, args.trials, args.optimizer) if args.trials > 0 else None
            best_score = math.inf
            best_entry: dict[str, Any] | None = None

            for seed_id, tuning in profile_seed_trials(engine, args.tmp_root, parse_csv(args.seed_profiles)):
                score, _ = run_trial(
                    phase="seed",
                    trial_id=f"{engine}_{seed_id}",
                    engine=engine,
                    tuning=tuning,
                    params=None,
                    candidates=pilot,
                    query_cache=query_cache,
                    query_timeout_s=args.query_timeout_seconds,
                    timeout_s=args.timeout_seconds,
                    warmup=args.warmup,
                    n_runs=args.n_runs,
                    fetch_chunk_size=args.fetch_chunk_size,
                    writer=writer,
                )
                f.flush()
                if score < best_score:
                    best_score = score
                    best_entry = {
                        "score": score,
                        "trial_id": f"{engine}_{seed_id}",
                        "params": None,
                        "tuning": tuning,
                    }

            for trial_num in range(args.trials):
                assert opt is not None
                suggestion = opt.suggest()
                params = {k: clean_json_value(v) for k, v in suggestion.config.to_dict().items()}
                tuning = params_to_tuning(engine, params, args.tmp_root)
                trial_id = f"{engine}_mlos_{trial_num:04d}"
                print(f"[mlos] trial {trial_id} params={json.dumps(params, sort_keys=True)}", file=sys.stderr)
                score, _ = run_trial(
                    phase="mlos",
                    trial_id=trial_id,
                    engine=engine,
                    tuning=tuning,
                    params=params,
                    candidates=pilot,
                    query_cache=query_cache,
                    query_timeout_s=args.query_timeout_seconds,
                    timeout_s=args.timeout_seconds,
                    warmup=args.warmup,
                    n_runs=args.n_runs,
                    fetch_chunk_size=args.fetch_chunk_size,
                    writer=writer,
                )
                opt.register(suggestion.complete(pd.Series({"score": score})))
                f.flush()
                if score < best_score:
                    best_score = score
                    best_entry = {
                        "score": score,
                        "trial_id": trial_id,
                        "params": params,
                        "tuning": tuning,
                    }

            if best_entry is None:
                raise RuntimeError(f"no trials evaluated for {engine}")
            best["engines"][engine] = best_entry
            write_json(args.best_configs, best)
            print(f"[mlos] best {engine}: score={best_entry['score']} trial={best_entry['trial_id']}", file=sys.stderr)

    write_json(args.best_configs, best)
    return best


def validate(args, candidates: list[CandidateCircuit], best: dict[str, Any] | None = None) -> None:
    if best is None:
        best = read_json(args.best_configs)
    engines_cfg = best.get("engines", {})
    if not isinstance(engines_cfg, dict) or not engines_cfg:
        raise SystemExit(f"{args.best_configs} does not contain engine configs")
    if not candidates:
        raise SystemExit("No .qpy circuits were found for validation.")

    results_csv = args.validation_csv or (args.out_dir / "results_mlos.csv")
    write_header = not results_csv.exists() or results_csv.stat().st_size == 0
    query_cache: dict[str, QueryBundle] = {}
    with results_csv.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=TRIAL_FIELDS)
        if write_header:
            writer.writeheader()
        for engine, entry in engines_cfg.items():
            tuning = entry.get("tuning")
            if not isinstance(tuning, dict):
                raise SystemExit(f"best config for {engine} is missing tuning")
            print(f"[validate] {engine} on {len(candidates)} circuits", file=sys.stderr)
            run_trial(
                phase="validate",
                trial_id=f"{engine}_mlos_best",
                engine=engine,
                tuning=tuning,
                params=entry.get("params"),
                candidates=candidates,
                query_cache=query_cache,
                query_timeout_s=args.query_timeout_seconds,
                timeout_s=args.timeout_seconds,
                warmup=args.warmup,
                n_runs=args.validation_runs,
                fetch_chunk_size=args.fetch_chunk_size,
                writer=writer,
            )
            f.flush()
    print(f"[validate] wrote {results_csv}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", type=Path,
                        default=paths.dataset("training_data") / "rdbms_training_data.parquet")
    parser.add_argument("--qpy-root", type=Path, action="append",
                        help="Directory to search recursively for .qpy files. Can be repeated.")
    parser.add_argument("--qpy-list", type=Path, default=None,
                        help="File containing exact .qpy paths to use instead of all_116 discovery.")
    parser.add_argument("--out-dir", type=Path,
                        default=paths.out_dir() / "finetuned_rdbms_116")
    parser.add_argument("--engines", default="duckdb,sqlite,postgres")
    parser.add_argument("--pilot-size", type=int, default=12)
    parser.add_argument("--trials", type=int, default=20,
                        help="MLOS-suggested trials per engine, after seed profile baselines.")
    parser.add_argument("--optimizer", choices=("flaml", "smac"), default="flaml")
    parser.add_argument("--seed-profiles", default="balanced,fast,spill_safe")
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--n-runs", type=int, default=1)
    parser.add_argument("--validation-runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--query-timeout-seconds", type=int, default=300)
    parser.add_argument("--fetch-chunk-size", type=int, default=8192)
    parser.add_argument("--tmp-root", type=Path,
                        default=paths.out_dir() / "finetuned_rdbms_116" / "tmp")
    parser.add_argument("--trials-csv", type=Path, default=None)
    parser.add_argument("--best-configs", type=Path,
                        default=paths.out_dir() / "finetuned_rdbms_116" / "mlos_best_configs.json")
    parser.add_argument("--validation-csv", type=Path, default=None)
    parser.add_argument("--validate", action="store_true",
                        help="Validate best configs on all discovered circuits after tuning.")
    parser.add_argument("--validate-only", action="store_true",
                        help="Skip tuning and validate configs from --best-configs.")
    args = parser.parse_args()

    candidates = discover_candidates(args)
    if args.validate_only:
        validate(args, candidates)
        return 0
    best = tune(args, candidates)
    if args.validate:
        validate(args, candidates, best)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
