"""Agent Registry and Inventory module.

Defines the 7 recognized organizational agent roles for Jester AI Company
and dynamically detects active vs. planned agent status from repository state.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

# The 7 recognized agent roles from company architecture (README.md Section 4)
RECOGNIZED_AGENTS: List[Dict[str, str]] = [
    {
        "role": "ceo",
        "title": "CEO Agent",
        "display_name": "CEO Agent",
        "responsibilities": (
            "Coordinates company operations, breaks down high-level objectives into actionable plans, "
            "delegates work to specialist employees, tracks status, and reports verified results to the human owner."
        ),
    },
    {
        "role": "product",
        "title": "Product Agent",
        "display_name": "Product Agent",
        "responsibilities": (
            "Defines requirements, scopes features, prioritizes user value, maintains product direction, "
            "and ensures work aligns with business objectives."
        ),
    },
    {
        "role": "research",
        "title": "Research Agent",
        "display_name": "Research Agent",
        "responsibilities": (
            "Conducts deep-dive investigations into technologies, tools, algorithms, and market data, "
            "delivering findings backed by concrete evidence."
        ),
    },
    {
        "role": "ux",
        "title": "UX Agent",
        "display_name": "UX Agent",
        "responsibilities": (
            "Designs user flows, interaction patterns, interface structures, and usability guidelines "
            "to ensure seamless user experiences."
        ),
    },
    {
        "role": "marketing",
        "title": "Marketing Agent",
        "display_name": "Marketing Agent",
        "responsibilities": (
            "Crafts product messaging, value propositions, documentation clarity, external communications, "
            "and positioning strategy."
        ),
    },
    {
        "role": "developer",
        "title": "Developer Agent",
        "display_name": "Developer Agent",
        "responsibilities": (
            "Writes, refactors, and tests clean, maintainable, and robust code adhering to project "
            "standards and operating principles."
        ),
    },
    {
        "role": "qa",
        "title": "QA Agent",
        "display_name": "QA Agent",
        "responsibilities": (
            "Designs test cases, verifies acceptance criteria, executes rigorous testing against real outputs, "
            "and guarantees that 'DONE' criteria are genuinely met."
        ),
    },
]


def _parse_agent_frontmatter(agent_md_path: Path) -> Dict[str, str]:
    """Parse YAML frontmatter key-value pairs from an agent.md file."""
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


def get_agent_inventory(repo_root: Path) -> List[Dict[str, Any]]:
    """Inspect repository to determine operational status for all 7 recognized agents.

    Each returned agent dictionary contains:
        - id: Canonical agent identifier (e.g. 'ceo', 'developer')
        - role: Canonical agent identifier matching role
        - name: Canonical agent identifier matching role
        - title: Formal agent title (e.g. 'CEO Agent')
        - display_name: Human-friendly name
        - status: 'ACTIVE' if an agent.md definition is present, else 'PLANNED'
        - responsibilities: Functional responsibilities defined in README.md Section 4
        - path: Relative path to agent.md if ACTIVE, else None
    """
    agents_dir = repo_root / ".agents" / "agents"
    inventory: List[Dict[str, Any]] = []

    for agent_def in RECOGNIZED_AGENTS:
        role_id = agent_def["role"]
        title = agent_def["title"]
        display_name = agent_def["display_name"]
        responsibilities = agent_def["responsibilities"]

        agent_file: Optional[Path] = None
        if agents_dir.is_dir():
            candidate = agents_dir / role_id / "agent.md"
            if candidate.is_file():
                agent_file = candidate
            else:
                # Case-insensitive directory lookup fallback
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
            fm = _parse_agent_frontmatter(agent_file)
            resolved_display_name = fm.get("displayName") or display_name
            rel_path = f".agents/agents/{role_id}/agent.md"
            inventory.append({
                "id": role_id,
                "role": role_id,
                "name": role_id,
                "title": title,
                "display_name": resolved_display_name,
                "status": "ACTIVE",
                "responsibilities": responsibilities,
                "path": rel_path,
            })
        else:
            inventory.append({
                "id": role_id,
                "role": role_id,
                "name": role_id,
                "title": title,
                "display_name": display_name,
                "status": "PLANNED",
                "responsibilities": responsibilities,
                "path": None,
            })

    return inventory
