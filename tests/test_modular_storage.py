"""Tests for the local storage layer and Azure Table name sanitisation.

These run fully offline. Azure connectivity is exercised by the manual probe in
``src/inferq/transfer/test_cloud_connection.py``, not here.
"""

import tempfile
import unittest
from pathlib import Path

from qiskit import QuantumCircuit

from inferq.remote import table_safe
from inferq.storage.local import get_circuit_info, save_circuit_locally


def _bell_circuit() -> QuantumCircuit:
    qc = QuantumCircuit(3, 3)
    qc.h(0)
    qc.cx(0, 1)
    qc.cx(1, 2)
    qc.measure_all()
    return qc


class TestLocalStorage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_circuit_locally_writes_and_reports_hash(self):
        qc = _bell_circuit()
        features = {"num_qubits": qc.num_qubits, "circuit_depth": qc.depth()}

        circuit_hash, saved_features, written = save_circuit_locally(
            qc, features, self.out_root
        )

        self.assertTrue(written)
        self.assertTrue(circuit_hash)
        self.assertTrue((self.out_root / circuit_hash).is_dir())
        self.assertEqual(saved_features["num_qubits"], qc.num_qubits)

    def test_saving_the_same_circuit_twice_is_not_rewritten(self):
        qc = _bell_circuit()
        features = {"num_qubits": qc.num_qubits}

        first_hash, _, first_written = save_circuit_locally(qc, features, self.out_root)
        second_hash, _, second_written = save_circuit_locally(qc, features, self.out_root)

        self.assertEqual(first_hash, second_hash)
        self.assertTrue(first_written)
        self.assertFalse(second_written)

    def test_get_circuit_info_reports_serialization_method(self):
        qc = _bell_circuit()
        circuit_hash, _, _ = save_circuit_locally(qc, {}, self.out_root)

        info = get_circuit_info(self.out_root / circuit_hash)

        self.assertIn("serialization_method", info)


class TestTableSafe(unittest.TestCase):
    def test_invalid_characters_become_underscores(self):
        self.assertEqual(table_safe("gate-count (total)"), "gate_count__total_")

    def test_leading_digit_is_prefixed(self):
        self.assertEqual(table_safe("2q_gates"), "prop_2q_gates")

    def test_result_is_lowercased_and_stripped(self):
        self.assertEqual(table_safe("  NumQubits  "), "numqubits")


if __name__ == "__main__":
    unittest.main()
