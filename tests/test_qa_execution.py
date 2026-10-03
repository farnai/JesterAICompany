"""Deterministic Test Matrix & Live Proof for Isolated QA Execution (STEP 14B).

Covers all 25+ verification checkpoints:
1. Fresh disposable Git worktree created from exact base_commit_hash
2. Uncommitted main repo changes absent from QA worktree
3. Missing or tampered CODE_PATCH rejected (fail closed)
4. Unverified or failing CODE_PATCH rejected
5. Missing or tampered QA_REPORT rejected
6. Mismatched upstream lineage rejected (Product, UX, Plan, Patch, QA Report)
7. Application-owned patch applicability check and apply (shell=False)
8. Inapplicable patch fails closed and cleans up
9. Applied diff validation matches CODE_PATCH authority
10. Mismatched diff fails closed and cleans up
11. Safe pytest action authorized and converted
12. Unsupported action type rejected
13. Forbidden metacharacters in target rejected
14. Directory traversal in target rejected
15. Protected path in target rejected
16. Non-existent target marked REJECTED_TARGET_NOT_FOUND
17. Budget limit enforced on QA actions
18. Deterministic constraint: missing/unavailable action FORBIDS PASS -> BLOCKED
19. Deterministic constraint: test failure FORBIDS PASS -> FAIL
20. Deterministic constraint: all tests pass -> PASS permitted
21. Strict verdict schema validation and parser
22. Durable QA_EXECUTION_REPORT artifact materialized with SHA-256 and full lineage
23. Guaranteed worktree cleanup on all exit paths
24. Main repository remains 100% untouched
25. Live Proof (Failing/Gap): Real QA Agent detects coverage gap / test failure -> FAIL / BLOCKED
26. Live Proof (Passing): Real QA Agent evaluates fully satisfied patch & passing test -> PASS
"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from jester_ai_company.execution_grant import ExecutionGrant, VerificationAction
from jester_ai_company.materializer import (
    compute_sha256,
    format_qa_execution_report,
    materialize_code_patch_artifact,
    materialize_qa_execution_report_artifact,
    materialize_qa_report_artifact,
    materialize_specialist_artifact,
)
from jester_ai_company.qa_result import (
    QAFailureReason,
    QAFinding,
    QAInputInvalidError,
    QAInspectionResult,
    QAInspectionStatus,
    QALineageMismatchError,
    QAPatchIntegrityError,
    QARecommendedAction,
    RequirementCoverage,
)
from jester_ai_company.qa_execution import (
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
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService, ExecutionError, InvalidTaskStateError
from jester_ai_company.product_result import ProductDeliverable, ProductTaskResult
from jester_ai_company.developer_result import DeveloperTaskResult, ProposedFile
from jester_ai_company.verification import (
    VerificationExecutionResult,
    VerificationStatus,
    execute_verification_action,
)
from jester_ai_company.worktree import (
    WorktreeManager,
    WorktreeSession,
    resolve_repo_head_commit,
    run_git,
)


# ==============================================================================
# Helper & Fixtures
# ==============================================================================

@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Tuple[Path, str]:
    """Create a temporary initialized Git repository with initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    run_git(["init"], cwd=repo)
    run_git(["config", "user.name", "Test Runner"], cwd=repo)
    run_git(["config", "user.email", "runner@example.com"], cwd=repo)

    readme = repo / "README.md"
    readme.write_text("# Target Repo Baseline\n", encoding="utf-8")
    run_git(["add", "README.md"], cwd=repo)
    run_git(["commit", "-m", "Initial baseline commit"], cwd=repo)

    head = resolve_repo_head_commit(repo)
    return repo, head


