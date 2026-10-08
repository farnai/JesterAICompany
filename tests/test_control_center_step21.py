"""Tests for Step 21 Control Center API Endpoints.

Verifies:
1. Repository projects endpoint exposes registered repository with live identity verification.
2. Company runs endpoint loads and exposes durable CompanyRuns with dynamic workforce (selected vs skipped agents and reasoning).
3. Active company run retrieval.
4. Proposal and unified diff retrieval.
5. Objective creation via POST /api/company-runs creating real CompanyRun.
6. Human approval boundary via POST /api/company-runs/{run_id}/approve.
7. Human rejection boundary via POST /api/company-runs/{run_id}/reject.
"""

from http import HTTPStatus
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from typing import Generator
import urllib.request
import pytest

from jester_ai_company.control_center import create_server
from jester_ai_company.context import CompanyObjective
from jester_ai_company.orchestrator import CompanyRun, CompanyRunState
from jester_ai_company.project import Project, RepositoryPolicy, RepositoryRef
from jester_ai_company.service import CompanyService


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def cc_server() -> Generator[dict, None, None]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        port = get_free_port()
        host = "127.0.0.1"
        service = CompanyService(output_dir=tmp_dir)
        server = create_server(host=host, port=port, service=service, load_history=False)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://{host}:{port}"
        yield {
            "server": server,
            "service": service,
            "base_url": base_url,
            "tmp_dir": tmp_dir,
        }

        server.shutdown()
        server.server_close()


def api_req(base_url: str, path: str, method: str = "GET", data: dict = None) -> tuple[int, dict | str]:
    url = f"{base_url}{path}"
    req_data = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if req_data is not None else {}
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in content_type:
                return status, json.loads(raw.decode("utf-8"))
            return status, raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, raw


def test_repository_projects_endpoint(cc_server):
    base_url = cc_server["base_url"]
    status, body = api_req(base_url, "/api/repository-projects")
    assert status == HTTPStatus.OK
    assert isinstance(body, list)
    assert len(body) >= 1
    jester_proj = next((p for p in body if p.get("project_id") == "prj_jester"), None)
    assert jester_proj is not None
    assert "verification" in jester_proj
    assert jester_proj["verification"]["project_id"] == "prj_jester"


def test_company_runs_creation_and_listing(cc_server):
    base_url = cc_server["base_url"]
    # 1. Create a run via POST /api/company-runs
    payload = {
        "title": "Add defensive validation to user profile parser",
        "description": "Ensure null bytes raise ValueError",
        "project_id": "prj_jester",
        "constraints": ["orchestrate focused engineering delivery using product and developer roles"],
        "auto_run": False,
    }
    status, body = api_req(base_url, "/api/company-runs", method="POST", data=payload)
    assert status == HTTPStatus.CREATED
    run_id = body["run_id"]
    assert run_id.startswith("crun_")
    assert body["state"] == CompanyRunState.CREATED.value
    assert "selected_agents" in body
    assert "skipped_agents" in body
    assert "selection_reasoning" in body

    # 2. List runs via GET /api/company-runs
    status, runs = api_req(base_url, "/api/company-runs")
    assert status == HTTPStatus.OK
    assert len(runs) >= 1
    assert runs[0]["run_id"] == run_id

    # 3. Active run endpoint
    status, active_run = api_req(base_url, "/api/company-runs/active")
    assert status == HTTPStatus.OK
    assert active_run["run_id"] == run_id

    # 4. Get run by id
    status, single_run = api_req(base_url, f"/api/company-runs/{run_id}")
    assert status == HTTPStatus.OK
    assert single_run["run_id"] == run_id


def test_human_rejection_boundary(cc_server):
    base_url = cc_server["base_url"]
    # Create run
    _, body = api_req(
        base_url,
        "/api/company-runs",
        method="POST",
        data={"title": "Test rejection", "auto_run": False},
    )
    run_id = body["run_id"]

    # Reject run
    status, rej_body = api_req(
        base_url,
        f"/api/company-runs/{run_id}/reject",
        method="POST",
        data={"reason": "Founder rejected proposed scope"},
    )
    assert status == HTTPStatus.OK
    assert rej_body["status"] == "REJECTED"
    assert rej_body["run"]["state"] == CompanyRunState.BLOCKED.value


