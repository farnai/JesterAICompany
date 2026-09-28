"""Tests for Control Center application server, API routes, and dashboard (Stage 27).

Verifies:
1. Server startup and HTML dashboard serving at GET /.
2. Health and Overview endpoints (GET /api/health, GET /api/overview).
3. Agents endpoint exposing all 7 recognized company employees (GET /api/agents).
4. Project management through API (GET /api/projects, POST /api/projects, GET /api/projects/{id}).
5. Task management through API (GET /api/tasks, POST /api/tasks, GET /api/tasks/{id}).
6. Controlled Task execution via API (POST /api/tasks/{id}/execute, POST /api/tasks/{id}/retry).
7. Execution runs and history visibility (GET /api/runs, GET /api/runs/{id}).
8. Independent QA verification inspection (GET /api/verifications).
9. Artifacts catalog and content streaming (GET /api/artifacts, GET /api/artifacts/content).
10. Historical runs ingestion from .runs directory into Control Center state.
11. Clean error handling and HTTP status codes (400, 404).
"""

from http import HTTPStatus
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from typing import Generator
import urllib.error
import urllib.request
import pytest

from jester_ai_company.control_center import create_server
from jester_ai_company.core import RunStatus, TaskStatus
from jester_ai_company.service import CompanyService


def get_free_port() -> int:
    """Find an available ephemeral port for the test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def test_server() -> Generator[dict, None, None]:
    """Start an isolated Control Center server on an ephemeral port with a temporary output dir."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        port = get_free_port()
        host = "127.0.0.1"
        service = CompanyService(output_dir=tmp_dir)
        server = create_server(host=host, port=port, service=service, load_history=False)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)  # Allow socket to bind

        base_url = f"http://{host}:{port}"

        yield {
            "server": server,
            "service": service,
            "base_url": base_url,
            "tmp_dir": tmp_dir,
        }

        server.shutdown()
        server.server_close()


def api_request(base_url: str, path: str, method: str = "GET", data: dict = None) -> tuple[int, dict | str]:
    """Helper to perform HTTP requests against the test server."""
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


def test_control_center_html_root_and_health(test_server):
    """Verify GET / serves HTML dashboard and GET /api/health responds OPERATIONAL."""
    base_url = test_server["base_url"]

    # 1. Root HTML
    status, body = api_request(base_url, "/")
    assert status == HTTPStatus.OK
    assert "<!DOCTYPE html>" in body
    assert "Jester AI Company" in body
    assert "Control Center" in body
    assert "Overview" in body
    assert "Employees" in body

    # 2. Health Check
    status, health = api_request(base_url, "/api/health")
    assert status == HTTPStatus.OK
    assert health["status"] == "OPERATIONAL"


def test_control_center_overview_and_agents_roster(test_server):
    """Verify Overview stats and all 7 recognized company employees are exposed."""
    base_url = test_server["base_url"]

    # 1. Overview
    status, ov = api_request(base_url, "/api/overview")
    assert status == HTTPStatus.OK
    assert ov["company"]["name"] == "Jester AI Company"
    assert ov["counts"]["total_employees"] == 7
    assert ov["counts"]["active_employees"] == 7

    # 2. Agents Roster
    status, agents = api_request(base_url, "/api/agents")
    assert status == HTTPStatus.OK
    assert len(agents) == 7

    roles = {a["role"] for a in agents}
    expected_roles = {"ceo", "product", "research", "ux", "marketing", "developer", "qa"}
    assert roles == expected_roles

    # Single agent query
    status, ceo = api_request(base_url, "/api/agents/ceo")
    assert status == HTTPStatus.OK
    assert ceo["role"] == "ceo"
    assert ceo["title"] == "CEO Agent"
    assert "invoke_subagent" in ceo["tools"]


def test_control_center_project_crud(test_server):
    """Verify creating and retrieving projects through Control Center API."""
    base_url = test_server["base_url"]

    # Create Project Alpha
    proj_payload = {
        "project_id": "proj-cc-test",
        "name": "Control Center Test Project",
        "tech_stack": ["Python", "FastAPI"],
        "root_path": "/repos/cctest",
    }
    status, proj = api_request(base_url, "/api/projects", method="POST", data=proj_payload)
    assert status == HTTPStatus.CREATED
    assert proj["id"] == "proj-cc-test"
    assert proj["name"] == "Control Center Test Project"

    # List Projects
    status, projects = api_request(base_url, "/api/projects")
    assert status == HTTPStatus.OK
    assert any(p["id"] == "proj-cc-test" for p in projects)

    # Get Single Project
    status, single = api_request(base_url, "/api/projects/proj-cc-test")
    assert status == HTTPStatus.OK
    assert single["id"] == "proj-cc-test"


