"""Unit and integration tests for tools/company_version.py.

Verifies:
1. tools/company_version.py exists and is executable.
2. Output on stdout is valid JSON.
3. JSON contains company_name ("Jester AI Company"), version ("0.1.0"), and agent_count (integer).
4. Pure stdout contract (diagnostics/errors to stderr, stdout unpolluted).
5. Location-agnostic execution (arbitrary cwd and --repo-root support).
6. Compact JSON formatting flag (--compact).
7. Fallback behavior when repository files are missing or modified.
8. Dynamic agent count calculation by scanning .agents/agents/*/agent.md definitions.
9. Direct programmatic Python API functions.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "company_version.py"

# Ensure repo root is on sys.path for direct module import tests
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import company_version
from tools.company_version import (
    DEFAULT_COMPANY_NAME,
    VERSION,
    count_registered_agents,
    get_company_version,
)


def test_script_exists():
    """Verify tools/company_version.py exists in repo."""
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"


def test_execution_from_repo_root():
    """Verify execution of python tools/company_version.py from repo root returns exit code 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Process failed with stderr: {result.stderr}"


def test_stdout_is_valid_json():
    """Verify stdout captures valid JSON format."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)


def test_schema_keys_present():
    """Verify company_name, version, and agent_count keys are present."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    for key in ("company_name", "version", "agent_count"):
        assert key in data, f"Missing required key '{key}' in output JSON"


def test_field_types():
    """Verify data types of all schema fields."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data["company_name"], str)
    assert isinstance(data["version"], str)
    assert isinstance(data["agent_count"], int) and not isinstance(data["agent_count"], bool)


def test_company_name_value():
    """Verify company_name is 'Jester AI Company'."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["company_name"] == "Jester AI Company"


def test_version_value():
    """Verify version is '0.1.0'."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["version"] == "0.1.0"


def test_agent_count_value():
    """Verify agent_count matches number of agents in repository (4)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["agent_count"] == count_registered_agents(REPO_ROOT)
    assert data["agent_count"] >= 7


def test_pure_stdout_contract():
    """Verify stderr does not pollute stdout and stdout contains only pure JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    stripped = result.stdout.strip()
    assert stripped.startswith("{")
    assert stripped.endswith("}")


def test_execution_from_arbitrary_cwd():
    """Verify script succeeds when executed from arbitrary working directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH)],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["company_name"] == "Jester AI Company"
        assert data["version"] == "0.1.0"
        assert data["agent_count"] == count_registered_agents(REPO_ROOT)


def test_compact_flag():
    """Verify --compact outputs single-line JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--compact"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["company_name"] == "Jester AI Company"
    assert data["version"] == "0.1.0"
    assert data["agent_count"] == count_registered_agents(REPO_ROOT)


def test_repo_root_flag():
    """Verify --repo-root option explicitly specifies the target repository."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(REPO_ROOT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["company_name"] == "Jester AI Company"
    assert data["version"] == "0.1.0"
    assert data["agent_count"] == count_registered_agents(REPO_ROOT)


def test_repo_root_and_compact_combined():
    """Verify combining --repo-root and --compact works properly."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--repo-root", str(REPO_ROOT), "--compact"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["company_name"] == "Jester AI Company"
    assert data["version"] == "0.1.0"
    assert data["agent_count"] == count_registered_agents(REPO_ROOT)


def test_dynamic_agent_count_custom_repo():
    """Verify agent_count dynamically reflects registered agents from .agents/agents/*/agent.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        tmp_readme = tmp_path / "README.md"
        tmp_readme.write_text(
            "# Custom Company\n- **Name:** Custom Jester AI\n",
            encoding="utf-8",
        )
        # Create 3 valid agent definitions
        for agent_name in ("agent_a", "agent_b", "agent_c"):
            agent_dir = tmp_path / ".agents" / "agents" / agent_name
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "agent.md").write_text(f"# {agent_name}\n", encoding="utf-8")

        # Create an ignored directory without agent.md
        ignored_dir = tmp_path / ".agents" / "agents" / "not_an_agent"
        ignored_dir.mkdir(parents=True, exist_ok=True)
        (ignored_dir / "other_file.txt").write_text("not an agent", encoding="utf-8")

        # Create an ignored regular file directly in .agents/agents/
        (tmp_path / ".agents" / "agents" / "agent.md").write_text("root file", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--repo-root", tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["company_name"] == "Custom Jester AI"
        assert data["version"] == "0.1.0"
        assert data["agent_count"] == 3


def test_dynamic_agent_count_zero_when_no_agents_dir():
    """Verify agent_count is 0 when .agents/agents directory is absent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_readme = Path(tmpdir) / "README.md"
        tmp_readme.write_text("# Company\n- **Name:** No Agents Inc\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--repo-root", tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["company_name"] == "No Agents Inc"
        assert data["version"] == "0.1.0"
        assert data["agent_count"] == 0


def test_dynamic_agent_count_zero_when_empty_agents_dir():
    """Verify agent_count is 0 when .agents/agents directory exists but is empty."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / ".agents" / "agents").mkdir(parents=True, exist_ok=True)
        tmp_readme = tmp_path / "README.md"
        tmp_readme.write_text("# Company\n- **Name:** Empty Agents Inc\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--repo-root", tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["company_name"] == "Empty Agents Inc"
        assert data["version"] == "0.1.0"
        assert data["agent_count"] == 0


def test_fallback_on_missing_readme():
    """Verify graceful fallback and stderr diagnostic when README.md is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        agent_dir = Path(tmpdir) / ".agents" / "agents" / "ceo"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.md").write_text("# CEO Agent", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--repo-root", tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Warning" in result.stderr
        data = json.loads(result.stdout)
        assert data["company_name"] == "Jester AI Company"
        assert data["version"] == "0.1.0"
        assert data["agent_count"] == 1


def test_direct_python_api_get_company_version():
    """Verify programmatic Python API get_company_version()."""
    version_info = get_company_version()
    assert isinstance(version_info, dict)
    assert version_info["company_name"] == "Jester AI Company"
    assert version_info["version"] == "0.1.0"
    assert version_info["agent_count"] == count_registered_agents(REPO_ROOT)


def test_direct_python_api_count_registered_agents():
    """Verify count_registered_agents() returns registered agent count for current repo."""
    count = count_registered_agents(REPO_ROOT)
    assert count == 7


def test_constants():
    """Verify module-level constants."""
    assert VERSION == "0.1.0"
    assert DEFAULT_COMPANY_NAME == "Jester AI Company"


def test_error_handling_in_main(monkeypatch):
    """Verify main returns 1 and outputs error message to stderr on exception."""
    from tools import company_version

    def mock_get_company_version(repo_root=None):
        raise RuntimeError("Simulated failure")

    monkeypatch.setattr(company_version, "get_company_version", mock_get_company_version)
    captured_stderr = []
    monkeypatch.setattr(sys.stderr, "write", lambda s: captured_stderr.append(s))

    returncode = company_version.main([])
    assert returncode == 1
    assert any("Simulated failure" in s for s in captured_stderr)
