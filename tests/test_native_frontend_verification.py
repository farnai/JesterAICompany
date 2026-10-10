"""Deterministic Regression & Integration Tests for Native Frontend Verification (STEP 23B.6-E).

Tests:
1. Successful frontend build inside real isolated worktree (no shell=True, canonical repo untouched).
2. Successful frontend build verdict validation preserves PASS.
3. Failed frontend build execution captures exit code and stderr.
4. Failed frontend build verdict validation overrides PASS to FAIL.
5. Missing 'build' script in package.json is rejected and blocks PASS.
6. Rejected actions (forbidden characters, traversal, missing dir, missing package.json) block PASS.
7. Bounded execution timeout captures TIMEOUT and overrides PASS to FAIL.
8. Unrelated backend tests block frontend changes from receiving PASS.
9. Missing changed-file metadata does not bypass subsystem relevance check.
10. Backend-only changes continue to pass with backend tests.
11. Full QA verification task execution pipeline with frontend build.
"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List
import uuid

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
from jester_ai_company.developer_result import DeveloperTaskResult, ProposedFile
from jester_ai_company.execution_grant import (
    ExecutionGrant,
    GrantValidationError,
    VerificationAction,
)
from jester_ai_company.materializer import (
    materialize_code_patch_artifact,
    materialize_qa_report_artifact,
    materialize_specialist_artifact,
)
from jester_ai_company.product_result import ProductDeliverable, ProductTaskResult
from jester_ai_company.qa_execution import (
    QAActionAuthorizationDecision,
    QAExecutionActionAudit,
    QAExecutionStatus,
    QAExecutionVerdictResult,
    QAFinalVerdict,
    authorize_and_convert_qa_actions,
    enforce_deterministic_verdict_constraints,
    extract_changed_files_from_patch,
    is_frontend_path,
    is_frontend_verification_action,
    parse_and_validate_qa_verdict,
)
from jester_ai_company.qa_result import (
    QAInspectionResult,
    QARecommendedAction,
)
from jester_ai_company.runtime import AgentExecutionResult
from jester_ai_company.service import CompanyService
from jester_ai_company.verification import (
    TargetValidationError,
    UnsupportedActionTypeError,
    VerificationExecutionResult,
    VerificationStatus,
    execute_verification_action,
    translate_verification_action,
    validate_verification_target,
)
from jester_ai_company.worktree import (
    WorktreeManager,
    resolve_repo_head_commit,
    run_git,
    sanitize_execution_environment,
)


@pytest.fixture
def canonical_repo_path() -> Path:
    """Return the absolute path to the canonical workspace repository."""
    return Path(__file__).resolve().parent.parent


def test_01_successful_frontend_build_in_real_isolated_worktree(canonical_repo_path):
    """1. Frontend build executes successfully inside an isolated worktree; canonical repo untouched."""
    mgr = WorktreeManager(repo_root=canonical_repo_path)
    head_commit = mgr.validate_repository()

    # Capture initial repository status
    code_init, out_init, err_init = run_git(["status", "--porcelain"], cwd=canonical_repo_path)
    assert code_init == 0

    session_id = f"test_fe_build_{uuid.uuid4().hex[:8]}"
    session = mgr.create_qa_worktree(base_commit_hash=head_commit, session_id=session_id)
    try:
        assert session.worktree_path.exists()
        assert (session.worktree_path / "frontend" / "package.json").is_file()

        action = VerificationAction(action_type="frontend_build", target="frontend")
        result = execute_verification_action(
            action=action,
            worktree_path=session.worktree_path,
            timeout=60.0,
        )

        # Build must pass cleanly inside isolated worktree
        if result.status != VerificationStatus.PASS.value:
            print("TEST 1 STDERR:", result.stderr)
            print("TEST 1 STDOUT:", result.stdout)
            print("TEST 1 ERROR:", result.error)
        assert result.status == VerificationStatus.PASS.value
        assert result.exit_code == 0
        assert result.passed is True
        assert result.duration_ms > 0
        assert not result.error

    finally:
        session.remove()

    # Verify session is cleaned up
    assert not session.worktree_path.exists()

    # Verify canonical repo is completely untouched
    code_after, out_after, err_after = run_git(["status", "--porcelain"], cwd=canonical_repo_path)
    assert code_after == 0
    assert out_after == out_init
    assert mgr.validate_repository() == head_commit


def test_02_successful_frontend_build_verdict_validation():
    """2. When frontend code changes have verified frontend builds, PASS is preserved."""
    agent_verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,
        summary="Frontend UI changes verified via build",
        requirements_evaluations=[],
        blocking_issues=[],
        release_recommendation="APPROVED_FOR_RELEASE",
    )
    va = VerificationAction("frontend_build", "frontend")
    audits = [
        QAExecutionActionAudit(
            action_type="frontend_build",
            target="frontend",
            purpose="compile and typecheck frontend",
            decision=QAActionAuthorizationDecision.AUTHORIZED.value,
            converted_action=va,
        )
    ]
    exec_result = VerificationExecutionResult(
        action=va,
        status=VerificationStatus.PASS.value,
        exit_code=0,
        stdout="tsc -b && vite build complete",
        stderr="",
        duration_ms=2500,
    )
    changed_files = ["frontend/src/components/Header.tsx"]

    constrained = enforce_deterministic_verdict_constraints(
        verdict_result=agent_verdict,
        action_audits=audits,
        verification_results=[exec_result],
        changed_files=changed_files,
    )

    assert constrained.verdict == QAFinalVerdict.PASS.value
    assert constrained.release_recommendation == "APPROVED_FOR_RELEASE"
    assert constrained.deterministic_override_applied is False
    assert len(constrained.blocking_issues) == 0


def test_03_failed_frontend_build_execution():
    """3. Failed frontend build produces FAIL status, captures nonzero exit code and logs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wt = Path(tmpdir) / "worktree"
        fe_dir = wt / "frontend"
        fe_dir.mkdir(parents=True, exist_ok=True)

        # package.json with a failing build script
        pkg_data = {
            "name": "test-failing-frontend",
            "scripts": {
                "build": "node -e process.exit(42)"
            }
        }
        (fe_dir / "package.json").write_text(json.dumps(pkg_data), encoding="utf-8")

        action = VerificationAction("frontend_build", "frontend")
        result = execute_verification_action(action=action, worktree_path=wt)

        assert result.status == VerificationStatus.FAIL.value
        assert result.exit_code == 42
        assert result.passed is False
        assert result.duration_ms >= 0


