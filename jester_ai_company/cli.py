"""Command Line Interface for Jester AI Company.

Provides CLI entrypoints for inspecting company operational state,
agent inventory, and capabilities in both human-readable and JSON formats.
"""

import argparse
import json
from pathlib import Path
import sys
from typing import List, Optional

from .status import format_status_console, get_company_status


def build_parser() -> argparse.ArgumentParser:
    """Build root CLI argument parser with subcommands and flags."""
    common_options = argparse.ArgumentParser(add_help=False)
    common_options.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON to stdout instead of human-formatted console output.",
    )
    common_options.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional path to repository root (defaults to script's parent repository).",
    )
    common_options.add_argument(
        "--compact",
        action="store_true",
        help="When --json is enabled, output compact single-line JSON instead of indented formatting.",
    )

    parser = argparse.ArgumentParser(
        prog="jester_ai_company",
        description="Jester AI Company Management CLI: Inspect company operational state and agents.",
        parents=[common_options],
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # 'status' subcommand
    subparsers.add_parser(
        "status",
        parents=[common_options],
        help="Inspect company operational status, agent inventory, and roles & responsibilities.",
    )

    return parser


def run_status_command(repo_root: Optional[Path], as_json: bool, compact: bool) -> int:
    """Execute status inspection and write formatted output to stdout."""
    try:
        status_data = get_company_status(repo_root=repo_root)

        if as_json:
            indent = None if compact else 2
            json_output = json.dumps(status_data, indent=indent)
            sys.stdout.write(json_output + "\n")
            sys.stdout.flush()
        else:
            console_output = format_status_console(status_data)
            sys.stdout.write(console_output + "\n")
            sys.stdout.flush()

        return 0
    except Exception as exc:
        print(f"Error: status inspection failed: {exc}", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    # If no command or 'status' subcommand is passed, run status
    if args.command is None or args.command == "status":
        return run_status_command(
            repo_root=args.repo_root,
            as_json=args.json,
            compact=args.compact,
        )

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
