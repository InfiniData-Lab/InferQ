from __future__ import annotations

import random

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import (
    EfficientSU2,
    PauliFeatureMap,
    RealAmplitudes,
    TwoLocal,
    ZFeatureMap,
    ZZFeatureMap,
)

from inferq.generators.base import BaseParams, Generator
from inferq.generators.params import (
    num_qbits,
    qnn_ansatz_type,
    qnn_feature_map_type,
    qnn_reps,
)
from inferq.storage.hashing import compute_circuit_hash_simple

"""Quantum Neural Network (QNN) circuit generator
===============================================
This module provides both a class-based QNN generator and a functional interface
for generating Quantum Neural Network circuits. It supports various feature maps
(ZFeatureMap, ZZFeatureMap, PauliFeatureMap) and ansätze (RealAmplitudes, 
EfficientSU2, TwoLocal) with configurable repetitions and entanglement patterns.

Quick example
~~~~~~~~~~~~~
```python
# Class-based approach
from inferq.generators.algorithms.qnn import QNNGenerator
from inferq.generators.base import BaseParams

params = BaseParams(max_qubits=5, min_qubits=2, measure=True)
qnn_gen = QNNGenerator(params)
n, feature_map_type, ansatz_type, reps_num = qnn_gen.generate_parameters()
qc = qnn_gen.generate(n, feature_map_type, ansatz_type, reps_num)

# Function-based approach
from inferq.generators.algorithms.qnn import generate
qc = generate(n=4, feature_map='ZZFeatureMap', ansatz='RealAmplitudes', reps=2)
```

Parameters
~~~~~~~~~~
* ``n`` – number of qubits (``n ≥ 1``).
* ``feature_map`` – type of feature map ('ZFeatureMap', 'ZZFeatureMap', 'PauliFeatureMap').
* ``ansatz`` – type of ansatz ('RealAmplitudes', 'EfficientSU2', 'TwoLocal').
* ``reps`` – number of repetitions for the ansatz.
* ``entanglement`` – entanglement pattern for certain ansätze.
* ``measure`` – whether to add measurements. Default ``False``.
* ``name`` – optional circuit name.

Returns
~~~~~~~
:class:`qiskit.circuit.QuantumCircuit` containing the QNN circuit.
"""