def test_04_failed_frontend_build_verdict_validation():
    """4. If executed frontend verification fails, agent PASS is deterministically overridden to FAIL."""
    agent_verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,
        summary="Agent falsely claimed frontend changes are fine",
        requirements_evaluations=[],
        blocking_issues=[],
        release_recommendation="APPROVED_FOR_RELEASE",
    )
    va = VerificationAction("frontend_build", "frontend")
    audits = [
        QAExecutionActionAudit(
            action_type="frontend_build",
            target="frontend",
            purpose="build",
            decision=QAActionAuthorizationDecision.AUTHORIZED.value,
            converted_action=va,
        )
    ]
    exec_result = VerificationExecutionResult(
        action=va,
        status=VerificationStatus.FAIL.value,
        exit_code=1,
        stdout="TS2304: Cannot find name 'foo'",
        stderr="Build error",
        duration_ms=1200,
    )
    changed_files = ["frontend/src/App.tsx"]

    constrained = enforce_deterministic_verdict_constraints(
        verdict_result=agent_verdict,
        action_audits=audits,
        verification_results=[exec_result],
        changed_files=changed_files,
    )

    assert constrained.verdict == QAFinalVerdict.FAIL.value
    assert constrained.release_recommendation == "REJECTED_NEEDS_FIX"
    assert constrained.deterministic_override_applied is True
    assert "failed" in constrained.override_reason.lower()
    assert any("failed" in issue.lower() for issue in constrained.blocking_issues)


