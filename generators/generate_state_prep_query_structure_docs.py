#!/usr/bin/env python3
"""Generate InfiniQuantum query structure artifacts for state-prep generators."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


THIS_FILE = Path(__file__).resolve()
INFERQ_ROOT = THIS_FILE.parents[1]
REPO_ROOT = THIS_FILE.parents[2]
IQS_ROOT = REPO_ROOT / "Infinidata-rdbms-simulator"

for path in (INFERQ_ROOT, IQS_ROOT, THIS_FILE.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


from generate_query_structure_docs import AlgorithmSpec, _write_artifacts  # noqa: E402
from generators.lib.generator import BaseParams  # noqa: E402
from generators.state_prep_circuits.effu2 import EfficientU2  # noqa: E402
from generators.state_prep_circuits.ghz import GHZ  # noqa: E402
from generators.state_prep_circuits.graph_state import GraphState  # noqa: E402
from generators.state_prep_circuits.random_circuit import RandomCircuit  # noqa: E402
from generators.state_prep_circuits.realamp_ansatz_rand import RealAmplitudes  # noqa: E402
from generators.state_prep_circuits.two_local_rand import TwoLocal  # noqa: E402
from generators.state_prep_circuits.wstate import WState  # noqa: E402


STATE_PREP_SQL_ROOT = INFERQ_ROOT / "generators" / "state_prep_circuits" / "sql"
GENERATED_BY = "InferQ/generators/generate_state_prep_query_structure_docs.py"


def _linear_values(count: int) -> list[float]:
    return [(index + 1) * 0.125 for index in range(count)]


def _state_prep_specs() -> list[AlgorithmSpec]:
    return [
        AlgorithmSpec(
            "ghz",
            "GHZ State",
            GHZ,
            {"num_qubits": 3},
            STATE_PREP_SQL_ROOT / "ghz_queries",
            GENERATED_BY,
        ),
        AlgorithmSpec(
            "wstate",
            "W State",
            WState,
            {"num_qubits": 3},
            STATE_PREP_SQL_ROOT / "wstate_queries",
            GENERATED_BY,
        ),
        AlgorithmSpec(
            "graph_state",
            "Graph State",
            GraphState,
            {"adjacency": [[0, 1, 1], [1, 0, 0], [1, 0, 0]]},
            STATE_PREP_SQL_ROOT / "graph_state_queries",
            GENERATED_BY,
        ),
        AlgorithmSpec(
            "random_circuit",
            "Random Circuit",
            RandomCircuit,
            {"width": 3, "depth": 1},
            STATE_PREP_SQL_ROOT / "random_circuit_queries",
            GENERATED_BY,
        ),
        AlgorithmSpec(
            "efficient_u2",
            "EfficientU2",
            EfficientU2,
            {"num_qubits": 3, "entanglement": "linear", "reps": 1},
            STATE_PREP_SQL_ROOT / "efficient_u2_queries",
            GENERATED_BY,
        ),
        AlgorithmSpec(
            "real_amplitudes",
            "Real Amplitudes",
            RealAmplitudes,
            {
                "num_qubits": 3,
                "circuit_depth": 1,
                "parameter_values": _linear_values(6),
            },
            STATE_PREP_SQL_ROOT / "real_amplitudes_queries",
            GENERATED_BY,
        ),
        AlgorithmSpec(
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
            STATE_PREP_SQL_ROOT / "two_local_queries",
            GENERATED_BY,
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-prep",
        action="append",
        choices=[spec.slug for spec in _state_prep_specs()],
        help="Generate one state-prep circuit. Can be passed more than once. Defaults to all.",
    )
    args = parser.parse_args()

    selected = set(args.state_prep or [])
    specs = [spec for spec in _state_prep_specs() if not selected or spec.slug in selected]

    base_params = BaseParams(
        max_qubits=3,
        min_qubits=3,
        max_depth=1,
        min_depth=1,
        min_reps=1,
        max_reps=1,
        measure=False,
        seed=7,
    )

    summaries: list[dict[str, Any]] = [_write_artifacts(spec, base_params) for spec in specs]
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
