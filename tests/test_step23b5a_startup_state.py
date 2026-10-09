"""Tests for STEP 23B.5-A: Startup State Investigation & Safe Live-Test Invariants.

Verifies:
1. Opening Control Center with no active runs initializes cleanly.
2. Opening Control Center with historical completed runs marks them as persisted snapshots (is_active_execution=False).
3. Opening Control Center with persisted interrupted runs (e.g. CREATED or RUNNING on disk) reports is_active_execution=False.
4. Page refresh and repeated polling GET requests produce zero execution side effects.
5. Zero model/runtime calls are triggered by any GET request or polling cycle.
6. Accurate distinction between active and historical/persisted execution status.
7. No implicit mutations or touches occur in the target repository.
8. Founder Approval gates and Engineering QA safeguards remain strictly intact.
"""

from datetime import datetime, timezone
from http import HTTPStatus
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from typing import Generator
import unittest.mock
import urllib.error
import urllib.request
import pytest

from jester_ai_company.control_center import (
    create_server,
    register_active_worker,
    unregister_active_worker,
    is_run_actively_executing,
)
from jester_ai_company.context import CompanyObjective
from jester_ai_company.orchestrator import CompanyRun, CompanyRunState
from jester_ai_company.project import Project, RepositoryPolicy, RepositoryRef
from jester_ai_company.service import CompanyService


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
    except urllib.error.HTTPError as exc:
        err_content = exc.read().decode("utf-8")
        try:
            parsed = json.loads(err_content)
        except Exception:
            parsed = err_content
        return exc.code, parsed


