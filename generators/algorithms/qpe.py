from __future__ import annotations
from typing import Optional
import math

from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit import Gate
from qiskit.circuit.library import QFT
from generators.lib.generator import Generator, BaseParams
from generators.lib.parameters import (
    num_qbits,
    qpe_evaluation_qubits,
    qpe_approximation_degree,
    qpe_eigenphase_value,
    qpe_system_qubits,
)

"""Approximate / *inexact* Quantum Phase Estimation (QPE) generator
===================================================================
This generator mirrors the *exact* QPE implementation but allows you to
**deliberately approximate** the inverse Quantum Fourier Transform to trade
circuit depth for precision.  The approximation is controlled via
``approximation_degree`` – identical to the parameter used in
:class:`qiskit.circuit.library.QFT`.

Key idea
~~~~~~~~
Dropping controlled‑phase rotations smaller than ``π / 2**approximation_degree``
reduces two‑qubit gate count from *O(m²)* to *O(m log(1/ε))* while introducing a
bounded phase error ε.  For many NISQ use‑cases a modest
``approximation_degree ≈ 2–3`` dramatically lowers depth with only a few bits
of precision loss – hence **“inexact QPE”**.

Usage
-----
```python
from qiskit.circuit.library import RZ
from qpe_inexact import generate, demo_state_prep

phi = 0.34375   # 44/128
qc = generate(m=7, unitary=RZ(2*math.pi*phi), prepare_eigenstate=demo_state_prep(),
              approximation_degree=2)
print(qc.draw())
```

Parameters
~~~~~~~~~~
* ``m`` – evaluation‑qubit count.
* ``unitary`` – gate/circuit implementing *n‑qubit* U.
* ``prepare_eigenstate`` – circuit preparing an eigenstate |ψ⟩ of U.
* ``approximation_degree`` – non‑negative integer.  0 ⇒ exact QFT; 1 drops
  controlled‑phase of angle π/2; 2 drops π/4, etc.
* ``measure`` – attach measurements (default ``True``).
* ``name`` – custom circuit name.

Returns :class:`qiskit.circuit.QuantumCircuit` (m + n qubits).
"""

# -----------------------------------------------------------------------------
# Demo helper – prepare |1⟩ for single‑qubit Z‑family gates
# -----------------------------------------------------------------------------


def demo_state_prep() -> QuantumCircuit:
    qc = QuantumCircuit(1, name="|1⟩ prep")
    qc.x(0)
    return qc


# -----------------------------------------------------------------------------
# Internal utilities
# -----------------------------------------------------------------------------


def _as_gate(obj) -> Gate:
    if isinstance(obj, Gate):
        return obj
    if isinstance(obj, QuantumCircuit):
        return obj.to_gate()
    raise TypeError("unitary must be Gate or QuantumCircuit")


def _controlled_power(U: Gate, power: int) -> Gate:
    return U.power(power).control(1)


