#!/usr/bin/env python3
"""
deep_benchmark.py — Deep profiling of SQLite vs Aer quantum simulation.

For each of the 4 extreme circuits (win_1, win_2, lose_1, lose_2):

SQLite path:
  • per-CTE true row counts (intermediate cardinalities)
  • estimated bytes per CTE (col_count × 16 bytes/complex × rows)
  • EXPLAIN QUERY PLAN check for temp-B-tree / external-sort spill
  • SQLite page-cache overflow via ctypes sqlite3_status()
  • Peak RSS, current VSZ, Δmajor-faults, Δminor-faults (psutil + resource)

Aer path:
  • Peak RSS, VSZ, Δmajor-faults, Δminor-faults per method × mode

Usage:
    uv run python analysis/deep_benchmark.py
    # → analysis/deep_benchmark_results.json
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import resource
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import psutil
import qiskit.qpy
from qiskit import transpile
from qiskit_aer import AerSimulator

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RDBMS_DIR    = PROJECT_ROOT.parent / "Infinidata-rdbms-simulator"

for p in (str(RDBMS_DIR), str(PROJECT_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSCircuit, Gate as IQSGate
from InfiniQuantumSim.utils import INDICES
from InfiniQuantumSim.sql_commands import sql_einsum_query
import InfiniQuantumSim.queryEinSum as ses
import opt_einsum as oe

CIRCUITS_DIR = PROJECT_ROOT / "data" / "extremes"
OUT_JSON     = Path(__file__).resolve().parent / "deep_benchmark_results.json"

# Top-5 qiskit_wins  (SQLite uses ~850× more memory than Qiskit)
# Top-5 sqlite_wins  (Qiskit uses ~350 000× more tracemalloc than SQLite)
# — all RowKeys taken from analysis/extremes_results.json —
CIRCUIT_LABELS: Dict[str, str] = {
    # qiskit_wins rank 1-5  (15 qubits, various depths, rz/cz/cx/ry gates)
    "20c7835540156a373bd0dbab1012b06f99e1d2d6b0079bab55d1073c9714e19f": "qwin_1",
    "1137d048a20593fd96ca41b3222ada0354ceea8e746f44abb8c0cba99da78d3c": "qwin_2",
    "0882311d69370df96823919e0afb49dfeee5531cb969e066c900cb9bd8c9c470": "qwin_3",
    "06e8dbb5cf8ad751288a557373e958906b329f5abe79cddcde8af53216886eac": "qwin_4",
    "02bc5051e86ad52efe2769a3d876e0b0a5ea2dc03576115c748f155604e99c57": "qwin_5",
    # sqlite_wins rank 1-5  (2-3 qubits, depth 725-997, single compiled unitary)
    "05fec6a4208e6b9842a930683ce2f168697dd54229176af898ed6ff78530e0fd": "swin_1",
    "1db055cd0453e8c75967710154eb273969205be72cc8ba681400fe7842465f21": "swin_2",
    "19a694b13987a01eed90550b56b3cca1d43dbec7a33ce5096f1da7d256564b27": "swin_3",
    "0d4a7e2a06d0f98917f068ae9bb056c06f2f26abda6c8bcbf3e3caafa5170ac0": "swin_4",
    "039af5ea948e8e5ea72f3a986cec186161233f0c8540ff73bb6b726604e60471": "swin_5",
}

AER_METHODS = [
    "statevector",
    "density_matrix",
    "matrix_product_state",
    "unitary",
    "automatic",
]

BASIS_GATES = [
    "cx", "u3", "u2", "u1", "x", "h", "s", "sdg", "t", "tdg",
    "swap", "ccx", "id", "rz", "ry", "rx", "sx", "p", "reset", "measure",
]

SINGLE_CORE = {
    "max_parallel_threads":     1,
    "max_parallel_experiments": 1,
    "max_parallel_shots":       1,
}

# ── SQLite ctypes for SQLITE_STATUS_PAGECACHE_OVERFLOW ─────────────────────
# SQLITE_STATUS_PAGECACHE_OVERFLOW = 2
_libsqlite: Optional[ctypes.CDLL] = None

def _get_libsqlite() -> Optional[ctypes.CDLL]:
    global _libsqlite
    if _libsqlite is not None:
        return _libsqlite
    candidates = [
        "/usr/lib/libsqlite3.dylib",
        "/usr/lib/x86_64-linux-gnu/libsqlite3.so.0",
        "/usr/lib/aarch64-linux-gnu/libsqlite3.so.0",
        "libsqlite3.so.0",
        "libsqlite3.dylib",
    ]
    for c in candidates:
        try:
            _libsqlite = ctypes.CDLL(c)
            _libsqlite.sqlite3_status.restype  = ctypes.c_int
            _libsqlite.sqlite3_status.argtypes = [
                ctypes.c_int, ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int), ctypes.c_int,
            ]
            return _libsqlite
        except Exception:
            pass
    return None


def sqlite_pagecache_overflow() -> Tuple[int, int]:
    """Return (current, highwater) bytes for SQLITE_STATUS_PAGECACHE_OVERFLOW."""
    lib = _get_libsqlite()
    if lib is None:
        return -1, -1
    cur = ctypes.c_int(0)
    hw  = ctypes.c_int(0)
    SQLITE_STATUS_PAGECACHE_OVERFLOW = 2
    lib.sqlite3_status(SQLITE_STATUS_PAGECACHE_OVERFLOW,
                       ctypes.byref(cur), ctypes.byref(hw), 0)
    return cur.value, hw.value


# ── OS resource helpers ────────────────────────────────────────────────────

def rss_bytes() -> int:
    """Current RSS in bytes (psutil, precise)."""
    return psutil.Process().memory_info().rss


def vsz_bytes() -> int:
    """Current VSZ in bytes (psutil)."""
    return psutil.Process().memory_info().vms


def page_faults_now() -> Tuple[int, int]:
    """Return (major_faults, minor_faults) accumulated by this process so far."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return int(ru.ru_majflt), int(ru.ru_minflt)


