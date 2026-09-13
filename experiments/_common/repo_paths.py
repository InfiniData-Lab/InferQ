"""Filesystem anchors for the experiment entry points.

The RDBMS runners execute against two sibling checkouts, ``InferQ`` and
``Infinidata-rdbms-simulator``, and need the directory that holds both of them
so they can put each one on ``sys.path``.
"""
from __future__ import annotations

from pathlib import Path

WORKSPACE_CHECKOUTS = ("InferQ", "Infinidata-rdbms-simulator")

_LIB_DIR = Path(__file__).resolve().parent
INFERQ_ROOT = _LIB_DIR.parents[1]


def repo_root(start: Path | None = None) -> Path:
    """Return the workspace directory that holds the sibling checkouts.

    Args:
        start: Path to walk upwards from. Defaults to this module's location,
            so the answer never depends on the current working directory.

    Returns:
        The first ancestor of ``start`` containing every entry in
        ``WORKSPACE_CHECKOUTS``. When the sibling simulator checkout is absent
        — a single-repo clone, or a module imported purely for inspection —
        the InferQ checkout's own parent is returned rather than raising, so
        importing a runner is always safe even where it cannot run.
    """
    origin = Path(start).resolve() if start is not None else _LIB_DIR
    for parent in (origin, *origin.parents):
        if all((parent / name).is_dir() for name in WORKSPACE_CHECKOUTS):
            return parent
    return INFERQ_ROOT.parent
