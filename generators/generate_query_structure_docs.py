#!/usr/bin/env python3
"""Generate InfiniQuantum query structure artifacts for algorithm generators.

For each algorithm generator this writes:
  - query_structure.md
  - monolithic.sql
  - monolithic_materialized.sql
  - split.sql

The SQL variants mirror the out-of-core worker modes:
  - monolithic: the raw InfiniQuantumSim WITH query
  - monolithic_materialized: the same query with AS MATERIALIZED CTE hints
  - split: one CREATE TEMP TABLE statement per K-step plus the final SELECT
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


THIS_FILE = Path(__file__).resolve()
INFERQ_ROOT = THIS_FILE.parents[1]
REPO_ROOT = THIS_FILE.parents[2]
IQS_ROOT = REPO_ROOT / "Infinidata-rdbms-simulator"

for path in (INFERQ_ROOT, IQS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from generators.algorithms.amplitude_estimation.amplitude_estimation_class import (  # noqa: E402
    AmplitudeEstimation,
)
from generators.algorithms.deutsch_jozsa.deutsch_jozsa_class import DeutschJozsa  # noqa: E402
from generators.algorithms.grover_no_ancilla.grover_no_ancilla_class import (  # noqa: E402
    GroverNoAncilla,
)
from generators.algorithms.grover_v_chain.grover_v_chain_class import GroverVChain  # noqa: E402
from generators.algorithms.qaoa import QAOA  # noqa: E402
from generators.algorithms.qft import QFTGenerator  # noqa: E402
from generators.algorithms.qnn import QNN  # noqa: E402
from generators.algorithms.qpe import QPE  # noqa: E402
from generators.algorithms.qwalk import QuantumWalk  # noqa: E402
from generators.algorithms.vqe import VQEGenerator  # noqa: E402
from generators.lib.generator import BaseParams  # noqa: E402
from qiskit import transpile  # noqa: E402
from scripts.ooc.worker import (  # noqa: E402
    _materialize_iqs_ctes,
    _parse_iqs_ctes,
    _split_iqs_query_per_step,
)


ALGORITHMS_ROOT = INFERQ_ROOT / "generators" / "algorithms"


@dataclass(frozen=True)
class AlgorithmSpec:
    slug: str
    display_name: str
    generator_cls: type
    kwargs: dict[str, Any]
    out_dir: Path
    generated_by: str = "InferQ/generators/generate_query_structure_docs.py"


def _algorithm_specs() -> list[AlgorithmSpec]:
    return [
        AlgorithmSpec(
            "amplitude_estimation",
            "Amplitude Estimation",
            AmplitudeEstimation,
            {"m": 2, "theta": 0.2},
            ALGORITHMS_ROOT / "amplitude_estimation",
        ),
        AlgorithmSpec(
            "deutsch_jozsa",
            "Deutsch-Jozsa",
            DeutschJozsa,
            {"n": 3, "oracle_type": "balanced", "bitstring": "101", "constant_output": 0},
            ALGORITHMS_ROOT / "deutsch_jozsa",
        ),
        AlgorithmSpec(
            "grover_no_ancilla",
            "Grover No Ancilla",
            GroverNoAncilla,
            {"n": 3, "target": "101", "iterations": 1},
            ALGORITHMS_ROOT / "grover_no_ancilla",
        ),
        AlgorithmSpec(
            "grover_v_chain",
            "Grover V-Chain",
            GroverVChain,
            {"n": 3, "target": "101", "iterations": 1},
            ALGORITHMS_ROOT / "grover_v_chain",
        ),
        AlgorithmSpec(
            "qaoa",
            "QAOA",
            QAOA,
            {
                "num_qubits": 3,
                "p": 1,
                "adjacency": [[0, 1, 0], [1, 0, 1], [0, 1, 0]],
                "gammas": [0.4],
                "betas": [0.2],
            },
            ALGORITHMS_ROOT / "qaoa_queries",
        ),
        AlgorithmSpec(
            "qft",
            "QFT",
            QFTGenerator,
            {"num_qubits": 3, "inverse": False, "do_swaps": True, "entangled": False},
            ALGORITHMS_ROOT / "qft_queries",
        ),
        AlgorithmSpec(
            "qnn",
            "QNN",
            QNN,
            {
                "num_qubits": 3,
                "feature_map_type": "ZFeatureMap",
                "ansatz_type": "RealAmplitudes",
                "reps_num": 1,
            },
            ALGORITHMS_ROOT / "qnn_queries",
        ),
        AlgorithmSpec(
            "qpe",
            "QPE",
            QPE,
            {"m": 2, "n_sys": 1, "approximation_degree": 0, "eigenphase": 0.25},
            ALGORITHMS_ROOT / "qpe_queries",
        ),
        AlgorithmSpec(
            "qwalk",
            "Quantum Walk",
            QuantumWalk,
            {"num_qubits": 3, "steps": 1, "coin_preparation_type": "hadamard"},
            ALGORITHMS_ROOT / "qwalk_queries",
        ),
        AlgorithmSpec(
            "vqe",
            "VQE",
            VQEGenerator,
            {
                "n": 3,
                "ansatz": "RealAmplitudes",
                "reps": 1,
                "entanglement": "linear",
                "parameter_prefix": "theta",
                "measure": False,
            },
            ALGORITHMS_ROOT / "vqe_queries",
        ),
    ]


_CTE_HEAD = re.compile(r"\s*(\w+)(\s*\([^)]*\))?\s+AS\s*(?:MATERIALIZED\s*)?\(", re.IGNORECASE)


def _cte_names(query: str) -> list[str]:
    s = query.lstrip()
    if not s.upper().startswith("WITH "):
        return []
    s = s[5:]
    names: list[str] = []
    pos = 0
    while True:
        match = _CTE_HEAD.match(s, pos)
        if not match:
            break
        names.append(match.group(1))
        i = match.end()
        depth = 1
        while i < len(s) and depth > 0:
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
            i += 1
        pos = i
        while pos < len(s) and s[pos] in " \t\n,":
            pos += 1
    return names


def _assign_deterministic_parameters(qc: Any) -> tuple[Any, dict[str, float]]:
    if not qc.parameters:
        return qc, {}
    ordered_params = sorted(qc.parameters, key=lambda param: param.name)
    values = {param: (index + 1) * 0.125 for index, param in enumerate(ordered_params)}
    assigned = qc.assign_parameters(values)
    return assigned, {param.name: value for param, value in values.items()}


def _statement_block(statements: list[str]) -> str:
    return ";\n\n".join(statement.rstrip("; \n") for statement in statements) + ";\n"


def _sql_header(spec: AlgorithmSpec, variant: str) -> str:
    return (
        f"-- {spec.display_name} InfiniQuantumSim query structure: {variant}\n"
        f"-- Generated by {spec.generated_by}\n\n"
    )


def _markdown_list(values: list[str], max_inline: int = 80) -> str:
    if not values:
        return "(none)"
    line = ", ".join(f"`{value}`" for value in values)
    if len(line) <= max_inline:
        return line
    return "\n".join(f"- `{value}`" for value in values)


def _operation_counts(qc: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for instruction in qc.data:
        name = instruction.operation.name
        if name in {"barrier", "measure"}:
            continue
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _build_iqs_query_deterministic(qc: Any) -> tuple[str, int, int]:
    """Build an IQS SQL query with stable generated gate names."""
    import opt_einsum as oe

    from InfiniQuantumSim.sql_commands import sql_einsum_query
    from InfiniQuantumSim.TLtensor import Gate as IQSGate
    from InfiniQuantumSim.TLtensor import QuantumCircuit as IQSQuantumCircuit
    from InfiniQuantumSim.utils import INDICES

    transpiled = transpile(qc, basis_gates=["u", "cx", "id", "rz", "sx", "x"], optimization_level=2)
    num_qubits = transpiled.num_qubits
    estimated = num_qubits + 3 * len(transpiled.data)
    if estimated >= len(INDICES):
        raise RuntimeError(f"circuit exceeds IQS index budget: {estimated} >= {len(INDICES)}")

    iqs = IQSQuantumCircuit(num_qubits=num_qubits)
    parameterized_counts: dict[str, int] = {}
    for instr in transpiled.data:
        op = instr.operation
        if op.name in {"barrier", "measure"}:
            continue
        qubits = [transpiled.find_bit(q).index for q in instr.qubits]
        matrix = op.to_matrix()
        if len(qubits) == 1:
            tensor = matrix
        elif len(qubits) == 2:
            tensor = matrix.reshape(2, 2, 2, 2)
        else:
            raise RuntimeError(f"unsupported {op.name} on {len(qubits)} qubits")

        if op.params:
            parameterized_counts[op.name] = parameterized_counts.get(op.name, 0) + 1
            gate_name = f"{op.name}_{parameterized_counts[op.name]}"
        else:
            gate_name = op.name

        iqs.add_gate(IQSGate(qubits, tensor, name=gate_name, two_qubit_gate=(len(qubits) == 2)))

    einstein, index_sizes, parameters = iqs.convert_to_einsum()
    views = oe.helpers.build_views(einstein, index_sizes)
    _, path_info = oe.contract_path(einstein, *views, optimize="greedy")
    query = sql_einsum_query(
        einstein,
        parameters,
        iqs.tensor_uniques,
        path_info=path_info,
        complex=True,
    )
    return query, num_qubits, len(iqs.gates)


def _write_artifacts(spec: AlgorithmSpec, base_params: BaseParams) -> dict[str, Any]:
    spec.out_dir.mkdir(parents=True, exist_ok=True)

    generator = spec.generator_cls(base_params)
    if not hasattr(generator, "measure"):
        generator.measure = base_params.measure
    qc = generator.generate(**spec.kwargs)
    original_parameter_count = len(qc.parameters)
    qc, assigned_parameters = _assign_deterministic_parameters(qc)
    transpiled = transpile(qc, basis_gates=["u", "cx", "id", "rz", "sx", "x"], optimization_level=2)

    monolithic_query, iqs_qubits, iqs_gates = _build_iqs_query_deterministic(qc)
    materialized_query = _materialize_iqs_ctes(monolithic_query)
    split_statements = _split_iqs_query_per_step(monolithic_query)
    split_query = _statement_block(split_statements)

    cte_counts = _parse_iqs_ctes(monolithic_query)
    cte_names = _cte_names(monolithic_query)
    helper_ctes = [name for name in cte_names if not name.startswith("K")]
    k_ctes = [name for name in cte_names if name.startswith("K")]

    (spec.out_dir / "monolithic.sql").write_text(
        _sql_header(spec, "monolithic") + monolithic_query.rstrip() + "\n",
        encoding="utf-8",
    )
    (spec.out_dir / "monolithic_materialized.sql").write_text(
        _sql_header(spec, "monolithic_materialized") + materialized_query.rstrip() + "\n",
        encoding="utf-8",
    )
    (spec.out_dir / "split.sql").write_text(
        _sql_header(spec, "split") + split_query,
        encoding="utf-8",
    )

    params_json = json.dumps(spec.kwargs, indent=2, sort_keys=True)
    assigned_json = json.dumps(assigned_parameters, indent=2, sort_keys=True)
    op_counts_json = json.dumps(_operation_counts(transpiled), indent=2, sort_keys=True)

    split_k_statements = max(0, len(split_statements) - 1)
    readme = f"""# {spec.display_name} Query Structure

