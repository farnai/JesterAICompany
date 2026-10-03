"""Automated test suite for Company Status & Agent Inspection Capability.

Verifies:
1. Baseline Integrity: Package imports, file existence, and zero external dependencies.
2. Functional Requirement 1 (Agent Inventory): All 7 recognized agents present.
3. Functional Requirement 2 (Agent Status): Distinction between ACTIVE (4) and PLANNED (3).
4. Functional Requirement 3 (Roles & Responsibilities): Full functional responsibilities matching README.md.
5. Functional Requirement 4 (Company State & Health): Company name, purpose, lifecycle stage, health, capabilities, and summary counts.
6. Functional Requirement 5 (Dual Output Modes): Human-readable console dashboard vs. strict stdout JSON schema.
7. Functional Requirement 6 (Execution Entrypoints):
   - python -m jester_ai_company status
   - python -m jester_ai_company status --json
   - python status.py
   - python status.py --json
   - python -m jester_ai_company status --help
   - python status.py --help
   - python -m jester_ai_company
8. Functional Requirement 7 (Constraints & Robustness): Zero third-party packages, JesterBridge boundaries,
   location-agnostic execution, and dynamic agent detection fallbacks.
"""

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Ensure repo root is on sys.path for direct imports
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import jester_ai_company
from jester_ai_company.registry import RECOGNIZED_AGENTS, get_agent_inventory
from jester_ai_company.status import (
    DEFAULT_COMPANY_NAME,
    DEFAULT_HEALTH_STATUS,
    DEFAULT_LIFECYCLE_STAGE,
    DEFAULT_PURPOSE,
    IMPLEMENTED_CAPABILITIES,
    VERSION,
    format_status_console,
    get_company_status,
    get_repo_root,
    parse_readme_metadata,
)
import status as root_status

EXPECTED_ROLES = {"ceo", "product", "research", "ux", "marketing", "developer", "qa"}
EXPECTED_ACTIVE_ROLES = set(EXPECTED_ROLES)
EXPECTED_PLANNED_ROLES = set()


# ==============================================================================
# 1. Baseline Integrity
# ==============================================================================

def test_package_files_exist():
    """Verify all package modules and root entrypoints exist."""
    expected_files = [
        REPO_ROOT / "jester_ai_company" / "__init__.py",
        REPO_ROOT / "jester_ai_company" / "__main__.py",
        REPO_ROOT / "jester_ai_company" / "cli.py",
        REPO_ROOT / "jester_ai_company" / "registry.py",
        REPO_ROOT / "jester_ai_company" / "status.py",
        REPO_ROOT / "status.py",
    ]
    for file_path in expected_files:
        assert file_path.is_file(), f"Missing file: {file_path}"


def test_package_exports():
    """Verify jester_ai_company exports public APIs and version."""
    assert hasattr(jester_ai_company, "__version__")
    assert jester_ai_company.__version__ == "0.1.0"
    assert hasattr(jester_ai_company, "get_company_status")
    assert hasattr(jester_ai_company, "get_agent_inventory")
    assert hasattr(jester_ai_company, "format_status_console")


# ==============================================================================
# 2. Functional Requirement 1: Agent Inventory
# ==============================================================================

def test_agent_inventory_contains_all_7_roles():
    """FR 1: All 7 recognized agents from company architecture are present."""
    status_data = get_company_status()
    agents = status_data["agents"]
    assert len(agents) == 7

    found_roles = {agent["role"] for agent in agents}
    assert found_roles == EXPECTED_ROLES


def test_agent_inventory_order_and_definitions():
    """FR 1: Recognized agent definitions include canonical identifiers and titles."""
    assert len(RECOGNIZED_AGENTS) == 7
    roles = [a["role"] for a in RECOGNIZED_AGENTS]
    assert set(roles) == EXPECTED_ROLES
    for agent in RECOGNIZED_AGENTS:
        assert agent["role"] in EXPECTED_ROLES
        assert "Agent" in agent["title"]
        assert len(agent["responsibilities"]) > 20


# ==============================================================================
# 3. Functional Requirement 2: Agent Status
# ==============================================================================

def test_active_agents_status_and_paths():
    """FR 2: Active agents (ceo, product, developer, qa) have status ACTIVE and existing path."""
    status_data = get_company_status()
    agents = status_data["agents"]
    agent_by_role = {a["role"]: a for a in agents}

    for role in EXPECTED_ACTIVE_ROLES:
        agent = agent_by_role[role]
        assert agent["id"] == role, f"Role '{role}' missing or mismatched id"
        assert agent["status"] == "ACTIVE", f"Role '{role}' should be ACTIVE"
        assert agent["path"] == f".agents/agents/{role}/agent.md"
        assert (REPO_ROOT / agent["path"]).is_file(), f"Path for {role} does not exist"