def snapshot_resources() -> Dict[str, Any]:
    rss = rss_bytes()
    vsz = vsz_bytes()
    maj, mfn = page_faults_now()
    return {"rss_bytes": rss, "vsz_bytes": vsz, "maj_flt": maj, "min_flt": mfn}


def delta_resources(before: Dict, after: Dict) -> Dict[str, Any]:
    return {
        "peak_rss_bytes":    after["rss_bytes"],   # psutil RSS after is our best "peak" proxy
        "vsz_bytes":         after["vsz_bytes"],
        "delta_maj_flt":     after["maj_flt"]  - before["maj_flt"],
        "delta_min_flt":     after["min_flt"]  - before["min_flt"],
    }


# ── CTE parser ─────────────────────────────────────────────────────────────

def _balance_parens(sql: str, start: int) -> int:
    """
    Given sql[start] == '(', return the index AFTER the matching ')'.
    """
    depth = 0
    i = start
    while i < len(sql):
        if sql[i] == '(':
            depth += 1
        elif sql[i] == ')':
            depth -= 1
            if depth == 0:
                return i + 1
        elif sql[i] in ("'", '"'):
            # Skip string literals
            q = sql[i]
            i += 1
            while i < len(sql) and sql[i] != q:
                if sql[i] == '\\':
                    i += 1
                i += 1
        i += 1
    return i


_CTE_RE = re.compile(
    r'(?:^|,)\s*'               # start of WITH or comma separator
    r'(\w+)'                    # CTE name
    r'\s*(\([^)]*\))?\s*'       # optional column list (no nesting)
    r'AS\s*\(',                 # AS (
    re.IGNORECASE | re.DOTALL,
)


