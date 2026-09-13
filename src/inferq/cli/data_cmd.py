"""``inferq data`` -- fetch, verify and inspect the registered datasets.

Three sub-commands, all driven by ``inferq/datasets/data/datasets.toml``:

``list``    what the registry knows about, and whether it is on disk
``fetch``   download, verify and unpack into ``$INFERQ_DATA_DIR``
``verify``  re-hash what is on disk against the recorded checksums
"""

from __future__ import annotations

import argparse
import logging

from inferq.datasets import registry


def _human(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _keys(requested: list[str], all_datasets: bool) -> list[str]:
    if all_datasets or not requested:
        return registry.available()
    return requested


def _cmd_list(args: argparse.Namespace) -> int:
    for key in registry.available():
        dataset_spec = registry.spec(key)
        result = registry.verify(key, quick=True)
        state = "complete" if result.complete else result.summary()
        print(f"{key}  [{state}]")
        print(f"  {dataset_spec.description}")
        print(f"  {len(dataset_spec.files)} files, {_human(dataset_spec.total_bytes)}")
        print(f"  root: {dataset_spec.root}")
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    from inferq.datasets.fetch import FetchError, fetch

    status = 0
    for key in _keys(args.keys, args.all):
        try:
            root = fetch(key, force=args.force, quick=args.quick)
        except (FetchError, KeyError) as exc:
            print(f"inferq data fetch: {exc}")
            status = 1
            continue
        print(f"{key}: ready at {root}")
    return status


def _cmd_verify(args: argparse.Namespace) -> int:
    status = 0
    for key in _keys(args.keys, args.all):
        try:
            result = registry.verify(key, quick=args.quick)
        except KeyError as exc:
            print(f"inferq data verify: {exc}")
            status = 1
            continue
        print(f"{key}: {result.summary()}  ({result.root})")
        for path in list(result.missing)[:10]:
            print(f"  missing {path}")
        for path in list(result.corrupt)[:10]:
            print(f"  corrupt {path}")
        if not result.complete:
            status = 1
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inferq data", description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="show every registered dataset and its state").set_defaults(
        func=_cmd_list
    )

    fetch_parser = sub.add_parser("fetch", help="download and verify a dataset")
    fetch_parser.add_argument("keys", nargs="*", help="dataset keys; default is all of them")
    fetch_parser.add_argument("--all", action="store_true", help="fetch every registered dataset")
    fetch_parser.add_argument(
        "--force", action="store_true", help="re-download even if the dataset already verifies"
    )
    fetch_parser.add_argument(
        "--quick", action="store_true", help="check sizes instead of hashing"
    )
    fetch_parser.set_defaults(func=_cmd_fetch)

    verify_parser = sub.add_parser("verify", help="re-check a dataset against its checksums")
    verify_parser.add_argument("keys", nargs="*", help="dataset keys; default is all of them")
    verify_parser.add_argument("--all", action="store_true", help="verify every dataset")
    verify_parser.add_argument(
        "--quick", action="store_true", help="check sizes instead of hashing"
    )
    verify_parser.set_defaults(func=_cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
