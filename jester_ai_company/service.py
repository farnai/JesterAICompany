"""Application Service API for Jester AI Company.

Provides a clean, unified programmatic interface for managing Projects, Tasks,
Runs, and executing workflows using the Universal Company Core and TaskExecutor.

Architecture:
    Caller (CLI, future UI/API)
                ↓
          CompanyService
                ↓
    Company / Project / Task
                ↓
          TaskExecutor
                ↓
             CEO Agent
                ↓ native invoke_subagent
          Specialist Employees
                ↓
          Independent QA
                ↓
          VerificationResult & TaskResult
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from .core import (
    Artifact,
    ChatMessage,
    Company,
    Employee,
    Project,
    RunStatus,
    Task,
    TaskResult,
    TaskRun,
    TaskStatus,
    VerificationResult,
    create_default_company,
)
from .execution import TaskExecutor
from .proposal import (
    CEOActionProposal,
    ProposalError,
    REGISTERED_SPECIALIST_ROLES,
    build_task_proposal_prompt,
    parse_and_validate_proposal,
)
from .runtime import AntigravityRuntime, InvalidAgentError

logger = logging.getLogger(__name__)




class CompanyServiceError(Exception):
    """Base exception for application-level company service errors."""
    pass


class ProjectNotFoundError(CompanyServiceError):
    """Raised when a requested project cannot be found."""
    pass


class TaskNotFoundError(CompanyServiceError):
    """Raised when a requested task cannot be found."""
    pass


class RunNotFoundError(CompanyServiceError):
    """Raised when a requested task run cannot be found."""
    pass


class InvalidTaskStateError(CompanyServiceError):
    """Raised when a task operation is invalid for the task's current state."""
    pass


class ExecutionError(CompanyServiceError):
    """Raised when task execution fails unrecoverably."""
    pass