def setup_upstream_qa_chain(
    service: CompanyService,
    repo: Path,
    head_commit: str,
    project_id: str = "proj-qa-exec",
    include_ux: bool = False,
    patch_text: Optional[str] = None,
    changed_files: Optional[List[str]] = None,
    recommended_actions: Optional[List[Dict[str, str]]] = None,
    dev_verifications: Optional[List[Dict[str, Any]]] = None,
    product_reqs: Optional[str] = None,
    qa_req_coverages: Optional[List[RequirementCoverage]] = None,
) -> Dict[str, Any]:
    """Setup a canonical Product -> (UX) -> Dev Plan -> Grant -> Patch -> QA_REPORT chain."""
    proj = service.create_project(project_id=project_id, name="QA Exec Test Project", tech_stack=["Python"])

    # 1. Product Task & Artifact
    prod_task = service.create_task(
        project_id=project_id,
        title="Product Spec",
        goal="Greeter requirements",
        required_roles=["product"],
    )
    prod_run = prod_task.create_run()
    prod_run.status = RunStatus.RUNNING.value
    content_str = product_reqs or "REQ-1: Greet known user by name returning 'Hello, {name}!'\nREQ-2: Reject empty name with ValueError"
    prod_res = ProductTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Greeter requirements",
        deliverables=[
            ProductDeliverable(
                name="Requirements",
                content=content_str,
            )
        ],
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

    # 2. Optional UX
    ux_art = None
    ux_task = None
    if include_ux:
        ux_task = service.create_task(project_id=project_id, title="UX Spec", goal="UX Design", required_roles=["ux"])
        service.attach_input_artifact(ux_task.id, prod_art.id, project_id=project_id)
        ux_run = ux_task.create_run()
        ux_run.status = RunStatus.RUNNING.value
        from jester_ai_company.ux_result import UXTaskResult
        ux_res = UXTaskResult(schema_version="1.0", status="completed", summary="UX Design.")
        ux_art = materialize_specialist_artifact(
            base_output_dir=Path(service.output_dir),
            task=ux_task,
            run=ux_run,
            agent_name="ux",
            typed_result=ux_res,
        )
        ux_run.complete(status=RunStatus.SUCCESS.value)
        ux_task.complete(status=TaskStatus.COMPLETED.value, summary=ux_res.summary, details=ux_res.to_dict())

    # 3. Developer Plan
    dev_task = service.create_task(project_id=project_id, title="Dev Plan", goal="Plan greeter", required_roles=["developer"])
    service.attach_input_artifact(dev_task.id, prod_art.id, project_id=project_id)
    if include_ux and ux_art:
        service.attach_input_artifact(dev_task.id, ux_art.id, project_id=project_id)
    dev_run = dev_task.create_run()
    dev_run.status = RunStatus.RUNNING.value
    dev_res = DeveloperTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Plan greeter module",
        implementation_plan=["Create greeter.py"],
        files_to_create=[ProposedFile(path="greeter.py", description="Greeter module")],
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

    # 4. Grant
    grant = ExecutionGrant(
        grant_id=f"grant_{proj.id}_001",
        task_id=dev_task.id,
        plan_artifact_id=plan_art.id,
        plan_sha256=plan_art.sha256,
        base_commit_hash=head_commit,
        approved_files_to_modify=[],
        approved_files_to_create=["greeter.py"],
        verification_actions=[VerificationAction("pytest", "tests/test_greeter.py")],
        founder_approval_id="founder_appr_001",
    )

    # 5. Verified CODE_PATCH
    if patch_text is None:
        patch_text = (
            "--- /dev/null\n"
            "+++ b/greeter.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+def greet_user(name: str) -> str:\n"
            "+    return f'Hello, {name}!'\n"
        )
    if changed_files is None:
        changed_files = ["greeter.py"]

    if dev_verifications is None:
        dev_verifications = [{
            "action": {"action_type": "pytest", "target": "tests/test_greeter.py"},
            "status": "PASS",
            "exit_code": 0,
            "stdout": "1 passed",
            "stderr": "",
            "duration_ms": 100,
        }]

    patch_task = service.create_task(project_id=project_id, title="Developer Mutation", goal="Create patch", required_roles=["developer"])
    patch_run = patch_task.create_run()
    patch_run.status = RunStatus.RUNNING.value
    patch_art = materialize_code_patch_artifact(
        base_output_dir=Path(service.output_dir),
        task=patch_task,
        run=patch_run,
        patch_text=patch_text,
        grant=grant,
        changed_files=changed_files,
        verifications=dev_verifications,
    )
    patch_run.complete(status=RunStatus.SUCCESS.value)
    patch_task.complete(status=TaskStatus.COMPLETED.value, summary="Patch created")

    # 6. QA_REPORT (from STEP 14A)
    qa_insp_task = service.create_task(project_id=project_id, title="QA Inspection", goal="Inspect patch", required_roles=["qa"])
    service.attach_input_artifact(qa_insp_task.id, prod_art.id, project_id=project_id)
    if include_ux and ux_art:
        service.attach_input_artifact(qa_insp_task.id, ux_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, patch_art.id, project_id=project_id)
    qa_insp_run = qa_insp_task.create_run()
    qa_insp_run.status = RunStatus.RUNNING.value

    recs = recommended_actions or [
        {"action_type": "pytest", "target": "tests/test_greeter.py", "purpose": "Verify greeter"}
    ]
    if qa_req_coverages is not None:
        coverages = qa_req_coverages
    elif product_reqs is not None and "REQ-2" not in product_reqs:
        coverages = [
            RequirementCoverage(requirement_id="REQ-1", status="COVERED", evidence="greet_user implemented"),
        ]
    else:
        coverages = [
            RequirementCoverage(requirement_id="REQ-1", status="COVERED", evidence="greet_user implemented"),
            RequirementCoverage(requirement_id="REQ-2", status="COVERED", evidence="ValueError on empty name implemented"),
        ]
    qa_insp_result = QAInspectionResult(
        schema_version="1.0",
        status=QAInspectionStatus.READY_FOR_QA_EXECUTION.value,
        summary="Inspection complete, ready for bounded execution.",
        requirements_coverage=coverages,
        recommended_verification_actions=[
            QARecommendedAction(action_type=r["action_type"], target=r["target"], purpose=r["purpose"])
            for r in recs
        ],
    )
    lineage_meta = {
        "product_artifact_id": prod_art.id,
        "product_sha256": prod_art.sha256,
        "ux_artifact_id": ux_art.id if ux_art else None,
        "ux_sha256": ux_art.sha256 if ux_art else None,
        "developer_plan_artifact_id": plan_art.id,
        "developer_plan_sha256": plan_art.sha256,
        "execution_grant_id": grant.grant_id,
        "code_patch_artifact_id": patch_art.id,
        "code_patch_sha256": patch_art.sha256,
        "base_commit_hash": head_commit,
        "verification_evidence": dev_verifications,
        "recommended_verification_actions": recs,
    }
    qa_report_art = materialize_qa_report_artifact(
        base_output_dir=Path(service.output_dir),
        task=qa_insp_task,
        run=qa_insp_run,
        typed_result=qa_insp_result,
        lineage_metadata=lineage_meta,
    )
    qa_insp_run.complete(status=RunStatus.SUCCESS.value)
    qa_insp_task.complete(status=TaskStatus.COMPLETED.value, summary=qa_insp_result.summary, details=qa_insp_result.to_dict())

    return {
        "project": proj,
        "product_task": prod_task,
        "product_artifact": prod_art,
        "ux_task": ux_task,
        "ux_artifact": ux_art,
        "developer_task": dev_task,
        "plan_artifact": plan_art,
        "grant": grant,
        "patch_task": patch_task,
        "patch_artifact": patch_art,
        "qa_insp_task": qa_insp_task,
        "qa_report_artifact": qa_report_art,
        "base_commit": head_commit,
    }


