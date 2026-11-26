"""Control Center HTTP Server and Application Handler for Jester AI Company.

Provides a lightweight, zero-external-dependency web control center and REST
endpoints adhering strictly to the CompanyService application boundary.

Architecture:
    Browser / Operator
            ↓ HTTP (HTML/JSON)
    ControlCenterHandler
            ↓
      CompanyService
            ↓
    Company Core & Execution Engine
"""

from datetime import datetime, timezone
import hmac
import html
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import secrets
import socket
import sys
import threading
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
import urllib.parse

logger = logging.getLogger(__name__)

ACTIVE_RUN_WORKERS: Set[str] = set()
_ACTIVE_WORKERS_LOCK = threading.Lock()


def register_active_worker(run_id: str) -> None:
    """Register an in-memory worker thread actively executing a CompanyRun."""
    with _ACTIVE_WORKERS_LOCK:
        ACTIVE_RUN_WORKERS.add(run_id)


def unregister_active_worker(run_id: str) -> None:
    """Unregister an in-memory worker thread upon lifecycle termination."""
    with _ACTIVE_WORKERS_LOCK:
        ACTIVE_RUN_WORKERS.discard(run_id)


def is_run_actively_executing(run_id: str) -> bool:
    """Check if a CompanyRun currently has an attached in-memory background worker."""
    with _ACTIVE_WORKERS_LOCK:
        return run_id in ACTIVE_RUN_WORKERS

from .context import CompanyObjective
from .core import TaskStatus
from .orchestrator import CompanyRun, CompanyRunState, WorkItemState
from .project import (
    Project as RepositoryProject,
    RepositoryPolicy,
    RepositoryRef,
    inspect_repository_state,
    verify_target_repository_identity,
)
from .knowledge import create_jester_registration_manifest
from .service import (
    CompanyService,
    CompanyServiceError,
    InvalidTaskStateError,
    ProjectNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)
import uuid

DASHBOARD_HTML_PATH = Path(__file__).resolve().parent / "dashboard.html"
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_PUBLIC_DIR = Path(__file__).resolve().parent.parent / "frontend" / "public"


def ensure_default_repository_project(service: CompanyService) -> None:
    """Ensure the authoritative Jester project is registered under ProjectRegistry."""
    if service.get_repository_project("prj_jester") is None:
        real_jester_path = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester").resolve()
        root_path_str = str(real_jester_path) if real_jester_path.exists() else str(service.repo_root)

        repo_ref = RepositoryRef(
            repository_id="repo_jester",
            root_path=root_path_str,
            target_branch="main",
            expected_remote="git@github.com:farnai/Jester.git",
            allow_untracked=True,
        )
        repo_policy = RepositoryPolicy(
            read_allowed=(
                "docs/**",
                "backend/**",
                "frontend/**",
                "tests/**",
                "scripts/**",
                "*.md",
                "*.ini",
                "*.txt",
            ),
            mutation_allowed=("backend/**", "frontend/**", "tests/**"),
            denied=(".git", ".git/**", ".env*", "*.key", "*.secret"),
        )
        project = RepositoryProject(
            project_id="prj_jester",
            name="Jester — People Discovery & Relationship Intelligence Engine",
            description="High-performance People Discovery and Relationship Intelligence platform",
            repository=repo_ref,
            policy=repo_policy,
        )
        service.register_repository_project(project, validate_repo=False)

    if service.get_project_knowledge_manifest("prj_jester") is None:
        manifest = create_jester_registration_manifest(project_id="prj_jester", repository_id="repo_jester")
        service.register_project_knowledge_manifest(manifest)