def test_planned_agents_status_and_paths():
    """FR 2: Planned agents (research, ux, marketing) have status PLANNED and path None when not yet registered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_root = Path(tmpdir)
        (mock_root / ".agents" / "agents" / "ceo").mkdir(parents=True)
        (mock_root / ".agents" / "agents" / "ceo" / "agent.md").write_text("# CEO", encoding="utf-8")
        status_data = get_company_status(repo_root=mock_root)
        agent_by_role = {a["role"]: a for a in status_data["agents"]}
        for role in ("research", "ux", "marketing"):
            agent = agent_by_role[role]
            assert agent["id"] == role, f"Role '{role}' missing or mismatched id"
            assert agent["status"] == "PLANNED", f"Role '{role}' should be PLANNED"
            assert agent["path"] is None


# ==============================================================================
# 4. Functional Requirement 3: Roles & Responsibilities
# ==============================================================================

def test_agent_roles_and_responsibilities_match_readme():
    """FR 3: Agent titles and functional responsibilities match README.md Section 4."""
    status_data = get_company_status()
    agent_by_role = {a["role"]: a for a in status_data["agents"]}

    # CEO
    ceo = agent_by_role["ceo"]
    assert "Coordinates company operations" in ceo["responsibilities"]
    assert "reports verified results" in ceo["responsibilities"]
    assert ceo["title"] == "CEO Agent"

    # Product
    product = agent_by_role["product"]
    assert "Defines requirements" in product["responsibilities"]
    assert "aligns with business objectives" in product["responsibilities"]
    assert product["title"] == "Product Agent"

    # Research
    research = agent_by_role["research"]
    assert "deep-dive investigations" in research["responsibilities"]
    assert "backed by concrete evidence" in research["responsibilities"]
    assert research["title"] == "Research Agent"

    # UX
    ux = agent_by_role["ux"]
    assert "user flows" in ux["responsibilities"]
    assert "seamless user experiences" in ux["responsibilities"]
    assert ux["title"] == "UX Agent"

    # Marketing
    marketing = agent_by_role["marketing"]
    assert "product messaging" in marketing["responsibilities"]
    assert "positioning strategy" in marketing["responsibilities"]
    assert marketing["title"] == "Marketing Agent"

    # Developer
    developer = agent_by_role["developer"]
    assert "Writes, refactors, and tests clean, maintainable, and robust code" in developer["responsibilities"]
    assert developer["title"] == "Developer Agent"

    # QA
    qa = agent_by_role["qa"]
    assert "Designs test cases, verifies acceptance criteria" in qa["responsibilities"]
    assert "guarantees that 'DONE' criteria are genuinely met" in qa["responsibilities"]
    assert qa["title"] == "QA Agent"


# ==============================================================================
# 5. Functional Requirement 4: Company State & Health
# ==============================================================================

def test_company_state_and_identity_fields():
    """FR 4: Company identity, purpose, lifecycle stage, and health are accurate."""
    status_data = get_company_status()

    assert status_data["company_name"] == "Jester AI Company"
    assert "AI employees that collaborate to perform real work" in status_data["purpose"]
    assert "Company Foundation" in status_data["lifecycle_stage"]
    assert status_data["health"] == "OPERATIONAL"
    assert status_data["status"] == "OPERATIONAL"

    # Also check nested company object
    company = status_data["company"]
    assert company["name"] == "Jester AI Company"
    assert company["health"] == "OPERATIONAL"


def test_summary_agent_counts():
    """FR 4: Summary counts are mathematically consistent and accurate."""
    status_data = get_company_status()
    summary = status_data["summary"]

    assert summary["total_agents"] == 7
    assert summary["active_agents"] == len(EXPECTED_ACTIVE_ROLES)
    assert summary["planned_agents"] == len(EXPECTED_PLANNED_ROLES)
    assert summary["active_agents"] + summary["planned_agents"] == summary["total_agents"]

    # Top-level mirrors
    assert status_data["total_agents"] == 7
    assert status_data["active_agents"] == len(EXPECTED_ACTIVE_ROLES)
    assert status_data["planned_agents"] == len(EXPECTED_PLANNED_ROLES)


def test_implemented_capabilities_catalog():
    """FR 4: Implemented capabilities list includes all known utilities."""
    status_data = get_company_status()
    caps = status_data["implemented_capabilities"]

    expected_caps = {
        "company_info",
        "company_health",
        "company_overview",
        "company_snapshot",
        "company_version",
        "run_pipeline",
        "verify_company",
        "company_status",
    }
    assert expected_caps.issubset(set(caps))
    assert len(status_data["capabilities"]) >= len(expected_caps)


# ==============================================================================
# 6. Functional Requirement 5: Dual Output Modes
# ==============================================================================

def test_default_human_readable_console_output():
    """FR 5: Default console output contains dividers, status badges, and is not raw JSON."""
    status_data = get_company_status()
    console_out = format_status_console(status_data)

    assert "========================================" in console_out
    assert "JESTER AI COMPANY STATUS" in console_out
    assert "Company Name     : Jester AI Company" in console_out
    assert "Health           : OPERATIONAL [OK]" in console_out
    assert "Summary:" in console_out
    assert "Total Agents   : 7" in console_out
    assert f"Active Agents  : {len(EXPECTED_ACTIVE_ROLES)}" in console_out
    assert f"Planned Agents : {len(EXPECTED_PLANNED_ROLES)}" in console_out
    assert "Implemented Capabilities:" in console_out
    assert "company_status" in console_out
    assert "[ACTIVE]   CEO Agent (ceo)" in console_out
    assert "[ACTIVE]   Research Agent (research)" in console_out

    # Verify formatting of planned agents with mock data
    mock_status = {
        "company_name": "Jester AI Company",
        "health": "healthy",
        "summary": {"total_agents": 1, "active_agents": 0, "planned_agents": 1},
        "capabilities": [],
        "implemented_capabilities": [],
        "agents": [{"role": "research", "title": "Research Agent", "status": "PLANNED", "path": None}],
        "metadata": {"version": "0.1.0", "timestamp": "2026-10-03T00:00:00Z"},
    }
    mock_out = format_status_console(mock_status)
    assert "[PLANNED]  Research Agent (research)" in mock_out

    # Must NOT be JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(console_out)


def test_json_output_mode_schema_conformance():
    """FR 5: --json produces strictly valid JSON conforming to schema."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "status", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""

    data = json.loads(result.stdout)
    required_keys = {
        "company_name",
        "purpose",
        "lifecycle_stage",
        "health",
        "status",
        "total_agents",
        "active_agents",
        "planned_agents",
        "summary",
        "implemented_capabilities",
        "capabilities",
        "agents",
        "company",
        "metadata",
    }
    assert required_keys.issubset(set(data.keys()))

    # Regression test for FINDING-001: Validate agent dictionary schema (id, name, status, role, responsibilities)
    agent_required_keys = {"id", "name", "status", "role", "responsibilities"}
    assert len(data["agents"]) == 7
    for agent in data["agents"]:
        assert isinstance(agent, dict)
        assert agent_required_keys.issubset(set(agent.keys())), (
            f"Agent {agent.get('role')} missing keys: {agent_required_keys - set(agent.keys())}"
        )
        assert agent["id"] == agent["role"]
        assert agent["name"] == agent["role"]
        assert agent["status"] in {"ACTIVE", "PLANNED"}
        assert len(agent["responsibilities"]) > 0


