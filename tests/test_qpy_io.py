"""The shared QPY loader must accept every source the call sites hand it."""

from io import BytesIO

import pytest
import qiskit.qpy
from qiskit import QuantumCircuit

from inferq.storage.qpy import circuit_from_qpy_programs, load_circuit


def _bell() -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    return qc


def _payload(circuit: QuantumCircuit) -> bytes:
    buffer = BytesIO()
    qiskit.qpy.dump(circuit, buffer)
    return buffer.getvalue()


def test_loads_from_a_path(tmp_path):
    path = tmp_path / "circuit.qpy"
    path.write_bytes(_payload(_bell()))

    assert load_circuit(path).num_qubits == 2


def test_loads_from_a_path_string(tmp_path):
    path = tmp_path / "circuit.qpy"
    path.write_bytes(_payload(_bell()))

    assert load_circuit(str(path)).num_qubits == 2


def test_loads_from_raw_bytes():
    """Blob downloads arrive as bytes, never as a file on disk."""
    assert load_circuit(_payload(_bell())).num_qubits == 2


def test_loads_from_an_open_stream():
    assert load_circuit(BytesIO(_payload(_bell()))).num_qubits == 2


def test_accepts_a_bare_circuit():
    """Older payloads deserialize to a circuit rather than a list of them."""
    circuit = _bell()

    assert circuit_from_qpy_programs(circuit) is circuit


def test_empty_payload_is_an_error():
    with pytest.raises(ValueError):
        circuit_from_qpy_programs([])