def test_durable_runs_and_proposals_on_production_server():
    """Verify that a server started against the real workspace .runs loads real runs and proposals."""
    workspace_root = Path(__file__).resolve().parent.parent
    service = CompanyService.create_production(repo_root=workspace_root)
    port = get_free_port()
    host = "127.0.0.1"
    server = create_server(host=host, port=port, service=service, load_history=True)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.05)

    base_url = f"http://{host}:{port}"
    try:
        # 1. Company runs should list real runs
        status, runs = api_req(base_url, "/api/company-runs")
        assert status == HTTPStatus.OK
        assert len(runs) >= 1
        run_ids = [r["run_id"] for r in runs]
        assert "crun_0e1e3955" in run_ids

        run_0e = next(r for r in runs if r["run_id"] == "crun_0e1e3955")
        assert "product" in run_0e["selected_agents"]
        assert "developer" in run_0e["selected_agents"]
        assert "qa" in run_0e["selected_agents"]
        assert "research" in run_0e["skipped_agents"]
        assert run_0e["qa_verdict"] == "PASS"

        # 2. Get proposal
        prop_id = run_0e["proposal"]["proposal_id"]
        status, prop = api_req(base_url, f"/api/proposals/{prop_id}")
        assert status == HTTPStatus.OK
        assert prop["proposal_id"] == prop_id
        assert prop["qa_verdict"] == "PASS"

        # 3. Get proposal diff
        status, diff_data = api_req(base_url, f"/api/proposals/{prop_id}/diff")
        assert status == HTTPStatus.OK
        assert "diff" in diff_data
        assert "canonical_pair_seed" in diff_data["diff"]
    finally:
        server.shutdown()
        server.server_close()


def test_company_run_lifecycle_ordering_step22c(cc_server):
    """STEP 22C REGRESSION TEST:
    Verify that auto_run executes CEO planning BEFORE start_company_run,
    and start_company_run is NEVER called while state == CREATED.
    """
    base_url = cc_server["base_url"]
    service = cc_server["service"]

    call_sequence = []
    original_plan = service.plan_company_run
    original_start = service.start_company_run
    original_boundary = service.run_company_until_boundary

    def mock_plan(run_id, timeout=None):
        r = service.get_company_run(run_id)
        call_sequence.append(("plan_company_run", r.state))
        r.state = CompanyRunState.PLAN_READY.value
        service.save_company_run(r)
        return r

    def mock_start(run_id):
        r = service.get_company_run(run_id)
        call_sequence.append(("start_company_run", r.state))
        assert r.state == CompanyRunState.PLAN_READY.value, f"Expected PLAN_READY, got {r.state}"
        r.state = CompanyRunState.RUNNING.value
        service.save_company_run(r)
        return r

    def mock_boundary(run_id, max_steps=10):
        r = service.get_company_run(run_id)
        call_sequence.append(("run_company_until_boundary", r.state))
        return r

    service.plan_company_run = mock_plan
    service.start_company_run = mock_start
    service.run_company_until_boundary = mock_boundary

    try:
        payload = {
            "title": "Validate non-negative versions",
            "project_id": "prj_jester",
            "auto_run": True,
            "sync": True,
        }
        status, body = api_req(base_url, "/api/company-runs", method="POST", data=payload)
        assert status == HTTPStatus.CREATED
        assert len(call_sequence) == 3
        assert call_sequence[0] == ("plan_company_run", CompanyRunState.CREATED.value)
        assert call_sequence[1] == ("start_company_run", CompanyRunState.PLAN_READY.value)
        assert call_sequence[2] == ("run_company_until_boundary", CompanyRunState.RUNNING.value)
    finally:
        service.plan_company_run = original_plan
        service.start_company_run = original_start
        service.run_company_until_boundary = original_boundary


def test_duplicate_concurrent_run_rejection(cc_server):
    """STEP 22C REGRESSION TEST:
    Verify that submitting an objective while another run is actively running
    is safely rejected with HTTP 409 Conflict.
    """
    base_url = cc_server["base_url"]
    service = cc_server["service"]

    # 1. Create and put run into RUNNING state
    _, body = api_req(
        base_url,
        "/api/company-runs",
        method="POST",
        data={"title": "First active run", "auto_run": False},
    )
    first_run_id = body["run_id"]
    first_run = service.get_company_run(first_run_id)
    first_run.state = CompanyRunState.RUNNING.value
    service.save_company_run(first_run)

    # 2. Attempt to create concurrent run on same project
    status, conflict_body = api_req(
        base_url,
        "/api/company-runs",
        method="POST",
        data={"title": "Concurrent conflicting run", "project_id": "prj_jester"},
    )
    assert status == HTTPStatus.CONFLICT
    assert "already actively executing" in conflict_body["error"]


