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
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import subprocess
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
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
    materialize_developer_repair_plan_artifact,
    materialize_developer_qa_repair_report_artifact,
    materialize_qa_report_artifact,
    materialize_qa_execution_report_artifact,
    materialize_real_repo_apply_report_artifact,
    materialize_specialist_artifact,
)
from .real_repo_apply import (
    ApprovalInvalidError,
    BaseCommitMismatchError,
    CandidateNotEligibleError,
    ConcurrentApplyError,
    CrashRecoveryBlockError,
    CrashStateClassification,
    CrossProjectMismatchError,
    GrantExpiredError,
    GrantReplayedError,
    PatchApplyFailedError,
    PatchPrecheckFailedError,
    PostApplyDiffMismatchError,
    ProposalMismatchError,
    RealRepoApplyError,
    RealRepoApplyGrant,
    RealRepoApplyLock,
    RealRepoApplyProposal,
    RealRepoApplyResult,
    RealRepoApplyStatus,
    RepositoryStateChangedError,
    RepositoryStateFingerprint,
    RollbackFailedError,
    TargetRepositoryDirtyError,
    TargetRepositoryIdentity,
    TargetRepositoryInvalidError,
    apply_code_patch_to_real_repo,
    build_real_repo_apply_proposal,
    classify_crash_state,
    compute_repo_fingerprint,
    derive_real_repo_apply_grant,
    format_real_repo_apply_proposal_report,
    format_real_repo_apply_report,
    precheck_code_patch_applicability,
    rollback_real_repo_apply,
    validate_candidate_eligibility,
    validate_real_repo_diff,
    verify_target_repo_cleanliness,
)
from .durable_storage import (
    CompanyRunNotFoundError,
    DurableRunStorage,
    GrantIntegrityError,
    GrantNotFoundError,
    ProposalIntegrityError,
    ProposalNotFoundError,
    ProposalPruneForbiddenError,
    StorageError,
    atomic_write_text,
)
from .project import (
    DEFAULT_PROJECT_REGISTRY,
    Project as RepositoryProject,
    ProjectRegistry,
    RepositoryPolicy,
    RepositoryRef,
    TargetRepositoryMismatchError,
    TargetRepositoryVerification,
    validate_grant_against_project_policy,
    verify_target_repository_identity,
)
from .knowledge import (
    DEFAULT_KNOWLEDGE_REGISTRY,
    ProjectContextExcerpt,
    ProjectKnowledgeCatalog,
    ProjectKnowledgeManifest,
    ProjectKnowledgeRegistry,
    ProjectKnowledgeSource,
    RoleKnowledgePolicy,
)
from .repair import (
    MAX_REPAIR_ITERATIONS,
    DeveloperQARepairLoopResult,
    DeveloperRepairPlan,
    DeveloperRepairTask,
    RepairAttemptRecord,
    RepairEligibilityClassification,
    RepairError,
    RepairWorkflowStatus,
    build_developer_repair_planning_prompt,
    build_developer_repair_task,
    classify_repair_eligibility,
    derive_repair_execution_grant,
    parse_and_validate_developer_repair_plan,
    reconstruct_qa_execution_context,
)
from .qa_execution import (
    QAActionAuthorizationDecision,
    QADiffMismatchError,
    QAExecutionActionAudit,
    QAExecutionError,
    QAExecutionOutcome,
    QAExecutionStatus,
    QAExecutionVerdictResult,
    QAFinalVerdict,
    QAPatchApplyError,
    QARequirementExecutionEvaluation,
    QAVerdictValidationError,
    apply_code_patch_to_worktree,
    authorize_and_convert_qa_actions,
    build_qa_verdict_prompt,
    enforce_deterministic_verdict_constraints,
    parse_and_validate_qa_verdict,
    validate_applied_patch_diff,
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
    build_qa_planning_execution_prompt,
    parse_and_validate_qa_planning_result,
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
from .orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    EmployeeResultSummary,
    HumanEscalation,
    OrchestrationError,
    PlanValidationError,
    PROHIBITED_QA_CAPABILITIES,
    SUPPORTED_QA_CAPABILITIES,
    TransitionPolicyError,
    UnsupportedRoleError,
    WorkItemState,
)
from .dag import (
    MAX_PLANNED_WORK_ITEMS,
    select_ready_work_items,
    validate_dag_structure,
)
from .engineering_pipeline import EngineeringPipelineAdapter
from .context import (
    assemble_specialist_context,
)
from .ceo_contract import (
    build_ceo_planning_prompt,
    parse_and_validate_ceo_plan,
)
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
        enable_engineering_pipeline: bool = True,
        durable_storage: Optional[DurableRunStorage] = None,
        is_production: bool = False,
    ):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.company = company or create_default_company(self.repo_root)
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.runtime = runtime or AntigravityRuntime(repo_root=self.repo_root)
        self.enable_engineering_pipeline = enable_engineering_pipeline
        self.is_production = is_production
        self.executor = TaskExecutor(
            company=self.company,
            output_dir=str(self.output_dir),
            verbose=self.verbose,
            repo_root=self.repo_root,
        )
        self.durable_storage = durable_storage or DurableRunStorage(
            storage_root=self.output_dir,
            is_production=is_production,
        )
        self._real_repo_apply_proposals: Dict[str, RealRepoApplyProposal] = {}
        self._real_repo_apply_grants: Dict[str, RealRepoApplyGrant] = {}
        self._company_runs: Dict[str, CompanyRun] = {}
        self.project_registry: ProjectRegistry = ProjectRegistry()
        self.knowledge_registry: ProjectKnowledgeRegistry = ProjectKnowledgeRegistry()

    @classmethod
    def create_production(
        cls,
        repo_root: Optional[Path] = None,
        workspace_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
    ) -> "CompanyService":
        """Factory for production CompanyService using explicit durable workspace (STEP 20A)."""
        root = (repo_root or Path(__file__).resolve().parent.parent).resolve()
        durable_root = Path(workspace_dir or root / ".runs").resolve()
        durable_storage = DurableRunStorage(storage_root=durable_root, is_production=True)
        return cls(
            output_dir=str(durable_root),
            repo_root=root,
            verbose=verbose,
            durable_storage=durable_storage,
            is_production=True,
        )

    # --------------------------------------------------------------------------
    # Repository Project Management (STEP 19B)
    # --------------------------------------------------------------------------

    def register_repository_project(
        self,
        project: RepositoryProject,
        validate_repo: bool = True,
    ) -> RepositoryProject:
        """Register a repository-backed Project under the generic ProjectRegistry."""
        return self.project_registry.register_project(project, validate_repo=validate_repo)

    def get_repository_project(self, project_id: str) -> Optional[RepositoryProject]:
        """Retrieve a repository-backed Project from the ProjectRegistry."""
        return self.project_registry.get_project(project_id)

    def require_repository_project(self, project_id: str) -> RepositoryProject:
        """Require a registered repository-backed Project or raise ProjectNotFoundError."""
        return self.project_registry.require_project(project_id)

    def list_repository_projects(self) -> List[RepositoryProject]:
        """List all registered repository-backed Projects."""
        return self.project_registry.list_projects()

    # --------------------------------------------------------------------------
    # Project Knowledge Management (STEP 19C-B)
    # --------------------------------------------------------------------------

    def register_project_knowledge_manifest(
        self,
        manifest: ProjectKnowledgeManifest,
    ) -> None:
        """Register a knowledge manifest associated with a registered Project."""
        self.knowledge_registry.register_manifest(manifest)

    def get_project_knowledge_manifest(self, project_id: str) -> Optional[ProjectKnowledgeManifest]:
        """Retrieve the configured knowledge manifest for a Project."""
        return self.knowledge_registry.get_manifest(project_id)

    def get_project_knowledge_catalog(self, project_id: str) -> Optional[ProjectKnowledgeCatalog]:
        """Obtain an operational ProjectKnowledgeCatalog for a Project if configured."""
        manifest = self.knowledge_registry.get_manifest(project_id)
        if not manifest:
            return None
        repo_proj = self.project_registry.get_project(project_id)
        if not repo_proj:
            return None
        return ProjectKnowledgeCatalog(
            manifest=manifest,
            repo_policy=repo_proj.policy,
            repo_root=repo_proj.repository.root_path,
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
                            sha256=a.get("sha256"),
                            producer_role=a.get("producer_role"),
                            metadata=a.get("metadata"),
                            artifact_id=a.get("id") or a.get("artifact_id"),
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
                error_msg = f"{agent_name.capitalize()} runtime execution failed with exit code {exec_result.exit_code}. stderr: {exec_result.stderr}. stdout: {exec_result.stdout[:500]}"
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
        res_status = str(getattr(typed_result, "status", "")).strip().upper()
        if agent_name == "qa":
            is_success = res_status in ("READY_FOR_QA_EXECUTION", "NEEDS_DEVELOPER_ATTENTION", "COMPLETED")
        else:
            is_success = res_status == "COMPLETED"

        if is_success:
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
        Supports durable rehydration from CompanyRuns and durable proposals if service was reconstructed.
        """
        for project in self.company.projects.values():
            for task in project.tasks.values():
                for run in task.runs:
                    for art in run.artifacts:
                        if art.id == artifact_id:
                            return (task, run, art)

        clean_id = (artifact_id or "").strip()
        if not clean_id:
            return None

        # Rehydrate from in-memory CompanyRuns
        for c_run in list(self._company_runs.values()):
            art_tuple = self._resolve_artifact_from_company_run(c_run, clean_id)
            if art_tuple:
                return art_tuple

        # Rehydrate from durable storage CompanyRuns
        if hasattr(self, "durable_storage") and self.durable_storage:
            try:
                for c_run in self.durable_storage.list_company_runs():
                    if c_run.run_id not in self._company_runs:
                        self._company_runs[c_run.run_id] = c_run
                    art_tuple = self._resolve_artifact_from_company_run(c_run, clean_id)
                    if art_tuple:
                        return art_tuple
            except Exception:
                pass

            # Fallback: check durable storage proposals for matching code patch artifact
            try:
                for prop in self.durable_storage.list_proposals():
                    if prop.code_patch_artifact_id == clean_id:
                        patch_file = self.durable_storage.proposals_dir / prop.proposal_id / "patch.diff"
                        if patch_file.is_file():
                            rel_path = str(patch_file.relative_to(self.output_dir))
                            art = Artifact(
                                id=clean_id,
                                name="patch.diff",
                                artifact_type=ArtifactType.CODE_PATCH.value,
                                path=rel_path,
                                durable=True,
                                sha256=prop.code_patch_sha256,
                                run_id=prop.company_run_id,
                                producer_role="developer",
                            )
                            default_proj = self.ensure_default_project()
                            task_id = f"task_{clean_id}"
                            task = default_proj.tasks.get(task_id) or default_proj.create_task(
                                task_id=task_id,
                                title=f"Task for {clean_id}",
                                goal=f"Durable proposal patch for {prop.proposal_id}",
                            )
                            run_id = f"run_{clean_id}"
                            task_run = next((r for r in task.runs if r.id == run_id), None)
                            if not task_run:
                                task_run = TaskRun(id=run_id, task_id=task.id, attempt_number=len(task.runs) + 1)
                                task.runs.append(task_run)
                            if not any(a.id == art.id for a in task_run.artifacts):
                                task_run.artifacts.append(art)
                            return (task, task_run, art)
            except Exception:
                pass

        return None

    def _resolve_artifact_from_company_run(
        self,
        c_run: Any,
        artifact_id: str,
    ) -> Optional[Tuple[Task, TaskRun, Artifact]]:
        """Rehydrate an Artifact from a CompanyRun's employee_summaries into company project state."""
        for summary in getattr(c_run, "employee_summaries", []):
            for ref in summary.artifact_refs:
                if ref.get("artifact_id") == artifact_id:
                    rel_path = ref.get("path", "")
                    art_type = ref.get("type", ArtifactType.SPECIFICATION.value)
                    art = Artifact(
                        id=artifact_id,
                        name=ref.get("name", "artifact"),
                        artifact_type=art_type,
                        path=rel_path,
                        durable=True,
                        sha256=ref.get("sha256"),
                        run_id=summary.run_id,
                        producer_role=summary.role,
                    )
                    proj_id = getattr(c_run, "project_id", None)
                    proj = self.company.projects.get(proj_id) if proj_id else None
                    if not proj:
                        proj = self.ensure_default_project()
                    task = proj.tasks.get(summary.task_id)
                    if not task:
                        task = proj.create_task(
                            task_id=summary.task_id,
                            title=f"Task: {summary.task_id}",
                            goal=summary.summary or f"Specialist task {summary.task_id}",
                        )
                    task_run = next((r for r in task.runs if r.id == summary.run_id), None)
                    if not task_run:
                        task_run = TaskRun(id=summary.run_id, task_id=task.id, attempt_number=len(task.runs) + 1)
                        task.runs.append(task_run)
                    if not any(a.id == art.id for a in task_run.artifacts):
                        task_run.artifacts.append(art)
                    return (task, task_run, art)
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

    def execute_qa_planning_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> TaskRun:
        """Execute a registered PENDING Task assigned to QA for planning/audit work (STEP 23B.1).

        Enforces:
        1. Role & Eligibility: Task status == PENDING, required_roles == ['qa'].
        2. Capability Validation: Capability must be in SUPPORTED_QA_CAPABILITIES.
           Prohibits certification, grants, patch verification, or apply actions.
        3. Preflight validation & loading of declared input artifacts.
        4. Independent Specialist Execution via generic runner with QA planning prompt.
        5. Deterministic validation via parse_and_validate_qa_planning_result.
        6. Durable QA Report materialization ('qa_report.md').
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
        if normalized_roles != ["qa"]:
            raise ValueError(
                f"Cannot execute task '{task.id}': Task is assigned to {task.required_roles}, expected exactly ['qa']."
            )

        # 2. Capability resolution & validation
        cap = (capability or "").strip().lower()
        if not cap:
            for out in task.expected_output:
                norm_out = str(out).strip().lower()
                if norm_out in SUPPORTED_QA_CAPABILITIES:
                    cap = norm_out
                    break

        if cap not in SUPPORTED_QA_CAPABILITIES:
            raise UnsupportedRoleError(
                f"QA task '{task.id}' has unsupported or missing capability '{cap}'. "
                f"Ordinary QA work items in DAG only support non-mutating planning/audit: "
                f"{sorted(SUPPORTED_QA_CAPABILITIES)}."
            )

        # 3. Preflight validation & loading of input artifacts
        verified_artifacts = self._verify_and_load_input_artifacts(task)

        # 4. Construct planning prompt
        prompt = build_qa_planning_execution_prompt(
            task,
            verified_artifacts=verified_artifacts or {},
            capability=cap,
        )

        return self._execute_specialist_task(
            task=task,
            agent_name="qa",
            prompt=prompt,
            result_parser=parse_and_validate_qa_planning_result,
        )

    def _get_repo_working_tree_state(self, repo_path: Optional[Path] = None) -> str:
        """Capture a deterministic lightweight status of repository working tree."""
        try:
            target = repo_path or self.repo_root
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(target),
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

        dev_knowledge = None
        if project_id:
            catalog = self.get_project_knowledge_catalog(project_id)
            if catalog:
                dev_policy = RoleKnowledgePolicy(
                    role="developer",
                    primary_domains=("backend", "architecture"),
                    max_sources=2,
                )
                selected_sources = catalog.select_sources_for_role(dev_policy)
                dev_knowledge = [
                    catalog.load_excerpt(s, repository_revision="HEAD", max_chars=800)
                    for s in selected_sources
                ]

        prompt = build_developer_execution_prompt(
            task,
            verified_artifacts=verified_artifacts,
            project_knowledge=dev_knowledge,
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
        repo_root: Optional[Path] = None,
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
        target_repo = (Path(repo_root) if repo_root else self.repo_root).resolve()
        base_commit = resolve_repo_head_commit(target_repo)

        # 6. Generate unique grant_id if not provided
        gid = grant_id or f"grant_{task.id}_{uuid.uuid4().hex[:8]}"

        # Reconcile create vs modify based on target repository disk state
        reconciled_mod = list(approved_files_to_modify or [])
        reconciled_create = []
        for f in (approved_files_to_create or []):
            if (target_repo / f).is_file():
                if f not in reconciled_mod:
                    reconciled_mod.append(f)
            else:
                reconciled_create.append(f)

        grant = ExecutionGrant(
            grant_id=gid,
            task_id=task.id,
            plan_artifact_id=artifact.id,
            plan_sha256=computed_sha,
            base_commit_hash=base_commit,
            approved_files_to_modify=tuple(reconciled_mod),
            approved_files_to_create=tuple(reconciled_create),
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
        is_main_repo = (target_repo == self.repo_root.resolve())
        for rel_path in all_approved:
            if is_protected_path(rel_path, protect_company_control=is_main_repo):
                raise ProtectedPathError(f"Approved path '{rel_path}' is protected by company policy.")
            if is_test_file(rel_path) and not grant.allow_test_modifications:
                raise TestModificationForbiddenError(
                    f"Test file '{rel_path}' cannot be modified: grant.allow_test_modifications is False."
                )

        # Validate against RepositoryPolicy if project is registered in ProjectRegistry (STEP 19B)
        if project_id:
            repo_proj = self.project_registry.get_project(project_id)
            if repo_proj:
                validate_grant_against_project_policy(
                    approved_files_to_modify=grant.approved_files_to_modify,
                    approved_files_to_create=grant.approved_files_to_create,
                    policy=repo_proj.policy,
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
        initial_patch_text: Optional[str] = None,
        patch_version: int = 1,
        previous_code_patch_artifact_id: Optional[str] = None,
        previous_code_patch_sha256: Optional[str] = None,
        repair_id: Optional[str] = None,
        repair_iteration: Optional[int] = None,
        allow_stale_head: bool = False,
        repo_root: Optional[Path] = None,
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
        target_repo = (Path(repo_root) if repo_root else self.repo_root).resolve()
        is_main_repo = (target_repo == self.repo_root.resolve())
        current_head = resolve_repo_head_commit(target_repo)
        if current_head != grant.base_commit_hash and not allow_stale_head:
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
            repo_root=target_repo,
            worktrees_dir=Path(self.output_dir) / "worktrees",
            protect_company_control=protect_company_control if is_main_repo else False,
        )
        session = manager.create_worktree(grant)
        cleaned_up = False

        try:
            # If initial patch is provided (e.g. during repair), apply it to worktree first
            if initial_patch_text:
                try:
                    apply_code_patch_to_worktree(session.worktree_path, initial_patch_text)
                except Exception as patch_err:
                    outcome = BoundedDeveloperExecutionOutcome(
                        grant_id=grant.grant_id,
                        status=DeveloperMutationStatus.PATCH_CAPTURE_FAILED.value,
                        summary=f"Failed to apply base patch to repair worktree: {patch_err}",
                        error=str(patch_err),
                    )
                    return outcome
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
                                    # 17. Patch Materialization (STEP 13B-3 & STEP 15)
                                    filename = (
                                        f"developer_changes_v{patch_version}.patch"
                                        if patch_version > 1
                                        else "developer_changes.patch"
                                    )
                                    try:
                                        patch_artifact = materialize_code_patch_artifact(
                                            base_output_dir=self.output_dir,
                                            task=source_task,
                                            run=source_run,
                                            grant=grant,
                                            patch_text=diff_res.diff_text,
                                            changed_files=diff_res.changed_files,
                                            verifications=veri_results,
                                            filename=filename,
                                            patch_version=patch_version,
                                            previous_code_patch_artifact_id=previous_code_patch_artifact_id,
                                            previous_code_patch_sha256=previous_code_patch_sha256,
                                            repair_id=repair_id,
                                            repair_iteration=repair_iteration,
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
        timeout: Optional[float] = None,
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
            elif (
                art.artifact_type in (ArtifactType.DEVELOPER_PLAN_REPORT.value, ArtifactType.DEVELOPER_REPAIR_PLAN_REPORT.value)
                or art.name == "developer_plan_report.md"
                or art.name.startswith("developer_repair_plan")
            ):
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
            timeout=timeout,
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
        timeout: Optional[float] = None,
    ) -> TaskRun:
        """Internal execution lifecycle for QA Agent inspection (STEP 14A)."""
        run = task.create_run()
        run.status = RunStatus.RUNNING.value

        if timeout is not None:
            exec_result = self.runtime.execute(
                agent="qa",
                prompt=prompt,
                timeout=timeout,
                workspace_dir=self.repo_root,
            )
        else:
            exec_result = self.runtime.execute(agent="qa", prompt=prompt)

        # 1. Handle runtime failures
        if not exec_result.success:
            if exec_result.timed_out:
                error_msg = f"[{QAFailureReason.QA_RUNTIME_FAILED.value}] QA runtime execution timed out after {exec_result.duration_ms:.0f}ms."
            else:
                stderr_diag = f" Stderr: {exec_result.stderr[:300]}" if exec_result.stderr else ""
                error_msg = f"[{QAFailureReason.QA_RUNTIME_FAILED.value}] QA runtime execution failed with exit code {exec_result.exit_code}.{stderr_diag}"
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

    # --------------------------------------------------------------------------
    # QA Isolated Verification Execution (STEP 14B)
    # --------------------------------------------------------------------------

    def execute_qa_verification_task(
        self,
        task_id: str,
        project_id: Optional[str] = None,
        code_patch_artifact_id: Optional[str] = None,
        qa_report_artifact_id: Optional[str] = None,
        timeout: Optional[float] = None,
        target_repo_root: Optional[Path] = None,
    ) -> TaskRun:
        """Execute independent QA verification execution against a verified CODE_PATCH (STEP 14B).

        Enforces:
        1. Role & Eligibility: Task status == PENDING, required_roles == ['qa'].
        2. Input Resolution & Lineage Validation:
           - Resolves Product, optional UX, Developer Plan, CODE_PATCH, and QA_REPORT artifacts.
           - Validates full upstream lineage coherence across all 5 artifacts.
        3. Preflight Security & Integrity Checks:
           - Stored SHA-256 vs recomputed disk SHA-256 for CODE_PATCH and QA_REPORT.
           - Valid base_commit_hash in CODE_PATCH.
           - Developer verification evidence present and all PASS.
           - QA_REPORT references exact CODE_PATCH ID, SHA, base commit, and upstream chain.
        4. Fresh Disposable Git Worktree Creation:
           - Created at exact CODE_PATCH.metadata.base_commit_hash.
           - Main working tree, dirty files, and Developer's old worktree are never used.
        5. Application-Owned Patch Applicability & Apply:
           - git apply --check <patch> -> git apply <patch> (argv array, shell=False).
           - Fails closed on applicability error.
        6. Workspace Mutation Verification:
           - Captures diff from fresh worktree.
           - Diff changed files match CODE_PATCH changed_files; no extra files or deletions.
        7. Authorization & Conversion Layer:
           - Proposed QARecommendedActions deterministically authorized.
           - Enforces type allowlist ('pytest'), path confinement, safe relative target, physical existence.
           - Non-executable/unsupported/missing targets recorded in audit log.
        8. Application-Owned Test Execution:
           - Executes authorized VerificationActions in isolated worktree via execute_verification_action.
           - Collects structured execution outcomes (status, exit code, logs, duration).
        9. Read-Only QA Agent Final Evaluation:
           - Presents requirements, patch, prior inspection, and actual test evidence to QA Agent.
           - QA Agent produces structured final verdict (PASS, FAIL, BLOCKED).
        10. Deterministic Safety Override:
            - If tests failed -> PASS is forbidden (overridden to FAIL).
            - If required tests could not execute -> PASS is forbidden (overridden to BLOCKED).
        11. Durable Artifact Materialization:
            - Materializes QA_EXECUTION_REPORT ("qa_execution_report.md" + companion ".meta.json").
            - SHA-256 verified on readback.
        12. Guaranteed Worktree Cleanup:
            - Disposable worktree is pruned and wiped in finally: block.
            - Main repository verified completely untouched.
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

        # 2. Attach inputs if explicitly passed
        if code_patch_artifact_id:
            already = any(inp.artifact_id == code_patch_artifact_id for inp in task.input_artifacts)
            if not already:
                self.attach_input_artifact(task.id, code_patch_artifact_id, project_id=project_id)

        if qa_report_artifact_id:
            already = any(inp.artifact_id == qa_report_artifact_id for inp in task.input_artifacts)
            if not already:
                self.attach_input_artifact(task.id, qa_report_artifact_id, project_id=project_id)

        if not task.input_artifacts:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA task '{task.id}' has no input artifacts attached."
            )

        # 3. Categorization
        product_inputs = []
        ux_inputs = []
        plan_inputs = []
        patch_inputs = []
        qa_report_inputs = []

        for ref in task.input_artifacts:
            lineage = self.find_artifact(ref.artifact_id)
            if not lineage:
                raise QAInputInvalidError(
                    f"[{QAFailureReason.QA_INPUT_INVALID.value}] Input artifact '{ref.artifact_id}' could not be found in company state."
                )
            src_task, src_run, art = lineage

            if art.artifact_type == ArtifactType.SPECIFICATION.value or (art.producer_role or "").lower() == "product":
                product_inputs.append((ref, art, src_task))
            elif art.artifact_type == ArtifactType.UX_SPECIFICATION.value or (art.producer_role or "").lower() == "ux":
                ux_inputs.append((ref, art, src_task))
            elif (
                art.artifact_type in (ArtifactType.DEVELOPER_PLAN_REPORT.value, ArtifactType.DEVELOPER_REPAIR_PLAN_REPORT.value)
                or art.name == "developer_plan_report.md"
                or art.name.startswith("developer_repair_plan")
            ):
                plan_inputs.append((ref, art, src_task))
            elif art.artifact_type == ArtifactType.CODE_PATCH.value or art.name.endswith(".patch"):
                patch_inputs.append((ref, art, src_task))
            elif art.artifact_type == ArtifactType.QA_REPORT.value or art.name == "qa_report.md":
                qa_report_inputs.append((ref, art, src_task))
            else:
                raise QAInputInvalidError(
                    f"[{QAFailureReason.QA_INPUT_INVALID.value}] Unrecognized input artifact type '{art.artifact_type}' for QA verification task."
                )

        if len(product_inputs) != 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA verification task requires exactly 1 Product specification artifact, found {len(product_inputs)}."
            )
        prod_ref, prod_art, prod_task = product_inputs[0]

        if len(plan_inputs) != 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA verification task requires exactly 1 Developer Plan artifact, found {len(plan_inputs)}."
            )
        plan_ref, plan_art, plan_task = plan_inputs[0]

        if len(patch_inputs) != 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA verification task requires exactly 1 CODE_PATCH artifact, found {len(patch_inputs)}."
            )
        patch_ref, patch_art, patch_task = patch_inputs[0]

        if len(qa_report_inputs) != 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA verification task requires exactly 1 QA_REPORT artifact, found {len(qa_report_inputs)}."
            )
        qa_rep_ref, qa_rep_art, qa_rep_task = qa_report_inputs[0]

        if len(ux_inputs) > 1:
            raise QAInputInvalidError(
                f"[{QAFailureReason.QA_INPUT_INVALID.value}] QA verification task cannot have more than 1 UX artifact, found {len(ux_inputs)}."
            )
        ux_ref, ux_art, ux_task = ux_inputs[0] if ux_inputs else (None, None, None)

        # 4. Lineage Validation
        plan_consumed_prods = {inp.artifact_id for inp in plan_task.input_artifacts if (inp.producer_role or "").lower() == "product"}
        if prod_art.id not in plan_consumed_prods:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] Product artifact '{prod_art.id}' does not match Developer Plan upstream Product '{sorted(plan_consumed_prods)}'."
            )

        plan_consumed_ux = {inp.artifact_id for inp in plan_task.input_artifacts if (inp.producer_role or "").lower() == "ux"}
        if plan_consumed_ux:
            if ux_art is None:
                raise QALineageMismatchError(
                    f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] Developer Plan consumed UX artifact '{sorted(plan_consumed_ux)}', but no UX artifact was provided."
                )
            if ux_art.id not in plan_consumed_ux:
                raise QALineageMismatchError(
                    f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] UX artifact '{ux_art.id}' does not match Developer Plan upstream UX '{sorted(plan_consumed_ux)}'."
                )
        else:
            if ux_art is not None:
                raise QALineageMismatchError(
                    f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] UX artifact '{ux_art.id}' provided, but Developer Plan did not consume any UX artifact."
                )

        patch_meta = patch_art.metadata or {}
        if patch_meta.get("plan_artifact_id") != plan_art.id or patch_meta.get("plan_sha256") != plan_art.sha256:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] CODE_PATCH does not match Developer Plan '{plan_art.id}'."
            )

        qa_rep_meta = qa_rep_art.metadata or {}
        if (qa_rep_art.producer_role or "").lower() != "qa":
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] QA_REPORT artifact was not produced by role 'qa'."
            )
        if qa_rep_meta.get("code_patch_artifact_id") != patch_art.id or qa_rep_meta.get("code_patch_sha256") != patch_art.sha256:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] QA_REPORT references code_patch '{qa_rep_meta.get('code_patch_artifact_id')}', expected '{patch_art.id}'."
            )
        if qa_rep_meta.get("product_artifact_id") != prod_art.id:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] QA_REPORT product_artifact_id mismatch: '{qa_rep_meta.get('product_artifact_id')}' != '{prod_art.id}'."
            )
        if qa_rep_meta.get("developer_plan_artifact_id") != plan_art.id:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] QA_REPORT developer_plan_artifact_id mismatch: '{qa_rep_meta.get('developer_plan_artifact_id')}' != '{plan_art.id}'."
            )

        base_commit = patch_meta.get("base_commit_hash")
        if not base_commit or not isinstance(base_commit, str) or not base_commit.strip():
            raise QAPatchIntegrityError(
                f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH metadata missing valid base_commit_hash."
            )
        if qa_rep_meta.get("base_commit_hash") != base_commit:
            raise QALineageMismatchError(
                f"[{QAFailureReason.QA_LINEAGE_MISMATCH.value}] QA_REPORT base_commit_hash '{qa_rep_meta.get('base_commit_hash')}' != patch base commit '{base_commit}'."
            )

        # Developer verification check
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
                    f"[{QAFailureReason.PATCH_INTEGRITY_FAILED.value}] CODE_PATCH verification failed at index {idx}."
                )

        # 5. Load and verify input contents & disk hashes
        prod_content = load_and_verify_input_artifact(Path(self.output_dir), prod_art, prod_ref)
        plan_content = load_and_verify_input_artifact(Path(self.output_dir), plan_art, plan_ref)
        patch_text = load_and_verify_input_artifact(Path(self.output_dir), patch_art, patch_ref)
        qa_rep_content = load_and_verify_input_artifact(Path(self.output_dir), qa_rep_art, qa_rep_ref)
        ux_content = load_and_verify_input_artifact(Path(self.output_dir), ux_art, ux_ref) if ux_art and ux_ref else None

        # 6. Extract recommended actions from QA_REPORT
        raw_recs = []
        if qa_rep_task and qa_rep_task.result and qa_rep_task.result.details:
            raw_recs = qa_rep_task.result.details.get("recommended_verification_actions", [])
        if not raw_recs:
            raw_recs = qa_rep_meta.get("recommended_verification_actions", [])

        recommended_actions: List[QARecommendedAction] = []
        for r in raw_recs:
            if isinstance(r, dict):
                recommended_actions.append(
                    QARecommendedAction(
                        action_type=str(r.get("action_type") or "pytest").strip().lower(),
                        target=str(r.get("target") or "").strip(),
                        purpose=str(r.get("purpose") or "").strip(),
                    )
                )

        # 7. Create fresh isolated Git worktree from exact base_commit_hash
        target_repo = (Path(target_repo_root) if target_repo_root else self.repo_root).resolve()
        is_main_repo = (target_repo == self.repo_root.resolve())
        session_id = f"qa_exec_{task.id}_{uuid.uuid4().hex[:8]}"
        manager = WorktreeManager(
            repo_root=target_repo,
            worktrees_dir=Path(self.output_dir) / "worktrees",
            protect_company_control=is_main_repo,
        )

        repo_state_before = self._get_repo_working_tree_state(repo_path=target_repo)
        session = manager.create_qa_worktree(base_commit_hash=base_commit, session_id=session_id)

        run = task.create_run()
        run.status = RunStatus.RUNNING.value

        try:
            # 8. Application-owned patch apply
            try:
                apply_code_patch_to_worktree(session.worktree_path, patch_text)
            except Exception as apply_err:
                error_msg = f"Patch application failed in fresh QA worktree: {apply_err}"
                logger.warning(error_msg)
                run.complete(status=RunStatus.FAILED.value, error=error_msg)
                task.complete(status=TaskStatus.FAILED.value, summary=error_msg)
                return run

            # 9. Resulting diff validation
            try:
                diff_res = validate_applied_patch_diff(session, patch_art)
            except Exception as diff_err:
                error_msg = f"Applied patch diff validation failed: {diff_err}"
                logger.warning(error_msg)
                run.complete(status=RunStatus.FAILED.value, error=error_msg)
                task.complete(status=TaskStatus.FAILED.value, summary=error_msg)
                return run

            # 10. Authorize and convert recommended actions
            authorized_actions, action_audits = authorize_and_convert_qa_actions(
                recommended_actions=recommended_actions,
                worktree_path=session.worktree_path,
            )

            # 11. Application-owned test execution
            sanitized_env = sanitize_execution_environment()
            verification_results: List[VerificationExecutionResult] = []
            for act in authorized_actions:
                vr = execute_verification_action(
                    action=act,
                    worktree_path=session.worktree_path,
                    timeout=30.0,
                    sanitized_env=sanitized_env,
                )
                verification_results.append(vr)

            # 12. Build QA Agent verdict prompt
            prompt = build_qa_verdict_prompt(
                task=task,
                product_content=prod_content,
                developer_plan_content=plan_content,
                code_patch_text=patch_text,
                qa_report_content=qa_rep_content,
                action_audits=action_audits,
                verification_results=verification_results,
                ux_content=ux_content,
            )

            # 13. Ensure QA agent definition exists in worktree for agy runtime
            worktree_agent_md = session.worktree_path / ".agents" / "agents" / "qa" / "agent.md"
            if not worktree_agent_md.exists():
                source_agent_md = self.repo_root / ".agents" / "agents" / "qa" / "agent.md"
                if not source_agent_md.exists():
                    source_agent_md = Path(__file__).resolve().parent.parent / ".agents" / "agents" / "qa" / "agent.md"
                if source_agent_md.exists():
                    worktree_agent_md.parent.mkdir(parents=True, exist_ok=True)
                    worktree_agent_md.write_text(source_agent_md.read_text(encoding="utf-8"), encoding="utf-8")

            # Execute QA Agent under read-only mode
            exec_res = self.runtime.execute(
                agent="qa",
                prompt=prompt,
                workspace_dir=session.worktree_path,
                env=sanitized_env,
            )

            if not exec_res.success or not (exec_res.stdout or "").strip():
                err_msg = (
                    f"QA Agent execution timed out after {exec_res.duration_ms:.0f}ms."
                    if exec_res.timed_out
                    else (exec_res.stderr or f"QA Agent execution failed with exit code {exec_res.exit_code}.")
                )
                run.complete(status=RunStatus.FAILED.value, error=err_msg)
                task.complete(status=TaskStatus.FAILED.value, summary=f"QA Execution failed: {err_msg}")
                return run

            # 14. Deterministic parsing and constraint enforcement
            try:
                verdict_res = parse_and_validate_qa_verdict(
                    raw_output=exec_res.stdout,
                    action_audits=action_audits,
                    verification_results=verification_results,
                )
            except Exception as parse_err:
                err_msg = f"Failed to parse and validate QA verdict: {parse_err}"
                run.complete(status=RunStatus.FAILED.value, error=err_msg)
                task.complete(status=TaskStatus.FAILED.value, summary=f"QA Execution failed: {err_msg}")
                return run

            # 15. Materialize durable QA_EXECUTION_REPORT
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
                "qa_report_artifact_id": qa_rep_art.id,
                "qa_report_sha256": qa_rep_art.sha256,
                "base_commit_hash": base_commit,
                "patch_apply_verified": True,
                "worktree_diff_sha256": diff_res.diff_sha256,
                "qa_execution_actions": [a.to_dict() for a in authorized_actions],
                "action_audits": [a.to_dict() for a in action_audits],
            }

            try:
                exec_art = materialize_qa_execution_report_artifact(
                    base_output_dir=Path(self.output_dir),
                    task=task,
                    run=run,
                    typed_verdict=verdict_res,
                    lineage_metadata=lineage_metadata,
                    execution_evidence=[v.to_dict() for v in verification_results],
                )
            except Exception as mat_err:
                err_msg = f"Failed to materialize QA_EXECUTION_REPORT: {mat_err}"
                run.complete(status=RunStatus.FAILED.value, error=err_msg)
                task.complete(status=TaskStatus.FAILED.value, summary=f"QA Execution failed: {err_msg}")
                return run

            # 16. Complete run and task
            run.complete(status=RunStatus.SUCCESS.value)
            task.complete(
                status=TaskStatus.COMPLETED.value,
                summary=f"QA Execution complete: verdict={verdict_res.verdict}. {verdict_res.summary}",
                details=verdict_res.to_dict(),
            )
            return run

        finally:
            # 17. Guaranteed worktree cleanup
            try:
                session.remove()
            except Exception as clean_err:
                logger.error("Failed to clean up QA worktree: %s", clean_err)

            repo_state_after = self._get_repo_working_tree_state(repo_path=target_repo)
            if repo_state_before != repo_state_after:
                raise ExecutionError(f"Repository mutation detected during QA execution task '{task.id}'!")

    # --------------------------------------------------------------------------
    # Developer ↔ QA Controlled Repair Loop (STEP 15)
    # --------------------------------------------------------------------------

    def execute_developer_qa_repair_loop(
        self,
        task_id: str,
        project_id: Optional[str] = None,
        founder_approvals: Optional[Dict[int, str]] = None,
        original_grant: Optional[ExecutionGrant] = None,
        max_repair_iterations: int = MAX_REPAIR_ITERATIONS,
        allow_test_modifications: bool = False,
        timeout: Optional[float] = None,
        target_repo_root: Optional[Path] = None,
    ) -> DeveloperQARepairLoopResult:
        """Execute the Developer ↔ QA Controlled Repair Loop (STEP 15).

        Architecture:
        1. Fully application-owned transitions. Agents NEVER invoke each other directly.
        2. Bounded to max_repair_iterations (default 2).
        3. Deterministic eligibility classification on current QA execution report:
           - PASS -> QA_PASSED immediately (never enters repair).
           - FAIL -> REPAIRABLE_IMPLEMENTATION.
           - BLOCKED -> REPAIRABLE_TEST_GAP vs NON_REPAIRABLE_*.
        4. Every repair iteration requires an explicit, legitimate founder approval ID.
           Missing, empty, or reused approvals immediately halt with REPAIR_GRANT_REJECTED.
           Never fabricates synthetic approvals.
        5. Developer executes strictly in read-only planning mode to produce DeveloperRepairPlan.
        6. Candidate ExecutionGrant derived monotonically with no protected paths.
        7. Fresh isolated worktree starts from original base commit + applies previous CODE_PATCH.
        8. Diff against original base commit captures complete cumulative CODE_PATCH vN.
        9. Repaired candidate undergoes complete independent QA reinspection (14A) & re-execution (14B).
        10. Final durable DEVELOPER_QA_REPAIR_REPORT artifact materialized with full history.
        11. Zero main-repository mutation guaranteed.
        """
        target_repo = (Path(target_repo_root) if target_repo_root else self.repo_root).resolve()
        repo_state_before = self._get_repo_working_tree_state(repo_path=target_repo)

        try:
            task = self.get_task(task_id, project_id=project_id)
            if not task:
                raise RepairError(f"Task '{task_id}' not found.")

            proj = self.company.projects.get(task.project_id or project_id or "default")
            if not proj:
                raise RepairError(f"Project for task '{task_id}' not found.")

            # 1. Locate latest QA_EXECUTION_REPORT associated with task
            qa_exec_art: Optional[Artifact] = None
            for run in reversed(task.runs):
                for art in run.artifacts:
                    if art.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value:
                        qa_exec_art = art
                        break
                if qa_exec_art:
                    break

            if not qa_exec_art:
                for other_task in reversed(list(proj.tasks.values())):
                    for run in reversed(other_task.runs):
                        for art in run.artifacts:
                            if art.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value:
                                meta = art.metadata or {}
                                if (
                                    meta.get("qa_task_id") == task.id
                                    or meta.get("task_id") == task.id
                                    or meta.get("original_task_id") == task.id
                                    or other_task.id == task.id
                                    or other_task.id.startswith(f"qa_exec_{task.id}")
                                    or other_task.id.startswith(task.id)
                                    or other_task.id == f"{task.id}_qa_verify"
                                ):
                                    qa_exec_art = art
                                    break
                        if qa_exec_art:
                            break
                    if qa_exec_art:
                        break

            if not qa_exec_art:
                raise RepairError(f"No QA_EXECUTION_REPORT found for task '{task.id}'.")

            # 2. Extract upstream artifact pointers from QA execution report metadata
            qa_meta = qa_exec_art.metadata or {}
            code_patch_id = qa_meta.get("code_patch_artifact_id")
            qa_report_id = qa_meta.get("qa_report_artifact_id")
            plan_art_id = qa_meta.get("developer_plan_artifact_id")
            prod_art_id = qa_meta.get("product_artifact_id")
            ux_art_id = qa_meta.get("ux_artifact_id")
            base_commit = qa_meta.get("base_commit_hash")

            if not code_patch_id:
                raise RepairError("QA_EXECUTION_REPORT missing code_patch_artifact_id.")
            patch_lineage = self.find_artifact(code_patch_id)
            if not patch_lineage:
                raise RepairError(f"CODE_PATCH artifact '{code_patch_id}' not found.")
            _, _, current_patch_art = patch_lineage

            if not qa_report_id:
                raise RepairError("QA_EXECUTION_REPORT missing qa_report_artifact_id.")
            qa_rep_lineage = self.find_artifact(qa_report_id)
            if not qa_rep_lineage:
                raise RepairError(f"QA_REPORT artifact '{qa_report_id}' not found.")
            _, _, current_qa_report_art = qa_rep_lineage

            if not plan_art_id:
                raise RepairError("QA_EXECUTION_REPORT missing developer_plan_artifact_id.")
            plan_lineage = self.find_artifact(plan_art_id)
            if not plan_lineage:
                raise RepairError(f"DEVELOPER_PLAN_REPORT artifact '{plan_art_id}' not found.")
            _, _, original_plan_art = plan_lineage

            if not prod_art_id:
                raise RepairError("QA_EXECUTION_REPORT missing product_artifact_id.")
            prod_lineage = self.find_artifact(prod_art_id)
            if not prod_lineage:
                raise RepairError(f"PRODUCT_REQUIREMENTS artifact '{prod_art_id}' not found.")
            _, _, prod_art = prod_lineage

            ux_art = None
            if ux_art_id:
                ux_lineage = self.find_artifact(ux_art_id)
                if ux_lineage:
                    _, _, ux_art = ux_lineage

            # 3. Base commit determination
            if not base_commit:
                base_commit = current_patch_art.metadata.get("base_commit_hash") if current_patch_art.metadata else None
            if not base_commit:
                base_commit = resolve_repo_head_commit(self.repo_root)

            # 4. Initialize grant baseline
            patch_meta = current_patch_art.metadata or {}
            if original_grant is None:
                orig_mod = tuple(patch_meta.get("changed_files", []))
                original_grant = ExecutionGrant(
                    grant_id=patch_meta.get("execution_grant_id", f"grant_{task.id}"),
                    task_id=task.id,
                    plan_artifact_id=patch_meta.get("plan_artifact_id", original_plan_art.id),
                    plan_sha256=patch_meta.get("plan_sha256", original_plan_art.sha256 or ""),
                    base_commit_hash=base_commit,
                    approved_files_to_modify=orig_mod,
                    approved_files_to_create=(),
                    verification_actions=(),
                    allow_test_modifications=allow_test_modifications,
                    max_files_changed=max(len(orig_mod) + 5, 5),
                    max_bytes_written=100_000,
                    max_verification_actions=5,
                    max_duration_seconds=120,
                    network_enabled=False,
                    founder_approval_id=patch_meta.get("founder_approval_id", "appr_base"),
                )
            elif original_grant.allow_test_modifications:
                allow_test_modifications = True

            # 5. Reconstruct initial QA execution evaluation
            current_verdict_res, current_action_audits, current_veri_results = reconstruct_qa_execution_context(
                qa_exec_art=qa_exec_art,
                task=task,
            )

            current_qa_exec_art = qa_exec_art
            current_qa_report_art = current_qa_report_art
            current_patch_art = current_patch_art
            current_grant = original_grant
            used_approval_ids: Set[str] = {original_grant.founder_approval_id}

            attempts: List[RepairAttemptRecord] = []
            dev_planning_invocations = 0
            dev_mutation_invocations = 0
            qa_inspection_invocations = 0
            qa_evaluation_invocations = 0

            final_status = ""
            termination_reason = ""
            final_code_patch_id: Optional[str] = current_patch_art.id
            final_qa_exec_id: Optional[str] = current_qa_exec_art.id
            repair_iterations_used = 0

            # 6. Repair Loop
            for iteration in range(1, max_repair_iterations + 1):
                # 6.1 Classify eligibility
                classification, repair_reason = classify_repair_eligibility(
                    verdict_result=current_verdict_res,
                    action_audits=current_action_audits,
                    verification_results=current_veri_results,
                )

                if classification == RepairEligibilityClassification.NOT_ELIGIBLE_PASS:
                    final_status = RepairWorkflowStatus.QA_PASSED.value
                    termination_reason = "QA verification has passed cleanly; no repair required."
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    break

                if classification in (
                    RepairEligibilityClassification.NON_REPAIRABLE_SECURITY,
                    RepairEligibilityClassification.NON_REPAIRABLE_ENVIRONMENT,
                    RepairEligibilityClassification.NON_REPAIRABLE_INFRASTRUCTURE,
                ):
                    final_status = RepairWorkflowStatus.NON_REPAIRABLE_BLOCKED.value
                    termination_reason = (
                        f"QA verification is blocked by non-repairable condition "
                        f"({classification.value}): {repair_reason}"
                    )
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    break

                # 6.2 Founder approval enforcement (Clarification 2)
                approval_id = (founder_approvals or {}).get(iteration)
                if not approval_id or not str(approval_id).strip():
                    final_status = RepairWorkflowStatus.REPAIR_GRANT_REJECTED.value
                    termination_reason = f"Repair iteration {iteration} rejected: missing legitimate founder approval."
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    break

                cleaned_approval_id = str(approval_id).strip()
                if cleaned_approval_id in used_approval_ids:
                    final_status = RepairWorkflowStatus.REPAIR_GRANT_REJECTED.value
                    termination_reason = (
                        f"Repair iteration {iteration} rejected: reused founder approval '{cleaned_approval_id}'. "
                        f"Each repair iteration requires a distinct, legitimate approval."
                    )
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    break

                used_approval_ids.add(cleaned_approval_id)

                # 6.3 Construct typed DeveloperRepairTask
                repair_id = f"repair_{task.id}_iter{iteration}"
                repair_task_context = build_developer_repair_task(
                    repair_id=repair_id,
                    original_task_id=task.id,
                    iteration=iteration,
                    product_art=prod_art,
                    plan_art=original_plan_art,
                    patch_art=current_patch_art,
                    qa_report_art=current_qa_report_art,
                    qa_exec_art=current_qa_exec_art,
                    verdict_result=current_verdict_res,
                    action_audits=current_action_audits,
                    verification_results=current_veri_results,
                    classification=classification,
                    repair_reason=repair_reason,
                    ux_art=ux_art,
                    max_iterations=max_repair_iterations,
                )

                # 6.4 Developer Repair Planning (READ-ONLY)
                product_ref = ArtifactInputRef(
                    artifact_id=prod_art.id,
                    run_id=prod_art.run_id or "",
                    sha256=prod_art.sha256 or "",
                    producer_role=prod_art.producer_role,
                )
                prod_content = load_and_verify_input_artifact(Path(self.output_dir), prod_art, product_ref)

                plan_ref = ArtifactInputRef(
                    artifact_id=original_plan_art.id,
                    run_id=original_plan_art.run_id or "",
                    sha256=original_plan_art.sha256 or "",
                    producer_role=original_plan_art.producer_role,
                )
                orig_plan_content = load_and_verify_input_artifact(Path(self.output_dir), original_plan_art, plan_ref)

                patch_ref = ArtifactInputRef(
                    artifact_id=current_patch_art.id,
                    run_id=current_patch_art.run_id or "",
                    sha256=current_patch_art.sha256 or "",
                    producer_role=current_patch_art.producer_role,
                )
                current_patch_content = load_and_verify_input_artifact(Path(self.output_dir), current_patch_art, patch_ref)

                qa_rep_ref = ArtifactInputRef(
                    artifact_id=current_qa_report_art.id,
                    run_id=current_qa_report_art.run_id or "",
                    sha256=current_qa_report_art.sha256 or "",
                    producer_role=current_qa_report_art.producer_role,
                )
                qa_rep_content = load_and_verify_input_artifact(Path(self.output_dir), current_qa_report_art, qa_rep_ref)

                qa_exec_ref = ArtifactInputRef(
                    artifact_id=current_qa_exec_art.id,
                    run_id=current_qa_exec_art.run_id or "",
                    sha256=current_qa_exec_art.sha256 or "",
                    producer_role=current_qa_exec_art.producer_role,
                )
                qa_exec_content = load_and_verify_input_artifact(Path(self.output_dir), current_qa_exec_art, qa_exec_ref)

                ux_content = None
                if ux_art:
                    ux_ref = ArtifactInputRef(
                        artifact_id=ux_art.id,
                        run_id=ux_art.run_id or "",
                        sha256=ux_art.sha256 or "",
                        producer_role=ux_art.producer_role,
                    )
                    ux_content = load_and_verify_input_artifact(Path(self.output_dir), ux_art, ux_ref)

                repair_plan_prompt = build_developer_repair_planning_prompt(
                    repair_task=repair_task_context,
                    product_content=prod_content,
                    original_plan_content=orig_plan_content,
                    previous_patch_text=current_patch_content,
                    qa_report_content=qa_rep_content,
                    qa_execution_report_content=qa_exec_content,
                    ux_content=ux_content,
                )

                dev_planning_invocations += 1
                repair_plan_task_id = f"{task.id}_repair_plan_iter{iteration}"
                repair_plan_task = proj.create_task(
                    task_id=repair_plan_task_id,
                    title=f"Developer Repair Planning (Iteration {iteration})",
                    goal=f"Formulate strict repair plan to resolve QA defects for task {task.id}",
                    required_roles=["developer"],
                )
                self.attach_input_artifact(repair_plan_task.id, prod_art.id, project_id=proj.id)
                if ux_art:
                    self.attach_input_artifact(repair_plan_task.id, ux_art.id, project_id=proj.id)
                self.attach_input_artifact(repair_plan_task.id, original_plan_art.id, project_id=proj.id)
                self.attach_input_artifact(repair_plan_task.id, current_patch_art.id, project_id=proj.id)
                self.attach_input_artifact(repair_plan_task.id, current_qa_report_art.id, project_id=proj.id)
                self.attach_input_artifact(repair_plan_task.id, current_qa_exec_art.id, project_id=proj.id)

                plan_run = repair_plan_task.create_run()
                plan_run.status = RunStatus.RUNNING.value

                plan_exec_res = self.runtime.execute(
                    agent="developer",
                    prompt=repair_plan_prompt,
                    timeout=timeout or 300.0,
                    workspace_dir=self.repo_root,
                    env=sanitize_execution_environment(),
                )

                try:
                    repair_plan = parse_and_validate_developer_repair_plan(plan_exec_res.stdout)
                except Exception as parse_err:
                    plan_run.complete(status=RunStatus.FAILED.value, error=str(parse_err))
                    repair_plan_task.complete(status=TaskStatus.FAILED.value, summary=f"Repair planning failed: {parse_err}")
                    final_status = RepairWorkflowStatus.REPAIR_PLAN_FAILED.value
                    termination_reason = f"Developer repair plan parsing/validation failed: {parse_err}"
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    attempts.append(
                        RepairAttemptRecord(
                            iteration=iteration,
                            repair_task_id=repair_task_context.repair_id,
                            status="FAILED",
                            error=str(parse_err),
                        )
                    )
                    break

                if repair_plan.requirement_conflict_detected:
                    plan_run.complete(status=RunStatus.FAILED.value, error=f"Requirement conflict: {repair_plan.conflict_details}")
                    repair_plan_task.complete(
                        status=TaskStatus.FAILED.value,
                        summary=f"Requirement conflict: {repair_plan.conflict_details}",
                    )
                    final_status = RepairWorkflowStatus.REQUIREMENT_CONFLICT.value
                    termination_reason = f"Developer identified requirement conflict: {repair_plan.conflict_details}"
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    attempts.append(
                        RepairAttemptRecord(
                            iteration=iteration,
                            repair_task_id=repair_task_context.repair_id,
                            status="REQUIREMENT_CONFLICT",
                            error=repair_plan.conflict_details,
                        )
                    )
                    break

                plan_run.complete(status=RunStatus.SUCCESS.value)
                repair_plan_task.complete(
                    status=TaskStatus.COMPLETED.value,
                    summary=f"Repair plan completed for iteration {iteration}",
                )
                plan_art = materialize_developer_repair_plan_artifact(
                    base_output_dir=Path(self.output_dir),
                    task=repair_plan_task,
                    run=plan_run,
                    typed_result=repair_plan,
                    filename=f"developer_repair_plan_v{iteration}.md",
                )

                # 6.5 Derive ExecutionGrant
                try:
                    repair_grant = derive_repair_execution_grant(
                        plan=repair_plan,
                        previous_grant=current_grant,
                        base_commit_hash=base_commit,
                        founder_approval_id=cleaned_approval_id,
                        allow_test_modifications=allow_test_modifications,
                        task_id=task.id,
                        plan_artifact_id=plan_art.id,
                        plan_sha256=plan_art.sha256 or "",
                    )
                except Exception as grant_err:
                    final_status = RepairWorkflowStatus.REPAIR_GRANT_REJECTED.value
                    termination_reason = f"Repair execution grant rejected: {grant_err}"
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    attempts.append(
                        RepairAttemptRecord(
                            iteration=iteration,
                            repair_task_id=repair_task_context.repair_id,
                            repair_plan_artifact_id=plan_art.id,
                            repair_plan_sha256=plan_art.sha256,
                            status="REPAIR_GRANT_REJECTED",
                            error=str(grant_err),
                        )
                    )
                    break

                # 6.6 Execute bounded Developer mutation in isolated worktree
                dev_mutation_invocations += 1
                mutation_outcome = self.execute_bounded_developer_mutation(
                    grant=repair_grant,
                    instruction=f"Repair QA defects: {repair_plan.root_cause}. Implement changes: {repair_plan.proposed_changes}",
                    timeout=timeout,
                    initial_patch_text=current_patch_content,
                    patch_version=iteration + 1,
                    previous_code_patch_artifact_id=current_patch_art.id,
                    previous_code_patch_sha256=current_patch_art.sha256,
                    repair_id=repair_id,
                    repair_iteration=iteration,
                    allow_stale_head=False,
                    repo_root=target_repo,
                )

                if mutation_outcome.status != DeveloperMutationStatus.SUCCESS.value or not mutation_outcome.patch_artifact:
                    final_status = RepairWorkflowStatus.REPAIR_EXECUTION_FAILED.value
                    termination_reason = f"Repair mutation execution failed: {mutation_outcome.summary}"
                    final_code_patch_id = current_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    attempts.append(
                        RepairAttemptRecord(
                            iteration=iteration,
                            repair_task_id=repair_task_context.repair_id,
                            repair_plan_artifact_id=plan_art.id,
                            repair_plan_sha256=plan_art.sha256,
                            execution_grant_id=repair_grant.grant_id,
                            status="EXECUTION_FAILED",
                            error=mutation_outcome.error or mutation_outcome.summary,
                        )
                    )
                    break

                repaired_patch_art = mutation_outcome.patch_artifact

                # 6.7 Independent QA Reinspection (STEP 14A)
                qa_inspection_invocations += 1
                qa_inspect_task_id = f"{task.id}_qa_inspect_iter{iteration}"
                qa_inspect_task = proj.create_task(
                    task_id=qa_inspect_task_id,
                    title=f"QA Reinspection (Iteration {iteration})",
                    goal=f"Reinspect repaired CODE_PATCH v{iteration + 1} for task {task.id}",
                    required_roles=["qa"],
                )
                self.attach_input_artifact(qa_inspect_task.id, prod_art.id, project_id=proj.id)
                if ux_art:
                    self.attach_input_artifact(qa_inspect_task.id, ux_art.id, project_id=proj.id)
                self.attach_input_artifact(qa_inspect_task.id, plan_art.id, project_id=proj.id)
                self.attach_input_artifact(qa_inspect_task.id, repaired_patch_art.id, project_id=proj.id)

                qa_inspect_run = self.execute_qa_inspection_task(
                    task_id=qa_inspect_task.id,
                    project_id=proj.id,
                    code_patch_artifact_id=repaired_patch_art.id,
                    timeout=timeout,
                )
                if qa_inspect_run.status != RunStatus.SUCCESS.value:
                    final_status = RepairWorkflowStatus.QA_REEXECUTION_FAILED.value
                    termination_reason = f"QA reinspection run failed: {qa_inspect_run.error}"
                    final_code_patch_id = repaired_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    attempts.append(
                        RepairAttemptRecord(
                            iteration=iteration,
                            repair_task_id=repair_task_context.repair_id,
                            repair_plan_artifact_id=plan_art.id,
                            repair_plan_sha256=plan_art.sha256,
                            execution_grant_id=repair_grant.grant_id,
                            code_patch_artifact_id=repaired_patch_art.id,
                            code_patch_sha256=repaired_patch_art.sha256,
                            status="QA_INSPECTION_FAILED",
                            error=qa_inspect_run.error,
                        )
                    )
                    break

                repaired_qa_report_art = [
                    a for a in qa_inspect_run.artifacts if a.artifact_type == ArtifactType.QA_REPORT.value
                ][0]

                # 6.8 Independent QA Re-execution (STEP 14B)
                qa_evaluation_invocations += 1
                qa_verify_task_id = f"{task.id}_qa_verify_iter{iteration}"
                qa_verify_task = proj.create_task(
                    task_id=qa_verify_task_id,
                    title=f"QA Verification Execution (Iteration {iteration})",
                    goal=f"Execute independent verification of repaired CODE_PATCH v{iteration + 1} for task {task.id}",
                    required_roles=["qa"],
                )
                self.attach_input_artifact(qa_verify_task.id, prod_art.id, project_id=proj.id)
                if ux_art:
                    self.attach_input_artifact(qa_verify_task.id, ux_art.id, project_id=proj.id)
                self.attach_input_artifact(qa_verify_task.id, plan_art.id, project_id=proj.id)
                self.attach_input_artifact(qa_verify_task.id, repaired_patch_art.id, project_id=proj.id)
                self.attach_input_artifact(qa_verify_task.id, repaired_qa_report_art.id, project_id=proj.id)

                qa_verify_run = self.execute_qa_verification_task(
                    task_id=qa_verify_task.id,
                    project_id=proj.id,
                    code_patch_artifact_id=repaired_patch_art.id,
                    qa_report_artifact_id=repaired_qa_report_art.id,
                    timeout=timeout,
                    target_repo_root=target_repo,
                )
                if qa_verify_run.status != RunStatus.SUCCESS.value:
                    final_status = RepairWorkflowStatus.QA_REEXECUTION_FAILED.value
                    termination_reason = f"QA re-execution run failed: {qa_verify_run.error}"
                    final_code_patch_id = repaired_patch_art.id
                    final_qa_exec_id = current_qa_exec_art.id
                    attempts.append(
                        RepairAttemptRecord(
                            iteration=iteration,
                            repair_task_id=repair_task_context.repair_id,
                            repair_plan_artifact_id=plan_art.id,
                            repair_plan_sha256=plan_art.sha256,
                            execution_grant_id=repair_grant.grant_id,
                            code_patch_artifact_id=repaired_patch_art.id,
                            code_patch_sha256=repaired_patch_art.sha256,
                            qa_report_artifact_id=repaired_qa_report_art.id,
                            qa_report_sha256=repaired_qa_report_art.sha256,
                            status="QA_EXECUTION_FAILED",
                            error=qa_verify_run.error,
                        )
                    )
                    break

                repaired_qa_exec_art = [
                    a for a in qa_verify_run.artifacts if a.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value
                ][0]
                new_verdict = repaired_qa_exec_art.metadata.get("verdict", "FAIL")
                repair_iterations_used = iteration

                attempt_rec = RepairAttemptRecord(
                    iteration=iteration,
                    repair_task_id=repair_task_context.repair_id,
                    repair_plan_artifact_id=plan_art.id,
                    repair_plan_sha256=plan_art.sha256,
                    execution_grant_id=repair_grant.grant_id,
                    code_patch_artifact_id=repaired_patch_art.id,
                    code_patch_sha256=repaired_patch_art.sha256,
                    qa_report_artifact_id=repaired_qa_report_art.id,
                    qa_report_sha256=repaired_qa_report_art.sha256,
                    qa_execution_report_artifact_id=repaired_qa_exec_art.id,
                    qa_execution_report_sha256=repaired_qa_exec_art.sha256,
                    qa_verdict=new_verdict,
                    status="COMPLETED",
                )
                attempts.append(attempt_rec)

                # Check outcome
                if new_verdict == QAFinalVerdict.PASS.value:
                    final_status = RepairWorkflowStatus.QA_PASSED.value
                    termination_reason = f"Repaired CODE_PATCH v{iteration + 1} PASSED QA verification on iteration {iteration}."
                    final_code_patch_id = repaired_patch_art.id
                    final_qa_exec_id = repaired_qa_exec_art.id
                    break
                else:
                    if iteration >= max_repair_iterations:
                        final_status = RepairWorkflowStatus.REPAIR_LIMIT_REACHED.value
                        termination_reason = (
                            f"Reached maximum allowed repair iterations ({max_repair_iterations}). "
                            f"Last QA verdict: {new_verdict}."
                        )
                        final_code_patch_id = repaired_patch_art.id
                        final_qa_exec_id = repaired_qa_exec_art.id
                        break
                    else:
                        # Advance current pointers for next repair iteration
                        current_patch_art = repaired_patch_art
                        current_grant = repair_grant
                        current_qa_report_art = repaired_qa_report_art
                        current_qa_exec_art = repaired_qa_exec_art
                        current_verdict_res, current_action_audits, current_veri_results = reconstruct_qa_execution_context(
                            qa_exec_art=current_qa_exec_art,
                            task=qa_verify_task,
                        )

            result = DeveloperQARepairLoopResult(
                status=final_status or RepairWorkflowStatus.WORKFLOW_ERROR.value,
                original_task_id=task.id,
                final_code_patch_artifact_id=final_code_patch_id,
                final_qa_execution_report_artifact_id=final_qa_exec_id,
                repair_iterations_used=repair_iterations_used,
                max_repair_iterations=max_repair_iterations,
                attempts=attempts,
                termination_reason=termination_reason,
                developer_planning_invocations=dev_planning_invocations,
                developer_mutation_invocations=dev_mutation_invocations,
                qa_inspection_invocations=qa_inspection_invocations,
                qa_evaluation_invocations=qa_evaluation_invocations,
            )

            # Materialize DEVELOPER_QA_REPAIR_REPORT artifact
            repair_summary_run = task.create_run()
            repair_summary_run.status = RunStatus.SUCCESS.value
            materialize_developer_qa_repair_report_artifact(
                base_output_dir=Path(self.output_dir),
                task=task,
                run=repair_summary_run,
                typed_result=result,
                filename="developer_qa_repair_report.md",
            )
            repair_summary_run.complete(status=RunStatus.SUCCESS.value)

            return result

        finally:
            repo_state_after = self._get_repo_working_tree_state(repo_path=target_repo)
            if repo_state_before != repo_state_after:
                raise ExecutionError(f"Repository mutation detected during repair loop execution on task '{task_id}'!")

    # --------------------------------------------------------------------------
    # Human-Approved Real Repository Apply (STEP 16)
    # --------------------------------------------------------------------------

    def prepare_real_repo_apply(
        self,
        code_patch_artifact_id: str,
        qa_execution_report_artifact_id: str,
        target_repo_root: Optional[Path] = None,
        project_id: Optional[str] = None,
        company_run_id: Optional[str] = None,
    ) -> RealRepoApplyProposal:
        """Prepare an immutable proposal for human review before real repository mutation (STEP 16).

        PERFORMS ZERO REPOSITORY MUTATION.
        """
        # 1. Resolve target repo root
        resolved_repo = (target_repo_root or self.repo_root).resolve()
        if not (resolved_repo / ".git").exists():
            raise TargetRepositoryInvalidError(f"Target path '{resolved_repo}' is not a valid git repository.")

        # Snapshot working tree state before
        repo_state_before = self._get_repo_working_tree_state(resolved_repo)

        try:
            # 2. Locate CODE_PATCH artifact
            patch_lineage = self.find_artifact(code_patch_artifact_id)
            if not patch_lineage:
                raise CandidateNotEligibleError(f"CODE_PATCH artifact '{code_patch_artifact_id}' not found in company state.")
            patch_task, patch_run, patch_art = patch_lineage

            patch_file_path = _resolve_artifact_file_path(Path(self.output_dir), patch_art)

            # 3. Locate QA_EXECUTION_REPORT artifact
            qa_exec_lineage = self.find_artifact(qa_execution_report_artifact_id)
            if not qa_exec_lineage:
                raise CandidateNotEligibleError(
                    f"QA_EXECUTION_REPORT artifact '{qa_execution_report_artifact_id}' not found in company state."
                )
            qa_exec_task, qa_exec_run, qa_exec_art = qa_exec_lineage

            qa_exec_file_path = _resolve_artifact_file_path(Path(self.output_dir), qa_exec_art)

            # 4. Locate QA_REPORT artifact
            qa_exec_meta = qa_exec_art.metadata or {}
            qa_rep_id = qa_exec_meta.get("qa_report_artifact_id")
            qa_rep_art = None
            if qa_rep_id:
                qa_rep_lineage = self.find_artifact(qa_rep_id)
                if qa_rep_lineage:
                    _, _, qa_rep_art = qa_rep_lineage

            if not qa_rep_art:
                # Fallback: search task/run for QA_REPORT matching code patch
                for p in self.company.projects.values():
                    for t in p.tasks.values():
                        for r in t.runs:
                            for art in r.artifacts:
                                if art.artifact_type == ArtifactType.QA_REPORT.value:
                                    m = art.metadata or {}
                                    if m.get("code_patch_artifact_id") == code_patch_artifact_id:
                                        qa_rep_art = art
                                        break
                            if qa_rep_art:
                                break
                        if qa_rep_art:
                            break

            if not qa_rep_art:
                raise CandidateNotEligibleError(
                    f"No QA_REPORT artifact found matching CODE_PATCH '{code_patch_artifact_id}'."
                )

            # 5. Build proposal (performs zero mutation)
            allow_untracked = False
            if project_id:
                proj_obj = self.project_registry.get_project(project_id)
                if proj_obj and proj_obj.repository:
                    allow_untracked = proj_obj.repository.allow_untracked
            if not allow_untracked:
                for p in self.project_registry.list_projects():
                    if p.repository and Path(p.repository.root_path).resolve() == resolved_repo:
                        if p.repository.allow_untracked:
                            allow_untracked = True
                            break

            proposal = build_real_repo_apply_proposal(
                target_repo_root=resolved_repo,
                code_patch_artifact=patch_art,
                code_patch_file_path=patch_file_path,
                qa_report_artifact=qa_rep_art,
                qa_execution_report_artifact=qa_exec_art,
                qa_execution_report_file_path=qa_exec_file_path,
                project_id=project_id,
                allow_untracked=allow_untracked,
            )

            # 6. Store in proposal registry & durable storage (STEP 20A)
            self._real_repo_apply_proposals[proposal.proposal_id] = proposal
            try:
                self.durable_storage.save_proposal(
                    proposal=proposal,
                    patch_file_path=patch_file_path,
                    qa_execution_file_path=qa_exec_file_path,
                    company_run_id=company_run_id,
                )
            except Exception as exc:
                logger.warning("Failed to persist proposal to durable storage: %s", exc)

            return proposal

        finally:
            repo_state_after = self._get_repo_working_tree_state(resolved_repo)
            if repo_state_before != repo_state_after:
                raise ExecutionError(f"Target repository mutation detected during prepare_real_repo_apply in '{resolved_repo}'!")

    def get_real_repo_apply_proposal(self, proposal_id: str) -> Optional[RealRepoApplyProposal]:
        """Retrieve a registered RealRepoApplyProposal by proposal_id from memory or durable storage."""
        if not proposal_id:
            return None
        clean_id = proposal_id.strip()
        if clean_id in self._real_repo_apply_proposals:
            return self._real_repo_apply_proposals[clean_id]

        # Durable storage recovery fallback (STEP 20A)
        try:
            proposal = self.durable_storage.load_proposal(clean_id, verify_integrity=True)
            self._real_repo_apply_proposals[clean_id] = proposal
            return proposal
        except (ProposalNotFoundError, ProposalIntegrityError, StorageError):
            return None

    def recover_real_repo_apply_proposal(
        self,
        proposal_id: str,
        verify_integrity: bool = True,
        target_repo_root: Optional[Union[str, Path]] = None,
    ) -> RealRepoApplyProposal:
        """Durable recovery API for Founder approval and restart workflows (STEP 20A).

        Loads proposal from durable storage, re-verifies patch SHA-256 and proposal SHA-256,
        ensures QA verdict is PASS, and checks target repository binding if provided.
        """
        proposal = self.durable_storage.load_proposal(proposal_id, verify_integrity=verify_integrity)
        self._real_repo_apply_proposals[proposal.proposal_id] = proposal

        if target_repo_root is not None:
            resolved_target = Path(target_repo_root).resolve()
            prop_target = Path(proposal.target_repository_root).resolve()
            if resolved_target != prop_target:
                raise ProposalMismatchError(
                    f"Target repository mismatch on recovery: expected '{resolved_target}', proposal has '{prop_target}'."
                )
            from .project import run_git
            code, head_out, _ = run_git(["rev-parse", "HEAD"], cwd=resolved_target)
            if code == 0:
                current_head = head_out.strip()
                if current_head != proposal.base_commit_hash:
                    raise ProposalMismatchError(
                        f"Base commit binding mismatch on recovery: current HEAD '{current_head}' "
                        f"!= proposal base commit '{proposal.base_commit_hash}'."
                    )

        return proposal

    def approve_real_repo_apply(
        self,
        proposal_id: str,
        founder_approval_id: str,
        approver: str = "Human Founder",
        project_id: Optional[str] = None,
    ) -> RealRepoApplyGrant:
        """Explicitly approve a RealRepoApplyProposal by Human Founder (STEP 16).

        PERFORMS ZERO REPOSITORY MUTATION.
        """
        if not proposal_id or not proposal_id.strip():
            raise ProposalMismatchError("proposal_id must not be empty.")

        proposal = self.get_real_repo_apply_proposal(proposal_id.strip())
        if not proposal:
            raise ProposalMismatchError(f"Proposal '{proposal_id}' not found in registered proposals.")

        if not founder_approval_id or not founder_approval_id.strip():
            raise MissingApprovalError("Explicit founder_approval_id is mandatory to approve real repo apply.")

        # Snapshot working tree state before
        repo_state_before = self._get_repo_working_tree_state(Path(proposal.target_repository_root))

        try:
            grant = derive_real_repo_apply_grant(
                proposal=proposal,
                founder_approval_id=founder_approval_id,
                approver=approver,
                project_id=project_id,
            )
            self._real_repo_apply_grants[grant.grant_id] = grant
            try:
                self.durable_storage.save_grant(grant)
            except Exception as exc:
                logger.warning("Failed to persist grant to durable storage: %s", exc)
            return grant
        finally:
            repo_state_after = self._get_repo_working_tree_state(Path(proposal.target_repository_root))
            if repo_state_before != repo_state_after:
                raise ExecutionError("Target repository mutation detected during approve_real_repo_apply!")

    def get_real_repo_apply_grant(self, grant_id: str) -> Optional[RealRepoApplyGrant]:
        """Retrieve an issued RealRepoApplyGrant by grant_id from memory or durable storage."""
        if not grant_id:
            return None
        clean_id = grant_id.strip()
        if clean_id in self._real_repo_apply_grants:
            return self._real_repo_apply_grants[clean_id]

        try:
            grant = self.durable_storage.load_grant(clean_id)
            self._real_repo_apply_grants[clean_id] = grant
            return grant
        except (GrantNotFoundError, GrantIntegrityError, StorageError):
            return None

    def execute_real_repo_apply(
        self,
        grant_id: str,
        project_id: Optional[str] = None,
    ) -> RealRepoApplyResult:
        """Execute transactional application of approved CODE_PATCH to real repository (STEP 16).

        Safety & Integrity Invariants:
        1. Single-use replay protection: consumed grants cannot be re-executed.
        2. External lock: stored in company runtime state, never target .git.
        3. Double TOCTOU pre-mutation check under lock (cleanliness + exact HEAD).
        4. Crash state classification: PARTIAL_OR_UNKNOWN_STATE fails closed.
        5. Zero agent runtime invocation: purely deterministic code execution.
        6. Post-apply diff equivalence: exact correspondence between git status and expected files.
        7. Non-destructive rollback: reverse patch apply restores clean state if validation fails.
        8. Durable receipt: materializes REAL_REPO_APPLY_REPORT artifact.
        """
        if not grant_id or not grant_id.strip():
            raise ApprovalInvalidError("grant_id must not be empty.")

        clean_grant_id = grant_id.strip()
        grant = self.get_real_repo_apply_grant(clean_grant_id)
        if not grant:
            raise ApprovalInvalidError(f"Grant '{grant_id}' not found in registered grants.")

        if grant.status == "CONSUMED":
            raise GrantReplayedError(f"Grant '{grant_id}' has already been consumed.")
        if grant.status != "ISSUED":
            raise ApprovalInvalidError(f"Grant '{grant_id}' status is '{grant.status}', expected 'ISSUED'.")

        # Cross-project mismatch protection
        proposal = self.get_real_repo_apply_proposal(grant.proposal_id)
        if project_id:
            if grant.project_id and grant.project_id != project_id:
                raise CrossProjectMismatchError(
                    f"Cross-project apply rejected: grant project '{grant.project_id}' != target project '{project_id}'."
                )
            if proposal and proposal.project_id and proposal.project_id != project_id:
                raise CrossProjectMismatchError(
                    f"Cross-project apply rejected: proposal project '{proposal.project_id}' != target project '{project_id}'."
                )
        if proposal and proposal.project_id and grant.project_id and proposal.project_id != grant.project_id:
            raise CrossProjectMismatchError(
                f"Cross-project apply rejected: proposal project '{proposal.project_id}' != grant project '{grant.project_id}'."
            )

        # Expiry check
        approved_dt = datetime.fromisoformat(grant.approved_at)
        now_dt = datetime.now(timezone.utc)
        elapsed = (now_dt - approved_dt).total_seconds()
        if elapsed > grant.validity_duration_seconds:
            raise GrantExpiredError(f"Grant '{grant_id}' has expired ({elapsed:.1f}s > {grant.validity_duration_seconds}s).")

        # Target repo check
        target_repo = Path(grant.target_repository_root).resolve()
        if not (target_repo / ".git").exists():
            raise TargetRepositoryInvalidError(f"Target directory '{target_repo}' is not a valid Git repository.")

        # Resolve code patch artifact and physical file
        patch_lineage = self.find_artifact(grant.code_patch_artifact_id)
        if patch_lineage:
            patch_task, patch_run, patch_art = patch_lineage
            patch_file_path = _resolve_artifact_file_path(Path(self.output_dir), patch_art)
            patch_bytes = patch_file_path.read_bytes()
        else:
            # Fallback to durable storage proposal patch (STEP 20A / 20C)
            durable_patch = self.durable_storage.proposals_dir / grant.proposal_id / "patch.diff"
            if durable_patch.is_file():
                patch_file_path = durable_patch
                patch_bytes = durable_patch.read_bytes()
                default_proj = list(self.company.projects.values())[0] if self.company.projects else None
                proj_id = grant.project_id or (default_proj.id if default_proj else "prj_default")
                patch_task = Task(
                    id=f"task_apply_{grant.proposal_id}",
                    project_id=proj_id,
                    title=f"RealRepoApply for {grant.proposal_id}",
                    goal="Execute human-approved RealRepoApply",
                    required_roles=["developer"],
                )
                if default_proj and patch_task.id not in default_proj.tasks:
                    default_proj.add_task(patch_task)
            else:
                raise CandidateNotEligibleError(f"CODE_PATCH artifact '{grant.code_patch_artifact_id}' not found.")

        actual_sha = hashlib.sha256(patch_bytes).hexdigest()
        if actual_sha != grant.code_patch_sha256:
            raise CandidateNotEligibleError(
                f"CODE_PATCH SHA mismatch: computed '{actual_sha}' != grant '{grant.code_patch_sha256}'."
            )
        patch_text = patch_bytes.decode("utf-8")

        start_time = datetime.now(timezone.utc)

        # External lock in company runtime state (Principle 1)
        locks_dir = Path(self.output_dir) / "locks"
        lock = RealRepoApplyLock(locks_dir=locks_dir, repo_root=target_repo)
        lock.acquire(grant.proposal_id)

        try:
            # Under external lock: Double pre-mutation TOCTOU check (Principle 4)
            # 1. Cleanliness & Crash State check
            allow_untracked = False
            if grant.project_id:
                proj_obj = self.project_registry.get_project(grant.project_id)
                if proj_obj and proj_obj.repository:
                    allow_untracked = proj_obj.repository.allow_untracked
            if not allow_untracked:
                for p in self.project_registry.list_projects():
                    if p.repository and Path(p.repository.root_path).resolve() == target_repo:
                        if p.repository.allow_untracked:
                            allow_untracked = True
                            break

            is_clean, dirty_stdout = verify_target_repo_cleanliness(target_repo, allow_untracked=allow_untracked)
            if not is_clean:
                crash_state = classify_crash_state(target_repo, patch_text, grant.expected_changed_files, allow_untracked=allow_untracked)
                if crash_state == CrashStateClassification.PARTIAL_OR_UNKNOWN_STATE:
                    raise CrashRecoveryBlockError(
                        f"Target repository '{target_repo}' has an unresolved crash/partial apply state ({crash_state.value}). "
                        f"Fails closed and blocks new apply.\nStatus:\n{dirty_stdout}"
                    )
                raise TargetRepositoryDirtyError(
                    f"Target repository '{target_repo}' is dirty before mutation:\n{dirty_stdout}"
                )

            # 2. Exact HEAD commit match
            current_head = resolve_repo_head_commit(target_repo)
            if current_head != grant.expected_head_hash:
                raise RepositoryStateChangedError(
                    f"TOCTOU violation: repository HEAD changed from approved '{grant.expected_head_hash}' "
                    f"to '{current_head}' before apply. Aborting mutation."
                )

            # 3. Non-mutating precheck under lock
            precheck_code_patch_applicability(target_repo, patch_text)

            # 4. Purely deterministic mutation boundary (Principle 11 & 12)
            # No agent runtime / LLM invocations occur!
            try:
                apply_code_patch_to_real_repo(target_repo, patch_text)
            except PatchApplyFailedError as exc:
                logger.warning("Patch apply failed (%s). Triggering rollback.", exc)
                rollback_real_repo_apply(target_repo, patch_text, grant.expected_changed_files, allow_untracked=allow_untracked)
                raise

            # 5. Exact diff equivalence validation (Principle 8)
            try:
                actual_files = validate_real_repo_diff(target_repo, grant.expected_changed_files, allow_untracked=allow_untracked)
            except PostApplyDiffMismatchError as val_exc:
                logger.warning("Post-apply diff validation failed (%s). Triggering rollback.", val_exc)
                rollback_real_repo_apply(target_repo, patch_text, grant.expected_changed_files, allow_untracked=allow_untracked)
                raise

            # 6. Consume the grant (single-use protection)
            updated_grant = RealRepoApplyGrant(
                schema_version=grant.schema_version,
                grant_id=grant.grant_id,
                proposal_id=grant.proposal_id,
                proposal_sha256=grant.proposal_sha256,
                target_repository_root=grant.target_repository_root,
                expected_head_hash=grant.expected_head_hash,
                code_patch_artifact_id=grant.code_patch_artifact_id,
                code_patch_sha256=grant.code_patch_sha256,
                qa_execution_report_artifact_id=grant.qa_execution_report_artifact_id,
                qa_execution_report_sha256=grant.qa_execution_report_sha256,
                expected_changed_files=grant.expected_changed_files,
                human_approval_id=grant.human_approval_id,
                approver=grant.approver,
                approved_at=grant.approved_at,
                status="CONSUMED",
                validity_duration_seconds=grant.validity_duration_seconds,
                project_id=grant.project_id,
                repository_id=grant.repository_id,
            )
            self._real_repo_apply_grants[clean_grant_id] = updated_grant
            try:
                self.durable_storage.save_grant(updated_grant)
            except Exception as exc:
                logger.warning("Failed to persist consumed grant to durable storage: %s", exc)

            end_time = datetime.now(timezone.utc)
            duration_ms = (end_time - start_time).total_seconds() * 1000.0

            result = RealRepoApplyResult(
                grant_id=grant.grant_id,
                proposal_id=grant.proposal_id,
                target_repository_root=grant.target_repository_root,
                status=RealRepoApplyStatus.APPLIED_SUCCESSFULLY.value,
                summary=f"Successfully applied CODE_PATCH '{grant.code_patch_artifact_id}' to real repository working tree.",
                pre_apply_head=grant.expected_head_hash,
                post_apply_head=current_head,
                expected_files=list(grant.expected_changed_files),
                actual_files=actual_files,
                duration_ms=duration_ms,
            )

            # Materialize durable receipt artifact REAL_REPO_APPLY_REPORT
            apply_run = patch_task.create_run()
            apply_run.status = RunStatus.SUCCESS.value
            report_art = materialize_real_repo_apply_report_artifact(
                base_output_dir=Path(self.output_dir),
                task=patch_task,
                run=apply_run,
                result=result,
                filename="real_repo_apply_report.md",
            )
            apply_run.complete(status=RunStatus.SUCCESS.value)
            result.report_artifact_id = report_art.id

            # Save durable receipt in proposal directory if available
            try:
                apply_result_path = self.durable_storage.proposals_dir / grant.proposal_id / "apply_result.json"
                if apply_result_path.parent.is_dir():
                    atomic_write_text(apply_result_path, json.dumps(result.to_dict(), indent=2))
            except Exception as exc:
                logger.warning("Failed to persist apply result to durable storage: %s", exc)

            return result

        finally:
            lock.release()

    # --------------------------------------------------------------------------
    # CEO Orchestration Planning (STEP 17B-2)
    # --------------------------------------------------------------------------

    def propose_initial_company_plan(
        self,
        objective: CompanyObjective,
        timeout: Optional[float] = None,
        project_knowledge: Optional[Any] = None,
    ) -> CEOOrchestrationPlan:
        """Invoke the real CEO Agent to formulate an initial macro orchestration plan.

        Enforces:
        - Bounded planning prompt generation containing the CompanyObjective.
        - Execution via the real AntigravityRuntime adapter.
        - Runtime execution success check.
        - Strict JSON extraction and trust boundary schema validation.
        - Deterministic DAG validation (Fan-In, depth, cycle, roles).
        - Zero specialist task execution, zero repository mutation, zero grant creation.

        Returns:
            Validated, accepted CEOOrchestrationPlan (pure inert data).
        """
        if not isinstance(objective, CompanyObjective):
            raise CompanyServiceError("Expected CompanyObjective instance.")

        prompt = build_ceo_planning_prompt(objective, project_knowledge=project_knowledge)
        exec_result = self.runtime.execute(
            agent="ceo",
            prompt=prompt,
            timeout=timeout,
        )
        if not exec_result.success:
            err_msg = (
                f"CEO agent execution failed (exit_code={exec_result.exit_code}, "
                f"timed_out={exec_result.timed_out}): {exec_result.stderr}"
            )
            raise ExecutionError(err_msg)

        plan = parse_and_validate_ceo_plan(exec_result.stdout, objective)
        return plan

    # --------------------------------------------------------------------------
    # Company Run Orchestration Engine (STEP 17B-3)
    # --------------------------------------------------------------------------

    def create_company_run(
        self,
        objective: CompanyObjective,
        project_id: Optional[str] = None,
        repository_id: Optional[str] = None,
        target_branch: Optional[str] = None,
        base_commit_hash: Optional[str] = None,
    ) -> CompanyRun:
        """Create a new CompanyRun coordinator from a CompanyObjective.

        Enforces:
        - Application-generated run_id (never supplied by CEO).
        - Initial state CREATED.
        - Objective bound immutably to run.
        - Project and repository identity bound immutably for Project-backed runs.
        - Counters initialized to zero.
        - No active plan initially, empty plan history, no active escalation.
        - Initial audit event recorded.
        - Durable minimal V1 state persistence.
        """
        if not isinstance(objective, CompanyObjective):
            raise OrchestrationError("Expected CompanyObjective instance.")

        bound_project_id = project_id or objective.project_id
        if project_id and objective.project_id and project_id != objective.project_id:
            raise OrchestrationError(
                f"Conflicting project_id: argument '{project_id}' != objective '{objective.project_id}'."
            )

        # Target Repository Identity Fail-Closed Guard
        verification_dict = None
        if bound_project_id:
            repo_proj = self.project_registry.get_project(bound_project_id)
            if repo_proj:
                verification = verify_target_repository_identity(
                    project=repo_proj,
                    candidate_repo_path=objective.target_repository,
                    expected_head=base_commit_hash,
                    expected_branch=target_branch,
                )
                verification_dict = verification.to_dict()

        run_id = f"crun_{uuid.uuid4().hex[:8]}"
        run = CompanyRun(
            run_id=run_id,
            objective=objective,
            state=CompanyRunState.CREATED.value,
            project_id=bound_project_id,
            repository_id=repository_id,
            target_branch=target_branch,
            base_commit_hash=base_commit_hash,
            target_repository_verification=verification_dict,
        )
        run.add_event(
            event_type="RUN_CREATED",
            reason="CompanyRun created from CompanyObjective",
            details={"target_repository_verification": verification_dict} if verification_dict else None,
        )
        self.save_company_run(run)
        return run

    def plan_company_run(
        self,
        run_id: str,
        timeout: Optional[float] = None,
    ) -> CompanyRun:
        """Execute the CEO planning phase for a CompanyRun.

        Enforces:
        - State transition: CREATED -> PLANNING.
        - Real CEO planning invocation via propose_initial_company_plan.
        - Increments ceo_invocation_count by exactly 1.
        - Validated plan attached to run and immutable plan history updated.
        - State transition: PLANNING -> PLAN_READY.
        - Fail-closed on error: transition to FAILED with error recorded.
        - Audit events recorded.
        """
        run = self.get_company_run(run_id)
        run.transition_to(CompanyRunState.PLANNING)
        run.add_event(
            event_type="PLANNING_STARTED",
            reason="CEO initial planning invocation started",
        )
        run.ceo_invocation_count += 1
        self.save_company_run(run)

        ceo_knowledge = None
        if run.project_id:
            catalog = self.get_project_knowledge_catalog(run.project_id)
            if catalog:
                ceo_policy = RoleKnowledgePolicy(
                    role="ceo",
                    primary_domains=("product", "architecture"),
                    max_sources=2,
                )
                selected_sources = catalog.select_sources_for_role(ceo_policy)
                ceo_knowledge = [
                    catalog.load_excerpt(s, repository_revision=run.base_commit_hash or "HEAD", max_chars=2500)
                    for s in selected_sources
                ]

        try:
            plan = self.propose_initial_company_plan(
                run.objective,
                timeout=timeout,
                project_knowledge=ceo_knowledge,
            )
        except Exception as exc:
            run.transition_to(CompanyRunState.FAILED, error=str(exc))
            run.add_event(
                event_type="RUN_FAILED",
                reason=f"CEO planning failed: {exc}",
            )
            self.save_company_run(run)
            raise

        run.set_plan(plan)
        run.transition_to(CompanyRunState.PLAN_READY)
        run.add_event(
            event_type="CEO_PLAN_ACCEPTED",
            reason="CEO plan parsed, verified, and accepted",
            details={
                "plan_id": plan.plan_id,
                "work_items_count": len(plan.work_items),
            },
        )
        self.save_company_run(run)
        return run

    def start_company_run(self, run_id: str) -> CompanyRun:
        """Start execution of a planned CompanyRun.

        Enforces:
        - State must be PLAN_READY.
        - Active plan must exist and pass DAG structural validation again.
        - State transition: PLAN_READY -> RUNNING.
        - Audit event recorded.
        """
        run = self.get_company_run(run_id)
        if run.state != CompanyRunState.PLAN_READY.value:
            raise TransitionPolicyError(
                f"Cannot start CompanyRun '{run_id}': State is '{run.state}', expected '{CompanyRunState.PLAN_READY.value}'."
            )
        if not run.active_plan:
            raise PlanValidationError(f"CompanyRun '{run_id}' has no active plan.")

        validate_dag_structure(run.active_plan)

        # Target Repository Identity Guard
        if run.project_id:
            repo_proj = self.project_registry.get_project(run.project_id)
            if repo_proj:
                verification = verify_target_repository_identity(
                    project=repo_proj,
                    candidate_repo_path=run.objective.target_repository,
                    expected_head=run.base_commit_hash,
                    expected_branch=run.target_branch,
                )
                run.target_repository_verification = verification.to_dict()

        run.transition_to(CompanyRunState.RUNNING)
        run.add_event(
            event_type="RUN_STARTED",
            reason="CompanyRun transitioned to RUNNING",
            details={"target_repository_verification": run.target_repository_verification} if run.target_repository_verification else None,
        )
        self.save_company_run(run)
        return run

    def execute_next_company_work(self, run_id: str) -> Optional[CompanyRun]:
        """Execute AT MOST ONE ready macro work item within a RUNNING CompanyRun.

        Deterministic Progression:
        1. Inspect CompanyRun (requires RUNNING).
        2. Identify completed work items.
        3. Deterministically select next ready work item: (priority ASC, work_item_id ASC).
        4. Validate role: closed mapping ('research', 'product', 'ux', 'marketing').
           'developer' -> explicit UnsupportedRoleError boundary (fail closed / stop).
           'qa' -> UnsupportedRoleError boundary (fail closed / stop).
        5. Mark work item RUNNING and record audit event.
        6. Translate CEO planned work item into typed application Task.
        7. Resolve completed dependency artifacts and enforce ALLOWED_HANDOFF_EDGES.
        8. Assemble role-specific ContextEnvelope (validating token budget & policies).
        9. Dispatch to existing specialist execution method.
        10. Verify resulting canonical artifact exists on disk and SHA-256 matches.
        11. Create bounded EmployeeResultSummary and bind Task/TaskRun IDs to work item.
        12. Mark work item COMPLETED and increment specialist_invocation_count.
        13. Evaluate non-code completion gate (if all plan items COMPLETED -> RUN COMPLETED).
        14. Persist updated CompanyRun.
        15. CRITICAL: CEO IS NEVER INVOKED DURING EXECUTION (ceo_invocation_count unchanged).
        """
        run = self.get_company_run(run_id)
        if run.state != CompanyRunState.RUNNING.value:
            raise TransitionPolicyError(
                f"Cannot execute work: CompanyRun '{run_id}' is in state '{run.state}', expected '{CompanyRunState.RUNNING.value}'."
            )
        if not run.active_plan:
            raise PlanValidationError(f"CompanyRun '{run_id}' has no active plan.")

        # Completed item IDs
        completed_ids = {
            item_id for item_id, st in run.work_item_states.items()
            if st == WorkItemState.COMPLETED.value
        }

        # Check if already completed
        if len(completed_ids) == len(run.active_plan.work_items) and len(run.active_plan.work_items) > 0:
            if not run.is_code_workflow:
                run.transition_to(CompanyRunState.COMPLETED)
                run.add_event("RUN_COMPLETED", reason="All planned non-code work items completed and verified")
                self.save_company_run(run)
            return run

        # Select ready items deterministically
        ready_items = select_ready_work_items(run.active_plan, completed_ids, run.work_item_states)
        if not ready_items:
            # Check if all completed
            if all(run.work_item_states.get(item.work_item_id) == WorkItemState.COMPLETED.value for item in run.active_plan.work_items):
                if not run.is_code_workflow:
                    run.transition_to(CompanyRunState.COMPLETED)
                    run.add_event("RUN_COMPLETED", reason="All planned non-code work items completed and verified")
                    self.save_company_run(run)
                return run

            # If not all completed and none ready, check if any failed
            has_failed = any(st == WorkItemState.FAILED.value for st in run.work_item_states.values())
            if has_failed:
                err_msg = "Unresolvable dependency failure: a prerequisite work item failed."
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                run.add_event("RUN_FAILED", reason=err_msg)
            else:
                err_msg = "No ready work items available in plan DAG."
                run.transition_to(CompanyRunState.BLOCKED, error=err_msg)
                run.add_event("RUN_FAILED", reason=err_msg)
            self.save_company_run(run)
            return run

        # Select exactly ONE ready item
        target_item = ready_items[0]
        role = target_item.role.lower()

        # Enforce budget limits
        if run.specialist_invocation_count >= len(run.active_plan.work_items):
            err_msg = (
                f"Specialist invocation count ({run.specialist_invocation_count}) "
                f"exceeds planned work items budget ({len(run.active_plan.work_items)})."
            )
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            run.add_event("RUN_FAILED", reason=err_msg)
            self.save_company_run(run)
            raise OrchestrationError(err_msg)

        # Enforce STEP 17B-4 role dispatching & STEP 23B.1 QA capability validation
        if role == "qa":
            qa_cap = (target_item.capability or "").strip().lower()
            if not qa_cap:
                for out in target_item.expected_outputs:
                    norm_out = str(out).strip().lower()
                    if norm_out in SUPPORTED_QA_CAPABILITIES:
                        qa_cap = norm_out
                        break

            if qa_cap not in SUPPORTED_QA_CAPABILITIES:
                err_msg = (
                    f"QA work item '{target_item.work_item_id}' has unsupported capability '{qa_cap}'. "
                    f"Ordinary QA in DAG only supports non-mutating planning/audit: {sorted(SUPPORTED_QA_CAPABILITIES)}. "
                    f"QA certification is strictly application-owned inside code pipelines."
                )
                target_item.state = WorkItemState.BLOCKED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.BLOCKED.value
                run.transition_to(CompanyRunState.BLOCKED, error=err_msg)
                run.add_event(
                    event_type="WORK_ITEM_FAILED",
                    work_item_id=target_item.work_item_id,
                    role=role,
                    reason=err_msg,
                )
                run.add_event(
                    event_type="RUN_FAILED",
                    reason=err_msg,
                )
                self.save_company_run(run)
                raise UnsupportedRoleError(err_msg)

        if role == "developer":
            obj_constraints = [str(c).lower() for c in (run.objective.constraints or [])]
            if not getattr(self, "enable_engineering_pipeline", True) or any(
                c in ("no developer role", "no code changes", "no source-code mutation") for c in obj_constraints
            ):
                err_msg = (
                    f"Role '{role}' is unsupported in STEP 17B-3 (non-code workflows only). "
                    f"Execution stopped at phase boundary."
                )
                target_item.state = WorkItemState.BLOCKED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.BLOCKED.value
                run.transition_to(CompanyRunState.BLOCKED, error=err_msg)
                run.add_event(
                    event_type="WORK_ITEM_FAILED",
                    work_item_id=target_item.work_item_id,
                    role=role,
                    reason=err_msg,
                )
                run.add_event(
                    event_type="RUN_FAILED",
                    reason=err_msg,
                )
                self.save_company_run(run)
                raise UnsupportedRoleError(err_msg)

            # Dispatch Developer macro work item to EngineeringPipelineAdapter
            return self.execute_developer_company_work(run_id=run.run_id, work_item_id=target_item.work_item_id)

        if role not in ("research", "product", "ux", "marketing", "qa"):
            err_msg = f"Unknown or unsupported specialist role '{role}' in work item '{target_item.work_item_id}'."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            run.add_event(
                event_type="WORK_ITEM_FAILED",
                work_item_id=target_item.work_item_id,
                role=role,
                reason=err_msg,
            )
            run.add_event(
                event_type="RUN_FAILED",
                reason=err_msg,
            )
            self.save_company_run(run)
            raise UnsupportedRoleError(err_msg)

        # Mark work item RUNNING
        target_item.state = WorkItemState.RUNNING.value
        run.work_item_states[target_item.work_item_id] = WorkItemState.RUNNING.value
        run.add_event(
            event_type="WORK_ITEM_STARTED",
            work_item_id=target_item.work_item_id,
            role=role,
            reason=f"Started execution of {target_item.work_item_id}",
        )
        self.save_company_run(run)

        # Ensure project exists
        proj_id = run.project_id or f"proj_{run.run_id}"
        if proj_id not in self.company.projects:
            self.create_project(proj_id, name=f"Project for {run.objective.title}")
        proj = self.get_project(proj_id)

        # Translate to typed Task
        task_id = f"task_{run.run_id}_{target_item.work_item_id}"
        task_expected = list(target_item.expected_outputs)
        if target_item.capability and target_item.capability not in task_expected:
            task_expected.append(target_item.capability)

        task = self.create_task(
            project_id=proj.id,
            title=f"[{role.upper()}] {target_item.objective[:60]}",
            goal=target_item.objective,
            task_id=task_id,
            constraints=list(run.objective.constraints),
            required_roles=[role],
            expected_output=task_expected,
        )
        target_item.task_id = task.id
        target_item.run_id = run.run_id

        # Resolve completed dependencies & attach permitted input artifacts
        for dep_id in target_item.depends_on:
            dep_item = next((w for w in run.active_plan.work_items if w.work_item_id == dep_id), None)
            if dep_item and dep_item.task_id:
                dep_task = self.get_task(dep_item.task_id, project_id=proj.id)
                for run_attempt in dep_task.runs:
                    if run_attempt.status == RunStatus.SUCCESS.value:
                        for art in run_attempt.artifacts:
                            producer_norm = (dep_item.role or "").strip().lower()
                            consumer_norm = role.strip().lower()
                            if (producer_norm, consumer_norm) in ALLOWED_HANDOFF_EDGES:
                                self.attach_input_artifact(
                                    target_task_id=task.id,
                                    source_artifact_id=art.id,
                                    project_id=proj.id,
                                )

        # Assemble and validate role-specific ContextEnvelope
        available_arts: Dict[str, Artifact] = {}
        for ref in task.input_artifacts:
            lineage = self.find_artifact(ref.artifact_id)
            if lineage:
                available_arts[ref.artifact_id] = lineage[2]

        role_knowledge = None
        if run.project_id:
            catalog = self.get_project_knowledge_catalog(run.project_id)
            if catalog:
                role_policy = RoleKnowledgePolicy(
                    role=role,
                    primary_domains=("product", "brand") if role in ("product", "marketing") else ("frontend", "brand") if role == "ux" else ("backend", "architecture"),
                    max_sources=2,
                )
                selected_sources = catalog.select_sources_for_role(role_policy)
                role_knowledge = [
                    catalog.load_excerpt(s, repository_revision=run.base_commit_hash or "HEAD", max_chars=2500)
                    for s in selected_sources
                ]

        assemble_specialist_context(
            recipient_role=role,
            objective=run.objective,
            work_item=target_item,
            base_output_dir=self.output_dir,
            available_artifacts=available_arts,
            artifact_input_refs=task.input_artifacts,
            summaries=run.employee_summaries,
            constraints=run.objective.constraints,
            company_run_state=run.state,
            project_knowledge=role_knowledge,
        )

        # Closed role dispatch
        try:
            if role == "research":
                task_run = self.execute_research_task(task.id, project_id=proj.id)
            elif role == "product":
                task_run = self.execute_product_task(task.id, project_id=proj.id)
            elif role == "ux":
                task_run = self.execute_ux_task(task.id, project_id=proj.id)
            elif role == "marketing":
                task_run = self.execute_marketing_task(task.id, project_id=proj.id)
            elif role == "qa":
                qa_cap = (target_item.capability or "").strip().lower()
                if not qa_cap:
                    for out in target_item.expected_outputs:
                        norm_out = str(out).strip().lower()
                        if norm_out in SUPPORTED_QA_CAPABILITIES:
                            qa_cap = norm_out
                            break
                task_run = self.execute_qa_planning_task(
                    task.id,
                    project_id=proj.id,
                    capability=qa_cap,
                )
            else:
                raise UnsupportedRoleError(f"Unsupported specialist role '{role}'.")
        except Exception as exec_err:
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=str(exec_err))
            run.add_event(
                event_type="WORK_ITEM_FAILED",
                work_item_id=target_item.work_item_id,
                role=role,
                task_id=task.id,
                reason=str(exec_err),
            )
            run.add_event(
                event_type="RUN_FAILED",
                reason=f"Execution error on work item {target_item.work_item_id}: {exec_err}",
            )
            self.save_company_run(run)
            raise

        # Verify task execution outcome
        task_updated = self.get_task(task.id, project_id=proj.id)
        if task_updated.status != TaskStatus.COMPLETED.value or task_run.status != RunStatus.SUCCESS.value:
            err_msg = task_run.error or f"Specialist '{role}' failed task '{task.id}'."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            run.add_event(
                event_type="WORK_ITEM_FAILED",
                work_item_id=target_item.work_item_id,
                role=role,
                task_id=task.id,
                reason=err_msg,
            )
            run.add_event(
                event_type="RUN_FAILED",
                reason=f"Specialist task {task.id} failed: {err_msg}",
            )
            self.save_company_run(run)
            return run

        # Canonical Artifact Verification (Fail closed if no artifacts or checksum mismatch)
        if not task_run.artifacts:
            err_msg = f"Work item '{target_item.work_item_id}' produced no durable artifacts."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            run.add_event(
                event_type="WORK_ITEM_FAILED",
                work_item_id=target_item.work_item_id,
                role=role,
                task_id=task.id,
                reason=err_msg,
            )
            run.add_event("RUN_FAILED", reason=err_msg)
            self.save_company_run(run)
            raise ArtifactVerificationError(err_msg)

        verified_artifact_refs: List[Dict[str, Any]] = []
        for art in task_run.artifacts:
            art_path = _resolve_artifact_file_path(self.output_dir, art)
            if not art_path.is_file():
                err_msg = f"Artifact file '{art.path}' does not exist on disk."
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                run.add_event(
                    event_type="WORK_ITEM_FAILED",
                    work_item_id=target_item.work_item_id,
                    role=role,
                    task_id=task.id,
                    reason=err_msg,
                )
                run.add_event("RUN_FAILED", reason=err_msg)
                self.save_company_run(run)
                raise ArtifactVerificationError(err_msg)

            actual_sha = hashlib.sha256(art_path.read_bytes()).hexdigest()
            if actual_sha != art.sha256:
                err_msg = f"Artifact checksum mismatch for '{art.name}': expected {art.sha256}, got {actual_sha}."
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                run.add_event(
                    event_type="WORK_ITEM_FAILED",
                    work_item_id=target_item.work_item_id,
                    role=role,
                    task_id=task.id,
                    reason=err_msg,
                )
                run.add_event("RUN_FAILED", reason=err_msg)
                self.save_company_run(run)
                raise ArtifactVerificationError(err_msg)

            verified_artifact_refs.append({
                "artifact_id": art.id,
                "name": art.name,
                "type": str(art.artifact_type),
                "sha256": art.sha256,
                "path": art.path,
                "producer_role": art.producer_role,
            })

        # Bind success to work item
        target_item.task_id = task.id
        target_item.run_id = task_run.id
        target_item.state = WorkItemState.COMPLETED.value
        run.work_item_states[target_item.work_item_id] = WorkItemState.COMPLETED.value
        run.specialist_invocation_count += 1

        # Create bounded EmployeeResultSummary
        summary = EmployeeResultSummary(
            role=role,
            task_id=task.id,
            run_id=task_run.id,
            status=task_updated.status,
            artifact_refs=verified_artifact_refs,
            summary=task_updated.result.summary if task_updated.result else "",
            blockers=[],
        )
        run.employee_summaries.append(summary)

        run.add_event(
            event_type="WORK_ITEM_COMPLETED",
            work_item_id=target_item.work_item_id,
            role=role,
            task_id=task.id,
            artifact_refs=verified_artifact_refs,
            reason=f"Work item {target_item.work_item_id} completed successfully",
        )

        # Deterministic Non-Code Completion Gate
        all_completed = all(
            run.work_item_states.get(w.work_item_id) == WorkItemState.COMPLETED.value
            for w in run.active_plan.work_items
        )
        if all_completed and not run.is_code_workflow:
            run.transition_to(CompanyRunState.COMPLETED)
            run.add_event(
                event_type="RUN_COMPLETED",
                reason="All planned non-code work items completed and verified",
            )

        self.save_company_run(run)
        return run

    step_company_work = execute_next_company_work

    def run_company_until_boundary(
        self,
        run_id: str,
        max_steps: int = 10,
    ) -> CompanyRun:
        """Execute successive ready work items until a terminal state or phase boundary is reached.

        Bounded by max_steps to prevent infinite loops.
        Stops at READY_FOR_HUMAN_APPLY for code workflows (autonomous company cannot approve apply).
        """
        steps = 0
        while steps < max_steps:
            run = self.get_company_run(run_id)
            if run.state in (
                CompanyRunState.COMPLETED.value,
                CompanyRunState.FAILED.value,
                CompanyRunState.BLOCKED.value,
                CompanyRunState.WAITING_FOR_HUMAN.value,
                CompanyRunState.READY_FOR_HUMAN_APPLY.value,
            ):
                break
            if run.state != CompanyRunState.RUNNING.value:
                break

            # Inspect ready work
            completed_ids = {
                item_id for item_id, st in run.work_item_states.items()
                if st == WorkItemState.COMPLETED.value
            }
            ready_items = select_ready_work_items(run.active_plan, completed_ids, run.work_item_states)
            if not ready_items:
                # Check if all completed
                if all(st == WorkItemState.COMPLETED.value for st in run.work_item_states.values()):
                    if not run.is_code_workflow:
                        run.transition_to(CompanyRunState.COMPLETED)
                        run.add_event("RUN_COMPLETED", reason="All planned non-code work items completed and verified")
                        self.save_company_run(run)
                break

            # Execute next unit of work
            try:
                self.execute_next_company_work(run_id)
            except UnsupportedRoleError:
                # Boundary reached (e.g. Developer or unknown role)
                break
            except Exception:
                # Stop on failure
                break

            steps += 1

        return self.get_company_run(run_id)

    def get_company_run(self, run_id: str) -> CompanyRun:
        """Retrieve a CompanyRun by run_id from memory or durable disk."""
        if run_id in self._company_runs:
            return self._company_runs[run_id]

        # 1. Durable storage lookup (STEP 20A)
        try:
            run = self.durable_storage.load_company_run(run_id)
            self._company_runs[run.run_id] = run
            return run
        except (CompanyRunNotFoundError, StorageError):
            pass

        # 2. File-backed flat fallback
        run_file = self.output_dir / "company_runs" / f"{run_id}.json"
        if run_file.is_file():
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
                run = CompanyRun.from_dict(data)
                self._company_runs[run.run_id] = run
                return run
            except Exception as exc:
                raise OrchestrationError(f"Failed to load CompanyRun '{run_id}' from disk: {exc}") from exc

        raise OrchestrationError(f"CompanyRun '{run_id}' not found.")

    def list_company_runs(self) -> List[CompanyRun]:
        """List all active, loaded, or persisted CompanyRuns."""
        runs_map = {r.run_id: r for r in self._company_runs.values()}
        try:
            for r in self.durable_storage.list_company_runs():
                if r.run_id not in runs_map:
                    runs_map[r.run_id] = r
        except Exception:
            pass
        return list(runs_map.values())

    def save_company_run(self, run: CompanyRun) -> None:
        """Persist CompanyRun to in-memory store and durable storage."""
        self._company_runs[run.run_id] = run

        # 1. Durable storage structured persistence (STEP 20A)
        try:
            self.durable_storage.save_company_run(run)
        except Exception as exc:
            logger.warning("Failed to save CompanyRun to durable storage: %s", exc)

        # 2. File-backed flat JSON for backwards compatibility
        runs_dir = self.output_dir / "company_runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"{run.run_id}.json"
        run_file.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")

    def execute_developer_company_work(
        self,
        run_id: str,
        work_item_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> CompanyRun:
        """Execute a ready Developer macro work item through the engineering pipeline."""
        run = self.get_company_run(run_id)
        if not run.active_plan:
            raise PlanValidationError(f"CompanyRun '{run_id}' has no active plan.")

        target_item = None
        if work_item_id:
            target_item = next((w for w in run.active_plan.work_items if w.work_item_id == work_item_id), None)
        else:
            completed_ids = {
                item_id for item_id, st in run.work_item_states.items()
                if st == WorkItemState.COMPLETED.value
            }
            ready_items = select_ready_work_items(run.active_plan, completed_ids, run.work_item_states)
            for item in ready_items:
                if item.role.lower() == "developer":
                    target_item = item
                    break

        if not target_item:
            raise OrchestrationError(f"No ready developer work item found in CompanyRun '{run_id}'.")

        adapter = EngineeringPipelineAdapter(self)
        return adapter.execute_developer_work(run=run, target_item=target_item, timeout=timeout)

    def approve_company_repo_apply(
        self,
        run_id: str,
        founder_approval_id: str,
        approver: str = "Human Founder",
    ) -> RealRepoApplyGrant:
        """Explicitly approve real repository apply by Human Founder for a CompanyRun (STEP 17B-4)."""
        run = self.get_company_run(run_id)
        adapter = EngineeringPipelineAdapter(self)
        return adapter.approve_repo_apply(
            run=run,
            founder_approval_id=founder_approval_id,
            approver=approver,
        )

    def apply_approved_company_repo(
        self,
        run_id: str,
    ) -> RealRepoApplyResult:
        """Execute transactional application of approved patch to repository for a CompanyRun (STEP 17B-4)."""
        run = self.get_company_run(run_id)
        adapter = EngineeringPipelineAdapter(self)
        return adapter.apply_repo(run=run)

    def apply_company_repo_with_human_approval(
        self,
        run_id: str,
        founder_approval_id: str,
        approver: str = "Human Founder",
    ) -> RealRepoApplyResult:
        """Convenience helper: approve and execute real repository apply in sequence."""
        self.approve_company_repo_apply(
            run_id=run_id,
            founder_approval_id=founder_approval_id,
            approver=approver,
        )
        return self.apply_approved_company_repo(run_id=run_id)


def _resolve_artifact_file_path(base_output_dir: Path, artifact: Artifact) -> Path:
    """Resolve an artifact's physical path on disk, preventing directory traversal."""
    if not artifact.path or ".." in artifact.path:
        raise CandidateNotEligibleError(
            f"Invalid artifact path '{artifact.path}': Directory traversal not allowed."
        )
    base_resolved = base_output_dir.resolve()
    target_path = (base_resolved / artifact.path).resolve()
    if not target_path.is_relative_to(base_resolved):
        raise CandidateNotEligibleError(
            f"Path traversal detected: Artifact path '{target_path}' escapes root '{base_resolved}'."
        )
    if not target_path.is_file():
        raise CandidateNotEligibleError(
            f"Artifact file does not exist at '{target_path}'."
        )
    return target_path









