"""Deterministic unit tests for AntigravityRuntime adapter.

Verifies:
A. Correct agy command construction
B. Absolute repository path is used
C. Requested agent is validated
D. Stdout is captured
E. Stderr is captured
F. Non-zero exit code produces success=False
G. Timeout produces a controlled structured failure
H. Arbitrary agent names are rejected
I. Subprocess invoked with shell=False
J. agy binary not found produces controlled structured failure
"""

from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jester_ai_company.runtime import (
    AgentExecutionResult,
    AntigravityRuntime,
    InvalidAgentError,
)


@pytest.fixture
def runtime():
    """Create runtime instance pointing to actual repo root."""
    return AntigravityRuntime()


def test_command_construction_and_absolute_path(runtime):
    """Verifies A, B, and I: Correct command arguments, absolute path, and shell=False."""
    cmd = runtime.build_command(agent="ceo", prompt="Test prompt for CEO")

    assert cmd[0] == "agy"
    assert cmd[1] == "--add-dir"
    repo_path = Path(cmd[2])
    assert repo_path.is_absolute()
    assert repo_path == runtime.repo_root
    assert cmd[3] == "--agent"
    assert cmd[4] == "ceo"
    assert cmd[5] == "--dangerously-skip-permissions"
    assert cmd[6] == "-p"
    assert cmd[7] == "Test prompt for CEO"


def test_agent_validation_success(runtime):
    """Verifies C: All 7 recognized agents are accepted."""
    for role in ("ceo", "product", "research", "ux", "marketing", "developer", "qa"):
        validated = runtime.validate_agent(role)
        assert validated == role
        # Case insensitivity check
        assert runtime.validate_agent(role.upper()) == role


def test_arbitrary_agent_names_rejected(runtime):
    """Verifies H: Unrecognized or malicious agent names are rejected before execution."""
    invalid_roles = [
        "hacker",
        "super_agent",
        "admin",
        "ceo; rm -rf /",
        "../../../etc/passwd",
        "",
        None,
        123,
    ]
    for invalid in invalid_roles:
        with pytest.raises(InvalidAgentError):
            runtime.validate_agent(invalid)

        with pytest.raises(InvalidAgentError):
            runtime.execute(agent=invalid, prompt="Test")


def test_missing_agent_md_rejected(tmp_path):
    """Verifies H: Recognized role name with missing agent.md is rejected."""
    # Create empty repo structure without .agents
    empty_runtime = AntigravityRuntime(repo_root=tmp_path)
    with pytest.raises(InvalidAgentError) as excinfo:
        empty_runtime.validate_agent("ceo")
    assert "definition file not found" in str(excinfo.value).lower()


def test_empty_prompt_rejected(runtime):
    """Verifies empty prompts are rejected."""
    with pytest.raises(ValueError):
        runtime.execute(agent="ceo", prompt="")

    with pytest.raises(ValueError):
        runtime.execute(agent="ceo", prompt="   \n\t  ")


@patch("subprocess.Popen")
def test_execution_success_captures_stdout(mock_popen, runtime):
    """Verifies D, F, I: Successful execution captures stdout, exit code 0, and shell=False."""
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.pid = 12345
    mock_proc.communicate.return_value = ("Hello, I am the CEO Agent.", "")
    mock_popen.return_value = mock_proc

    result = runtime.execute(agent="ceo", prompt="Identify yourself", timeout=30.0)

    assert result.success is True
    assert result.exit_code == 0
    assert result.stdout == "Hello, I am the CEO Agent."
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.agent == "ceo"
    assert result.duration_ms >= 0

    # Verify subprocess kwargs
    call_kwargs = mock_popen.call_args.kwargs
    assert call_kwargs.get("shell") is False
    assert call_kwargs.get("cwd") == str(runtime.repo_root)
    mock_proc.communicate.assert_called_once_with(timeout=30.0)


@patch("subprocess.Popen")
def test_execution_failure_captures_stderr(mock_popen, runtime):
    """Verifies E and F: Non-zero exit code captures stderr and produces success=False."""
    mock_proc = MagicMock()
    mock_proc.returncode = 2
    mock_proc.pid = 12346
    mock_proc.communicate.return_value = ("", "Error: CLI flag not recognized")
    mock_popen.return_value = mock_proc

    result = runtime.execute(agent="ceo", prompt="Test failure")

    assert result.success is False
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr == "Error: CLI flag not recognized"
    assert result.timed_out is False


@patch("jester_ai_company.runtime.kill_process_tree")
@patch("subprocess.Popen")
def test_execution_timeout_handled(mock_popen, mock_kill, runtime):
    """Verifies G: Timeout produces controlled structured failure rather than hanging."""
    mock_proc = MagicMock()
    mock_proc.pid = 12347
    mock_proc.communicate.side_effect = [
        subprocess.TimeoutExpired(
            cmd=["agy", "..."],
            timeout=5.0,
            output="Partial progress before timeout",
            stderr="",
        ),
        ("", ""),
    ]
    mock_popen.return_value = mock_proc

    result = runtime.execute(agent="ceo", prompt="Long running task", timeout=5.0)

    assert result.success is False
    assert result.exit_code == -1
    assert result.timed_out is True
    assert "Partial progress before timeout" in result.stdout
    assert "timed out after 5.0 seconds" in result.stderr
    assert result.duration_ms >= 0
    mock_kill.assert_called_once_with(12347)


@patch("subprocess.Popen")
def test_executable_not_found_handled(mock_popen, runtime):
    """Verifies J: Missing agy executable returns controlled structured result."""
    mock_popen.side_effect = FileNotFoundError("Executable not found")

    result = runtime.execute(agent="ceo", prompt="Test binary missing")

    assert result.success is False
    assert result.exit_code == 127
    assert result.timed_out is False
    assert "not found on system PATH" in result.stderr


def test_result_to_dict():
    """Verifies structured result dictionary serialization."""
    res = AgentExecutionResult(
        agent="ceo",
        success=True,
        stdout="Output",
        stderr="",
        exit_code=0,
        duration_ms=123.45,
        timed_out=False,
        command=["agy", "-p", "hi"],
    )
    d = res.to_dict()
    assert d["agent"] == "ceo"
    assert d["success"] is True
    assert d["stdout"] == "Output"
    assert d["duration_ms"] == 123.45
    assert d["command"] == ["agy", "-p", "hi"]


def test_product_agent_runtime_parity(runtime):
    """Verifies STEP 5: Product agent uses the identical AntigravityRuntime execution path as CEO."""
    # A. "product" is an allowed registered runtime agent
    validated = runtime.validate_agent("product")
    assert validated == "product"

    cmd = runtime.build_command(agent="product", prompt="Define product requirements")
    assert cmd[0] == "agy"
    assert cmd[3] == "--agent"
    assert cmd[4] == "product"
    assert cmd[7] == "Define product requirements"

    # B. unknown agent remains rejected
    with pytest.raises(InvalidAgentError):
        runtime.validate_agent("unknown_product_lead")

    # C. Mock execution proves identical AgentExecutionResult structure without separate runtime class
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.pid = 12348
    mock_proc.communicate.return_value = ("Product requirements document", "")
    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
        res = runtime.execute(agent="product", prompt="Define product requirements")
        assert res.agent == "product"
        assert res.success is True
        assert res.stdout == "Product requirements document"
        assert res.exit_code == 0
        assert res.duration_ms >= 0
        mock_popen.assert_called_once()
