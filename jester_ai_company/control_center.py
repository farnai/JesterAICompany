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
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from pathlib import Path
import sys
import threading
from typing import Any, Dict, List, Optional
import urllib.parse

logger = logging.getLogger(__name__)

from .context import CompanyObjective
from .core import TaskStatus
from .orchestrator import CompanyRun, CompanyRunState
from .project import (
    Project as RepositoryProject,
    RepositoryPolicy,
    RepositoryRef,
    inspect_repository_state,
    verify_target_repository_identity,
)
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
    if service.get_repository_project("prj_jester") is not None:
        return

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
        mutation_allowed=("backend/**", "tests/**"),
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
    return run_dict


class ControlCenterHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler serving the Control Center UI and REST API."""

    service: CompanyService = None  # Injected by server factory

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr request logging in test/silent modes if needed."""
        # Can be overridden or kept clean
        sys.stderr.write(f"[ControlCenter] {self.address_string()} - {format % args}\n")

    def _send_json(self, status_code: int, data: Any) -> None:
        """Helper to send a JSON response with CORS and cache-control headers."""
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_content: str) -> None:
        """Helper to send an HTML response."""
        body = html_content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text_content: str, status_code: int = HTTPStatus.OK) -> None:
        """Helper to send a plain text response."""
        body = text_content.encode("utf-8", errors="replace")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status_code: int, message: str) -> None:
        """Send standard structured JSON error."""
        self._send_json(status_code, {"error": message, "status": "error"})

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests."""
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # --------------------------------------------------------------------------
    # GET Routing
    # --------------------------------------------------------------------------

    def do_GET(self) -> None:
        """Handle GET requests for static UI and API endpoints."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        # 1. UI Root (React SPA if built, fallback to dashboard.html)
        if path in ("", "/index.html"):
            dist_index = FRONTEND_DIST_DIR / "index.html"
            if dist_index.is_file():
                content = dist_index.read_text(encoding="utf-8")
                self._send_html(content)
            elif DASHBOARD_HTML_PATH.is_file():
                content = DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
                self._send_html(content)
            else:
                self._send_html("<h1>Jester AI Company Control Center</h1><p>Dashboard HTML not found.</p>")
            return

        # 1b. Static Assets (/assets/*, /portraits/* or root public files)
        if path.startswith(("/assets/", "/portraits/")) or path in ("/office_backdrop.jpg", "/favicon.svg"):
            asset_file = FRONTEND_DIST_DIR / path.lstrip("/")
            if not asset_file.is_file():
                asset_file = FRONTEND_PUBLIC_DIR / path.lstrip("/")
            if asset_file.is_file():
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
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.end_headers()
                self.wfile.write(data)
                return

        # 2. Health Check
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {
                "status": "OPERATIONAL",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
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

        # 11. Artifact Content Reader
        if path == "/api/artifacts/content":
            art_path = query.get("path", [None])[0]
            run_id = query.get("run_id", [None])[0]
            if not art_path:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Missing required query parameter 'path'.")
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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Parse request body
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(post_data.decode("utf-8")) if post_data else {}
        except json.JSONDecodeError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid JSON payload.")
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

        # 3. Execute Task: POST /api/tasks/{task_id}/execute
        if path.startswith("/api/tasks/") and path.endswith("/execute"):
            parts = path.split("/")
            # ["", "api", "tasks", "<task_id>", "execute"]
            if len(parts) == 5:
                task_id = parts[3]
                verify_cmd = payload.get("verify_cmd")
                mock = payload.get("mock", True)  # Default to mock=True in UI for safety
                dry_run = payload.get("dry_run", False)

                try:
                    run = self.service.execute_task(
                        task_id=task_id,
                        verify_cmd=verify_cmd,
                        mock=mock,
                        dry_run=dry_run,
                    )
                    self._send_json(HTTPStatus.OK, run.to_dict())
                except TaskNotFoundError as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
                return

        # 4. Retry Task: POST /api/tasks/{task_id}/retry
        if path.startswith("/api/tasks/") and path.endswith("/retry"):
            parts = path.split("/")
            if len(parts) == 5:
                task_id = parts[3]
                verify_cmd = payload.get("verify_cmd")
                mock = payload.get("mock", True)
                dry_run = payload.get("dry_run", False)

                try:
                    run = self.service.retry_task(
                        task_id=task_id,
                        verify_cmd=verify_cmd,
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

        # 7. Founder Approve Repo Apply: POST /api/company-runs/{run_id}/approve (STEP 21 & STEP 22E)
        if path.startswith("/api/company-runs/") and path.endswith("/approve"):
            parts = path.split("/")
            if len(parts) == 5:
                run_id = parts[3]
                founder_approval_id = payload.get("founder_approval_id", f"appr_{uuid.uuid4().hex[:8]}")
                approver = payload.get("approver", "Human Founder")
                expected_prop_id = payload.get("proposal_id")

                try:
                    target_run = self.service.get_company_run(run_id)
                except Exception as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, f"Company run '{run_id}' not found: {exc}")
                    return

                if not target_run.real_repo_apply_proposal_id:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        f"Cannot approve CompanyRun '{run_id}': No proposal has been generated or verified for this run.",
                    )
                    return

                if expected_prop_id and expected_prop_id != target_run.real_repo_apply_proposal_id:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        f"Proposal identity mismatch for CompanyRun '{run_id}': expected '{expected_prop_id}', run has '{target_run.real_repo_apply_proposal_id}'.",
                    )
                    return

                try:
                    grant = self.service.approve_company_repo_apply(
                        run_id=run_id,
                        founder_approval_id=founder_approval_id,
                        approver=approver,
                    )
                    run = self.service.get_company_run(run_id)
                    self._send_json(HTTPStatus.OK, {
                        "status": "APPROVED",
                        "grant": grant.to_dict(),
                        "run": enrich_company_run_data(run, self.service),
                    })
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
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

        # 9. Real Repo Apply Execution: POST /api/company-runs/{run_id}/apply (STEP 21 & STEP 22E)
        if path.startswith("/api/company-runs/") and path.endswith("/apply"):
            parts = path.split("/")
            if len(parts) == 5:
                run_id = parts[3]
                expected_prop_id = payload.get("proposal_id")
                expected_grant_id = payload.get("grant_id")

                try:
                    target_run = self.service.get_company_run(run_id)
                except Exception as exc:
                    self._send_error_json(HTTPStatus.NOT_FOUND, f"Company run '{run_id}' not found: {exc}")
                    return

                if not target_run.real_repo_apply_grant_id:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        f"Cannot apply CompanyRun '{run_id}': No grant has been issued. Explicit founder approval is required.",
                    )
                    return

                if expected_grant_id and expected_grant_id != target_run.real_repo_apply_grant_id:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        f"Grant identity mismatch for CompanyRun '{run_id}': expected '{expected_grant_id}', run has '{target_run.real_repo_apply_grant_id}'.",
                    )
                    return

                if expected_prop_id and expected_prop_id != target_run.real_repo_apply_proposal_id:
                    self._send_error_json(
                        HTTPStatus.BAD_REQUEST,
                        f"Proposal identity mismatch for CompanyRun '{run_id}': expected '{expected_prop_id}', run has '{target_run.real_repo_apply_proposal_id}'.",
                    )
                    return

                try:
                    result = self.service.apply_approved_company_repo(run_id=run_id)
                    run = self.service.get_company_run(run_id)
                    self._send_json(HTTPStatus.OK, {
                        "status": "APPLIED",
                        "result": result.to_dict(),
                        "run": enrich_company_run_data(run, self.service),
                    })
                except Exception as exc:
                    self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
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
                            worker = threading.Thread(
                                target=lambda: (
                                    self.service.start_company_run(run_id),
                                    self.service.run_company_until_boundary(run_id, max_steps=10)
                                ),
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

        self._send_error_json(HTTPStatus.NOT_FOUND, f"POST endpoint not found: {self.path}")


def create_server(
    host: str = "127.0.0.1",
    port: int = 8500,
    service: Optional[CompanyService] = None,
    load_history: bool = True,
) -> ThreadingHTTPServer:
    """Factory to create and configure a ThreadingHTTPServer with CompanyService bound."""
    svc = service or CompanyService()
    svc.ensure_default_project()
    ensure_default_repository_project(svc)
    if load_history:
        svc.load_history_from_disk()

    # Create handler class bound to this service instance
    class BoundControlCenterHandler(ControlCenterHandler):
        service = svc

    server = ThreadingHTTPServer((host, port), BoundControlCenterHandler)
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

