"""Tests for Company Chat communication layer and Control Center chat endpoints (STEP 3).

Verifies:
1. Core ChatMessage initialization and default CEO greeting.
2. Founder message is passed to CEO runtime (Verification A).
3. Agent is always "ceo" (Verification B).
4. Successful stdout becomes CEO chat response (Verification C).
5. Runtime failure is handled safely without crashing (Verification D).
6. Timeout is handled safely (Verification E).
7. Empty runtime output is handled safely (Verification F).
8. No Task is created on chat messages (Verification G).
9. No TaskRun is created on chat messages (Verification H).
10. No specialist execution occurs (Verification I).
11. Control Center HTTP API GET /api/chat and POST /api/chat.
12. Input validation (400 for empty message).
"""

from http import HTTPStatus
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
from typing import Generator
from unittest.mock import MagicMock
import urllib.error
import urllib.request
import pytest

from jester_ai_company.control_center import create_server
from jester_ai_company.core import ChatMessage, Task, TaskRun, create_default_company
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_mock_runtime(
    stdout: str = "Hello Founder, CEO standing by.",
    stderr: str = "",
    success: bool = True,
    exit_code: int = 0,
    timed_out: bool = False,
    duration_ms: float = 120.0,
) -> MagicMock:
    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.return_value = AgentExecutionResult(
        agent="ceo",
        success=success,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        timed_out=timed_out,
        command=["agy", "--agent", "ceo", "-p", "..."],
    )
    return runtime


@pytest.fixture
def chat_server() -> Generator[dict, None, None]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        port = get_free_port()
        host = "127.0.0.1"
        mock_runtime = make_mock_runtime(stdout="Operational report: all systems running.")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        server = create_server(host=host, port=port, service=service, load_history=False)

        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        time.sleep(0.05)

        base_url = f"http://{host}:{port}"

        yield {
            "server": server,
            "service": service,
            "mock_runtime": mock_runtime,
            "base_url": base_url,
        }

        server.shutdown()
        server.server_close()


def api_request(base_url: str, path: str, method: str = "GET", data: dict = None) -> tuple[int, dict | str]:
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


# -----------------------------------------------------------------------------
# Base Core & Greeting
# -----------------------------------------------------------------------------

def test_core_chat_message_and_default_greeting():
    """Verify Company core initializes with a default CEO welcome message."""
    company = create_default_company()
    assert len(company.messages) >= 1
    first_msg = company.messages[0]
    assert first_msg.sender_role == "ceo"
    assert "Founder" in first_msg.content
    assert "CEO Agent" in first_msg.sender_name


# -----------------------------------------------------------------------------
# Step 3 Deterministic Verifications (A through I)
# -----------------------------------------------------------------------------

def test_chat_founder_message_passed_to_ceo_runtime():
    """Verification A & B: Founder message is passed to CEO runtime, agent is always 'ceo'."""
    mock_runtime = make_mock_runtime(stdout="Understood, Founder. Aligning company objectives.")
    service = CompanyService(runtime=mock_runtime)

    founder_message = "Identify high-priority objectives for this quarter."
    res = service.send_chat_message(founder_message, sender_role="owner")

    mock_runtime.execute.assert_called_once()
    called_kwargs = mock_runtime.execute.call_args.kwargs
    assert called_kwargs["agent"] == "ceo"
    assert called_kwargs["prompt"] == founder_message
    assert res["user_message"]["content"] == founder_message
    assert res["reply"]["sender_role"] == "ceo"
    assert res["reply"]["content"] == "Understood, Founder. Aligning company objectives."


def test_chat_agent_is_always_ceo_even_if_extra_params_provided():
    """Verification B: Chat endpoint agent is strictly hardcoded to 'ceo'."""
    mock_runtime = make_mock_runtime(stdout="CEO guidance.")
    service = CompanyService(runtime=mock_runtime)

    service.send_chat_message(
        "Build a restaurant website.",
        sender_role="owner",
        project_id="proj_1",
        task_id="task_1",
    )

    mock_runtime.execute.assert_called_once()
    assert mock_runtime.execute.call_args.kwargs["agent"] == "ceo"


def test_chat_successful_stdout_becomes_ceo_response():
    """Verification C: Successful stdout becomes the CEO chat response."""
    ceo_output = "I am the CEO. I manage company strategy and team alignment."
    mock_runtime = make_mock_runtime(stdout=f"  {ceo_output}\n\n")
    service = CompanyService(runtime=mock_runtime)

    res = service.send_chat_message("Who are you?", sender_role="owner")
    assert res["reply"]["content"] == ceo_output


def test_chat_runtime_failure_handled_safely():
    """Verification D: Runtime failure (exit code != 0) returns controlled message without throwing."""
    mock_runtime = make_mock_runtime(
        success=False,
        exit_code=1,
        stdout="",
        stderr="Internal runtime crash in agy engine",
    )
    service = CompanyService(runtime=mock_runtime)

    res = service.send_chat_message("Status report please", sender_role="owner")
    assert res["reply"] is not None
    assert res["reply"]["sender_role"] == "ceo"
    # Must NOT expose raw stderr, filesystem paths, or crash
    assert "agy engine" not in res["reply"]["content"]
    assert "apologize" in res["reply"]["content"].lower()
    assert "internal issue" in res["reply"]["content"].lower()


