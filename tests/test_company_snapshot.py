"""Unit and integration tests for tools/company_snapshot.py.

Verifies:
1. tools/company_snapshot.py exists and is executable.
2. Default CLI execution outputs a human-readable snapshot report (exit code 0).
3. CLI --json flag produces valid JSON on pure stdout with exit code 0.
4. CLI --json --compact produces valid single-line JSON.
5. Programmatic API get_company_snapshot() returns a valid snapshot dictionary.
6. Required dictionary keys are present: company_name, status, total_agents,
   active_agents, planned_agents, agents, summary, company, metadata.
7. AC 2 Compliance:
   - total_agents == 7
   - active_agents == 4 (ceo, developer, product, qa)
   - planned_agents == 3 (research, ux, marketing)
   - agents list contains all 7 roles with valid statuses (ACTIVE or PLANNED)
8. Agent entries contain expected schema keys (role, name, display_name, status, path, description).
9. Location-agnostic execution works with custom --repo-root and from arbitrary cwd.
10. Safe fallback behavior when README.md is missing.
"""

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "company_snapshot.py"

# Ensure repo root is on sys.path for direct module import tests
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import company_snapshot
from tools.company_snapshot import (
    DEFAULT_COMPANY_NAME,
    DEFAULT_STATUS,
    VERSION,
    format_snapshot_report,
    get_company_snapshot,
    get_repo_root,
    inspect_active_agents,
    inspect_agents,
    parse_company_metadata,
)

EXPECTED_ACTIVE_ROLES = {"ceo", "developer", "product", "qa"}
EXPECTED_PLANNED_ROLES = {"research", "ux", "marketing"}
EXPECTED_ALL_ROLES = EXPECTED_ACTIVE_ROLES | EXPECTED_PLANNED_ROLES


# ==============================================================================
# Baseline Integrity
# ==============================================================================

def test_script_exists():
    """Verify tools/company_snapshot.py exists in repo."""
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"


# ==============================================================================
# CLI Human-Readable Output (Default)
# ==============================================================================

def test_cli_default_exit_code():
    """Executing tools/company_snapshot.py with no flags exits with code 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Process failed with stderr: {result.stderr}"


def test_cli_default_human_readable_output():
    """Default execution outputs a human-readable snapshot report."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    stdout = result.stdout
    assert "JESTER AI COMPANY SNAPSHOT" in stdout
    assert "Company Name" in stdout
    assert "Jester AI Company" in stdout
    assert "Summary:" in stdout
    assert "Total Agents" in stdout
    assert "Active Agents" in stdout
    assert "Planned Agents" in stdout
    assert "Agents:" in stdout
    assert "[ACTIVE]" in stdout
    assert "[PLANNED]" in stdout


def test_cli_default_is_not_json():
    """Default execution does not output raw JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)


# ==============================================================================
# CLI --json Flag & Pure Stdout Contract
# ==============================================================================

def test_cli_json_flag_exit_code():
    """Executing with --json flag exits with code 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Process failed with stderr: {result.stderr}"


def test_cli_json_flag_valid_json():
    """Executing with --json outputs valid JSON to stdout."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, dict)


def test_cli_json_pure_stdout():
    """Pure stdout contract: diagnostics or warnings do not corrupt stdout JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""


