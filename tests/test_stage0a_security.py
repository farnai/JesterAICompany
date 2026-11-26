"""Stage 0A Negative Security & Legitimate Local Access Regression Tests.

Strictly isolated in temporary directories (zero mutations to workspace .runs/ or real repos).
Independently verifies:
- DEF-001: Arbitrary HTTP verify_cmd disabled, no wildcard CORS (*), Host/Origin/Fetch-Metadata
  validation, local ephemeral session auth protecting sensitive reads + all mutations,
  and independent CSRF resistance.
- DEF-002: Static file Path Traversal blocked (/assets/, /portraits/, percent-encoded, backslash).
- DEF-003: /api/artifacts/content strictly confined to output_dir (no repo_root escape or .env read).
- DEF-004: Immediate fail-closed containment on HTTP /approve and /apply (including non-empty
  caller-supplied founder_approval_id) + programmatic rejection of synthetic approval prefixes.
- Legitimate same-origin browser workflow (GET / cookie + meta CSRF token -> reads & mutations).
"""

from __future__ import annotations

import hashlib
from http import HTTPStatus
import http.client
from http.cookies import SimpleCookie
import json
from pathlib import Path
import re
import socket
import tempfile
import threading
import time
from typing import Any, Dict, Generator, Optional, Tuple
import pytest