Generated by `{spec.generated_by}`.

## Representative Circuit

- Generator: `{spec.generator_cls.__name__}`
- Parameters:

```json
{params_json}
```

- Qubits: `{qc.num_qubits}`
- Classical bits: `{qc.num_clbits}`
- Circuit depth: `{qc.depth()}`
- Circuit operations: `{qc.size()}`
- Transpiled operations used by InfiniQuantumSim:

```json
{op_counts_json}
```

- Symbolic parameters assigned before query generation: `{original_parameter_count}`

```json
{assigned_json}
```

## SQL Shape

- Monolithic file: `monolithic.sql`
- Materialized file: `monolithic_materialized.sql`
- Split file: `split.sql`
- IQS qubits: `{iqs_qubits}`
- IQS gates: `{iqs_gates}`
- Helper/tensor CTEs: `{cte_counts["num_h_ctes"]}`
- K-step contraction CTEs: `{cte_counts["num_k_ctes"]}`
- Split statements: `{len(split_statements)}` total, `{split_k_statements}` materialized K tables plus final SELECT

## CTE Order

Helper/tensor CTEs:

{_markdown_list(helper_ctes)}

K-step contraction CTEs:

{_markdown_list(k_ctes)}

## Variant Semantics

- `monolithic.sql` keeps the raw InfiniQuantumSim CTE cascade in one `WITH ... SELECT` query.
- `monolithic_materialized.sql` keeps one query but adds `AS MATERIALIZED` to each CTE.
- `split.sql` creates one temp table per `K*` contraction step and then runs the final SELECT with helper CTEs repeated as needed.
"""
    (spec.out_dir / "query_structure.md").write_text(readme, encoding="utf-8")

    return {
        "algorithm": spec.slug,
        "out_dir": str(spec.out_dir.relative_to(REPO_ROOT)),
        "iqs_gates": iqs_gates,
        "k_ctes": cte_counts["num_k_ctes"],
        "split_statements": len(split_statements),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--algorithm",
        action="append",
        choices=[spec.slug for spec in _algorithm_specs()],
        help="Generate one algorithm. Can be passed more than once. Defaults to all.",
    )
    args = parser.parse_args()

    selected = set(args.algorithm or [])
    specs = [spec for spec in _algorithm_specs() if not selected or spec.slug in selected]

    base_params = BaseParams(
        max_qubits=3,
        min_qubits=3,
        max_depth=1,
        min_depth=1,
        min_eval_qubits=2,
        max_eval_qubits=2,
        measure=False,
        seed=7,
    )

    summaries = [_write_artifacts(spec, base_params) for spec in specs]
    for summary in summaries:
        print(
            "{algorithm}: wrote {out_dir} "
            "(iqs_gates={iqs_gates}, k_ctes={k_ctes}, split_statements={split_statements})".format(
                **summary
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
