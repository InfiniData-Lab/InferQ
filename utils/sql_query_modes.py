"""SQL query mode helpers for InfiniQuantumSim-generated IQS queries."""

from __future__ import annotations

import re


VALID_SQL_QUERY_MODES = {"monolithic", "monolithic_materialized", "split"}

_CTE_HEAD = re.compile(r"\s*(\w+)(\s*\([^)]*\))?\s+AS\s*\(", re.IGNORECASE)


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


def split_iqs_query_per_step(query: str, *, temp: bool = True) -> list[str]:
    """Split an IQS `WITH H#... K#... SELECT` query into per-step DDL.

    Tensor/helper CTEs are repeated on every statement. Each `K*` contraction CTE
    becomes one materialized table, followed by the final SELECT.
    """
    s = query.lstrip()
    if not s.upper().startswith("WITH "):
        return [s]
    s = s[5:]

    cte_defs: list[tuple[str, str, str]] = []
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
    final_select = s[pos:].strip()

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
    """Keep one IQS query but force CTE materialization."""
    s = query.lstrip()
    if not s.upper().startswith("WITH "):
        return query
    s = s[5:]

    cte_defs: list[tuple[str, str, str]] = []
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

    if not cte_defs:
        return query
    final_select = s[pos:].strip()
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
