from __future__ import annotations

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFT

from inferq.generators.base import BaseParams, Generator
from inferq.generators.params import demo_theta_value, evaluation_qubits

"""Quantum Amplitude Estimation circuit generator
=================================================
This module provides a single public entry‑point :pyfunc:`generate` that builds
an **Amplitude Estimation (AE)** circuit following the original QAE (based on
Quantum Phase Estimation) described by Brassard *et al.* 2002.  The generator
is *generic*: you may supply an arbitrary state‑preparation unitary *A* and its
associated Grover operator *Q* (the amplitude amplification operator).  For
quick experimentation, a 1‑qubit *demo* mode is included that estimates the
amplitude *a = sin² θ* of measuring ``|1⟩`` after a single‑qubit rotation by
``θ``.

Usage
-----
```python
from inferq.generators.algorithms.amplitude_estimation import generate, demo_state_prep, demo_grover

# Generic call — supply your own circuits ----------------------------
qc = generate(
    m=4,  # evaluation qubits ↔ precision 2⁻ᵐ
    state_preparation=my_A,      # QuantumCircuit
    grover_operator=my_Q,        # QuantumCircuit
)

# Quick demo ----------------------------------------------------------
qc_demo = generate(m=3, theta=0.3)  # estimates sin²(0.3) ≈ 0.0886
print(qc_demo.draw())
```

Parameters
~~~~~~~~~~
* ``m`` – number of evaluation (phase) qubits; precision ≈ 1/2ᵐ.
* ``state_preparation`` – :class:`~qiskit.circuit.QuantumCircuit` that maps
  ``|0…0⟩ → |ψ⟩ = A|0…0⟩``.
* ``grover_operator`` – :class:`~qiskit.circuit.QuantumCircuit` implementing the
  amplitude‑amplification operator ``Q = −A S₀ A† S_χ``.
* ``theta`` – shortcut for the built‑in 1‑qubit demo: provide an angle (rad)
  and the generator auto‑creates ``state_preparation`` (Ry(2θ)) and the
  corresponding ``grover_operator``.
* ``name`` – optional circuit name.

Exactly one of (``state_preparation`` & ``grover_operator``) **or** ``theta``
must be supplied.

Returns
~~~~~~~
:class:`qiskit.circuit.QuantumCircuit` – complete AE circuit with an ``m``‑bit
classical register holding the inverse‑QFT output.
"""

# -----------------------------------------------------------------------------
# Demo helper — single‑qubit amplitude: |ψ⟩ = cos θ |0⟩ + sin θ |1⟩
# -----------------------------------------------------------------------------


def demo_state_prep(theta: float) -> QuantumCircuit:
    """Return 1‑qubit state‑preparation circuit Ry(2θ)."""
    qc = QuantumCircuit(1, name=f"A(θ={theta:.3f})")
    qc.ry(2 * theta, 0)
    return qc


def demo_grover(theta: float) -> QuantumCircuit:
    """Return 1‑qubit Grover (amplification) operator for the demo state.

    Q = A Z A† Z  (|1⟩ is the *good* state; Z=I−2|1⟩⟨1| is S_χ and, up to a
    global phase, also S₀ for 1 qubit.)
    """
    qc = QuantumCircuit(1, name="Q")
    qc.ry(2 * theta, 0)
    qc.z(0)
    qc.ry(-2 * theta, 0)
    qc.z(0)
    return qc


# -----------------------------------------------------------------------------
# Internal helpers
# -----------------------------------------------------------------------------


def _controlled_power(q: QuantumCircuit, power: int) -> QuantumCircuit:
    """Return `q ** power` **controlled on 1 qubit** (ctrl→target list order)."""
    return q.power(power).control(1)


def _validate_inputs(
    m: int,
    state_preparation: QuantumCircuit | None,
    grover_operator: QuantumCircuit | None,
    theta: float | None,
) -> tuple[QuantumCircuit, QuantumCircuit]:
    """Validation & automatic demo‑circuit creation."""
    if m < 1:
        raise ValueError("m (evaluation qubits) must be ≥ 1")

    if state_preparation is None or grover_operator is None:
        if theta is None:
            raise ValueError(
                "Provide either (state_preparation & grover_operator) or theta for the demo mode"
            )
        # Auto‑build demo circuits (1 qubit)
        state_preparation = demo_state_prep(theta)
        grover_operator = demo_grover(theta)
    else:
        if theta is not None:
            raise ValueError("theta cannot be combined with explicit circuits")

    if state_preparation.num_qubits != grover_operator.num_qubits:
        raise ValueError(
            "state_preparation and grover_operator must act on the same number of qubits"
        )

    return state_preparation, grover_operator


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def generate(
    *,
    m: int,
    state_preparation: QuantumCircuit | None = None,
    grover_operator: QuantumCircuit | None = None,
    theta: float | None = None,
    name: str | None = None,
) -> QuantumCircuit:  # noqa: D401
    """Construct and return an Amplitude Estimation quantum circuit."""

    A, Q = _validate_inputs(m, state_preparation, grover_operator, theta)
    n_sys = A.num_qubits

    # Registers
    qr_eval = QuantumRegister(m, name="qpe")
    qr_sys = QuantumRegister(n_sys, name="sys")
    cr_eval = ClassicalRegister(m, name="c")
    qc = QuantumCircuit(qr_eval, qr_sys, cr_eval, name=name or "AmplitudeEstimation")

    # Step 1 ─ prepare |ψ⟩ on system register
    qc.append(A, qr_sys)

    # Step 2 ─ create uniform superposition on evaluation qubits
    qc.h(qr_eval)

    # Step 3 ─ apply controlled‑Q^{2^j}
    for j in range(m):
        power = 2**j
        controlled_Q = _controlled_power(Q, power)
        qc.append(controlled_Q, [qr_eval[j], *qr_sys])

    # Step 4 ─ inverse QFT on evaluation register
    qc.append(QFT(m, inverse=True, do_swaps=False, name="QFT†").decompose(), qr_eval)


    # Metadata
    qc.metadata = {
        "algorithm": "AmplitudeEstimation",
        "m_eval_qubits": m,
        "n_system_qubits": n_sys,
        "demo_theta": theta,
    }
    return qc


