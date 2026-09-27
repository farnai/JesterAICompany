#!/usr/bin/env python3
"""Company Overview Tool.

CLI utility to inspect Jester AI Company organizational structure and agent roster.
Provides a human-readable dashboard by default, and strict JSON schema output
when invoked with --json.

Adheres strictly to Jester AI Company core operating principles:
- Practical over complex
- Zero external dependencies (pure stdlib)
- Pure stdout JSON contract when --json is requested (diagnostics/errors to stderr)
- Location-agnostic execution
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional

# Static baseline defaults
DEFAULT_COMPANY_NAME = "Jester AI Company"
DEFAULT_STATUS = "STEP 2 = Company Foundation"
VERSION = "0.1.0"

# Defined organizational blueprint roles: (role_id, display_name, fallback_description)
ALL_ROLES = [
    (
        "ceo",
        "CEO Agent",
        "Coordinates company operations, breaks down objectives, delegates work, and reports verified results.",
    ),
    (
        "developer",
        "Developer Agent",
        "Software engineer responsible for implementing code changes, debugging, running tests, and inspecting builds.",
    ),
    (
        "product",
        "Product Agent",
        "Defines requirements, scopes features, prioritizes user value, and ensures work aligns with business objectives.",
    ),
    (
        "qa",
        "QA Agent",
        "Designs test cases, verifies acceptance criteria, executes rigorous testing against real outputs.",
    ),
    (
        "research",
        "Research Agent",
        "Conducts deep-dive investigations into technologies, tools, algorithms, and market data.",
    ),
    (
        "ux",
        "UX Agent",
        "Designs user flows, interaction patterns, interface structures, and usability guidelines.",
    ),
    (
        "marketing",
        "Marketing Agent",
        "Crafts product messaging, value propositions, documentation clarity, and communications.",
    ),
]


def get_repo_root(custom_path: Optional[Path] = None) -> Path:
    """Resolve repository root directory.

    If custom_path is provided, uses it. Otherwise resolves relative to this script's
    location (repo_root/tools/company_overview.py -> repo_root).
    """
    if custom_path is not None:
        return Path(custom_path).resolve()
    return Path(__file__).resolve().parent.parent


def parse_company_metadata(readme_path: Path) -> Dict[str, str]:
    """Parse company name and operational status from README.md content.

    Safely falls back to baseline defaults if README is missing or malformed.
    """
    metadata = {
        "name": DEFAULT_COMPANY_NAME,
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
            metadata["name"] = name_val

    # 2. Status / Build Phase (Section 6 current step)
    phase_match = re.search(
        r"-\s*\*\*(STEP\s+\d+\s+=[^*]+)\*\*\s*\*\(Current\)\*",
        content,
    )
    if phase_match:
        phase_val = phase_match.group(1).strip()
        if phase_val:
            metadata["status"] = phase_val

    return metadata


def _parse_agent_frontmatter(agent_md_path: Path) -> Dict[str, str]:
    """Parse YAML frontmatter from agent.md if present."""
    frontmatter: Dict[str, str] = {}
    try:
        content = agent_md_path.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                yaml_block = parts[1]
                for line in yaml_block.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        frontmatter[k.strip()] = v.strip().strip("'\"")
    except Exception:
        pass
    return frontmatter


def inspect_agents(repo_root: Path) -> List[Dict[str, Any]]:
    """Inspect .agents/agents/ to determine status for all 7 roles.

    Returns a list of agent dictionaries with keys:
    role, name, display_name, status (ACTIVE or PLANNED), path, and description.
    """
    agents_dir = repo_root / ".agents" / "agents"
    agents_list: List[Dict[str, Any]] = []

    for role_id, default_display_name, default_desc in ALL_ROLES:
        agent_file: Optional[Path] = None
        if agents_dir.is_dir():
            candidate = agents_dir / role_id / "agent.md"
            if candidate.is_file():
                agent_file = candidate
            else:
                # Case-insensitive directory lookup
                try:
                    for entry in agents_dir.iterdir():
                        if entry.is_dir() and entry.name.lower() == role_id.lower():
                            cand = entry / "agent.md"
                            if cand.is_file():
                                agent_file = cand
                                break
                except OSError:
                    pass

        if agent_file is not None:
            # Active agent
            fm = _parse_agent_frontmatter(agent_file)
            display_name = fm.get("displayName") or default_display_name
            description = fm.get("description") or default_desc
            rel_path = f".agents/agents/{role_id}/agent.md"
            agents_list.append({
                "role": role_id,
                "name": role_id,
                "display_name": display_name,
                "status": "ACTIVE",
                "path": rel_path,
                "description": description,
            })
        else:
            # Planned agent
            agents_list.append({
                "role": role_id,
                "name": role_id,
                "display_name": default_display_name,
                "status": "PLANNED",
                "path": None,
                "description": default_desc,
            })

    return agents_list


def get_company_overview(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Inspect repository and return structured company overview dictionary.

    Returns:
        dict containing:
            - company: Dict with name, company_name, and status.
            - summary: Dict with total_agents (7), active_agents (4), inactive_agents (3).
            - agents: List of 7 role dictionaries with status ACTIVE or PLANNED.
            - metadata: Dict with generated_at timestamp and version.
    """
    root = get_repo_root(repo_root)
    readme_path = root / "README.md"
    company_meta = parse_company_metadata(readme_path)

    agents = inspect_agents(root)
    total_agents = len(agents)
    active_agents = sum(1 for a in agents if a["status"] == "ACTIVE")
    inactive_agents = total_agents - active_agents

    return {
        "company": {
            "name": company_meta["name"],
            "company_name": company_meta["name"],
            "status": company_meta["status"],
        },
        "summary": {
            "total_agents": total_agents,
            "active_agents": active_agents,
            "inactive_agents": inactive_agents,
        },
        "agents": agents,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
        },
    }


def format_dashboard(overview: Dict[str, Any]) -> str:
    """Format company overview dictionary as a human-readable CLI dashboard."""
    company = overview.get("company", {})
    summary = overview.get("summary", {})
    agents = overview.get("agents", [])

    lines = [
        "=" * 68,
        "                    JESTER AI COMPANY OVERVIEW",
        "=" * 68,
        f"Company Name    : {company.get('name', DEFAULT_COMPANY_NAME)}",
        f"Status          : {company.get('status', DEFAULT_STATUS)}",
        "-" * 68,
        "Summary:",
        f"  Total Agents    : {summary.get('total_agents', 0)}",
        f"  Active Agents   : {summary.get('active_agents', 0)}",
        f"  Inactive Agents : {summary.get('inactive_agents', 0)}",
        "-" * 68,
        "Agents:",
    ]
    for agent in agents:
        role = agent.get("role", "")
        status = agent.get("status", "")
        path = agent.get("path")
        if status == "ACTIVE" and path:
            lines.append(f"  [{status}]  {role:<11} ({path})")
        else:
            lines.append(f"  [{status}] {role:<11} (planned)")
    lines.append("=" * 68)
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Jester AI Company Overview: Inspect company status and agent roster."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output strict JSON schema to stdout instead of human-readable dashboard.",
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
        help="When --json is enabled, output compact single-line JSON instead of indented formatting.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main execution entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        overview = get_company_overview(args.repo_root)
        if args.json:
            indent = None if args.compact else 2
            json_output = json.dumps(overview, indent=indent)
            sys.stdout.write(json_output + "\n")
            sys.stdout.flush()
        else:
            dashboard = format_dashboard(overview)
            sys.stdout.write(dashboard + "\n")
            sys.stdout.flush()
        return 0
    except Exception as exc:
        print(f"Error: company_overview execution failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
