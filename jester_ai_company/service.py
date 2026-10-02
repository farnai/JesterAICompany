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

from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

from .core import (
    ALLOWED_HANDOFF_EDGES,
    Artifact,
    ArtifactInputRef,
    ArtifactType,
    ArtifactVerificationError,
    ChatMessage,
    Company,
    Employee,
    HandoffError,
    HandoffPolicyError,
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
from .ux_result import (
    UXResultParseError,
    UXResultValidationError,
    UXTaskResult,
    build_ux_execution_prompt,
    parse_and_validate_ux_result,
)
from .marketing_result import (
    MarketingResultParseError,
    MarketingResultValidationError,
    MarketingTaskResult,
    build_marketing_execution_prompt,
    parse_and_validate_marketing_result,
)
from .developer_result import (
    DeveloperResultParseError,
    DeveloperResultValidationError,
    DeveloperTaskResult,
    build_developer_execution_prompt,
    parse_and_validate_developer_result,
)
from .product_result import (
    ProductResultParseError,
    ProductResultValidationError,
    ProductTaskResult,
    build_product_execution_prompt,
    parse_and_validate_product_result,
)
from .materializer import (
    MAX_COMBINED_INPUT_ARTIFACT_SIZE_BYTES,
    MAX_INPUT_ARTIFACT_SIZE_BYTES,
    MaterializationError,
    format_qa_report,
    load_and_verify_input_artifact,
    materialize_code_patch_artifact,
    materialize_qa_report_artifact,
    materialize_specialist_artifact,
)
from .qa_result import (
    QAFailureReason,
    QAFinding,
    QAFindingSeverity,
    QAInputInvalidError,
    QAInspectionResult,
    QAInspectionStatus,
    QALineageMismatchError,
    QAPatchIntegrityError,
    QARecommendedAction,
    QAResultParseError,
    QAResultValidationError,
    QATestCase,
    RequirementCoverage,
    RequirementCoverageStatus,
    build_qa_inspection_prompt,
    parse_and_validate_qa_result,
)
from .research_result import (
    ResearchResultParseError,
    ResearchResultValidationError,
    ResearchTaskResult,
    build_research_execution_prompt,
    parse_and_validate_research_result,
)
from .proposal import (
    CEOActionProposal,
    ProposalError,
    REGISTERED_SPECIALIST_ROLES,
    build_task_proposal_prompt,
    parse_and_validate_proposal,
)
from .runtime import AntigravityRuntime, InvalidAgentError
from .execution_grant import (
    ExecutionGrant,
    GrantError,
    GrantValidationError,
    MissingApprovalError,
    PlanArtifactMismatchError,
    ProtectedPathError,
    StaleCommitError,
    TestModificationForbiddenError,
    VerificationAction,
)
from .developer_mutation import (
    DeveloperMutationError,
    DeveloperMutationParseError,
    DeveloperMutationResult,
    DeveloperMutationStatus,
    DeveloperMutationValidationError,
    build_developer_mutation_prompt,
    parse_and_validate_developer_mutation_result,
)
from .verification import (
    VerificationExecutionResult,
    VerificationStatus,
    execute_verification_action,
)
from .policy_hook import (
    WriteAuthorizationDecision,
    authorize_tool_mutation,
    install_execution_policy_hook,
)
from .worktree import (
    WorktreeAuditRecord,
    WorktreeConfinementError,
    WorktreeDiffResult,
    WorktreeError,
    WorktreeGitError,
    WorktreeManager,
    WorktreeSession,
    is_protected_path,
    is_test_file,
    resolve_repo_head_commit,
    sanitize_execution_environment,
    verify_workspace_path,
)

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


@dataclass
class BoundedDeveloperExecutionOutcome:
    """Outcome of a bounded Developer mutation execution within an isolated worktree."""
    grant_id: str
    status: str
    summary: str
    diff_result: Optional[WorktreeDiffResult] = None
    mutation_result: Optional[DeveloperMutationResult] = None
    audit_records: List[Dict[str, Any]] = field(default_factory=list)
    verification_results: List[Any] = field(default_factory=list)
    patch_artifact: Optional[Artifact] = None
    error: Optional[str] = None
    cleaned_up: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize outcome to dictionary."""
        return {
            "grant_id": self.grant_id,
            "status": self.status,
            "summary": self.summary,
            "diff_result": self.diff_result.to_dict() if self.diff_result else None,
            "mutation_result": self.mutation_result.to_dict() if self.mutation_result else None,
            "audit_records": self.audit_records,
            "verification_results": [
                vr.to_dict() if hasattr(vr, "to_dict") else vr
                for vr in self.verification_results
            ],
            "patch_artifact": self.patch_artifact.to_dict() if self.patch_artifact else None,
            "error": self.error,
            "cleaned_up": self.cleaned_up,
        }


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
        input_artifacts: Optional[List[ArtifactInputRef]] = None,
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
            input_artifacts=list(input_artifacts or []),
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

    # --------------------------------------------------------------------------
    # Specialist Task Execution (STEP 6B & STEP 7)
    # --------------------------------------------------------------------------

    def _execute_specialist_task(
        self,
        task: Task,
        agent_name: str,
        prompt: str,
        result_parser: Callable[[str], Any],
    ) -> TaskRun:
        """Internal generic specialist execution mechanism (STEP 7).

        Executes the lifecycle mechanics for a specialist task without
        knowing role-specific semantics:
        - Transitions TaskRun to RUNNING.
        - Invokes AntigravityRuntime for agent_name with prompt.
        - Handles execution failure, timeout, and empty output safely.
        - Applies the provided result_parser to parse & validate.
        - Completes TaskRun (SUCCESS or FAILED) and Task (COMPLETED or FAILED).
        - Persists validated structured result in Task.result.details.
        """
        run = task.create_run()
        run.status = RunStatus.RUNNING.value

        exec_result = self.runtime.execute(agent=agent_name, prompt=prompt)

        # 1. Handle runtime failures
        if not exec_result.success:
            if exec_result.timed_out:
                error_msg = f"{agent_name.capitalize()} runtime execution timed out after {exec_result.duration_ms:.0f}ms."
            else:
                error_msg = f"{agent_name.capitalize()} runtime execution failed with exit code {exec_result.exit_code}."
            logger.warning("%s task %s execution failed: %s", agent_name.capitalize(), task.id, error_msg)
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
            return run

        # 2. Handle empty output
        raw_stdout = (exec_result.stdout or "").strip()
        if not raw_stdout:
            error_msg = f"{agent_name.capitalize()} runtime execution produced empty output."
            logger.warning("%s task %s produced empty output", agent_name.capitalize(), task.id)
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
            return run

        # 3. Deterministic parsing and schema validation
        try:
            typed_result = result_parser(raw_stdout)
        except Exception as parse_err:
            error_msg = f"{agent_name.capitalize()} output validation failed: {parse_err}"
            logger.warning("%s task %s validation failed: %s", agent_name.capitalize(), task.id, error_msg)
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
            return run

        # 4. Materialize durable artifact & complete Run/Task
        if getattr(typed_result, "status", None) == "completed":
            try:
                materialize_specialist_artifact(
                    base_output_dir=self.output_dir,
                    task=task,
                    run=run,
                    agent_name=agent_name,
                    typed_result=typed_result,
                )
            except Exception as mat_err:
                error_msg = f"Artifact materialization failed: {mat_err}"
                logger.warning("%s task %s materialization failed: %s", agent_name.capitalize(), task.id, error_msg)
                run.complete(status=RunStatus.FAILED.value, error=error_msg)
                task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
                return run

            run.complete(status=RunStatus.SUCCESS.value)
            task.complete(
                status=TaskStatus.COMPLETED.value,
                summary=typed_result.summary,
                details=typed_result.to_dict(),
            )
        else:
            error_msg = getattr(typed_result, "summary", "") or f"{agent_name.capitalize()} agent reported task failure."
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(
                status=TaskStatus.FAILED.value,
                summary=f"Task execution failed: {error_msg}",
                details=typed_result.to_dict(),
            )

        return run


    # --------------------------------------------------------------------------
    # Artifact Handoff (STEP 10)
    # --------------------------------------------------------------------------

    def find_artifact(self, artifact_id: str) -> Optional[Tuple[Task, TaskRun, Artifact]]:
        """Find an artifact by ID across all projects, tasks, and runs.

        Returns (Task, TaskRun, Artifact) if found, else None.
        """
        for project in self.company.projects.values():
            for task in project.tasks.values():
                for run in task.runs:
                    for art in run.artifacts:
                        if art.id == artifact_id:
                            return (task, run, art)
        return None

    def attach_input_artifact(
        self,
        target_task_id: str,
        source_artifact_id: str,
        project_id: Optional[str] = None,
    ) -> ArtifactInputRef:
        """Attach an existing verified upstream Artifact as input to a target Task (STEP 10).

        Policy:
        - Target task must exist and be in PENDING status.
        - Target task required_roles must be exactly ['product'].
        - Upstream artifact must exist.
        - Upstream task must be COMPLETED.
        - Upstream taskrun must be SUCCESS.
        - Upstream artifact must be durable and have a valid sha256.
        - Upstream artifact producer_role must be 'research'.
        - No duplicate attachments of the same artifact to target task.
        """
        target_task = self.get_task(target_task_id, project_id=project_id)
        if target_task.status != TaskStatus.PENDING.value:
            raise InvalidTaskStateError(
                f"Cannot attach input artifact: target task '{target_task.id}' status is '{target_task.status}', expected '{TaskStatus.PENDING.value}'."
            )

        # Policy: Consumer single role check (STEP 10 & 11)
        target_roles = [r.strip().lower() for r in target_task.required_roles]
        if len(target_roles) != 1:
            raise HandoffPolicyError(
                f"Handoff policy violation: target task '{target_task.id}' required_roles is {target_task.required_roles}, expected exactly single specialist role."
            )
        consumer = target_roles[0]

        # Locate upstream lineage
        lineage = self.find_artifact(source_artifact_id)
        if not lineage:
            raise HandoffError(f"Artifact not found: '{source_artifact_id}'.")

        source_task, source_run, source_artifact = lineage

        # Verify upstream task is COMPLETED
        if source_task.status != TaskStatus.COMPLETED.value:
            raise HandoffPolicyError(
                f"Cannot consume artifact '{source_artifact.id}': upstream task '{source_task.id}' is '{source_task.status}', expected '{TaskStatus.COMPLETED.value}'."
            )

        # Verify upstream run is SUCCESS
        if source_run.status != RunStatus.SUCCESS.value:
            raise HandoffPolicyError(
                f"Cannot consume artifact '{source_artifact.id}': upstream run '{source_run.id}' is '{source_run.status}', expected '{RunStatus.SUCCESS.value}'."
            )

        # Verify artifact durability and hash
        if not source_artifact.durable:
            raise HandoffPolicyError(
                f"Cannot consume artifact '{source_artifact.id}': artifact is marked non-durable."
            )
        if not source_artifact.sha256:
            raise HandoffPolicyError(
                f"Cannot consume artifact '{source_artifact.id}': artifact has no recorded SHA-256."
            )

        # Policy: Check allowed handoff edges (STEP 10 & 11)
        producer = (source_artifact.producer_role or "").strip().lower()
        if (producer, consumer) not in ALLOWED_HANDOFF_EDGES:
            raise HandoffPolicyError(
                f"Handoff policy violation: handoff from '{producer}' to '{consumer}' is not permitted. Allowed edges: {sorted(ALLOWED_HANDOFF_EDGES)}."
            )

        # Duplicate check
        for existing in target_task.input_artifacts:
            if existing.artifact_id == source_artifact.id:
                raise HandoffError(
                    f"Artifact '{source_artifact.id}' is already attached to task '{target_task.id}'."
                )

        ref = ArtifactInputRef(
            artifact_id=source_artifact.id,
            run_id=source_run.id,
            sha256=source_artifact.sha256,
            producer_role=source_artifact.producer_role,
        )
        target_task.input_artifacts.append(ref)
        return ref

    def execute_product_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
    ) -> TaskRun:
        """Execute a registered PENDING Task assigned to Product Agent (STEP 6B & STEP 10).

        Validates that the task is PENDING and required_roles == ['product'].
        Validates and loads any declared input artifacts before run execution (preflight check).
        Constructs product execution prompt and delegates to generic execution mechanism.
        """
        task = self.get_task(task_id, project_id=project_id)

        # 1. Eligibility validation
        if task.status != TaskStatus.PENDING.value:
            raise InvalidTaskStateError(
                f"Cannot execute task '{task.id}': Task status is '{task.status}', expected '{TaskStatus.PENDING.value}'."
            )

        if not task.required_roles:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task has no required roles assigned."
            )

        normalized_roles = [r.strip().lower() for r in task.required_roles]
        if normalized_roles != ["product"]:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task is assigned to {task.required_roles}, expected exactly ['product']."
            )

        # 2. Preflight validation & loading of input artifacts (STEP 10)
        verified_artifacts = self._verify_and_load_input_artifacts(task)

        prompt = build_product_execution_prompt(
            task,
            verified_artifacts=verified_artifacts if verified_artifacts else None,
        )
        return self._execute_specialist_task(
            task=task,
            agent_name="product",
            prompt=prompt,
            result_parser=parse_and_validate_product_result,
        )

    def execute_research_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
    ) -> TaskRun:
        """Execute a registered PENDING Task assigned to Research Agent (STEP 7).

        Validates that the task is PENDING and required_roles == ['research'].
        Constructs research execution prompt and delegates to generic execution mechanism.
        """
        task = self.get_task(task_id, project_id=project_id)

        # 1. Eligibility validation
        if task.status != TaskStatus.PENDING.value:
            raise InvalidTaskStateError(
                f"Cannot execute task '{task.id}': Task status is '{task.status}', expected '{TaskStatus.PENDING.value}'."
            )

        if not task.required_roles:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task has no required roles assigned."
            )

        normalized_roles = [r.strip().lower() for r in task.required_roles]
        if normalized_roles != ["research"]:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task is assigned to {task.required_roles}, expected exactly ['research']."
            )

        prompt = build_research_execution_prompt(task)
        return self._execute_specialist_task(
            task=task,
            agent_name="research",
            prompt=prompt,
            result_parser=parse_and_validate_research_result,
        )

    def execute_ux_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
    ) -> TaskRun:
        """Execute a registered PENDING Task assigned to UX Agent (STEP 11).

        Validates that the task is PENDING and required_roles == ['ux'].
        Validates and loads any declared input artifacts before run execution (preflight check).
        Constructs UX execution prompt and delegates to generic execution mechanism.
        """
        task = self.get_task(task_id, project_id=project_id)

        # 1. Eligibility validation
        if task.status != TaskStatus.PENDING.value:
            raise InvalidTaskStateError(
                f"Cannot execute task '{task.id}': Task status is '{task.status}', expected '{TaskStatus.PENDING.value}'."
            )

        if not task.required_roles:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task has no required roles assigned."
            )

        normalized_roles = [r.strip().lower() for r in task.required_roles]
        if normalized_roles != ["ux"]:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task is assigned to {task.required_roles}, expected exactly ['ux']."
            )

        # 2. Preflight validation & loading of input artifacts (STEP 10 & 11)
        verified_artifacts = self._verify_and_load_input_artifacts(task)

        prompt = build_ux_execution_prompt(
            task,
            verified_artifacts=verified_artifacts if verified_artifacts else None,
        )
        return self._execute_specialist_task(
            task=task,
            agent_name="ux",
            prompt=prompt,
            result_parser=parse_and_validate_ux_result,
        )

    def _verify_and_load_input_artifacts(self, task: Task) -> List[Tuple[ArtifactInputRef, str]]:
        """Safely verify and load all declared input artifacts for a task (preflight check)."""
        verified_artifacts: List[Tuple[ArtifactInputRef, str]] = []
        for input_ref in task.input_artifacts:
            lineage = self.find_artifact(input_ref.artifact_id)
            if not lineage:
                raise ArtifactVerificationError(
                    f"Preflight failure: Input artifact '{input_ref.artifact_id}' could not be found in company state."
                )
            source_task, source_run, artifact = lineage

            # Verify upstream task and run state
            if source_task.status != TaskStatus.COMPLETED.value:
                raise ArtifactVerificationError(
                    f"Preflight failure: Upstream task '{source_task.id}' is '{source_task.status}', expected '{TaskStatus.COMPLETED.value}'."
                )
            if source_run.status != RunStatus.SUCCESS.value:
                raise ArtifactVerificationError(
                    f"Preflight failure: Upstream run '{source_run.id}' is '{source_run.status}', expected '{RunStatus.SUCCESS.value}'."
                )

            # Load and verify bytes, path, size, and hash
            content = load_and_verify_input_artifact(
                base_output_dir=Path(self.output_dir),
                artifact=artifact,
                expected_ref=input_ref,
            )
            verified_artifacts.append((input_ref, content))
        return verified_artifacts

    def execute_marketing_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
    ) -> TaskRun:
        """Execute a registered PENDING Task assigned to Marketing Agent (STEP 12).

        Validates that the task is PENDING and required_roles == ['marketing'].
        Validates and loads any declared input artifacts before run execution (preflight check).
        Constructs Marketing execution prompt and delegates to generic execution mechanism.
        """
        task = self.get_task(task_id, project_id=project_id)

        # 1. Eligibility validation
        if task.status != TaskStatus.PENDING.value:
            raise InvalidTaskStateError(
                f"Cannot execute task '{task.id}': Task status is '{task.status}', expected '{TaskStatus.PENDING.value}'."
            )

        if not task.required_roles:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task has no required roles assigned."
            )

        normalized_roles = [r.strip().lower() for r in task.required_roles]
        if normalized_roles != ["marketing"]:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task is assigned to {task.required_roles}, expected exactly ['marketing']."
            )

        # 2. Preflight validation & loading of input artifacts (STEP 10, 11 & 12)
        verified_artifacts = self._verify_and_load_input_artifacts(task)

        prompt = build_marketing_execution_prompt(
            task,
            verified_artifacts=verified_artifacts if verified_artifacts else None,
        )
        return self._execute_specialist_task(
            task=task,
            agent_name="marketing",
            prompt=prompt,
            result_parser=parse_and_validate_marketing_result,
        )

    def _get_repo_working_tree_state(self) -> str:
        """Capture a deterministic lightweight status of repository working tree."""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
            return res.stdout.strip()
        except Exception:
            return ""

    def execute_developer_planning_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
    ) -> TaskRun:
        """Execute a registered PENDING Task assigned to Developer Agent in PLANNING MODE (STEP 13A).

        Enforces:
        1. Eligibility: Task status == PENDING, required_roles == ['developer'].
        2. Exact Fan-In Shape: Exactly TWO input artifacts, exactly 1 Product and 1 UX, no duplicates.
        3. Preflight Verification: Upstream tasks COMPLETED, runs SUCCESS, hashes matching, <=100KB per artifact.
        4. Combined Size Limit: Sum of inputs <= MAX_COMBINED_INPUT_ARTIFACT_SIZE_BYTES (150KB).
        5. Canonical Ordering: Product requirements presented before UX specification.
        6. Read-Only Safety: Repository working tree verified before and after execution.
        """
        task = self.get_task(task_id, project_id=project_id)

        # 1. Eligibility validation
        if task.status != TaskStatus.PENDING.value:
            raise InvalidTaskStateError(
                f"Cannot execute task '{task.id}': Task status is '{task.status}', expected '{TaskStatus.PENDING.value}'."
            )

        if not task.required_roles:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task has no required roles assigned."
            )

        normalized_roles = [r.strip().lower() for r in task.required_roles]
        if normalized_roles != ["developer"]:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task is assigned to {task.required_roles}, expected exactly ['developer']."
            )

        # 2. Exact Fan-In Shape Validation (STEP 13A)
        if len(task.input_artifacts) != 2:
            raise HandoffPolicyError(
                f"Developer planning task '{task.id}' requires exactly 2 input artifacts (1 Product, 1 UX), found {len(task.input_artifacts)}."
            )

        ref1, ref2 = task.input_artifacts[0], task.input_artifacts[1]
        if ref1.artifact_id == ref2.artifact_id:
            raise HandoffPolicyError(
                f"Developer planning task '{task.id}' contains duplicate references to artifact '{ref1.artifact_id}'."
            )

        lineage1 = self.find_artifact(ref1.artifact_id)
        lineage2 = self.find_artifact(ref2.artifact_id)
        if not lineage1 or not lineage2:
            raise ArtifactVerificationError("One or more input artifacts could not be found in company state.")

        producer_roles = {
            (lineage1[2].producer_role or "").lower(),
            (lineage2[2].producer_role or "").lower(),
        }
        if producer_roles != {"product", "ux"}:
            raise HandoffPolicyError(
                f"Developer planning task requires exactly one 'product' artifact and one 'ux' artifact. Found roles: {sorted(producer_roles)}."
            )

        # 3. Preflight validation & loading of input artifacts
        verified_artifacts = self._verify_and_load_input_artifacts(task)

        # 4. Combined Size Limit check
        total_bytes = sum(len(content.encode("utf-8")) for _, content in verified_artifacts)
        if total_bytes > MAX_COMBINED_INPUT_ARTIFACT_SIZE_BYTES:
            raise ArtifactVerificationError(
                f"Combined input artifact size ({total_bytes} bytes) exceeds maximum allowed limit ({MAX_COMBINED_INPUT_ARTIFACT_SIZE_BYTES} bytes)."
            )

        prompt = build_developer_execution_prompt(
            task,
            verified_artifacts=verified_artifacts,
        )

        repo_state_before = self._get_repo_working_tree_state()

        run = self._execute_specialist_task(
            task=task,
            agent_name="developer",
            prompt=prompt,
            result_parser=parse_and_validate_developer_result,
        )

        repo_state_after = self._get_repo_working_tree_state()
        if repo_state_before != repo_state_after:
            raise ExecutionError(f"Repository mutation detected during Developer planning task '{task.id}'!")

        return run

    # --------------------------------------------------------------------------
    # Execution Grant & Isolated Worktree Infrastructure (STEP 13B-1)
    # --------------------------------------------------------------------------

    def create_execution_grant(
        self,
        task_id: str,
        plan_artifact_id: str,
        founder_approval_id: str,
        approved_files_to_modify: Optional[List[str]] = None,
        approved_files_to_create: Optional[List[str]] = None,
        verification_actions: Optional[List[VerificationAction]] = None,
        allow_test_modifications: bool = False,
        max_files_changed: int = 3,
        max_bytes_written: int = 100_000,
        max_verification_actions: int = 3,
        max_duration_seconds: int = 120,
        project_id: Optional[str] = None,
        grant_id: Optional[str] = None,
    ) -> ExecutionGrant:
        """Create and validate an immutable ExecutionGrant bound to verified company state (STEP 13B-1).

        Enforces:
        1. Explicit founder approval id (no auto-approvals).
        2. Task exists and is in registered state.
        3. Plan artifact exists in company state and was produced by 'developer'.
        4. Plan artifact is durable and has valid SHA-256 matching disk bytes.
        5. Upstream planning task was COMPLETED and run was SUCCESS.
        6. Base commit hash is resolved from target repo HEAD.
        7. Approved paths satisfy confinement, protected-path, and test-file policies.
        """
        import hashlib

        # 1. Founder approval check (Requirement 4)
        if not founder_approval_id or not str(founder_approval_id).strip():
            raise MissingApprovalError("Cannot create ExecutionGrant: founder_approval_id must not be empty.")

        # 2. Task lookup
        task = self.get_task(task_id, project_id=project_id)

        # 3. Plan artifact lookup and validation (Requirement 3)
        lineage = self.find_artifact(plan_artifact_id)
        if not lineage:
            raise PlanArtifactMismatchError(
                f"Plan artifact '{plan_artifact_id}' could not be found in company state."
            )

        source_task, source_run, artifact = lineage

        if (artifact.producer_role or "").lower() != "developer":
            raise PlanArtifactMismatchError(
                f"Plan artifact '{plan_artifact_id}' was produced by '{artifact.producer_role}', expected 'developer'."
            )

        if not artifact.durable:
            raise PlanArtifactMismatchError(
                f"Plan artifact '{plan_artifact_id}' is marked non-durable."
            )

        if source_task.status != TaskStatus.COMPLETED.value:
            raise PlanArtifactMismatchError(
                f"Upstream planning task '{source_task.id}' is '{source_task.status}', expected '{TaskStatus.COMPLETED.value}'."
            )

        if source_run.status != RunStatus.SUCCESS.value:
            raise PlanArtifactMismatchError(
                f"Upstream planning run '{source_run.id}' is '{source_run.status}', expected '{RunStatus.SUCCESS.value}'."
            )

        # 4. Verify disk bytes & SHA-256
        target_path = (self.output_dir / artifact.path).resolve()
        if not target_path.is_file():
            raise PlanArtifactMismatchError(
                f"Plan artifact file not found on disk at '{target_path}'."
            )
        computed_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()
        if computed_sha != artifact.sha256:
            raise PlanArtifactMismatchError(
                f"Plan artifact disk SHA mismatch: computed '{computed_sha}' != recorded '{artifact.sha256}'."
            )

        # 5. Resolve repo HEAD commit (Requirement 5)
        base_commit = resolve_repo_head_commit(self.repo_root)

        # 6. Generate unique grant_id if not provided
        gid = grant_id or f"grant_{task.id}_{uuid.uuid4().hex[:8]}"

        grant = ExecutionGrant(
            grant_id=gid,
            task_id=task.id,
            plan_artifact_id=artifact.id,
            plan_sha256=computed_sha,
            base_commit_hash=base_commit,
            approved_files_to_modify=tuple(approved_files_to_modify or []),
            approved_files_to_create=tuple(approved_files_to_create or []),
            verification_actions=tuple(verification_actions or []),
            allow_test_modifications=allow_test_modifications,
            max_files_changed=max_files_changed,
            max_bytes_written=max_bytes_written,
            max_verification_actions=max_verification_actions,
            max_duration_seconds=max_duration_seconds,
            network_enabled=False,
            founder_approval_id=str(founder_approval_id).strip(),
        )

        # Validate approved paths against protected and test policies upfront
        all_approved = list(grant.approved_files_to_modify) + list(grant.approved_files_to_create)
        for rel_path in all_approved:
            if is_protected_path(rel_path, protect_company_control=True):
                raise ProtectedPathError(f"Approved path '{rel_path}' is protected by company policy.")
            if is_test_file(rel_path) and not grant.allow_test_modifications:
                raise TestModificationForbiddenError(
                    f"Test file '{rel_path}' cannot be modified: grant.allow_test_modifications is False."
                )

        return grant

    def create_worktree_session(
        self,
        grant: ExecutionGrant,
        worktrees_dir: Optional[Path] = None,
    ) -> WorktreeSession:
        """Create an isolated Git worktree session bound to the approved ExecutionGrant."""
        manager = WorktreeManager(
            repo_root=self.repo_root,
            worktrees_dir=worktrees_dir or (Path(self.output_dir) / "worktrees"),
            protect_company_control=True,
        )
        return manager.create_worktree(grant)

    def execute_bounded_developer_mutation(
        self,
        grant: ExecutionGrant,
        instruction: str,
        timeout: Optional[float] = None,
        protect_company_control: bool = True,
    ) -> "BoundedDeveloperExecutionOutcome":
        """Execute real Developer agent for bounded code mutation inside an isolated worktree.

        Enforces:
        1. Base commit validation (current HEAD must equal grant.base_commit_hash).
        2. Plan artifact existence, developer producer role, and disk SHA-256 match.
        3. Detached isolated Git worktree creation (main repository untouched).
        4. Execution-scoped PreToolUse hook installation (denies unauthorized writes/commands before execution).
        5. Sanitized execution environment (secret-like tokens and keys stripped).
        6. Subprocess execution with bounded timeout.
        7. Structured output parsing into DeveloperMutationResult.
        8. Independent application-owned Git diff capture.
        9. Diff audit against ExecutionGrant (detects unauthorized modifications or deletions).
        10. Resource budget enforcement (max_files_changed, max_bytes_written).
        11. Guaranteed worktree cleanup on all exit paths.
        """
        # 1. Base commit check (Fail closed on stale repository)
        current_head = resolve_repo_head_commit(self.repo_root)
        if current_head != grant.base_commit_hash:
            return BoundedDeveloperExecutionOutcome(
                grant_id=grant.grant_id,
                status=DeveloperMutationStatus.POLICY_DENIED.value,
                summary="Execution denied: repository HEAD has moved since grant approval.",
                error=f"Current HEAD '{current_head}' != grant base_commit_hash '{grant.base_commit_hash}'.",
                cleaned_up=True,
            )

        # 2. Plan artifact validation
        lineage = self.find_artifact(grant.plan_artifact_id)
        if not lineage:
            return BoundedDeveloperExecutionOutcome(
                grant_id=grant.grant_id,
                status=DeveloperMutationStatus.POLICY_DENIED.value,
                summary="Execution denied: plan artifact not found in company service.",
                error=f"Plan artifact '{grant.plan_artifact_id}' not found.",
                cleaned_up=True,
            )
        source_task, source_run, plan_art = lineage
        if plan_art.sha256 != grant.plan_sha256:
            return BoundedDeveloperExecutionOutcome(
                grant_id=grant.grant_id,
                status=DeveloperMutationStatus.POLICY_DENIED.value,
                summary="Execution denied: plan artifact SHA mismatch.",
                error=f"Plan artifact SHA '{plan_art.sha256}' != grant SHA '{grant.plan_sha256}'.",
                cleaned_up=True,
            )

        # 3. Create isolated worktree
        manager = WorktreeManager(
            repo_root=self.repo_root,
            worktrees_dir=Path(self.output_dir) / "worktrees",
            protect_company_control=protect_company_control,
        )
        session = manager.create_worktree(grant)
        cleaned_up = False

        try:
            # 4. Ensure Developer agent definition is present in worktree
            worktree_agent_md = session.worktree_path / ".agents" / "agents" / "developer" / "agent.md"
            if not worktree_agent_md.exists():
                source_agent_md = self.repo_root / ".agents" / "agents" / "developer" / "agent.md"
                if source_agent_md.exists():
                    worktree_agent_md.parent.mkdir(parents=True, exist_ok=True)
                    worktree_agent_md.write_text(source_agent_md.read_text(encoding="utf-8"), encoding="utf-8")

            # 5. Install execution-scoped policy hook
            audit_log_path = install_execution_policy_hook(
                session.worktree_path,
                grant,
                protect_company_control=protect_company_control,
            )

            # 6. Sanitize environment
            sanitized_env = sanitize_execution_environment()

            # 7. Build dedicated mutation prompt
            prompt = build_developer_mutation_prompt(grant, instruction)

            # 8. Execute runtime
            exec_timeout = timeout or float(grant.max_duration_seconds)
            exec_res = self.runtime.execute(
                agent="developer",
                prompt=prompt,
                timeout=exec_timeout,
                workspace_dir=session.worktree_path,
                env=sanitized_env,
            )

            # 9. Read hook audit records
            audit_records: List[Dict[str, Any]] = []
            if audit_log_path.exists():
                for line in audit_log_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            audit_records.append(json.loads(line))
                        except Exception:
                            pass

            # 10. Check runtime exit status
            if exec_res.timed_out:
                outcome = BoundedDeveloperExecutionOutcome(
                    grant_id=grant.grant_id,
                    status=DeveloperMutationStatus.TIMEOUT.value,
                    summary="Developer execution timed out.",
                    audit_records=audit_records,
                    error=exec_res.stderr or "Timed out.",
                )
            else:
                # 11. Parse mutation result report
                mutation_res: Optional[DeveloperMutationResult] = None
                try:
                    mutation_res = parse_and_validate_developer_mutation_result(exec_res.stdout)
                except Exception as exc:
                    mutation_res = DeveloperMutationResult(
                        status="failed",
                        summary=f"Failed to parse structured output: {exc}",
                        raw_response=exec_res.stdout,
                    )

                # 12. Independent application-owned Git diff capture
                diff_res = session.capture_diff()

                # 13. Validate diff against ExecutionGrant
                if len(diff_res.deleted_files) > 0:
                    outcome = BoundedDeveloperExecutionOutcome(
                        grant_id=grant.grant_id,
                        status=DeveloperMutationStatus.UNAUTHORIZED_DIFF.value,
                        summary=f"Diff validation failed: file deletion detected: {diff_res.deleted_files}",
                        diff_result=diff_res,
                        mutation_result=mutation_res,
                        audit_records=audit_records,
                        error=f"Deleted files in diff: {diff_res.deleted_files}",
                    )
                else:
                    approved_mod = {f.strip("/").lower() for f in grant.approved_files_to_modify}
                    approved_create = {f.strip("/").lower() for f in grant.approved_files_to_create}
                    all_approved = approved_mod | approved_create

                    unauthorized_files: List[str] = []
                    for chg in diff_res.changed_files:
                        norm_chg = chg.replace("\\", "/").strip("/").lower()
                        if norm_chg not in all_approved:
                            unauthorized_files.append(chg)

                    if unauthorized_files:
                        outcome = BoundedDeveloperExecutionOutcome(
                            grant_id=grant.grant_id,
                            status=DeveloperMutationStatus.UNAUTHORIZED_DIFF.value,
                            summary=f"Diff validation failed: unauthorized file(s) modified: {unauthorized_files}",
                            diff_result=diff_res,
                            mutation_result=mutation_res,
                            audit_records=audit_records,
                            error=f"Unauthorized files in diff: {unauthorized_files}",
                        )
                    elif len(diff_res.changed_files) > grant.max_files_changed:
                        outcome = BoundedDeveloperExecutionOutcome(
                            grant_id=grant.grant_id,
                            status=DeveloperMutationStatus.BUDGET_EXCEEDED.value,
                            summary=f"Quota exceeded: {len(diff_res.changed_files)} files changed > limit {grant.max_files_changed}",
                            diff_result=diff_res,
                            mutation_result=mutation_res,
                            audit_records=audit_records,
                            error="Exceeded max_files_changed budget.",
                        )
                    elif len(diff_res.diff_bytes) > grant.max_bytes_written:
                        outcome = BoundedDeveloperExecutionOutcome(
                            grant_id=grant.grant_id,
                            status=DeveloperMutationStatus.BUDGET_EXCEEDED.value,
                            summary=f"Quota exceeded: {len(diff_res.diff_bytes)} bytes written > limit {grant.max_bytes_written}",
                            diff_result=diff_res,
                            mutation_result=mutation_res,
                            audit_records=audit_records,
                            error="Exceeded max_bytes_written budget.",
                        )
                    elif diff_res.is_binary:
                        outcome = BoundedDeveloperExecutionOutcome(
                            grant_id=grant.grant_id,
                            status=DeveloperMutationStatus.PATCH_CAPTURE_FAILED.value,
                            summary="Binary changes detected in diff; binary files are not supported in CODE_PATCH V1.",
                            diff_result=diff_res,
                            mutation_result=mutation_res,
                            audit_records=audit_records,
                            error="Binary files cannot be represented in CODE_PATCH.",
                        )
                    else:
                        # 15. Check if any tool denial occurred
                        any_denied = any(rec.get("decision") == "deny" for rec in audit_records)
                        if diff_res.is_empty and any_denied:
                            outcome = BoundedDeveloperExecutionOutcome(
                                grant_id=grant.grant_id,
                                status=DeveloperMutationStatus.POLICY_DENIED.value,
                                summary="All attempted modifications were denied by PreToolUse policy.",
                                diff_result=diff_res,
                                mutation_result=mutation_res,
                                audit_records=audit_records,
                                error="PreToolUse hook denied unauthorized tool calls.",
                            )
                        elif not exec_res.success and diff_res.is_empty:
                            outcome = BoundedDeveloperExecutionOutcome(
                                grant_id=grant.grant_id,
                                status=DeveloperMutationStatus.RUNTIME_FAILED.value,
                                summary=f"Developer execution failed with exit code {exec_res.exit_code}.",
                                diff_result=diff_res,
                                mutation_result=mutation_res,
                                audit_records=audit_records,
                                error=exec_res.stderr or f"Exit code {exec_res.exit_code}",
                            )
                        elif diff_res.is_empty:
                            outcome = BoundedDeveloperExecutionOutcome(
                                grant_id=grant.grant_id,
                                status=DeveloperMutationStatus.RUNTIME_FAILED.value,
                                summary="No modifications were produced by Developer Agent in worktree.",
                                diff_result=diff_res,
                                mutation_result=mutation_res,
                                audit_records=audit_records,
                                error="No changes produced in diff.",
                            )
                        else:
                            # 16. Verification Action Execution (STEP 13B-3)
                            veri_results: List[VerificationExecutionResult] = []
                            veri_actions = list(getattr(grant, "verification_actions", []))
                            max_veri = getattr(grant, "max_verification_actions", 3)

                            if len(veri_actions) > max_veri:
                                outcome = BoundedDeveloperExecutionOutcome(
                                    grant_id=grant.grant_id,
                                    status=DeveloperMutationStatus.VERIFICATION_FAILED.value,
                                    summary=f"Verification budget exceeded: {len(veri_actions)} actions > limit {max_veri}",
                                    diff_result=diff_res,
                                    mutation_result=mutation_res,
                                    audit_records=audit_records,
                                    error="Exceeded max_verification_actions budget.",
                                )
                            else:
                                all_passed = True
                                failure_outcome: Optional[BoundedDeveloperExecutionOutcome] = None

                                for va in veri_actions:
                                    vr = execute_verification_action(
                                        action=va,
                                        worktree_path=session.worktree_path,
                                        timeout=float(getattr(grant, "max_duration_seconds", 30.0)),
                                        sanitized_env=sanitized_env,
                                    )
                                    veri_results.append(vr)

                                    if vr.status == VerificationStatus.TIMEOUT.value:
                                        all_passed = False
                                        failure_outcome = BoundedDeveloperExecutionOutcome(
                                            grant_id=grant.grant_id,
                                            status=DeveloperMutationStatus.VERIFICATION_TIMEOUT.value,
                                            summary=f"Verification timed out on {va.action_type}: {va.target}",
                                            diff_result=diff_res,
                                            mutation_result=mutation_res,
                                            audit_records=audit_records,
                                            verification_results=veri_results,
                                            error=vr.error or "Verification timed out.",
                                        )
                                        break
                                    elif vr.status == VerificationStatus.EXECUTION_ERROR.value:
                                        all_passed = False
                                        failure_outcome = BoundedDeveloperExecutionOutcome(
                                            grant_id=grant.grant_id,
                                            status=DeveloperMutationStatus.VERIFICATION_EXECUTION_ERROR.value,
                                            summary=f"Verification execution error on {va.action_type}: {va.target}",
                                            diff_result=diff_res,
                                            mutation_result=mutation_res,
                                            audit_records=audit_records,
                                            verification_results=veri_results,
                                            error=vr.error or vr.stderr or "Verification execution error.",
                                        )
                                        break
                                    elif not vr.passed:
                                        all_passed = False
                                        failure_outcome = BoundedDeveloperExecutionOutcome(
                                            grant_id=grant.grant_id,
                                            status=DeveloperMutationStatus.VERIFICATION_FAILED.value,
                                            summary=f"Verification failed on {va.action_type}: {va.target} with exit code {vr.exit_code}",
                                            diff_result=diff_res,
                                            mutation_result=mutation_res,
                                            audit_records=audit_records,
                                            verification_results=veri_results,
                                            error=vr.stderr or vr.stdout or f"Verification failed with exit code {vr.exit_code}.",
                                        )
                                        break

                                if not all_passed and failure_outcome is not None:
                                    outcome = failure_outcome
                                else:
                                    # 17. Patch Materialization (STEP 13B-3)
                                    try:
                                        patch_artifact = materialize_code_patch_artifact(
                                            base_output_dir=self.output_dir,
                                            task=source_task,
                                            run=source_run,
                                            grant=grant,
                                            patch_text=diff_res.diff_text,
                                            changed_files=diff_res.changed_files,
                                            verifications=veri_results,
                                            filename="developer_changes.patch",
                                        )
                                        outcome = BoundedDeveloperExecutionOutcome(
                                            grant_id=grant.grant_id,
                                            status=DeveloperMutationStatus.SUCCESS.value,
                                            summary=f"Developer mutation succeeded and verified. CODE_PATCH artifact materialized: {patch_artifact.path}",
                                            diff_result=diff_res,
                                            mutation_result=mutation_res,
                                            audit_records=audit_records,
                                            verification_results=veri_results,
                                            patch_artifact=patch_artifact,
                                        )
                                    except MaterializationError as mat_err:
                                        err_str = str(mat_err)
                                        status_val = (
                                            DeveloperMutationStatus.ARTIFACT_HASH_MISMATCH.value
                                            if "mismatch" in err_str
                                            else DeveloperMutationStatus.ARTIFACT_MATERIALIZATION_FAILED.value
                                        )
                                        outcome = BoundedDeveloperExecutionOutcome(
                                            grant_id=grant.grant_id,
                                            status=status_val,
                                            summary=f"Failed to materialize CODE_PATCH artifact: {mat_err}",
                                            diff_result=diff_res,
                                            mutation_result=mutation_res,
                                            audit_records=audit_records,
                                            verification_results=veri_results,
                                            error=err_str,
                                        )
        finally:
            cleanup_success = False
            try:
                session.remove()
                cleanup_success = True
            except Exception as clean_err:
                logger.error("Failed to clean up worktree: %s", clean_err)
                cleanup_success = False

            if outcome is not None:
                outcome.cleaned_up = cleanup_success
                if not cleanup_success and outcome.status == DeveloperMutationStatus.SUCCESS.value:
                    outcome.status = DeveloperMutationStatus.CLEANUP_FAILED.value
                    outcome.error = "Worktree cleanup failed after execution."

        return outcome

    # --------------------------------------------------------------------------
    # QA Independent Inspection Execution (STEP 14A)
    # --------------------------------------------------------------------------

    def execute_qa_inspection_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
        code_patch_artifact_id: Optional[str] = None,
    ) -> TaskRun:
        """Execute an independent QA Agent inspection of a verified CODE_PATCH against upstream requirements (STEP 14A).

        Enforces:
        1. Role & Eligibility: Task status == PENDING, required_roles == ['qa'].
        2. Input Resolution & Lineage Validation:
           - Resolves canonical Product, optional UX, Developer Plan, and CODE_PATCH artifacts.
           - Rejects missing, duplicate, or mismatched inputs (fail closed).
           - Verifies Developer Plan was derived from the same Product (and UX) artifacts.
           - Verifies CODE_PATCH was produced under the matching Developer Plan.
        3. CODE_PATCH Integrity & Preflight Verification:
           - Verifies physical file existence on disk.
           - Recomputes SHA-256 and validates match against recorded and reference hashes.
           - Validates base commit metadata is non-empty.
           - Validates that Developer verification outcomes are present and 100% PASS.
           - Fails closed on tampered, unverified, or failed patch.
        4. Independent Inspection Execution:
           - Constructs prompt with clear prompt-injection boundary (patch/source as UNTRUSTED DATA).
           - Verifies repository working tree state before execution.
           - Executes real `agy --agent qa`.
           - Enforces zero repository mutation (working tree before == working tree after).
        5. Deterministic Parsing & Validation:
           - Strict parsing into QAInspectionResult (schema_version "1.0").
           - Status must be one of: READY_FOR_QA_EXECUTION, NEEDS_DEVELOPER_ATTENTION, BLOCKED.
           - Structured findings with controlled severities.
        6. Durable QA Artifact Materialization:
           - Materializes QA_REPORT ("qa_report.md") with companion ".meta.json".
           - Attaches complete provenance lineage back to Product, UX, Plan, Grant, Patch, Commit.
           - Validates readback SHA-256.
        """
        task = self.get_task(task_id, project_id=project_id)

        # 1. Eligibility validation
        if task.status != TaskStatus.PENDING.value:
            raise InvalidTaskStateError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] Cannot execute task '{task.id}': Task status is '{task.status}', expected '{TaskStatus.PENDING.value}'."
            )

        if not task.required_roles:
            raise ValueError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] Cannot execute task '{task.id}': Task has no required roles assigned."
            )

        normalized_roles = [r.strip().lower() for r in task.required_roles]
        if normalized_roles != ["qa"]:
            raise ValueError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] Cannot execute task '{task.id}': Task is assigned to {task.required_roles}, expected exactly ['qa']."
            )

        # 2. Input Artifacts Categorization & Resolution
        if code_patch_artifact_id:
            already_attached = any(inp.artifact_id == code_patch_artifact_id for inp in task.input_artifacts)
            if not already_attached:
                self.attach_input_artifact(task.id, code_patch_artifact_id, project_id=project_id)

        if not task.input_artifacts:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA task '{task.id}' has no input artifacts attached."
            )

        product_inputs = []
        ux_inputs = []
        plan_inputs = []
        patch_inputs = []

        for ref in task.input_artifacts:
            lineage = self.find_artifact(ref.artifact_id)
            if not lineage:
                raise QAInputInvalidError(
                    f"[{QAFailureReason.QA_INPUT_INVALID.value}] Input artifact '{ref.artifact_id}' could not be found in company state."
                )
            src_task, src_run, art = lineage

            # Classify artifact
            if art.artifact_type == ArtifactType.SPECIFICATION.value or (art.producer_role or "").lower() == "product":
                product_inputs.append((ref, art, src_task))
            elif art.artifact_type == ArtifactType.UX_SPECIFICATION.value or (art.producer_role or "").lower() == "ux":
                ux_inputs.append((ref, art, src_task))
            elif art.artifact_type == ArtifactType.DEVELOPER_PLAN_REPORT.value or art.name == "developer_plan_report.md":
                plan_inputs.append((ref, art, src_task))
            elif art.artifact_type == ArtifactType.CODE_PATCH.value or art.name.endswith(".patch"):
                patch_inputs.append((ref, art, src_task))
            else:
                raise QAInputInvalidError(
                    f"[{QAFailureReason.QA_INPUT_INVALID.value}] Unrecognized input artifact type '{art.artifact_type}' for QA task."
                )

        if len(product_inputs) != 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA task requires exactly 1 Product specification artifact, found {len(product_inputs)}."
            )
        prod_ref, prod_art, prod_task = product_inputs[0]

        if len(plan_inputs) != 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA task requires exactly 1 Developer Plan artifact, found {len(plan_inputs)}."
            )
        plan_ref, plan_art, plan_task = plan_inputs[0]

        if len(patch_inputs) != 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA task requires exactly 1 CODE_PATCH artifact, found {len(patch_inputs)}."
            )
        patch_ref, patch_art, patch_task = patch_inputs[0]

        if len(ux_inputs) > 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA task cannot have more than 1 UX artifact, found {len(ux_inputs)}."
            )
        ux_ref, ux_art, ux_task = ux_inputs[0] if ux_inputs else (None, None, None)

        # 3. Lineage Validation
        plan_consumed_prods = {inp.artifact_id for inp in plan_task.input_artifacts if (inp.producer_role or "").lower() == "product"}
        if prod_art.id not in plan_consumed_prods:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] Product artifact '{prod_art.id}' does not match the Developer Plan's upstream Product artifact '{sorted(plan_consumed_prods)}'."
            )

        plan_consumed_ux = {inp.artifact_id for inp in plan_task.input_artifacts if (inp.producer_role or "").lower() == "ux"}
        if plan_consumed_ux:
            if ux_art is None:
                raise QALineageMismatchError(
                    f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] Developer Plan consumed UX artifact '{sorted(plan_consumed_ux)}', but no UX artifact was provided to QA task."
                )
            if ux_art.id not in plan_consumed_ux:
                raise QALineageMismatchError(
                    f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] UX artifact '{ux_art.id}' does not match the Developer Plan's upstream UX artifact '{sorted(plan_consumed_ux)}'."
                )
        else:
            if ux_art is not None:
                raise QALineageMismatchError(
                    f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] QA task was provided UX artifact '{ux_art.id}', but Developer Plan did not consume any UX artifact."
                )

        patch_meta = patch_art.metadata or {}
        patch_plan_id = patch_meta.get("plan_artifact_id")
        patch_plan_sha = patch_meta.get("plan_sha256")
        if not patch_plan_id or patch_plan_id != plan_art.id:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] CODE_PATCH was not created from Developer Plan '{plan_art.id}' (recorded: '{patch_plan_id}')."
            )
        if not patch_plan_sha or patch_plan_sha != plan_art.sha256:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] CODE_PATCH plan_sha256 mismatch: recorded '{patch_plan_sha}' != actual '{plan_art.sha256}'."
            )

        # 4. CODE_PATCH Integrity & Preflight Verification
        if patch_ref.sha256 != patch_art.sha256:
            raise QAPatchIntegrityError(
                f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH input reference SHA '{patch_ref.sha256}' != recorded SHA '{patch_art.sha256}'."
            )

        patch_path = (Path(self.output_dir) / patch_art.path).resolve()
        if not patch_path.is_file():
            raise QAPatchIntegrityError(
                f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH file not found on disk at '{patch_path}'."
            )

        patch_bytes = patch_path.read_bytes()
        actual_sha = hashlib.sha256(patch_bytes).hexdigest()
        if actual_sha != patch_art.sha256:
            raise QAPatchIntegrityError(
                f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH physical file tampered: actual SHA '{actual_sha}' != recorded SHA '{patch_art.sha256}'."
            )

        base_commit = patch_meta.get("base_commit_hash")
        if not base_commit or not isinstance(base_commit, str) or not base_commit.strip():
            raise QAPatchIntegrityError(
                f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH metadata missing valid base_commit_hash."
            )

        veri_outcomes = patch_meta.get("verification_outcomes", [])
        if not veri_outcomes or not isinstance(veri_outcomes, list):
            raise QAPatchIntegrityError(
                f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH is unverified: metadata contains no verification outcomes."
            )

        for idx, vo in enumerate(veri_outcomes):
            vo_status = vo.get("status") if isinstance(vo, dict) else getattr(vo, "status", None)
            vo_exit = vo.get("exit_code") if isinstance(vo, dict) else getattr(vo, "exit_code", -1)
            if vo_status != "PASS" or vo_exit != 0:
                raise QAPatchIntegrityError(
                    f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH verification failed at index {idx} (status='{vo_status}', exit_code={vo_exit}). Cannot inspect unverified or failing patch."
                )

        # 5. Load and verify input contents
        product_content = load_and_verify_input_artifact(Path(self.output_dir), prod_art, prod_ref)
        plan_content = load_and_verify_input_artifact(Path(self.output_dir), plan_art, plan_ref)
        ux_content = load_and_verify_input_artifact(Path(self.output_dir), ux_art, ux_ref) if ux_art and ux_ref else None
        patch_text = patch_bytes.decode("utf-8")
        changed_files = patch_meta.get("changed_files", [])
        dev_summary = plan_task.result.summary if plan_task.result else None

        prompt = build_qa_inspection_prompt(
            task=task,
            product_content=product_content,
            developer_plan_content=plan_content,
            code_patch_text=patch_text,
            changed_files=changed_files,
            verification_evidence=veri_outcomes,
            ux_content=ux_content,
            developer_summary=dev_summary,
        )

        lineage_metadata: Dict[str, Any] = {
            "product_artifact_id": prod_art.id,
            "product_sha256": prod_art.sha256,
            "ux_artifact_id": ux_art.id if ux_art else None,
            "ux_sha256": ux_art.sha256 if ux_art else None,
            "developer_plan_artifact_id": plan_art.id,
            "developer_plan_sha256": plan_art.sha256,
            "execution_grant_id": patch_meta.get("execution_grant_id", ""),
            "code_patch_artifact_id": patch_art.id,
            "code_patch_sha256": patch_art.sha256,
            "base_commit_hash": base_commit,
            "verification_evidence": veri_outcomes,
        }

        # 6. Execute QA Agent under zero-mutation invariant
        repo_state_before = self._get_repo_working_tree_state()

        run = self._execute_qa_specialist_task(
            task=task,
            prompt=prompt,
            lineage_metadata=lineage_metadata,
        )

        repo_state_after = self._get_repo_working_tree_state()
        if repo_state_before != repo_state_after:
            raise ExecutionError(f"Repository mutation detected during QA inspection task '{task.id}'!")

        return run

    def _execute_qa_specialist_task(
        self,
        task: Task,
        prompt: str,
        lineage_metadata: Dict[str, Any],
    ) -> TaskRun:
        """Internal execution lifecycle for QA Agent inspection (STEP 14A)."""
        run = task.create_run()
        run.status = RunStatus.RUNNING.value

        exec_result = self.runtime.execute(agent="qa", prompt=prompt)

        # 1. Handle runtime failures
        if not exec_result.success:
            if exec_result.timed_out:
                error_msg = f"[{QAFailureReason.QA_RUNTIME_FAILED.value}] QA runtime execution timed out after {exec_result.duration_ms:.0f}ms."
            else:
                error_msg = f"[{QAFailureReason.QA_RUNTIME_FAILED.value}] QA runtime execution failed with exit code {exec_result.exit_code}."
            logger.warning("QA task %s execution failed: %s", task.id, error_msg)
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
            return run

        # 2. Handle empty output
        raw_stdout = (exec_result.stdout or "").strip()
        if not raw_stdout:
            error_msg = f"[{QAFailureReason.QA_OUTPUT_INVALID.value}] QA runtime execution produced empty output."
            logger.warning("QA task %s produced empty output", task.id)
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
            return run

        # 3. Deterministic parsing and schema validation
        try:
            typed_result = parse_and_validate_qa_result(raw_stdout)
        except Exception as parse_err:
            error_msg = f"[{QAFailureReason.QA_OUTPUT_INVALID.value}] QA output validation failed: {parse_err}"
            logger.warning("QA task %s validation failed: %s", task.id, error_msg)
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
            return run

        # 4. Materialize durable QA_REPORT artifact
        try:
            materialize_qa_report_artifact(
                base_output_dir=Path(self.output_dir),
                task=task,
                run=run,
                typed_result=typed_result,
                lineage_metadata=lineage_metadata,
            )
        except Exception as mat_err:
            error_msg = f"[{QAFailureReason.QA_ARTIFACT_FAILED.value}] Artifact materialization failed: {mat_err}"
            logger.warning("QA task %s materialization failed: %s", task.id, error_msg)
            run.complete(status=RunStatus.FAILED.value, error=error_msg)
            task.complete(status=TaskStatus.FAILED.value, summary=f"Task execution failed: {error_msg}")
            return run

        # 5. Complete Run and Task with structured QA details
        run.complete(status=RunStatus.SUCCESS.value)
        task.complete(
            status=TaskStatus.COMPLETED.value,
            summary=f"QA Inspection complete: status={typed_result.status}. {typed_result.summary}",
            details=typed_result.to_dict(),
        )
        return run