def test_05_missing_build_script_rejection():
    """5. package.json missing 'build' script is rejected during validation and blocks release."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wt = Path(tmpdir) / "worktree"
        fe_dir = wt / "frontend"
        fe_dir.mkdir(parents=True, exist_ok=True)

        # package.json without 'build' script
        pkg_data = {
            "name": "no-build-script",
            "scripts": {
                "test": "vitest run"
            }
        }
        (fe_dir / "package.json").write_text(json.dumps(pkg_data), encoding="utf-8")

        # 1. Target validation rejects it
        with pytest.raises(TargetValidationError, match="does not define a 'build' script"):
            validate_verification_target("frontend", wt, action_type="frontend_build")

        # 2. Authorization rejects it
        recs = [QARecommendedAction(action_type="frontend_build", target="frontend", purpose="build")]
        authorized, audits = authorize_and_convert_qa_actions(recs, wt)

        assert len(authorized) == 0
        assert len(audits) == 1
        assert audits[0].decision == QAActionAuthorizationDecision.REJECTED_TARGET_NOT_FOUND.value
        assert "build" in audits[0].reason

        # 3. Verdict enforcement forbids PASS on rejected action
        agent_verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.PASS.value,
            summary="Agent passed despite missing build script",
        )
        constrained = enforce_deterministic_verdict_constraints(
            verdict_result=agent_verdict,
            action_audits=audits,
            verification_results=[],
            changed_files=["frontend/src/App.tsx"],
        )

        assert constrained.verdict == QAFinalVerdict.BLOCKED.value
        assert constrained.deterministic_override_applied is True


def test_06_rejected_actions_forbidden_chars_traversal_missing():
    """6. Malicious metacharacters, traversal, and nonexistent targets are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wt = Path(tmpdir) / "worktree"
        wt.mkdir(parents=True, exist_ok=True)

        recs = [
            # Shell metacharacters
            QARecommendedAction(action_type="frontend_build", target="frontend; rm -rf /", purpose="injection"),
            # Traversal
            QARecommendedAction(action_type="frontend_build", target="../outside", purpose="traversal"),
            # Nonexistent target
            QARecommendedAction(action_type="frontend_build", target="frontend_nonexistent", purpose="missing"),
            # Target missing package.json
            QARecommendedAction(action_type="frontend_build", target="empty_dir", purpose="no pkg json"),
        ]
        (wt / "empty_dir").mkdir(parents=True, exist_ok=True)

        authorized, audits = authorize_and_convert_qa_actions(recs, wt)
        assert len(authorized) == 0
        assert audits[0].decision == QAActionAuthorizationDecision.REJECTED_FORBIDDEN_CHARS.value
        assert audits[1].decision == QAActionAuthorizationDecision.REJECTED_TRAVERSAL.value
        assert audits[2].decision == QAActionAuthorizationDecision.REJECTED_TARGET_NOT_FOUND.value
        assert audits[3].decision == QAActionAuthorizationDecision.REJECTED_TARGET_NOT_FOUND.value

        # Overridden to BLOCKED
        agent_verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.PASS.value,
            summary="Pass with rejected audits",
        )
        constrained = enforce_deterministic_verdict_constraints(
            verdict_result=agent_verdict,
            action_audits=audits,
            verification_results=[],
            changed_files=["frontend/src/App.tsx"],
        )
        assert constrained.verdict == QAFinalVerdict.BLOCKED.value


