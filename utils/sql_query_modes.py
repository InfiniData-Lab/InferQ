"""SQL query mode helpers for InfiniQuantumSim-generated IQS queries.

An IQS query is a `WITH <tensor CTEs>, <K# contraction CTEs> SELECT ...`
cascade. The three modes here are what the out-of-core and fine-tuned RDBMS
experiments compare, and what `generators/generate_query_structure_docs.py`
emits as per-algorithm reference SQL:

  monolithic              the raw query, left to the engine's optimizer
  monolithic_materialized the same query with `AS MATERIALIZED` CTE hints
  split                   one CREATE TABLE per K-step plus the final SELECT

This module is the single home for that lowering. It has no dependency on the
experiment scripts, so both `generators/` and `scripts/` import from here.
"""

from __future__ import annotations

import re


VALID_SQL_QUERY_MODES = {"monolithic", "monolithic_materialized", "split"}

# `MATERIALIZED` is optional so an already-materialized query re-parses rather
# than silently falling through as if it had no CTEs at all.
_CTE_HEAD = re.compile(
    r"\s*(\w+)(\s*\([^)]*\))?\s+AS\s*(?:MATERIALIZED\s*)?\(", re.IGNORECASE
)

# A parsed CTE definition: its name, its optional column list, and its body.
CteDef = tuple[str, str, str]


def normalize_sql_query_mode(mode: str | None) -> str:
    """Return a canonical SQL query mode name."""
    if mode is None:
        return "monolithic"
    normalized = str(mode).strip().lower().replace("-", "_")
    aliases = {
        "materialized": "monolithic_materialized",
        "mono_materialized": "monolithic_materialized",
        "monolithic_materialised": "monolithic_materialized",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in VALID_SQL_QUERY_MODES:
        valid = ", ".join(sorted(VALID_SQL_QUERY_MODES))
        raise ValueError(f"unknown SQL query mode {mode!r}; expected one of: {valid}")
    return normalized


def parse_iqs_query(query: str) -> tuple[list[CteDef], str]:
    """Split a `WITH ... SELECT` query into its CTE definitions and final SELECT.

    Bodies are found by paren-balancing rather than by regex, because CTE bodies
    contain nested parentheses that no single regex can bracket correctly.
    Returns ``([], query)`` for a query with no leading WITH.
    """
    s = query.lstrip()
    if not s.upper().startswith("WITH "):
        return [], s
    s = s[5:]

    cte_defs: list[CteDef] = []
    pos = 0
    while True:
        match = _CTE_HEAD.match(s, pos)
        if not match:
            break
        name = match.group(1)
        cols = (match.group(2) or "").strip()
        body_start = match.end()
        depth = 1
        i = body_start
        while i < len(s) and depth > 0:
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
            i += 1
        cte_defs.append((name, cols, s[body_start:i - 1]))
        pos = i
        while pos < len(s) and s[pos] in " \t\n,":
            pos += 1
    return cte_defs, s[pos:].strip()


def iqs_cte_names(query: str) -> list[str]:
    """Names of the CTEs in an IQS query, in declaration order."""
    cte_defs, _ = parse_iqs_query(query)
    return [name for (name, _cols, _body) in cte_defs]


def count_iqs_ctes(query: str) -> dict[str, int]:
    """Count contraction vs tensor-literal CTEs in an IQS query.

    `K#` CTEs are intermediary contraction steps; the rest (`H#` and helpers)
    are tensor-literal CTEs. Returns zeros for a query without a leading WITH.
    """
    names = iqs_cte_names(query)
    num_k = sum(1 for name in names if name.startswith("K"))
    return {"num_k_ctes": num_k, "num_h_ctes": len(names) - num_k}


def split_iqs_query_per_step(query: str, *, temp: bool = True) -> list[str]:
    """Split an IQS query into step-by-step DDL, one table per contraction.

    Both SQLite and DuckDB inline this CTE cascade by default and try to plan it
    as one giant join, which blows up the heap regardless of the engine's spill
    knobs. Materializing each contraction step (`K#`) into its own table forces
    the engine to round-trip each intermediate through its storage layer,
    bounding peak RSS to roughly one step's hash-build.

    Tensor literal CTEs (anything not named `K#`) and any helper CTEs are
    re-emitted as a shared WITH-prefix on every statement; their contents are
    tiny VALUES clauses so duplicating them costs nothing.

    Pass ``temp=False`` to emit `CREATE TABLE` instead of `CREATE TEMP TABLE` —
    necessary for SQLite, where TEMP tables live in the temp schema whose
    backing is controlled by `PRAGMA temp_store`. If sqlite was compiled with
    `SQLITE_TEMP_STORE=2` (always memory) the PRAGMA is a no-op and temp tables
    stay in heap; a regular CREATE TABLE writes to the main disk-backed DB
    unconditionally.
    """
    cte_defs, final_select = parse_iqs_query(query)
    if not cte_defs:
        return [final_select]

    helper_defs = [(n, c, b) for (n, c, b) in cte_defs if not n.startswith("K")]
    k_defs = [(n, c, b) for (n, c, b) in cte_defs if n.startswith("K")]

    prefix = ""
    if helper_defs:
        prefix = "WITH " + ", ".join(f"{n}{c} AS ({b})" for (n, c, b) in helper_defs) + " "

    table_kind = "TEMP TABLE" if temp else "TABLE"
    statements = [f"CREATE {table_kind} {n} AS {prefix}{b}" for (n, _c, b) in k_defs]
    statements.append(f"{prefix}{final_select}")
    return statements


def materialize_iqs_ctes(query: str) -> str:
    """Keep one WITH query but force CTE materialization.

    This is the closest SQL-level knob for making the representative monolithic
    pipeline less prone to optimizer inlining. SQLite, DuckDB, and PostgreSQL
    12+ understand `AS MATERIALIZED`.
    """
    cte_defs, final_select = parse_iqs_query(query)
    if not cte_defs:
        return query
    return "WITH " + ", ".join(
        f"{n}{c} AS MATERIALIZED ({b})" for (n, c, b) in cte_defs
    ) + " " + final_select


def apply_sql_query_mode(query: str, mode: str, *, split_temp: bool = True) -> str | list[str]:
    """Apply a query mode to an IQS SQL query."""
    normalized = normalize_sql_query_mode(mode)
    if normalized == "monolithic":
        return query
    if normalized == "monolithic_materialized":
        return materialize_iqs_ctes(query)
    return split_iqs_query_per_step(query, temp=split_temp)


def statement_block(statements: list[str]) -> str:
    """Serialize a statement list as a semicolon-delimited SQL script."""
    return ";\n\n".join(statement.rstrip("; \n") for statement in statements) + ";\n"
