"""The dataset registry: what can be fetched, from where, and how it is verified.

The registry itself is ``data/datasets.toml``, which ships inside the wheel. It
is the authority on three things per dataset: an immutable upstream, an ordered
list of mirrors to try, and a sha256 plus size for every file a loader will read.

Verification is per file, not per archive. A dataset that only carried an
archive checksum could not tell a partially-unpacked tree from a complete one,
and the vendored copy this replaces recorded only an upstream commit SHA --
enough to say where the bytes came from, not enough to confirm they arrived.
"""

from __future__ import annotations

import hashlib
import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from inferq import paths

__all__ = [
    "DatasetSpec",
    "FileSpec",
    "VerificationResult",
    "available",
    "load_registry",
    "spec",
    "verify",
]

REGISTRY_PATH = Path(__file__).parent / "data" / "datasets.toml"

#: Read in this many bytes at a time when hashing. Large enough that the syscall
#: overhead disappears, small enough that an 81 MB file does not land in memory.
_HASH_CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class FileSpec:
    """One file in a dataset, addressed relative to the dataset root."""

    path: str
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    """Everything needed to fetch and verify one dataset."""

    key: str
    description: str
    homepage: str
    license: str
    upstream: str
    commit: str | None
    mirrors: tuple[str, ...]
    subdirs: tuple[str, ...]
    strip_components: int
    max_file_bytes: int | None
    files: tuple[FileSpec, ...]

    @property
    def root(self) -> Path:
        """Directory this dataset unpacks into. Not created."""
        return paths.dataset(self.key)

    @property
    def total_bytes(self) -> int:
        return sum(f.size for f in self.files)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of checking a dataset on disk against the registry."""

    key: str
    root: Path
    ok: tuple[str, ...]
    missing: tuple[str, ...]
    corrupt: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing and not self.corrupt

    def summary(self) -> str:
        parts = [f"{len(self.ok)} ok"]
        if self.missing:
            parts.append(f"{len(self.missing)} missing")
        if self.corrupt:
            parts.append(f"{len(self.corrupt)} corrupt")
        return ", ".join(parts)


@cache
def load_registry() -> dict[str, DatasetSpec]:
    """Parse ``datasets.toml`` into specs. Cached: the file ships read-only."""
    raw = tomllib.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    specs = {}
    for key, entry in raw.get("datasets", {}).items():
        files = tuple(
            FileSpec(path=path, sha256=meta["sha256"], size=int(meta["size"]))
            for path, meta in sorted(entry.get("files", {}).items())
        )
        specs[key] = DatasetSpec(
            key=key,
            description=entry.get("description", ""),
            homepage=entry.get("homepage", ""),
            license=entry.get("license", ""),
            upstream=entry["upstream"],
            commit=entry.get("commit"),
            mirrors=tuple(entry.get("mirrors", ())),
            subdirs=tuple(entry.get("subdirs", ())),
            strip_components=int(entry.get("strip_components", 0)),
            max_file_bytes=entry.get("max_file_bytes"),
            files=files,
        )
    return specs


def available() -> list[str]:
    """Registry keys, sorted."""
    return sorted(load_registry())


def spec(key: str) -> DatasetSpec:
    """Look up one dataset, with the valid keys in the error when it is missing."""
    registry = load_registry()
    try:
        return registry[key]
    except KeyError:
        raise KeyError(f"unknown dataset {key!r}; known: {', '.join(sorted(registry))}") from None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify(key: str, *, root: Path | None = None, quick: bool = False) -> VerificationResult:
    """Check every file of ``key`` on disk against the registry.

    ``quick`` compares sizes only. It catches a truncated download in a fraction
    of the time, and is the right default for a loader guarding its own input;
    a release check should hash.
    """
    dataset_spec = spec(key)
    base = Path(root) if root is not None else dataset_spec.root
    ok, missing, corrupt = [], [], []
    for file_spec in dataset_spec.files:
        target = base / file_spec.path
        if not target.is_file():
            missing.append(file_spec.path)
            continue
        if target.stat().st_size != file_spec.size:
            corrupt.append(file_spec.path)
            continue
        if not quick and sha256_of(target) != file_spec.sha256:
            corrupt.append(file_spec.path)
            continue
        ok.append(file_spec.path)
    return VerificationResult(
        key=key,
        root=base,
        ok=tuple(ok),
        missing=tuple(missing),
        corrupt=tuple(corrupt),
    )
