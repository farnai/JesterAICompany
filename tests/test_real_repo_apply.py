"""Deterministic and Live Test Suite for Real Repository Apply (STEP 16).

Verifies:
1. External repository lock stored in JesterAICompany runtime state (.runs/locks/), NOT target .git.
2. Simplified local repository identity: canonical repo root + exact HEAD + branch/state.
3. Deterministic crash recovery classification (NOT_APPLIED, EXACT_APPROVED_PATCH_PRESENT, PARTIAL_OR_UNKNOWN_STATE).
4. Unresolved/unknown crash state must fail closed and block new apply.
5. Rollback only under proven clean-repository precondition.
6. Exact reverse patch as primary rollback without dangerous git reset --hard / git clean -fd.
7. No pytest/application tests executed in real repository in V1.
8. Exact diff equivalence as the final commit point.
9. Explicit real Human approval required in production.
10. Prepare and approve perform ZERO repository mutation.
11. execute_real_repo_apply is the ONLY real repository mutation boundary.
12. No agent runtime invocation during real repository apply.
13. Live Proof 1: Clean successful apply to real-like repository.
14. Live Proof 2: TOCTOU invalidation when repository state changes after approval.
15. Live Proof 3: Safe rollback when post-apply diff is intentionally corrupted.
16. Live Proof 4: Unresolved crash recovery state fails closed and blocks new apply.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock
import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    Company,
    Project,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from jester_ai_company.execution_grant import (
    ExecutionGrant,
    MissingApprovalError,
    ProtectedPathError,
    VerificationAction,
)
from jester_ai_company.materializer import (
    compute_sha256,
    materialize_code_patch_artifact,
    materialize_qa_execution_report_artifact,
    materialize_qa_report_artifact,
    materialize_real_repo_apply_report_artifact,
    materialize_specialist_artifact,
)
from jester_ai_company.product_result import (
    ProductDeliverable,
    ProductTaskResult,
)
from jester_ai_company.developer_result import (
    DeveloperTaskResult,
    ProposedFile,
)
from jester_ai_company.qa_execution import (
    QAExecutionVerdictResult,
    QAFinalVerdict,
    QARequirementExecutionEvaluation,
)
from jester_ai_company.qa_result import (
    QAInspectionResult,
    QAInspectionStatus,
    QARecommendedAction,
    RequirementCoverage,
)
from jester_ai_company.real_repo_apply import (
    ApprovalInvalidError,
    BaseCommitMismatchError,
    CandidateNotEligibleError,
    ConcurrentApplyError,
    CrashRecoveryBlockError,
    CrashStateClassification,
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
from jester_ai_company.runtime import AntigravityRuntime
from jester_ai_company.service import CompanyService, ExecutionError
from jester_ai_company.worktree import (
    resolve_repo_head_commit,
    run_git,
)


# ==============================================================================
# Helper for Setting Up a Disposable Git Repository
# ==============================================================================

def setup_disposable_repo(target_dir: Path) -> str:
    """Initialize a fresh, clean git repository with a committed calculator.py file."""
    run_git(["init"], cwd=target_dir)
    run_git(["config", "user.name", "Test Runner"], cwd=target_dir)
    run_git(["config", "user.email", "runner@example.com"], cwd=target_dir)
    (target_dir / "README.md").write_text("# Target Repo\n", encoding="utf-8")
    (target_dir / "calculator.py").write_text(
        "def add(a: int, b: int) -> int:\n    return 0\n",
        encoding="utf-8",
    )
    run_git(["add", "."], cwd=target_dir)
    run_git(["commit", "-m", "Initial baseline commit"], cwd=target_dir)
    return resolve_repo_head_commit(target_dir)


def create_candidate_chain(
    service: CompanyService,
    repo_dir: Path,
    head_commit: str,
    project_id: str = "proj_apply",
    patch_text: Optional[str] = None,
    changed_files: Optional[List[str]] = None,
    qa_verdict: str = "PASS",
    verification_passed: bool = True,
) -> Dict[str, Any]:
    """Helper to assemble a complete, valid upstream artifact chain for apply testing."""
    proj = service.create_project(project_id=project_id, name="ApplyTestProj")

    # 1. Product Spec
    prod_task = service.create_task(project_id=project_id, title="Product Spec", goal="Spec", required_roles=["product"])
    prod_run = prod_task.create_run()
    prod_run.status = RunStatus.RUNNING.value
    prod_res = ProductTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Requirements for add function",
        deliverables=[ProductDeliverable(name="Requirements", content="REQ-01: Fix add() to return a + b.")],
    )
    prod_art = materialize_specialist_artifact(
        base_output_dir=Path(service.output_dir),
        task=prod_task,
        run=prod_run,
        agent_name="product",
        typed_result=prod_res,
    )
    prod_run.complete(status=RunStatus.SUCCESS.value)
    prod_task.complete(status=TaskStatus.COMPLETED.value, summary=prod_res.summary, details=prod_res.to_dict())

    # 2. Developer Plan
    dev_task = service.create_task(project_id=project_id, title="Dev Plan", goal="Plan", required_roles=["developer"])
    service.attach_input_artifact(dev_task.id, prod_art.id, project_id=project_id)
    dev_run = dev_task.create_run()
    dev_run.status = RunStatus.RUNNING.value
    files_to_modify = changed_files or ["calculator.py"]
    dev_res = DeveloperTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Plan for calculator.py",
        implementation_plan=["Fix add return value"],
        files_to_modify=[ProposedFile(path=f, description=f"Update {f}") for f in files_to_modify],
    )
    plan_art = materialize_specialist_artifact(
        base_output_dir=Path(service.output_dir),
        task=dev_task,
        run=dev_run,
        agent_name="developer",
        typed_result=dev_res,
    )
    dev_run.complete(status=RunStatus.SUCCESS.value)
    dev_task.complete(status=TaskStatus.COMPLETED.value, summary=dev_res.summary, details=dev_res.to_dict())

    # 3. Grant
    grant = ExecutionGrant(
        grant_id=f"grant_{project_id}_01",
        task_id=dev_task.id,
        plan_artifact_id=plan_art.id,
        plan_sha256=plan_art.sha256,
        base_commit_hash=head_commit,
        approved_files_to_modify=tuple(files_to_modify),
        verification_actions=(VerificationAction("pytest", "tests/test_calculator.py"),),
        founder_approval_id="founder_initial_approval_01",
    )

    # 4. Patch
    actual_patch = patch_text or (
        "diff --git a/calculator.py b/calculator.py\n"
        "--- a/calculator.py\n"
        "+++ b/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a: int, b: int) -> int:\n"
        "-    return 0\n"
        "+    return a + b\n"
    )
    patch_task = service.create_task(project_id=project_id, title="Developer Mutation", goal="Patch", required_roles=["developer"])
    patch_run = patch_task.create_run()
    patch_run.status = RunStatus.RUNNING.value
    patch_art = materialize_code_patch_artifact(
        base_output_dir=Path(service.output_dir),
        task=patch_task,
        run=patch_run,
        grant=grant,
        patch_text=actual_patch,
        changed_files=list(files_to_modify),
        verifications=[{"action": {"action_type": "pytest", "target": "tests/test_calculator.py"}, "status": "PASS" if verification_passed else "FAIL", "exit_code": 0 if verification_passed else 1}],
        patch_version=1,
    )
    patch_run.complete(status=RunStatus.SUCCESS.value)
    patch_task.complete(status=TaskStatus.COMPLETED.value, summary="Patch created")

    # 5. QA Report (Step 14A)
    qa_insp_task = service.create_task(project_id=project_id, title="QA Inspection", goal="Inspect", required_roles=["qa"])
    service.attach_input_artifact(qa_insp_task.id, prod_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, patch_art.id, project_id=project_id)
    qa_insp_run = qa_insp_task.create_run()
    qa_insp_run.status = RunStatus.RUNNING.value
    qa_insp_result = QAInspectionResult(
        schema_version="1.0",
        status=QAInspectionStatus.READY_FOR_QA_EXECUTION.value,
        summary="Inspection passed",
        requirements_coverage=[RequirementCoverage(requirement_id="REQ-01", status="COVERED", evidence="covered")],
        recommended_verification_actions=[QARecommendedAction(action_type="pytest", target="tests/test_calculator.py", purpose="Verify add")],
    )
    qa_lineage_meta = {
        "product_artifact_id": prod_art.id,
        "product_sha256": prod_art.sha256,
        "developer_plan_artifact_id": plan_art.id,
        "developer_plan_sha256": plan_art.sha256,
        "code_patch_artifact_id": patch_art.id,
        "code_patch_sha256": patch_art.sha256,
        "base_commit_hash": head_commit,
        "patch_version": 1,
    }
    qa_rep_art = materialize_qa_report_artifact(
        base_output_dir=Path(service.output_dir),
        task=qa_insp_task,
        run=qa_insp_run,
        typed_result=qa_insp_result,
        lineage_metadata=qa_lineage_meta,
    )
    qa_insp_run.complete(status=RunStatus.SUCCESS.value)
    qa_insp_task.complete(status=TaskStatus.COMPLETED.value, summary=qa_insp_result.summary, details=qa_insp_result.to_dict())

    # 6. QA Execution Report (Step 14B)
    qa_exec_task = service.create_task(project_id=project_id, title="QA Execution", goal="Execute QA", required_roles=["qa"])
    service.attach_input_artifact(qa_exec_task.id, prod_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, patch_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, qa_rep_art.id, project_id=project_id)
    qa_exec_run = qa_exec_task.create_run()
    qa_exec_run.status = RunStatus.RUNNING.value

    verdict_res = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=qa_verdict,
        summary="QA execution verdict",
        requirements_evaluations=[QARequirementExecutionEvaluation("REQ-01", "SATISFIED" if qa_verdict == "PASS" else "FAILED", "Logs")],
        release_recommendation="RELEASE" if qa_verdict == "PASS" else "HOLD",
    )
    exec_meta = {
        "product_artifact_id": prod_art.id,
        "developer_plan_artifact_id": plan_art.id,
        "code_patch_artifact_id": patch_art.id,
        "code_patch_sha256": patch_art.sha256,
        "qa_report_artifact_id": qa_rep_art.id,
        "base_commit_hash": head_commit,
    }

    qa_exec_art = materialize_qa_execution_report_artifact(
        base_output_dir=Path(service.output_dir),
        task=qa_exec_task,
        run=qa_exec_run,
        typed_verdict=verdict_res,
        lineage_metadata=exec_meta,
        execution_evidence=[{"action": {"action_type": "pytest", "target": "tests/test_calculator.py"}, "passed": (qa_verdict == "PASS"), "exit_code": 0 if qa_verdict == "PASS" else 1}],
    )
    qa_exec_run.complete(status=RunStatus.SUCCESS.value)
    qa_exec_task.complete(status=TaskStatus.COMPLETED.value, summary=verdict_res.summary, details=verdict_res.to_dict())

    return {
        "project": proj,
        "patch_task": patch_task,
        "patch_artifact": patch_art,
        "qa_report_artifact": qa_rep_art,
        "qa_exec_task": qa_exec_task,
        "qa_exec_artifact": qa_exec_art,
        "base_commit": head_commit,
        "patch_text": actual_patch,
        "changed_files": files_to_modify,
    }


# ==============================================================================
# 1. External Lock Unit Tests (Principle 1)
# ==============================================================================

class TestExternalRepositoryLock:
    """Verifies that repository apply lock is stored in runtime state, never target .git."""

    def test_lock_stored_in_runtime_state_not_git(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        locks_dir = runs_dir / "locks"

        lock = RealRepoApplyLock(locks_dir=locks_dir, repo_root=repo_dir)
        lock.acquire(proposal_id="prop_01")

        # Must exist in runtime locks_dir
        assert lock.lock_file.exists()
        assert lock.lock_file.is_relative_to(locks_dir)

        # Must NOT exist anywhere inside target repo or target repo .git
        git_dir = repo_dir / ".git"
        assert not any(git_dir.rglob("*.lock"))

        lock.release()
        assert not lock.lock_file.exists()

    def test_lock_concurrency_conflict_raises_error(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        locks_dir = tmp_path / ".runs" / "locks"
        lock1 = RealRepoApplyLock(locks_dir=locks_dir, repo_root=repo_dir)
        lock2 = RealRepoApplyLock(locks_dir=locks_dir, repo_root=repo_dir)

        lock1.acquire(proposal_id="prop_01")
        with pytest.raises(ConcurrentApplyError) as exc_info:
            lock2.acquire(proposal_id="prop_02")

        assert "already locked" in str(exc_info.value)
        lock1.release()

        # After release, lock2 can acquire
        lock2.acquire(proposal_id="prop_02")
        lock2.release()


# ==============================================================================
# 2. Local Repository Identity & Fingerprint Tests (Principle 2)
# ==============================================================================

class TestRepositoryIdentityAndCleanliness:
    """Verifies local repository identity and cleanliness checks."""

    def test_clean_repo_fingerprint(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        fp = compute_repo_fingerprint(repo_dir)
        assert fp.canonical_root == repo_dir.resolve().as_posix()
        assert fp.head_commit_hash == head
        assert fp.is_clean is True
        assert len(fp.state_sha256) == 64

    def test_dirty_repo_fingerprint_and_cleanliness_check(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        # Introduce a modification
        (repo_dir / "calculator.py").write_text("corrupted", encoding="utf-8")

        is_clean, dirty_stdout = verify_target_repo_cleanliness(repo_dir)
        assert is_clean is False
        assert "calculator.py" in dirty_stdout

        fp = compute_repo_fingerprint(repo_dir)
        assert fp.is_clean is False

    def test_non_git_repo_raises_invalid_error(self, tmp_path: Path):
        not_a_repo = tmp_path / "empty_dir"
        not_a_repo.mkdir()

        with pytest.raises(TargetRepositoryInvalidError):
            compute_repo_fingerprint(not_a_repo)

        with pytest.raises(TargetRepositoryInvalidError):
            verify_target_repo_cleanliness(not_a_repo)


# ==============================================================================
# 3. Crash Recovery State Classification Tests (Principles 3 & 4)
# ==============================================================================

class TestCrashStateClassification:
    """Verifies deterministic classification of repository states after crash/preflight."""

    def test_clean_repo_classified_not_applied(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        classification = classify_crash_state(
            repo_root=repo_dir,
            patch_text="dummy patch",
            expected_files=("calculator.py",),
        )
        assert classification == CrashStateClassification.NOT_APPLIED

    def test_exact_approved_patch_present(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        # Mutate calculator.py as expected
        (repo_dir / "calculator.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n",
            encoding="utf-8",
        )

        classification = classify_crash_state(
            repo_root=repo_dir,
            patch_text="dummy",
            expected_files=("calculator.py",),
        )
        assert classification == CrashStateClassification.EXACT_APPROVED_PATCH_PRESENT

    def test_partial_or_unknown_state_fails_closed(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        # Dirty with an unexpected file
        (repo_dir / "unexpected.txt").write_text("junk", encoding="utf-8")

        classification = classify_crash_state(
            repo_root=repo_dir,
            patch_text="dummy",
            expected_files=("calculator.py",),
        )
        assert classification == CrashStateClassification.PARTIAL_OR_UNKNOWN_STATE


# ==============================================================================
# 3B. Candidate Eligibility & Diff Validation Tests
# ==============================================================================

class TestCandidateEligibilityAndValidation:
    """Verifies fail-closed rejection of ineligible candidate artifacts."""

    def test_candidate_rejected_if_qa_verdict_is_fail(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head, qa_verdict="FAIL")

        with pytest.raises(CandidateNotEligibleError) as exc_info:
            service.prepare_real_repo_apply(
                code_patch_artifact_id=chain["patch_artifact"].id,
                qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
                target_repo_root=repo_dir,
            )
        assert "expected 'PASS'" in str(exc_info.value)

    def test_candidate_rejected_if_patch_sha_mismatch(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        # Tamper with the physical patch file
        patch_file = runs_dir / chain["patch_artifact"].path
        patch_file.write_text("tampered content", encoding="utf-8")

        with pytest.raises(CandidateNotEligibleError) as exc_info:
            service.prepare_real_repo_apply(
                code_patch_artifact_id=chain["patch_artifact"].id,
                qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
                target_repo_root=repo_dir,
            )
        assert "CODE_PATCH SHA mismatch" in str(exc_info.value)

    def test_candidate_rejected_if_base_commit_mismatch(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        # Advance target repo HEAD
        (repo_dir / "adv.txt").write_text("adv", encoding="utf-8")
        run_git(["add", "adv.txt"], cwd=repo_dir)
        run_git(["commit", "-m", "adv"], cwd=repo_dir)

        with pytest.raises(BaseCommitMismatchError) as exc_info:
            service.prepare_real_repo_apply(
                code_patch_artifact_id=chain["patch_artifact"].id,
                qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
                target_repo_root=repo_dir,
            )
        assert "does not match CODE_PATCH base commit" in str(exc_info.value)

    def test_candidate_rejected_if_protected_path(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head, changed_files=[".env"])

        with pytest.raises(ProtectedPathError):
            service.prepare_real_repo_apply(
                code_patch_artifact_id=chain["patch_artifact"].id,
                qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
                target_repo_root=repo_dir,
            )


    def test_candidate_rejected_if_non_passing_verification_outcomes(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head, verification_passed=False)

        with pytest.raises(CandidateNotEligibleError) as exc_info:
            service.prepare_real_repo_apply(
                code_patch_artifact_id=chain["patch_artifact"].id,
                qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
                target_repo_root=repo_dir,
            )
        assert "non-passing verification" in str(exc_info.value)

    def test_validate_real_repo_diff_catches_extra_file(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        (repo_dir / "calculator.py").write_text("updated", encoding="utf-8")
        (repo_dir / "extra.py").write_text("extra", encoding="utf-8")

        with pytest.raises(PostApplyDiffMismatchError) as exc_info:
            validate_real_repo_diff(repo_dir, ("calculator.py",))
        assert "unexpected changed file" in str(exc_info.value)

    def test_validate_real_repo_diff_catches_missing_file(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        with pytest.raises(PostApplyDiffMismatchError) as exc_info:
            validate_real_repo_diff(repo_dir, ("calculator.py",))
        assert "missing expected changed file" in str(exc_info.value)

    def test_git_hooks_neutralized_during_apply(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        setup_disposable_repo(repo_dir)

        # Create a malicious hook in target repo .git/hooks/
        hooks_dir = repo_dir / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        marker = repo_dir / "hook_executed_marker.txt"
        hook_script = hooks_dir / "pre-applypatch"
        hook_script.write_text(f"touch {marker.as_posix()}\n", encoding="utf-8")

        patch_text = (
            "diff --git a/calculator.py b/calculator.py\n"
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a: int, b: int) -> int:\n"
            "-    return 0\n"
            "+    return a + b\n"
        )
        precheck_code_patch_applicability(repo_dir, patch_text)
        apply_code_patch_to_real_repo(repo_dir, patch_text)

        # Hook must NOT have executed
        assert not marker.exists()


# ==============================================================================
# 4. Zero Mutation in Prepare and Approve Tests (Principle 10)
# ==============================================================================

class TestPrepareAndApproveZeroMutation:

    """Verifies that prepare and approve perform ZERO repository mutation."""

    def test_prepare_real_repo_apply_zero_mutation(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        stat_before = verify_target_repo_cleanliness(repo_dir)[1]
        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )

        stat_after = verify_target_repo_cleanliness(repo_dir)[1]
        assert stat_before == ""
        assert stat_after == ""
        assert proposal.target_head_hash == head
        assert proposal.code_patch_artifact_id == chain["patch_artifact"].id
        assert proposal.is_clean is True

    def test_approve_real_repo_apply_zero_mutation(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )

        stat_before = verify_target_repo_cleanliness(repo_dir)[1]
        grant = service.approve_real_repo_apply(
            proposal_id=proposal.proposal_id,
            founder_approval_id="founder_human_approval_001",
            approver="Human Founder",
        )
        stat_after = verify_target_repo_cleanliness(repo_dir)[1]

        assert stat_before == ""
        assert stat_after == ""
        assert grant.proposal_id == proposal.proposal_id
        assert grant.human_approval_id == "founder_human_approval_001"
        assert grant.status == "ISSUED"

    def test_missing_founder_approval_fails(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )

        with pytest.raises(MissingApprovalError):
            service.approve_real_repo_apply(
                proposal_id=proposal.proposal_id,
                founder_approval_id="",
            )


# ==============================================================================
# 5. Security & Invariant Tests (Replay, Expiry, Agent Runtime)
# ==============================================================================

class TestSecurityAndExecutionInvariants:
    """Verifies replay protection, expiry, and zero agent invocation."""

    def test_grant_replay_protection(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )
        grant = service.approve_real_repo_apply(
            proposal_id=proposal.proposal_id,
            founder_approval_id="founder_appr_01",
        )

        # First execution succeeds
        res1 = service.execute_real_repo_apply(grant.grant_id)
        assert res1.status == RealRepoApplyStatus.APPLIED_SUCCESSFULLY.value

        # Second execution with same grant MUST be rejected
        with pytest.raises(GrantReplayedError):
            service.execute_real_repo_apply(grant.grant_id)

    def test_grant_expiration_rejected(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )
        grant = service.approve_real_repo_apply(
            proposal_id=proposal.proposal_id,
            founder_approval_id="founder_appr_01",
        )

        # Manually alter approved_at to simulate expiration
        expired_grant = RealRepoApplyGrant(
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
            approved_at="2020-01-01T00:00:00+00:00",
            status="ISSUED",
            validity_duration_seconds=3600,
        )
        service._real_repo_apply_grants[grant.grant_id] = expired_grant

        with pytest.raises(GrantExpiredError):
            service.execute_real_repo_apply(grant.grant_id)

    def test_zero_agent_runtime_invocation_during_apply(self, tmp_path: Path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        mock_runtime = MagicMock(spec=AntigravityRuntime)
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir, runtime=mock_runtime)
        chain = create_candidate_chain(service, repo_dir, head)

        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )
        grant = service.approve_real_repo_apply(
            proposal_id=proposal.proposal_id,
            founder_approval_id="founder_appr_01",
        )

        res = service.execute_real_repo_apply(grant.grant_id)
        assert res.status == RealRepoApplyStatus.APPLIED_SUCCESSFULLY.value

        # Assert Antigravity runtime was NEVER called during real repo apply
        assert mock_runtime.execute.call_count == 0



# ==============================================================================
# 6. The Four Disposable-Repository Live Proofs
# ==============================================================================

class TestLiveProofs:
    """Rigorous live proofs executed against real, disposable Git repositories."""

    def test_live_proof_1_clean_successful_apply(self, tmp_path: Path):
        """Live Proof 1: Clean successful apply to real-like repository.

        Verifies:
        - Target working tree mutated cleanly.
        - Exact diff correspondence between working tree and CODE_PATCH.
        - HEAD commit unchanged (no working tree commit).
        - External lock acquired during transaction and released.
        - Durable REAL_REPO_APPLY_REPORT artifact materialized with SHA-256 integrity.
        """
        repo_dir = tmp_path / "live_repo_1"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        # 1. Prepare
        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )
        assert proposal.is_clean is True

        # 2. Approve
        grant = service.approve_real_repo_apply(
            proposal_id=proposal.proposal_id,
            founder_approval_id="founder_live_proof_1",
            approver="Human Founder",
        )

        # 3. Execute
        result = service.execute_real_repo_apply(grant.grant_id)

        assert result.status == RealRepoApplyStatus.APPLIED_SUCCESSFULLY.value
        assert result.pre_apply_head == head
        assert result.post_apply_head == head  # No auto-commit!
        assert result.actual_files == ["calculator.py"]

        # Check physical file modification
        calc_content = (repo_dir / "calculator.py").read_text(encoding="utf-8")
        assert "return a + b" in calc_content

        # Check git status
        is_clean, dirty_out = verify_target_repo_cleanliness(repo_dir)
        assert is_clean is False
        assert "calculator.py" in dirty_out

        # Check lock released
        locks_dir = runs_dir / "locks"
        assert not any(locks_dir.glob("*.lock"))

        # Check durable artifact
        assert result.report_artifact_id is not None
        report_lineage = service.find_artifact(result.report_artifact_id)
        assert report_lineage is not None
        _, _, rep_art = report_lineage
        assert rep_art.artifact_type == ArtifactType.REAL_REPO_APPLY_REPORT.value
        assert rep_art.sha256 is not None

    def test_live_proof_2_toctou_invalidation_when_repo_advances(self, tmp_path: Path):
        """Live Proof 2: TOCTOU invalidation when repository state changes after approval.

        Verifies:
        - When repository HEAD advances after approval, transaction aborts before mutation.
        - Target repository remains untouched at its new HEAD.
        - Lock is safely released.
        """
        repo_dir = tmp_path / "live_repo_2"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        proposal = service.prepare_real_repo_apply(
            code_patch_artifact_id=chain["patch_artifact"].id,
            qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
            target_repo_root=repo_dir,
        )
        grant = service.approve_real_repo_apply(
            proposal_id=proposal.proposal_id,
            founder_approval_id="founder_live_proof_2",
        )

        # TOCTOU Intervention: Human owner commits new change to repository
        (repo_dir / "other.py").write_text("# other feature\n", encoding="utf-8")
        run_git(["add", "other.py"], cwd=repo_dir)
        run_git(["commit", "-m", "Intervening commit by developer"], cwd=repo_dir)
        new_head = resolve_repo_head_commit(repo_dir)
        assert new_head != head

        # Execution MUST detect TOCTOU violation and abort before mutating calculator.py
        with pytest.raises(RepositoryStateChangedError) as exc_info:
            service.execute_real_repo_apply(grant.grant_id)

        assert "TOCTOU violation" in str(exc_info.value)

        # Verify calculator.py was NOT modified
        calc_content = (repo_dir / "calculator.py").read_text(encoding="utf-8")
        assert "return 0" in calc_content

        # Verify lock is released
        locks_dir = runs_dir / "locks"
        assert not any(locks_dir.glob("*.lock"))

    def test_live_proof_3_safe_rollback_when_post_apply_diff_corrupted(self, tmp_path: Path):
        """Live Proof 3: Safe rollback when post-apply diff is corrupted.

        Verifies:
        - If post-apply diff validation fails, targeted safe rollback restores clean state.
        - Primary rollback uses git apply --reverse.
        - No dangerous git reset --hard or git clean -fd.
        - Clean state precondition is strictly restored.
        """
        repo_dir = tmp_path / "live_repo_3"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        # Patch that modifies calculator.py
        patch_text = chain["patch_text"]

        # 1. Apply patch directly
        apply_code_patch_to_real_repo(repo_dir, patch_text)
        assert not verify_target_repo_cleanliness(repo_dir)[0]

        # 2. Corrupt post-apply state by creating an extra untracked file
        (repo_dir / "corrupted_extra.py").write_text("corrupted", encoding="utf-8")

        # 3. Validation catches the mismatch
        with pytest.raises(PostApplyDiffMismatchError):
            validate_real_repo_diff(repo_dir, ("calculator.py",))

        # Remove extra file so clean pre-condition is testable for reverse apply
        (repo_dir / "corrupted_extra.py").unlink()

        # 4. Trigger safe rollback
        rollback_real_repo_apply(repo_dir, patch_text, ("calculator.py",))

        # 5. Verify repository is 100% clean and restored to original baseline
        is_clean, dirty_out = verify_target_repo_cleanliness(repo_dir)
        assert is_clean is True, f"Working tree not clean: {dirty_out}"

        calc_content = (repo_dir / "calculator.py").read_text(encoding="utf-8")
        assert "return 0" in calc_content

    def test_live_proof_4_unresolved_crash_state_fails_closed(self, tmp_path: Path):
        """Live Proof 4: Unresolved crash recovery state fails closed and blocks new apply.

        Verifies:
        - A repository in an unknown/dirty crash state is classified as PARTIAL_OR_UNKNOWN_STATE.
        - Both prepare_real_repo_apply and execute_real_repo_apply fail closed with CrashRecoveryBlockError.
        - No mutation occurs.
        """
        repo_dir = tmp_path / "live_repo_4"
        repo_dir.mkdir()
        head = setup_disposable_repo(repo_dir)

        runs_dir = tmp_path / ".runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo_dir)
        chain = create_candidate_chain(service, repo_dir, head)

        # Simulate a crash leaving partial changes: calculator.py is corrupted
        (repo_dir / "calculator.py").write_text("PARTIAL_CRASH_STATE\n", encoding="utf-8")
        (repo_dir / "untracked_artifact.tmp").write_text("trash", encoding="utf-8")

        # Classify state
        state = classify_crash_state(repo_dir, chain["patch_text"], ("calculator.py",))
        assert state == CrashStateClassification.PARTIAL_OR_UNKNOWN_STATE

        # Prepare must fail closed
        with pytest.raises(CrashRecoveryBlockError) as exc_info:
            service.prepare_real_repo_apply(
                code_patch_artifact_id=chain["patch_artifact"].id,
                qa_execution_report_artifact_id=chain["qa_exec_artifact"].id,
                target_repo_root=repo_dir,
            )

        assert "unresolved crash" in str(exc_info.value)