# -----------------------------------------------------------------------------
# CLI tool for quick inspection
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    import argparse

    from qiskit.visualization import circuit_drawer

    parser = argparse.ArgumentParser(
        description="Generate a QAE circuit (Brassard 2002) and save as image."
    )
    parser.add_argument("m", type=int, help="Number of evaluation qubits")
    parser.add_argument(
        "--theta", type=float, help="Demo mode: prepare 1‑qubit state Ry(2θ)"
    )
    parser.add_argument(
        "--outfile", default="amplitude_estimation.svg", help="Output image filename"
    )

    args = parser.parse_args()

    qc_cli = generate(m=args.m, theta=args.theta)
    circuit_drawer(qc_cli, output="mpl", filename=args.outfile, style="iqp")
    print(f"Circuit saved to {args.outfile}")

    # Example usage for testing
    print("\nExample usage:")
    qc_example = generate(m=3, theta=0.5)
    print(f"Generated circuit: {qc_example.name}")
    print(f"Evaluation qubits: {qc_example.metadata['m_eval_qubits']}")
    print(f"System qubits: {qc_example.metadata['n_system_qubits']}")
    print(f"Demo theta: {qc_example.metadata['demo_theta']}")


# Class-based wrapper for Amplitude Estimation algorithm
class AmplitudeEstimation(Generator):
    """
    Class to generate an Amplitude Estimation quantum circuit.
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = base_params  # Amplitude estimation always requires measurement

    def generate(
        self,
        m: int,
        theta: float,
        state_preparation: QuantumCircuit | None = None,
        grover_operator: QuantumCircuit | None = None,
        name: str | None = None,
    ) -> QuantumCircuit:
        """
        Generate an Amplitude Estimation circuit using the class-based approach.

        Args:
            m (int): Number of evaluation qubits.
            theta (float): Demo theta value for single-qubit demo mode.
            state_preparation (Optional[QuantumCircuit]): Custom state preparation circuit.
            grover_operator (Optional[QuantumCircuit]): Custom Grover operator circuit.
            name (Optional[str]): Optional circuit name.

        Returns:
            QuantumCircuit: The generated amplitude estimation circuit.
        """
        # Use the original generate function for the actual circuit construction
        qc = generate(
            m=m,
            state_preparation=state_preparation,
            grover_operator=grover_operator,
            theta=theta,
            name=name or f"AmplitudeEstimation({m}eval,θ={theta:.3f})",
        )

        return qc

    def generate_parameters(self) -> tuple[int, float]:
        """
        Generate parameters for the Amplitude Estimation circuit.

        Returns:
            tuple: (m_evaluation_qubits, theta_value)
        """
        self.m_eval_qubits = evaluation_qubits(
            self.base_params.min_eval_qubits,
            self.base_params.max_eval_qubits,
            self.base_params.seed,
        )

        self.theta_value = demo_theta_value(seed=self.base_params.seed)

        return self.m_eval_qubits, self.theta_value


if __name__ == "__main__":
    # Example usage
    params = BaseParams(
        max_qubits=3,
        min_qubits=2,
        max_depth=5,
        min_depth=1,
        min_eval_qubits=2,
        max_eval_qubits=4,
        measure=True,
    )

    ae_generator = AmplitudeEstimation(params)
    m_eval, theta = ae_generator.generate_parameters()

    print("Generated parameters:")
    print(f"  - Evaluation qubits: {m_eval}")
    print(f"  - Theta value: {theta:.4f}")

    ae_circuit = ae_generator.generate(m_eval, theta)
    print(ae_circuit)
    print(f"\nGenerated circuit: {ae_circuit.name}")
    print(f"Total qubits: {ae_circuit.num_qubits}")
    print(f"Classical registers: {len(ae_circuit.cregs)}")
