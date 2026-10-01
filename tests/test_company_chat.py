"""Tests for Company Chat communication layer and Control Center chat endpoints (Stage 27-E.1).

Verifies:
1. Core ChatMessage initialization and default CEO greeting.
2. CompanyService list_chat_messages and send_chat_message synthesis.
3. Control Center HTTP API GET /api/chat and POST /api/chat.
4. Input validation (400 for empty message).
5. State integration (CEO responses reflect real projects and tasks).
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
from jester_ai_company.core import ChatMessage, create_default_company
from jester_ai_company.service import CompanyService


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def chat_server() -> Generator[dict, None, None]:
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


def test_core_chat_message_and_default_greeting():
    """Verify Company core initializes with a default CEO welcome message."""
    company = create_default_company()
    assert len(company.messages) >= 1
    first_msg = company.messages[0]
    assert first_msg.sender_role == "ceo"
    assert "Founder" in first_msg.content
    assert "CEO Agent" in first_msg.sender_name


def test_service_chat_methods():
    """Verify CompanyService list_chat_messages and send_chat_message."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        msgs = service.list_chat_messages()
        assert len(msgs) >= 1

        # Owner asks about status
        res = service.send_chat_message("What is our current status?")
        assert res["user_message"]["sender_role"] == "owner"
        assert res["reply"]["sender_role"] == "ceo"
        assert "Operational report" in res["reply"]["content"]

        # Owner commissions a project
        res2 = service.send_chat_message("I need a website for my restaurant.")
        assert res2["reply"]["sender_role"] == "ceo"
        assert "Developer" in res2["reply"]["content"]
        assert "QA" in res2["reply"]["content"]


def test_api_chat_endpoints(chat_server):
    """Verify GET /api/chat and POST /api/chat."""
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
    assert "workforce roster" in res["reply"]["content"]

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
