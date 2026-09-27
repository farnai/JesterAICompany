"""Company Status inspection and formatting module.

Inspects the company's operational state, recognized agents, active vs. planned
statuses, and domain responsibilities according to company architecture.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Optional

from .registry import get_agent_inventory

# Baseline defaults
DEFAULT_COMPANY_NAME = "Jester AI Company"
DEFAULT_PURPOSE = (
    "A team of AI employees that collaborate to perform real work "
    "and report results to the human owner."
)
DEFAULT_LIFECYCLE_STAGE = "Phase 2 - Company Foundation (Step 3 - Capability Rollout)"
DEFAULT_HEALTH_STATUS = "OPERATIONAL"
VERSION = "0.1.0"

# Catalog of implemented capabilities within Jester AI Company
IMPLEMENTED_CAPABILITIES: List[Dict[str, str]] = [
    {
        "name": "company_info",
        "description": "Repository metadata and registered agent introspection",
        "entrypoint": "tools/company_info.py",
    },
    {
        "name": "company_health",
        "description": "Operational health check and agent definition validation",
        "entrypoint": "tools/company_health.py",
    },
    {
        "name": "company_overview",
        "description": "Organizational blueprint and agent roster dashboard",
        "entrypoint": "tools/company_overview.py",
    },
    {
        "name": "company_snapshot",
        "description": "Operational state and active agent snapshot report",
        "entrypoint": "tools/company_snapshot.py",
    },
    {
        "name": "company_version",
        "description": "Version metadata and registered agent count",
        "entrypoint": "tools/company_version.py",
    },
    {
        "name": "run_pipeline",
        "description": "Sequential multi-agent execution pipeline runner with verification gating",
        "entrypoint": "tools/run_pipeline.py",
    },
    {
        "name": "verify_company",
        "description": "Repository structure, documentation, and boundary verification",
        "entrypoint": "tools/verify_company.py",
    },
    {
        "name": "company_status",
        "description": "Company status and agent inspection capability",
        "entrypoint": "jester_ai_company status / status.py",
    },
]


def get_repo_root(custom_path: Optional[Path] = None) -> Path:
    """Resolve repository root directory.

    If custom_path is provided, uses it. Otherwise resolves relative to this package's
    parent repository root.
    """
    if custom_path is not None:
        return Path(custom_path).resolve()
    # jester_ai_company/status.py -> jester_ai_company -> repo_root
    return Path(__file__).resolve().parent.parent


def parse_readme_metadata(readme_path: Path) -> Dict[str, str]:
    """Parse company identity, purpose, and lifecycle stage from README.md content.

    Safely falls back to baseline defaults if README is missing or malformed.
    """
    metadata = {
        "company_name": DEFAULT_COMPANY_NAME,
        "purpose": DEFAULT_PURPOSE,
        "lifecycle_stage": DEFAULT_LIFECYCLE_STAGE,
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

    # 2. Company Purpose
    purpose_match = re.search(r"-\s*\*\*Purpose:\*\*\s*(.+)", content)
    if purpose_match:
        purpose_val = purpose_match.group(1).strip()
        if purpose_val:
            metadata["purpose"] = purpose_val

    # 3. Lifecycle Stage (Section 6 current step)
    phase_match = re.search(
        r"-\s*\*\*(STEP\s+\d+\s+=[^*]+)\*\*\s*\*\(Current\)\*",
        content,
    )
    if phase_match:
        phase_val = phase_match.group(1).strip()
        if phase_val:
            metadata["lifecycle_stage"] = f"{phase_val} (Phase 2 - Company Foundation)"

    return metadata


def _sanitize_and_truncate_goal(goal: Optional[str], max_len: int = 61) -> str:
    """Sanitize whitespace and truncate goal to max_len characters (58 chars + '...' if longer)."""
    if not goal:
        return "None"
    sanitized = " ".join(str(goal).split())
    if len(sanitized) > max_len:
        return sanitized[:58] + "..."
    return sanitized


def get_pipeline_telemetry(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Read-only inspection of .runs/ directory relative to resolved repository root.

    Extracts execution telemetry including total run count and the latest run's
    manifest data (run_id, status, created_at, completed_at, goal).
    """
    root = get_repo_root(repo_root)
    runs_dir = root / ".runs"

    empty_telemetry: Dict[str, Any] = {
        "total_runs": 0,
        "has_runs": False,
        "latest_run": None,
        "run_id": None,
        "status": None,
        "created_at": None,
        "completed_at": None,
        "goal": None,
    }

    if not runs_dir.is_dir():
        return empty_telemetry

    try:
        run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    except OSError:
        return empty_telemetry

    if not run_dirs:
        return empty_telemetry

    # Sort run directories naturally (e.g. run_YYYYMMDD_HHMMSS or run_1, run_2, run_10)
    def _run_sort_key(path: Path) -> List[Any]:
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", path.name)]

    sorted_runs = sorted(run_dirs, key=_run_sort_key)
    latest_dir = sorted_runs[-1]
    total_runs = len(sorted_runs)

    manifest_path = latest_dir / "run_manifest.json"
    if not manifest_path.is_file():
        corrupted_run: Dict[str, Any] = {
            "run_id": latest_dir.name,
            "status": "CORRUPTED",
            "created_at": None,
            "completed_at": None,
            "goal": None,
            "error": f"run_manifest.json not found in {latest_dir.name}",
        }
        return {
            "total_runs": total_runs,
            "has_runs": True,
            "latest_run": corrupted_run,
            "run_id": latest_dir.name,
            "status": "CORRUPTED",
            "created_at": None,
            "completed_at": None,
            "goal": None,
        }

    try:
        content = manifest_path.read_text(encoding="utf-8")
        manifest_data = json.loads(content)
        if not isinstance(manifest_data, dict):
            raise ValueError("run_manifest.json is not a valid JSON dictionary")

        run_id = manifest_data.get("run_id") or latest_dir.name
        status_val = manifest_data.get("status") or "UNKNOWN"
        created_at = manifest_data.get("created_at")
        completed_at = manifest_data.get("completed_at")
        goal = manifest_data.get("goal")

        latest_run = {
            "run_id": str(run_id),
            "status": str(status_val),
            "created_at": created_at,
            "completed_at": completed_at,
            "goal": goal,
        }

        return {
            "total_runs": total_runs,
            "has_runs": True,
            "latest_run": latest_run,
            "run_id": latest_run["run_id"],
            "status": latest_run["status"],
            "created_at": latest_run["created_at"],
            "completed_at": latest_run["completed_at"],
            "goal": latest_run["goal"],
        }
    except Exception as exc:
        corrupted_run = {
            "run_id": latest_dir.name,
            "status": "CORRUPTED",
            "created_at": None,
            "completed_at": None,
            "goal": None,
            "error": f"Failed to parse run_manifest.json: {exc}",
        }
        return {
            "total_runs": total_runs,
            "has_runs": True,
            "latest_run": corrupted_run,
            "run_id": latest_dir.name,
            "status": "CORRUPTED",
            "created_at": None,
            "completed_at": None,
            "goal": None,
        }