def test_07_frontend_build_timeout():
    """7. Subprocess timeout captures TIMEOUT status and deterministically overrides PASS to FAIL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        wt = Path(tmpdir) / "worktree"
        fe_dir = wt / "frontend"
        fe_dir.mkdir(parents=True, exist_ok=True)

        # Build script that sleeps longer than timeout
        pkg_data = {
            "name": "test-timeout",
            "scripts": {
                "build": "node -e setTimeout(null,5000)"
            }
        }
        (fe_dir / "package.json").write_text(json.dumps(pkg_data), encoding="utf-8")

        action = VerificationAction("frontend_build", "frontend")
        result = execute_verification_action(
            action=action,
            worktree_path=wt,
            timeout=0.1,  # Bounded execution timeout
        )

        assert result.status == VerificationStatus.TIMEOUT.value
        assert result.exit_code == -1
        assert result.passed is False
        assert "timed out" in (result.error or "").lower()

        # Verdict validation overrides to FAIL
        agent_verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.PASS.value,
            summary="Agent passed despite timeout",
        )
        audits = [
            QAExecutionActionAudit(
                action_type="frontend_build",
                target="frontend",
                purpose="build",
                decision=QAActionAuthorizationDecision.AUTHORIZED.value,
                converted_action=action,
            )
        ]
        constrained = enforce_deterministic_verdict_constraints(
            verdict_result=agent_verdict,
            action_audits=audits,
            verification_results=[result],
            changed_files=["frontend/src/App.tsx"],
        )

        assert constrained.verdict == QAFinalVerdict.FAIL.value
        assert constrained.release_recommendation == "REJECTED_NEEDS_FIX"
        assert constrained.deterministic_override_applied is True


def test_08_unrelated_backend_tests_block_frontend_changes():
    """8. Frontend changes cannot receive PASS solely from unrelated backend tests."""
    agent_verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,
        summary="Passed backend canonical test",
    )
    va = VerificationAction("pytest", "tests/core/test_canonical.py")
    audits = [
        QAExecutionActionAudit(
            action_type="pytest",
            target="tests/core/test_canonical.py",
            purpose="backend canonical",
            decision=QAActionAuthorizationDecision.AUTHORIZED.value,
            converted_action=va,
        )
    ]
    exec_result = VerificationExecutionResult(
        action=va,
        status=VerificationStatus.PASS.value,
        exit_code=0,
        stdout="1 passed in 0.02s",
        stderr="",
        duration_ms=20,
    )
    changed_files = ["frontend/src/components/NewObjectiveModal.tsx"]

    constrained = enforce_deterministic_verdict_constraints(
        verdict_result=agent_verdict,
        action_audits=audits,
        verification_results=[exec_result],
        changed_files=changed_files,
    )

    assert constrained.verdict == QAFinalVerdict.BLOCKED.value
    assert constrained.release_recommendation == "BLOCKED_ON_FRONTEND_VERIFICATION"
    assert constrained.deterministic_override_applied is True
    assert "Frontend code changes cannot receive a release-ready PASS" in constrained.override_reason


def test_09_missing_changed_file_metadata_does_not_bypass_relevance_check():
    """9. Missing changed_files metadata does not silently bypass frontend relevance checks."""
    patch_text = (
        "diff --git a/frontend/src/components/ObjectiveHeader.tsx b/frontend/src/components/ObjectiveHeader.tsx\n"
        "index 1111111..2222222 100644\n"
        "--- a/frontend/src/components/ObjectiveHeader.tsx\n"
        "+++ b/frontend/src/components/ObjectiveHeader.tsx\n"
        "@@ -1,3 +1,4 @@\n"
        "+// Modified header component\n"
    )
    va = VerificationAction("pytest", "tests/core/test_canonical.py")
    audits = [
        QAExecutionActionAudit(
            action_type="pytest",
            target="tests/core/test_canonical.py",
            purpose="backend test",
            decision=QAActionAuthorizationDecision.AUTHORIZED.value,
            converted_action=va,
        )
    ]
    exec_result = VerificationExecutionResult(
        action=va,
        status=VerificationStatus.PASS.value,
        exit_code=0,
        stdout="1 passed",
        stderr="",
        duration_ms=15,
    )

    # 1. changed_files is None
    agent_verdict_1 = QAExecutionVerdictResult(schema_version="1.0", verdict="PASS", summary="ok")
    res_1 = enforce_deterministic_verdict_constraints(
        verdict_result=agent_verdict_1,
        action_audits=audits,
        verification_results=[exec_result],
        changed_files=None,
        code_patch_text=patch_text,
    )
    assert res_1.verdict == QAFinalVerdict.BLOCKED.value
    assert res_1.release_recommendation == "BLOCKED_ON_FRONTEND_VERIFICATION"

    # 2. changed_files is empty []
    agent_verdict_2 = QAExecutionVerdictResult(schema_version="1.0", verdict="PASS", summary="ok")
    res_2 = enforce_deterministic_verdict_constraints(
        verdict_result=agent_verdict_2,
        action_audits=audits,
        verification_results=[exec_result],
        changed_files=[],
        code_patch_text=patch_text,
    )
    assert res_2.verdict == QAFinalVerdict.BLOCKED.value
    assert res_2.release_recommendation == "BLOCKED_ON_FRONTEND_VERIFICATION"

    # 3. Via parse_and_validate_qa_verdict
    raw_json = json.dumps({
        "schema_version": "1.0",
        "verdict": "PASS",
        "summary": "Agent passed with missing changed_files metadata",
        "requirements_evaluations": [],
        "blocking_issues": [],
        "release_recommendation": "APPROVED_FOR_RELEASE",
    })
    res_3 = parse_and_validate_qa_verdict(
        raw_output=raw_json,
        action_audits=audits,
        verification_results=[exec_result],
        changed_files=[],
        code_patch_text=patch_text,
    )
    assert res_3.verdict == QAFinalVerdict.BLOCKED.value
    assert res_3.release_recommendation == "BLOCKED_ON_FRONTEND_VERIFICATION"


def test_10_backend_only_changes_continue_to_pass():
    """10. Backend-only changes verified by passing backend tests maintain PASS."""
    agent_verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,
        summary="Backend optimization verified cleanly",
        requirements_evaluations=[],
        blocking_issues=[],
        release_recommendation="APPROVED_FOR_RELEASE",
    )
    va = VerificationAction("pytest", "tests/core/test_canonical.py")
    audits = [
        QAExecutionActionAudit(
            action_type="pytest",
            target="tests/core/test_canonical.py",
            purpose="canonical verification",
            decision=QAActionAuthorizationDecision.AUTHORIZED.value,
            converted_action=va,
        )
    ]
    exec_result = VerificationExecutionResult(
        action=va,
        status=VerificationStatus.PASS.value,
        exit_code=0,
        stdout="1 passed",
        stderr="",
        duration_ms=30,
    )
    changed_files = ["jester_ai_company/core.py"]
    patch_text = (
        "diff --git a/jester_ai_company/core.py b/jester_ai_company/core.py\n"
        "--- a/jester_ai_company/core.py\n"
        "+++ b/jester_ai_company/core.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+# Backend change\n"
    )

    constrained = enforce_deterministic_verdict_constraints(
        verdict_result=agent_verdict,
        action_audits=audits,
        verification_results=[exec_result],
        changed_files=changed_files,
        code_patch_text=patch_text,
    )

    assert constrained.verdict == QAFinalVerdict.PASS.value
    assert constrained.release_recommendation == "APPROVED_FOR_RELEASE"
    assert constrained.deterministic_override_applied is False


def test_11_full_qa_verification_pipeline_with_frontend_build(canonical_repo_path):
    """11. QA verification pipeline executes authorized frontend build in isolated worktree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a test repository with a frontend subsystem
        repo = Path(tmpdir) / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        run_git(["init"], cwd=repo)
        run_git(["config", "user.name", "QA Frontend Tester"], cwd=repo)
        run_git(["config", "user.email", "qa_fe@example.com"], cwd=repo)
        (repo / "README.md").write_text("# Target Repo Baseline\n", encoding="utf-8")

        fe_dir = repo / "frontend"
        fe_dir.mkdir(parents=True, exist_ok=True)
        pkg_data = {
            "name": "frontend-pipeline-test",
            "scripts": {
                "build": "node -v"
            }
        }
        (fe_dir / "package.json").write_text(json.dumps(pkg_data), encoding="utf-8")
        (fe_dir / "Button.tsx").write_text("export const Button = () => null;\n", encoding="utf-8")

        run_git(["add", "."], cwd=repo)
        run_git(["commit", "-m", "Baseline commit with frontend"], cwd=repo)
        head_commit = resolve_repo_head_commit(repo)

        service = CompanyService(repo_root=repo, output_dir=repo / ".runs")

        # Set up upstream artifacts
        proj = service.create_project(project_id="proj_fe_01", name="FE Test Project", tech_stack=["TypeScript"])
        prod_task = service.create_task(project_id=proj.id, title="Product Task", goal="Reqs", required_roles=["product"])
        prod_run = prod_task.create_run()
        prod_res = ProductTaskResult(
            schema_version="1.0",
            status="completed",
            summary="FE Requirement",
            deliverables=[ProductDeliverable(name="Requirements", content="REQ-1: Add button")],
        )
        prod_art = materialize_specialist_artifact(
            base_output_dir=Path(service.output_dir),
            task=prod_task,
            run=prod_run,
            agent_name="product",
            typed_result=prod_res,
        )
        prod_run.complete(status=RunStatus.SUCCESS.value)
        prod_task.complete(status=TaskStatus.COMPLETED.value, summary=prod_res.summary)

        dev_task = service.create_task(project_id=proj.id, title="Developer Plan", goal="Plan FE", required_roles=["developer"])
        service.attach_input_artifact(dev_task.id, prod_art.id, project_id=proj.id)
        dev_run = dev_task.create_run()
        dev_res = DeveloperTaskResult(
            schema_version="1.0",
            status="completed",
            summary="Plan FE",
            implementation_plan=["Modify Button.tsx"],
        )
        plan_art = materialize_specialist_artifact(
            base_output_dir=Path(service.output_dir),
            task=dev_task,
            run=dev_run,
            agent_name="developer",
            typed_result=dev_res,
        )
        dev_run.complete(status=RunStatus.SUCCESS.value)
        dev_task.complete(status=TaskStatus.COMPLETED.value, summary=dev_res.summary)

        grant = ExecutionGrant(
            grant_id="grant_fe_01",
            task_id=dev_task.id,
            plan_artifact_id=plan_art.id,
            plan_sha256=plan_art.sha256,
            base_commit_hash=head_commit,
            approved_files_to_modify=["frontend/Button.tsx"],
            verification_actions=[VerificationAction("frontend_build", "frontend")],
            founder_approval_id="founder_fe_01",
        )

        patch_text = (
            "diff --git a/frontend/Button.tsx b/frontend/Button.tsx\n"
            "--- a/frontend/Button.tsx\n"
            "+++ b/frontend/Button.tsx\n"
            "@@ -1,1 +1,2 @@\n"
            " export const Button = () => null;\n"
            "+// updated button\n"
        )
        patch_task = service.create_task(project_id=proj.id, title="Dev Mutation", goal="Patch", required_roles=["developer"])
        patch_run = patch_task.create_run()
        patch_art = materialize_code_patch_artifact(
            base_output_dir=Path(service.output_dir),
            task=patch_task,
            run=patch_run,
            patch_text=patch_text,
            grant=grant,
            changed_files=["frontend/Button.tsx"],
            verifications=[{
                "action": {"action_type": "frontend_build", "target": "frontend"},
                "status": "PASS",
                "exit_code": 0,
                "stdout": "Build succeeded",
                "stderr": "",
                "duration_ms": 100,
            }],
        )
        patch_run.complete(status=RunStatus.SUCCESS.value)
        patch_task.complete(status=TaskStatus.COMPLETED.value, summary="Patch created")

        qa_insp_task = service.create_task(project_id=proj.id, title="QA Inspection", goal="Inspect", required_roles=["qa"])
        service.attach_input_artifact(qa_insp_task.id, prod_art.id, project_id=proj.id)
        service.attach_input_artifact(qa_insp_task.id, plan_art.id, project_id=proj.id)
        service.attach_input_artifact(qa_insp_task.id, patch_art.id, project_id=proj.id)
        qa_insp_run = qa_insp_task.create_run()
        qa_insp_res = QAInspectionResult(
            schema_version="1.0",
            status="READY_FOR_QA_EXECUTION",
            summary="Ready for QA execution",
            recommended_verification_actions=[
                QARecommendedAction(action_type="frontend_build", target="frontend", purpose="verify frontend build")
            ],
        )
        qa_rep_art = materialize_qa_report_artifact(
            base_output_dir=Path(service.output_dir),
            task=qa_insp_task,
            run=qa_insp_run,
            typed_result=qa_insp_res,
            lineage_metadata={
                "project_id": proj.id,
                "product_artifact_id": prod_art.id,
                "product_sha256": prod_art.sha256,
                "ux_artifact_id": None,
                "ux_sha256": None,
                "developer_plan_artifact_id": plan_art.id,
                "developer_plan_sha256": plan_art.sha256,
                "execution_grant_id": grant.grant_id,
                "code_patch_artifact_id": patch_art.id,
                "code_patch_sha256": patch_art.sha256,
                "base_commit_hash": head_commit,
                "verification_evidence": [{
                    "action": {"action_type": "frontend_build", "target": "frontend"},
                    "status": "PASS",
                    "exit_code": 0,
                    "stdout": "Build succeeded",
                    "stderr": "",
                    "duration_ms": 100,
                }],
                "recommended_verification_actions": [
                    {"action_type": "frontend_build", "target": "frontend", "purpose": "verify frontend build"}
                ],
            },
        )
        qa_insp_run.complete(status=RunStatus.SUCCESS.value)
        qa_insp_task.complete(status=TaskStatus.COMPLETED.value, summary=qa_insp_res.summary, details=qa_insp_res.to_dict())

        # QA Verify Task
        qa_task = service.create_task(
            project_id=proj.id,
            title="QA Verification: Frontend Build",
            goal="Verify frontend build in fresh isolated worktree",
            required_roles=["qa"],
        )
        service.attach_input_artifact(qa_task.id, prod_art.id, project_id=proj.id)
        service.attach_input_artifact(qa_task.id, plan_art.id, project_id=proj.id)
        service.attach_input_artifact(qa_task.id, patch_art.id, project_id=proj.id)
        service.attach_input_artifact(qa_task.id, qa_rep_art.id, project_id=proj.id)

        # Mock QA agent output with PASS
        mock_verdict = json.dumps({
            "schema_version": "1.0",
            "verdict": "PASS",
            "summary": "Frontend build succeeded cleanly in isolated worktree",
            "requirements_evaluations": [
                {"requirement_id": "REQ-1", "status": "SATISFIED", "evidence": "frontend_build passed", "notes": "ok"}
            ],
            "executed_tests_summary": "1/1 frontend verification action passed",
            "blocking_issues": [],
            "release_recommendation": "APPROVED_FOR_RELEASE",
        })
        service.runtime.execute = lambda agent, prompt, **kw: AgentExecutionResult(
            agent=agent, success=True, stdout=mock_verdict, stderr="", exit_code=0, duration_ms=45.0
        )

        run = service.execute_qa_verification_task(qa_task.id)
        assert run.status == RunStatus.SUCCESS.value
        assert qa_task.status == TaskStatus.COMPLETED.value
        assert qa_task.result is not None

        details = qa_task.result.details
        assert details["verdict"] == QAFinalVerdict.PASS.value
        assert details["release_recommendation"] == "APPROVED_FOR_RELEASE"
        assert details["deterministic_override_applied"] is False

        # Worktree cleaned up
        assert not (repo / ".runs" / "worktrees").exists() or len(list((repo / ".runs" / "worktrees").glob("*"))) == 0

        # QA_EXECUTION_REPORT materialized
        exec_reports = [a for a in run.artifacts if a.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value]
        assert len(exec_reports) == 1
        assert (repo / ".runs" / exec_reports[0].path).exists()