def test_lifecycle_failure_handling(cc_server):
    """STEP 22C REGRESSION TEST:
    Verify that when planning fails during auto_run, the run transitions cleanly
    to FAILED with error and RUN_FAILED event instead of remaining stuck in CREATED.
    """
    base_url = cc_server["base_url"]
    service = cc_server["service"]

    original_plan = service.plan_company_run

    def failing_plan(run_id, timeout=None):
        raise RuntimeError("Simulated CEO model timeout")

    service.plan_company_run = failing_plan

    try:
        payload = {
            "title": "Failure test run",
            "project_id": "prj_jester",
            "auto_run": True,
            "sync": True,
        }
        status, body = api_req(base_url, "/api/company-runs", method="POST", data=payload)
        assert status == HTTPStatus.INTERNAL_SERVER_ERROR
        # Verify run state in service
        runs = service.list_company_runs()
        fail_run = next(r for r in runs if r.objective.title == "Failure test run")
        assert fail_run.state == CompanyRunState.FAILED.value
        assert "Simulated CEO model timeout" in fail_run.error
    finally:
        service.plan_company_run = original_plan


# ==============================================================================
# STEP 22E — RUN-SCOPED DIFF & APPROVAL SAFETY REGRESSION TESTS
# ==============================================================================

def test_step22e_run_without_proposal_has_no_diff(cc_server):
    """STEP 22E-A: A run in CREATED, PLANNING, or RUNNING state must not expose any diff or proposal."""
    base_url = cc_server["base_url"]
    service = cc_server["service"]

    # Create run without auto_run
    _, body = api_req(
        base_url,
        "/api/company-runs",
        method="POST",
        data={"title": "Run in progress", "auto_run": False},
    )
    run_id = body["run_id"]
    assert body.get("proposal") is None

    # GET /api/company-runs/{run_id}/diff should return 404 NOT_FOUND
    status, diff_body = api_req(base_url, f"/api/company-runs/{run_id}/diff")
    assert status == HTTPStatus.NOT_FOUND
    assert "has no verified proposal or patch diff" in diff_body.get("error", "")


def test_step22e_historical_proposal_isolation_and_identity_validation(cc_server):
    """STEP 22E-B & C:
    Run A has a valid proposal. Run B has no proposal.
    Selecting Run B must not expose Run A's patch.
    When querying proposal diff with mismatched run_id, API rejects with HTTP 400.
    """
    base_url = cc_server["base_url"]
    service = cc_server["service"]

    # 1. Create Run A and associate a mock proposal
    _, body_a = api_req(
        base_url,
        "/api/company-runs",
        method="POST",
        data={"title": "Run A with proposal", "auto_run": False},
    )
    run_a_id = body_a["run_id"]
    run_a = service.get_company_run(run_a_id)

    # Use a mock proposal in durable storage
    import hashlib
    from jester_ai_company.real_repo_apply import RealRepoApplyProposal, compute_proposal_sha256
    patch_a_text = "diff --git a/src/core/feature_a.py b/src/core/feature_a.py\n+feature_a_code\n"
    patch_a_sha = hashlib.sha256(patch_a_text.encode("utf-8")).hexdigest()

    prop_data = {
        "schema_version": "1.0",
        "proposal_id": "prop_test_22e_a",
        "target_repository_root": "C:/fake/repo",
        "target_branch": "main",
        "target_head_hash": "abcd1234abcd1234abcd1234abcd1234abcd1234",
        "base_commit_hash": "abcd1234abcd1234abcd1234abcd1234abcd1234",
        "code_patch_artifact_id": "art_patch_a",
        "code_patch_sha256": patch_a_sha,
        "patch_version": 1,
        "qa_report_artifact_id": "art_qa_a",
        "qa_report_sha256": "qa_sha_a",
        "qa_execution_report_artifact_id": "art_qa_exec_a",
        "qa_execution_report_sha256": "qa_exec_sha_a",
        "qa_verdict": "PASS",
        "expected_changed_files": ("src/core/feature_a.py",),
        "expected_diff_stat": {"files_changed": 1, "insertions": 5, "deletions": 0},
        "is_clean": True,
        "created_at": "2026-10-08T12:00:00Z",
        "proposal_sha256": "",
        "project_id": "prj_jester",
    }
    dummy_prop = RealRepoApplyProposal.from_dict(prop_data)
    dummy_prop_sha = compute_proposal_sha256(dummy_prop)
    prop_data["proposal_sha256"] = dummy_prop_sha
    prop_a = RealRepoApplyProposal.from_dict(prop_data)

    # Write patch and proposal into durable storage
    service.durable_storage.save_proposal(prop_a, patch_a_text, company_run_id=run_a_id)

    run_a.real_repo_apply_proposal_id = prop_a.proposal_id
    run_a.state = CompanyRunState.READY_FOR_HUMAN_APPLY.value
    service.save_company_run(run_a)

    # 2. Create Run B without proposal
    _, body_b = api_req(
        base_url,
        "/api/company-runs",
        method="POST",
        data={"title": "Run B without proposal", "auto_run": False},
    )
    run_b_id = body_b["run_id"]

    # Verify Run B has no proposal and returns 404 for diff
    status_b, diff_b = api_req(base_url, f"/api/company-runs/{run_b_id}/diff")
    assert status_b == HTTPStatus.NOT_FOUND

    # Querying proposal A's diff with run_id=Run_B MUST be rejected with HTTP 400
    status_cross, cross_body = api_req(
        base_url,
        f"/api/proposals/{prop_a.proposal_id}/diff?run_id={run_b_id}",
    )
    assert status_cross == HTTPStatus.BAD_REQUEST
    assert "Proposal identity mismatch" in cross_body.get("error", "")

    # Querying proposal A's diff with run_id=Run_A MUST succeed
    status_valid, valid_body = api_req(
        base_url,
        f"/api/proposals/{prop_a.proposal_id}/diff?run_id={run_a_id}",
    )
    assert status_valid == HTTPStatus.OK
    assert "feature_a_code" in valid_body["diff"]