def get_company_status(repo_root: Optional[Path] = None) -> Dict[str, Any]:
    """Inspect repository and return complete structured company status dictionary.

    Returns a comprehensive dictionary adhering to the PRD schema:
        - company_name: Official company name ('Jester AI Company')
        - purpose: Company purpose statement
        - lifecycle_stage: Current stage description
        - health: Operational health status ('OPERATIONAL')
        - status: Operational state ('OPERATIONAL' / 'OK')
        - summary: Summary counts (total_agents, active_agents, planned_agents)
        - total_agents: Integer count (7)
        - active_agents: Integer count (7)
        - planned_agents: Integer count (0)
        - implemented_capabilities: List of capability identifier strings
        - capabilities: Detailed list of capabilities with descriptions and entrypoints
        - agents: Complete list of recognized agents with status and responsibilities
        - pipeline_telemetry: Pipeline execution telemetry from .runs/
        - telemetry: Alias for pipeline_telemetry
        - company: Nested company metadata object
        - metadata: Timestamp and version metadata
    """
    root = get_repo_root(repo_root)
    readme_path = root / "README.md"
    readme_meta = parse_readme_metadata(readme_path)

    agents = get_agent_inventory(root)
    total_agents = len(agents)
    active_agents = sum(1 for a in agents if a.get("status") == "ACTIVE")
    planned_agents = total_agents - active_agents

    is_operational = (active_agents > 0 and bool(readme_meta["company_name"]))
    health_str = "OPERATIONAL" if is_operational else "DEGRADED"
    status_str = "OPERATIONAL" if is_operational else "DEGRADED"

    cap_names = [cap["name"] for cap in IMPLEMENTED_CAPABILITIES]
    telemetry_data = get_pipeline_telemetry(root)

    return {
        "company_name": readme_meta["company_name"],
        "purpose": readme_meta["purpose"],
        "lifecycle_stage": readme_meta["lifecycle_stage"],
        "health": health_str,
        "status": status_str,
        "total_agents": total_agents,
        "active_agents": active_agents,
        "planned_agents": planned_agents,
        "summary": {
            "total_agents": total_agents,
            "active_agents": active_agents,
            "planned_agents": planned_agents,
        },
        "implemented_capabilities": cap_names,
        "capabilities": IMPLEMENTED_CAPABILITIES,
        "agents": agents,
        "pipeline_telemetry": telemetry_data,
        "telemetry": telemetry_data,
        "company": {
            "name": readme_meta["company_name"],
            "company_name": readme_meta["company_name"],
            "purpose": readme_meta["purpose"],
            "lifecycle_stage": readme_meta["lifecycle_stage"],
            "health": health_str,
            "status": status_str,
        },
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": VERSION,
        },
    }


