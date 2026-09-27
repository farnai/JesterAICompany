#!/usr/bin/env python3
"""Company Version Tool.

CLI utility to inspect Jester AI Company version metadata and output company
identity, version, and registered agent count in machine-readable JSON format.

Adheres strictly to Jester AI Company core operating principles:
- Practical over complex
- Zero external dependencies
- Pure stdout JSON contract (diagnostics/errors to stderr)
- Location-agnostic execution
"""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure repository root and script directory are in sys.path for robust imports
CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

VERSION = "0.1.0"
DEFAULT_COMPANY_NAME = "Jester AI Company"

try:
    from tools.company_info import (
        DEFAULT_COMPANY_NAME,
        get_company_info,
        get_repo_root,
    )
except ImportError:
    try:
        from company_info import (  # type: ignore
            DEFAULT_COMPANY_NAME,
            get_company_info,
            get_repo_root,
        )
    except ImportError:
        def get_repo_root(custom_path: Optional[Path] = None) -> Path:
            """Resolve repository root directory."""
            if custom_path is not None:
                return custom_path.resolve()
            return Path(__file__).resolve().parent.parent

        def get_company_info(repo_root: Optional[Path] = None) -> Dict[str, Any]:
            """Fallback company info generator."""
            return {
                "company_name": DEFAULT_COMPANY_NAME,
            }


def count_registered_agents(repo_root: Optional[Path] = None) -> int:
    """Scan the .agents/agents/ directory structure for agent.md definitions.

    A registered agent is identified by a subdirectory in .agents/agents/
    containing an agent.md definition file.
    """
    root = get_repo_root(repo_root)
    agents_dir = root / ".agents" / "agents"
    if not agents_dir.is_dir():
        return 0

    count = 0
    try:
        for entry in sorted(agents_dir.iterdir()):
            if entry.is_dir() and (entry / "agent.md").is_file():
                count += 1
    except OSError:
        return 0
    return count


def get_company_version(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Inspect repository and return company version metadata dictionary.

    Returns a dictionary containing:
        - company_name: Name of the company ("Jester AI Company").
        - version: Company version string ("0.1.0").
        - agent_count: Integer count of registered agents dynamically counted
          from .agents/agents/*/agent.md.
    """
    root = get_repo_root(repo_root)
    info = get_company_info(root)
    company_name = info.get("company_name", DEFAULT_COMPANY_NAME)
    agent_count = count_registered_agents(root)

    return {
        "company_name": company_name,
        "version": VERSION,
        "agent_count": agent_count,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Inspect company version metadata and output JSON to stdout."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional path to repository root (defaults to script's parent repository).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact single-line JSON instead of indented formatting.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main execution entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        data = get_company_version(args.repo_root)
        indent = None if args.compact else 2
        json_output = json.dumps(data, indent=indent)
        sys.stdout.write(json_output + "\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:
        print(f"Error: company_version execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
