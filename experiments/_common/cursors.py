"""Result-set helpers shared by the benchmark runners."""


def drain_cursor(cursor, *, chunk_size: int = 8192) -> int:
    """Consume a result set without retaining all rows in Python memory.

    Benchmarks care about the row count and the time the engine takes to
    produce it, never about the rows themselves, so fetching in chunks keeps
    the measurement from being dominated by Python-side materialization.
    """
    n_rows = 0
    while True:
        rows = cursor.fetchmany(chunk_size)
        if not rows:
            return n_rows
        n_rows += len(rows)
