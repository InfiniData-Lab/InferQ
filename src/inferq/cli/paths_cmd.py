"""``inferq paths`` — show the resolved filesystem layout.

Prints where the library will read and write, and which environment variable
overrides each root, so a misconfigured machine is one command away from being
diagnosed instead of being inferred from a stack trace.
"""

from __future__ import annotations

import argparse

from inferq import paths

_ROOTS: list[tuple[str, str, str]] = [
    ("data", "INFERQ_DATA_DIR", "fetched datasets and the local circuit store"),
    ("cache", "INFERQ_CACHE_DIR", "re-derivable scratch"),
    ("state", "INFERQ_STATE_DIR", "checkpoints and logs"),
    ("out", "INFERQ_OUT_DIR", "experiment results and figures"),
]

_RESOLVERS = {
    "data": paths.data_dir,
    "cache": paths.cache_dir,
    "state": paths.state_dir,
    "out": paths.out_dir,
    "circuits": paths.circuits_dir,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="inferq paths", description=__doc__)
    parser.add_argument(
        "--create",
        action="store_true",
        help="Create any of the four roots that do not exist yet",
    )
    parser.add_argument(
        "--print",
        dest="only",
        choices=sorted(_RESOLVERS),
        help="Print just this root, unlabelled, for use in a shell script",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.only is not None:
        resolved = _RESOLVERS[args.only]()
        if args.create:
            paths.ensure_dir(resolved)
        print(resolved)
        return 0

    checkout = paths.repo_root()
    print(f"repo root : {checkout if checkout else '(installed; no checkout)'}")
    print(f"circuits  : {paths.circuits_dir()}")
    print()

    width = max(len(name) for name, _, _ in _ROOTS)
    for name, env_var, description in _ROOTS:
        resolved = _RESOLVERS[name]()
        if args.create:
            paths.ensure_dir(resolved)
        marker = "" if resolved.exists() else "  (missing)"
        print(f"{name.ljust(width)} : {resolved}{marker}")
        print(f"{' '.ljust(width)}   ${env_var} — {description}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