class QPE(Generator):
    """
    Class to generate a Quantum Phase Estimation circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = base_params.measure  # QPE always requires measurement

    def generate(
        self,
        m: int,
        n_sys: int = 1,
        approximation_degree: int = 1,
        eigenphase: float = 0.25,
        unitary: Optional[Gate] = None,
        prepare_eigenstate: Optional[QuantumCircuit] = None,
        name: Optional[str] = None,
    ) -> QuantumCircuit:
        """
        Generate a Quantum Phase Estimation circuit.

        Args:
            m (int): Number of evaluation qubits (≥ 1).
            n_sys (int): Number of system qubits.
            approximation_degree (int): QFT approximation degree.
            eigenphase (float): Eigenphase value for demo mode.
            unitary (Optional[Gate]): Custom unitary operator.
            prepare_eigenstate (Optional[QuantumCircuit]): Custom eigenstate preparation.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated QPE circuit.
        """
        if m < 1:
            raise ValueError("m must be ≥ 1")
        if approximation_degree < 0:
            raise ValueError("approximation_degree must be ≥ 0")

        # Create default unitary and eigenstate if not provided
        if unitary is None:
            unitary = self._create_demo_unitary(eigenphase, n_sys)
        if prepare_eigenstate is None:
            prepare_eigenstate = self._create_demo_eigenstate(n_sys)

        U_gate = _as_gate(unitary)
        if U_gate.num_qubits != n_sys:
            raise ValueError("unitary and eigenstate prep must act on same #qubits")

        # Registers
        qr_eval = QuantumRegister(m, "qpe")
        qr_sys = QuantumRegister(n_sys, "sys")
        cr_eval = ClassicalRegister(m, "c")
        qc = QuantumCircuit(qr_eval, qr_sys, cr_eval)
        qc.name = name or f"QPE({m}eval,{n_sys}sys,deg{approximation_degree})"

        # 1) Eigenstate preparation
        qc.append(prepare_eigenstate.to_gate(label="Prep|ψ⟩"), qr_sys)

        # 2) Hadamard layer
        qc.h(qr_eval)

        # 3) Controlled‑powers of U
        for j in range(m):
            power = 2**j
            qc.append(_controlled_power(U_gate, power), [qr_eval[j], *qr_sys])

        # 4) Approximate inverse QFT
        qft_inv = QFT(
            num_qubits=m,
            approximation_degree=approximation_degree,
            inverse=True,
            do_swaps=False,
            name="QFT†~",
        ).decompose()
        qc.append(qft_inv, qr_eval)

        # 5) Measurement
        if self.measure:
            qc.barrier()
            qc.measure(qr_eval, cr_eval)  # type: ignore[arg-type]

        # Metadata
        qc.metadata = {
            "algorithm": "InexactQPE",
            "m_eval": m,
            "n_system": n_sys,
            "approx_deg": approximation_degree,
            "eigenphase": eigenphase,
        }

        return qc.decompose()

    def _create_demo_unitary(self, eigenphase: float, n_sys: int) -> Gate:
        """Create a demo unitary for the given eigenphase."""
        # Create a simple RZ rotation unitary using standard circuit methods
        qc = QuantumCircuit(n_sys)
        qc.rz(2 * math.pi * eigenphase, 0)  # Apply phase to first qubit
        return qc.to_gate()

    def _create_demo_eigenstate(self, n_sys: int) -> QuantumCircuit:
        """Create a demo eigenstate preparation circuit."""
        qc = QuantumCircuit(n_sys, name="|ψ⟩ prep")
        qc.x(0)  # Prepare |1⟩ for first qubit (eigenstate of RZ)
        return qc

    def generate_parameters(self) -> tuple[int, int, int, float]:
        """
        Generate parameters for the QPE circuit.

        Returns:
            tuple: (m_eval, n_sys, approximation_degree, eigenphase)
        """
        # Calculate available qubits for evaluation vs system
        total_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )

        # Reserve at least 1 system qubit, rest for evaluation
        max_sys = min(3, total_qubits - 2)  # Keep some qubits for evaluation
        self.n_sys = qpe_system_qubits(self.base_params.seed, 1, max(1, max_sys))

        # Remaining qubits for evaluation
        max_eval = total_qubits - self.n_sys
        self.m_eval = qpe_evaluation_qubits(
            self.base_params.seed, min_eval=2, max_eval=max(2, max_eval)
        )

        # If total exceeds available, adjust
        if self.m_eval + self.n_sys > total_qubits:
            self.m_eval = total_qubits - self.n_sys

        self.approximation_degree = qpe_approximation_degree(self.base_params.seed)
        self.eigenphase = qpe_eigenphase_value(self.base_params.seed)

        return {
            "m": self.m_eval,
            "n_sys": self.n_sys,
            "approximation_degree": self.approximation_degree,
            "eigenphase": self.eigenphase,
        }


# -----------------------------------------------------------------------------
# Example usage for class-based approach
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    # Example usage of QPEGenerator class
    print("Example using QPEGenerator class:")
    from generators.lib.generator import BaseParams

    # Create base parameters
    params = BaseParams(
        max_qubits=8, min_qubits=4, max_depth=1, min_depth=1, measure=True, seed=42
    )

    # Create QPE generator
    qpe_gen = QPE(params)

    # Generate parameters
    params = qpe_gen.generate_parameters()
    print("Generated parameters:")
    print(f"  - Evaluation qubits: {params['m']}")
    print(f"  - System qubits: {params['n_sys']}")
    print(f"  - Approximation degree: {params['approximation_degree']}")
    print(f"  - Eigenphase: {params['eigenphase']:.4f}")

    # Generate QPE circuit with default demo unitary
    qpe_circuit = qpe_gen.generate(
        **params,
    )
    print(f"\nGenerated circuit: {qpe_circuit.name}")
    print(f"Total qubits: {qpe_circuit.num_qubits}")
    print(f"Circuit depth: {qpe_circuit.depth()}")
    print(f"Metadata: {qpe_circuit.metadata}")

    # Example with custom unitary
    print("\n" + "=" * 60)
    print("Example with custom unitary:")

    custom_eigenphase = 0.34375  # 44/128
    # Create custom unitary using QuantumCircuit.rz instead of RZ from library
    custom_unitary_qc = QuantumCircuit(1)
    custom_unitary_qc.rz(2 * math.pi * custom_eigenphase, 0)
    custom_unitary = custom_unitary_qc.to_gate()
    custom_eigenstate = demo_state_prep()

    qpe_circuit_custom = qpe_gen.generate(
        m=5,
        n_sys=1,
        approximation_degree=2,
        eigenphase=custom_eigenphase,
        unitary=custom_unitary,
        prepare_eigenstate=custom_eigenstate,
        name="CustomQPE",
    )
    print(f"Custom circuit: {qpe_circuit_custom.name}")
    print(f"Custom circuit qubits: {qpe_circuit_custom.num_qubits}")
    print(f"Custom circuit depth: {qpe_circuit_custom.depth()}")
    print(qpe_circuit_custom)