def enrich_company_run_data(run: CompanyRun, service: CompanyService) -> Dict[str, Any]:
    """Enrich CompanyRun dict representation with real workforce and proposal context."""
    run_dict = run.to_dict()

    # 1. Selected and skipped workforce
    selected_agents: List[str] = []
    if run.active_plan and run.active_plan.work_items:
        for wi in run.active_plan.work_items:
            if wi.role and wi.role not in selected_agents:
                selected_agents.append(wi.role)

    if any(s.role == "qa" for s in run.employee_summaries) and "qa" not in selected_agents:
        selected_agents.append("qa")

    if not selected_agents and run.employee_summaries:
        for s in run.employee_summaries:
            if s.role and s.role not in selected_agents:
                selected_agents.append(s.role)

    all_roles = ["product", "research", "ux", "marketing", "developer", "qa"]
    skipped_agents = [r for r in all_roles if r not in selected_agents]

    # 2. Selection reasoning
    reasoning = ""
    if run.objective and run.objective.constraints:
        for c in run.objective.constraints:
            if "specialist" in c.lower() or "orchestrate" in c.lower() or "delivery" in c.lower():
                reasoning = c
                break
    if not reasoning and run.objective:
        reasoning = f"Plan formulated for objective: {run.objective.title}"
    if not reasoning:
        reasoning = "CEO dynamic workforce allocation based on objective constraints."

    # 3. QA Verdict and summary
    qa_verdict = None
    qa_summary = None
    for s in run.employee_summaries:
        if s.role == "qa":
            qa_summary = s.summary
            if "PASS" in s.summary.upper():
                qa_verdict = "PASS"
            elif "FAIL" in s.summary.upper():
                qa_verdict = "FAIL"
            elif "BLOCK" in s.summary.upper():
                qa_verdict = "BLOCKED"
            break

    # 4. Proposal details if available
    proposal_dict = None
    if run.real_repo_apply_proposal_id:
        try:
            prop = service.durable_storage.load_proposal(run.real_repo_apply_proposal_id, verify_integrity=False)
            if prop:
                proposal_dict = prop.to_dict()
                if prop.qa_verdict:
                    qa_verdict = prop.qa_verdict
        except Exception:
            pass

    # 5. Grant details if available
    grant_dict = None
    if run.real_repo_apply_grant_id:
        try:
            grant = service.durable_storage.load_grant(run.real_repo_apply_grant_id)
            if grant:
                grant_dict = grant.to_dict()
        except Exception:
            pass
    elif proposal_dict:
        # Check if grant exists for this proposal in durable storage
        try:
            for g in service.durable_storage.list_grants():
                if g.proposal_id == run.real_repo_apply_proposal_id:
                    grant_dict = g.to_dict()
                    break
        except Exception:
            pass

    # 6. Step 20c receipt if available
    receipt_dict = None
    try:
        receipt_file = service.output_dir / "step_20c_receipt.json"
        if receipt_file.is_file():
            rcpt = json.loads(receipt_file.read_text(encoding="utf-8"))
            if rcpt.get("company_run_id") == run.run_id:
                receipt_dict = rcpt
    except Exception:
        pass

    run_dict["selected_agents"] = selected_agents
    run_dict["skipped_agents"] = skipped_agents
    run_dict["selection_reasoning"] = reasoning
    run_dict["qa_verdict"] = qa_verdict
    run_dict["qa_summary"] = qa_summary
    run_dict["proposal"] = proposal_dict
    run_dict["grant"] = grant_dict
    run_dict["receipt"] = receipt_dict
    run_dict["clarification_request"] = getattr(run, "clarification_request", None)
    run_dict["investigation_findings"] = getattr(run, "investigation_findings", [])
    run_dict["investigation_count"] = getattr(run, "investigation_count", 0)
    run_dict["max_investigations"] = getattr(run, "max_investigations", 2)
    run_dict["last_ceo_decision"] = getattr(run, "last_ceo_decision", None)
    run_dict["founder_clarifications"] = getattr(run, "founder_clarifications", [])
    run_dict["team_selection"] = getattr(run, "team_selection", None)
    run_dict["team_escalations"] = getattr(run, "team_escalations", [])
    run_dict["escalation_count"] = getattr(run, "escalation_count", 0)
    run_dict["max_escalations"] = getattr(run, "max_escalations", 2)
    run_dict["execution_telemetry"] = service.get_company_run_metrics(run.run_id)
    is_live = is_run_actively_executing(run.run_id)
    run_dict["is_active_execution"] = is_live
    run_dict["is_persisted_snapshot"] = not is_live

    # 7. Fault-Tolerant Recovery context (STEP 23B.5-C)
    current_attempt = 1
    if getattr(run, "recovery_attempt_counts", None):
        current_attempt = max(run.recovery_attempt_counts.values(), default=1)

    last_failure = getattr(run, "current_recovery_record", None)
    preserved_artifacts_names: List[str] = []
    if getattr(run, "recovery_checkpoint", None) and isinstance(run.recovery_checkpoint, dict):
        for a in run.recovery_checkpoint.get("preserved_artifacts", []):
            name_val = a.get("name") or a.get("artifact_id")
            if name_val and name_val not in preserved_artifacts_names:
                preserved_artifacts_names.append(name_val)
    elif getattr(run, "employee_summaries", None):
        for s in run.employee_summaries:
            for a in s.artifact_refs:
                name_val = a.get("name") or a.get("artifact_id")
                if name_val and name_val not in preserved_artifacts_names:
                    preserved_artifacts_names.append(name_val)

    remaining_work_ids: List[str] = []
    if getattr(run, "active_plan", None):
        for w in run.active_plan.work_items:
            if run.work_item_states.get(w.work_item_id) != WorkItemState.COMPLETED.value:
                remaining_work_ids.append(w.work_item_id)

    founder_action_needed = (
        run.state in ("WAITING_FOR_CLARIFICATION", "WAITING_FOR_HUMAN")
        or bool(getattr(run, "clarification_request", None))
        or bool(getattr(run, "escalation", None))
    )

    recovery_summary = {
        "current_attempt": current_attempt,
        "max_retries": 1,
        "failure_category": last_failure.get("failure_category") if last_failure else None,
        "recovery_decision": last_failure.get("recovery_decision") if last_failure else None,
        "preserved_artifacts": preserved_artifacts_names,
        "remaining_work": remaining_work_ids,
        "founder_action_required": founder_action_needed,
        "explanation": last_failure.get("explanation") if last_failure else None,
        "is_exploration_timeout": last_failure.get("is_exploration_timeout", False) if last_failure else False,
    }
    run_dict["recovery_summary"] = recovery_summary
    run_dict["recovery_checkpoint"] = getattr(run, "recovery_checkpoint", None)
    run_dict["recovery_history"] = getattr(run, "recovery_history", [])
    return run_dict


SESSION_COOKIE_NAME = "jester_cc_session"
AUTH_HEADER_NAME = "X-Jester-Control-Token"
CSRF_HEADER_NAME = "X-Jester-CSRF-Token"
_LOOPBACK_HOSTS: FrozenSet[str] = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _build_allowed_origins(port: int, extra_origins: Optional[Iterable[str]] = None) -> FrozenSet[str]:
    """Compute strict loopback Origin allowlist for a bound Control Center port. Never allows '*'."""
    origins: Set[str] = {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://[::1]:{port}",
    }
    if extra_origins:
        for orig in extra_origins:
            cleaned = str(orig).strip().rstrip("/")
            if cleaned and cleaned != "*":
                parsed = urllib.parse.urlparse(cleaned)
                if parsed.scheme in ("http", "https") and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
                    origins.add(f"{parsed.scheme}://{parsed.netloc}")
    return frozenset(origins)


def _decode_path_fully(raw_path: str, max_rounds: int = 3) -> str:
    """Iteratively percent-decode a URL path to detect single- or multi-encoded traversal payloads."""
    current = raw_path
    for _ in range(max_rounds):
        decoded = urllib.parse.unquote(current)
        if decoded == current:
            break
        current = decoded
    return current


def _has_artifact_traversal_tokens(raw_value: str) -> bool:
    """Validate artifact relative path (allows benign Windows relative subpaths like '00_context\\file.json'
    while strictly rejecting UNC paths, drive letters, leading slashes, null bytes, and '..' segments)."""
    if not raw_value or "\x00" in raw_value:
        return True
    decoded = _decode_path_fully(raw_value)
    for candidate in (raw_value, decoded):
        stripped = candidate.strip()
        if not stripped or "\x00" in stripped or stripped.startswith(("/", "\\")) or ":" in stripped:
            return True
        norm = stripped.replace("\\", "/")
        if norm.startswith("/") or any(seg == ".." for seg in norm.split("/")):
            return True
    return False


def _has_path_traversal_tokens(raw_value: str) -> bool:
    """Return True if raw or percent-decoded path contains traversal, backslash, drive, or null-byte tokens."""
    if not raw_value or "\x00" in raw_value:
        return True
    decoded = _decode_path_fully(raw_value)
    if "\x00" in decoded or "\\" in raw_value or "\\" in decoded:
        return True
    for candidate in (raw_value, decoded):
        parts = [seg for seg in candidate.split("/") if seg]
        if any(seg == ".." for seg in parts):
            return True
    return False


