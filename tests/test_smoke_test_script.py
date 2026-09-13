"""Tests for the environment smoke test's reporting logic.

The script's value is its verdict: which engines take part in a run, and whether
a circuit directory holds every artifact it should. Both are checked here
without running the pipeline.
"""

import json
import tempfile
import unittest
from pathlib import Path

from inferq.cli.smoke import EngineStatus, omit_methods_for, verify_circuit_dir


def _engine(name: str, available: bool) -> EngineStatus:
    return EngineStatus(name, name.upper(), available, "")


class TestOmitMethods(unittest.TestCase):
    def test_unreachable_engines_are_omitted_and_reachable_ones_kept(self):
        engines = [
            _engine("sqlite", True),
            _engine("ducksql", True),
            _engine("psql", False),
            _engine("umbra", False),
        ]

        self.assertEqual(omit_methods_for(engines), ["psql", "umbra"])

    def test_nothing_is_omitted_when_every_engine_answers(self):
        self.assertEqual(omit_methods_for([_engine("sqlite", True)]), [])


class TestVerifyCircuitDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _circuit_dir(self, name: str = "a" * 64, **meta_overrides) -> Path:
        circuit_dir = self.root / name
        circuit_dir.mkdir()
        (circuit_dir / "circuit.qpy").write_bytes(b"qpy")
        meta = {"qpy_sha256": name, "circuit_qubits": 3, "statevector_execution_time": 0.1}
        meta.update(meta_overrides)
        (circuit_dir / "meta.json").write_text(json.dumps(meta))
        return circuit_dir

    def _statuses(self, rows):
        return {artifact: status for status, artifact, _ in rows}

    def test_a_complete_directory_passes(self):
        circuit_dir = self._circuit_dir(sql_query_mode="monolithic")
        (circuit_dir / "circuit.sql").write_text("SELECT 1")

        statuses = self._statuses(verify_circuit_dir(circuit_dir, expect_sql=True))

        self.assertEqual(statuses, {"circuit.qpy": "PASS", "meta.json": "PASS", "circuit.sql": "PASS"})

    def test_missing_sql_fails_when_the_circuit_was_simulated_for_it(self):
        circuit_dir = self._circuit_dir(infiniquantum_execution_time=0.4)

        statuses = self._statuses(verify_circuit_dir(circuit_dir, expect_sql=True))

        self.assertEqual(statuses["circuit.sql"], "FAIL")

    def test_missing_sql_is_skipped_when_the_circuit_was_never_lowered(self):
        circuit_dir = self._circuit_dir(infiniquantum_execution_time=None)

        installed = self._statuses(verify_circuit_dir(circuit_dir, expect_sql=True))
        absent = self._statuses(verify_circuit_dir(circuit_dir, expect_sql=False))

        self.assertEqual(installed["circuit.sql"], "SKIP")
        self.assertEqual(absent["circuit.sql"], "SKIP")

    def test_a_hash_that_disagrees_with_the_directory_name_fails(self):
        circuit_dir = self._circuit_dir(qpy_sha256="not-the-directory-name")

        statuses = self._statuses(verify_circuit_dir(circuit_dir, expect_sql=False))

        self.assertEqual(statuses["meta.json"], "FAIL")

    def test_a_directory_with_no_serialized_circuit_fails(self):
        circuit_dir = self._circuit_dir()
        (circuit_dir / "circuit.qpy").unlink()

        statuses = self._statuses(verify_circuit_dir(circuit_dir, expect_sql=False))

        self.assertEqual(statuses["circuit.qpy"], "FAIL")


if __name__ == "__main__":
    unittest.main()
