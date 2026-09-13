"""Structural guards that keep the repository from drifting back.

Every check here corresponds to a problem this repository actually had. They are
cheap, they run without network access, and each one fails with the specific
thing that regressed rather than with a diff.

Run it directly (``uv run python tools/check_repo_hygiene.py``) or let CI do it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A tracked file larger than this is almost certainly data that belongs in the
#: external store. ``uv.lock`` is the largest legitimate file at ~0.5 MB.
MAX_TRACKED_BYTES = 1_000_000

#: Extensions that must never appear inside the built wheel. Curated CSV
#: inventories are deliberate package data and are not on this list.
FORBIDDEN_WHEEL_SUFFIXES = {".parquet", ".qasm", ".qpy", ".pdf", ".png", ".jsonl"}

#: The wheel is source plus a registry and two small CSVs. Anything approaching
#: this size means data crept back in.
MAX_WHEEL_BYTES = 2_000_000

#: Inside the distribution, only ``inferq.paths`` may derive a location from the
#: source file's own position. Tests and the ``experiments`` workspace member are
#: outside that rule: neither is installed, so each has to anchor itself. Nothing
#: anywhere may hard-code the checkout's directory name -- that breaks the moment
#: someone clones into a differently named folder.
SELF_ANCHOR_NEEDLE = "parents["
CHECKOUT_NAME_NEEDLES = ('/ "InferQ"', "/ 'InferQ'")
SELF_ANCHOR_EXEMPT = {Path("src/inferq/paths.py")}


def _git(*args: str) -> list[str]:
    output = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [line for line in output.splitlines() if line]


def check_no_tracked_but_ignored() -> list[str]:
    """A file that is both tracked and ignored means the ignore rules are lying."""
    offenders = _git("ls-files", "-i", "-c", "--exclude-standard")
    return [f"tracked but ignored: {path}" for path in offenders]


def check_no_gitignore_negations() -> list[str]:
    """Negations are the symptom of data and code sharing a directory."""
    text = (REPO_ROOT / ".gitignore").read_text()
    return [
        f".gitignore negation on line {number}: {line}"
        for number, line in enumerate(text.splitlines(), start=1)
        if line.startswith("!")
    ]


def check_no_large_tracked_files() -> list[str]:
    failures = []
    for path in _git("ls-files"):
        full = REPO_ROOT / path
        if not full.is_file():
            continue
        size = full.stat().st_size
        if size > MAX_TRACKED_BYTES:
            failures.append(f"tracked file over {MAX_TRACKED_BYTES} bytes: {path} ({size})")
    return failures


def check_notebook_outputs_are_empty() -> list[str]:
    """Notebook outputs are base64 images; in git they never stop growing."""
    failures = []
    for path in _git("ls-files", "*.ipynb"):
        document = json.loads((REPO_ROOT / path).read_text())
        for index, cell in enumerate(document.get("cells", [])):
            if cell.get("outputs"):
                failures.append(f"notebook has stored outputs: {path} cell {index}")
    return failures


def check_no_path_hacks() -> list[str]:
    failures = []
    for path in _git("ls-files", "*.py"):
        relative = Path(path)
        if relative == Path(__file__).relative_to(REPO_ROOT):
            continue
        text = (REPO_ROOT / path).read_text()
        in_distribution = relative.parts[0] == "src"
        if (
            in_distribution
            and relative not in SELF_ANCHOR_EXEMPT
            and SELF_ANCHOR_NEEDLE in text
        ):
            failures.append(f"path resolution outside inferq.paths: {path}")
        for needle in CHECKOUT_NAME_NEEDLES:
            if needle in text:
                failures.append(f"hard-coded checkout directory name: {path} contains {needle!r}")
    return failures


def check_wheel(wheel: Path) -> list[str]:
    failures = []
    size = wheel.stat().st_size
    if size > MAX_WHEEL_BYTES:
        failures.append(f"wheel is {size} bytes, over the {MAX_WHEEL_BYTES} byte budget")
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if Path(name).suffix.lower() in FORBIDDEN_WHEEL_SUFFIXES:
                failures.append(f"wheel contains data file: {name}")
            if name.startswith("experiments/") or name.startswith("tools/"):
                failures.append(f"wheel contains non-library code: {name}")
    return failures


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    failures: list[str] = []
    failures += check_no_tracked_but_ignored()
    failures += check_no_gitignore_negations()
    failures += check_no_large_tracked_files()
    failures += check_notebook_outputs_are_empty()
    failures += check_no_path_hacks()

    for argument in argv:
        failures += check_wheel(Path(argument))

    if failures:
        print("repository hygiene checks failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print("repository hygiene checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