class TestStartupStateAndInvariants:
    """Test suite covering startup state, historical restoration, and zero-side-effect safety."""

    def test_requirement_1_opening_control_center_with_no_active_runs(self, tmp_path: Path):
        """Opening Control Center with no existing runs returns clean empty state."""
        port = get_free_port()
        service = CompanyService(output_dir=str(tmp_path / ".runs"))
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=False)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # 1. Overview endpoint returns cleanly
            status, overview = make_request(base_url, "/api/overview")
            assert status == HTTPStatus.OK
            assert overview["company"]["name"] == "Jester AI Company"
            assert overview["counts"]["total_runs"] == 0
            assert overview["counts"]["in_progress_tasks"] == 0
            assert overview["counts"]["completed_tasks"] == 0

            # 2. Company runs endpoint returns empty list
            status, runs_data = make_request(base_url, "/api/company-runs")
            assert status == HTTPStatus.OK
            assert isinstance(runs_data, list)
            assert len(runs_data) == 0
        finally:
            server.shutdown()
            server.server_close()

    def test_requirement_2_opening_control_center_with_historical_completed_runs(self, tmp_path: Path):
        """Historical completed runs on disk are loaded with is_persisted_snapshot=True and is_active_execution=False."""
        runs_dir = tmp_path / ".runs"
        cruns_dir = runs_dir / "company_runs"
        cruns_dir.mkdir(parents=True, exist_ok=True)

        # Write a completed run to disk
        completed_run_data = {
            "run_id": "crun_hist_completed",
            "state": "COMPLETED",
            "objective": {
                "id": "obj_test",
                "title": "Historical Completed Objective",
                "description": "Already completed task",
                "constraints": [],
                "acceptance_criteria": [],
            },
            "created_at": "2026-10-08T10:00:00+00:00",
            "completed_at": "2026-10-08T10:05:00+00:00",
            "project_id": "prj_jester",
            "selected_agents": ["developer", "ux_specialist"],
            "ceo_invocation_count": 2,
            "specialist_invocation_count": 3,
            "events": [],
            "error": None,
        }
        (cruns_dir / "crun_hist_completed.json").write_text(
            json.dumps(completed_run_data), encoding="utf-8"
        )

        port = get_free_port()
        service = CompanyService(output_dir=str(runs_dir))
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            status, runs_data = make_request(base_url, "/api/company-runs")
            assert status == HTTPStatus.OK
            assert isinstance(runs_data, list)
            assert len(runs_data) == 1
            run_summary = runs_data[0]
            assert run_summary["run_id"] == "crun_hist_completed"
            assert run_summary["state"] == "COMPLETED"
            assert run_summary["is_active_execution"] is False
            assert run_summary["is_persisted_snapshot"] is True

            # Direct run detail endpoint
            status, detail = make_request(base_url, "/api/company-runs/crun_hist_completed")
            assert status == HTTPStatus.OK
            assert detail["run_id"] == "crun_hist_completed"
            assert detail["is_active_execution"] is False
            assert detail["is_persisted_snapshot"] is True
            assert detail["ceo_invocation_count"] == 2
            assert detail["specialist_invocation_count"] == 3
        finally:
            server.shutdown()
            server.server_close()

    def test_requirement_3_opening_control_center_with_persisted_interrupted_runs(self, tmp_path: Path):
        """Runs persisted in CREATED or RUNNING on disk without worker threads are NOT active executions."""
        runs_dir = tmp_path / ".runs"
        cruns_dir = runs_dir / "company_runs"
        cruns_dir.mkdir(parents=True, exist_ok=True)

        # Write an interrupted run in CREATED state
        created_run_data = {
            "run_id": "crun_interrupted_created",
            "state": "CREATED",
            "objective": {
                "id": "obj_reg",
                "title": "Fix registration on Jester",
                "description": "Pending run from interrupted test",
            },
            "created_at": "2026-10-09T11:45:00+00:00",
            "project_id": "prj_jester",
            "selected_agents": ["developer", "ux_specialist"],
            "ceo_invocation_count": 0,
            "specialist_invocation_count": 0,
            "events": [],
            "error": None,
        }
        (cruns_dir / "crun_interrupted_created.json").write_text(
            json.dumps(created_run_data), encoding="utf-8"
        )

        # Write an interrupted run in RUNNING state
        running_run_data = {
            "run_id": "crun_interrupted_running",
            "state": "RUNNING",
            "objective": {
                "id": "obj_run",
                "title": "Running Task Interrupted By Restart",
                "description": "Interrupted execution during host reboot",
            },
            "created_at": "2026-10-09T11:50:00+00:00",
            "project_id": "prj_jester",
            "selected_agents": ["developer"],
            "ceo_invocation_count": 1,
            "specialist_invocation_count": 0,
            "events": [],
            "error": None,
        }
        (cruns_dir / "crun_interrupted_running.json").write_text(
            json.dumps(running_run_data), encoding="utf-8"
        )

        port = get_free_port()
        service = CompanyService(output_dir=str(runs_dir))
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # Check created run
            status, detail_created = make_request(base_url, "/api/company-runs/crun_interrupted_created")
            assert status == HTTPStatus.OK
            assert detail_created["state"] == "CREATED"
            assert detail_created["is_active_execution"] is False
            assert detail_created["is_persisted_snapshot"] is True
            assert detail_created["ceo_invocation_count"] == 0

            # Check running run
            status, detail_running = make_request(base_url, "/api/company-runs/crun_interrupted_running")
            assert status == HTTPStatus.OK
            assert detail_running["state"] == "RUNNING"
            assert detail_running["is_active_execution"] is False
            assert detail_running["is_persisted_snapshot"] is True
        finally:
            server.shutdown()
            server.server_close()

    def test_requirement_4_page_refresh_without_execution_side_effects(self, tmp_path: Path):
        """Repeated GET requests and dashboard refreshing produce zero state changes or side effects."""
        runs_dir = tmp_path / ".runs"
        cruns_dir = runs_dir / "company_runs"
        cruns_dir.mkdir(parents=True, exist_ok=True)

        run_data = {
            "run_id": "crun_refresh_test",
            "state": "CREATED",
            "objective": {
                "id": "obj_ref",
                "title": "Refresh Safety Check",
                "description": "Ensures read queries are idempotent",
            },
            "created_at": "2026-10-09T12:00:00+00:00",
            "events": [{"event_type": "RUN_CREATED", "timestamp": "2026-10-09T12:00:00+00:00"}],
            "error": None,
        }
        run_file = cruns_dir / "crun_refresh_test.json"
        run_file.write_text(json.dumps(run_data), encoding="utf-8")
        initial_file_content = run_file.read_text(encoding="utf-8")

        port = get_free_port()
        service = CompanyService(output_dir=str(runs_dir))
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # Simulate 15 polling/refresh cycles across standard UI endpoints
            for _ in range(15):
                make_request(base_url, "/")
                make_request(base_url, "/api/overview")
                make_request(base_url, "/api/company-runs")
                make_request(base_url, "/api/company-runs/crun_refresh_test")
                make_request(base_url, "/api/projects")

            # Verify run state in memory and on disk is completely untouched
            run_in_memory = service.get_company_run("crun_refresh_test")
            assert run_in_memory.state == "CREATED"
            assert len(run_in_memory.events) == 1

            # File on disk was not modified or overwritten
            assert run_file.read_text(encoding="utf-8") == initial_file_content
        finally:
            server.shutdown()
            server.server_close()

    def test_requirement_5_no_model_calls_triggered_by_get_requests_or_polling(self, tmp_path: Path):
        """Zero model adapter calls or runtime executions are triggered by any GET request."""
        runs_dir = tmp_path / ".runs"
        cruns_dir = runs_dir / "company_runs"
        cruns_dir.mkdir(parents=True, exist_ok=True)

        run_data = {
            "run_id": "crun_no_model_test",
            "state": "CREATED",
            "objective": {
                "id": "obj_model",
                "title": "No Model Calls Check",
                "description": "Validates zero inference on polling",
            },
            "created_at": "2026-10-09T12:00:00+00:00",
            "events": [],
            "error": None,
        }
        (cruns_dir / "crun_no_model_test.json").write_text(json.dumps(run_data), encoding="utf-8")

        port = get_free_port()
        mock_runtime = unittest.mock.MagicMock()
        mock_runtime.execute.return_value = {"content": "should never be called"}

        service = CompanyService(output_dir=str(runs_dir), runtime=mock_runtime)
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # Poll all endpoints
            endpoints = [
                "/",
                "/api/health",
                "/api/overview",
                "/api/company-runs",
                "/api/company-runs/crun_no_model_test",
                "/api/company-runs/crun_no_model_test/metrics",
                "/api/projects",
                "/api/agents",
                "/api/verifications",
            ]
            for ep in endpoints:
                status, _ = make_request(base_url, ep)
                assert status == HTTPStatus.OK

            # Invariant: Runtime execute was NEVER invoked
            assert mock_runtime.execute.call_count == 0
        finally:
            server.shutdown()
            server.server_close()

    def test_requirement_6_accurate_active_vs_historical_status(self, tmp_path: Path):
        """Active execution flag transitions correctly based on registered worker threads."""
        runs_dir = tmp_path / ".runs"
        cruns_dir = runs_dir / "company_runs"
        cruns_dir.mkdir(parents=True, exist_ok=True)

        run_id = "crun_lifecycle_status_test"
        run_data = {
            "run_id": run_id,
            "state": "RUNNING",
            "objective": {
                "id": "obj_live",
                "title": "Worker Tracking Test",
                "description": "Verifies dynamic worker flag updates",
            },
            "created_at": "2026-10-09T12:00:00+00:00",
            "events": [],
            "error": None,
        }
        (cruns_dir / f"{run_id}.json").write_text(json.dumps(run_data), encoding="utf-8")

        port = get_free_port()
        service = CompanyService(output_dir=str(runs_dir))
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # 1. Initially no worker is attached
            assert not is_run_actively_executing(run_id)
            status, detail = make_request(base_url, f"/api/company-runs/{run_id}")
            assert status == HTTPStatus.OK
            assert detail["is_active_execution"] is False
            assert detail["is_persisted_snapshot"] is True

            # 2. Worker registers
            register_active_worker(run_id)
            assert is_run_actively_executing(run_id)
            status, detail = make_request(base_url, f"/api/company-runs/{run_id}")
            assert status == HTTPStatus.OK
            assert detail["is_active_execution"] is True
            assert detail["is_persisted_snapshot"] is False

            # 3. Worker terminates and unregisters
            unregister_active_worker(run_id)
            assert not is_run_actively_executing(run_id)
            status, detail = make_request(base_url, f"/api/company-runs/{run_id}")
            assert status == HTTPStatus.OK
            assert detail["is_active_execution"] is False
            assert detail["is_persisted_snapshot"] is True
        finally:
            unregister_active_worker(run_id)
            server.shutdown()
            server.server_close()

    def test_requirement_7_no_implicit_target_repository_mutations(self, tmp_path: Path):
        """Startup and read-only polling never modify, create, or delete any files in the target repo."""
        # Initialize an isolated dummy git target repo
        target_repo = tmp_path / "target_repo"
        target_repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(target_repo), check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(target_repo), check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(target_repo), check=True)

        sample_file = target_repo / "main.py"
        sample_file.write_text("print('hello target')\n", encoding="utf-8")
        subprocess.run(["git", "add", "main.py"], cwd=str(target_repo), check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(target_repo), check=True)

        # Record clean working tree state
        initial_status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(target_repo),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert initial_status.strip() == ""
        initial_mtime = sample_file.stat().st_mtime_ns

        # Setup CompanyService with a registered project pointing to target_repo
        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir))
        proj = Project(
            project_id="prj_target_test",
            name="Target Test Project",
            description="Testing read-only repository invariants",
            repository=RepositoryRef(
                repository_id="repo_target_test",
                root_path=str(target_repo),
                target_branch="master",
            ),
            policy=RepositoryPolicy(),
        )
        service.register_repository_project(proj)

        port = get_free_port()
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=False)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # Poll projects, overview, runs
            for _ in range(5):
                make_request(base_url, "/api/projects")
                make_request(base_url, "/api/repository-projects/prj_target_test")
                make_request(base_url, "/api/overview")

            # Check target repo state: strictly pristine
            final_status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(target_repo),
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            assert final_status.strip() == ""
            assert sample_file.stat().st_mtime_ns == initial_mtime
            assert sample_file.read_text(encoding="utf-8") == "print('hello target')\n"
        finally:
            server.shutdown()
            server.server_close()

    def test_requirement_8_founder_approval_and_qa_safeguards_intact(self, tmp_path: Path):
        """Historical runs waiting for founder apply cannot be applied without explicit human authorization."""
        runs_dir = tmp_path / ".runs"
        cruns_dir = runs_dir / "company_runs"
        cruns_dir.mkdir(parents=True, exist_ok=True)

        run_id = "crun_approval_safeguard"
        run_data = {
            "run_id": run_id,
            "state": "READY_FOR_HUMAN_APPLY",
            "objective": {
                "id": "obj_app",
                "title": "Human Gate Test",
                "description": "Verifies human founder gate cannot be bypassed",
            },
            "created_at": "2026-10-09T12:00:00+00:00",
            "real_repo_apply_proposal_id": "prop_test_123",
            "events": [],
            "error": None,
        }
        (cruns_dir / f"{run_id}.json").write_text(json.dumps(run_data), encoding="utf-8")

        port = get_free_port()
        service = CompanyService(output_dir=str(runs_dir))
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://127.0.0.1:{port}"
        try:
            # Verify status is loaded as READY_FOR_HUMAN_APPLY and persisted snapshot
            status, detail = make_request(base_url, f"/api/company-runs/{run_id}")
            assert status == HTTPStatus.OK
            assert detail["state"] == "READY_FOR_HUMAN_APPLY"
            assert detail["is_active_execution"] is False

            # Attempting apply without founder grant or approval MUST fail with error
            apply_status, apply_res = make_request(
                base_url,
                f"/api/company-runs/{run_id}/apply",
                method="POST",
                data={"proposal_id": "prop_test_123"},
            )
            # Must be rejected because founder grant has not been issued
            assert apply_status in (HTTPStatus.BAD_REQUEST, HTTPStatus.INTERNAL_SERVER_ERROR)
            assert "grant" in str(apply_res).lower() or "approval" in str(apply_res).lower() or "error" in str(apply_res).lower()

            # The run state was NOT modified to APPLYING or COMPLETED
            status, detail_after = make_request(base_url, f"/api/company-runs/{run_id}")
            assert detail_after["state"] == "READY_FOR_HUMAN_APPLY"
        finally:
            server.shutdown()
            server.server_close()
