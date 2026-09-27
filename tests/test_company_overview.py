"""Unit and integration tests for tools/company_overview.py.

Verifies:
AC 1: Default Human-Readable Dashboard CLI (exit code 0, human-readable layout, agent statuses).
AC 2: CLI --json Flag for Strict JSON Schema Output (pure stdout contract, valid JSON, compact flag).
AC 3: Programmatic API get_company_overview() (importable, location-agnostic, parameterized repo_root).
AC 4: Top-Level Schema Keys & company Object (name='Jester AI Company', status='STEP 2 = Company Foundation').
AC 5: summary Object Statistics (total_agents=7, active_agents=4, inactive_agents=3).
AC 6: agents List & Status Values (ACTIVE for ceo, developer, product, qa; PLANNED for research, ux, marketing).
AC 7: metadata Section & Operational Robustness (ISO timestamp, version, arbitrary cwd, dynamic agent detection, fallback).
"""

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "company_overview.py"

# Ensure repo root is on sys.path for direct module import tests
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import company_overview
from tools.company_overview import (
    DEFAULT_COMPANY_NAME,
    DEFAULT_STATUS,
    VERSION,
    format_dashboard,
    get_company_overview,
    get_repo_root,
    inspect_agents,
    parse_company_metadata,
)

EXPECTED_ROLES = {"ceo", "developer", "product", "qa", "research", "ux", "marketing"}
EXPECTED_ACTIVE_ROLES = {"ceo", "developer", "product", "qa"}
EXPECTED_PLANNED_ROLES = {"research", "ux", "marketing"}


# ==============================================================================
# Baseline Integrity
# ==============================================================================

def test_script_exists():
    """Verify tools/company_overview.py exists in repo."""
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"


# ==============================================================================
# AC 1: Default Human-Readable Dashboard CLI
# ==============================================================================

def test_ac1_cli_default_exit_code():
    """AC 1: Executing tools/company_overview.py with no flags exits with code 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Process failed with stderr: {result.stderr}"


def test_ac1_cli_default_human_readable_output():
    """AC 1: Default execution outputs a human-readable dashboard."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    stdout = result.stdout
    assert "JESTER AI COMPANY OVERVIEW" in stdout
    assert "Company Name" in stdout
    assert "Jester AI Company" in stdout
    assert "Summary:" in stdout
    assert "Total Agents" in stdout
    assert "Active Agents" in stdout
    assert "Inactive Agents" in stdout
    assert "Agents:" in stdout
    assert "[ACTIVE]" in stdout
    assert "[PLANNED]" in stdout


def test_ac1_cli_default_is_not_json():
    """AC 1: Default execution does not output raw JSON."""
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
# AC 2: CLI --json Flag for Strict JSON Schema Output
# ==============================================================================

def test_ac2_cli_json_flag_exit_code():
    """AC 2: Executing tools/company_overview.py --json exits with code 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Process failed with stderr: {result.stderr}"


def test_ac2_cli_json_flag_valid_json():
    """AC 2: Executing with --json prints strictly valid JSON to stdout."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, dict)


def test_ac2_cli_pure_stdout_contract():
    """AC 2: Verify pure stdout contract; stderr does not pollute stdout."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    stripped = result.stdout.strip()
    assert stripped.startswith("{")
    assert stripped.endswith("}")


def test_ac2_cli_compact_json():
    """AC 2: Verify --compact flag with --json prints single-line JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json", "--compact"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert isinstance(data, dict)


# ==============================================================================
# AC 3: Programmatic API get_company_overview()
# ==============================================================================

def test_ac3_programmatic_function_call():
    """AC 3: get_company_overview() can be invoked directly as a Python function."""
    data = get_company_overview()
    assert isinstance(data, dict)
    assert "company" in data
    assert "summary" in data
    assert "agents" in data
    assert "metadata" in data


def test_ac3_programmatic_with_explicit_repo_root():
    """AC 3: get_company_overview(repo_root=...) supports explicit repo root."""
    data = get_company_overview(repo_root=REPO_ROOT)
    assert isinstance(data, dict)
    assert data["company"]["name"] == "Jester AI Company"
    assert data["summary"]["total_agents"] == 7
    assert data["summary"]["active_agents"] == 4
    assert data["summary"]["inactive_agents"] == 3


# ==============================================================================
# AC 4: Top-Level Schema Keys & company Object
# ==============================================================================

def test_ac4_top_level_schema_keys():
    """AC 4: Schema contains company, summary, agents, and metadata."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    required_keys = {"company", "summary", "agents", "metadata"}
    assert required_keys.issubset(set(data.keys()))


def test_ac4_company_object_fields():
    """AC 4: company object contains name and status."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    company = data["company"]
    assert isinstance(company, dict)
    assert company["name"] == "Jester AI Company"
    assert company["status"] == "STEP 2 = Company Foundation"


# ==============================================================================
# AC 5: summary Object Statistics
# ==============================================================================