def test_cli_json_compact():
    """Executing with --json --compact produces a single line of valid JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json", "--compact"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = [line for line in result.stdout.strip().splitlines() if line]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert isinstance(data, dict)


# ==============================================================================
# Dictionary Keys & Schema
# ==============================================================================

def test_top_level_dictionary_keys():
    """Verify all expected top-level dictionary keys are present."""
    data = get_company_snapshot(REPO_ROOT)
    expected_keys = {
        "company_name",
        "status",
        "total_agents",
        "active_agents",
        "planned_agents",
        "agents",
        "company",
        "summary",
        "metadata",
    }
    for key in expected_keys:
        assert key in data, f"Missing required top-level key '{key}'"


def test_summary_dictionary_keys():
    """Verify summary section contains total_agents, active_agents, planned_agents."""
    data = get_company_snapshot(REPO_ROOT)
    summary = data.get("summary", {})
    assert "total_agents" in summary
    assert "active_agents" in summary
    assert "planned_agents" in summary


def test_metadata_dictionary_keys():
    """Verify metadata section contains generated_at timestamp and version."""
    data = get_company_snapshot(REPO_ROOT)
    metadata = data.get("metadata", {})
    assert "generated_at" in metadata
    assert "version" in metadata
    assert metadata["version"] == VERSION
    # Ensure generated_at is a valid ISO timestamp
    datetime.fromisoformat(metadata["generated_at"])


# ==============================================================================
# AC 2 Compliance: Agent Counts & Roster Verification
# ==============================================================================

def test_ac2_agent_counts():
    """AC 2: total_agents=7, active_agents=4, planned_agents=3."""
    data = get_company_snapshot(REPO_ROOT)

    # Top-level counts
    assert data["total_agents"] == 7, "total_agents should be 7"
    assert data["active_agents"] == 4, "active_agents should be 4"
    assert data["planned_agents"] == 3, "planned_agents should be 3"

    # Summary counts
    summary = data["summary"]
    assert summary["total_agents"] == 7
    assert summary["active_agents"] == 4
    assert summary["planned_agents"] == 3


def test_ac2_agents_list_all_roles():
    """AC 2: agents list contains all 7 roles with active and planned statuses."""
    data = get_company_snapshot(REPO_ROOT)
    agents = data.get("agents", [])

    assert len(agents) == 7, f"Expected 7 agents, got {len(agents)}"

    roles_in_list = {a["role"] for a in agents}
    assert roles_in_list == EXPECTED_ALL_ROLES

    agent_by_role = {a["role"]: a for a in agents}

    for role in EXPECTED_ACTIVE_ROLES:
        assert agent_by_role[role]["status"] == "ACTIVE"
        assert agent_by_role[role]["path"] == f".agents/agents/{role}/agent.md"

    for role in EXPECTED_PLANNED_ROLES:
        assert agent_by_role[role]["status"] == "PLANNED"
        assert agent_by_role[role]["path"] is None


def test_agent_entry_schema():
    """Verify schema of all agent items in the agents list."""
    data = get_company_snapshot(REPO_ROOT)
    for agent in data["agents"]:
        assert "role" in agent
        assert "name" in agent
        assert "display_name" in agent
        assert "status" in agent
        assert "path" in agent
        assert "description" in agent
        assert agent["status"] in {"ACTIVE", "PLANNED"}
        if agent["status"] == "ACTIVE":
            assert agent["path"].startswith(".agents/agents/")
            assert agent["path"].endswith("agent.md")
        else:
            assert agent["path"] is None
        assert len(agent["description"]) > 0


# ==============================================================================
# Location-Agnostic & Fallback Handling
# ==============================================================================

def test_location_agnostic_repo_root_flag():
    """CLI works when passed explicit --repo-root from another working directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--repo-root", str(REPO_ROOT), "--json"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_agents"] == 7
        assert data["active_agents"] == 4
        assert data["planned_agents"] == 3


def test_location_agnostic_execution():
    """CLI works from arbitrary working directory resolving repo root relative to script."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--json"],
            cwd=tmp_dir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["total_agents"] == 7
        assert data["active_agents"] == 4
        assert data["planned_agents"] == 3


def test_missing_readme_fallback():
    """Snapshot gracefully falls back to default company name and status if README is absent."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Empty directory with no README and no .agents
        snapshot = get_company_snapshot(tmp_path)
        assert snapshot["company_name"] == DEFAULT_COMPANY_NAME
        assert snapshot["status"] == DEFAULT_STATUS
        assert snapshot["total_agents"] == 7
        assert snapshot["active_agents"] == 0
        assert snapshot["planned_agents"] == 7
        assert len(snapshot["agents"]) == 7
        for agent in snapshot["agents"]:
            assert agent["status"] == "PLANNED"
