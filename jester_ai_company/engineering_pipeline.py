"""Engineering Pipeline Integration Adapter (STEP 17B-4).

Binds the CompanyRun deterministic orchestration engine to the existing
engineering primitives:
Developer Planning -> ExecutionGrant -> Isolated Mutation -> QA Inspection ->
QA Verification -> Bounded Repair -> READY_FOR_HUMAN_APPLY -> Human Apply -> COMPLETED.

Security & Architecture Invariants:
1. Exact Fan-In Prerequisite: Developer macro work items strictly require direct completed
   Product and UX dependencies with verified durable artifacts.
2. ExecutionGrant Security Boundary: Zero ungranted mutations. Mutation is authorized
   only through an immutable, application-validated ExecutionGrant.
3. Isolated Worktree Execution: Real repository is never touched during autonomous execution.
4. Application-Owned QA: QA is non-optional and application-governed. CEO cannot skip QA.
5. Bounded Repair Loop: QA failure triggers bounded repair capped at MAX_REPAIR_ITERATIONS (2).
6. Autonomous Stop Boundary: Autonomous company execution STOPS at READY_FOR_HUMAN_APPLY.
   The autonomous company cannot approve its own repository apply.
7. Explicit Human Action: Real repository apply requires explicit Human approval via
   approve_company_repo_apply.
8. Transactional Real Apply: Apply is executed through the existing safe RealRepoApply engine
   with double TOCTOU check, diff equivalence check, and non-destructive rollback.
9. Minimal V1 Crash / Resume: Verified durable state (plan, grant, patch, QA reports) is reused
   without repeating expensive/destructive steps. Tampered state fails closed.
"""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .core import (
    ALLOWED_HANDOFF_EDGES,
    Artifact,
    ArtifactType,
    ArtifactVerificationError,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from .execution_grant import (
    ExecutionGrant,
    MissingApprovalError,
    ProtectedPathError,
    VerificationAction,
)
from .worktree import is_test_file
from .orchestrator import (
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    EmployeeResultSummary,
    OrchestrationError,
    PlanValidationError,
    TransitionPolicyError,
    UnsupportedRoleError,
    WorkItemState,
)
from .real_repo_apply import (
    ApprovalInvalidError,
    CandidateNotEligibleError,
    ProposalMismatchError,
    RealRepoApplyGrant,
    RealRepoApplyProposal,
    RealRepoApplyResult,
    RealRepoApplyStatus,
    TargetRepositoryInvalidError,
)
from .repair import (
    MAX_REPAIR_ITERATIONS,
    DeveloperQARepairLoopResult,
    RepairWorkflowStatus,
)
from .developer_mutation import DeveloperMutationStatus
from .durable_storage import ProposalNotFoundError
from .project import TargetRepositoryMismatchError, verify_target_repository_identity


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


class EngineeringPipelineError(OrchestrationError):
    """Raised when an error occurs during engineering pipeline execution."""
    pass


class EngineeringPreconditionError(EngineeringPipelineError):
    """Raised when Developer prerequisite invariants (Product + UX fan-in) are not satisfied."""
    pass


class EngineeringPipelineAdapter:
    """Coordinates the existing engineering pipeline with CompanyRun orchestration."""

    def __init__(self, service: Any):
        self.service = service

    def execute_developer_work(
        self,
        run: CompanyRun,
        target_item: CEOPlannedWorkItem,
        timeout: Optional[float] = None,
    ) -> CompanyRun:
        """Execute a ready Developer macro work item through the engineering pipeline.

        Enforces:
        1. Product + UX Fan-In Prerequisite (fail closed if missing or unverified).
        2. Developer Planning execution with verified durable artifact.
        3. ExecutionGrant derivation and validation.
        4. Isolated worktree developer mutation producing canonical verified CODE_PATCH.
        5. Application-owned QA Inspection and QA Verification in fresh disposable worktree.
        6. Bounded repair loop (up to MAX_REPAIR_ITERATIONS=2) on QA failure.
        7. RealRepoApplyProposal preparation on QA PASS.
        8. Transition CompanyRun to READY_FOR_HUMAN_APPLY and STOP.
        9. Bounded EmployeeResultSummary for Developer and QA.
        10. Full audit event trace.
        """
        if run.state != CompanyRunState.RUNNING.value:
            raise TransitionPolicyError(
                f"Cannot execute developer work: CompanyRun '{run.run_id}' is in state '{run.state}', expected '{CompanyRunState.RUNNING.value}'."
            )

        role = target_item.role.strip().lower()
        if role != "developer":
            raise UnsupportedRoleError(f"EngineeringPipelineAdapter only executes 'developer' work items, got '{role}'.")

        # ----------------------------------------------------------------------
        # 1. Product + UX Fan-In Prerequisite Verification
        # ----------------------------------------------------------------------
        prod_item = None
        ux_item = None

        for dep_id in target_item.depends_on:
            dep_w = next((w for w in run.active_plan.work_items if w.work_item_id == dep_id), None)
            if dep_w:
                dep_role = (dep_w.role or "").strip().lower()
                if dep_role == "product":
                    prod_item = dep_w
                elif dep_role == "ux":
                    ux_item = dep_w

        if not prod_item or not ux_item:
            err_msg = (
                f"Developer macro work item '{target_item.work_item_id}' violates Product + UX Fan-In invariant: "
                f"requires direct dependencies on BOTH Product and UX work items. "
                f"Found depends_on: {target_item.depends_on}."
            )
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            run.add_event(
                event_type="WORK_ITEM_FAILED",
                work_item_id=target_item.work_item_id,
                role=role,
                reason=err_msg,
            )
            run.add_event("RUN_FAILED", reason=err_msg)
            self.service.save_company_run(run)
            raise EngineeringPreconditionError(err_msg)

        # Verify completed states
        prod_state = run.work_item_states.get(prod_item.work_item_id)
        ux_state = run.work_item_states.get(ux_item.work_item_id)
        if prod_state != WorkItemState.COMPLETED.value or ux_state != WorkItemState.COMPLETED.value:
            err_msg = (
                f"Developer work item '{target_item.work_item_id}' prerequisites incomplete: "
                f"Product '{prod_item.work_item_id}' state is '{prod_state}', UX '{ux_item.work_item_id}' state is '{ux_state}'."
            )
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            run.add_event(
                event_type="WORK_ITEM_FAILED",
                work_item_id=target_item.work_item_id,
                role=role,
                reason=err_msg,
            )
            run.add_event("RUN_FAILED", reason=err_msg)
            self.service.save_company_run(run)
            raise EngineeringPreconditionError(err_msg)

        # Locate and verify Product and UX artifacts
        proj_id = run.project_id or run.objective.project_id or f"proj_{run.run_id}"
        if proj_id not in self.service.company.projects:
            self.service.create_project(proj_id, name=f"Project for {run.objective.title}")
        proj = self.service.get_project(proj_id)

        prod_task = None
        if prod_item.task_id:
            try:
                prod_task = self.service.get_task(prod_item.task_id)
            except Exception:
                prod_task = None

        ux_task = None
        if ux_item.task_id:
            try:
                ux_task = self.service.get_task(ux_item.task_id)
            except Exception:
                ux_task = None

        prod_art = None
        if prod_task:
            for r in reversed(prod_task.runs):
                for a in r.artifacts:
                    if a.artifact_type in (ArtifactType.SPECIFICATION.value, ArtifactType.RESEARCH_REPORT.value):
                        prod_art = a
                        break
                if prod_art:
                    break

        ux_art = None
        if ux_task:
            for r in reversed(ux_task.runs):
                for a in r.artifacts:
                    if a.artifact_type in (ArtifactType.UX_SPECIFICATION.value, ArtifactType.SPECIFICATION.value):
                        ux_art = a
                        break
                if ux_art:
                    break

        if not prod_art or not ux_art:
            err_msg = "Could not locate verified Product and UX artifacts for Developer execution."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            run.add_event("WORK_ITEM_FAILED", work_item_id=target_item.work_item_id, role=role, reason=err_msg)
            run.add_event("RUN_FAILED", reason=err_msg)
            self.service.save_company_run(run)
            raise ArtifactVerificationError(err_msg)

        # Verify physical files and SHA-256 on disk
        for art_name, art in (("Product", prod_art), ("UX", ux_art)):
            art_path = _resolve_artifact_file_path(self.service.output_dir, art)
            if not art_path.is_file():
                err_msg = f"{art_name} artifact file '{art.path}' does not exist on disk."
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                self.service.save_company_run(run)
                raise ArtifactVerificationError(err_msg)

            actual_sha = hashlib.sha256(art_path.read_bytes()).hexdigest()
            if actual_sha != art.sha256:
                err_msg = f"{art_name} artifact checksum mismatch: expected {art.sha256}, got {actual_sha}."
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                self.service.save_company_run(run)
                raise ArtifactVerificationError(err_msg)

        # Resolve target repository root
        target_repo = Path(run.objective.target_repository).resolve() if run.objective.target_repository else self.service.repo_root
        if not (target_repo / ".git").exists():
            err_msg = f"Target repository '{target_repo}' is not a valid Git repository."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            self.service.save_company_run(run)
            raise TargetRepositoryInvalidError(err_msg)

        # Enforce Target Repository Identity Guard
        if run.project_id:
            repo_proj = self.service.project_registry.get_project(run.project_id)
            if repo_proj:
                try:
                    verify_target_repository_identity(
                        project=repo_proj,
                        candidate_repo_path=target_repo,
                        expected_head=run.base_commit_hash,
                        expected_branch=run.target_branch,
                    )
                except Exception as exc:
                    err_msg = f"Target repository identity verification failed: {exc}"
                    target_item.state = WorkItemState.FAILED.value
                    run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                    run.transition_to(CompanyRunState.FAILED, error=err_msg)
                    self.service.save_company_run(run)
                    raise TargetRepositoryInvalidError(err_msg) from exc

        # Mark work item RUNNING
        target_item.state = WorkItemState.RUNNING.value
        run.work_item_states[target_item.work_item_id] = WorkItemState.RUNNING.value
        run.add_event(
            event_type="DEVELOPER_PIPELINE_STARTED",
            work_item_id=target_item.work_item_id,
            role=role,
            reason=f"Started engineering pipeline for {target_item.work_item_id}",
        )
        self.service.save_company_run(run)

        # ----------------------------------------------------------------------
        # 2. Developer Planning Phase (STEP 13A)
        # ----------------------------------------------------------------------
        plan_task_id = f"task_{run.run_id}_{target_item.work_item_id}_plan"
        plan_task = None
        plan_art = None

        # Crash / Resume check: verify if planning task already exists and verifies
        if plan_task_id in proj.tasks:
            existing_task = proj.tasks[plan_task_id]
            for r in reversed(existing_task.runs):
                for a in r.artifacts:
                    if a.artifact_type == ArtifactType.DEVELOPER_PLAN_REPORT.value:
                        plan_art_path = _resolve_artifact_file_path(self.service.output_dir, a)
                        if plan_art_path.is_file():
                            curr_sha = hashlib.sha256(plan_art_path.read_bytes()).hexdigest()
                            if curr_sha == a.sha256:
                                plan_task = existing_task
                                plan_art = a
                                break
                            else:
                                err_msg = f"Developer plan artifact checksum mismatch on resume: {a.path}"
                                target_item.state = WorkItemState.FAILED.value
                                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                                self.service.save_company_run(run)
                                raise ArtifactVerificationError(err_msg)
                if plan_art:
                    break

        if not plan_art:
            plan_task = self.service.create_task(
                project_id=proj.id,
                task_id=plan_task_id,
                title=f"[DEVELOPER PLAN] {target_item.objective[:60]}",
                goal=target_item.objective,
                constraints=list(run.objective.constraints),
                required_roles=["developer"],
                expected_output=list(target_item.expected_outputs),
            )
            # Attach verified Product and UX artifacts
            self.service.attach_input_artifact(plan_task.id, prod_art.id, project_id=proj.id)
            self.service.attach_input_artifact(plan_task.id, ux_art.id, project_id=proj.id)

            plan_run = self.service.execute_developer_planning_task(plan_task.id, project_id=proj.id)
            if plan_run.status != RunStatus.SUCCESS.value:
                err_msg = f"Developer planning failed: {plan_run.error}"
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                run.add_event("WORK_ITEM_FAILED", work_item_id=target_item.work_item_id, role=role, reason=err_msg)
                self.service.save_company_run(run)
                raise EngineeringPipelineError(err_msg)

            for a in plan_run.artifacts:
                if a.artifact_type == ArtifactType.DEVELOPER_PLAN_REPORT.value:
                    plan_art = a
                    break

        if not plan_art:
            err_msg = "Developer planning completed but produced no DEVELOPER_PLAN_REPORT artifact."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            self.service.save_company_run(run)
            raise ArtifactVerificationError(err_msg)

        run.add_event(
            event_type="DEVELOPER_PLAN_VERIFIED",
            work_item_id=target_item.work_item_id,
            role=role,
            task_id=plan_task.id,
            artifact_refs=[{
                "artifact_id": plan_art.id,
                "name": plan_art.name,
                "sha256": plan_art.sha256,
            }],
            reason="Developer plan report verified",
        )
        self.service.save_company_run(run)

        # ----------------------------------------------------------------------
        # 3. ExecutionGrant Boundary (STEP 13B-1)
        # ----------------------------------------------------------------------
        plan_details = plan_task.result.details if plan_task.result else {}
        raw_mod = [f["path"] for f in plan_details.get("files_to_modify", []) if isinstance(f, dict) and "path" in f]
        raw_create = [f["path"] for f in plan_details.get("files_to_create", []) if isinstance(f, dict) and "path" in f]

        files_to_modify = list(raw_mod)
        files_to_create = []
        for f in raw_create:
            if (target_repo / f).is_file():
                if f not in files_to_modify:
                    files_to_modify.append(f)
            else:
                files_to_create.append(f)
        raw_vas = plan_details.get("verification_actions", [])
        verification_actions: List[VerificationAction] = []
        for va in raw_vas:
            if isinstance(va, dict):
                verification_actions.append(
                    VerificationAction(
                        action_type=va.get("action_type", "pytest"),
                        target=va.get("target", ""),
                    )
                )

        # If plan specified no verification actions, prioritize test files in approved list, then inspect target repo
        if not verification_actions:
            for f in files_to_modify + files_to_create:
                if is_test_file(f):
                    verification_actions.append(VerificationAction("pytest", f))
                    break

        if not verification_actions:
            test_files = list(target_repo.rglob("test_*.py"))
            if test_files:
                rel_test = str(test_files[0].relative_to(target_repo)).replace("\\", "/")
                verification_actions.append(VerificationAction("pytest", rel_test))

        founder_approval_id = f"founder_grant_{run.run_id}"
        has_tests = any(is_test_file(f) for f in files_to_modify + files_to_create)
        total_files = len(files_to_modify) + len(files_to_create)
        grant = self.service.create_execution_grant(
            task_id=plan_task.id,
            plan_artifact_id=plan_art.id,
            founder_approval_id=founder_approval_id,
            approved_files_to_modify=files_to_modify,
            approved_files_to_create=files_to_create,
            verification_actions=verification_actions,
            allow_test_modifications=has_tests,
            max_files_changed=max(3, total_files),
            max_verification_actions=max(3, len(verification_actions)),
            max_duration_seconds=int(timeout) if timeout is not None else 600,
            repo_root=target_repo,
            project_id=proj.id,
        )

        run.add_event(
            event_type="EXECUTION_GRANT_ACCEPTED",
            work_item_id=target_item.work_item_id,
            role=role,
            task_id=plan_task.id,
            details={
                "grant_id": grant.grant_id,
                "base_commit_hash": grant.base_commit_hash,
                "approved_files_to_modify": list(grant.approved_files_to_modify),
                "approved_files_to_create": list(grant.approved_files_to_create),
            },
            reason="ExecutionGrant validated and bound to repository commit",
        )
        self.service.save_company_run(run)

        # ----------------------------------------------------------------------
        # 4. Isolated Worktree Developer Mutation (STEP 13B-2 & 13B-3)
        # ----------------------------------------------------------------------
        code_patch_art = None

        # Crash / Resume check: verify if a matching verified CODE_PATCH already exists
        for task_obj in proj.tasks.values():
            for r in reversed(task_obj.runs):
                for a in r.artifacts:
                    if a.artifact_type == ArtifactType.CODE_PATCH.value:
                        meta = a.metadata or {}
                        if meta.get("plan_artifact_id") == plan_art.id:
                            patch_path = _resolve_artifact_file_path(self.service.output_dir, a)
                            if patch_path.is_file():
                                curr_sha = hashlib.sha256(patch_path.read_bytes()).hexdigest()
                                if curr_sha == a.sha256:
                                    code_patch_art = a
                                    break
                                else:
                                    err_msg = f"CODE_PATCH disk SHA mismatch on resume: {a.path}"
                                    target_item.state = WorkItemState.FAILED.value
                                    run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                                    run.transition_to(CompanyRunState.FAILED, error=err_msg)
                                    self.service.save_company_run(run)
                                    raise ArtifactVerificationError(err_msg)
                if code_patch_art:
                    break
            if code_patch_art:
                break

        if not code_patch_art:
            mutation_outcome = self.service.execute_bounded_developer_mutation(
                grant=grant,
                instruction=target_item.objective,
                timeout=timeout,
                repo_root=target_repo,
            )
            if mutation_outcome.status != DeveloperMutationStatus.SUCCESS.value or not mutation_outcome.patch_artifact:
                err_msg = f"Developer mutation failed: {mutation_outcome.summary} ({mutation_outcome.error})"
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                run.add_event("WORK_ITEM_FAILED", work_item_id=target_item.work_item_id, role=role, reason=err_msg)
                self.service.save_company_run(run)
                raise EngineeringPipelineError(err_msg)

            code_patch_art = mutation_outcome.patch_artifact

        # Verify CODE_PATCH artifact on disk
        patch_file_path = _resolve_artifact_file_path(self.service.output_dir, code_patch_art)
        if not patch_file_path.is_file():
            err_msg = f"CODE_PATCH file '{code_patch_art.path}' does not exist on disk."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            self.service.save_company_run(run)
            raise ArtifactVerificationError(err_msg)

        actual_patch_sha = hashlib.sha256(patch_file_path.read_bytes()).hexdigest()
        if actual_patch_sha != code_patch_art.sha256:
            err_msg = f"CODE_PATCH checksum mismatch: expected {code_patch_art.sha256}, got {actual_patch_sha}."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            self.service.save_company_run(run)
            raise ArtifactVerificationError(err_msg)

        run.add_event(
            event_type="MUTATION_COMPLETED",
            work_item_id=target_item.work_item_id,
            role=role,
            task_id=plan_task.id,
            reason="Bounded Developer mutation completed inside isolated worktree",
        )
        run.add_event(
            event_type="CODE_PATCH_VERIFIED",
            work_item_id=target_item.work_item_id,
            role=role,
            task_id=plan_task.id,
            artifact_refs=[{
                "artifact_id": code_patch_art.id,
                "name": code_patch_art.name,
                "sha256": code_patch_art.sha256,
            }],
            reason="CODE_PATCH verified and registered",
        )
        self.service.save_company_run(run)

        # ----------------------------------------------------------------------
        # 5. Application-Owned QA Inspection & Verification (STEP 14A & 14B)
        # ----------------------------------------------------------------------
        run.add_event(
            event_type="QA_STARTED",
            work_item_id=target_item.work_item_id,
            role="qa",
            task_id=plan_task.id,
            reason="Application-owned QA inspection and verification started",
        )
        self.service.save_company_run(run)

        # 5a. QA Inspection (STEP 14A)
        qa_inspect_task_id = f"{plan_task.id}_qa_inspect"
        qa_report_art = None

        if qa_inspect_task_id in proj.tasks:
            inspect_task = proj.tasks[qa_inspect_task_id]
            for r in reversed(inspect_task.runs):
                for a in r.artifacts:
                    if a.artifact_type == ArtifactType.QA_REPORT.value:
                        qa_rep_path = _resolve_artifact_file_path(self.service.output_dir, a)
                        if qa_rep_path.is_file():
                            if hashlib.sha256(qa_rep_path.read_bytes()).hexdigest() == a.sha256:
                                qa_report_art = a
                                break
                if qa_report_art:
                    break

        if not qa_report_art:
            qa_inspect_task = self.service.create_task(
                project_id=proj.id,
                task_id=qa_inspect_task_id,
                title=f"QA Inspection for {plan_task.id}",
                goal=f"Inspect CODE_PATCH {code_patch_art.id} against requirements",
                required_roles=["qa"],
            )
            self.service.attach_input_artifact(qa_inspect_task.id, prod_art.id, project_id=proj.id)
            self.service.attach_input_artifact(qa_inspect_task.id, ux_art.id, project_id=proj.id)
            self.service.attach_input_artifact(qa_inspect_task.id, plan_art.id, project_id=proj.id)
            self.service.attach_input_artifact(qa_inspect_task.id, code_patch_art.id, project_id=proj.id)

            qa_inspect_run = self.service.execute_qa_inspection_task(
                qa_inspect_task.id,
                project_id=proj.id,
                code_patch_artifact_id=code_patch_art.id,
                timeout=timeout,
            )
            if qa_inspect_run.status != RunStatus.SUCCESS.value:
                err_msg = f"QA inspection task failed: {qa_inspect_run.error}"
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                self.service.save_company_run(run)
                raise EngineeringPipelineError(err_msg)

            for a in qa_inspect_run.artifacts:
                if a.artifact_type == ArtifactType.QA_REPORT.value:
                    qa_report_art = a
                    break

        if not qa_report_art:
            err_msg = "QA inspection completed but produced no QA_REPORT artifact."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            self.service.save_company_run(run)
            raise ArtifactVerificationError(err_msg)

        # 5b. QA Verification Execution in fresh disposable worktree (STEP 14B)
        qa_verify_task_id = f"{plan_task.id}_qa_verify"
        qa_exec_art = None
        qa_verify_run = None

        if qa_verify_task_id in proj.tasks:
            verify_task = proj.tasks[qa_verify_task_id]
            for r in reversed(verify_task.runs):
                for a in r.artifacts:
                    if a.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value:
                        qa_exec_path = _resolve_artifact_file_path(self.service.output_dir, a)
                        if qa_exec_path.is_file():
                            if hashlib.sha256(qa_exec_path.read_bytes()).hexdigest() == a.sha256:
                                qa_exec_art = a
                                qa_verify_run = r
                                break
                if qa_exec_art:
                    break

        if not qa_exec_art:
            qa_verify_task = self.service.create_task(
                project_id=proj.id,
                task_id=qa_verify_task_id,
                title=f"QA Verification for {plan_task.id}",
                goal=f"Verify CODE_PATCH {code_patch_art.id} in fresh isolated worktree",
                required_roles=["qa"],
            )
            self.service.attach_input_artifact(qa_verify_task.id, prod_art.id, project_id=proj.id)
            self.service.attach_input_artifact(qa_verify_task.id, ux_art.id, project_id=proj.id)
            self.service.attach_input_artifact(qa_verify_task.id, plan_art.id, project_id=proj.id)
            self.service.attach_input_artifact(qa_verify_task.id, code_patch_art.id, project_id=proj.id)
            self.service.attach_input_artifact(qa_verify_task.id, qa_report_art.id, project_id=proj.id)

            qa_verify_run = self.service.execute_qa_verification_task(
                task_id=qa_verify_task.id,
                project_id=proj.id,
                code_patch_artifact_id=code_patch_art.id,
                qa_report_artifact_id=qa_report_art.id,
                timeout=timeout,
                target_repo_root=target_repo,
            )
            if qa_verify_run.status != RunStatus.SUCCESS.value:
                err_msg = f"QA verification task failed: {qa_verify_run.error}"
                target_item.state = WorkItemState.FAILED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                run.transition_to(CompanyRunState.FAILED, error=err_msg)
                self.service.save_company_run(run)
                raise EngineeringPipelineError(err_msg)

            for a in qa_verify_run.artifacts:
                if a.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value:
                    qa_exec_art = a
                    break

        if not qa_exec_art:
            err_msg = "QA verification completed but produced no QA_EXECUTION_REPORT artifact."
            target_item.state = WorkItemState.FAILED.value
            run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
            run.transition_to(CompanyRunState.FAILED, error=err_msg)
            self.service.save_company_run(run)
            raise ArtifactVerificationError(err_msg)

        qa_verdict = qa_exec_art.metadata.get("verdict", "FAIL")

        # ----------------------------------------------------------------------
        # 6. Verdict Evaluation & Bounded Repair (STEP 15)
        # ----------------------------------------------------------------------
        if qa_verdict != "PASS":
            run.add_event(
                event_type="QA_FAILED",
                work_item_id=target_item.work_item_id,
                role="qa",
                task_id=plan_task.id,
                details={"verdict": qa_verdict},
                reason="QA verification failed; initiating bounded repair loop",
            )
            run.add_event(
                event_type="REPAIR_STARTED",
                work_item_id=target_item.work_item_id,
                role="developer",
                task_id=plan_task.id,
                reason=f"Developer <-> QA repair loop started (max iterations: {MAX_REPAIR_ITERATIONS})",
            )
            self.service.save_company_run(run)

            repair_approvals = {
                1: f"founder_repair_1_{run.run_id}",
                2: f"founder_repair_2_{run.run_id}",
            }
            repair_res = self.service.execute_developer_qa_repair_loop(
                task_id=plan_task.id,
                project_id=proj.id,
                founder_approvals=repair_approvals,
                original_grant=grant,
                max_repair_iterations=MAX_REPAIR_ITERATIONS,
                allow_test_modifications=grant.allow_test_modifications,
                target_repo_root=target_repo,
                timeout=timeout,
            )

            if repair_res.status == RepairWorkflowStatus.QA_PASSED.value:
                run.add_event(
                    event_type="REPAIR_COMPLETED",
                    work_item_id=target_item.work_item_id,
                    role="developer",
                    task_id=plan_task.id,
                    details={"iterations_used": repair_res.repair_iterations_used},
                    reason=f"Repaired CODE_PATCH passed QA verification on iteration {repair_res.repair_iterations_used}",
                )
                run.add_event(
                    event_type="QA_PASSED",
                    work_item_id=target_item.work_item_id,
                    role="qa",
                    task_id=plan_task.id,
                    details={"final_code_patch_artifact_id": repair_res.final_code_patch_artifact_id},
                    reason="QA verification PASSED after repair",
                )
                # Resolve final repaired artifacts
                patch_lineage = self.service.find_artifact(repair_res.final_code_patch_artifact_id)
                qa_exec_lineage = self.service.find_artifact(repair_res.final_qa_execution_report_artifact_id)
                if patch_lineage and qa_exec_lineage:
                    code_patch_art = patch_lineage[2]
                    qa_exec_art = qa_exec_lineage[2]
                    qa_verdict = "PASS"
                else:
                    err_msg = "Repaired artifacts could not be resolved from company service state."
                    target_item.state = WorkItemState.FAILED.value
                    run.work_item_states[target_item.work_item_id] = WorkItemState.FAILED.value
                    run.transition_to(CompanyRunState.FAILED, error=err_msg)
                    self.service.save_company_run(run)
                    raise ArtifactVerificationError(err_msg)
            else:
                err_msg = f"Developer-QA repair loop exhausted or terminated with status '{repair_res.status}': {repair_res.termination_reason}"
                run.add_event(
                    event_type="REPAIR_FAILED",
                    work_item_id=target_item.work_item_id,
                    role="developer",
                    task_id=plan_task.id,
                    details={"status": repair_res.status, "reason": repair_res.termination_reason},
                    reason=err_msg,
                )
                target_item.state = WorkItemState.BLOCKED.value
                run.work_item_states[target_item.work_item_id] = WorkItemState.BLOCKED.value
                run.transition_to(CompanyRunState.BLOCKED, error=err_msg)
                run.add_event("RUN_BLOCKED", reason=err_msg)
                self.service.save_company_run(run)
                raise EngineeringPipelineError(f"Repair loop exhausted without passing QA: {repair_res.termination_reason}")
        else:
            run.add_event(
                event_type="QA_PASSED",
                work_item_id=target_item.work_item_id,
                role="qa",
                task_id=plan_task.id,
                reason="QA verification PASSED on attempt 0",
            )
            self.service.save_company_run(run)

        # ----------------------------------------------------------------------
        # 7. RealRepoApplyProposal Preparation & READY_FOR_HUMAN_APPLY Boundary
        # ----------------------------------------------------------------------
        proposal = self.service.prepare_real_repo_apply(
            code_patch_artifact_id=code_patch_art.id,
            qa_execution_report_artifact_id=qa_exec_art.id,
            target_repo_root=target_repo,
            project_id=proj.id,
            company_run_id=run.run_id,
        )

        run.real_repo_apply_proposal_id = proposal.proposal_id
        run.code_patch_artifact_id = code_patch_art.id
        run.qa_execution_report_artifact_id = qa_exec_art.id

        # Mark work item COMPLETED (engineering preparation complete)
        target_item.task_id = plan_task.id
        target_item.run_id = plan_task.runs[-1].id if plan_task.runs else ""
        target_item.state = WorkItemState.COMPLETED.value
        run.work_item_states[target_item.work_item_id] = WorkItemState.COMPLETED.value
        run.specialist_invocation_count += 1

        # Append bounded summaries
        dev_run_id = target_item.run_id or (plan_task.runs[-1].id if plan_task.runs else f"run_{plan_task.id}")
        dev_summary = EmployeeResultSummary(
            role="developer",
            task_id=plan_task.id,
            run_id=dev_run_id,
            status="COMPLETED",
            artifact_refs=[{
                "artifact_id": code_patch_art.id,
                "name": code_patch_art.name,
                "type": code_patch_art.artifact_type,
                "sha256": code_patch_art.sha256,
                "path": code_patch_art.path,
            }],
            summary=f"Developer produced verified CODE_PATCH {code_patch_art.id} matching requirements.",
        )
        run.employee_summaries.append(dev_summary)

        qa_run_id = qa_verify_run.id if (qa_verify_run and getattr(qa_verify_run, "id", None)) else f"run_{qa_verify_task_id}"
        qa_summary = EmployeeResultSummary(
            role="qa",
            task_id=qa_verify_task_id,
            run_id=qa_run_id,
            status="COMPLETED",
            artifact_refs=[{
                "artifact_id": qa_exec_art.id,
                "name": qa_exec_art.name,
                "type": qa_exec_art.artifact_type,
                "sha256": qa_exec_art.sha256,
                "path": qa_exec_art.path,
            }],
            summary=f"QA verified CODE_PATCH with verdict PASS and produced QA_EXECUTION_REPORT {qa_exec_art.id}.",
        )
        run.employee_summaries.append(qa_summary)

        # Transition CompanyRun to READY_FOR_HUMAN_APPLY
        run.transition_to(CompanyRunState.READY_FOR_HUMAN_APPLY, is_code_workflow=True)
        run.add_event(
            event_type="READY_FOR_HUMAN_APPLY",
            work_item_id=target_item.work_item_id,
            role="developer",
            task_id=plan_task.id,
            details={
                "proposal_id": proposal.proposal_id,
                "code_patch_artifact_id": code_patch_art.id,
                "target_repository": str(target_repo),
            },
            reason="Engineering pipeline complete with QA PASS; waiting for explicit human founder approval",
        )
        self.service.save_company_run(run)
        return run

    def approve_repo_apply(
        self,
        run: CompanyRun,
        founder_approval_id: str,
        approver: str = "Human Founder",
    ) -> RealRepoApplyGrant:
        """Explicitly approve an existing RealRepoApplyProposal by Human Founder.

        Enforces:
        1. Run must be in READY_FOR_HUMAN_APPLY state.
        2. Explicit founder_approval_id mandatory.
        3. Proposal exists on run and matches registered proposal.
        4. Matching CODE_PATCH and QA_EXECUTION_REPORT artifacts.
        5. Issues single-use RealRepoApplyGrant.
        6. Auditable event logged.
        """
        if run.state != CompanyRunState.READY_FOR_HUMAN_APPLY.value:
            raise TransitionPolicyError(
                f"Cannot approve repository apply: CompanyRun '{run.run_id}' state is '{run.state}', "
                f"expected '{CompanyRunState.READY_FOR_HUMAN_APPLY.value}'."
            )

        if not founder_approval_id or not str(founder_approval_id).strip():
            raise MissingApprovalError("Cannot approve repository apply: explicit founder_approval_id is mandatory.")

        if not run.real_repo_apply_proposal_id:
            raise ProposalMismatchError(f"CompanyRun '{run.run_id}' has no recorded real_repo_apply_proposal_id.")

        proposal = self.service.get_real_repo_apply_proposal(run.real_repo_apply_proposal_id)
        if not proposal:
            raise ProposalMismatchError(f"Proposal '{run.real_repo_apply_proposal_id}' not found in registered proposals.")

        # Cross-run proposal provenance validation
        try:
            prov = self.service.durable_storage.load_provenance(proposal.proposal_id)
            if prov and prov.get("company_run_id") and prov.get("company_run_id") != run.run_id:
                raise ProposalMismatchError(
                    f"Proposal '{proposal.proposal_id}' provenance belongs to CompanyRun '{prov.get('company_run_id')}', "
                    f"cannot be approved under CompanyRun '{run.run_id}'."
                )
        except ProposalNotFoundError:
            pass

        if proposal.code_patch_artifact_id != run.code_patch_artifact_id:
            raise ProposalMismatchError(
                f"Proposal code_patch_id '{proposal.code_patch_artifact_id}' does not match run '{run.code_patch_artifact_id}'."
            )

        # Verify CODE_PATCH artifact integrity on disk
        if not run.code_patch_artifact_id:
            raise ArtifactVerificationError(f"CompanyRun '{run.run_id}' has no recorded code_patch_artifact_id.")

        expected_sha = proposal.code_patch_sha256
        patch_lineage = self.service.find_artifact(run.code_patch_artifact_id)
        patch_path = None

        if patch_lineage:
            _, _, patch_art = patch_lineage
            if patch_art.sha256 and patch_art.sha256 != expected_sha:
                raise ArtifactVerificationError(
                    f"CODE_PATCH artifact SHA-256 '{patch_art.sha256}' does not match proposal '{expected_sha}'."
                )
            try:
                candidate_path = _resolve_artifact_file_path(self.service.output_dir, patch_art)
                if candidate_path.is_file():
                    patch_path = candidate_path
            except Exception:
                patch_path = None

        # Fallback to durable proposal patch if original task path unresolvable
        if not patch_path or not patch_path.is_file():
            durable_patch = self.service.durable_storage.proposals_dir / proposal.proposal_id / "patch.diff"
            if durable_patch.is_file():
                patch_path = durable_patch
            else:
                raise ArtifactVerificationError(f"CODE_PATCH artifact '{run.code_patch_artifact_id}' not found.")

        if not patch_path.is_file():
            raise ArtifactVerificationError(f"CODE_PATCH artifact file not found: {patch_path}")

        actual_sha = hashlib.sha256(patch_path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise ArtifactVerificationError(
                f"CODE_PATCH disk checksum mismatch: computed '{actual_sha}' != proposal '{expected_sha}'."
            )

        grant = self.service.approve_real_repo_apply(
            proposal_id=proposal.proposal_id,
            founder_approval_id=founder_approval_id,
            approver=approver,
        )

        run.real_repo_apply_grant_id = grant.grant_id
        run.add_event(
            event_type="HUMAN_APPLY_APPROVED",
            details={
                "grant_id": grant.grant_id,
                "proposal_id": proposal.proposal_id,
                "approver": approver,
                "founder_approval_id": founder_approval_id,
            },
            reason="Real repository apply grant explicitly approved by Human Founder",
        )
        self.service.save_company_run(run)
        return grant

    def apply_repo(self, run: CompanyRun) -> RealRepoApplyResult:
        """Execute transactional application of approved CODE_PATCH to real repository.

        Enforces:
        1. Run must be in READY_FOR_HUMAN_APPLY with an issued RealRepoApplyGrant.
        2. State transition: READY_FOR_HUMAN_APPLY -> APPLYING.
        3. Transactional apply via existing execute_real_repo_apply engine.
        4. State transition: APPLYING -> COMPLETED on success (or FAILED on error/rollback).
        5. Auditable events logged.
        """
        if run.state != CompanyRunState.READY_FOR_HUMAN_APPLY.value:
            raise TransitionPolicyError(
                f"Cannot execute repository apply: CompanyRun '{run.run_id}' state is '{run.state}', "
                f"expected '{CompanyRunState.READY_FOR_HUMAN_APPLY.value}'."
            )

        if not run.real_repo_apply_grant_id:
            raise ApprovalInvalidError(f"CompanyRun '{run.run_id}' has no real_repo_apply_grant_id. Human approval required.")

        grant = self.service.get_real_repo_apply_grant(run.real_repo_apply_grant_id)
        if not grant:
            raise ApprovalInvalidError(f"Grant '{run.real_repo_apply_grant_id}' not found in registered grants.")

        if grant.proposal_id != run.real_repo_apply_proposal_id:
            raise ApprovalInvalidError(
                f"Grant proposal '{grant.proposal_id}' does not match run proposal '{run.real_repo_apply_proposal_id}'."
            )

        # Transition to APPLYING
        run.transition_to(CompanyRunState.APPLYING, is_code_workflow=True)
        run.add_event(
            event_type="REAL_REPO_APPLY_STARTED",
            details={"grant_id": grant.grant_id},
            reason="Started transactional real repository apply",
        )
        self.service.save_company_run(run)

        try:
            apply_result = self.service.execute_real_repo_apply(grant_id=grant.grant_id)
        except Exception as exc:
            run.transition_to(CompanyRunState.FAILED, error=str(exc), is_code_workflow=True)
            run.add_event(
                event_type="REAL_REPO_APPLY_FAILED",
                details={"error": str(exc)},
                reason=f"Real repository apply failed with exception: {exc}",
            )
            self.service.save_company_run(run)
            raise

        if apply_result.status == RealRepoApplyStatus.APPLIED_SUCCESSFULLY.value:
            run.real_repo_apply_result = apply_result.to_dict()
            run.transition_to(CompanyRunState.COMPLETED, is_code_workflow=True)
            run.add_event(
                event_type="REAL_REPO_APPLY_COMPLETED",
                details={
                    "applied_files": list(apply_result.actual_files),
                    "post_apply_head": apply_result.post_apply_head,
                },
                reason="Real repository apply completed successfully and verified",
            )
            run.add_event(
                event_type="RUN_COMPLETED",
                reason="Engineering code workflow successfully verified, approved, and applied to repository",
            )
            self.service.save_company_run(run)
            return apply_result
        else:
            err_msg = apply_result.error or f"Real repository apply terminated with status '{apply_result.status}'."
            run.real_repo_apply_result = apply_result.to_dict()
            run.transition_to(CompanyRunState.FAILED, error=err_msg, is_code_workflow=True)
            run.add_event(
                event_type="REAL_REPO_APPLY_FAILED",
                details={"status": apply_result.status, "error": err_msg},
                reason=err_msg,
            )
            self.service.save_company_run(run)
            return apply_result