def _resolve_confined_static_file(raw_path: str, allowed_roots: Tuple[Path, ...]) -> Tuple[Optional[Path], bool]:
    """Safely resolve a static asset path strictly inside allowed_roots (DEF-002).

    Returns:
        (resolved_file_or_None, is_forbidden_traversal)
    """
    if _has_path_traversal_tokens(raw_path):
        return None, True

    decoded = _decode_path_fully(raw_path)
    rel_str = decoded.lstrip("/")
    if not rel_str or ":" in rel_str:
        return None, True

    rel_path = Path(rel_str)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        return None, True

    for base in allowed_roots:
        base_resolved = base.resolve()
        candidate = base_resolved / rel_path
        try:
            resolved = candidate.resolve()
        except OSError:
            continue

        if not resolved.is_relative_to(base_resolved):
            return None, True

        if resolved.is_file():
            return resolved, False

    return None, False


class ControlCenterHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler serving the Control Center UI and REST API."""

    service: CompanyService = None  # Injected by server factory
    auth_token: str = ""  # Ephemeral per-server secret injected by server factory
    csrf_token: str = ""  # Ephemeral per-server CSRF secret injected by server factory
    allowed_origins: FrozenSet[str] = frozenset()
    bound_port: int = 8500

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr request logging in test/silent modes if needed."""
        sys.stderr.write(f"[ControlCenter] {self.address_string()} - {format % args}\n")

    def _get_validated_cors_origin(self) -> Optional[str]:
        """Return exact Origin header if and only if it is in allowed_origins."""
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if origin and origin in self.allowed_origins:
            return origin
        return None

    def _send_security_headers(self) -> None:
        """Attach baseline browser security headers and strict (non-wildcard) CORS if allowed."""
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        valid_origin = self._get_validated_cors_origin()
        if valid_origin:
            self.send_header("Access-Control-Allow-Origin", valid_origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers",
                f"Content-Type, Authorization, {AUTH_HEADER_NAME}, {CSRF_HEADER_NAME}",
            )
            self.send_header("Vary", "Origin")

    def _send_json(self, status_code: int, data: Any) -> None:
        """Helper to send a JSON response with strict security headers (zero wildcard CORS)."""
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_content: str, set_session_cookie: bool = False) -> None:
        """Helper to send an HTML response with dynamic CSRF meta tag and HttpOnly session cookie."""
        rendered = html_content
        if set_session_cookie and self.csrf_token:
            meta_tag = (
                f'    <meta name="jester-csrf-token" '
                f'content="{html.escape(self.csrf_token, quote=True)}" />\n'
            )
            if "</head>" in rendered:
                rendered = rendered.replace("</head>", f"{meta_tag}  </head>", 1)
            else:
                rendered = meta_tag + rendered

        body = rendered.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        if set_session_cookie and self.auth_token:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={self.auth_token}; HttpOnly; SameSite=Strict; Path=/",
            )
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text_content: str, status_code: int = HTTPStatus.OK) -> None:
        """Helper to send a plain text response with strict security headers."""
        body = text_content.encode("utf-8", errors="replace")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._send_security_headers()
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _drain_unread_request_body(self) -> None:
        """Safely drain bounded unread POST/PUT/DELETE request body before returning early errors.

        Prevents Windows TCP RST (WinError 10053) when rejecting unauthenticated or
        forbidden requests that sent a JSON payload before the handler called _read_json_body().
        """
        if getattr(self, "_body_drained", False):
            return
        self._body_drained = True
        if getattr(self, "command", "") not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return
        if content_length <= 0:
            return
        to_read = min(content_length, 1_048_576)
        try:
            self.rfile.read(to_read)
        except OSError:
            pass

    def _send_error_json(self, status_code: int, message: str, code: Optional[str] = None) -> None:
        """Send standard structured JSON error."""
        self._drain_unread_request_body()
        payload: Dict[str, Any] = {"error": message, "status": "error"}
        if code:
            payload["code"] = code
        self._send_json(status_code, payload)

    # --------------------------------------------------------------------------
    # Stage 0A Independent Security Gates (Host, Origin/Fetch, Auth, CSRF)
    # --------------------------------------------------------------------------

    def _validate_host(self) -> bool:
        """Verify Host header targets loopback only (anti-DNS-rebinding)."""
        raw_host = (self.headers.get("Host") or "").strip()
        if not raw_host:
            return True  # HTTP/1.0 or minimal local clients without Host header
        parsed = urllib.parse.urlparse(f"http://{raw_host}")
        hostname = (parsed.hostname or "").lower()
        if hostname not in _LOOPBACK_HOSTS:
            self._send_error_json(
                HTTPStatus.FORBIDDEN,
                f"Rejected non-loopback Host header: '{raw_host}'.",
                code="INVALID_HOST",
            )
            return False
        if parsed.port is not None and self.bound_port and parsed.port != self.bound_port:
            # Permit Vite dev proxy or explicit allowed loopback origin ports only if configured
            origin_candidate = f"http://{hostname}:{parsed.port}"
            if origin_candidate not in self.allowed_origins:
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    f"Host port mismatch: '{raw_host}'.",
                    code="INVALID_HOST_PORT",
                )
                return False
        return True

    def _validate_origin_and_fetch_metadata(self, is_api: bool, is_mutation: bool) -> bool:
        """Independently enforce Origin allowlist, Sec-Fetch-Site, and Referer checks."""
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if origin:
            if origin not in self.allowed_origins:
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    f"Cross-origin request blocked: origin '{origin}' is not allowed.",
                    code="ORIGIN_NOT_ALLOWED",
                )
                return False

        sec_fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if is_api and sec_fetch_site == "cross-site":
            self._send_error_json(
                HTTPStatus.FORBIDDEN,
                "Cross-site fetch metadata rejected for Control Center API.",
                code="CROSS_SITE_REQUEST_BLOCKED",
            )
            return False

        if is_mutation and not origin:
            referer = (self.headers.get("Referer") or "").strip()
            if referer:
                ref_parsed = urllib.parse.urlparse(referer)
                ref_origin = f"{ref_parsed.scheme}://{ref_parsed.netloc}".rstrip("/")
                if ref_origin not in self.allowed_origins:
                    self._send_error_json(
                        HTTPStatus.FORBIDDEN,
                        f"Cross-origin Referer blocked for mutation: '{ref_origin}'.",
                        code="REFERER_NOT_ALLOWED",
                    )
                    return False

        return True

    def _authenticate_request(self) -> Optional[str]:
        """Authenticate local Control Center requests via Bearer/header token or HttpOnly session cookie.

        Returns:
            "header" or "cookie" if authenticated; None after sending HTTP 401.
        """
        expected = self.auth_token
        if not expected:
            self._send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "Control Center authentication token is not initialized.",
                code="AUTH_NOT_CONFIGURED",
            )
            return None

        # 1. Explicit Authorization: Bearer <token> or X-Jester-Control-Token: <token>
        auth_header = (self.headers.get("Authorization") or "").strip()
        if auth_header.lower().startswith("bearer "):
            presented = auth_header[7:].strip()
            if presented and hmac.compare_digest(presented, expected):
                return "header"
            self._send_error_json(
                HTTPStatus.UNAUTHORIZED,
                "Invalid Control Center Bearer token.",
                code="AUTHENTICATION_REQUIRED",
            )
            return None

        ctrl_token = (self.headers.get(AUTH_HEADER_NAME) or "").strip()
        if ctrl_token:
            if hmac.compare_digest(ctrl_token, expected):
                return "header"
            self._send_error_json(
                HTTPStatus.UNAUTHORIZED,
                f"Invalid {AUTH_HEADER_NAME} header.",
                code="AUTHENTICATION_REQUIRED",
            )
            return None

        # 2. HttpOnly SameSite=Strict session cookie set on same-origin HTML load
        cookie_header = self.headers.get("Cookie") or ""
        if cookie_header:
            cookie: SimpleCookie = SimpleCookie()
            try:
                cookie.load(cookie_header)
            except Exception:
                cookie = SimpleCookie()
            if SESSION_COOKIE_NAME in cookie:
                cookie_val = cookie[SESSION_COOKIE_NAME].value.strip()
                if cookie_val and hmac.compare_digest(cookie_val, expected):
                    return "cookie"

        self._send_error_json(
            HTTPStatus.UNAUTHORIZED,
            "Authentication required to access Control Center API.",
            code="AUTHENTICATION_REQUIRED",
        )
        return None

    def _validate_csrf(self, auth_method: str) -> bool:
        """Independently enforce CSRF resistance on state-changing requests.

        1. Rejects non-JSON Content-Type (blocks simple HTML form / text-plain CSRF).
        2. Requires valid X-Jester-CSRF-Token header for cookie-authenticated mutations.
        """
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._send_error_json(
                HTTPStatus.FORBIDDEN,
                f"CSRF protection requires 'Content-Type: application/json', got '{content_type or 'missing'}'.",
                code="CSRF_CONTENT_TYPE_INVALID",
            )
            return False

        if auth_method == "cookie":
            presented_csrf = (self.headers.get(CSRF_HEADER_NAME) or "").strip()
            if not presented_csrf or not self.csrf_token or not hmac.compare_digest(presented_csrf, self.csrf_token):
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    f"Missing or invalid {CSRF_HEADER_NAME} header for cookie-authenticated mutation.",
                    code="CSRF_TOKEN_INVALID",
                )
                return False

        return True

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests strictly without wildcard '*'."""
        if not self._validate_host():
            return
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if origin and origin not in self.allowed_origins:
            self._send_error_json(
                HTTPStatus.FORBIDDEN,
                f"CORS preflight rejected for disallowed origin '{origin}'.",
                code="ORIGIN_NOT_ALLOWED",
            )
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_security_headers()
        self.end_headers()

    # --------------------------------------------------------------------------
    # GET Routing
    # --------------------------------------------------------------------------

    def do_GET(self) -> None:
        """Handle GET requests for static UI and API endpoints."""
        if not self._validate_host():
            return

        parsed = urllib.parse.urlparse(self.path)
        raw_path = parsed.path
        path = raw_path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)
        is_api = path.startswith("/api/") or path == "/api"

        if not self._validate_origin_and_fetch_metadata(is_api=is_api, is_mutation=False):
            return

        # 1. UI Root (React SPA if built, fallback to dashboard.html) — issues local HttpOnly cookie + dynamic CSRF meta
        if path in ("", "/index.html"):
            dist_index = FRONTEND_DIST_DIR / "index.html"
            if dist_index.is_file():
                content = dist_index.read_text(encoding="utf-8")
                self._send_html(content, set_session_cookie=True)
            elif DASHBOARD_HTML_PATH.is_file():
                content = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
                self._send_html(content, set_session_cookie=True)
            else:
                self._send_html(
                    "<h1>Jester AI Company Control Center</h1><p>Dashboard HTML not found.</p>",
                    set_session_cookie=True,
                )
            return

        # 1b. Static Assets (/assets/*, /portraits/* or root public files) with strict confinement (DEF-002)
        if raw_path.startswith(("/assets/", "/portraits/")) or path in ("/office_backdrop.jpg", "/favicon.svg"):
            asset_file, is_forbidden = _resolve_confined_static_file(
                raw_path,
                (FRONTEND_DIST_DIR, FRONTEND_PUBLIC_DIR),
            )
            if is_forbidden:
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Path traversal or out-of-bounds static file access denied.",
                    code="PATH_TRAVERSAL_BLOCKED",
                )
                return
            if asset_file is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Static asset not found: {raw_path}")
                return

            suffix = asset_file.suffix.lower()
            content_types = {
                ".js": "application/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".ico": "image/x-icon",
                ".json": "application/json; charset=utf-8",
            }
            ctype = content_types.get(suffix, "application/octet-stream")
            data = asset_file.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self._send_security_headers()
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(data)
            return

        # 2. Health Check (minimal non-sensitive liveness endpoint)
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {
                "status": "OPERATIONAL",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "auth_required": True,
            })
            return

        # All other /api/* read endpoints expose sensitive operational/artifact/proposal data -> require auth!
        if is_api:
            if self._authenticate_request() is None:
                return

        # 3. Company Overview
        if path == "/api/overview":
            overview = self.service.get_overview()
            self._send_json(HTTPStatus.OK, overview)
            return

        # 4. Company Detail
        if path == "/api/company":
            self._send_json(HTTPStatus.OK, self.service.get_company())
            return

        # 5. Agents / Employees (7 recognized roles)
        if path == "/api/agents":
            employees = [e.to_dict() for e in self.service.list_employees()]
            self._send_json(HTTPStatus.OK, employees)
            return

        if path.startswith("/api/agents/"):
            agent_id = path[len("/api/agents/"):]
            emp = self.service.get_employee(agent_id)
            if emp:
                self._send_json(HTTPStatus.OK, emp.to_dict())
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Agent '{agent_id}' not found.")
            return

        # 6. Projects
        if path == "/api/projects":
            projects = [p.to_dict() for p in self.service.list_projects()]
            self._send_json(HTTPStatus.OK, projects)
            return

        if path.startswith("/api/projects/"):
            project_id = path[len("/api/projects/"):]
            try:
                proj = self.service.get_project(project_id)
                self._send_json(HTTPStatus.OK, proj.to_dict())
            except ProjectNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            return

        # 7. Tasks
        if path == "/api/tasks":
            proj_id = query.get("project_id", [None])[0]
            if proj_id:
                try:
                    tasks = [t.to_dict() for t in self.service.list_tasks(proj_id)]
                except ProjectNotFoundError as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
                    return
            else:
                # All tasks across all projects
                tasks = []
                for p in self.service.list_projects():
                    for t in p.tasks.values():
                        tasks.append(t.to_dict())
            self._send_json(HTTPStatus.OK, tasks)
            return

        if path.startswith("/api/tasks/"):
            task_id = path[len("/api/tasks/"):]
            try:
                task = self.service.get_task(task_id)
                self._send_json(HTTPStatus.OK, task.to_dict())
            except TaskNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            return

        # 8. Task Runs
        if path == "/api/runs":
            runs = self.service.list_all_runs()
            self._send_json(HTTPStatus.OK, runs)
            return

        if path.startswith("/api/runs/"):
            run_id = path[len("/api/runs/"):]
            try:
                run = self.service.get_run(run_id)
                self._send_json(HTTPStatus.OK, run.to_dict())
            except RunNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            return

        # 9. QA / Verifications
        if path == "/api/verifications":
            veris = self.service.list_all_verifications()
            self._send_json(HTTPStatus.OK, veris)
            return

        # 10. Artifacts Catalog
        if path == "/api/artifacts":
            artifacts = self.service.list_all_artifacts()
            self._send_json(HTTPStatus.OK, artifacts)
            return

        # 11. Artifact Content Reader (strictly confined to output_dir — DEF-003)
        if path == "/api/artifacts/content":
            art_path = query.get("path", [None])[0]
            run_id = query.get("run_id", [None])[0]
            if not art_path:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Missing required query parameter 'path'.")
                return

            if (
                _has_artifact_traversal_tokens(art_path)
                or (run_id is not None and (_has_path_traversal_tokens(run_id) or "/" in run_id or ":" in run_id))
            ):
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    "Forbidden artifact path: traversal or out-of-bounds reference denied.",
                    code="ARTIFACT_PATH_FORBIDDEN",
                )
                return

            content = self.service.get_artifact_content(art_path, run_id=run_id)
            if content is None:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Artifact not found or inaccessible: '{art_path}'")
                return

            self._send_text(content)
            return

        # 12. Chat Messages (Stage 27-E.1)
        if path == "/api/chat":
            limit = int(query.get("limit", [50])[0])
            msgs = [m.to_dict() for m in self.service.list_chat_messages(limit=limit)]
            self._send_json(HTTPStatus.OK, {"messages": msgs})
            return

        # 13. Repository Projects (STEP 21)
        if path == "/api/repository-projects":
            projs = []
            for p in self.service.list_repository_projects():
                p_dict = p.to_dict()
                try:
                    v = verify_target_repository_identity(project=p)
                    p_dict["verification"] = v.to_dict()
                except Exception as exc:
                    p_dict["verification"] = {"is_valid": False, "error": str(exc)}
                projs.append(p_dict)
            self._send_json(HTTPStatus.OK, projs)
            return

        if path.startswith("/api/repository-projects/"):
            p_id = path[len("/api/repository-projects/"):]
            p = self.service.get_repository_project(p_id)
            if p:
                p_dict = p.to_dict()
                try:
                    v = verify_target_repository_identity(project=p)
                    p_dict["verification"] = v.to_dict()
                except Exception as exc:
                    p_dict["verification"] = {"is_valid": False, "error": str(exc)}
                self._send_json(HTTPStatus.OK, p_dict)
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Repository project '{p_id}' not found.")
            return

        # 14. Company Runs (STEP 21)
        if path == "/api/company-runs":
            runs = [enrich_company_run_data(r, self.service) for r in self.service.list_company_runs()]
            runs.sort(key=lambda r: r.get("created_at", "") or "", reverse=True)
            self._send_json(HTTPStatus.OK, runs)
            return

        if path == "/api/company-runs/active":
            runs = self.service.list_company_runs()
            if runs:
                active_runs = [r for r in runs if r.state not in ("COMPLETED", "FAILED", "BLOCKED")]
                target_run = active_runs[-1] if active_runs else runs[-1]
                self._send_json(HTTPStatus.OK, enrich_company_run_data(target_run, self.service))
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, "No company runs found.")
            return

        # 14b. Run-Scoped Proposal Diff (STEP 22E)
        if path.startswith("/api/company-runs/") and path.endswith("/diff"):
            parts = path.split("/")
            run_id = parts[3]
            try:
                run = self.service.get_company_run(run_id)
                if not run.real_repo_apply_proposal_id:
                    self._send_error_json(
                        HTTPStatus.NOT_FOUND,
                        f"Company run '{run_id}' has no verified proposal or patch diff.",
                    )
                    return
                patch_str = self.service.durable_storage.load_proposal_patch(
                    run.real_repo_apply_proposal_id, verify_integrity=False
                )
                self._send_json(HTTPStatus.OK, {
                    "run_id": run_id,
                    "proposal_id": run.real_repo_apply_proposal_id,
                    "diff": patch_str,
                })
            except Exception as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Diff for company run '{run_id}' not found: {exc}")
            return

        # 14c. Run Execution Metrics & Comparison (STEP 23B.4)
        if path == "/api/company-runs/compare":
            base_id = query.get("baseline", [None])[0]
            target_id = query.get("target", [None])[0]
            if not base_id or not target_id:
                runs = [r for r in self.service.list_company_runs() if r.state in ("COMPLETED", "READY_FOR_HUMAN_APPLY", "RUNNING")]
                runs.sort(key=lambda r: r.created_at or "")
                if len(runs) >= 2:
                    base_id = runs[-2].run_id
                    target_id = runs[-1].run_id
                else:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "Requires 'baseline' and 'target' query parameters, or at least two completed runs.")
                    return
            try:
                comparison = self.service.compare_company_runs(base_id, target_id)
                self._send_json(HTTPStatus.OK, comparison)
            except Exception as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Failed to compare runs '{base_id}' and '{target_id}': {exc}")
            return

        if path.startswith("/api/company-runs/") and path.endswith("/metrics"):
            parts = path.split("/")
            run_id = parts[3]
            try:
                metrics = self.service.get_company_run_metrics(run_id)
                self._send_json(HTTPStatus.OK, metrics)
            except Exception as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Metrics for company run '{run_id}' not found: {exc}")
            return

        if path.startswith("/api/company-runs/"):
            run_id = path[len("/api/company-runs/"):]
            try:
                run = self.service.get_company_run(run_id)
                self._send_json(HTTPStatus.OK, enrich_company_run_data(run, self.service))
            except Exception as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Company run '{run_id}' not found: {exc}")
            return

        # 15. Proposals & Diff (STEP 21 & STEP 22E)
        if path.startswith("/api/proposals/") and path.endswith("/diff"):
            parts = path.split("/")
            prop_id = parts[3]
            target_run_id = query.get("run_id", [None])[0]
            if target_run_id:
                try:
                    run = self.service.get_company_run(target_run_id)
                    if run.real_repo_apply_proposal_id != prop_id:
                        self._send_error_json(
                            HTTPStatus.BAD_REQUEST,
                            f"Proposal identity mismatch: proposal '{prop_id}' does not belong to run '{target_run_id}' (run has '{run.real_repo_apply_proposal_id}').",
                        )
                        return
                except Exception as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, f"Company run '{target_run_id}' not found: {exc}")
                    return
            try:
                patch_str = self.service.durable_storage.load_proposal_patch(prop_id, verify_integrity=False)
                self._send_json(HTTPStatus.OK, {"proposal_id": prop_id, "diff": patch_str})
            except Exception as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Proposal patch '{prop_id}' not found: {exc}")
            return

        if path.startswith("/api/proposals/"):
            prop_id = path[len("/api/proposals/"):]
            try:
                prop = self.service.durable_storage.load_proposal(prop_id, verify_integrity=False)
                self._send_json(HTTPStatus.OK, prop.to_dict())
            except Exception as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"Proposal '{prop_id}' not found: {exc}")
            return

        # 16. 404 Fallback
        self._send_error_json(HTTPStatus.NOT_FOUND, f"Endpoint not found: {self.path}")

    # --------------------------------------------------------------------------
    # POST Routing
    # --------------------------------------------------------------------------

    def do_POST(self) -> None:
        """Handle POST requests for controlled project, task, and execution operations."""
        if not self._validate_host():
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if not self._validate_origin_and_fetch_metadata(is_api=True, is_mutation=True):
            return

        auth_method = self._authenticate_request()
        if auth_method is None:
            return

        if not self._validate_csrf(auth_method):
            return

        # Parse request body
        content_length = int(self.headers.get("Content-Length", 0))
        self._body_drained = True
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except json.JSONDecodeError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON payload.")
            return
        if not isinstance(payload, dict):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "JSON body must be an object.")
            return

        # 1. Create Project
        if path == "/api/projects":
            project_id = payload.get("project_id")
            name = payload.get("name")
            root_path = payload.get("root_path")
            tech_stack = payload.get("tech_stack", [])
            conventions = payload.get("conventions", {})

            if not project_id:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Field 'project_id' is required.")
                return

            try:
                proj = self.service.create_project(
                    project_id=project_id,
                    name=name or project_id,
                    root_path=root_path,
                    tech_stack=tech_stack,
                    conventions=conventions,
                )
                self._send_json(HTTPStatus.CREATED, proj.to_dict())
            except Exception as exc:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        # 2. Create Task
        if path == "/api/tasks":
            project_id = payload.get("project_id")
            title = payload.get("title")
            goal = payload.get("goal")
            task_id = payload.get("task_id")
            constraints = payload.get("constraints", [])
            required_roles = payload.get("required_roles", [])

            if not project_id or not title:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Fields 'project_id' and 'title' are required.")
                return

            try:
                task = self.service.create_task(
                    project_id=project_id,
                    title=title,
                    goal=goal or "",
                    task_id=task_id,
                    constraints=constraints,
                    required_roles=required_roles,
                )
                self._send_json(HTTPStatus.CREATED, task.to_dict())
            except ProjectNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except Exception as exc:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        # 3. Execute Task: POST /api/tasks/{task_id}/execute (arbitrary verify_cmd disabled — DEF-001)
        if path.startswith("/api/tasks/") and path.endswith("/execute"):
            parts = path.split("/")
            # ["", "api", "tasks", "<task_id>", "execute"]
            if len(parts) == 5:
                task_id = parts[3]
                if "verify_cmd" in payload and payload.get("verify_cmd") is not None:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        "Arbitrary 'verify_cmd' execution via HTTP is disabled for security (DEF-001).",
                        code="VERIFY_CMD_DISABLED",
                    )
                    return
                mock = payload.get("mock", True)  # Default to mock=True in UI for safety
                dry_run = payload.get("dry_run", False)

                try:
                    run = self.service.execute_task(
                        task_id=task_id,
                        verify_cmd=None,
                        mock=mock,
                        dry_run=dry_run,
                    )
                    self._send_json(HTTPStatus.OK, run.to_dict())
                except TaskNotFoundError as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

        # 4. Retry Task: POST /api/tasks/{task_id}/retry (arbitrary verify_cmd disabled — DEF-001)
        if path.startswith("/api/tasks/") and path.endswith("/retry"):
            parts = path.split("/")
            if len(parts) == 5:
                task_id = parts[3]
                if "verify_cmd" in payload and payload.get("verify_cmd") is not None:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        "Arbitrary 'verify_cmd' execution via HTTP is disabled for security (DEF-001).",
                        code="VERIFY_CMD_DISABLED",
                    )
                    return
                mock = payload.get("mock", True)
                dry_run = payload.get("dry_run", False)

                try:
                    run = self.service.retry_task(
                        task_id=task_id,
                        verify_cmd=None,
                        mock=mock,
                        dry_run=dry_run,
                    )
                    self._send_json(HTTPStatus.OK, run.to_dict())
                except TaskNotFoundError as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
                except InvalidTaskStateError as exc:
                    self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

        # 5. Send Chat Message: POST /api/chat (Stage 27-E.1)
        if path == "/api/chat":
            content = payload.get("content")
            sender_role = payload.get("sender_role", "owner")
            project_id = payload.get("project_id")
            task_id = payload.get("task_id")

            if not content or not str(content).strip():
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Field 'content' is required.")
                return

            try:
                result = self.service.send_chat_message(
                    content=str(content),
                    sender_role=sender_role,
                    project_id=project_id,
                    task_id=task_id,
                )
                self._send_json(HTTPStatus.OK, result)
            except Exception as exc:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        # 6. Create & Execute Company Run: POST /api/company-runs (STEP 21 & STEP 22C)
        if path == "/api/company-runs":
            title = payload.get("title")
            if not title:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Field 'title' is required.")
                return

            description = payload.get("description", title)
            project_id = payload.get("project_id", "prj_jester")
            constraints = payload.get("constraints", [])
            acceptance_criteria = payload.get("acceptance_criteria", [])
            target_repository = payload.get("target_repository")
            auto_run = payload.get("auto_run", True)
            sync_exec = payload.get("sync", False)

            # Auto-resolve target repository from project if not explicitly given
            if not target_repository:
                proj = self.service.get_repository_project(project_id)
                if proj and proj.repository:
                    target_repository = proj.repository.root_path

            # Duplicate / concurrent run safety: ensure no run is actively planning or executing
            active_executing = [
                r for r in self.service.list_company_runs()
                if (r.project_id == project_id or not project_id)
                and r.state in (
                    CompanyRunState.PLANNING.value,
                    CompanyRunState.RUNNING.value,
                    CompanyRunState.APPLYING.value,
                )
            ]
            if active_executing:
                self._send_error_json(
                    HTTPStatus.CONFLICT,
                    f"A company run '{active_executing[0].run_id}' is already actively executing (state: {active_executing[0].state}). Please wait for it to complete or reach a human approval boundary.",
                )
                return

            objective = CompanyObjective(
                id=f"obj_{uuid.uuid4().hex[:8]}",
                title=title,
                description=description,
                constraints=constraints,
                acceptance_criteria=acceptance_criteria,
                target_repository=target_repository,
                project_id=project_id,
            )

            try:
                run = self.service.create_company_run(
                    objective=objective,
                    project_id=project_id,
                )

                if auto_run:
                    register_active_worker(run.run_id)

                    def _run_lifecycle(r_id: str) -> None:
                        try:
                            # Step 1: CEO planning (CREATED -> PLANNING -> PLAN_READY or WAITING_FOR_CLARIFICATION)
                            planned_run = self.service.plan_company_run(r_id)
                            if planned_run.state == CompanyRunState.WAITING_FOR_CLARIFICATION.value:
                                return
                            # Step 2: Start execution (PLAN_READY -> RUNNING)
                            self.service.start_company_run(r_id)
                            # Step 3: Run specialist DAG until boundary
                            self.service.run_company_until_boundary(r_id, max_steps=10)
                        except Exception as exc:
                            logger.error(
                                "Lifecycle execution failed for company run %s: %s",
                                r_id,
                                exc,
                                exc_info=True,
                            )
                            try:
                                failed_run = self.service.get_company_run(r_id)
                                if failed_run.state not in (
                                    CompanyRunState.FAILED.value,
                                    CompanyRunState.BLOCKED.value,
                                    CompanyRunState.COMPLETED.value,
                                ):
                                    failed_run.transition_to(CompanyRunState.FAILED, error=str(exc))
                                    failed_run.add_event(
                                        event_type="RUN_FAILED",
                                        reason=f"Lifecycle execution failed: {exc}",
                                    )
                                    self.service.save_company_run(failed_run)
                            except Exception:
                                pass
                        finally:
                            unregister_active_worker(r_id)

                    if sync_exec:
                        _run_lifecycle(run.run_id)
                        run = self.service.get_company_run(run.run_id)
                        if run.state == CompanyRunState.FAILED.value and run.error:
                            raise Exception(run.error)
                    else:
                        worker = threading.Thread(
                            target=_run_lifecycle,
                            args=(run.run_id,),
                            daemon=True,
                            name=f"Worker-{run.run_id}",
                        )
                        worker.start()

                self._send_json(HTTPStatus.CREATED, enrich_company_run_data(run, self.service))
            except Exception as exc:
                self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        # 7. Founder Approve Repo Apply: POST /api/company-runs/{run_id}/approve
        # Stage 0A immediate containment (DEF-004): fail closed unconditionally until
        # Stage 0B authenticated ProtectedOperationGrant verification is implemented.
        # A caller-supplied string (even non-empty) is NOT authentic founder authorization.
        if path.startswith("/api/company-runs/") and path.endswith("/approve"):
            parts = path.split("/")
            if len(parts) == 5:
                run_id = parts[3]
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    f"Protected approval for CompanyRun '{run_id}' is blocked (fail-closed, DEF-004): "
                    "a caller-supplied 'founder_approval_id' string is not accepted as authentic founder authorization. "
                    "Authenticated ProtectedOperationGrant support is required (Stage 0B).",
                    code="UNVERIFIED_PROTECTED_OPERATION",
                )
                return

        # 8. Founder Reject Repo Apply: POST /api/company-runs/{run_id}/reject (STEP 21)
        if path.startswith("/api/company-runs/") and path.endswith("/reject"):
            parts = path.split("/")
            if len(parts) == 5:
                run_id = parts[3]
                reason = payload.get("reason", "Rejected by Human Founder")
                try:
                    run = self.service.get_company_run(run_id)
                    run.transition_to(CompanyRunState.BLOCKED)
                    run.add_event("FOUNDER_REJECTED", reason=reason)
                    self.service.save_company_run(run)
                    self._send_json(HTTPStatus.OK, {
                        "status": "REJECTED",
                        "run": enrich_company_run_data(run, self.service),
                    })
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

        # 9. Real Repo Apply Execution: POST /api/company-runs/{run_id}/apply
        # Stage 0A immediate containment (DEF-004): fail closed unconditionally until
        # Stage 0B authenticated ProtectedOperationGrant verification is implemented.
        if path.startswith("/api/company-runs/") and path.endswith("/apply"):
            parts = path.split("/")
            if len(parts) == 5:
                run_id = parts[3]
                self._send_error_json(
                    HTTPStatus.FORBIDDEN,
                    f"Protected real-repository apply for CompanyRun '{run_id}' is blocked (fail-closed, DEF-004): "
                    "unverified HTTP apply operations are disabled until Stage 0B authenticated ProtectedOperationGrant is ready.",
                    code="UNVERIFIED_PROTECTED_OPERATION",
                )
                return

        # 10. Founder Clarification: POST /api/company-runs/{run_id}/clarify (STEP 23B.2)
        if path.startswith("/api/company-runs/") and path.endswith("/clarify"):
            parts = path.split("/")
            if len(parts) == 5:
                run_id = parts[3]
                response_text = payload.get("response") or payload.get("clarification")
                author = payload.get("author", "Human Founder")
                auto_run = payload.get("auto_run", True)
                sync_exec = payload.get("sync", False)

                if not response_text or not str(response_text).strip():
                    self._send_error_json(HTTPStatus.BAD_REQUEST, "Field 'response' is required.")
                    return

                try:
                    target_run = self.service.get_company_run(run_id)
                except Exception as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, f"Company run '{run_id}' not found: {exc}")
                    return

                if target_run.state != CompanyRunState.WAITING_FOR_CLARIFICATION.value:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        f"CompanyRun '{run_id}' is in state '{target_run.state}', not 'WAITING_FOR_CLARIFICATION'.",
                    )
                    return

                try:
                    def _resume_lifecycle(r_id: str, resp: str, auth: str) -> None:
                        try:
                            resumed_run = self.service.submit_founder_clarification(
                                run_id=r_id,
                                response=resp,
                                author=auth,
                            )
                            if resumed_run.state == CompanyRunState.PLAN_READY.value and auto_run:
                                self.service.start_company_run(r_id)
                                self.service.run_company_until_boundary(r_id, max_steps=10)
                        except Exception as exc:
                            logger.error("Resume lifecycle failed for run %s: %s", r_id, exc, exc_info=True)

                    if sync_exec:
                        _resume_lifecycle(run_id, str(response_text).strip(), author)
                        run = self.service.get_company_run(run_id)
                    else:
                        run = self.service.submit_founder_clarification(
                            run_id=run_id,
                            response=str(response_text).strip(),
                            author=author,
                        )
                        if auto_run and run.state == CompanyRunState.PLAN_READY.value:
                            register_active_worker(run_id)

                            def _resume_worker(r_id: str) -> None:
                                try:
                                    self.service.start_company_run(r_id)
                                    self.service.run_company_until_boundary(r_id, max_steps=10)
                                except Exception as exc:
                                    logger.error("Resume lifecycle failed for run %s: %s", r_id, exc, exc_info=True)
                                finally:
                                    unregister_active_worker(r_id)

                            worker = threading.Thread(
                                target=_resume_worker,
                                args=(run_id,),
                                daemon=True,
                                name=f"Worker-Resume-{run_id}",
                            )
                            worker.start()

                    self._send_json(HTTPStatus.OK, {
                        "status": "CLARIFIED",
                        "run": enrich_company_run_data(run, self.service),
                    })
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

        # 11. Team Escalation: POST /api/company-runs/{run_id}/escalate (STEP 23B.3)
        if path.startswith("/api/company-runs/") and path.endswith("/escalate"):
            parts = path.split("/")
            if len(parts) == 5:
                run_id = parts[3]
                triggered_by_role = payload.get("triggered_by_role", "developer")
                reason = payload.get("reason", "Missing capability discovered during execution")
                requested_capability = payload.get("requested_capability", "")
                requested_role = payload.get("requested_role")

                try:
                    run = self.service.escalate_company_team(
                        run_id=run_id,
                        triggered_by_role=triggered_by_role,
                        reason=reason,
                        requested_capability=requested_capability,
                        requested_role=requested_role,
                    )
                    self._send_json(HTTPStatus.OK, {
                        "status": "ESCALATED",
                        "run": enrich_company_run_data(run, self.service),
                    })
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

        self._send_error_json(HTTPStatus.NOT_FOUND, f"POST endpoint not found: {self.path}")


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with strict address exclusivity to prevent duplicate listeners on Windows."""
    allow_reuse_address = False

    def server_bind(self) -> None:
        if sys.platform == "win32":
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except (AttributeError, OSError) as exc:
                logger.debug("Could not set SO_EXCLUSIVEADDRUSE on socket: %s", exc)
        super().server_bind()