def parse_ctes(sql: str) -> List[Dict[str, Any]]:
    """
    Parse all CTEs from a WITH … SELECT … query.
    Returns list of dicts: {name, columns, body_sql, body_start, body_end}
    sorted in definition order.
    """
    # Strip leading WITH
    stripped = sql.strip()
    if stripped.upper().startswith("WITH "):
        search_in = stripped[5:]
        offset    = sql.index(stripped) + 5
    else:
        search_in = stripped
        offset    = 0

    results: List[Dict[str, Any]] = []
    for m in _CTE_RE.finditer(search_in):
        name     = m.group(1)
        cols_raw = (m.group(2) or "").strip("()").strip()
        # Body starts at the '(' that follows 'AS '
        as_paren_start = offset + m.end() - 1   # index of '(' in original sql
        body_end       = _balance_parens(sql, as_paren_start)
        body           = sql[as_paren_start + 1 : body_end - 1].strip()
        results.append({
            "name":       name,
            "columns":    cols_raw,
            "body_sql":   body,
            "body_start": as_paren_start + 1,
            "body_end":   body_end - 1,
        })

    # Sort by position in SQL
    results.sort(key=lambda x: x["body_start"])
    return results


def build_count_query(ctes: List[Dict], target_name: str) -> Optional[str]:
    """
    Build: WITH <ctes up to and including target_name>
           SELECT COUNT(*) FROM <target_name>
    """
    include = []
    for c in ctes:
        include.append(c)
        if c["name"] == target_name:
            break
    else:
        return None  # target not found

    parts = []
    for c in include:
        col_part = f"({c['columns']})" if c["columns"] else ""
        parts.append(f"{c['name']}{col_part} AS ({c['body_sql']})")

    return "WITH " + ",\n".join(parts) + f"\nSELECT COUNT(*) FROM {target_name}"


def explain_qp(con: sqlite3.Connection, sql: str) -> List[str]:
    """Run EXPLAIN QUERY PLAN and return detail strings."""
    try:
        rows = con.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        return [r[-1] for r in rows]
    except Exception as e:
        return [f"ERROR: {e}"]


def detect_spill_from_eqp(eqp_lines: List[str]) -> Dict[str, Any]:
    spill = {
        "has_temp_btree": False,
        "has_external_sort": False,
        "has_auto_index": False,
        "details": [],
    }
    for line in eqp_lines:
        lo = line.upper()
        if "TEMP B-TREE" in lo:
            spill["has_temp_btree"] = True
            spill["details"].append(line)
        if "SCAN" in lo and "EXTERNAL" in lo:
            spill["has_external_sort"] = True
            spill["details"].append(line)
        if "AUTO" in lo and "INDEX" in lo:
            spill["has_auto_index"] = True
            spill["details"].append(line)
    return spill


# ── Circuit loading & IQS conversion ──────────────────────────────────────

def load_qiskit_circuits() -> Dict[str, Any]:
    circuits = {}
    for qpy_file in sorted(CIRCUITS_DIR.glob("*.qpy")):
        h = qpy_file.stem
        label = CIRCUIT_LABELS.get(h, h[:8])
        with open(qpy_file, "rb") as f:
            loaded = qiskit.qpy.load(f)
        qc = loaded[0] if isinstance(loaded, list) else loaded
        circuits[label] = qc
    return circuits


def qiskit_to_iqs(qc) -> IQSCircuit:
    """Transpile a Qiskit circuit and convert to InfiniQuantumSim circuit."""
    tqc = transpile(qc,
                    basis_gates=["u", "cx", "id", "rz", "sx", "x"],
                    optimization_level=2)
    num_qubits = tqc.num_qubits
    iqs = IQSCircuit(num_qubits=num_qubits)

    for instr in tqc.data:
        op     = instr.operation
        qubits = [tqc.find_bit(q).index for q in instr.qubits]

        if op.name in ("barrier", "measure"):
            continue

        matrix = op.to_matrix()

        if len(qubits) == 1:
            tensor = matrix
        elif len(qubits) == 2:
            tensor = matrix.reshape(2, 2, 2, 2)
        else:
            raise ValueError(f"Unsupported gate on {len(qubits)} qubits: {op.name}")

        gate_name = f"{op.name}_{id(op)}" if op.params else op.name
        gate = IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2))
        iqs.add_gate(gate)

    return iqs