def test_ac5_summary_counts():
    """AC 5: summary has total_agents=7, active_agents=4, inactive_agents=3."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    summary = data["summary"]

    assert summary["total_agents"] == 7
    assert summary["active_agents"] == 4
    assert summary["inactive_agents"] == 3


def test_ac5_summary_field_types():
    """AC 5: summary counts are strictly integers."""
    data = get_company_overview()
    summary = data["summary"]
    for key in ("total_agents", "active_agents", "inactive_agents"):
        assert isinstance(summary[key], int) and not isinstance(summary[key], bool)


def test_ac5_summary_mathematical_consistency():
    """AC 5: active_agents + inactive_agents == total_agents."""
    data = get_company_overview()
    summary = data["summary"]
    assert summary["active_agents"] + summary["inactive_agents"] == summary["total_agents"]


# ==============================================================================
# AC 6: agents List & Status Values
# ==============================================================================

def test_ac6_agents_list_length_and_all_roles():
    """AC 6: agents list has 7 roles: ceo, developer, product, qa, research, ux, marketing."""
    data = get_company_overview()
    agents = data["agents"]
    assert isinstance(agents, list)
    assert len(agents) == 7

    roles = [a["role"] for a in agents]
    assert set(roles) == EXPECTED_ROLES


def test_ac6_active_agents_status():
    """AC 6: Active agents (ceo, developer, product, qa) have status ACTIVE and valid path."""
    data = get_company_overview()
    agents = data["agents"]

    agent_by_role = {a["role"]: a for a in agents}

    for role in EXPECTED_ACTIVE_ROLES:
        agent = agent_by_role[role]
        assert agent["status"] == "ACTIVE", f"Role '{role}' should have status ACTIVE"
        assert agent["path"] == f".agents/agents/{role}/agent.md"
        assert (REPO_ROOT / agent["path"]).is_file()


def test_ac6_planned_agents_status():
    """AC 6: Planned agents (research, ux, marketing) have status PLANNED and path None."""
    data = get_company_overview()
    agents = data["agents"]

    agent_by_role = {a["role"]: a for a in agents}

    for role in EXPECTED_PLANNED_ROLES:
        agent = agent_by_role[role]
        assert agent["status"] == "PLANNED", f"Role '{role}' should have status PLANNED"
        assert agent["path"] is None


def test_ac6_agent_entry_schema():
    """AC 6: Each agent entry contains role, name, display_name, status, path, description."""
    data = get_company_overview()
    agents = data["agents"]

    expected_keys = {"role", "name", "display_name", "status", "path", "description"}
    for agent in agents:
        assert isinstance(agent, dict)
        assert expected_keys.issubset(set(agent.keys()))
        assert agent["role"] == agent["name"]
        assert agent["status"] in {"ACTIVE", "PLANNED"}


# ==============================================================================
# AC 7: metadata Section & Operational Robustness / Fallback
# ==============================================================================

def test_ac7_metadata_fields():
    """AC 7: metadata contains generated_at ISO timestamp and version."""
    data = get_company_overview()
    metadata = data["metadata"]
    assert isinstance(metadata, dict)
    assert "generated_at" in metadata
    assert "version" in metadata
    assert metadata["version"] == VERSION

    # Verify generated_at is a valid ISO timestamp
    parsed_dt = datetime.fromisoformat(metadata["generated_at"])
    assert isinstance(parsed_dt, datetime)


def test_ac7_location_agnostic_execution():
    """AC 7: Invocation succeeds from an arbitrary working directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--json"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["company"]["name"] == "Jester AI Company"
        assert data["summary"]["total_agents"] == 7
        assert data["summary"]["active_agents"] == 4


def test_ac7_repo_root_flag():
    """AC 7: Specifying --repo-root option explicitly points to repo."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--json", "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["company"]["name"] == "Jester AI Company"
    assert data["summary"]["active_agents"] == 4


def test_ac7_dynamic_agent_detection_with_mock():
    """AC 7: Modifying agent definitions in a mock repository dynamically updates counts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_root = Path(tmpdir)
        mock_agents = mock_root / ".agents" / "agents"

        # Create only 2 agents (ceo and qa)
        (mock_agents / "ceo").mkdir(parents=True)
        (mock_agents / "ceo" / "agent.md").write_text("---\nname: ceo\n---\n", encoding="utf-8")

        (mock_agents / "qa").mkdir(parents=True)
        (mock_agents / "qa" / "agent.md").write_text("---\nname: qa\n---\n", encoding="utf-8")

        # Mock README
        (mock_root / "README.md").write_text("- **Name:** Mock Company\n", encoding="utf-8")

        overview = get_company_overview(mock_root)
        assert overview["company"]["name"] == "Mock Company"
        assert overview["summary"]["total_agents"] == 7
        assert overview["summary"]["active_agents"] == 2
        assert overview["summary"]["inactive_agents"] == 5

        agent_by_role = {a["role"]: a for a in overview["agents"]}
        assert agent_by_role["ceo"]["status"] == "ACTIVE"
        assert agent_by_role["qa"]["status"] == "ACTIVE"
        assert agent_by_role["developer"]["status"] == "PLANNED"
        assert agent_by_role["product"]["status"] == "PLANNED"


def test_ac7_fallback_on_missing_repo_root():
    """AC 7: Graceful fallback when repository root is empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_root = Path(tmpdir)
        overview = get_company_overview(mock_root)
        assert overview["company"]["name"] == DEFAULT_COMPANY_NAME
        assert overview["company"]["status"] == DEFAULT_STATUS
        assert overview["summary"]["total_agents"] == 7
        assert overview["summary"]["active_agents"] == 0
        assert overview["summary"]["inactive_agents"] == 7
        for agent in overview["agents"]:
            assert agent["status"] == "PLANNED"


def test_format_dashboard_helper():
    """Verify format_dashboard outputs formatted text with summary and agent lines."""
    data = get_company_overview()
    dashboard = format_dashboard(data)
    assert isinstance(dashboard, str)
    assert "Jester AI Company" in dashboard
    assert "Total Agents    : 7" in dashboard
    assert "[ACTIVE]  ceo" in dashboard
    assert "[PLANNED] marketing" in dashboard
