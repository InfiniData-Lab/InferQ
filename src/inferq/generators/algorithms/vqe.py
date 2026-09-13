from __future__ import annotations

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit import Parameter
from qiskit.circuit.library import (
    EfficientSU2,
    NLocal,
    RealAmplitudes,
    TwoLocal,
)

from inferq.generators.base import BaseParams, Generator
from inferq.generators.params import (
    num_qbits,
    vqe_ansatz_type,
    vqe_entanglement_pattern,
    vqe_parameter_prefix,
    vqe_reps,
)

"""Variational Quantum Eigensolver (VQE) circuit generator
=========================================================
This module offers a single public entry‑point :pyfunc:`generate` that returns a
**parameterised ansatz circuit** suitable for use in a VQE workflow.  While the
full VQE algorithm requires generating *measurement* circuits for each Pauli
term of the Hamiltonian, that outer loop is optimiser‑specific; here we focus
on building the *ansatz* (trial wave‑function) with sensible defaults and
metadata.

Features
~~~~~~~~
* Choose one of Qiskit’s standard ansatz templates
  (``"RealAmplitudes"``, ``"EfficientSU2"``, ``"TwoLocal"``) **or**
  pass your own :class:`~qiskit.circuit.QuantumCircuit`.
* Control depth via ``reps`` and entanglement pattern via ``entanglement``.
* Optionally embed measurement gates so the circuit is executable as‑is.

Example – 6‑qubit RealAmplitudes ansatz
--------------------------------------
```python
from inferq.generators.algorithms.vqe import generate
qc, params = generate(n=6, ansatz="RealAmplitudes", reps=2)
print(qc.draw())
```

API
~~~
```python
vqe.generate(
    *,
    n: int,                        # number of qubits
    ansatz: str | QuantumCircuit = "RealAmplitudes",
    reps: int = 1,
    entanglement: str | list[str] = "full",
    parameter_prefix: str = "θ",
    measure: bool = True,
    name: str | None = None,
) -> tuple[QuantumCircuit, list[Parameter]]
```
The function returns the **ansatz circuit** (with optional measurements) and
its ordered list of :class:`~qiskit.circuit.Parameter` objects so you can plug
values into an optimiser.
"""


# Mapping from string → ansatz class ------------------------------------------------
_ANSATZ_MAP = {
    "RealAmplitudes": RealAmplitudes,
    "EfficientSU2": EfficientSU2,
    "TwoLocal": TwoLocal,
}


# -----------------------------------------------------------------------------
# Class-based VQE Generator
# -----------------------------------------------------------------------------