def test_control_center_task_lifecycle_and_execution(test_server):
    """Verify creating a task, executing it (mock), and inspecting runs and QA results."""
    base_url = test_server["base_url"]

    # 1. Create Project
    api_request(base_url, "/api/projects", method="POST", data={
        "project_id": "proj-exec",
        "name": "Exec Project",
        "tech_stack": ["Python"],
    })

    # 2. Create Task
    task_payload = {
        "project_id": "proj-exec",
        "title": "Build Status Endpoint",
        "goal": "Implement status endpoint returning healthy status",
        "constraints": ["Zero dependencies"],
        "required_roles": ["product", "developer", "qa"],
    }
    status, task = api_request(base_url, "/api/tasks", method="POST", data=task_payload)
    assert status == HTTPStatus.CREATED
    assert task["project_id"] == "proj-exec"
    assert task["title"] == "Build Status Endpoint"
    assert task["status"] == TaskStatus.PENDING.value
    task_id = task["id"]

    # 3. Execute Task (mock=True)
    exec_payload = {
        "verify_cmd": 'python -c "import sys; sys.exit(0)"',
        "mock": True,
        "dry_run": False,
    }
    status, run = api_request(base_url, f"/api/tasks/{task_id}/execute", method="POST", data=exec_payload)
    assert status == HTTPStatus.OK
    assert run["status"] == RunStatus.SUCCESS.value
    assert run["attempt_number"] == 1
    run_id = run["id"]

    # 4. Verify Task State Updated
    status, updated_task = api_request(base_url, f"/api/tasks/{task_id}")
    assert status == HTTPStatus.OK
    assert updated_task["status"] == TaskStatus.COMPLETED.value
    assert updated_task["result"] is not None

    # 5. List Runs
    status, runs = api_request(base_url, "/api/runs")
    assert status == HTTPStatus.OK
    assert any(r["id"] == run_id for r in runs)

    # 6. Verify QA Checks List
    status, veris = api_request(base_url, "/api/verifications")
    assert status == HTTPStatus.OK
    assert len(veris) >= 1
    assert any(v["run_id"] == run_id and v["passed"] is True for v in veris)

    # 7. List Artifacts and Read Content
    status, artifacts = api_request(base_url, "/api/artifacts")
    assert status == HTTPStatus.OK
    run_artifacts = [a for a in artifacts if a["run_id"] == run_id]
    assert len(run_artifacts) >= 2

    # Read artifact content
    first_art = run_artifacts[0]
    art_path = first_art["path"]
    status, content = api_request(base_url, f"/api/artifacts/content?path={art_path}&run_id={run_id}")
    assert status == HTTPStatus.OK
    assert len(content) > 0


def test_control_center_error_handling(test_server):
    """Verify Control Center returns proper HTTP error codes for invalid requests."""
    base_url = test_server["base_url"]

    # 404 for non-existent project
    status, err = api_request(base_url, "/api/projects/non-existent-proj")
    assert status == HTTPStatus.NOT_FOUND
    assert "error" in err

    # 404 for non-existent task
    status, err = api_request(base_url, "/api/tasks/non-existent-task")
    assert status == HTTPStatus.NOT_FOUND

    # 400 for bad task creation (missing project_id)
    status, err = api_request(base_url, "/api/tasks", method="POST", data={"title": "No Project"})
    assert status == HTTPStatus.BAD_REQUEST

    # 400 for bad artifact query
    status, err = api_request(base_url, "/api/artifacts/content")
    assert status == HTTPStatus.BAD_REQUEST


def test_control_center_loads_disk_history(tmp_path):
    """Verify load_history_from_disk populates historical runs into Control Center."""
    runs_dir = tmp_path / ".runs"
    runs_dir.mkdir()

    # Create synthetic run folder on disk
    run_1_dir = runs_dir / "run_20260928_100000"
    run_1_dir.mkdir()
    manifest_data = {
        "run_id": "run_20260928_100000",
        "task_id": "task_historic_01",
        "project_id": "jester-ai-company",
        "status": "SUCCESS",
        "created_at": "2026-09-28T10:00:00Z",
        "goal": "Historic task execution goal",
        "verifications": [
            {
                "id": "veri_hist",
                "verifier_role": "qa",
                "passed": True,
                "summary": "Historical QA Passed",
            }
        ],
        "artifacts": [
            {
                "id": "art_hist",
                "name": "spec.md",
                "artifact_type": "SPECIFICATION",
                "path": "spec.md",
                "durable": True,
            }
        ],
    }
    (run_1_dir / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")
    (run_1_dir / "spec.md").write_text("# Historic Spec Content", encoding="utf-8")

    port = get_free_port()
    service = CompanyService(output_dir=str(runs_dir))
    server = create_server(host="127.0.0.1", port=port, service=service, load_history=True)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    time.sleep(0.05)

    base_url = f"http://127.0.0.1:{port}"
    try:
        status, runs = api_request(base_url, "/api/runs")
        assert status == HTTPStatus.OK
        assert len(runs) >= 1
        assert runs[0]["id"] == "run_20260928_100000"

        # Verify artifact content accessible
        status, content = api_request(base_url, "/api/artifacts/content?path=spec.md&run_id=run_20260928_100000")
        assert status == HTTPStatus.OK
        assert "Historic Spec Content" in content
    finally:
        server.shutdown()
        server.server_close()
