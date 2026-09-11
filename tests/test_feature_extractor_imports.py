"""Every feature-extractor module must import on its own.

The package used to be circular: ``static_features`` star-imported the
``graphs`` subpackage, whose modules import ``static_features`` back. Importing
anything in the package first happened to work, so the whole suite passed while
``import feature_extractors.static_features`` in a fresh interpreter raised.
Only a fresh process per module reproduces that, hence the subprocess.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

MODULES = [
    "feature_extractors.extractors",
    "feature_extractors.graph_features",
    "feature_extractors.graphs",
    "feature_extractors.graphs.dependency",
    "feature_extractors.graphs.interaction",
    "feature_extractors.sql_analyzer",
    "feature_extractors.static_features",
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
    for path in sorted(REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if {"analysis", "build", ".venv", "__pycache__"}.intersection(relative.parts):
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("from ") and stripped.endswith("import *"):
                offenders.append(f"{relative}:{number}")

    assert not offenders, f"star imports hide dependency cycles: {offenders}"
