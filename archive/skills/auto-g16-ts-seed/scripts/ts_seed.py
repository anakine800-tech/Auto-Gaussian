#!/usr/bin/env python3
"""CLI for non-executable Auto-G16 TS seed artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

import ts_seed_core as core


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Build and validate hash-bound, non-executable TS seed artifacts.")
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("build-candidate", "build-portfolio"):
        command = sub.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--output", required=True, type=Path)
    validate = sub.add_parser("validate")
    validate.add_argument("artifact", type=Path)
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "build-candidate":
            core.require(args.output.resolve().parent == args.source.resolve().parent, "output must stay beside its package-relative source")
            output = core.build_candidate(core.load_json(args.source), args.source)
            core.write_new_json(args.output, output)
        elif args.command == "build-portfolio":
            core.require(args.output.resolve().parent == args.source.resolve().parent, "output must stay beside its package-relative source")
            output = core.build_portfolio(core.load_json(args.source), args.source)
            core.write_new_json(args.output, output)
        else:
            document = core.load_json(args.artifact)
            if document.get("schema") == core.CANDIDATE_SCHEMA:
                core.validate_candidate(document, args.artifact)
            elif document.get("schema") == core.PORTFOLIO_SCHEMA:
                core.validate_portfolio(document, args.artifact)
            else:
                raise core.ContractError("unsupported TS seed schema")
    except core.ContractError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