def test_step22e_server_side_approval_identity_safety(cc_server):
    """STEP 22E-D: Server-side approve/apply must fail closed if proposal/grant identity is mismatched."""
    base_url = cc_server["base_url"]
    service = cc_server["service"]

    # 1. Create run without proposal and attempt approve -> 400 Bad Request
    _, body = api_req(
        base_url,
        "/api/company-runs",
        method="POST",
        data={"title": "Run for safety test", "auto_run": False},
    )
    run_id = body["run_id"]

    status, err_body = api_req(
        base_url,
        f"/api/company-runs/{run_id}/approve",
        method="POST",
        data={"approver": "Human Founder"},
    )
    assert status == HTTPStatus.BAD_REQUEST
    assert "No proposal has been generated or verified" in err_body.get("error", "")

    # 2. Attempt apply on run without grant -> 400 Bad Request
    status_apply, apply_err = api_req(
        base_url,
        f"/api/company-runs/{run_id}/apply",
        method="POST",
        data={},
    )
    assert status_apply == HTTPStatus.BAD_REQUEST
    assert "No grant has been issued" in apply_err.get("error", "")


def test_step22e_current_pending_run_preserved():
    """STEP 22E-E: The real current run 'crun_10422da9' and proposal 'prop_apply_a6f7c706' remain intact."""
    workspace_root = Path(__file__).resolve().parent.parent
    service = CompanyService.create_production(repo_root=workspace_root)
    service.load_history_from_disk()

    run = service.get_company_run("crun_10422da9")
    assert run is not None
    assert run.state in (CompanyRunState.READY_FOR_HUMAN_APPLY.value, CompanyRunState.COMPLETED.value)
    assert run.real_repo_apply_proposal_id == "prop_apply_a6f7c706"
    if run.state == CompanyRunState.COMPLETED.value:
        assert run.real_repo_apply_grant_id is not None
    else:
        assert run.real_repo_apply_grant_id is None
    assert run.objective.title == "Add defensive non-negative version validation to canonical_pair_seed"

    # Verify durable proposal exists and is untouched
    prop = service.durable_storage.load_proposal("prop_apply_a6f7c706", verify_integrity=True)
    assert prop.proposal_id == "prop_apply_a6f7c706"
    assert prop.qa_verdict == "PASS"
    assert list(prop.expected_changed_files) == [
        "backend/app/core/canonical.py",
        "tests/core/test_canonical.py",
    ]




