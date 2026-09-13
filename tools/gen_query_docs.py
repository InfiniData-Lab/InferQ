#!/usr/bin/env python3
"""Regenerate the InfiniQuantumSim query-structure reference under docs/.

For every generator — ten algorithms and seven state-prep circuits — this writes a
directory under ``docs/query-structures/<name>/`` containing:

    query_structure.md          circuit shape, CTE inventory, variant semantics
    monolithic.sql              the raw InfiniQuantumSim WITH query
    monolithic_materialized.sql the same query with AS MATERIALIZED CTE hints
    split.sql                   one CREATE TEMP TABLE per K-step, then the SELECT

The three SQL variants are exactly the modes the out-of-core worker compares, so
these files double as the fixtures ``tests/test_sql_query_modes.py`` parses.

The output is deterministic: symbolic parameters are assigned fixed values and the
IQS gate names are numbered in circuit order, so a regeneration that changes a byte
means the lowering changed.

Requires InfiniQuantumSim, which is not a runtime dependency of ``inferq``:

    uv run --group infiniquantum python tools/gen_query_docs.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qiskit import transpile

from inferq import paths
from inferq.generators.algorithms.amplitude_estimation import AmplitudeEstimation
from inferq.generators.algorithms.deutsch_jozsa import DeutschJozsa
from inferq.generators.algorithms.grover_no_ancilla import GroverNoAncilla
from inferq.generators.algorithms.grover_v_chain import GroverVChain
from inferq.generators.algorithms.qaoa import QAOA
from inferq.generators.algorithms.qft import QFTGenerator
from inferq.generators.algorithms.qnn import QNN
from inferq.generators.algorithms.qpe import QPE
from inferq.generators.algorithms.qwalk import QuantumWalk
from inferq.generators.algorithms.vqe import VQEGenerator
from inferq.generators.base import BaseParams
from inferq.generators.state_prep.efficient_u2 import EfficientU2
from inferq.generators.state_prep.ghz import GHZ
from inferq.generators.state_prep.graph_state import GraphState
from inferq.generators.state_prep.random_circuit import RandomCircuit
from inferq.generators.state_prep.real_amplitudes import RealAmplitudes
from inferq.generators.state_prep.two_local import TwoLocal
from inferq.generators.state_prep.wstate import WState
from inferq.sql.query_modes import (
    count_iqs_ctes,
    iqs_cte_names,
    materialize_iqs_ctes,
    split_iqs_query_per_step,
    statement_block,
)

GENERATED_BY = "tools/gen_query_docs.py"


#: Set by ``--check`` so a verification run writes to a scratch tree instead of
#: over the committed reference.
_OUTPUT_OVERRIDE: Path | None = None


def docs_root() -> Path:
    """Directory the reference is written to.

    Anchored on the checkout, not the working directory: regenerating the docs
    from anywhere must land in the same place or the drift check is meaningless.
    """
    if _OUTPUT_OVERRIDE is not None:
        return _OUTPUT_OVERRIDE
    checkout = paths.repo_root()
    if checkout is None:
        raise SystemExit(
            "tools/gen_query_docs.py must run from an InferQ checkout; "
            "there is nowhere to write docs/query-structures/ from a wheel."
        )
    return checkout / "docs" / "query-structures"


@dataclass(frozen=True)
class GeneratorSpec:
    """One generator and the fixed arguments its reference circuit is built with."""

    slug: str
    display_name: str
    generator_cls: type
    kwargs: dict[str, Any]
    generated_by: str = GENERATED_BY

    @property
    def out_dir(self) -> Path:
        return docs_root() / self.slug


def _algorithm_specs() -> list[GeneratorSpec]:
    return [
        GeneratorSpec(
            "amplitude_estimation",
            "Amplitude Estimation",
            AmplitudeEstimation,
            {"m": 2, "theta": 0.2},
        ),
        GeneratorSpec(
            "deutsch_jozsa",
            "Deutsch-Jozsa",
            DeutschJozsa,
            {"n": 3, "oracle_type": "balanced", "bitstring": "101", "constant_output": 0},
        ),
        GeneratorSpec(
            "grover_no_ancilla",
            "Grover No Ancilla",
            GroverNoAncilla,
            {"n": 3, "target": "101", "iterations": 1},
        ),
        GeneratorSpec(
            "grover_v_chain",
            "Grover V-Chain",
            GroverVChain,
            {"n": 3, "target": "101", "iterations": 1},
        ),
        GeneratorSpec(
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
        ),
        GeneratorSpec(
            "qft",
            "QFT",
            QFTGenerator,
            {"num_qubits": 3, "inverse": False, "do_swaps": True, "entangled": False},
        ),
        GeneratorSpec(
            "qnn",
            "QNN",
            QNN,
            {
                "num_qubits": 3,
                "feature_map_type": "ZFeatureMap",
                "ansatz_type": "RealAmplitudes",
                "reps_num": 1,
            },
        ),
        GeneratorSpec(
            "qpe",
            "QPE",
            QPE,
            {"m": 2, "n_sys": 1, "approximation_degree": 0, "eigenphase": 0.25},
        ),
        GeneratorSpec(
            "qwalk",
            "Quantum Walk",
            QuantumWalk,
            {"num_qubits": 3, "steps": 1, "coin_preparation_type": "hadamard"},
        ),
        GeneratorSpec(
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
        ),
    ]


def _assign_deterministic_parameters(qc: Any) -> tuple[Any, dict[str, float]]:
    if not qc.parameters:
        return qc, {}
    ordered_params = sorted(qc.parameters, key=lambda param: param.name)
    values = {param: (index + 1) * 0.125 for index, param in enumerate(ordered_params)}
    assigned = qc.assign_parameters(values)
    return assigned, {param.name: value for param, value in values.items()}


def _sql_header(spec: GeneratorSpec, variant: str) -> str:
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


def _write_artifacts(spec: GeneratorSpec, base_params: BaseParams) -> dict[str, Any]:
    spec.out_dir.mkdir(parents=True, exist_ok=True)

    generator = spec.generator_cls(base_params)
    if not hasattr(generator, "measure"):
        generator.measure = base_params.measure
    qc = generator.generate(**spec.kwargs)
    original_parameter_count = len(qc.parameters)
    qc, assigned_parameters = _assign_deterministic_parameters(qc)
    transpiled = transpile(qc, basis_gates=["u", "cx", "id", "rz", "sx", "x"], optimization_level=2)

    monolithic_query, iqs_qubits, iqs_gates = _build_iqs_query_deterministic(qc)
    materialized_query = materialize_iqs_ctes(monolithic_query)
    split_statements = split_iqs_query_per_step(monolithic_query)
    split_query = statement_block(split_statements)

    cte_counts = count_iqs_ctes(monolithic_query)
    cte_names = iqs_cte_names(monolithic_query)
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
        "out_dir": str(spec.out_dir.relative_to(docs_root().parent.parent)),
        "iqs_gates": iqs_gates,
        "k_ctes": cte_counts["num_k_ctes"],
        "split_statements": len(split_statements),
    }


def _linear_values(count: int) -> list[float]:
    return [(index + 1) * 0.125 for index in range(count)]


def _state_prep_specs() -> list[GeneratorSpec]:
    return [
        GeneratorSpec(
            "ghz",
            "GHZ State",
            GHZ,
            {"num_qubits": 3},
        ),
        GeneratorSpec(
            "wstate",
            "W State",
            WState,
            {"num_qubits": 3},
        ),
        GeneratorSpec(
            "graph_state",
            "Graph State",
            GraphState,
            {"adjacency": [[0, 1, 1], [1, 0, 0], [1, 0, 0]]},
        ),
        GeneratorSpec(
            "random_circuit",
            "Random Circuit",
            RandomCircuit,
            {"width": 3, "depth": 1},
        ),
        GeneratorSpec(
            "efficient_u2",
            "EfficientU2",
            EfficientU2,
            {"num_qubits": 3, "entanglement": "linear", "reps": 1},
        ),
        GeneratorSpec(
            "real_amplitudes",
            "Real Amplitudes",
            RealAmplitudes,
            {
                "num_qubits": 3,
                "circuit_depth": 1,
                "parameter_values": _linear_values(6),
            },
        ),
        GeneratorSpec(
            "two_local",
            "TwoLocal",
            TwoLocal,
            {
                "num_qubits": 3,
                "circuit_reps": 1,
                "parameter_values": _linear_values(12),
                "rotation_blocks": ["ry", "rz"],
                "entanglement_blocks": ["cx"],
                "entanglement": "linear",
                "skip_final_rotation_layer": False,
            },
        ),
    ]


def _base_params(**overrides: Any) -> BaseParams:
    """Fixed generator parameters. Any change here regenerates every artifact."""
    defaults = dict(
        max_qubits=3,
        min_qubits=3,
        max_depth=1,
        min_depth=1,
        measure=False,
        seed=7,
    )
    defaults.update(overrides)
    return BaseParams(**defaults)


#: Each family needs a different slice of BaseParams: algorithms size their
#: evaluation register, state-prep circuits their repetition count.
FAMILIES = {
    "algorithm": (_algorithm_specs, dict(min_eval_qubits=2, max_eval_qubits=2)),
    "state-prep": (_state_prep_specs, dict(min_reps=1, max_reps=1)),
}


def _all_specs() -> list[tuple[GeneratorSpec, BaseParams]]:
    pairs = []
    for build_specs, params in FAMILIES.values():
        base = _base_params(**params)
        pairs.extend((spec, base) for spec in build_specs())
    return pairs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name",
        action="append",
        choices=sorted(spec.slug for spec, _ in _all_specs()),
        help="Regenerate one generator's artifacts. Repeatable. Defaults to all.",
    )
    parser.add_argument(
        "--family",
        action="append",
        choices=sorted(FAMILIES),
        help="Regenerate one family. Repeatable. Defaults to all.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Do not write. Regenerate into a scratch tree and fail if it differs "
            "from the committed reference -- the lowering changed without the "
            "docs being updated."
        ),
    )
    return parser.parse_args(argv)


def _check(selected: list[tuple[GeneratorSpec, BaseParams]]) -> int:
    """Regenerate into a temporary tree and diff it against what is committed."""
    global _OUTPUT_OVERRIDE

    committed = docs_root()
    differences: list[str] = []

    with tempfile.TemporaryDirectory() as scratch:
        _OUTPUT_OVERRIDE = Path(scratch)
        try:
            for spec, base in selected:
                _write_artifacts(spec, base)
        finally:
            _OUTPUT_OVERRIDE = None

        for spec, _ in selected:
            fresh_dir = Path(scratch) / spec.slug
            for fresh in sorted(fresh_dir.iterdir()):
                existing = committed / spec.slug / fresh.name
                if not existing.exists():
                    differences.append(f"missing: {spec.slug}/{fresh.name}")
                elif existing.read_bytes() != fresh.read_bytes():
                    differences.append(f"stale: {spec.slug}/{fresh.name}")

    if differences:
        print("docs/query-structures is out of date:", file=sys.stderr)
        for difference in differences:
            print(f"  {difference}", file=sys.stderr)
        print("\nRegenerate with: uv run python tools/gen_query_docs.py", file=sys.stderr)
        return 1

    print(f"docs/query-structures matches the lowering ({len(selected)} generators)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    families = set(args.family or FAMILIES)
    names = set(args.name or ())

    selected = []
    for family, (build_specs, params) in FAMILIES.items():
        if family not in families:
            continue
        base = _base_params(**params)
        selected.extend(
            (spec, base) for spec in build_specs() if not names or spec.slug in names
        )

    if not selected:
        raise SystemExit("no generators selected")

    if args.check:
        return _check(selected)

    for spec, base in selected:
        summary = _write_artifacts(spec, base)
        print(
            "{algorithm}: wrote {out_dir} "
            "(iqs_gates={iqs_gates}, k_ctes={k_ctes}, split_statements={split_statements})".format(
                **summary
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
