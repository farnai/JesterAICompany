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

from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from .core import (
    Artifact,
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
    ):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.company = company or create_default_company(self.repo_root)
        self.output_dir = Path(output_dir)
        self.verbose = verbose
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