def test_json_compact_flag():
    """FR 5: --compact with --json outputs single-line JSON."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "status", "--json", "--compact"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["company_name"] == "Jester AI Company"


# ==============================================================================
# 7. Functional Requirement 6: Execution Entrypoints
# ==============================================================================

def test_entrypoint_module_status():
    """FR 6: python -m jester_ai_company status exits 0 with console output."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "status"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "JESTER AI COMPANY STATUS" in result.stdout
    assert "Company Name     : Jester AI Company" in result.stdout


def test_entrypoint_module_status_json():
    """FR 6: python -m jester_ai_company status --json exits 0 with valid JSON."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "status", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["company_name"] == "Jester AI Company"
    assert data["summary"]["total_agents"] == 7


def test_entrypoint_module_default_run():
    """FR 6: python -m jester_ai_company (without args) defaults to status report."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "JESTER AI COMPANY STATUS" in result.stdout


def test_entrypoint_root_status_script():
    """FR 6: python status.py exits 0 with human-readable dashboard."""
    result = subprocess.run(
        [sys.executable, "status.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "JESTER AI COMPANY STATUS" in result.stdout
    assert f"Active Agents  : {len(EXPECTED_ACTIVE_ROLES)}" in result.stdout


def test_entrypoint_root_status_script_json():
    """FR 6: python status.py --json exits 0 with valid JSON."""
    result = subprocess.run(
        [sys.executable, "status.py", "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["company_name"] == "Jester AI Company"
    assert data["active_agents"] == len(EXPECTED_ACTIVE_ROLES)


def test_entrypoint_module_status_help():
    """FR 6: python -m jester_ai_company status --help exits 0 with help text."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "status", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--json" in result.stdout
    assert "--repo-root" in result.stdout


def test_entrypoint_root_status_help():
    """FR 6: python status.py --help exits 0 with help text."""
    result = subprocess.run(
        [sys.executable, "status.py", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--json" in result.stdout


# ==============================================================================
# 8. Functional Requirement 7: Constraints, Boundaries & Robustness
# ==============================================================================

def test_no_third_party_dependencies_in_package():
    """FR 7: Ensure jester_ai_company package uses only Python standard library."""
    import inspect
    import jester_ai_company.cli
    import jester_ai_company.registry
    import jester_ai_company.status

    allowed_stdlib_modules = {
        "argparse",
        "datetime",
        "json",
        "os",
        "pathlib",
        "re",
        "sys",
        "typing",
        "jester_ai_company",
    }

    for mod in (jester_ai_company.cli, jester_ai_company.registry, jester_ai_company.status):
        for name, val in inspect.getmembers(mod):
            if inspect.ismodule(val):
                top_pkg = val.__name__.split(".")[0]
                assert top_pkg in allowed_stdlib_modules or top_pkg.startswith("jester_ai_company"), (
                    f"Forbidden external import '{top_pkg}' in {mod.__name__}"
                )


def test_jesterbridge_boundary_not_referenced():
    """FR 7: JesterBridge must not be imported or referenced anywhere in implementation."""
    package_dir = REPO_ROOT / "jester_ai_company"
    for py_file in package_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "JesterBridge" not in content, f"Forbidden JesterBridge reference in {py_file}"


def test_location_agnostic_execution():
    """FR 7: Execution succeeds from an arbitrary working directory outside the repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Run python status.py via absolute path
        status_script = REPO_ROOT / "status.py"
        result = subprocess.run(
            [sys.executable, str(status_script), "--json"],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["company_name"] == "Jester AI Company"
        assert data["summary"]["total_agents"] == 7
        assert data["summary"]["active_agents"] == len(EXPECTED_ACTIVE_ROLES)


def test_repo_root_flag():
    """FR 7: Specifying --repo-root explicitly inspects the target repository."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "status", "--json", "--repo-root", str(REPO_ROOT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["company_name"] == "Jester AI Company"
    assert data["summary"]["active_agents"] == len(EXPECTED_ACTIVE_ROLES)


def test_dynamic_agent_detection_mock_directory():
    """FR 7: Dynamic detection updates agent status when definitions are added/removed."""
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

        status_data = get_company_status(mock_root)
        assert status_data["company_name"] == "Mock Company"
        assert status_data["summary"]["total_agents"] == 7
        assert status_data["summary"]["active_agents"] == 2
        assert status_data["summary"]["planned_agents"] == 5

        agents = {a["role"]: a for a in status_data["agents"]}
        assert agents["ceo"]["status"] == "ACTIVE"
        assert agents["qa"]["status"] == "ACTIVE"
        assert agents["developer"]["status"] == "PLANNED"
        assert agents["product"]["status"] == "PLANNED"
        assert agents["research"]["status"] == "PLANNED"


def test_fallback_on_missing_repo_root():
    """FR 7: Graceful fallback when repository root is empty or invalid."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_root = Path(tmpdir)
        status_data = get_company_status(mock_root)

        assert status_data["company_name"] == DEFAULT_COMPANY_NAME
        assert status_data["summary"]["total_agents"] == 7
        assert status_data["summary"]["active_agents"] == 0
        assert status_data["summary"]["planned_agents"] == 7
        assert status_data["health"] == "DEGRADED"


# ==============================================================================
# 9. Negative CLI Tests (Regression for FINDING-002)
# ==============================================================================

def test_negative_module_invalid_flag():
    """FINDING-002: Invalid flag passed to module CLI produces non-zero exit and stderr message."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "--invalid-flag-xyz"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "error" in result.stderr.lower() or "unrecognized" in result.stderr.lower()


def test_negative_module_invalid_subcommand():
    """FINDING-002: Invalid subcommand passed to module CLI produces non-zero exit and stderr message."""
    result = subprocess.run(
        [sys.executable, "-m", "jester_ai_company", "nonexistent_subcommand"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "error" in result.stderr.lower() or "invalid choice" in result.stderr.lower()


def test_negative_status_script_invalid_flag():
    """FINDING-002: Invalid flag passed to status.py produces non-zero exit and stderr message."""
    result = subprocess.run(
        [sys.executable, "status.py", "--invalid-flag-xyz"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "error" in result.stderr.lower() or "unrecognized" in result.stderr.lower()


def test_negative_status_script_invalid_subcommand():
    """FINDING-002: Invalid subcommand passed to status.py produces non-zero exit and stderr message."""
    result = subprocess.run(
        [sys.executable, "status.py", "nonexistent_subcommand"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "error" in result.stderr.lower() or "invalid choice" in result.stderr.lower()

