#!/usr/bin/env python3
"""Company Information Tool.

CLI utility to inspect the Jester AI Company repository metadata and
output company identity, registered agent roles, and operational status in
machine-readable JSON format.

Adheres strictly to the Jester AI Company core operating principles:
- Practical over complex
- Zero external dependencies
- Pure stdout JSON contract (diagnostics/errors to stderr)
- Location-agnostic execution
"""

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional

# Static baseline defaults (used as safe fallback)
DEFAULT_COMPANY_NAME = "Jester AI Company"
DEFAULT_REGISTERED_AGENTS = [
    "CEO",
    "Product",
    "Research",
    "UX",
    "Marketing",
    "Developer",
    "QA",
]
DEFAULT_STATUS = "STEP 2 = Company Foundation"


def get_repo_root(custom_path: Optional[Path] = None) -> Path:
    """Resolve repository root directory.

    If custom_path is provided, uses it. Otherwise resolves relative to this script's
    location (repo_root/tools/company_info.py -> repo_root).
    """
    if custom_path is not None:
        return custom_path.resolve()
    return Path(__file__).resolve().parent.parent


def parse_metadata_from_readme(readme_path: Path) -> Dict[str, Any]:
    """Parse company metadata from README.md content.

    Safely falls back to default values if sections are missing or formatted
    unexpectedly.
    """
    metadata: Dict[str, Any] = {
        "company_name": DEFAULT_COMPANY_NAME,
        "registered_agents": list(DEFAULT_REGISTERED_AGENTS),
        "status": DEFAULT_STATUS,
    }

    if not readme_path.is_file():
        print(
            f"Warning: README file not found at '{readme_path}', using baseline defaults.",
            file=sys.stderr,
        )
        return metadata

    try:
        content = readme_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(
            f"Warning: Failed to read '{readme_path}' ({exc}), using baseline defaults.",
            file=sys.stderr,
        )
        return metadata

    # 1. Company Name
    name_match = re.search(r"-\s*\*\*Name:\*\*\s*(.+)", content)
    if name_match:
        name_val = name_match.group(1).strip()
        if name_val:
            metadata["company_name"] = name_val

    # 2. Registered Agent Roles (Section 4)
    roles_section = re.search(
        r"## 4\. Initial Employee Roles.*?\n(.*?)(?=\n---|\n##|\Z)",
        content,
        re.DOTALL,
    )
    if roles_section:
        extracted_roles = [
            m.rstrip(":")
            for m in re.findall(
                r"-\s*\*\*([A-Za-z0-9_ -]+?):?\*\*",
                roles_section.group(1),
            )
        ]
        if extracted_roles:
            metadata["registered_agents"] = extracted_roles

    # 3. Status / Build Phase (Section 6 current step)
    phase_match = re.search(
        r"-\s*\*\*(STEP\s+\d+\s+=[^*]+)\*\*\s*\*\(Current\)\*",
        content,
    )
    if phase_match:
        phase_val = phase_match.group(1).strip()
        if phase_val:
            metadata["status"] = phase_val

    return metadata


def get_company_info(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Inspect repository and return structured company information dictionary."""
    root = get_repo_root(repo_root)
    readme_path = root / "README.md"
    return parse_metadata_from_readme(readme_path)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Inspect repository metadata and output company status in machine-readable JSON."
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
        data = get_company_info(args.repo_root)
        indent = None if args.compact else 2
        json_output = json.dumps(data, indent=indent)
        sys.stdout.write(json_output + "\n")
        sys.stdout.flush()
        return 0
    except Exception as exc:
        print(f"Error: company_info execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