class CompanyService:
    """Application service managing Projects, Tasks, Runs, and Execution.

    This service establishes the application boundary underneath future Control Center
    and API layers. In-memory state management; persistent storage is intentionally deferred.
    """

    def __init__(
        self,
        company: Optional[Company] = None,
        output_dir: str = ".runs",
        verbose: bool = False,
        repo_root: Optional[Path] = None,
        runtime: Optional[AntigravityRuntime] = None,
    ):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.company = company or create_default_company(self.repo_root)
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.runtime = runtime or AntigravityRuntime(repo_root=self.repo_root)
        self.executor = TaskExecutor(
            company=self.company,
            output_dir=str(self.output_dir),
            verbose=self.verbose,
            repo_root=self.repo_root,
        )

    # --------------------------------------------------------------------------
    # Project Management
    # --------------------------------------------------------------------------

    def create_project(
        self,
        project_id: str,
        name: str,
        root_path: Optional[str] = None,
        tech_stack: Optional[List[str]] = None,
        conventions: Optional[Dict[str, Any]] = None,
    ) -> Project:
        """Create and register a Project context within the Company."""
        if not project_id or not project_id.strip():
            raise ValueError("project_id must not be empty")

        proj_id = project_id.strip()
        project = Project(
            id=proj_id,
            name=name.strip() if name else proj_id,
            root_path=str(root_path or self.repo_root),
            tech_stack=list(tech_stack or []),
            conventions=dict(conventions or {}),
        )
        self.company.register_project(project)
        return project

    def get_project(self, project_id: str) -> Project:
        """Retrieve a Project by its identifier."""
        project = self.company.projects.get(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")
        return project

    def list_projects(self) -> List[Project]:
        """List all registered Projects."""
        return list(self.company.projects.values())

    # --------------------------------------------------------------------------
    # Task Management
    # --------------------------------------------------------------------------

    def create_task(
        self,
        project_id: str,
        title: str,
        goal: str,
        task_id: Optional[str] = None,
        constraints: Optional[List[str]] = None,
        required_roles: Optional[List[str]] = None,
        expected_output: Optional[List[str]] = None,
    ) -> Task:
        """Create and register a Task belonging to the specified Project."""
        project = self.get_project(project_id)
        actual_task_id = (task_id or f"task_{uuid.uuid4().hex[:8]}").strip()

        task = project.create_task(
            task_id=actual_task_id,
            title=title.strip() if title else "Untitled Task",
            goal=goal.strip() if goal else "",
            constraints=list(constraints or []),
            required_roles=list(required_roles or []),
            expected_output=list(expected_output or []),
        )
        return task

    def get_task(self, task_id: str, project_id: Optional[str] = None) -> Task:
        """Retrieve a Task by ID, optionally scoped to a Project."""
        if project_id:
            project = self.get_project(project_id)
            task = project.tasks.get(task_id)
            if task:
                return task
            raise TaskNotFoundError(f"Task '{task_id}' not found in project '{project_id}'.")

        # Global search across all registered projects
        for proj in self.company.projects.values():
            if task_id in proj.tasks:
                return proj.tasks[task_id]

        raise TaskNotFoundError(f"Task '{task_id}' not found in any project.")

    def list_tasks(self, project_id: str) -> List[Task]:
        """List all Tasks associated with the specified Project."""
        project = self.get_project(project_id)
        return list(project.tasks.values())

    # --------------------------------------------------------------------------
    # Execution & Retry
    # --------------------------------------------------------------------------

    def execute_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
        verify_cmd: Optional[str] = None,
        mock: bool = False,
        dry_run: bool = False,
        max_fix_attempts: int = 2,
    ) -> TaskRun:
        """Execute a TaskRun for the given Task using the Stage 25 TaskExecutor."""
        task = self.get_task(task_id, project_id=project_id)
        proj = self.get_project(task.project_id)

        run = self.executor.execute_task(
            task=task,
            project=proj,
            verify_cmd=verify_cmd,
            mock=mock,
            dry_run=dry_run,
            max_fix_attempts=max_fix_attempts,
        )
        return run

    def retry_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
        verify_cmd: Optional[str] = None,
        mock: bool = False,
        dry_run: bool = False,
        max_fix_attempts: int = 2,
    ) -> TaskRun:
        """Retry a failed Task, creating a subsequent TaskRun attempt under the SAME Task."""
        task = self.get_task(task_id, project_id=project_id)

        if task.status == TaskStatus.COMPLETED.value:
            raise InvalidTaskStateError(
                f"Cannot retry task '{task_id}': Task has already completed successfully."
            )

        if not task.runs:
            raise InvalidTaskStateError(
                f"Cannot retry task '{task_id}': Task has not been executed yet. Call execute_task first."
            )

        return self.execute_task(
            task_id=task.id,
            project_id=task.project_id,
            verify_cmd=verify_cmd,
            mock=mock,
            dry_run=dry_run,
            max_fix_attempts=max_fix_attempts,
        )

    # --------------------------------------------------------------------------
    # Outputs, Results, Verifications & Artifacts
    # --------------------------------------------------------------------------

    def get_run(self, run_id: str, task_id: Optional[str] = None) -> TaskRun:
        """Retrieve a specific TaskRun by its run_id."""
        if task_id:
            task = self.get_task(task_id)
            for r in task.runs:
                if r.id == run_id:
                    return r
            raise RunNotFoundError(f"Run '{run_id}' not found for task '{task_id}'.")

        # Global search across all tasks
        for proj in self.company.projects.values():
            for t in proj.tasks.values():
                for r in t.runs:
                    if r.id == run_id:
                        return r

        raise RunNotFoundError(f"Run '{run_id}' not found.")

    def list_runs(self, task_id: str, project_id: Optional[str] = None) -> List[TaskRun]:
        """List all TaskRun attempts belonging to a Task."""
        task = self.get_task(task_id, project_id=project_id)
        return list(task.runs)

    def get_task_result(self, task_id: str, project_id: Optional[str] = None) -> Optional[TaskResult]:
        """Retrieve the consolidated TaskResult for a Task, if completed."""
        task = self.get_task(task_id, project_id=project_id)
        return task.result

    def get_task_verifications(
        self,
        task_id: str,
        run_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[VerificationResult]:
        """Retrieve QA verification records for a Task (or specific run)."""
        task = self.get_task(task_id, project_id=project_id)
        if run_id:
            run = self.get_run(run_id, task_id=task.id)
            return list(run.verifications)

        all_veris: List[VerificationResult] = []
        for r in task.runs:
            all_veris.extend(r.verifications)
        return all_veris

    def get_task_artifacts(
        self,
        task_id: str,
        run_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List[Artifact]:
        """Retrieve all recorded Artifacts for a Task (or specific run)."""
        task = self.get_task(task_id, project_id=project_id)
        if run_id:
            run = self.get_run(run_id, task_id=task.id)
            return list(run.artifacts)

        all_artifacts: List[Artifact] = []
        for r in task.runs:
            all_artifacts.extend(r.artifacts)
        return all_artifacts

    # --------------------------------------------------------------------------
    # Observability, Employees, Overview & History (Stage 27)
    # --------------------------------------------------------------------------

    def list_employees(self) -> List[Employee]:
        """List all recognized company employees."""
        return list(self.company.employees.values())

    def get_employee(self, role_or_id: str) -> Optional[Employee]:
        """Retrieve an employee by role or ID."""
        return self.company.get_employee(role_or_id)

    def get_company(self) -> Dict[str, Any]:
        """Return the serialized company domain object."""
        return self.company.to_dict()

    def ensure_default_project(self) -> Project:
        """Ensure a default self-hosting project is registered if no projects exist."""
        default_id = "jester-ai-company"
        if default_id in self.company.projects:
            return self.company.projects[default_id]
        return self.create_project(
            project_id=default_id,
            name="Jester AI Company Self-Host",
            root_path=str(self.repo_root),
            tech_stack=["Python"],
            conventions={"testing": "pytest", "architecture": "Universal Core"},
        )

    def load_history_from_disk(self) -> int:
        """Scan output_dir (.runs) and register past execution runs into Project/Task state.

        Enables the Control Center to observe historical runs recorded on disk alongside in-memory executions.
        Returns the number of historical runs successfully loaded.
        """
        if not self.output_dir.is_dir():
            return 0

        default_proj = self.ensure_default_project()
        loaded_count = 0

        try:
            entries = sorted(
                [d for d in self.output_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
                key=lambda p: p.name,
            )
        except OSError:
            return 0

        for run_dir in entries:
            manifest_file = run_dir / "run_manifest.json"
            if not manifest_file.is_file():
                continue

            try:
                import json
                from .core import _utc_now_iso, ArtifactType
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue

                run_id = data.get("run_id") or run_dir.name
                # Check if this run is already loaded
                already_exists = False
                for proj in self.company.projects.values():
                    for t in proj.tasks.values():
                        if any(r.id == run_id for r in t.runs):
                            already_exists = True
                            break
                    if already_exists:
                        break
                if already_exists:
                    continue

                task_id = data.get("task_id") or f"task_{run_id}"
                proj_id = data.get("project_id") or default_proj.id
                proj = self.company.projects.get(proj_id) or default_proj

                # Resolve or create task
                task = proj.tasks.get(task_id)
                if not task:
                    goal = data.get("goal") or f"Execution run {run_id}"
                    task = proj.create_task(
                        task_id=task_id,
                        title=f"Task: {task_id}",
                        goal=goal,
                    )

                # Build TaskRun
                attempt = data.get("attempt_number") or (len(task.runs) + 1)
                status_raw = data.get("status") or RunStatus.SUCCESS.value
                run_status = RunStatus.SUCCESS.value if status_raw in ("SUCCESS", "COMPLETED") else RunStatus.FAILED.value
                run = TaskRun(
                    id=run_id,
                    task_id=task.id,
                    attempt_number=attempt,
                    status=run_status,
                    created_at=data.get("created_at") or _utc_now_iso(),
                    completed_at=data.get("completed_at"),
                    error=data.get("error"),
                )

                # Load verifications
                veris_data = data.get("verifications") or []
                for v in veris_data:
                    run.add_verification(
                        verifier_role=v.get("verifier_role", "qa"),
                        passed=bool(v.get("passed")),
                        summary=v.get("summary", ""),
                        details=v.get("details", {}),
                    )

                # Check stage verification details if verifications list is empty
                if not run.verifications and "stages" in data:
                    for stage in data["stages"]:
                        if stage.get("stage_id") == "03_verification" and "details" in stage:
                            det = stage["details"]
                            run.add_verification(
                                verifier_role="qa",
                                passed=bool(det.get("passed", True)),
                                summary=f"Stage verification (code {det.get('exit_code', 0)})",
                                details=det,
                            )

                # Load artifacts
                arts_data = data.get("artifacts") or []
                if arts_data and isinstance(arts_data[0], dict):
                    for a in arts_data:
                        run.add_artifact(
                            name=a.get("name", "artifact"),
                            artifact_type=a.get("artifact_type", ArtifactType.SPECIFICATION.value),
                            path=a.get("path", ""),
                            durable=a.get("durable", True),
                        )
                elif "stages" in data:
                    for stage in data["stages"]:
                        for art_path in stage.get("artifacts", []):
                            art_name = Path(art_path).name
                            run.add_artifact(
                                name=art_name,
                                artifact_type=ArtifactType.SPECIFICATION.value,
                                path=art_path,
                                durable=True,
                            )

                task.runs.append(run)
                if run.status == RunStatus.SUCCESS.value:
                    task.status = TaskStatus.COMPLETED.value
                    if not task.result:
                        task.complete(TaskStatus.COMPLETED.value, summary=f"Completed on run {run.id}")
                elif run.status == RunStatus.FAILED.value:
                    task.status = TaskStatus.FAILED.value

                loaded_count += 1
            except Exception:
                continue

        return loaded_count

    def list_all_runs(self) -> List[Dict[str, Any]]:
        """List all TaskRun attempts across all projects and tasks with contextual metadata."""
        runs: List[Dict[str, Any]] = []
        for proj in self.company.projects.values():
            for task in proj.tasks.values():
                for run in task.runs:
                    r_dict = run.to_dict()
                    r_dict["project_id"] = proj.id
                    r_dict["project_name"] = proj.name
                    r_dict["task_title"] = task.title
                    r_dict["task_goal"] = task.goal
                    r_dict["has_passed_verification"] = any(v.passed for v in run.verifications)
                    runs.append(r_dict)
        runs.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""), reverse=True)
        return runs

    def list_all_verifications(self) -> List[Dict[str, Any]]:
        """List all QA verifications across all tasks with parent task/run context."""
        verifications: List[Dict[str, Any]] = []
        for proj in self.company.projects.values():
            for task in proj.tasks.values():
                for run in task.runs:
                    for v in run.verifications:
                        v_dict = v.to_dict()
                        v_dict["run_id"] = run.id
                        v_dict["task_id"] = task.id
                        v_dict["task_title"] = task.title
                        v_dict["project_id"] = proj.id
                        v_dict["project_name"] = proj.name
                        verifications.append(v_dict)
        return verifications

    def list_all_artifacts(self) -> List[Dict[str, Any]]:
        """List all artifacts across all tasks with parent task/run context."""
        artifacts: List[Dict[str, Any]] = []
        for proj in self.company.projects.values():
            for task in proj.tasks.values():
                for run in task.runs:
                    for a in run.artifacts:
                        a_dict = a.to_dict()
                        a_dict["run_id"] = run.id
                        a_dict["task_id"] = task.id
                        a_dict["task_title"] = task.title
                        a_dict["project_id"] = proj.id
                        a_dict["project_name"] = proj.name
                        artifacts.append(a_dict)
        return artifacts

    def get_artifact_content(self, relative_path: str, run_id: Optional[str] = None) -> Optional[str]:
        """Safely read and return text content of an artifact file within output_dir."""
        rel = Path(relative_path)
        if run_id:
            target = (self.output_dir / run_id / rel).resolve()
        else:
            target = (self.output_dir / rel).resolve()

        out_resolved = self.output_dir.resolve()
        repo_resolved = self.repo_root.resolve()
        # Verify target is contained within output_dir or repo_root
        try:
            target.relative_to(out_resolved)
        except ValueError:
            try:
                target.relative_to(repo_resolved)
            except ValueError:
                return None

        if not target.is_file():
            return None

        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def get_overview(self) -> Dict[str, Any]:
        """Synthesize high-level operational overview for the Control Center."""
        from .core import _utc_now_iso
        projects = list(self.company.projects.values())
        employees = list(self.company.employees.values())
        all_tasks: List[Task] = []
        for p in projects:
            all_tasks.extend(p.tasks.values())

        all_runs: List[TaskRun] = []
        for t in all_tasks:
            all_runs.extend(t.runs)

        completed_tasks = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED.value)
        failed_tasks = sum(1 for t in all_tasks if t.status == TaskStatus.FAILED.value)
        in_progress_tasks = sum(1 for t in all_tasks if t.status == TaskStatus.IN_PROGRESS.value)
        pending_tasks = sum(1 for t in all_tasks if t.status == TaskStatus.PENDING.value)

        successful_runs = sum(1 for r in all_runs if r.status == RunStatus.SUCCESS.value)
        failed_runs = sum(1 for r in all_runs if r.status == RunStatus.FAILED.value)

        all_veris: List[VerificationResult] = []
        for r in all_runs:
            all_veris.extend(r.verifications)
        passed_veris = sum(1 for v in all_veris if v.passed)
        failed_veris = sum(1 for v in all_veris if not v.passed)

        recent_runs_summary = self.list_all_runs()[:10]

        return {
            "company": {
                "id": self.company.id,
                "name": self.company.name,
                "purpose": self.company.purpose,
                "health": "OPERATIONAL",
                "status": "OPERATIONAL",
            },
            "counts": {
                "total_employees": len(employees),
                "active_employees": sum(1 for e in employees if e.status == "ACTIVE"),
                "total_projects": len(projects),
                "total_tasks": len(all_tasks),
                "completed_tasks": completed_tasks,
                "failed_tasks": failed_tasks,
                "in_progress_tasks": in_progress_tasks,
                "pending_tasks": pending_tasks,
                "total_runs": len(all_runs),
                "successful_runs": successful_runs,
                "failed_runs": failed_runs,
                "total_verifications": len(all_veris),
                "passed_verifications": passed_veris,
                "failed_verifications": failed_veris,
            },
            "recent_runs": recent_runs_summary,
            "timestamp": _utc_now_iso(),
        }

    # --------------------------------------------------------------------------
    # Company Chat & Communication (Stage 27-E.1)
    # --------------------------------------------------------------------------

    def list_chat_messages(self, limit: int = 50) -> List[ChatMessage]:
        """List chronological chat messages in the company-wide thread."""
        return self.company.messages[-limit:]

    def send_chat_message(
        self,
        content: str,
        sender_role: str = "owner",
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a message to the company chat and synthesize the CEO/team response."""
        text = (content or "").strip()
        if not text:
            raise ValueError("Message content must not be empty.")

        sender_name = "You (Founder)" if sender_role == "owner" else (
            self.company.get_employee(sender_role).title if self.company.get_employee(sender_role) else sender_role.capitalize()
        )

        user_msg = self.company.add_message(
            sender_role=sender_role,
            sender_name=sender_name,
            content=text,
            project_id=project_id,
            task_id=task_id,
        )

        ceo_reply = None
        if sender_role == "owner":
            # Milestone STEP 3: Chat endpoint invokes strictly the CEO agent via AntigravityRuntime
            agent_to_invoke = "ceo"
            try:
                exec_result = self.runtime.execute(agent=agent_to_invoke, prompt=text)
                if exec_result.success and exec_result.stdout and exec_result.stdout.strip():
                    ceo_text = exec_result.stdout.strip()
                elif exec_result.timed_out:
                    logger.warning(
                        "CEO runtime execution timed out after %.2fms for prompt: %s",
                        exec_result.duration_ms,
                        text[:60],
                    )
                    ceo_text = (
                        "I apologize, Founder, but my response timed out. "
                        "Please try again in a moment."
                    )
                elif exec_result.exit_code == 127 or "not found" in (exec_result.stderr or "").lower():
                    logger.warning(
                        "Antigravity CLI executable not found: %s",
                        exec_result.stderr,
                    )
                    ceo_text = (
                        "I apologize, Founder, but the executive runtime is currently "
                        "unavailable on this system."
                    )
                elif not exec_result.success:
                    logger.warning(
                        "CEO runtime execution failed (exit_code=%s, duration=%.2fms): %s",
                        exec_result.exit_code,
                        exec_result.duration_ms,
                        exec_result.stderr,
                    )
                    ceo_text = (
                        "I apologize, Founder, but I encountered an internal issue "
                        "processing your request. Please try again."
                    )
                else:
                    # Non-zero output missing despite 0 exit code
                    logger.warning(
                        "CEO runtime completed with exit code 0 but produced empty output (duration=%.2fms)",
                        exec_result.duration_ms,
                    )
                    ceo_text = (
                        "I apologize, Founder, but I was unable to generate a response. "
                        "Please try rephrasing your message."
                    )
            except Exception as exc:
                logger.warning("Unexpected error communicating with CEO runtime: %s", exc)
                ceo_text = (
                    "I apologize, Founder, but an unexpected error occurred while "
                    "communicating with executive leadership."
                )

            ceo_reply = self.company.add_message(
                sender_role="ceo",
                sender_name="CEO Agent",
                content=ceo_text,
                project_id=project_id,
                task_id=task_id,
            )

        return {
            "user_message": user_msg.to_dict(),
            "reply": ceo_reply.to_dict() if ceo_reply else None,
            "messages": [m.to_dict() for m in self.list_chat_messages(limit=50)],
        }

    # --------------------------------------------------------------------------
    # Structured Task Proposal Contract (STEP 4)
    # --------------------------------------------------------------------------

    def propose_task(self, founder_request: str) -> CEOActionProposal:
        """Evaluate a founder request and return a structured CEOActionProposal.

        This method translates natural-language founder intent into a machine-validated
        task proposal without persisting any Task, creating any TaskRun, or executing
        any specialist.

        Args:
            founder_request: Natural-language request from the founder.

        Returns:
            Validated CEOActionProposal adhering to schema_version '1.0'.

        Raises:
            ValueError: If founder_request is empty.
            ProposalError: If runtime execution, JSON parsing, or schema validation fails.
        """
        text = (founder_request or "").strip()
        if not text:
            raise ValueError("Founder request must not be empty.")

        prompt = build_task_proposal_prompt(text)
        result = self.runtime.execute(agent="ceo", prompt=prompt)

        if not result.success:
            logger.warning(
                "CEO runtime failed during propose_task (exit_code=%s, duration=%.2fms): %s",
                result.exit_code,
                result.duration_ms,
                result.stderr,
            )
            raise ProposalError(
                f"CEO runtime execution failed: {result.stderr or f'exit code {result.exit_code}'}"
            )

        return parse_and_validate_proposal(result.stdout)

    def accept_task_proposal(
        self,
        proposal: CEOActionProposal,
        project_id: str,
        task_id: Optional[str] = None,
    ) -> Task:
        """Ingest a validated CEOActionProposal into a registered Task in the Project.

        Converts an approved CEO proposal with action='propose_task' into a
        concrete Task domain entity associated with the given Project.

        This method is strictly deterministic:
        - It does NOT call an LLM or Antigravity runtime.
        - It does NOT execute the task or invoke any specialist.
        - It does NOT create a TaskRun or Artifact.

        Args:
            proposal: Validated CEOActionProposal instance.
            project_id: Identifier of an existing registered Project.
            task_id: Optional explicit task ID override.

        Returns:
            The registered Task entity with status PENDING.

        Raises:
            ValueError: If proposal is None or proposal.action is not 'propose_task'.
            ProjectNotFoundError: If project_id is not registered.
            InvalidAgentError: If proposal.assigned_agent is not a recognized specialist.
        """
        if not isinstance(proposal, CEOActionProposal):
            raise ValueError("Expected a valid CEOActionProposal instance.")

        if proposal.action != "propose_task":
            raise ValueError(
                f"Only proposals with action 'propose_task' can be accepted as tasks. "
                f"Received action: '{proposal.action}'."
            )

        # Ensure project exists (raises ProjectNotFoundError if unknown)
        project = self.get_project(project_id)

        # Validate specialist role against registered specialist roles
        assigned = (proposal.assigned_agent or "").strip().lower()
        if assigned not in REGISTERED_SPECIALIST_ROLES:
            raise InvalidAgentError(
                f"Cannot accept task proposal: assigned specialist '{proposal.assigned_agent}' "
                f"is not one of registered specialists: {sorted(REGISTERED_SPECIALIST_ROLES)}."
            )

        # Ingest deterministically into existing Task model
        task = self.create_task(
            project_id=project.id,
            title=proposal.title or "Untitled Task",
            goal=proposal.objective or "",
            task_id=task_id,
            constraints=list(proposal.constraints or []),
            required_roles=[assigned],
            expected_output=list(proposal.expected_output or []),
        )
        return task