from jester_ai_company.control_center import (
    AUTH_HEADER_NAME,
    CSRF_HEADER_NAME,
    FRONTEND_DIST_DIR,
    SESSION_COOKIE_NAME,
    create_server,
)
from jester_ai_company.orchestrator import CompanyRunState
from jester_ai_company.real_repo_apply import (
    MissingApprovalError,
    RealRepoApplyProposal,
    compute_proposal_sha256,
    derive_real_repo_apply_grant,
)
from jester_ai_company.service import CompanyService


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _raw_http(
    port: int,
    method: str,
    path: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
) -> Tuple[int, Dict[str, str], str]:
    """Low-level HTTP request preserving raw URL path (no client-side '..' normalization)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        hdrs = dict(headers or {})
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, resp_headers, raw
    finally:
        conn.close()


@pytest.fixture
def sec_env() -> Generator[Dict[str, Any], None, None]:
    """Start an isolated Control Center server with temp repo_root and temp .runs/."""
    with tempfile.TemporaryDirectory(prefix="stage0a_sec_") as td:
        root = Path(td)
        runs_dir = root / ".runs"
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Place a sentinel secret outside .runs/ (in repo_root) AND inside .runs/ to prove both are protected
        (root / ".env").write_text("TOP_SECRET=STAGE0A_SENTINEL_OUTSIDE\n", encoding="utf-8")
        (root / "README.md").write_text("# Private Repo Readme\n", encoding="utf-8")
        (runs_dir / ".env").write_text("TOP_SECRET=STAGE0A_SENTINEL_INSIDE\n", encoding="utf-8")

        # Legitimate artifact inside .runs/
        legit_dir = runs_dir / "run_legit_01"
        legit_dir.mkdir(parents=True, exist_ok=True)
        (legit_dir / "report.md").write_text("# Verified Artifact Content\n", encoding="utf-8")

        port = _free_port()
        service = CompanyService(repo_root=root, output_dir=str(runs_dir))
        server = create_server(host="127.0.0.1", port=port, service=service, load_history=False)

        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        time.sleep(0.05)

        yield {
            "port": port,
            "root": root,
            "runs_dir": runs_dir,
            "service": service,
            "server": server,
            "auth_token": server.auth_token,
            "csrf_token": server.csrf_token,
            "origin": f"http://127.0.0.1:{port}",
        }

        server.shutdown()
        server.server_close()


# ==============================================================================
# 1. Local Auth & Zero Hardcoded Secrets (Independent of Origin/CSRF)
# ==============================================================================

def test_ephemeral_tokens_are_unique_per_server_and_not_hardcoded_in_frontend():
    with tempfile.TemporaryDirectory() as td:
        svc1 = CompanyService(output_dir=str(Path(td) / "r1"))
        svc2 = CompanyService(output_dir=str(Path(td) / "r2"))
        s1 = create_server(host="127.0.0.1", port=_free_port(), service=svc1, load_history=False)
        s2 = create_server(host="127.0.0.1", port=_free_port(), service=svc2, load_history=False)
        try:
            assert len(s1.auth_token) >= 32
            assert len(s1.csrf_token) >= 32
            assert s1.auth_token != s2.auth_token
            assert s1.csrf_token != s2.csrf_token
            assert s1.auth_token != s1.csrf_token
        finally:
            s1.server_close()
            s2.server_close()

    # Verify non-loopback bind is rejected
    with tempfile.TemporaryDirectory() as td:
        svc = CompanyService(output_dir=str(Path(td) / "r3"))
        with pytest.raises(ValueError, match="loopback"):
            create_server(host="0.0.0.0", port=_free_port(), service=svc, load_history=False)


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/overview",
        "/api/company",
        "/api/agents",
        "/api/projects",
        "/api/tasks",
        "/api/runs",
        "/api/verifications",
        "/api/artifacts",
        "/api/artifacts/content?path=run_legit_01/report.md",
        "/api/chat",
        "/api/repository-projects",
        "/api/company-runs",
        "/api/company-runs/active",
        "/api/proposals/nonexistent",
    ],
)
def test_sensitive_read_endpoints_require_authentication(sec_env, endpoint):
    port = sec_env["port"]
    status, headers, body = _raw_http(port, "GET", endpoint)
    assert status == HTTPStatus.UNAUTHORIZED, f"{endpoint} unexpectedly returned {status}: {body}"
    assert headers.get("access-control-allow-origin") != "*"
    data = json.loads(body)
    assert data.get("code") == "AUTHENTICATION_REQUIRED"


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/api/projects", {"project_id": "p1", "name": "P1"}),
        ("/api/tasks", {"project_id": "jester-ai-company", "title": "T1"}),
        ("/api/chat", {"content": "hello"}),
        ("/api/company-runs", {"title": "Run 1", "auto_run": False}),
    ],
)
def test_mutation_endpoints_reject_unauthenticated_and_wrong_tokens(sec_env, endpoint, payload):
    port = sec_env["port"]
    raw_body = json.dumps(payload).encode("utf-8")

    # 1. No credentials
    status, _, body = _raw_http(
        port, "POST", endpoint, headers={"Content-Type": "application/json"}, body=raw_body
    )
    assert status == HTTPStatus.UNAUTHORIZED
    assert json.loads(body).get("code") == "AUTHENTICATION_REQUIRED"

    # 2. Wrong Bearer token
    status2, _, _ = _raw_http(
        port,
        "POST",
        endpoint,
        headers={"Content-Type": "application/json", "Authorization": "Bearer wrong-token"},
        body=raw_body,
    )
    assert status2 == HTTPStatus.UNAUTHORIZED

    # 3. Wrong X-Jester-Control-Token
    status3, _, _ = _raw_http(
        port,
        "POST",
        endpoint,
        headers={"Content-Type": "application/json", AUTH_HEADER_NAME: "wrong-token"},
        body=raw_body,
    )
    assert status3 == HTTPStatus.UNAUTHORIZED


def test_health_endpoint_stays_minimal_and_non_sensitive(sec_env):
    status, headers, body = _raw_http(sec_env["port"], "GET", "/api/health")
    assert status == HTTPStatus.OK
    assert headers.get("access-control-allow-origin") != "*"
    data = json.loads(body)
    assert data["status"] == "OPERATIONAL"
    assert data["auth_required"] is True
    assert sec_env["auth_token"] not in body
    assert sec_env["csrf_token"] not in body


# ==============================================================================
# 2. Independent Origin, Host, Fetch-Metadata, and CSRF Validation
# ==============================================================================

def test_origin_and_cors_wildcard_eliminated(sec_env):
    port = sec_env["port"]
    auth_hdr = {"Authorization": f"Bearer {sec_env['auth_token']}"}

    # Evil Origin on GET (even WITH valid auth!) -> 403
    status, headers, body = _raw_http(
        port, "GET", "/api/overview", headers={**auth_hdr, "Origin": "https://evil.example"}
    )
    assert status == HTTPStatus.FORBIDDEN
    assert "access-control-allow-origin" not in headers
    assert json.loads(body).get("code") == "ORIGIN_NOT_ALLOWED"

    # Evil Origin on OPTIONS preflight -> 403, no '*'
    status_opt, headers_opt, _ = _raw_http(
        port, "OPTIONS", "/api/tasks", headers={"Origin": "https://evil.example"}
    )
    assert status_opt == HTTPStatus.FORBIDDEN
    assert "access-control-allow-origin" not in headers_opt

    # Evil Origin on POST (even WITH valid auth!) -> 403
    status_post, headers_post, _ = _raw_http(
        port,
        "POST",
        "/api/projects",
        headers={**auth_hdr, "Origin": "https://evil.example", "Content-Type": "application/json"},
        body=json.dumps({"project_id": "evil", "name": "Evil"}).encode("utf-8"),
    )
    assert status_post == HTTPStatus.FORBIDDEN
    assert "access-control-allow-origin" not in headers_post

    # Allowed loopback Origin echoes exact origin (never '*')
    allowed_origin = sec_env["origin"]
    status_ok, headers_ok, _ = _raw_http(
        port, "GET", "/api/overview", headers={**auth_hdr, "Origin": allowed_origin}
    )
    assert status_ok == HTTPStatus.OK
    assert headers_ok.get("access-control-allow-origin") == allowed_origin
    assert headers_ok.get("access-control-allow-origin") != "*"


def test_host_rebinding_sec_fetch_site_and_referer_blocked(sec_env):
    port = sec_env["port"]
    auth_hdr = {"Authorization": f"Bearer {sec_env['auth_token']}"}

    # 1. DNS rebinding Host header -> 403
    status_host, _, body_host = _raw_http(
        port, "GET", "/api/overview", headers={**auth_hdr, "Host": "attacker.example:8500"}
    )
    assert status_host == HTTPStatus.FORBIDDEN
    assert json.loads(body_host).get("code") == "INVALID_HOST"

    # 2. Sec-Fetch-Site: cross-site -> 403 even with valid auth
    status_sfs, _, body_sfs = _raw_http(
        port, "GET", "/api/overview", headers={**auth_hdr, "Sec-Fetch-Site": "cross-site"}
    )
    assert status_sfs == HTTPStatus.FORBIDDEN
    assert json.loads(body_sfs).get("code") == "CROSS_SITE_REQUEST_BLOCKED"

    # 3. Cross-origin Referer on POST when Origin omitted -> 403
    status_ref, _, body_ref = _raw_http(
        port,
        "POST",
        "/api/projects",
        headers={
            **auth_hdr,
            "Content-Type": "application/json",
            "Referer": "https://evil.example/phish",
        },
        body=json.dumps({"project_id": "p_ref", "name": "Ref"}).encode("utf-8"),
    )
    assert status_ref == HTTPStatus.FORBIDDEN
    assert json.loads(body_ref).get("code") == "REFERER_NOT_ALLOWED"


def test_csrf_resistance_independent_of_cookie_auth(sec_env):
    """Cookie-authenticated mutations MUST supply valid X-Jester-CSRF-Token and application/json."""
    port = sec_env["port"]
    cookie_hdr = f"{SESSION_COOKIE_NAME}={sec_env['auth_token']}"
    body = json.dumps({"project_id": "csrf_test", "name": "CSRF Test"}).encode("utf-8")

    # 1. Cookie auth WITHOUT CSRF token -> 403
    s1, _, b1 = _raw_http(
        port,
        "POST",
        "/api/projects",
        headers={"Cookie": cookie_hdr, "Content-Type": "application/json"},
        body=body,
    )
    assert s1 == HTTPStatus.FORBIDDEN
    assert json.loads(b1).get("code") == "CSRF_TOKEN_INVALID"

    # 2. Cookie auth WITH WRONG CSRF token -> 403
    s2, _, b2 = _raw_http(
        port,
        "POST",
        "/api/projects",
        headers={
            "Cookie": cookie_hdr,
            "Content-Type": "application/json",
            CSRF_HEADER_NAME: "wrong-csrf-token",
        },
        body=body,
    )
    assert s2 == HTTPStatus.FORBIDDEN
    assert json.loads(b2).get("code") == "CSRF_TOKEN_INVALID"

    # 3. Cookie auth WITH valid CSRF token BUT form/text-plain Content-Type -> 403
    s3, _, b3 = _raw_http(
        port,
        "POST",
        "/api/projects",
        headers={
            "Cookie": cookie_hdr,
            "Content-Type": "text/plain",
            CSRF_HEADER_NAME: sec_env["csrf_token"],
        },
        body=body,
    )
    assert s3 == HTTPStatus.FORBIDDEN
    assert json.loads(b3).get("code") == "CSRF_CONTENT_TYPE_INVALID"

    # 4. Cookie auth WITH valid CSRF token + application/json -> 201
    s4, _, _ = _raw_http(
        port,
        "POST",
        "/api/projects",
        headers={
            "Cookie": cookie_hdr,
            "Content-Type": "application/json",
            CSRF_HEADER_NAME: sec_env["csrf_token"],
            "Origin": sec_env["origin"],
        },
        body=body,
    )
    assert s4 == HTTPStatus.CREATED


# ==============================================================================
# 3. DEF-001: Arbitrary verify_cmd Execution Disabled Over HTTP
# ==============================================================================

def test_def001_verify_cmd_blocked_on_execute_and_retry(sec_env):
    port = sec_env["port"]
    root = sec_env["root"]
    auth_hdr = {
        "Authorization": f"Bearer {sec_env['auth_token']}",
        "Content-Type": "application/json",
    }

    # Create task legitimately
    s_create, _, b_create = _raw_http(
        port,
        "POST",
        "/api/tasks",
        headers=auth_hdr,
        body=json.dumps(
            {
                "project_id": "jester-ai-company",
                "title": "RCE Negative Test",
                "goal": "Ensure verify_cmd cannot execute shell",
            }
        ).encode("utf-8"),
    )
    assert s_create == HTTPStatus.CREATED
    task_id = json.loads(b_create)["id"]

    marker = root / "rce_must_not_exist.txt"
    evil_cmd = f'python -c "from pathlib import Path; Path({str(marker)!r}).write_text(\'PWNED\')"'

    # 1. Execute with verify_cmd -> 400 VERIFY_CMD_DISABLED
    s_exec, _, b_exec = _raw_http(
        port,
        "POST",
        f"/api/tasks/{task_id}/execute",
        headers=auth_hdr,
        body=json.dumps({"mock": True, "verify_cmd": evil_cmd}).encode("utf-8"),
    )
    assert s_exec == HTTPStatus.BAD_REQUEST
    assert json.loads(b_exec).get("code") == "VERIFY_CMD_DISABLED"
    assert not marker.exists()

    # 2. Retry with verify_cmd -> 400 VERIFY_CMD_DISABLED
    s_retry, _, b_retry = _raw_http(
        port,
        "POST",
        f"/api/tasks/{task_id}/retry",
        headers=auth_hdr,
        body=json.dumps({"mock": True, "verify_cmd": evil_cmd}).encode("utf-8"),
    )
    assert s_retry == HTTPStatus.BAD_REQUEST
    assert json.loads(b_retry).get("code") == "VERIFY_CMD_DISABLED"
    assert not marker.exists()


# ==============================================================================
# 4. DEF-002: Static Asset Path Traversal Blocked
# ==============================================================================

@pytest.mark.parametrize(
    "attack_path",
    [
        "/assets/../../package.json",
        "/assets/../../../README.md",
        "/assets/%2e%2e/%2e%2e/package.json",
        "/assets/%252e%252e/%252e%252e/package.json",
        "/assets/..\\..\\package.json",
        "/portraits/../../package.json",
        "/assets/index.js%00.png",
    ],
)
def test_def002_static_path_traversal_blocked(sec_env, attack_path):
    status, _, body = _raw_http(sec_env["port"], "GET", attack_path)
    assert status == HTTPStatus.FORBIDDEN, f"{attack_path} returned {status}: {body[:120]}"
    assert json.loads(body).get("code") == "PATH_TRAVERSAL_BLOCKED"
    assert '"vitest"' not in body


def test_def002_legitimate_static_asset_still_served(sec_env):
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if not assets_dir.is_dir():
        pytest.skip("frontend/dist/assets not built")
    sample = next(assets_dir.iterdir(), None)
    assert sample is not None
    status, _, body = _raw_http(sec_env["port"], "GET", f"/assets/{sample.name}")
    assert status == HTTPStatus.OK
    assert len(body) > 0


# ==============================================================================
# 5. DEF-003: Artifact Content Strictly Confined to output_dir
# ==============================================================================

@pytest.mark.parametrize(
    "query",
    [
        "path=../.env",
        "path=../README.md",
        "path=..%2f.env",
        "path=..%252f.env",
        "path=..\\README.md",
        "path=\\\\server\\share\\secret.txt",
        "path=C:/Windows/win.ini",
        "path=/etc/passwd",
        "path=report.md&run_id=../..",
    ],
)
def test_def003_artifact_content_traversal_blocked(sec_env, query):
    auth_hdr = {"Authorization": f"Bearer {sec_env['auth_token']}"}
    status, _, body = _raw_http(sec_env["port"], "GET", f"/api/artifacts/content?{query}", headers=auth_hdr)
    assert status == HTTPStatus.FORBIDDEN, f"query {query} returned {status}: {body}"
    assert "STAGE0A_SENTINEL" not in body


def test_def003_sensitive_filename_inside_runs_and_direct_service_blocked(sec_env):
    svc: CompanyService = sec_env["service"]
    assert svc.get_artifact_content("../.env") is None
    assert svc.get_artifact_content(".env") is None
    assert svc.get_artifact_content("../README.md") is None

    # Legitimate artifact inside output_dir succeeds via HTTP and service
    auth_hdr = {"Authorization": f"Bearer {sec_env['auth_token']}"}
    status, _, body = _raw_http(
        sec_env["port"],
        "GET",
        "/api/artifacts/content?path=report.md&run_id=run_legit_01",
        headers=auth_hdr,
    )
    assert status == HTTPStatus.OK
    assert "Verified Artifact Content" in body


# ==============================================================================
# 6. DEF-004: Immediate Fail-Closed Containment (Unverified Protected Ops Blocked)
# ==============================================================================

def test_def004_http_approve_and_apply_fail_closed_even_with_non_empty_approval_id(sec_env):
    """Non-empty founder_approval_id over HTTP MUST NOT be treated as authentic founder authorization."""
    port = sec_env["port"]
    svc: CompanyService = sec_env["service"]
    auth_hdr = {
        "Authorization": f"Bearer {sec_env['auth_token']}",
        "Content-Type": "application/json",
    }

    # Create a run and attach a valid READY_FOR_HUMAN_APPLY proposal so only the auth gate is tested
    s_cr, _, b_cr = _raw_http(
        port,
        "POST",
        "/api/company-runs",
        headers=auth_hdr,
        body=json.dumps({"title": "Protected Op Containment Test", "auto_run": False}).encode("utf-8"),
    )
    assert s_cr == HTTPStatus.CREATED
    run_id = json.loads(b_cr)["run_id"]

    patch_text = "diff --git a/app.py b/app.py\n+x = 1\n"
    prop_data = {
        "schema_version": "1.0",
        "proposal_id": "prop_stage0a_01",
        "target_repository_root": str(sec_env["root"]),
        "target_branch": "main",
        "target_head_hash": "a" * 40,
        "base_commit_hash": "a" * 40,
        "code_patch_artifact_id": "art_patch_0a",
        "code_patch_sha256": hashlib.sha256(patch_text.encode("utf-8")).hexdigest(),
        "patch_version": 1,
        "qa_report_artifact_id": "art_qa_0a",
        "qa_report_sha256": "b" * 64,
        "qa_execution_report_artifact_id": "art_qae_0a",
        "qa_execution_report_sha256": "c" * 64,
        "qa_verdict": "PASS",
        "expected_changed_files": ("app.py",),
        "expected_diff_stat": {"files_changed": 1, "insertions": 1, "deletions": 0},
        "is_clean": True,
        "created_at": "2026-11-26T00:00:00Z",
        "proposal_sha256": "",
        "project_id": "prj_jester",
    }
    tmp_prop = RealRepoApplyProposal.from_dict(prop_data)
    prop_data["proposal_sha256"] = compute_proposal_sha256(tmp_prop)
    prop = RealRepoApplyProposal.from_dict(prop_data)
    svc.durable_storage.save_proposal(prop, patch_text, company_run_id=run_id)

    run = svc.get_company_run(run_id)
    run.real_repo_apply_proposal_id = prop.proposal_id
    run.state = CompanyRunState.READY_FOR_HUMAN_APPLY.value
    svc.save_company_run(run)

    # 1. Omitted founder_approval_id -> 403 UNVERIFIED_PROTECTED_OPERATION
    s1, _, b1 = _raw_http(
        port, "POST", f"/api/company-runs/{run_id}/approve", headers=auth_hdr, body=b"{}"
    )
    assert s1 == HTTPStatus.FORBIDDEN
    assert json.loads(b1).get("code") == "UNVERIFIED_PROTECTED_OPERATION"

    # 2. Empty founder_approval_id -> 403 UNVERIFIED_PROTECTED_OPERATION
    s2, _, b2 = _raw_http(
        port,
        "POST",
        f"/api/company-runs/{run_id}/approve",
        headers=auth_hdr,
        body=json.dumps({"founder_approval_id": ""}).encode("utf-8"),
    )
    assert s2 == HTTPStatus.FORBIDDEN
    assert json.loads(b2).get("code") == "UNVERIFIED_PROTECTED_OPERATION"

    # 3. NON-EMPTY caller-supplied founder_approval_id -> STILL 403 fail-closed!
    s3, _, b3 = _raw_http(
        port,
        "POST",
        f"/api/company-runs/{run_id}/approve",
        headers=auth_hdr,
        body=json.dumps(
            {"founder_approval_id": "founder_legit_looking_id_999", "proposal_id": prop.proposal_id}
        ).encode("utf-8"),
    )
    assert s3 == HTTPStatus.FORBIDDEN
    assert json.loads(b3).get("code") == "UNVERIFIED_PROTECTED_OPERATION"

    # Verify NO grant was issued and state did not change
    reloaded = svc.get_company_run(run_id)
    assert reloaded.real_repo_apply_grant_id is None
    assert reloaded.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value

    # 4. POST /apply -> ALSO 403 fail-closed!
    s4, _, b4 = _raw_http(
        port,
        "POST",
        f"/api/company-runs/{run_id}/apply",
        headers=auth_hdr,
        body=json.dumps({"proposal_id": prop.proposal_id}).encode("utf-8"),
    )
    assert s4 == HTTPStatus.FORBIDDEN
    assert json.loads(b4).get("code") == "UNVERIFIED_PROTECTED_OPERATION"

    # 5. Programmatic derive_real_repo_apply_grant rejects synthetic prefixes
    for synthetic_id in ("founder_grant_crun_1", "founder_repair_1_crun_1", "appr_12345678", "founder_ui_1"):
        with pytest.raises(MissingApprovalError, match="synthetic"):
            derive_real_repo_apply_grant(prop, founder_approval_id=synthetic_id)


# ==============================================================================
# 7. Legitimate Same-Origin Browser Session End-to-End Flow
# ==============================================================================

def test_legitimate_local_browser_session_bootstrap_and_operations(sec_env):
    """Simulate a real local browser loading GET /, receiving HttpOnly cookie + CSRF meta, and using API."""
    port = sec_env["port"]
    origin = sec_env["origin"]

    # 1. Browser loads GET /
    status, headers, html_body = _raw_http(port, "GET", "/")
    assert status == HTTPStatus.OK
    assert headers.get("x-frame-options") == "DENY"
    assert headers.get("x-content-type-options") == "nosniff"

    # Verify HttpOnly + SameSite=Strict cookie was set
    set_cookie = headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie

    cookie = SimpleCookie()
    cookie.load(set_cookie)
    session_val = cookie[SESSION_COOKIE_NAME].value
    assert session_val == sec_env["auth_token"]

    # Extract dynamically injected CSRF token from <meta name="jester-csrf-token">
    m = re.search(r'<meta\s+name="jester-csrf-token"\s+content="([^"]+)"', html_body)
    assert m is not None, "Expected dynamic jester-csrf-token meta tag in served HTML"
    csrf_val = m.group(1)
    assert csrf_val == sec_env["csrf_token"]

    browser_headers = {
        "Cookie": f"{SESSION_COOKIE_NAME}={session_val}",
        CSRF_HEADER_NAME: csrf_val,
        "Origin": origin,
        "Content-Type": "application/json",
    }

    # 2. Legitimate GET /api/overview & GET /api/company-runs succeed
    s_ov, _, b_ov = _raw_http(port, "GET", "/api/overview", headers=browser_headers)
    assert s_ov == HTTPStatus.OK
    assert json.loads(b_ov)["company"]["name"] == "Jester AI Company"

    s_runs, _, _ = _raw_http(port, "GET", "/api/company-runs", headers=browser_headers)
    assert s_runs == HTTPStatus.OK

    # 3. Legitimate POST /api/company-runs succeeds
    s_new, _, b_new = _raw_http(
        port,
        "POST",
        "/api/company-runs",
        headers=browser_headers,
        body=json.dumps({"title": "Legitimate Browser Run", "auto_run": False}).encode("utf-8"),
    )
    assert s_new == HTTPStatus.CREATED
    assert json.loads(b_new)["run_id"].startswith("crun_")
