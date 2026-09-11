"""Tests for running a lowered query against an in-process SQL engine.

The `split` query mode hands the engine a sequence of statements -- table
definitions followed by the select that reads the contraction out -- rather than
one self-contained query. Only the last of those produces rows, so the runner
has to tell "this statement returned nothing" apart from "this statement timed
out", which is what a `None` means everywhere else in this path.
"""

from __future__ import annotations

import unittest

from simulators.lib.infiniquantum import _execute_statement_sequence

SPLIT_STATEMENTS = [
    "CREATE TABLE a AS SELECT 1 AS i, 2.0 AS v",
    "CREATE TABLE b AS SELECT 1 AS i, 3.0 AS v",
    "SELECT a.i, a.v * b.v AS v FROM a JOIN b ON a.i = b.i",
]


class TestStatementSequence(unittest.TestCase):
    def test_duckdb_returns_the_rows_of_the_final_select(self):
        result = _execute_statement_sequence("ducksql", SPLIT_STATEMENTS, timeout=30)

        self.assertEqual(result, [(1, 6.0)])

    def test_duckdb_runs_a_single_statement_query_unchanged(self):
        result = _execute_statement_sequence("ducksql", ["SELECT 1"], timeout=30)

        self.assertEqual(result, [(1,)])

    def test_an_unknown_engine_is_rejected(self):
        with self.assertRaises(ValueError):
            _execute_statement_sequence("oracle", ["SELECT 1"], timeout=30)


if __name__ == "__main__":
    unittest.main()
