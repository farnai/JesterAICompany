"""Unit and integration tests for tools/company_health.py.

Verifies:
1. tools/company_health.py exists and is executable.
2. Output on stdout is valid JSON.
3. JSON contains company_name ("Jester AI Company"), status ("healthy"), and agent_count (integer).
4. Pure stdout contract (diagnostics to stderr, stdout unpolluted).
5. Location-agnostic execution (arbitrary cwd and --repo-root support).
6. Compact JSON formatting flag (--compact).
7. Fallback behavior when repository files are missing or modified.
8. Dynamic agent count calculation by scanning .agents/agents/ for agent.md definitions.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "company_health.py"

# Ensure repo root is on sys.path for direct module import tests
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.company_health import get_company_health


def test_script_exists():
    """Verify tools/company_health.py exists in repo."""
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"


def test_execution_from_repo_root():
    """Verify execution of python tools/company_health.py from repo root returns exit code 0."""
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
    """Verify company_name, status, and agent_count keys are present."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    for key in ("company_name", "status", "agent_count"):
        assert key in data, f"Missing required key '{key}' in output JSON"


def test_company_name_value():
    """Verify company_name is 'Jester AI Company'."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert data["company_name"] == "Jester AI Company"


def test_status_value():
    """Verify status is 'healthy'."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert data["status"] == "healthy"


def test_agent_count_value():
    """Verify agent_count is an integer representing registered agents."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert "agent_count" in data
    assert isinstance(data["agent_count"], int) and not isinstance(data["agent_count"], bool)
    assert data["agent_count"] == 4


def test_pure_stdout_contract():
    """Verify stderr does not pollute stdout and stdout contains only JSON."""
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
        assert data["status"] == "healthy"
        assert data["agent_count"] == 4


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
    assert data["status"] == "healthy"
    assert data["agent_count"] == 4


def test_fallback_on_missing_readme():
    """Verify graceful fallback and stderr diagnostic when README.md is missing but agents exist."""
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
        assert data["status"] == "healthy"
        assert data["agent_count"] == 1


def test_dynamic_agent_count_from_agents_dir():
    """Verify agent_count dynamically reflects registered agents from .agents/agents/ in custom repo root."""
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
        assert data["status"] == "healthy"
        assert data["agent_count"] == 3


def test_direct_python_api():
    """Verify programmatic Python API get_company_health()."""
    health = get_company_health()
    assert isinstance(health, dict)
    assert health["company_name"] == "Jester AI Company"
    assert health["status"] == "healthy"
    assert health["agent_count"] == 4


def test_count_registered_agents_direct():
    """Verify count_registered_agents() returns 4 for current repo."""
    from tools.company_health import count_registered_agents

    count = count_registered_agents(REPO_ROOT)
    assert count == 4


def test_unhealthy_when_agents_dir_missing():
    """Verify agent_count is 0 and status is 'unhealthy' when .agents/agents directory is absent."""
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
        assert data["agent_count"] == 0
        assert data["status"] == "unhealthy"


def test_unhealthy_when_agent_count_zero(monkeypatch):
    """Verify status is 'unhealthy' if agent count is 0."""
    from tools import company_health

    monkeypatch.setattr(
        company_health,
        "count_registered_agents",
        lambda root=None: 0,
    )
    health = company_health.get_company_health()
    assert health["company_name"] == "Jester AI Company"
    assert health["agent_count"] == 0
    assert health["status"] == "unhealthy"


def test_unhealthy_when_company_name_empty(monkeypatch):
    """Verify status is 'unhealthy' if company_name is empty."""
    from tools import company_health

    monkeypatch.setattr(
        company_health,
        "get_company_info",
        lambda root: {"company_name": "", "agent_count": 4, "registered_agents": []},
    )
    health = company_health.get_company_health()
    assert health["status"] == "unhealthy"