def format_status_console(status_data: Dict[str, Any]) -> str:
    """Format company status dictionary as a clean, readable console report.

    Features dividers, status badges ([ACTIVE], [PLANNED], [OK]), pipeline telemetry,
    and clear alignment.
    """
    company_name = status_data.get("company_name", DEFAULT_COMPANY_NAME)
    purpose = status_data.get("purpose", DEFAULT_PURPOSE)
    lifecycle_stage = status_data.get("lifecycle_stage", DEFAULT_LIFECYCLE_STAGE)
    health = status_data.get("health", DEFAULT_HEALTH_STATUS)
    summary = status_data.get("summary", {})
    capabilities = status_data.get("capabilities", [])
    agents = status_data.get("agents", [])
    telemetry = status_data.get("pipeline_telemetry") or status_data.get("telemetry") or {}

    lines: List[str] = [
        "=" * 80,
        "                           JESTER AI COMPANY STATUS",
        "=" * 80,
        f"Company Name     : {company_name}",
        f"Purpose          : {purpose}",
        f"Lifecycle Stage  : {lifecycle_stage}",
        f"Health           : {health} [OK]",
        "-" * 80,
        "Summary:",
        f"  Total Agents   : {summary.get('total_agents', 0)}",
        f"  Active Agents  : {summary.get('active_agents', 0)}",
        f"  Planned Agents : {summary.get('planned_agents', 0)}",
        "-" * 80,
        "Pipeline Telemetry:",
    ]

    total_runs = telemetry.get("total_runs", 0)
    latest_run = telemetry.get("latest_run") or {}
    run_id = telemetry.get("run_id") or latest_run.get("run_id")
    status_val = telemetry.get("status") or latest_run.get("status")
    goal = telemetry.get("goal") or latest_run.get("goal")
    created_at = telemetry.get("created_at") or latest_run.get("created_at")
    completed_at = telemetry.get("completed_at") or latest_run.get("completed_at")

    if total_runs == 0:
        lines.append(f"  {'Total Runs':<15} : 0")
        lines.append(f"  {'Latest Run':<15} : None")
        lines.append(f"  {'Status':<15} : None")
    else:
        lines.append(f"  {'Total Runs':<15} : {total_runs}")
        lines.append(f"  {'Latest Run':<15} : {run_id or 'None'}")
        lines.append(f"  {'Status':<15} : {status_val or 'UNKNOWN'}")
        if goal:
            lines.append(f"  {'Goal':<15} : {_sanitize_and_truncate_goal(goal, 61)}")
        if created_at:
            lines.append(f"  {'Created At':<15} : {created_at}")
        if completed_at:
            lines.append(f"  {'Completed At':<15} : {completed_at}")
        elif status_val in {"RUNNING", "INITIALIZING", "IN_PROGRESS"}:
            lines.append(f"  {'Completed At':<15} : In Progress")

    lines.extend([
        "-" * 80,
        "Implemented Capabilities:",
    ])

    for cap in capabilities:
        name = cap.get("name", "")
        desc = cap.get("description", "")
        lines.append(f"  - {name:<18} : {desc}")

    lines.extend([
        "-" * 80,
        "Agent Roster (7 Recognized Roles):",
    ])

    for agent in agents:
        role = agent.get("role", "")
        title = agent.get("title") or agent.get("display_name", role)
        status = agent.get("status", "PLANNED")
        path = agent.get("path")
        resp = agent.get("responsibilities", "")

        badge = f"[{status}]"
        if status == "ACTIVE":
            lines.append(f"  {badge:<10} {title} ({role})")
            if path:
                lines.append(f"             Path: {path}")
            lines.append(f"             Responsibilities: {resp}")
        else:
            lines.append(f"  {badge:<10} {title} ({role})")
            lines.append(f"             Responsibilities: {resp}")
        lines.append("")

    # Remove the trailing empty line if present and add closing divider
    if lines and lines[-1] == "":
        lines.pop()
    lines.append("=" * 80)

    return "\n".join(lines)
