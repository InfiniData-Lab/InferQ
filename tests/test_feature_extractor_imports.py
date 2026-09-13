"""Every feature-extractor module must import on its own.

The package used to be circular: ``static_features`` star-imported the ``graphs``
subpackage, whose modules import ``static_features`` back. Importing anything in
the package first happened to work, so the whole suite passed while
``import inferq.features.static_features`` in a fresh interpreter raised. Only a
fresh process per module reproduces that, hence the subprocess.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Trees that hold importable first-party code, and the directory each one's
#: dotted names are relative to.
SOURCE_ROOTS = (REPO_ROOT / "src", REPO_ROOT / "experiments", REPO_ROOT / "tests")

MODULES = [
    "inferq.features",
    "inferq.features.extractors",
    "inferq.features.graph_features",
    "inferq.features.graphs",
    "inferq.features.graphs.dependency",
    "inferq.features.graphs.interaction",
    "inferq.features.sql_analyzer",
    "inferq.features.static_features",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports_first(module_name: str):
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_no_first_party_star_imports():
    """A star import from a sibling package is how the cycle got in."""
    offenders = []
    for root in SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            relative = path.relative_to(REPO_ROOT)
            if {"build", ".venv", "__pycache__"}.intersection(relative.parts):
                continue
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("from ") and stripped.endswith("import *"):
                    offenders.append(f"{relative}:{number}")

    assert not offenders, f"star imports hide dependency cycles: {offenders}"
