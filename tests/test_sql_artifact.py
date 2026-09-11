"""Tests for the lowered-SQL artifact the pipeline writes next to each circuit.

The InfiniQuantumSim simulation path produces a SQL query for every circuit it
handles. These cover recovering that query from a set of simulation results and
storing it as ``circuit.sql`` alongside the serialized circuit.
"""

import json
import tempfile
import unittest
from pathlib import Path

from qiskit import QuantumCircuit

from simulators import sql_artifact_from_results
from utils.local_storage import save_circuit_locally


def _bell_circuit() -> QuantumCircuit:
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    return qc


class TestSqlArtifactFromResults(unittest.TestCase):
    def test_returns_query_and_mode_from_the_simulation_that_produced_them(self):
        results = {
            "statevector": {"success": True, "execution_time": 0.1},
            "infiniquantum": {
                "success": True,
                "sql_query": "SELECT 1",
                "sql_query_mode": "monolithic",
            },
        }

        self.assertEqual(sql_artifact_from_results(results), ("SELECT 1", "monolithic"))

    def test_ignores_a_failed_simulation_that_still_carries_a_query(self):
        results = {
            "infiniquantum": {
                "success": False,
                "sql_query": "SELECT 1",
                "sql_query_mode": "split",
            }
        }

        self.assertEqual(sql_artifact_from_results(results), (None, None))

    def test_reports_nothing_when_no_simulation_lowered_the_circuit(self):
        results = {"statevector": {"success": True, "execution_time": 0.1}}

        self.assertEqual(sql_artifact_from_results(results), (None, None))


class TestSqlArtifactStorage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_query_is_written_beside_the_circuit_and_the_mode_recorded(self):
        query = "WITH t AS (SELECT 1) SELECT * FROM t"

        circuit_hash, _, _ = save_circuit_locally(
            _bell_circuit(),
            {},
            self.out_root,
            sql_query=query,
            sql_query_mode="monolithic_materialized",
        )

        circuit_dir = self.out_root / circuit_hash
        self.assertEqual((circuit_dir / "circuit.sql").read_text(), query)
        meta = json.loads((circuit_dir / "meta.json").read_text())
        self.assertEqual(meta["sql_query_mode"], "monolithic_materialized")

    def test_no_file_is_written_when_the_circuit_was_never_lowered(self):
        circuit_hash, _, _ = save_circuit_locally(_bell_circuit(), {}, self.out_root)

        circuit_dir = self.out_root / circuit_hash
        self.assertFalse((circuit_dir / "circuit.sql").exists())
        meta = json.loads((circuit_dir / "meta.json").read_text())
        self.assertIsNone(meta["sql_query_mode"])


if __name__ == "__main__":
    unittest.main()
