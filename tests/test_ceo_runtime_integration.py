"""Integration smoke test for AntigravityRuntime calling the REAL CEO agent.

This test invokes the real agy CLI and live model backend.
It is explicitly separated and will be skipped during normal unit test runs
unless the environment variable RUN_REAL_INTEGRATION=1 is set.

Usage:
    $env:RUN_REAL_INTEGRATION="1"
    pytest tests/test_ceo_runtime_integration.py -v
"""

import os
from pathlib import Path
import subprocess
import sys
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jester_ai_company.runtime import AntigravityRuntime


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_INTEGRATION") != "1",
    reason="Real Antigravity integration smoke test skipped unless RUN_REAL_INTEGRATION=1",
)
def test_real_ceo_runtime_smoke():
    """Verify live end-to-end execution: Python -> AntigravityRuntime -> agy -> CEO Agent."""
    runtime = AntigravityRuntime(default_timeout=60.0)

    # 1. Capture clean git status before execution
    proc_before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(runtime.repo_root),
        capture_output=True,
        text=True,
    )
    status_before = proc_before.stdout.strip()

    # 2. Execute against real CEO agent
    prompt = "Identify yourself and state your role in one sentence. Do not invoke subagents."
    result = runtime.execute(agent="ceo", prompt=prompt)

    # 3. Assert execution outcome
    assert result.success is True, f"Execution failed with stderr: {result.stderr}"
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.duration_ms > 0
    assert result.agent == "ceo"

    # 4. Assert response content
    assert result.stdout and len(result.stdout.strip()) > 0
    stdout_lower = result.stdout.lower()
    assert "ceo" in stdout_lower
    assert any(term in stdout_lower for term in ("jester", "coordinator", "strategic", "operational"))

    # 5. Verify no repository files were created, modified, or deleted
    proc_after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(runtime.repo_root),
        capture_output=True,
        text=True,
    )
    status_after = proc_after.stdout.strip()
    assert status_after == status_before, f"Git status changed after execution:\n{status_after}"
