"""The ``inferq`` console script.

One entry point replaces the ``python <path>`` invocations the repository used to
rely on. Sub-commands are dispatched by name to the module that owns them and the
module is imported only once its command is selected, so ``inferq --help`` does not
pay for Qiskit, Aer or a cloud SDK.
"""

from __future__ import annotations

import sys
from importlib import import_module

# command -> (module, attribute, takes an explicit argv list)
_COMMANDS: dict[str, tuple[str, str, bool]] = {
    "run": ("inferq.cli.run", "main", True),
    "smoke": ("inferq.cli.smoke", "main", True),
    "ingest": ("inferq.cli.ingest", "main", True),
    "rerun": ("inferq.rerun.rerun_cli", "main", True),
    "download": ("inferq.transfer.download_circuits", "main", True),
    "upload": ("inferq.transfer.upload_circuits", "main", False),
    "catalog": ("inferq.transfer.list_circuits", "main", False),
    "paths": ("inferq.cli.paths_cmd", "main", True),
    "data": ("inferq.cli.data_cmd", "main", True),
}

_SUMMARY = {
    "run": "generate, simulate and store circuits",
    "smoke": "end-to-end check of the local install",
    "ingest": "ingest circuits from an external benchmark suite",
    "rerun": "reprocess stored circuits (simulations, SQL or dynamic features)",
    "download": "download circuits from cloud object storage",
    "upload": "upload local circuits to cloud object storage",
    "catalog": "list circuits recorded in the cloud metadata store",
    "paths": "show the resolved data, cache, state and output directories",
    "data": "list, fetch and verify the registered benchmark datasets",
}


def _usage() -> str:
    width = max(len(name) for name in _COMMANDS)
    lines = [
        "usage: inferq <command> [args...]",
        "",
        "commands:",
        *(f"  {name.ljust(width)}  {_SUMMARY[name]}" for name in sorted(_COMMANDS)),
        "",
        "Run `inferq <command> --help` for a command's own options.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(_usage())
        return 0

    command, rest = argv[0], argv[1:]
    target = _COMMANDS.get(command)
    if target is None:
        print(f"inferq: unknown command {command!r}\n", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2

    module_name, attribute, takes_argv = target
    entry = getattr(import_module(module_name), attribute)

    if takes_argv:
        result = entry(rest)
    else:
        # Sub-commands that still read sys.argv directly; give them a prog name
        # that matches how the user invoked them.
        saved = sys.argv
        sys.argv = [f"inferq {command}", *rest]
        try:
            result = entry()
        finally:
            sys.argv = saved

    return 0 if result is None else int(result)


__all__ = ["main"]
