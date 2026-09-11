"""Every module in the repository must be importable.

This guards against the failure mode that static analysis misses and that only
surfaces when a script is finally run: a module that cannot be imported at all
because of a bare sibling import, a stale symbol, or a package-relative path
that was never exercised.

Third-party dependencies are deliberately not the subject of this test. A module
whose import fails only because an optional dependency is absent is skipped;
anything that fails for a reason internal to the repository is a failure.
"""

import importlib
import pkgutil
import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories that hold research scripts and generated data rather than
#: importable library code.
EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "analysis",
    "circuits",
    "data",
    "node_modules",
}

#: Top-level distributions that are optional at runtime. A module that fails to
#: import solely because one of these is missing is skipped, not failed.
OPTIONAL_DEPENDENCIES = {
    "ConfigSpace",
    "InfiniQuantumSim",
    "infiniquantumsim",
    "matplotlib",
    "mlos_core",
    "mqt",
    "pkg_resources",
    "psycopg2",
    "pyodbc",
    "seaborn",
    "sklearn",
    "supermarq",
    "tqdm",
    "xgboost",
}


def _module_names() -> list[str]:
    """Return the dotted name of every module in the repository."""
    names = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if EXCLUDED_DIRS.intersection(relative.parts):
            continue
        parts = list(relative.parts)
        if parts[-1] == "__init__.py":
            parts.pop()
            if not parts:
                continue
        else:
            parts[-1] = parts[-1].removesuffix(".py")
        # A directory whose name is not a valid identifier (e.g. environment-test)
        # cannot be addressed as a package.
        if not all(part.isidentifier() for part in parts):
            continue
        names.append(".".join(parts))
    return names


def _missing_optional_dependency(error: BaseException) -> str | None:
    """Return the optional distribution behind an import error, if any."""
    if not isinstance(error, ModuleNotFoundError) or not error.name:
        return None
    root = error.name.split(".")[0]
    return root if root in OPTIONAL_DEPENDENCIES else None


@pytest.fixture(scope="module", autouse=True)
def _repo_root_on_path():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


@pytest.mark.parametrize("module_name", _module_names())
def test_module_imports(module_name: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            importlib.import_module(module_name)
        except BaseException as error:  # noqa: BLE001 - report, don't propagate
            optional = _missing_optional_dependency(error)
            if optional is not None:
                pytest.skip(f"optional dependency {optional!r} is not installed")
            pytest.fail(f"{module_name} is not importable: {type(error).__name__}: {error}")


def test_every_package_directory_is_importable():
    """A directory with an __init__.py must resolve as a package."""
    failures = []
    for package_dir in sorted(REPO_ROOT.rglob("__init__.py")):
        relative = package_dir.parent.relative_to(REPO_ROOT)
        if not relative.parts or EXCLUDED_DIRS.intersection(relative.parts):
            continue
        if not all(part.isidentifier() for part in relative.parts):
            continue
        name = ".".join(relative.parts)
        if importlib.util.find_spec(name) is None:
            failures.append(name)
    assert not failures, f"packages not resolvable: {failures}"
