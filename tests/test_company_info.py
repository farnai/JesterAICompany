"""Unit and regression tests for tools/company_info.py.

Verifies all acceptance criteria defined in the product specification.
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "tools" / "company_info.py"


def test_script_exists():
    """Verify tools/company_info.py exists in repo."""
    assert SCRIPT_PATH.is_file(), f"Script not found at {SCRIPT_PATH}"


def test_execution_from_repo_root():
    """AC 1: Given repository root, when executing python tools/company_info.py, exit code is 0."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Process failed with stderr: {result.stderr}"


def test_stdout_is_valid_json():
    """AC 2: When capturing stdout, then output parses validly as JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    # Must not raise json.JSONDecodeError
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)


def test_schema_keys_present():
    """AC 3: Keys company_name, registered_agents, and status are present."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    for key in ("company_name", "registered_agents", "status"):
        assert key in data, f"Missing key '{key}' in output JSON"


def test_company_name_value():
    """AC 4: Value of company_name is 'Jester AI Company'."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    assert data["company_name"] == "Jester AI Company"


def test_registered_agents_value():
    """AC 5: registered_agents is list of strings containing defined company roles."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    roles = data["registered_agents"]
    assert isinstance(roles, list)
    assert len(roles) > 0
    assert all(isinstance(role, str) for role in roles)
    # Check baseline company roles
    expected_roles = {"CEO", "Product", "Research", "UX", "Marketing", "Developer", "QA"}
    assert expected_roles.issubset(set(roles))


def test_status_value():
    """AC 6: status is a non-empty string."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    status = data["status"]
    assert isinstance(status, str)
    assert len(status.strip()) > 0
    assert status == "STEP 2 = Company Foundation"


def test_pure_stdout_contract():
    """Verify that stderr does not pollute stdout and stdout is pure JSON."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    # stdout stripped must start with { and end with }
    assert result.stdout.strip().startswith("{")
    assert result.stdout.strip().endswith("}")


def test_execution_from_arbitrary_cwd():
    """Path resolution must succeed regardless of current working directory."""
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
        assert "CEO" in data["registered_agents"]


def test_compact_flag():
    """Verify --compact flag outputs single-line JSON without newline formatting."""
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


def test_fallback_on_missing_readme():
    """Verify graceful fallback and stderr diagnostic when README.md is absent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--repo-root", tmpdir],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Warning" in result.stderr
        data = json.loads(result.stdout)
        assert data["company_name"] == "Jester AI Company"
        assert len(data["registered_agents"]) == 7
        assert data["status"] == "STEP 2 = Company Foundation"
