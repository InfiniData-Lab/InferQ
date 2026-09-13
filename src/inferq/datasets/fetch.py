"""Download, unpack and verify the datasets named in the registry.

Downloads go through :mod:`urllib` rather than ``requests`` so that fetching a
dataset never drags a third-party HTTP stack into the base install. Mirrors are
tried in the order the registry lists them, and the result is always verified
against the per-file checksums before it is moved into place: a fetch either
leaves a complete, checked tree or leaves nothing.
"""

from __future__ import annotations

import logging
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from inferq import paths

from .registry import DatasetSpec, VerificationResult, spec, verify

__all__ = ["FetchError", "fetch"]

logger = logging.getLogger(__name__)

#: Refuse to unpack an archive member whose resolved path escapes the target
#: directory. Python 3.12 gained `filter="data"` for this; state it explicitly
#: so the behaviour does not depend on the interpreter's default changing.
_TAR_FILTER = "data"


class FetchError(RuntimeError):
    """Every mirror failed, or what arrived did not match the registry."""


def _download(url: str, target: Path) -> None:
    logger.info("downloading %s", url)
    with urllib.request.urlopen(url) as response, target.open("wb") as handle:  # noqa: S310
        shutil.copyfileobj(response, handle)


def _unpack(archive: Path, target: Path, dataset_spec: DatasetSpec) -> None:
    """Extract the wanted subdirectories, stripping the archive's top-level dir."""
    paths.ensure_dir(target)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts[dataset_spec.strip_components :]
            if not parts:
                continue
            if dataset_spec.subdirs and parts[0] not in dataset_spec.subdirs:
                continue
            member.name = str(Path(*parts))
            tar.extract(member, target, filter=_TAR_FILTER)


def _report(result: VerificationResult) -> str:
    lines = [f"{result.key}: {result.summary()}"]
    for path in list(result.missing)[:5]:
        lines.append(f"  missing {path}")
    for path in list(result.corrupt)[:5]:
        lines.append(f"  corrupt {path}")
    extra = len(result.missing) + len(result.corrupt) - 10
    if extra > 0:
        lines.append(f"  ... and {extra} more")
    return "\n".join(lines)


def fetch(key: str, *, force: bool = False, quick: bool = False) -> Path:
    """Ensure dataset ``key`` is present and verified; return its root.

    A dataset that already verifies is left alone, so this is safe to call from a
    loader on every run. ``force`` re-downloads even then.
    """
    dataset_spec = spec(key)
    root = dataset_spec.root

    if not force:
        existing = verify(key, quick=quick)
        if existing.complete:
            logger.debug("%s already complete at %s", key, root)
            return root

    if not dataset_spec.mirrors:
        raise FetchError(f"{key}: registry lists no mirrors to fetch from")

    failures = []
    with tempfile.TemporaryDirectory(prefix=f"inferq-{key}-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "archive.tar.gz"
        staged = tmp_path / "staged"
        for url in dataset_spec.mirrors:
            try:
                _download(url, archive)
                _unpack(archive, staged, dataset_spec)
            except (urllib.error.URLError, OSError, tarfile.TarError) as exc:
                failures.append(f"{url}: {type(exc).__name__}: {exc}")
                shutil.rmtree(staged, ignore_errors=True)
                continue

            result = verify(key, root=staged, quick=quick)
            if not result.complete:
                failures.append(f"{url}: verification failed\n{_report(result)}")
                shutil.rmtree(staged, ignore_errors=True)
                continue

            # Only now is the old copy touched: a failed fetch must never leave
            # the previous dataset worse off than it found it.
            if root.exists():
                shutil.rmtree(root)
            paths.ensure_dir(root.parent)
            shutil.move(str(staged), str(root))
            logger.info("%s fetched to %s (%s)", key, root, result.summary())
            return root

    raise FetchError(f"{key}: every mirror failed\n" + "\n".join(failures))