# ── SQLite deep benchmark ──────────────────────────────────────────────────

def sqlite_deep_run(iqs_qc: IQSCircuit, label: str) -> Dict[str, Any]:
    print(f"\n  [SQLite] {label}")

    # ── Build SQL query ────────────────────────────────────────────────────
    einstein, index_sizes, parameters = iqs_qc.convert_to_einsum()
    opt_rg    = oe.RandomGreedy(max_repeats=256)
    views     = oe.helpers.build_views(einstein, index_sizes)
    path_info = oe.contract_path(einstein, *views, optimize=opt_rg)[1]
    sql       = sql_einsum_query(einstein, parameters, iqs_qc.tensor_uniques,
                                 path_info=path_info, complex=True)

    # Basic SQL stats
    ctes = parse_ctes(sql)
    k_ctes   = [c for c in ctes if re.match(r'^K\d+$', c["name"])]
    ten_ctes = [c for c in ctes if not re.match(r'^K\d+$', c["name"])]

    print(f"    total CTEs  : {len(ctes)}  "
          f"(tensor CTEs: {len(ten_ctes)}, contraction CTEs: {len(k_ctes)})")
    print(f"    SQL length  : {len(sql):,} chars")

    # ── Open in-memory SQLite ──────────────────────────────────────────────
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA cache_size = -65536")   # 64 MB page cache (negative = KiB)
    # Keep temp_store in memory (2) — default; we just record if we *would* spill
    con.execute("PRAGMA temp_store = 2")

    # ── EXPLAIN QUERY PLAN on the full query ──────────────────────────────
    # Strip trailing ';' if present; SQLite EXPLAIN needs clean SQL
    clean_sql = sql.rstrip(";").strip()
    # The final query may be a SELECT at the top level; find it
    # We need the final SELECT (after all CTEs), which is already the full `sql`
    eqp_lines = explain_qp(con, clean_sql)
    spill_info = detect_spill_from_eqp(eqp_lines)

    # ── Pagecache overflow BEFORE ──────────────────────────────────────────
    pc_before_cur, pc_before_hw = sqlite_pagecache_overflow()

    # ── Run query & measure resources ────────────────────────────────────
    before = snapshot_resources()
    t0     = time.perf_counter()

    try:
        cur    = con.cursor()
        result = cur.execute(clean_sql).fetchall()
        ok     = True
        err    = None
    except Exception as exc:
        ok     = False
        err    = str(exc)
        result = []

    elapsed = time.perf_counter() - t0
    after   = snapshot_resources()
    res_delta = delta_resources(before, after)

    # ── Pagecache overflow AFTER ───────────────────────────────────────────
    pc_after_cur, pc_after_hw = sqlite_pagecache_overflow()
    pagecache_overflow_bytes = max(0, pc_after_hw - pc_before_hw)

    # ── Per-CTE row counts ─────────────────────────────────────────────────
    cte_stats: List[Dict] = []
    print(f"    Counting rows per K_i CTE ({len(k_ctes)} contraction CTEs)...")

    for c in k_ctes:
        q = build_count_query(ctes, c["name"])
        if q is None:
            count = None
        else:
            try:
                row = con.execute(q).fetchone()
                count = row[0] if row else 0
            except Exception as e:
                count = f"ERR:{e}"

        # Column count from column list (index cols + re + im)
        cols = [x.strip() for x in c["columns"].split(",") if x.strip()]
        n_index_cols = max(0, len(cols) - 2)  # subtract re and im
        # Estimated bytes: each row = n_index_cols * 8 bytes (int64) + 2 * 8 bytes (float64)
        bytes_per_row = n_index_cols * 8 + 2 * 8
        est_bytes = (count * bytes_per_row) if isinstance(count, int) else None

        stat = {
            "cte_name":     c["name"],
            "columns":      c["columns"],
            "n_index_cols": n_index_cols,
            "row_count":    count,
            "bytes_per_row": bytes_per_row,
            "est_bytes":    est_bytes,
        }
        cte_stats.append(stat)
        print(f"      {c['name']:6s}  rows={count}  "
              f"idx_cols={n_index_cols}  ~{est_bytes} bytes")

    # ── Tensor (leaf) CTE row counts ──────────────────────────────────────
    leaf_stats: List[Dict] = []
    for c in ten_ctes:
        q = build_count_query(ctes, c["name"])
        if q is None:
            count = None
        else:
            try:
                row = con.execute(q).fetchone()
                count = row[0] if row else 0
            except Exception as e:
                count = f"ERR:{e}"
        cols = [x.strip() for x in c["columns"].split(",") if x.strip()]
        n_index_cols = max(0, len(cols) - 2)
        bytes_per_row = n_index_cols * 8 + 2 * 8
        est_bytes = (count * bytes_per_row) if isinstance(count, int) else None
        leaf_stats.append({
            "cte_name":     c["name"],
            "n_index_cols": n_index_cols,
            "row_count":    count,
            "bytes_per_row": bytes_per_row,
            "est_bytes":    est_bytes,
        })

    # ── SQLite page stats ──────────────────────────────────────────────────
    page_size  = con.execute("PRAGMA page_size").fetchone()[0]
    page_count = con.execute("PRAGMA page_count").fetchone()[0]
    total_db_bytes = page_size * page_count

    con.close()

    # ── Final result ──────────────────────────────────────────────────────
    result_rows   = len(result) if ok else 0
    result_nz     = sum(1 for r in result if abs(r[-2]) > 1e-12 or abs(r[-1]) > 1e-12) if ok else 0

    return {
        "label":    label,
        "backend":  "sqlite",
        "success":  ok,
        "error":    err,

        # Timing
        "wall_s":   elapsed,

        # Resource metrics
        "peak_rss_bytes":       res_delta["peak_rss_bytes"],
        "vsz_bytes":            res_delta["vsz_bytes"],
        "delta_major_faults":   res_delta["delta_maj_flt"],
        "delta_minor_faults":   res_delta["delta_min_flt"],

        # Temp-file / spill info
        "pagecache_overflow_bytes": pagecache_overflow_bytes,
        "sqlite_in_memory":    True,
        "spill_detection":     spill_info,
        "eqp_lines":           eqp_lines,

        # Intermediate cardinalities
        "leaf_cte_count":        len(ten_ctes),
        "contraction_cte_count": len(k_ctes),
        "leaf_ctes":             leaf_stats,
        "contraction_ctes":      cte_stats,

        # Final result stats
        "result_rows":           result_rows,
        "result_nonzero_rows":   result_nz,

        # DB stats
        "sqlite_page_size":      page_size,
        "sqlite_page_count":     page_count,
        "sqlite_total_db_bytes": total_db_bytes,

        # SQL info
        "sql_length_chars":      len(sql),
        "total_cte_count":       len(ctes),
    }


