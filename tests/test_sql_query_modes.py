"""Golden tests for the IQS SQL lowering.

`docs/query-structures/<name>/` holds committed reference SQL for each generator:
the raw monolithic query plus the two lowered variants. Re-deriving the variants
from the monolithic query and comparing against those files pins the lowering to
output that has already been used in published experiments, so a refactor of
`inferq.sql.query_modes` cannot silently change query shape.

The fixtures cover all 17 generators. Before the restructure they lived beside
the generators as `*_queries/` directories and the glob here matched only the ten
that used the flat layout, so the four package-style algorithms' SQL went
untested. Regenerate the tree with `tools/gen_query_docs.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from inferq.sql.query_modes import (
    apply_sql_query_mode,
    count_iqs_ctes,
    iqs_cte_names,
    materialize_iqs_ctes,
    normalize_sql_query_mode,
    split_iqs_query_per_step,
    statement_block,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
QUERY_DIRS = sorted(p for p in (REPO_ROOT / "docs" / "query-structures").glob("*") if p.is_dir())


def _body(path: Path) -> str:
    """Read a reference .sql file, dropping its generated `--` header."""
    lines = path.read_text().splitlines()
    start = 0
    while start < len(lines) and (
        lines[start].startswith("--") or not lines[start].strip()
    ):
        start += 1
    return "\n".join(lines[start:]).strip()


def _ids(dirs: list[Path]) -> list[str]:
    return [d.name for d in dirs]


def test_reference_queries_exist():
    assert QUERY_DIRS, "no docs/query-structures/<name>/ fixtures found"


@pytest.mark.parametrize("query_dir", QUERY_DIRS, ids=_ids(QUERY_DIRS))
def test_materialized_matches_reference(query_dir: Path):
    monolithic = _body(query_dir / "monolithic.sql")
    expected = _body(query_dir / "monolithic_materialized.sql")
    produced = materialize_iqs_ctes(monolithic).rstrip("; \n")
    assert produced == expected.rstrip("; \n")


@pytest.mark.parametrize("query_dir", QUERY_DIRS, ids=_ids(QUERY_DIRS))
def test_split_matches_reference(query_dir: Path):
    monolithic = _body(query_dir / "monolithic.sql")
    expected = _body(query_dir / "split.sql")
    produced = statement_block(split_iqs_query_per_step(monolithic)).strip()
    assert produced == expected.rstrip("; \n") + ";"


@pytest.mark.parametrize("query_dir", QUERY_DIRS, ids=_ids(QUERY_DIRS))
def test_split_temp_false_emits_plain_tables(query_dir: Path):
    monolithic = _body(query_dir / "monolithic.sql")
    plain = split_iqs_query_per_step(monolithic, temp=False)
    temp = split_iqs_query_per_step(monolithic, temp=True)
    assert len(plain) == len(temp)
    assert not any(s.startswith("CREATE TEMP TABLE") for s in plain)
    assert all(s.startswith("CREATE TEMP TABLE") for s in temp[:-1])


@pytest.mark.parametrize("query_dir", QUERY_DIRS, ids=_ids(QUERY_DIRS))
def test_cte_counts_partition_the_names(query_dir: Path):
    monolithic = _body(query_dir / "monolithic.sql")
    names = iqs_cte_names(monolithic)
    counts = count_iqs_ctes(monolithic)
    assert names, "reference monolithic query has no CTEs"
    assert counts["num_k_ctes"] + counts["num_h_ctes"] == len(names)
    assert counts["num_k_ctes"] == sum(1 for n in names if n.startswith("K"))
    # One CREATE per K-step, plus the final SELECT.
    assert len(split_iqs_query_per_step(monolithic)) == counts["num_k_ctes"] + 1


@pytest.mark.parametrize("query_dir", QUERY_DIRS, ids=_ids(QUERY_DIRS))
def test_apply_sql_query_mode_dispatches(query_dir: Path):
    monolithic = _body(query_dir / "monolithic.sql")
    assert apply_sql_query_mode(monolithic, "monolithic") == monolithic
    assert apply_sql_query_mode(monolithic, "monolithic_materialized") == (
        materialize_iqs_ctes(monolithic)
    )
    assert apply_sql_query_mode(monolithic, "split") == split_iqs_query_per_step(monolithic)


def test_queries_without_with_pass_through():
    plain = "SELECT 1"
    assert materialize_iqs_ctes(plain) == plain
    assert split_iqs_query_per_step(plain) == [plain]
    assert count_iqs_ctes(plain) == {"num_k_ctes": 0, "num_h_ctes": 0}


def test_materialize_is_stable_under_reapplication():
    """The CTE regex accepts an existing MATERIALIZED hint, so this is a no-op."""
    query = "WITH H0 AS (SELECT 1 AS a), K1 AS (SELECT a FROM H0) SELECT * FROM K1"
    once = materialize_iqs_ctes(query)
    assert once == materialize_iqs_ctes(once)


@pytest.mark.parametrize(
    "given,expected",
    [
        (None, "monolithic"),
        ("Monolithic", "monolithic"),
        ("materialized", "monolithic_materialized"),
        ("monolithic-materialised", "monolithic_materialized"),
        (" SPLIT ", "split"),
    ],
)
def test_normalize_sql_query_mode(given, expected):
    assert normalize_sql_query_mode(given) == expected


def test_normalize_rejects_unknown_mode():
    with pytest.raises(ValueError, match="unknown SQL query mode"):
        normalize_sql_query_mode("hybrid")
