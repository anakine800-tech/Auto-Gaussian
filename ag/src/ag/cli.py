"""CLI skeleton with registration points for the redesign tasks."""

import argparse
from importlib import import_module

from ag import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ag")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")
    for name in ("facts", "thermo", "dedup", "cluster", "graph"):
        module_name = f"ag.{name}"
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name != module_name:
                raise
            continue
        module.register(subparsers)
    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
