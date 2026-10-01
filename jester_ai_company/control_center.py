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
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional
import urllib.parse

from .core import TaskStatus
from .service import (
    CompanyService,
    CompanyServiceError,
    InvalidTaskStateError,
    ProjectNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)

DASHBOARD_HTML_PATH = Path(__file__).resolve().parent / "dashboard.html"
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


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

        # 1b. Static Assets (/assets/* or root public files)
        if path.startswith("/assets/"):
            asset_file = FRONTEND_DIST_DIR / path.lstrip("/")
            if asset_file.is_file():
                suffix = asset_file.suffix.lower()
                content_types = {
                    ".js": "application/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
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

        # 13. 404 Fallback
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
