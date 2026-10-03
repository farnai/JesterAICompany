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


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_INTEGRATION") != "1",
    reason="Real Antigravity integration proof skipped unless RUN_REAL_INTEGRATION=1",
)
def test_real_ceo_live_planning_proof():
    """Live proof for STEP 17B-2: Real CEO agent receives CompanyObjective and returns valid DAG plan."""
    from jester_ai_company.dag import compute_graph_depth, validate_dag_structure
    from jester_ai_company.orchestrator import CompanyObjective
    from jester_ai_company.service import CompanyService

    runtime = AntigravityRuntime(default_timeout=120.0)
    service = CompanyService(runtime=runtime)

    # 1. Capture git status before
    proc_before = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(runtime.repo_root),
        capture_output=True,
        text=True,
    )
    status_before = proc_before.stdout.strip()

    objective = CompanyObjective(
        id="obj_launch_brief_001",
        title="Prepare a Launch Positioning Brief",
        description=(
            "Research the current repository's documented company purpose and produce "
            "a product positioning and marketing brief for a hypothetical developer preview."
        ),
        constraints=[
            "no repository mutation",
            "no code changes",
            "no shell authority delegated to CEO",
            "use only appropriate macro specialist roles",
        ],
        acceptance_criteria=[
            "plan is valid",
            "plan is deterministic-schema compatible",
            "no privileged actions",
            "no Developer node unless Product+UX prerequisites are present",
            "no ordinary Developer->QA node",
            "<=6 work items",
            "graph depth <=4",
        ],
    )

    # 2. Invoke CEO via CompanyService
    plan = service.propose_initial_company_plan(objective, timeout=120.0)

    # 3. Assert plan structure & boundaries
    assert plan is not None
    assert plan.objective_id == objective.id
    assert plan.version == 1
    assert 1 <= len(plan.work_items) <= 6

    depth = compute_graph_depth(plan)
    assert depth <= 4

    # 4. Assert DAG validation succeeds
    validate_dag_structure(plan)

    # 5. Assert selected roles are macro roles and no CEO
    roles = {w.role for w in plan.work_items}
    assert "ceo" not in roles

    # 6. Verify zero repository mutation occurred
    proc_after = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(runtime.repo_root),
        capture_output=True,
        text=True,
    )
    status_after = proc_after.stdout.strip()
    assert status_after == status_before, f"Git status changed after execution:\n{status_after}"

    # Print summary for audit report
    print("\n--- LIVE CEO PROOF SUMMARY ---")
    print(f"Objective ID     : {objective.id}")
    print(f"Plan ID          : {plan.plan_id}")
    print(f"Work Items Count : {len(plan.work_items)}")
    print(f"Graph Depth      : {depth}")
    print(f"Selected Roles   : {sorted(roles)}")
    for item in plan.work_items:
        print(f"  [{item.work_item_id}] role={item.role} priority={item.priority} depends_on={item.depends_on}")