# ==============================================================================
# Unit & Lifecycle Tests
# ==============================================================================

def test_1_fresh_worktree_created_at_exact_base_commit(temp_git_repo):
    """1. Disposable worktree is created from exact base_commit_hash in detached mode."""
    repo, head_commit = temp_git_repo
    manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

    with manager.create_qa_worktree(base_commit_hash=head_commit, session_id="test_qa_wt_01") as session:
        assert session.worktree_path.exists()
        wt_head = resolve_repo_head_commit(session.worktree_path)
        assert wt_head == head_commit


def test_2_uncommitted_main_repo_changes_absent_from_qa_worktree(temp_git_repo):
    """2. Dirty changes in human workspace are absent from the fresh QA worktree."""
    repo, head_commit = temp_git_repo
    # Make human repo dirty
    dirty_file = repo / "uncommitted_secret.txt"
    dirty_file.write_text("dirty content", encoding="utf-8")

    manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
    with manager.create_qa_worktree(base_commit_hash=head_commit, session_id="test_qa_wt_dirty") as session:
        assert not (session.worktree_path / "uncommitted_secret.txt").exists()

    assert dirty_file.exists()


def test_3_missing_or_tampered_code_patch_rejected(temp_git_repo):
    """3. Preflight re-verification fails closed if CODE_PATCH is tampered on disk."""
    repo, head_commit = temp_git_repo
    service = CompanyService(repo_root=repo, output_dir=repo / ".runs")
    chain = setup_upstream_qa_chain(service, repo, head_commit)

    # Tamper with patch on disk
    patch_disk = repo / ".runs" / chain["patch_artifact"].path
    patch_disk.write_text("TAMPERED", encoding="utf-8")

    qa_task = service.create_task(project_id="proj-qa-exec", title="QA Exec", goal="Exec", required_roles=["qa"])
    service.attach_input_artifact(qa_task.id, chain["product_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["plan_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["patch_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["qa_report_artifact"].id)

    with pytest.raises(Exception, match="mismatch|tampered"):
        service.execute_qa_verification_task(qa_task.id)


def test_4_unverified_or_failing_code_patch_rejected(temp_git_repo):
    """4. Preflight re-verification fails closed if CODE_PATCH contains failing verification."""
    repo, head_commit = temp_git_repo
    service = CompanyService(repo_root=repo, output_dir=repo / ".runs")
    failing_veris = [{
        "action": {"action_type": "pytest", "target": "tests/test.py"},
        "status": "FAIL",
        "exit_code": 1,
        "stdout": "fail",
        "stderr": "error",
        "duration_ms": 10,
    }]
    chain = setup_upstream_qa_chain(service, repo, head_commit, dev_verifications=failing_veris)

    qa_task = service.create_task(project_id="proj-qa-exec", title="QA Exec", goal="Exec", required_roles=["qa"])
    service.attach_input_artifact(qa_task.id, chain["product_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["plan_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["patch_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["qa_report_artifact"].id)

    with pytest.raises(QAPatchIntegrityError, match="verification failed"):
        service.execute_qa_verification_task(qa_task.id)


def test_5_missing_or_tampered_qa_report_rejected(temp_git_repo):
    """5. Preflight fails closed if QA_REPORT is tampered on disk."""
    repo, head_commit = temp_git_repo
    service = CompanyService(repo_root=repo, output_dir=repo / ".runs")
    chain = setup_upstream_qa_chain(service, repo, head_commit)

    qa_rep_disk = repo / ".runs" / chain["qa_report_artifact"].path
    qa_rep_disk.write_text("TAMPERED REPORT", encoding="utf-8")

    qa_task = service.create_task(project_id="proj-qa-exec", title="QA Exec", goal="Exec", required_roles=["qa"])
    service.attach_input_artifact(qa_task.id, chain["product_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["plan_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["patch_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["qa_report_artifact"].id)

    with pytest.raises(Exception, match="mismatch|tampered"):
        service.execute_qa_verification_task(qa_task.id)


def test_6_mismatched_upstream_lineage_rejected(temp_git_repo):
    """6. Preflight fails closed if QA_REPORT references a different CODE_PATCH."""
    repo, head_commit = temp_git_repo
    service = CompanyService(repo_root=repo, output_dir=repo / ".runs")
    chain = setup_upstream_qa_chain(service, repo, head_commit)

    # Corrupt the reference in QA_REPORT metadata
    chain["qa_report_artifact"].metadata["code_patch_artifact_id"] = "different_patch_id"

    qa_task = service.create_task(project_id="proj-qa-exec", title="QA Exec", goal="Exec", required_roles=["qa"])
    service.attach_input_artifact(qa_task.id, chain["product_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["plan_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["patch_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["qa_report_artifact"].id)

    with pytest.raises(QALineageMismatchError, match="references code_patch"):
        service.execute_qa_verification_task(qa_task.id)


def test_7_patch_apply_preflight_and_application_success(temp_git_repo):
    """7. Application-owned git apply --check and git apply execute cleanly."""
    repo, head_commit = temp_git_repo
    manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

    patch_text = (
        "--- /dev/null\n"
        "+++ b/greeter.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def greet():\n"
        "+    return 'hi'\n"
    )

    with manager.create_qa_worktree(base_commit_hash=head_commit, session_id="test_qa_apply") as session:
        apply_code_patch_to_worktree(session.worktree_path, patch_text)
        assert (session.worktree_path / "greeter.py").exists()
        assert "def greet():" in (session.worktree_path / "greeter.py").read_text(encoding="utf-8")


def test_8_inapplicable_patch_fails_closed_and_cleans_up(temp_git_repo):
    """8. Inapplicable patch fails with QAPatchApplyError and cleans up."""
    repo, head_commit = temp_git_repo
    manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

    corrupt_patch = (
        "--- a/non_existent.py\n"
        "+++ b/non_existent.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-original\n"
        "+replacement\n"
    )

    with manager.create_qa_worktree(base_commit_hash=head_commit, session_id="test_qa_bad_patch") as session:
        wt_path = session.worktree_path
        with pytest.raises(QAPatchApplyError, match="preflight check failed"):
            apply_code_patch_to_worktree(session.worktree_path, corrupt_patch)

    assert not wt_path.exists()


def test_9_applied_diff_validation_matches_patch_authority(temp_git_repo):
    """9. Worktree diff corresponds exactly to CODE_PATCH metadata."""
    repo, head_commit = temp_git_repo
    manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

    patch_text = (
        "--- /dev/null\n"
        "+++ b/greeter.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def greet():\n"
        "+    return 'hi'\n"
    )
    mock_art = Artifact(
        id="art_patch_01",
        name="patch",
        artifact_type="CODE_PATCH",
        path="p.patch",
        metadata={"changed_files": ["greeter.py"]},
    )

    with manager.create_qa_worktree(base_commit_hash=head_commit, session_id="test_diff_val") as session:
        apply_code_patch_to_worktree(session.worktree_path, patch_text)
        diff_res = validate_applied_patch_diff(session, mock_art)
        assert diff_res.changed_files == ["greeter.py"]
        assert diff_res.is_empty is False


def test_10_mismatched_diff_fails_closed(temp_git_repo):
    """10. Applied patch creating unauthorized extra files fails closed."""
    repo, head_commit = temp_git_repo
    manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

    patch_text = (
        "--- /dev/null\n"
        "+++ b/greeter.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def greet():\n"
        "+    return 'hi'\n"
    )
    # Metadata only authorized app.py, but patch modified greeter.py
    mock_art = Artifact(
        id="art_patch_01",
        name="patch",
        artifact_type="CODE_PATCH",
        path="p.patch",
        metadata={"changed_files": ["app.py"]},
    )

    with manager.create_qa_worktree(base_commit_hash=head_commit, session_id="test_diff_mismatch") as session:
        apply_code_patch_to_worktree(session.worktree_path, patch_text)
        with pytest.raises(QADiffMismatchError, match="unexpected file"):
            validate_applied_patch_diff(session, mock_art)


def test_11_authorization_approves_safe_pytest_action(temp_git_repo):
    """11. Safe pytest action on existing test file is authorized and converted."""
    repo, _ = temp_git_repo
    test_file = repo / "tests" / "test_sample.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_ok(): pass\n", encoding="utf-8")

    recs = [QARecommendedAction(action_type="pytest", target="tests/test_sample.py", purpose="run test")]
    authorized, audits = authorize_and_convert_qa_actions(recs, repo)

    assert len(authorized) == 1
    assert authorized[0].action_type == "pytest"
    assert authorized[0].target == "tests/test_sample.py"
    assert audits[0].decision == QAActionAuthorizationDecision.AUTHORIZED.value


def test_12_authorization_rejects_unsupported_action_type(temp_git_repo):
    """12. Unsupported action type (bash, shell, python script) is rejected."""
    repo, _ = temp_git_repo
    recs = [QARecommendedAction(action_type="bash -c", target="test.py", purpose="run bash")]
    authorized, audits = authorize_and_convert_qa_actions(recs, repo)

    assert len(authorized) == 0
    assert audits[0].decision == QAActionAuthorizationDecision.REJECTED_UNSUPPORTED_TYPE.value


def test_13_authorization_rejects_forbidden_metacharacters(temp_git_repo):
    """13. Targets with shell metacharacters are rejected."""
    repo, _ = temp_git_repo
    recs = [QARecommendedAction(action_type="pytest", target="tests/test.py; rm -rf /", purpose="bad")]
    authorized, audits = authorize_and_convert_qa_actions(recs, repo)

    assert len(authorized) == 0
    assert audits[0].decision == QAActionAuthorizationDecision.REJECTED_FORBIDDEN_CHARS.value


def test_14_authorization_rejects_directory_traversal(temp_git_repo):
    """14. Targets with traversal markers are rejected."""
    repo, _ = temp_git_repo
    recs = [QARecommendedAction(action_type="pytest", target="../outside.py", purpose="traversal")]
    authorized, audits = authorize_and_convert_qa_actions(recs, repo)

    assert len(authorized) == 0
    assert audits[0].decision == QAActionAuthorizationDecision.REJECTED_TRAVERSAL.value


def test_15_authorization_rejects_protected_paths(temp_git_repo):
    """15. Targets in protected paths (.git, .agents, .env) are rejected."""
    repo, _ = temp_git_repo
    recs = [QARecommendedAction(action_type="pytest", target=".git/hooks/test.py", purpose="protected")]
    authorized, audits = authorize_and_convert_qa_actions(recs, repo)

    assert len(authorized) == 0
    assert audits[0].decision == QAActionAuthorizationDecision.REJECTED_PROTECTED_PATH.value


def test_16_authorization_rejects_nonexistent_target(temp_git_repo):
    """16. Target that does not physically exist in worktree is marked REJECTED_TARGET_NOT_FOUND."""
    repo, _ = temp_git_repo
    recs = [QARecommendedAction(action_type="pytest", target="tests/missing.py", purpose="missing")]
    authorized, audits = authorize_and_convert_qa_actions(recs, repo)

    assert len(authorized) == 0
    assert audits[0].decision == QAActionAuthorizationDecision.REJECTED_TARGET_NOT_FOUND.value


def test_17_authorization_enforces_budget_limit(temp_git_repo):
    """17. Actions exceeding max_actions budget are rejected."""
    repo, _ = temp_git_repo
    test_file = repo / "tests" / "test_app.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_dummy(): pass\n", encoding="utf-8")

    recs = [
        QARecommendedAction(action_type="pytest", target="tests/test_app.py", purpose=f"action {i}")
        for i in range(10)
    ]
    authorized, audits = authorize_and_convert_qa_actions(recs, repo, max_actions=3)

    assert len(authorized) <= 3
    assert audits[3].decision == QAActionAuthorizationDecision.REJECTED_BUDGET_EXCEEDED.value


def test_18_deterministic_constraint_forbids_pass_on_unavailable_action():
    """18. If a required action was rejected/unavailable, PASS is strictly FORBIDDEN -> BLOCKED."""
    agent_verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,  # Agent prematurely said PASS
        summary="Looks good to agent",
        requirements_evaluations=[],
    )
    audits = [
        QAExecutionActionAudit(
            action_type="pytest",
            target="tests/test_missing.py",
            purpose="test missing feature",
            decision=QAActionAuthorizationDecision.REJECTED_TARGET_NOT_FOUND.value,
        )
    ]
    constrained = enforce_deterministic_verdict_constraints(agent_verdict, audits, [])

    assert constrained.verdict == QAFinalVerdict.BLOCKED.value
    assert constrained.deterministic_override_applied is True
    assert "could not be executed" in constrained.override_reason


def test_19_deterministic_constraint_forbids_pass_on_execution_failure():
    """19. If an executed action failed, PASS is strictly FORBIDDEN -> FAIL."""
    agent_verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,  # Agent falsely said PASS
        summary="Claims all good",
        requirements_evaluations=[],
    )
    exec_result = VerificationExecutionResult(
        action=VerificationAction("pytest", "tests/test_app.py"),
        status=VerificationStatus.FAIL.value,
        exit_code=1,
        stdout="FAILED",
        stderr="",
        duration_ms=50,
    )
    constrained = enforce_deterministic_verdict_constraints(agent_verdict, [], [exec_result])

    assert constrained.verdict == QAFinalVerdict.FAIL.value
    assert constrained.deterministic_override_applied is True
    assert "executed verification action(s) failed" in constrained.override_reason


def test_20_deterministic_constraint_permits_pass_when_clean():
    """20. When all actions are authorized and passed, PASS is preserved."""
    agent_verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,
        summary="All verified",
        requirements_evaluations=[],
    )
    va = VerificationAction("pytest", "tests/test_app.py")
    audits = [
        QAExecutionActionAudit(
            action_type="pytest",
            target="tests/test_app.py",
            purpose="run",
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
        duration_ms=40,
    )
    constrained = enforce_deterministic_verdict_constraints(agent_verdict, audits, [exec_result])

    assert constrained.verdict == QAFinalVerdict.PASS.value
    assert constrained.deterministic_override_applied is False


def test_21_qa_verdict_schema_validation():
    """21. Strict schema validation and parsing for QAExecutionVerdictResult."""
    valid_json = json.dumps({
        "schema_version": "1.0",
        "verdict": "PASS",
        "summary": "Passed all tests",
        "requirements_evaluations": [
            {"requirement_id": "REQ-1", "status": "SATISFIED", "evidence": "test_app passed", "notes": "ok"}
        ],
        "executed_tests_summary": "1/1 passed",
        "blocking_issues": [],
        "release_recommendation": "APPROVED_FOR_RELEASE",
    })
    res = parse_and_validate_qa_verdict(valid_json, [], [])
    assert res.verdict == "PASS"
    assert len(res.requirements_evaluations) == 1

    # Invalid status rejected
    bad_status_json = json.dumps({
        "schema_version": "1.0",
        "verdict": "MAYBE",
        "summary": "Unknown status",
    })
    with pytest.raises(QAVerdictValidationError, match="Invalid final QA verdict"):
        parse_and_validate_qa_verdict(bad_status_json, [], [])


def test_22_durable_qa_execution_report_materialized(temp_git_repo):
    """22. QA_EXECUTION_REPORT artifact is materialized with exact SHA-256 and lineage."""
    repo, head_commit = temp_git_repo
    task = Task("task_exec", "proj_01", "qa", "QA Task", "Goal")
    run = task.create_run()

    verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict="PASS",
        summary="Verified successfully",
        requirements_evaluations=[
            QARequirementExecutionEvaluation(requirement_id="REQ-1", status="SATISFIED", evidence="Passed")
        ],
        executed_tests_summary="1 passed",
        release_recommendation="APPROVED_FOR_RELEASE",
    )
    lineage = {
        "product_artifact_id": "art_p1",
        "product_sha256": "p" * 64,
        "developer_plan_artifact_id": "art_plan1",
        "developer_plan_sha256": "d" * 64,
        "code_patch_artifact_id": "art_patch1",
        "code_patch_sha256": "c" * 64,
        "qa_report_artifact_id": "art_qar1",
        "qa_report_sha256": "q" * 64,
        "base_commit_hash": head_commit,
    }

    art = materialize_qa_execution_report_artifact(
        base_output_dir=repo / ".runs",
        task=task,
        run=run,
        typed_verdict=verdict,
        lineage_metadata=lineage,
    )
    assert art.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value
    assert (repo / ".runs" / art.path).exists()
    assert (repo / ".runs" / (art.path + ".meta.json")).exists()
    disk_bytes = (repo / ".runs" / art.path).read_bytes()
    assert hashlib.sha256(disk_bytes).hexdigest() == art.sha256


def test_23_and_24_worktree_cleanup_and_repo_immutability(temp_git_repo):
    """23 & 24. Worktree is removed on all exit paths and main repository remains 100% untouched."""
    repo, head_commit = temp_git_repo
    service = CompanyService(repo_root=repo, output_dir=repo / ".runs")
    chain = setup_upstream_qa_chain(service, repo, head_commit)

    initial_status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout

    qa_task = service.create_task(project_id="proj-qa-exec", title="QA Exec", goal="Exec", required_roles=["qa"])
    service.attach_input_artifact(qa_task.id, chain["product_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["plan_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["patch_artifact"].id)
    service.attach_input_artifact(qa_task.id, chain["qa_report_artifact"].id)

    # Mock runtime to return valid FAIL verdict
    mock_verdict = json.dumps({
        "schema_version": "1.0",
        "verdict": "FAIL",
        "summary": "Mock verdict FAIL",
        "requirements_evaluations": [],
        "executed_tests_summary": "0 executed",
        "blocking_issues": ["No tests"],
        "release_recommendation": "REJECTED_NEEDS_FIX",
    })
    service.runtime.execute = lambda agent, prompt, **kw: AgentExecutionResult(
        agent=agent, success=True, stdout=mock_verdict, stderr="", exit_code=0, duration_ms=50.0
    )

    run = service.execute_qa_verification_task(qa_task.id)
    assert run.status == RunStatus.SUCCESS.value
    assert qa_task.status == TaskStatus.COMPLETED.value

    # Verify no worktrees remain
    worktrees = list((repo / ".runs" / "worktrees").glob("*"))
    assert len(worktrees) == 0

    # Verify main repo is 100% unchanged
    after_status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True).stdout
    assert initial_status == after_status
    assert resolve_repo_head_commit(repo) == head_commit


# ==============================================================================
# Live Proofs with Real Antigravity Runtime (agy --agent qa)
# ==============================================================================

def test_live_qa_agent_failing_proof():
    """Live Proof (Gap / Failure): Real QA Agent evaluates incomplete patch and issues FAIL or BLOCKED."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        run_git(["init"], cwd=repo)
        run_git(["config", "user.name", "Live Runner"], cwd=repo)
        run_git(["config", "user.email", "live@example.com"], cwd=repo)
        (repo / "README.md").write_text("# Target Repo Baseline\n", encoding="utf-8")
        company_agents = Path(__file__).resolve().parent.parent / ".agents"
        if company_agents.exists():
            shutil.copytree(company_agents, repo / ".agents")
        run_git(["add", "."], cwd=repo)
        run_git(["commit", "-m", "Baseline commit"], cwd=repo)
        head_commit = resolve_repo_head_commit(repo)

        service = CompanyService(repo_root=repo, output_dir=repo / ".runs")

        # Patch only implements greet_user, omits REQ-2 (reject empty name)
        # Recommended action points to tests/test_empty_name.py which DOES NOT EXIST
        patch_text = (
            "--- /dev/null\n"
            "+++ b/greeter.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+def greet_user(name: str) -> str:\n"
            "+    return f'Hello, {name}!'\n"
        )
        recs = [
            {"action_type": "pytest", "target": "tests/test_empty_name.py", "purpose": "verify empty name raises ValueError"}
        ]
        chain = setup_upstream_qa_chain(
            service,
            repo,
            head_commit,
            patch_text=patch_text,
            recommended_actions=recs,
        )

        qa_task = service.create_task(
            project_id="proj-qa-exec",
            title="Live QA Execution: Incomplete Greeter",
            goal="Execute QA verification and issue final release verdict",
            required_roles=["qa"],
        )
        service.attach_input_artifact(qa_task.id, chain["product_artifact"].id)
        service.attach_input_artifact(qa_task.id, chain["plan_artifact"].id)
        service.attach_input_artifact(qa_task.id, chain["patch_artifact"].id)
        service.attach_input_artifact(qa_task.id, chain["qa_report_artifact"].id)

        # Real agy runtime executes
        run = service.execute_qa_verification_task(qa_task.id)
        if run.status == RunStatus.FAILED.value and (
            "exit code 3" in (run.error or "")
            or "RESOURCE_EXHAUSTED" in (run.error or "")
            or "429" in (run.error or "")
        ):
            pytest.skip("External Antigravity provider unavailable / quota exhausted (HTTP 429)")
        assert run.status == RunStatus.SUCCESS.value
        assert qa_task.status == TaskStatus.COMPLETED.value
        assert qa_task.result is not None

        details = qa_task.result.details
        assert details["schema_version"] == "1.0"
        # Since required test was missing / could not execute, verdict MUST be BLOCKED or FAIL (PASS forbidden)
        assert details["verdict"] in {QAFinalVerdict.BLOCKED.value, QAFinalVerdict.FAIL.value}
        assert details["verdict"] != QAFinalVerdict.PASS.value

        # Check durable QA_EXECUTION_REPORT
        exec_reports = [a for a in run.artifacts if a.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value]
        assert len(exec_reports) == 1
        assert (repo / ".runs" / exec_reports[0].path).exists()


def test_live_qa_agent_successful_proof():
    """Live Proof (Success): Real QA Agent evaluates fully implemented and verified patch and issues PASS."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir) / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        run_git(["init"], cwd=repo)
        run_git(["config", "user.name", "Live Runner"], cwd=repo)
        run_git(["config", "user.email", "live@example.com"], cwd=repo)

        # Initialize tests/test_greeter.py in base commit so the test file physically exists!
        tests_dir = repo / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_greeter.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).parent.parent))\n"
            "from greeter import greet_user\n\n"
            "def test_greet_user():\n"
            "    assert greet_user('World') == 'Hello, World!'\n",
            encoding="utf-8",
        )
        (repo / "README.md").write_text("# Target Repo Baseline\n", encoding="utf-8")
        company_agents = Path(__file__).resolve().parent.parent / ".agents"
        if company_agents.exists():
            shutil.copytree(company_agents, repo / ".agents")
        run_git(["add", "."], cwd=repo)
        run_git(["commit", "-m", "Baseline commit with tests"], cwd=repo)
        head_commit = resolve_repo_head_commit(repo)

        service = CompanyService(repo_root=repo, output_dir=repo / ".runs")

        # Patch implements greet_user cleanly
        patch_text = (
            "--- /dev/null\n"
            "+++ b/greeter.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+def greet_user(name: str) -> str:\n"
            "+    return f'Hello, {name}!'\n"
        )
        recs = [
            {"action_type": "pytest", "target": "tests/test_greeter.py", "purpose": "verify greet_user"}
        ]
        chain = setup_upstream_qa_chain(
            service,
            repo,
            head_commit,
            patch_text=patch_text,
            recommended_actions=recs,
            product_reqs="REQ-1: Greet known user by name returning 'Hello, {name}!'",
        )

        qa_task = service.create_task(
            project_id="proj-qa-exec",
            title="Live QA Execution: Passing Greeter",
            goal="Execute QA verification and issue final release verdict",
            required_roles=["qa"],
        )
        service.attach_input_artifact(qa_task.id, chain["product_artifact"].id)
        service.attach_input_artifact(qa_task.id, chain["plan_artifact"].id)
        service.attach_input_artifact(qa_task.id, chain["patch_artifact"].id)
        service.attach_input_artifact(qa_task.id, chain["qa_report_artifact"].id)

        # Real agy runtime executes
        run = service.execute_qa_verification_task(qa_task.id)
        if run.status == RunStatus.FAILED.value and (
            "exit code 3" in (run.error or "")
            or "RESOURCE_EXHAUSTED" in (run.error or "")
            or "429" in (run.error or "")
        ):
            pytest.skip("External Antigravity provider unavailable / quota exhausted (HTTP 429)")
        assert run.status == RunStatus.SUCCESS.value
        assert qa_task.status == TaskStatus.COMPLETED.value
        assert qa_task.result is not None

        details = qa_task.result.details
        assert details["schema_version"] == "1.0"
        # Test passed cleanly -> PASS verdict
        assert details["verdict"] == QAFinalVerdict.PASS.value

        # Check durable QA_EXECUTION_REPORT
        exec_reports = [a for a in run.artifacts if a.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value]
        assert len(exec_reports) == 1
        assert (repo / ".runs" / exec_reports[0].path).exists()
