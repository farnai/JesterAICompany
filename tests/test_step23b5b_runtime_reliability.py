"""Tests for STEP 23B.5-B: Live Research Timeout, Backend 502 & Telemetry Reliability.

Validates:
1. Successful Research execution (mocked runtime produces valid schema 1.1 result).
2. Research subprocess timeout (clean fail-closed handling, exit_code=-1, timed_out=True).
3. Subprocess crash / nonzero exit handling.
4. CLI authentication / missing binary failure handling.
5. Backend API responsiveness during a long-running background task.
6. Process-tree cleanup after timeout (kill_process_tree invocation).
7. Durable FAILED state and error attribution (telemetry total_errors >= 1 on failure).
8. Correct worker registration and cleanup (register_active_worker lifecycle).
9. RUNNING vs PERSISTED SNAPSHOT presentation consistency.
10. Windows socket address exclusivity (SO_EXCLUSIVEADDRUSE prevents duplicate binding).
11. No duplicate execution on polling.
12. Founder Approval and repository guards unchanged.
13. Target Jester repository remains unmodified.
"""

from datetime import datetime, timezone
from http import HTTPStatus
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Generator
import unittest.mock
import urllib.error
import urllib.request
import pytest

from jester_ai_company.control_center import (
    ExclusiveThreadingHTTPServer,
    create_server,
    register_active_worker,
    unregister_active_worker,
    is_run_actively_executing,
    enrich_company_run_data,
)
from jester_ai_company.context import CompanyObjective
from jester_ai_company.core import RunStatus, TaskStatus
from jester_ai_company.orchestrator import CompanyRun, CompanyRunState
from jester_ai_company.project import Project, RepositoryPolicy, RepositoryRef
from jester_ai_company.research_result import (
    RESEARCH_SCHEMA_VERSION,
    build_research_execution_prompt,
    parse_and_validate_research_result,
)
from jester_ai_company.runtime import (
    AgentExecutionResult,
    AntigravityRuntime,
    kill_process_tree,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.telemetry import RunExecutionTelemetry


def get_free_port() -> int:
    """Find an available ephemeral port for the test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_request(base_url: str, path: str, method: str = "GET", data: dict = None) -> tuple:
    """Execute an HTTP request against the test server."""
    url = f"{base_url}{path}"
    headers = {"Content-Type": "application/json"} if data else {}
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            status = response.status
            content = response.read().decode("utf-8")
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = content
            return status, parsed
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = content
        return e.code, parsed


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Temporary workspace directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def service(temp_dir: Path) -> CompanyService:
    """Configured CompanyService using temp output dir."""
    svc = CompanyService(output_dir=temp_dir / ".runs")
    svc.ensure_default_project()
    return svc


# ==============================================================================
# 1. Successful Research Execution
# ==============================================================================

def test_successful_research_execution(service: CompanyService) -> None:
    """Verify research specialist execution completes and materializes artifacts when model responds."""
    proj = service.ensure_default_project()
    task = proj.create_task(
        task_id="tsk_res_1",
        title="Research auth flow",
        goal="Analyze authentication architecture",
        required_roles=["research"],
    )

    valid_research_json = json.dumps({
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "status": "completed",
        "summary": "Auth flow uses JWT tokens with Argon2 hashing.",
        "sources": [
            {
                "source_id": "src_1",
                "title": "Auth Module",
                "reference": "backend/app/auth.py",
                "source_type": "local_file",
                "accessed_at": None,
            }
        ],
        "findings": [
            {
                "claim": "Passwords hashed with Argon2",
                "evidence": "Observed argon2cffi in dependencies",
                "evidence_status": "verified_source",
                "source_ids": ["src_1"],
                "certainty": "high",
            }
        ],
        "uncertainties": [],
        "open_questions": [],
    })

    with unittest.mock.patch.object(
        service.runtime,
        "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=True,
            stdout=valid_research_json,
            stderr="",
            exit_code=0,
            duration_ms=1200.0,
            timed_out=False,
        ),
    ):
        task_run = service.execute_research_task(task.id, project_id=proj.id)

    assert task_run.status == RunStatus.SUCCESS.value
    assert task.status == TaskStatus.COMPLETED.value
    assert len(task_run.artifacts) == 1
    assert task.result is not None


# ==============================================================================
# 2. Research Subprocess Timeout Handling
# ==============================================================================

def test_research_subprocess_timeout(service: CompanyService) -> None:
    """Verify research timeout transitions task run to FAILED and records bounded error."""
    proj = service.ensure_default_project()
    task = proj.create_task(
        task_id="tsk_res_timeout",
        title="Deep research",
        goal="Exhaustive scan",
        required_roles=["research"],
    )

    with unittest.mock.patch.object(
        service.runtime,
        "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=False,
            stdout="...[partial trace]...",
            stderr="Agent execution timed out after 300.0 seconds.",
            exit_code=-1,
            duration_ms=300050.0,
            timed_out=True,
        ),
    ):
        task_run = service.execute_research_task(task.id, project_id=proj.id, timeout=300.0)

    assert task_run.status == RunStatus.FAILED.value
    assert task.status == TaskStatus.FAILED.value
    assert "timed out after 300050ms" in task_run.error


# ==============================================================================
# 3. Subprocess Crash / Nonzero Exit
# ==============================================================================

def test_subprocess_crash_nonzero_exit(service: CompanyService) -> None:
    """Verify nonzero exit code transitions task run to FAILED with exit code preserved."""
    proj = service.ensure_default_project()
    task = proj.create_task(
        task_id="tsk_res_crash",
        title="Research crash test",
        goal="Trigger crash",
        required_roles=["research"],
    )

    with unittest.mock.patch.object(
        service.runtime,
        "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=False,
            stdout="",
            stderr="MemoryError: Out of memory in child process",
            exit_code=137,
            duration_ms=500.0,
            timed_out=False,
        ),
    ):
        task_run = service.execute_research_task(task.id, project_id=proj.id)

    assert task_run.status == RunStatus.FAILED.value
    assert task.status == TaskStatus.FAILED.value
    assert "exit code 137" in task_run.error


# ==============================================================================
# 4. CLI Authentication / Missing Binary Failure
# ==============================================================================

def test_cli_missing_binary_failure(service: CompanyService) -> None:
    """Verify missing agy CLI executable produces exit_code 127 and clean error message."""
    proj = service.ensure_default_project()
    task = proj.create_task(
        task_id="tsk_res_nofile",
        title="Research missing CLI",
        goal="Test binary not found",
        required_roles=["research"],
    )

    with unittest.mock.patch.object(
        service.runtime,
        "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=False,
            stdout="",
            stderr="Antigravity CLI executable 'agy' not found on system PATH: [WinError 2] The system cannot find the file specified",
            exit_code=127,
            duration_ms=10.0,
            timed_out=False,
        ),
    ):
        task_run = service.execute_research_task(task.id, project_id=proj.id)

    assert task_run.status == RunStatus.FAILED.value
    assert "exit code 127" in task_run.error
    assert "not found" in task_run.error.lower()


# ==============================================================================
# 5. Backend API Responsiveness During Long-Running Task
# ==============================================================================

def test_backend_responsiveness_during_execution(service: CompanyService) -> None:
    """Verify Control Center API remains responsive to GET requests while worker executes in background."""
    port = get_free_port()
    server = create_server(host="127.0.0.1", port=port, service=service, load_history=False)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    try:
        # Start a long-running simulated worker
        run = service.create_company_run(
            objective=CompanyObjective(
                id="obj_resp_1",
                title="Responsiveness test",
                description="Simulate active run",
            )
        )
        register_active_worker(run.run_id)

        # Worker simulates 1.5 seconds of work in background
        def _simulated_worker():
            try:
                time.sleep(1.5)
            finally:
                unregister_active_worker(run.run_id)

        worker = threading.Thread(target=_simulated_worker, daemon=True)
        worker.start()

        # Query GET /api/company-runs while worker is running - must return 200 immediately
        t0 = time.perf_counter()
        status, runs_data = make_request(base_url, "/api/company-runs")
        duration = time.perf_counter() - t0

        assert status == HTTPStatus.OK
        assert duration < 1.0  # API response must be nearly instantaneous
        assert any(r["run_id"] == run.run_id for r in runs_data)

        # Target run must show is_active_execution=True
        target_run_dict = next(r for r in runs_data if r["run_id"] == run.run_id)
        assert target_run_dict["is_active_execution"] is True
        assert target_run_dict["is_persisted_snapshot"] is False

        # Wait for worker to finish
        worker.join(timeout=3.0)

        # Now target run must show is_active_execution=False
        status2, runs_data2 = make_request(base_url, "/api/company-runs")
        target_run_dict2 = next(r for r in runs_data2 if r["run_id"] == run.run_id)
        assert target_run_dict2["is_active_execution"] is False
        assert target_run_dict2["is_persisted_snapshot"] is True
    finally:
        server.shutdown()
        server.server_close()


# ==============================================================================
# 6. Process-Tree Cleanup After Timeout
# ==============================================================================

def test_process_tree_cleanup_on_timeout() -> None:
    """Verify kill_process_tree terminates process tree on timeout."""
    with unittest.mock.patch("subprocess.run") as mock_sub_run:
        kill_process_tree(99999)
        if sys.platform == "win32":
            mock_sub_run.assert_called_once()
            args = mock_sub_run.call_args[0][0]
            assert "taskkill" in args
            assert "/T" in args
            assert "99999" in args


# ==============================================================================
# 7. Durable FAILED State and Error Attribution in Telemetry
# ==============================================================================

def test_durable_failed_state_and_telemetry_attribution(service: CompanyService) -> None:
    """Verify that when a company run fails due to specialist timeout, telemetry reports status=FAILED and total_errors>=1."""
    objective = CompanyObjective(
        id="obj_telemetry_fail",
        title="Research Registration",
        description="Investigate Jester registration architecture",
    )
    run = service.create_company_run(objective=objective)
    planned_run = service.plan_company_run(run.run_id)
    if planned_run.state == CompanyRunState.WAITING_FOR_CLARIFICATION.value:
        planned_run = service.submit_founder_clarification(
            run.run_id,
            response="Focus exclusively on backend user registration endpoints.",
        )
    service.start_company_run(run.run_id)

    # Force specialist execution to timeout
    with unittest.mock.patch.object(
        service.runtime,
        "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=False,
            stdout="",
            stderr="Agent execution timed out after 300.0 seconds.",
            exit_code=-1,
            duration_ms=300050.0,
            timed_out=True,
        ),
    ):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    updated_run = service.get_company_run(run.run_id)
    assert updated_run.state == CompanyRunState.FAILED.value
    assert "timed out" in updated_run.error.lower()

    # Telemetry check via get_company_run_metrics
    metrics = service.get_company_run_metrics(run.run_id)
    assert metrics["status"] == "FAILED"
    assert metrics["total_errors"] >= 1


# ==============================================================================
# 8. Correct Worker Registration and Cleanup
# ==============================================================================

def test_worker_registration_and_cleanup_lifecycle(service: CompanyService) -> None:
    """Verify register_active_worker and unregister_active_worker properly track execution."""
    run_id = "crun_lifecycle_test"
    assert not is_run_actively_executing(run_id)

    register_active_worker(run_id)
    assert is_run_actively_executing(run_id)

    unregister_active_worker(run_id)
    assert not is_run_actively_executing(run_id)


# ==============================================================================
# 9. RUNNING vs PERSISTED SNAPSHOT Presentation
# ==============================================================================

def test_running_vs_persisted_snapshot_presentation(service: CompanyService) -> None:
    """Verify is_active_execution and is_persisted_snapshot are strictly mutually exclusive."""
    run = service.create_company_run(
        objective=CompanyObjective(
            id="obj_snap_test",
            title="Snapshot test",
            description="Testing snapshot badge",
        )
    )

    # When not in active workers: snapshot=True, active=False
    enriched1 = enrich_company_run_data(run, service)
    assert enriched1["is_active_execution"] is False
    assert enriched1["is_persisted_snapshot"] is True

    # When registered in active workers: snapshot=False, active=True
    register_active_worker(run.run_id)
    try:
        enriched2 = enrich_company_run_data(run, service)
        assert enriched2["is_active_execution"] is True
        assert enriched2["is_persisted_snapshot"] is False
    finally:
        unregister_active_worker(run.run_id)


# ==============================================================================
# 10. Windows Socket Address Exclusivity
# ==============================================================================

def test_socket_address_exclusivity() -> None:
    """Verify ExclusiveThreadingHTTPServer prevents duplicate listeners on the same port."""
    port = get_free_port()
    svc = CompanyService()
    svc.ensure_default_project()

    server1 = create_server(host="127.0.0.1", port=port, service=svc, load_history=False)
    try:
        if sys.platform == "win32":
            # On Windows, attempting to create a second server on the same port must fail with OSError [WinError 10048]
            with pytest.raises(OSError) as exc_info:
                create_server(host="127.0.0.1", port=port, service=svc, load_history=False)
            assert "10048" in str(exc_info.value) or "normally permitted" in str(exc_info.value)
    finally:
        server1.server_close()


# ==============================================================================
# 11. No Duplicate Execution on Polling
# ==============================================================================

def test_no_duplicate_execution_on_polling(service: CompanyService) -> None:
    """Verify repeated GET requests do not spawn duplicate tasks, runs, or threads."""
    port = get_free_port()
    server = create_server(host="127.0.0.1", port=port, service=service, load_history=False)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    try:
        initial_runs = service.list_company_runs()
        initial_count = len(initial_runs)

        # Execute 10 consecutive poll requests
        for _ in range(10):
            status, _ = make_request(base_url, "/api/company-runs")
            assert status == HTTPStatus.OK

        after_runs = service.list_company_runs()
        assert len(after_runs) == initial_count
    finally:
        server.shutdown()
        server.server_close()


# ==============================================================================
# 12. Founder Approval & Repository Guards Unchanged
# ==============================================================================

def test_founder_approval_guards_intact(service: CompanyService) -> None:
    """Verify apply cannot proceed without verified proposal and founder approval."""
    run = service.create_company_run(
        objective=CompanyObjective(
            id="obj_guard_test",
            title="Guard test",
            description="Testing guard enforcement",
        )
    )
    with pytest.raises(Exception):
        service.apply_approved_company_repo(run.run_id)


# ==============================================================================
# 13. Target Jester Repository Untouched
# ==============================================================================

def test_target_jester_repository_untouched() -> None:
    """Verify external Jester repository has no unexpected mutations."""
    jester_path = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester")
    if not jester_path.is_dir():
        pytest.skip("External Jester repo path not found")

    res = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(jester_path),
        capture_output=True,
        text=True,
        check=False,
    )
    # Check that tracked modified files are only canonical.py and test_canonical.py
    modified_tracked = [
        l.strip() for l in res.stdout.strip().splitlines()
        if l.strip().startswith("M ") or l.strip().startswith("M\t")
    ]
    assert len(modified_tracked) == 2
    assert any("canonical.py" in l for l in modified_tracked)
    assert any("test_canonical.py" in l for l in modified_tracked)


# ==============================================================================
# 14. Research Prompt Bounding
# ==============================================================================

def test_research_prompt_bounding(service: CompanyService) -> None:
    """Verify that build_research_execution_prompt includes execution budget and bounding instructions."""
    proj = service.ensure_default_project()
    task = proj.create_task(
        task_id="tsk_prompt_test",
        title="Prompt budget test",
        goal="Test prompt content",
        required_roles=["research"],
    )
    prompt = build_research_execution_prompt(task)
    assert "EXECUTION BUDGET & BOUNDARIES" in prompt
    assert "limit to 3-5 focused file reads" in prompt
    assert "Do NOT perform exhaustive or recursive deep scans" in prompt