# ── Aer deep benchmark ─────────────────────────────────────────────────────

def aer_deep_run(qc, label: str) -> List[Dict[str, Any]]:
    print(f"\n  [Aer] {label}  ({qc.num_qubits} qubits, depth {qc.depth()})")
    rows: List[Dict] = []

    for method in AER_METHODS:
        for single_core in (False, True):
            mode = "single" if single_core else "multi"
            sim_kwargs: Dict[str, Any] = {"method": method}
            if single_core:
                sim_kwargs |= SINGLE_CORE

            # Prepare circuit
            try:
                circ = transpile(qc, basis_gates=BASIS_GATES, optimization_level=0)
                if method == "unitary":
                    circ.save_unitary()
                else:
                    if not any(i.operation.name == "measure" for i in circ.data):
                        circ.measure_all()
                sim = AerSimulator(**sim_kwargs)
            except Exception as exc:
                rows.append({
                    "label": label, "backend": "aer",
                    "method": method, "mode": mode,
                    "success": False, "error": str(exc)[:120],
                })
                continue

            # Warm resource snapshot
            before = snapshot_resources()
            t0 = time.perf_counter()

            try:
                job    = sim.run(circ)
                result = job.result()
                ok     = result.success
                err    = None if ok else result.status
            except Exception as exc:
                ok  = False
                err = str(exc)[:120]

            elapsed = time.perf_counter() - t0
            after   = snapshot_resources()
            res_d   = delta_resources(before, after)

            mark = "+" if ok else "-"
            print(
                f"    [{mark}] {method:<26} [{mode:<6}]  "
                f"wall={elapsed:.4f}s  "
                f"rss={res_d['peak_rss_bytes']//1024:,}KB  "
                f"vsz={res_d['vsz_bytes']//1024//1024:,}MB  "
                f"Δmaj={res_d['delta_maj_flt']}"
            )

            rows.append({
                "label":   label,
                "backend": "aer",
                "method":  method,
                "mode":    mode,
                "success": ok,
                "error":   err if not ok else None,

                "wall_s":             elapsed,
                "peak_rss_bytes":     res_d["peak_rss_bytes"],
                "vsz_bytes":          res_d["vsz_bytes"],
                "delta_major_faults": res_d["delta_maj_flt"],
                "delta_minor_faults": res_d["delta_min_flt"],
            })

    return rows