def create_server(
    host: str = "127.0.0.1",
    port: int = 8500,
    service: Optional[CompanyService] = None,
    load_history: bool = True,
    auth_token: Optional[str] = None,
    csrf_token: Optional[str] = None,
    allowed_origins: Optional[Iterable[str]] = None,
) -> ExclusiveThreadingHTTPServer:
    """Factory to create and configure an ExclusiveThreadingHTTPServer with CompanyService bound.

    Generates ephemeral per-server 256-bit authentication and CSRF tokens unless explicitly
    injected for programmatic/local test clients. Never uses hardcoded default secrets.
    """
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            f"Control Center must bind strictly to loopback (127.0.0.1/localhost/::1), got '{host}'."
        )

    svc = service or CompanyService()
    svc.ensure_default_project()
    ensure_default_repository_project(svc)
    if load_history:
        svc.load_history_from_disk()

    resolved_auth_token = auth_token.strip() if isinstance(auth_token, str) and auth_token.strip() else secrets.token_urlsafe(32)
    resolved_csrf_token = csrf_token.strip() if isinstance(csrf_token, str) and csrf_token.strip() else secrets.token_urlsafe(32)

    # Create handler class bound to this service instance
    class BoundControlCenterHandler(ControlCenterHandler):
        service = svc
        auth_token = resolved_auth_token
        csrf_token = resolved_csrf_token
        allowed_origins = frozenset()
        bound_port = port

    server = ExclusiveThreadingHTTPServer((host, port), BoundControlCenterHandler)
    actual_port = server.server_address[1]
    BoundControlCenterHandler.bound_port = actual_port
    BoundControlCenterHandler.allowed_origins = _build_allowed_origins(actual_port, allowed_origins)

    # Expose ephemeral runtime tokens on the server object for local programmatic callers/tests
    server.auth_token = resolved_auth_token  # type: ignore[attr-defined]
    server.csrf_token = resolved_csrf_token  # type: ignore[attr-defined]
    server.allowed_origins = BoundControlCenterHandler.allowed_origins  # type: ignore[attr-defined]
    return server



def run_control_center(
    host: str = "127.0.0.1",
    port: int = 8500,
    service: Optional[CompanyService] = None,
    open_browser: bool = False,
) -> None:
    """Run the Control Center server loop."""
    server = create_server(host=host, port=port, service=service, load_history=True)
    url = f"http://{host}:{port}"
    print("=" * 72)
    print("        JESTER AI COMPANY CONTROL CENTER (STAGE 27)")
    print("=" * 72)
    print(f"Server running at: {url}")
    print(f"Company:           {server.RequestHandlerClass.service.company.name}")
    print(f"Active Employees:  {len(server.RequestHandlerClass.service.list_employees())}")
    print(f"Projects:          {len(server.RequestHandlerClass.service.list_projects())}")
    print("Press Ctrl+C to terminate.")
    print("=" * 72)

    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Control Center...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_control_center()