def test_chat_runtime_timeout_handled_safely():
    """Verification E: Timeout returns controlled message without throwing."""
    mock_runtime = make_mock_runtime(
        success=False,
        timed_out=True,
        exit_code=-1,
        stdout="",
        stderr="Agent execution timed out after 60.0 seconds.",
    )
    service = CompanyService(runtime=mock_runtime)

    res = service.send_chat_message("Execute heavy computation", sender_role="owner")
    assert res["reply"] is not None
    assert res["reply"]["sender_role"] == "ceo"
    assert "timed out" in res["reply"]["content"].lower()
    assert "60.0" not in res["reply"]["content"]


def test_chat_empty_runtime_output_handled_safely():
    """Verification F: Empty runtime output returns controlled message."""
    mock_runtime = make_mock_runtime(
        success=True,
        exit_code=0,
        stdout="    \n   ",
    )
    service = CompanyService(runtime=mock_runtime)

    res = service.send_chat_message("Hello", sender_role="owner")
    assert res["reply"] is not None
    assert res["reply"]["sender_role"] == "ceo"
    assert "unable to generate a response" in res["reply"]["content"].lower()


def test_chat_missing_executable_handled_safely():
    """Verification D (missing agy executable): returns controlled message."""
    mock_runtime = make_mock_runtime(
        success=False,
        exit_code=127,
        stdout="",
        stderr="Antigravity CLI executable 'agy' not found on system PATH.",
    )
    service = CompanyService(runtime=mock_runtime)

    res = service.send_chat_message("Hello", sender_role="owner")
    assert res["reply"] is not None
    assert res["reply"]["sender_role"] == "ceo"
    assert "unavailable on this system" in res["reply"]["content"].lower()


def test_chat_unexpected_exception_handled_safely():
    """Verification D (unexpected exception in runtime): returns controlled message without crashing."""
    mock_runtime = MagicMock(spec=AntigravityRuntime)
    mock_runtime.execute.side_effect = RuntimeError("Hardware failure")
    service = CompanyService(runtime=mock_runtime)

    res = service.send_chat_message("Hello", sender_role="owner")
    assert res["reply"] is not None
    assert res["reply"]["sender_role"] == "ceo"
    assert "Hardware failure" not in res["reply"]["content"]
    assert "unexpected error" in res["reply"]["content"].lower()


def test_chat_no_task_side_effects_on_restaurant_prompt():
    """Verification G, H, I: Prompts like 'restaurant' or 'execute' do NOT create tasks, runs, or invoke specialists."""
    mock_runtime = make_mock_runtime(stdout="Understood, I will keep that in mind.")
    service = CompanyService(runtime=mock_runtime)
    project = service.ensure_default_project()
    initial_tasks_count = len(project.tasks)

    # 1. Commission prompt that previously triggered task creation
    res1 = service.send_chat_message("I need a website for my restaurant.", sender_role="owner")
    assert len(project.tasks) == initial_tasks_count, "Verification G: No Task must be created from chat"

    # 2. Execute prompt that previously triggered task execution
    res2 = service.send_chat_message("Execute task now and run QA", sender_role="owner")
    assert len(project.tasks) == initial_tasks_count

    # Check total runs in executor
    all_runs = []
    for t in project.tasks.values():
        all_runs.extend(service.list_runs(t.id))
    assert len(all_runs) == 0, "Verification H: No TaskRun must be created from chat"

    # Verify runtime was only invoked for agent="ceo"
    for call in mock_runtime.execute.call_args_list:
        assert call.kwargs["agent"] == "ceo", "Verification I: No specialist execution occurs"


# -----------------------------------------------------------------------------
# Control Center API Chat Endpoints
# -----------------------------------------------------------------------------

def test_api_chat_endpoints(chat_server):
    """Verify GET /api/chat and POST /api/chat via HTTP server."""
    base_url = chat_server["base_url"]

    # 1. GET /api/chat
    status, body = api_request(base_url, "/api/chat")
    assert status == HTTPStatus.OK
    assert "messages" in body
    assert len(body["messages"]) >= 1

    # 2. POST /api/chat valid message
    post_data = {
        "content": "Can we check who is working on the team?",
        "sender_role": "owner",
    }
    status, res = api_request(base_url, "/api/chat", method="POST", data=post_data)
    assert status == HTTPStatus.OK
    assert res["user_message"]["content"] == post_data["content"]
    assert res["reply"]["sender_role"] == "ceo"
    assert "Operational report" in res["reply"]["content"]

    # 3. Verify messages list updated
    status, body_after = api_request(base_url, "/api/chat")
    assert status == HTTPStatus.OK
    assert len(body_after["messages"]) >= 3


def test_api_chat_validation_error(chat_server):
    """Verify POST /api/chat rejects empty content with 400."""
    base_url = chat_server["base_url"]
    status, err = api_request(base_url, "/api/chat", method="POST", data={"content": "  "})
    assert status == HTTPStatus.BAD_REQUEST
    assert "required" in err["error"].lower()