class VQEGenerator(Generator):
    """Class-based generator for Variational Quantum Eigensolver (VQE) ansatz circuits.

    This generator creates parameterized ansatz circuits suitable for VQE workflows.
    It supports various ansatz templates from Qiskit's circuit library and allows
    customization of depth, entanglement patterns, and parameter naming.

    Example:
        >>> from generators.lib.generator import BaseParams
        >>> params = BaseParams(max_qubits=5, min_qubits=2, measure=True)
        >>> generator = VQEGenerator(params)
        >>> vqe_params = generator.generate_parameters()
        >>> qc, circuit_params = generator.generate(vqe_params['n'], **vqe_params)
        >>> print(f"Generated VQE circuit with {len(circuit_params)} parameters")
    """

    def __init__(self, base_params: BaseParams):
        super().__init__(base_params)
        self.measure = self.base_params.measure

    def generate(
        self,
        n: int,
        ansatz: str | QuantumCircuit = "RealAmplitudes",
        reps: int = 1,
        entanglement: str | list[str] = "full",
        parameter_prefix: str = "θ",
        measure: bool | None = None,
        name: str | None = None,
    ) -> QuantumCircuit:
        """Generate a VQE ansatz circuit.

        Args:
            n: Number of qubits.
            ansatz: Either a string key (see docs) or a pre-built QuantumCircuit.
            reps: Number of repeated layers in the ansatz template.
            entanglement: Entanglement pattern for the ansatz.
            parameter_prefix: Prefix for automatic Parameter symbol names.
            measure: If True, append measurement gates. If None, uses base_params.measure.
            name: Optional circuit name.

        Returns:
            Tuple of (QuantumCircuit, list of Parameters).
        """
        if measure is None:
            measure = self.measure

        if n < 1:
            raise ValueError("n must be ≥ 1")
        if reps < 1:
            raise ValueError("reps must be ≥ 1")

        # ------------------------------------------------------------------
        # Build / validate ansatz template
        # ------------------------------------------------------------------
        if isinstance(ansatz, QuantumCircuit):
            template: QuantumCircuit = ansatz
        else:
            if ansatz not in _ANSATZ_MAP:
                raise ValueError(
                    f"Unknown ansatz '{ansatz}'. Choose from {list(_ANSATZ_MAP)} or supply a circuit."
                )
            cls = _ANSATZ_MAP[ansatz]
            if issubclass(cls, NLocal):
                template = cls(
                    num_qubits=n,
                    reps=reps,
                    entanglement=entanglement,
                    parameter_prefix=parameter_prefix,
                )
            else:  # pragma: no cover – all mapped classes are NLocal
                template = cls(
                    num_qubits=n,
                    reps=reps,
                    entanglement=entanglement,
                    parameter_prefix=parameter_prefix,
                )

        params: list[Parameter] = list(template.parameters)

        # ------------------------------------------------------------------
        # Wrap into outer circuit with measurement (optional)
        # ------------------------------------------------------------------
        qr = QuantumRegister(n, "q")
        cr = ClassicalRegister(n, "c") if measure else None
        qc = QuantumCircuit(qr, cr) if cr else QuantumCircuit(qr)
        qc.name = name or f"VQE_{template.name}"  # type: ignore[attr-defined]

        qc.append(template.to_gate(label=template.name), qr)

        if measure:
            qc.barrier()
            qc.measure(qr, cr)  # type: ignore[arg-type]

        qc.metadata = {
            "algorithm": "VQE_ansatz",
            "n_qubits": n,
            "ansatz": template.name,  # type: ignore[attr-defined]
            "reps": reps,
            "entanglement": entanglement,
            "param_count": len(params),
            "measured": measure,
        }

        return qc

    def generate_parameters(self) -> dict:
        """Generate parameters for the VQE circuit using base_params.

        Returns:
            Dictionary containing all parameters needed for generate().
        """
        self.num_qubits = num_qbits(
            self.base_params.min_qubits,
            self.base_params.max_qubits,
            self.base_params.seed,
        )
        self.ansatz = vqe_ansatz_type(seed=self.base_params.seed)
        self.reps = vqe_reps(seed=self.base_params.seed)
        self.entanglement = vqe_entanglement_pattern(seed=self.base_params.seed)
        self.parameter_prefix = vqe_parameter_prefix(seed=self.base_params.seed)
        self.measure = self.base_params.measure

        return {
            "n": self.num_qubits,
            "ansatz": self.ansatz,
            "reps": self.reps,
            "entanglement": self.entanglement,
            "parameter_prefix": self.parameter_prefix,
            "measure": self.measure,
            "name": f"VQE_{self.ansatz}_{self.num_qubits}q",
        }


# -----------------------------------------------------------------------------
# CLI helper
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    from inferq.generators.base import BaseParams

    # Example usage following GHZ pattern
    params = BaseParams(
        max_qubits=6, min_qubits=2, max_depth=10, min_depth=1, measure=True, seed=42
    )
    vqe_generator = VQEGenerator(params)
    vqe_params = vqe_generator.generate_parameters()
    vqe_circuit, circuit_params = vqe_generator.generate(**vqe_params)

    print("VQE Circuit Generated:")
    print(f"Name: {vqe_circuit.name}")
    print(f"Qubits: {vqe_params['n']}")
    print(f"Ansatz: {vqe_params['ansatz']}")
    print(f"Reps: {vqe_params['reps']}")
    print(f"Parameters: {len(circuit_params)}")
    print(f"Metadata: {vqe_circuit.metadata}")
    print(vqe_circuit)