# ── Summary printer ────────────────────────────────────────────────────────

def print_summary(all_results: Dict) -> None:
    sep = "─" * 100
    print(f"\n\n{'═'*100}")
    print("  DEEP BENCHMARK SUMMARY")
    print(f"{'═'*100}")

    for label in CIRCUIT_LABELS.values():
        if label not in all_results:
            continue
        d = all_results[label]
        sq = d.get("sqlite")
        aer_rows = d.get("aer", [])

        print(f"\n{'─'*100}")
        print(f"  Circuit: {label}")
        print(f"{'─'*100}")

        if sq:
            print(f"  SQLite  wall={sq['wall_s']:.4f}s  "
                  f"rss={sq['peak_rss_bytes']//1024:,}KB  "
                  f"vsz={sq['vsz_bytes']//1024//1024:,}MB  "
                  f"Δmaj={sq['delta_major_faults']}  "
                  f"pagecache_overflow={sq['pagecache_overflow_bytes']}B  "
                  f"sqlite_db_bytes={sq['sqlite_total_db_bytes']:,}")
            print(f"          temp_btree={sq['spill_detection']['has_temp_btree']}  "
                  f"auto_index={sq['spill_detection']['has_auto_index']}")
            print(f"          Leaf CTEs ({sq['leaf_cte_count']}), "
                  f"Contraction CTEs ({sq['contraction_cte_count']})")

            # Top-5 largest intermediate CTEs by est_bytes
            k_sorted = sorted(
                [c for c in sq["contraction_ctes"] if isinstance(c.get("est_bytes"), int)],
                key=lambda x: x["est_bytes"], reverse=True
            )[:5]
            if k_sorted:
                print(f"          Top-5 largest intermediate CTEs:")
                for c in k_sorted:
                    print(f"            {c['cte_name']:6s}  "
                          f"rows={c['row_count']:>8,}  "
                          f"idx_cols={c['n_index_cols']}  "
                          f"~{c['est_bytes']:>10,} bytes")

        print(f"\n  {'Method':<28} {'Mode':<7} {'wall_s':>8} "
              f"{'RSS_KB':>9} {'VSZ_MB':>7} {'ΔmajFlt':>8} {'ok':<4}")
        print(f"  {sep[:94]}")
        for r in aer_rows:
            if not r.get("wall_s"):
                continue
            print(
                f"  {r['method']:<28} {r['mode']:<7} {r['wall_s']:>8.4f} "
                f"{r['peak_rss_bytes']//1024:>9,} "
                f"{r['vsz_bytes']//1024//1024:>7,} "
                f"{r['delta_major_faults']:>8} "
                f"{'Y' if r['success'] else 'N':<4}"
            )

    print(f"\n{'═'*100}\n")


