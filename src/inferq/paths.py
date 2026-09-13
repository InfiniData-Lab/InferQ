"""Filesystem layout for InferQ.

This module is the single place a path is resolved, and :func:`ensure_dir` is the
only place the library creates a directory. Nothing here touches the filesystem at
import time.

Four roots, each overridable by an environment variable, each defaulting *outside*
the code tree so a checkout never accumulates generated files:

==========================  ============================  ==================================
Root                        Environment variable          Holds
==========================  ============================  ==================================
:func:`data_dir`            ``INFERQ_DATA_DIR``           fetched datasets, circuit stores
:func:`cache_dir`           ``INFERQ_CACHE_DIR``          re-derivable scratch, hash caches
:func:`state_dir`           ``INFERQ_STATE_DIR``          checkpoints, logs, resumable state
:func:`out_dir`             ``INFERQ_OUT_DIR``            experiment results and figures
==========================  ============================  ==================================

Inside a source checkout the defaults live under ``<repo>/var/``, which is ignored
wholesale. From an installed wheel there is no checkout to anchor to, so they fall
back to the XDG user directories.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "cache_dir",
    "circuit_layouts",
    "circuit_path",
    "circuits_dir",
    "data_dir",
    "dataset",
    "ensure_dir",
    "log_file",
    "out_dir",
    "repo_root",
    "resolve_manifest_entry",
    "state_dir",
]

#: Marker distinguishing the InferQ checkout from any other ancestor directory
#: that happens to contain a ``pyproject.toml``.
_PROJECT_NAMES = {"inferq", "inferq-workspace"}

_XDG_DEFAULTS = {
    "XDG_DATA_HOME": ".local/share",
    "XDG_CACHE_HOME": ".cache",
    "XDG_STATE_HOME": ".local/state",
}


def _is_inferq_project(pyproject: Path) -> bool:
    """Whether ``pyproject`` declares the InferQ project or its workspace root."""
    import tomllib

    try:
        with pyproject.open("rb") as handle:
            table = tomllib.load(handle)
    except (OSError, ValueError):
        return False
    name = table.get("project", {}).get("name")
    if name in _PROJECT_NAMES:
        return True
    # The workspace root may declare no [project] table of its own.
    return "workspace" in table.get("tool", {}).get("uv", {})


def repo_root(start: Path | str | None = None) -> Path | None:
    """Return the InferQ checkout containing ``start``, or ``None``.

    Walks upward looking for a ``pyproject.toml`` that actually belongs to InferQ,
    rather than assuming a fixed depth or a directory *name*. Returns ``None`` when
    running from an installed wheel, where there is no checkout — callers must treat
    that as the normal case and fall back to the user directories.
    """
    origin = Path(start) if start is not None else Path(__file__).resolve()
    if origin.is_file():
        origin = origin.parent
    for candidate in (origin, *origin.parents):
        pyproject = candidate / "pyproject.toml"
        if pyproject.is_file() and _is_inferq_project(pyproject):
            return candidate
    return None


def _xdg_home(variable: str) -> Path:
    configured = os.environ.get(variable)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / _XDG_DEFAULTS[variable]


def _root(env_var: str, checkout_subdir: str, xdg_variable: str) -> Path:
    """Resolve one root: explicit override, else checkout-local, else XDG."""
    configured = os.environ.get(env_var)
    if configured:
        return Path(configured).expanduser().resolve()
    checkout = repo_root()
    if checkout is not None:
        return checkout / "var" / checkout_subdir
    return _xdg_home(xdg_variable) / "inferq"


def data_dir() -> Path:
    """Root for fetched datasets and the local circuit store."""
    return _root("INFERQ_DATA_DIR", "data", "XDG_DATA_HOME")


def cache_dir() -> Path:
    """Root for re-derivable scratch: hash caches, unpack staging."""
    return _root("INFERQ_CACHE_DIR", "cache", "XDG_CACHE_HOME")


def state_dir() -> Path:
    """Root for resumable state: checkpoints and logs."""
    return _root("INFERQ_STATE_DIR", "state", "XDG_STATE_HOME")


def log_file(name: str) -> Path:
    """Path of a log file, with its directory created.

    Log files used to be written to the process's working directory, so where a
    run's log landed depended on where the operator happened to stand. They all
    live under ``state_dir()/logs`` now, which is the one root whose whole point
    is state that survives a run.
    """
    return ensure_dir(state_dir() / "logs") / name


def out_dir() -> Path:
    """Root for experiment results and figures."""
    configured = os.environ.get("INFERQ_OUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    checkout = repo_root()
    if checkout is not None:
        return checkout / "out"
    return Path.cwd() / "out"


def ensure_dir(path: Path | str) -> Path:
    """Create ``path`` (and parents) if missing and return it.

    The only directory creation in the library. Call it from the code that is about
    to write, never at import time: an import that mkdirs is what puts an empty
    ``logs/`` into a fresh clone.
    """
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def dataset(name: str) -> Path:
    """Directory a fetched dataset unpacks into. Not created."""
    return data_dir() / "datasets" / name


def circuits_dir() -> Path:
    """Root of the content-addressed local circuit store. Not created."""
    return data_dir() / "circuits"


def circuit_path(circuit_hash: str, root: Path | str | None = None) -> Path:
    """Directory holding the circuit identified by ``circuit_hash``.

    The store is content addressed, so this is a pure function of the hash: the same
    circuit resolves to the same directory no matter which run produced it.
    """
    _require_hash(circuit_hash)
    base = Path(root) if root is not None else circuits_dir()
    return base / circuit_hash


def circuit_layouts(circuit_hash: str, root: Path | str | None = None) -> list[Path]:
    """Every on-disk layout a circuit's QPY file is known to use, most specific first.

    Three layouts are in circulation and all three are legitimate: the canonical
    store writes ``<root>/<hash>/circuit.qpy``, while the experiment exporters write
    a sharded ``<root>/<hash[:2]>/<hash>.qpy`` or, for small exports, a flat
    ``<root>/<hash>.qpy``. Resolution tries them in order rather than assuming one.
    """
    _require_hash(circuit_hash)
    base = Path(root) if root is not None else circuits_dir()
    return [
        base / circuit_hash[:2] / f"{circuit_hash}.qpy",
        base / f"{circuit_hash}.qpy",
        base / circuit_hash / "circuit.qpy",
    ]


def resolve_manifest_entry(
    entry: dict,
    root: Path | str | None = None,
    *,
    key: str = "qpy_path",
    search: bool = True,
) -> Path:
    """Resolve a manifest row to a local path, re-deriving it from the row's hash.

    Manifests record the absolute ``qpy_path`` of the machine that produced them, so
    reading one literally is not portable: on any other machine that path points into
    a home directory which does not exist. When the row carries a hash the location
    is re-derived from the local store instead, trying each known layout in turn.

    With ``search=False`` the first candidate layout is returned without touching the
    filesystem, which is what a caller that is about to *write* the file wants. The
    recorded path is used verbatim only when the row carries no hash at all.
    """
    recorded = entry.get(key)
    circuit_hash = entry.get("hash") or entry.get("circuit_hash")

    if not circuit_hash:
        if not recorded:
            raise KeyError(f"manifest entry has neither {key!r} nor 'hash': {entry!r}")
        return Path(recorded)

    candidates = circuit_layouts(circuit_hash, root)
    if not search:
        return candidates[0]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if recorded and Path(recorded).exists():
        return Path(recorded)
    return candidates[0]


def _require_hash(circuit_hash: str) -> None:
    if not circuit_hash or not isinstance(circuit_hash, str):
        raise ValueError("circuit_hash must be a non-empty string")
