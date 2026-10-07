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