class QNN(Generator):
    """
    Class to generate a Quantum Neural Network circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(
        self,
        num_qubits: int,
        feature_map_type: str = "ZZFeatureMap",
        ansatz_type: str = "RealAmplitudes",
        reps_num: int = 1,
        entanglement: str | None = None,
        name: str | None = None,
    ) -> QuantumCircuit:
        """
        Generate a Quantum Neural Network circuit.

        Args:
            num_qubits (int): Number of qubits (≥ 1).
            feature_map_type (str): Type of feature map.
            ansatz_type (str): Type of ansatz.
            reps_num (int): Number of repetitions for ansatz.
            entanglement (Optional[str]): Entanglement pattern.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated QNN circuit.
        """
        if num_qubits < 1:
            raise ValueError("num_qubits must be ≥ 1")

        # Create the quantum circuit
        qc = QuantumCircuit(num_qubits)
        qc.name = name or f"QNN({num_qubits}q,{feature_map_type},{ansatz_type})"

        # Create feature map
        feature_map = self._create_feature_map(feature_map_type, num_qubits).decompose()
        qc.compose(feature_map, inplace=True)

        # Add barrier for visual separation
        qc.barrier()

        # Create ansatz
        ansatz = self._create_ansatz(ansatz_type, num_qubits, reps_num, entanglement).decompose()
        qc.compose(ansatz, inplace=True)

        # Add measurements if requested
        if self.measure:
            qc.barrier()
            qc.measure_all()

        # Metadata
        qc.metadata = {
            "algorithm": "QNN",
            "n_qubits": num_qubits,
            "feature_map": feature_map_type,
            "ansatz": ansatz_type,
            "reps": reps_num,
            "entanglement": entanglement,
            "measured": self.measure,
        }

        return qc.decompose()

    def _create_feature_map(self, feature_map_type: str, num_qubits: int):
        """Create the specified feature map."""
        if feature_map_type == "ZFeatureMap":
            return ZFeatureMap(feature_dimension=num_qubits, reps=1)
        elif feature_map_type == "ZZFeatureMap":
            return ZZFeatureMap(feature_dimension=num_qubits, reps=1)
        elif feature_map_type == "PauliFeatureMap":
            return PauliFeatureMap(feature_dimension=num_qubits, reps=1)
        else:
            raise ValueError(f"Unknown feature map type: {feature_map_type}")

    def _create_ansatz(
        self,
        ansatz_type: str,
        num_qubits: int,
        reps_num: int,
        entanglement: str | None,
    ):
        """Create the specified ansatz."""
        # Set default entanglement if not specified
        if entanglement is None:
            entanglement = "linear"

        if ansatz_type == "RealAmplitudes":
            return RealAmplitudes(
                num_qubits=num_qubits, reps=reps_num, entanglement=entanglement
            )
        elif ansatz_type == "EfficientSU2":
            return EfficientSU2(
                num_qubits=num_qubits, reps=reps_num, entanglement=entanglement
            )
        elif ansatz_type == "TwoLocal":
            return TwoLocal(
                num_qubits=num_qubits,
                rotation_blocks="ry",
                entanglement_blocks="cx",
                entanglement=entanglement,
                reps=reps_num,
            )
        else:
            raise ValueError(f"Unknown ansatz type: {ansatz_type}")

    def generate_parameters(self) -> tuple[int, str, str, int]:
        """
        Generate parameters for the QNN circuit.

        Returns:
            tuple: (num_qubits, feature_map_type, ansatz_type, reps_num)
        """
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        # Generate feature map type using parameter helper
        self.feature_map_type = qnn_feature_map_type(self.base_params.seed)

        # Generate ansatz type using parameter helper
        self.ansatz_type = qnn_ansatz_type(self.base_params.seed)

        # Generate number of repetitions using parameter helper
        self.reps_num = qnn_reps(self.base_params.seed, 1, 3)

        return {
            "num_qubits": self.num_qubits,
            "feature_map_type": self.feature_map_type,
            "ansatz_type": self.ansatz_type,
            "reps_num": self.reps_num,
        }


# -----------------------------------------------------------------------------
# CLI for quick visualization
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a QNN circuit and save to SVG."
    )
    parser.add_argument("n", type=int, help="Number of qubits (≥1)")
    parser.add_argument(
        "--feature-map",
        choices=["ZFeatureMap", "ZZFeatureMap", "PauliFeatureMap"],
        default="ZZFeatureMap",
        help="Feature map type",
    )
    parser.add_argument(
        "--ansatz",
        choices=["RealAmplitudes", "EfficientSU2", "TwoLocal"],
        default="RealAmplitudes",
        help="Ansatz type",
    )
    parser.add_argument("--reps", type=int, default=1, help="Number of repetitions")
    parser.add_argument("--measure", action="store_true", help="Add measurements")
    parser.add_argument("--outfile", default="qnn.svg", help="Output SVG filename")
    args = parser.parse_args()

    # Example usage of class-based approach
    print("\nExample using QNNGenerator class:")
    from inferq.generators.base import BaseParams

    params = BaseParams(
        max_qubits=args.n,
        min_qubits=args.n,
        max_depth=1,
        min_depth=1,
        measure=args.measure,
        seed=42,
    )
    random.seed(params.seed)
    np.random.seed(params.seed)

    qnn_gen = QNN(params)
    params = qnn_gen.generate_parameters()
    qc_class = qnn_gen.generate(**params)
    print(
        f"Generated circuit: {qc_class.name}, qubits={qc_class.num_qubits}, depth={qc_class.depth()}"
    )
    print(
        f"Parameters: n={params['num_qubits']}, feature_map={params['feature_map_type']}, ansatz={params['ansatz_type']}, reps={params['reps_num']}"
    )
   
    print(compute_circuit_hash_simple(qc_class))