# ── Why Qiskit Loses: analysis note ────────────────────────────────────────

def explain_qiskit_losses(all_results: Dict) -> Dict:
    """
    Synthesise observations about why Qiskit methods lose compared to SQLite
    for certain circuits.
    """
    notes = {}
    for label in CIRCUIT_LABELS.values():
        d = all_results.get(label, {})
        sq = d.get("sqlite")
        aer_rows = d.get("aer", [])

        if not sq or not aer_rows:
            continue

        sqlite_wall = sq["wall_s"]
        sqlite_rss  = sq["peak_rss_bytes"]

        observations = []

        # Find best Aer method
        ok_aer = [r for r in aer_rows if r.get("success") and r.get("wall_s")]
        if ok_aer:
            best_time  = min(ok_aer, key=lambda r: r["wall_s"])
            worst_time = max(ok_aer, key=lambda r: r["wall_s"])
            best_rss   = min(ok_aer, key=lambda r: r["peak_rss_bytes"])

            time_ratio_best  = best_time["wall_s"] / max(sqlite_wall, 1e-9)
            time_ratio_worst = worst_time["wall_s"] / max(sqlite_wall, 1e-9)
            rss_ratio        = best_rss["peak_rss_bytes"] / max(sqlite_rss, 1)

            observations.append({
                "metric": "wall_time",
                "best_aer_method": best_time["method"],
                "best_aer_mode":   best_time["mode"],
                "best_aer_s":      best_time["wall_s"],
                "sqlite_s":        sqlite_wall,
                "ratio_best_over_sqlite": time_ratio_best,
                "note": (
                    "Qiskit best method is FASTER than SQLite" if time_ratio_best < 1
                    else "SQLite is FASTER than best Qiskit method"
                ),
            })
            observations.append({
                "metric": "rss_memory",
                "best_aer_rss_bytes": best_rss["peak_rss_bytes"],
                "sqlite_rss_bytes":   sqlite_rss,
                "ratio_aer_over_sqlite": rss_ratio,
                "note": (
                    "Qiskit uses LESS RSS than SQLite" if rss_ratio < 1
                    else "SQLite uses LESS RSS than Qiskit"
                ),
            })

            # Density matrix check (known to be expensive)
            dm_rows = [r for r in ok_aer if r["method"] == "density_matrix"]
            if dm_rows:
                dm_best = min(dm_rows, key=lambda r: r["wall_s"])
                observations.append({
                    "metric": "density_matrix_overhead",
                    "dm_wall_s":     dm_best["wall_s"],
                    "sqlite_wall_s": sqlite_wall,
                    "ratio":         dm_best["wall_s"] / max(sqlite_wall, 1e-9),
                    "note": (
                        "density_matrix is SLOWER than SQLite"
                        if dm_best["wall_s"] > sqlite_wall
                        else "density_matrix is FASTER than SQLite"
                    ),
                })

        # Check if SQLite spills to disk
        if sq["spill_detection"]["has_temp_btree"]:
            observations.append({
                "metric": "sqlite_temp_btree",
                "note":   "SQLite uses temp B-tree (GROUP BY / ORDER BY sort). "
                          "This is in-memory for :memory: db.",
                "details": sq["spill_detection"]["details"],
            })

        if sq["pagecache_overflow_bytes"] > 0:
            observations.append({
                "metric": "sqlite_pagecache_overflow",
                "overflow_bytes": sq["pagecache_overflow_bytes"],
                "note":   "SQLite page-cache overflowed (pages evicted/re-read).",
            })

        # Intermediate cardinality growth
        k_with_counts = [
            c for c in sq["contraction_ctes"]
            if isinstance(c.get("row_count"), int)
        ]
        if k_with_counts:
            max_intermediate = max(k_with_counts, key=lambda c: c["row_count"])
            total_intermed_bytes = sum(
                c["est_bytes"] for c in k_with_counts if isinstance(c.get("est_bytes"), int)
            )
            observations.append({
                "metric": "intermediate_cardinality",
                "max_intermediate_cte": max_intermediate["cte_name"],
                "max_intermediate_rows": max_intermediate["row_count"],
                "max_intermediate_bytes": max_intermediate["est_bytes"],
                "total_intermediate_bytes": total_intermed_bytes,
                "note": (
                    f"Largest intermediate {max_intermediate['cte_name']} has "
                    f"{max_intermediate['row_count']} rows "
                    f"(~{max_intermediate['est_bytes']:,} bytes). "
                    "SQLite stores SPARSE tensor representation (only non-zero amplitudes). "
                    "Qiskit statevector stores DENSE 2^n-element array. "
                    "For circuits with many zeros, SQLite wins on memory. "
                    "For dense states, SQLite's per-row overhead (indices + re + im) "
                    "plus GROUP-BY aggregation cost dominates."
                ),
            })

        notes[label] = observations

    return notes


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading QPY circuits …")
    qiskit_circuits = load_qiskit_circuits()
    for label, qc in qiskit_circuits.items():
        print(f"  {label}: {qc.num_qubits} qubits, depth {qc.depth()}")

    all_results: Dict[str, Any] = {}

    for label in CIRCUIT_LABELS.values():
        qc = qiskit_circuits.get(label)
        if qc is None:
            print(f"[WARN] {label} not found, skipping.")
            continue

        print(f"\n{'='*60}\n  Circuit: {label}  "
              f"({qc.num_qubits} qubits, depth {qc.depth()})\n{'='*60}")

        all_results[label] = {}

        # ── SQLite path ──────────────────────────────────────────────────
        try:
            iqs_qc = qiskit_to_iqs(qc)
            sq_result = sqlite_deep_run(iqs_qc, label)
            all_results[label]["sqlite"] = sq_result
        except Exception as exc:
            import traceback
            print(f"  [ERROR] SQLite path for {label}: {exc}")
            traceback.print_exc()
            all_results[label]["sqlite"] = {"error": str(exc), "success": False}

        # ── Aer path ─────────────────────────────────────────────────────
        try:
            aer_results = aer_deep_run(qc, label)
            all_results[label]["aer"] = aer_results
        except Exception as exc:
            import traceback
            print(f"  [ERROR] Aer path for {label}: {exc}")
            traceback.print_exc()
            all_results[label]["aer"] = []

    # ── Why-Qiskit-Loses analysis ─────────────────────────────────────────
    loss_analysis = explain_qiskit_losses(all_results)
    all_results["__loss_analysis__"] = loss_analysis

    # ── Print summary ─────────────────────────────────────────────────────
    print_summary(all_results)

    # ── Save JSON ─────────────────────────────────────────────────────────
    def _jsonify(v):
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
        if isinstance(v, np.ndarray):
            return v.tolist()
        raise TypeError(f"Not serialisable: {type(v)}")

    with open(OUT_JSON, "w") as f:
        json.dump(all_results, f, indent=2, default=_jsonify)

    print(f"Results written to: {OUT_JSON}")


if __name__ == "__main__":
    main()
