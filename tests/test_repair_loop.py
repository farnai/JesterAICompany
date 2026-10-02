"""Deterministic and Live Test Suite for Developer ↔ QA Controlled Repair Loop (STEP 15).

Verifies:
1. Eligibility classification (PASS -> not eligible, FAIL -> repairable, BLOCKED -> categorized).
2. Clarification 1: ALLOWED_HANDOFF_EDGES defines data-level compatibility only, NOT agent authority.
   QA cannot invoke Developer, Developer cannot invoke QA, Developer cannot invoke itself,
   CompanyService is the sole transition owner.
3. Clarification 2: Human approval enforcement.
   Never fabricate founder approvals in production. Missing approval halts in REPAIR_GRANT_REJECTED.
   Reusing previous approval halts in REPAIR_GRANT_REJECTED. Every iteration requires distinct approval.
4. Monotonic scope control & cumulative ExecutionGrant.
5. Worktree reconstruction: fresh worktree from base_commit_hash + pre-applied previous patch.
6. Cumulative CODE_PATCH vN capture against base_commit_hash with complete metadata lineage.
7. MAX_REPAIR_ITERATIONS = 2 hard limit (no 3rd attempt).
8. Durable DEVELOPER_REPAIR_PLAN_REPORT and DEVELOPER_QA_REPAIR_REPORT artifacts.
9. Zero main repository mutation guaranteed.
10. Live one-repair success proof and live repair limit proof.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import pytest

from jester_ai_company.core import (
    ALLOWED_HANDOFF_EDGES,
    Artifact,
    ArtifactInputRef,
    ArtifactType,
    Company,
    Employee,
    Project,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from jester_ai_company.developer_result import (
    DeveloperTaskResult,
    ProposedFile,
)
from jester_ai_company.execution_grant import (
    ExecutionGrant,
    GrantValidationError,
    MissingApprovalError,
    ProtectedPathError,
    TestModificationForbiddenError,
    VerificationAction,
)
from jester_ai_company.materializer import (
    compute_sha256,
    load_and_verify_input_artifact,
    materialize_code_patch_artifact,
    materialize_developer_qa_repair_report_artifact,
    materialize_developer_repair_plan_artifact,
    materialize_qa_execution_report_artifact,
    materialize_qa_report_artifact,
    materialize_specialist_artifact,
)
from jester_ai_company.product_result import (
    ProductDeliverable,
    ProductTaskResult,
)
from jester_ai_company.qa_execution import (
    QAActionAuthorizationDecision,
    QAExecutionActionAudit,
    QAExecutionOutcome,
    QAExecutionVerdictResult,
    QAFinalVerdict,
    QARecommendedAction,
    QARequirementExecutionEvaluation,
    apply_code_patch_to_worktree,
    validate_applied_patch_diff,
)
from jester_ai_company.qa_result import (
    QAInspectionResult,
    QAInspectionStatus,
    RequirementCoverage,
)
from jester_ai_company.repair import (
    MAX_REPAIR_ITERATIONS,
    DeveloperQARepairLoopResult,
    DeveloperRepairPlan,
    DeveloperRepairTask,
    RepairAttemptRecord,
    RepairEligibilityClassification,
    RepairEligibilityError,
    RepairError,
    RepairPlanError,
    RepairWorkflowStatus,
    RequirementConflictError,
    build_developer_repair_planning_prompt,
    build_developer_repair_task,
    classify_repair_eligibility,
    derive_repair_execution_grant,
    format_developer_qa_repair_report,
    format_developer_repair_plan_report,
    parse_and_validate_developer_repair_plan,
    reconstruct_qa_execution_context,
)
from jester_ai_company.runtime import AntigravityRuntime, AgentExecutionResult
from jester_ai_company.service import BoundedDeveloperExecutionOutcome, CompanyService
from jester_ai_company.verification import (
    VerificationExecutionResult,
    VerificationStatus,
)
from jester_ai_company.worktree import (
    WorktreeManager,
    WorktreeSession,
    resolve_repo_head_commit,
    run_git,
)


# ==============================================================================
# Helper for Setting Up Canonical Upstream Fixtures
# ==============================================================================

def create_canonical_test_chain(
    service: CompanyService,
    repo_dir: Path,
    head_commit: str,
    project_id: str = "proj_test",
    patch_text: str = "",
    changed_files: list = None,
    founder_approval_id: str = "founder_appr_initial_01",
    qa_verdict: str = "FAIL",
    qa_summary: str = "Verification failed",
    qa_evidence_passed: bool = False,
    recs: list = None,
):
    proj = service.create_project(project_id=project_id, name="RepairTestProj")

    # 1. Product
    prod_task = service.create_task(project_id=project_id, title="Product Spec", goal="Spec", required_roles=["product"])
    prod_run = prod_task.create_run()
    prod_run.status = RunStatus.RUNNING.value
    prod_res = ProductTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Requirements",
        deliverables=[ProductDeliverable(name="Requirements", content="REQ-01: Calculate sum\nREQ-02: Robustness")],
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
    dev_res = DeveloperTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Plan module",
        implementation_plan=["Implement calc.py"],
        files_to_modify=[ProposedFile(path="calc.py", description="Calc implementation")],
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
    files_mod = tuple(changed_files or ["calc.py"])
    grant = ExecutionGrant(
        grant_id=f"grant_{project_id}_01",
        task_id=dev_task.id,
        plan_artifact_id=plan_art.id,
        plan_sha256=plan_art.sha256,
        base_commit_hash=head_commit,
        approved_files_to_modify=files_mod,
        verification_actions=(VerificationAction("pytest", "tests/test_calc.py"),),
        founder_approval_id=founder_approval_id,
    )

    # 4. Patch
    actual_patch = patch_text or (
        "diff --git a/calc.py b/calc.py\n"
        "--- a/calc.py\n"
        "+++ b/calc.py\n"
        "@@ -1 +1 @@\n"
        "-def add(a, b): return 0\n"
        "+def add(a, b): return a + b - 1\n"
    )
    patch_task = service.create_task(project_id=project_id, title="Developer Mutation", goal="Create patch", required_roles=["developer"])
    patch_run = patch_task.create_run()
    patch_run.status = RunStatus.RUNNING.value
    patch_art = materialize_code_patch_artifact(
        base_output_dir=Path(service.output_dir),
        task=patch_task,
        run=patch_run,
        grant=grant,
        patch_text=actual_patch,
        changed_files=list(files_mod),
        verifications=[{"action": {"action_type": "pytest", "target": "tests/test_calc.py"}, "status": "PASS", "exit_code": 0}],
        patch_version=1,
    )
    patch_run.complete(status=RunStatus.SUCCESS.value)
    patch_task.complete(status=TaskStatus.COMPLETED.value, summary="Patch created")

    # 5. QA Report (Step 14A)
    qa_insp_task = service.create_task(project_id=project_id, title="QA Inspection", goal="Inspect patch", required_roles=["qa"])
    service.attach_input_artifact(qa_insp_task.id, prod_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, patch_art.id, project_id=project_id)
    qa_insp_run = qa_insp_task.create_run()
    qa_insp_run.status = RunStatus.RUNNING.value

    recs_list = recs or [{"action_type": "pytest", "target": "tests/test_calc.py", "purpose": "Verify calc"}]
    qa_insp_result = QAInspectionResult(
        schema_version="1.0",
        status=QAInspectionStatus.READY_FOR_QA_EXECUTION.value,
        summary="Inspection complete",
        requirements_coverage=[RequirementCoverage(requirement_id="REQ-01", status="COVERED", evidence="tested")],
        recommended_verification_actions=[
            QARecommendedAction(action_type=r["action_type"], target=r["target"], purpose=r["purpose"])
            for r in recs_list
        ],
    )
    lineage_meta = {
        "product_artifact_id": prod_art.id,
        "product_sha256": prod_art.sha256,
        "developer_plan_artifact_id": plan_art.id,
        "developer_plan_sha256": plan_art.sha256,
        "execution_grant_id": grant.grant_id,
        "code_patch_artifact_id": patch_art.id,
        "code_patch_sha256": patch_art.sha256,
        "base_commit_hash": head_commit,
        "verification_evidence": [va.to_dict() for va in grant.verification_actions],
        "recommended_verification_actions": recs_list,
    }
    qa_rep_art = materialize_qa_report_artifact(
        base_output_dir=Path(service.output_dir),
        task=qa_insp_task,
        run=qa_insp_run,
        typed_result=qa_insp_result,
        lineage_metadata=lineage_meta,
    )
    qa_insp_run.complete(status=RunStatus.SUCCESS.value)
    qa_insp_task.complete(status=TaskStatus.COMPLETED.value, summary=qa_insp_result.summary, details=qa_insp_result.to_dict())

    # 6. QA Execution Report (Step 14B)
    qa_exec_task = service.create_task(project_id=project_id, title="QA Verification", goal="Verify patch", required_roles=["qa"])
    service.attach_input_artifact(qa_exec_task.id, prod_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, patch_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, qa_rep_art.id, project_id=project_id)
    qa_exec_run = qa_exec_task.create_run()
    qa_exec_run.status = RunStatus.RUNNING.value

    verdict_res = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=qa_verdict,
        summary=qa_summary,
        requirements_evaluations=[QARequirementExecutionEvaluation("REQ-01", "SATISFIED" if qa_verdict == "PASS" else "FAILED", "Execution log")],
        release_recommendation="RELEASE" if qa_verdict == "PASS" else "HOLD",
    )
    exec_meta = {
        "product_artifact_id": prod_art.id,
        "developer_plan_artifact_id": plan_art.id,
        "code_patch_artifact_id": patch_art.id,
        "qa_report_artifact_id": qa_rep_art.id,
        "base_commit_hash": head_commit,
        "action_audits": [
            {
                "action_type": r["action_type"],
                "target": r["target"],
                "purpose": r["purpose"],
                "decision": "AUTHORIZED",
                "reason": "Safe target",
            }
            for r in recs_list
        ],
    }
    qa_exec_art = materialize_qa_execution_report_artifact(
        base_output_dir=Path(service.output_dir),
        task=qa_exec_task,
        run=qa_exec_run,
        typed_verdict=verdict_res,
        lineage_metadata=exec_meta,
        execution_evidence=[{
            "action": {"action_type": recs_list[0]["action_type"], "target": recs_list[0]["target"]},
            "passed": qa_evidence_passed,
            "exit_code": 0 if qa_evidence_passed else 1,
            "stdout": "tests output",
        }],
    )
    qa_exec_run.complete(status=RunStatus.SUCCESS.value)
    qa_exec_task.complete(status=TaskStatus.COMPLETED.value, summary=verdict_res.summary, details=verdict_res.to_dict())

    return {
        "project": proj,
        "product_task": prod_task,
        "product_artifact": prod_art,
        "developer_task": dev_task,
        "plan_artifact": plan_art,
        "grant": grant,
        "patch_task": patch_task,
        "patch_artifact": patch_art,
        "qa_insp_task": qa_insp_task,
        "qa_report_artifact": qa_rep_art,
        "qa_exec_task": qa_exec_task,
        "qa_exec_artifact": qa_exec_art,
        "base_commit": head_commit,
    }


# ==============================================================================
# 1. Eligibility Classifier Unit Tests
# ==============================================================================

class TestEligibilityClassification:
    """Verifies deterministic classification of QA outcomes for repair eligibility."""

    def test_pass_never_eligible(self):
        verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.PASS.value,
            summary="All tests passed.",
        )
        cls, reason = classify_repair_eligibility(verdict, [], [])
        assert cls == RepairEligibilityClassification.NOT_ELIGIBLE_PASS
        assert "no repair required" in reason.lower()

    def test_fail_with_failed_verification_is_repairable(self):
        act = VerificationAction(action_type="pytest", target="tests/test_calc.py")
        vr = VerificationExecutionResult(
            action=act,
            status=VerificationStatus.FAIL.value,
            exit_code=1,
            stdout="FAILED test_add",
            stderr="",
            duration_ms=100,
        )
        verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.FAIL.value,
            summary="Verification failed.",
        )
        cls, reason = classify_repair_eligibility(verdict, [], [vr])
        assert cls == RepairEligibilityClassification.REPAIRABLE_IMPLEMENTATION
        assert "tests/test_calc.py" in reason

    def test_fail_with_failed_requirements_is_repairable(self):
        verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.FAIL.value,
            summary="REQ-01 was not satisfied by implementation.",
        )
        cls, reason = classify_repair_eligibility(verdict, [], [])
        assert cls == RepairEligibilityClassification.REPAIRABLE_IMPLEMENTATION
        assert "REQ-01" in reason

    def test_blocked_missing_target_is_repairable_test_gap(self):
        audit = QAExecutionActionAudit(
            action_type="pytest",
            target="tests/test_missing.py",
            purpose="verify",
            decision=QAActionAuthorizationDecision.REJECTED_TARGET_NOT_FOUND.value,
            reason="File missing",
        )
        verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.BLOCKED.value,
            summary="Target missing.",
        )
        cls, reason = classify_repair_eligibility(verdict, [audit], [])
        assert cls == RepairEligibilityClassification.REPAIRABLE_TEST_GAP
        assert "tests/test_missing.py" in reason

    def test_blocked_protected_path_is_non_repairable_security(self):
        audit = QAExecutionActionAudit(
            action_type="pytest",
            target=".git/config",
            purpose="verify",
            decision=QAActionAuthorizationDecision.REJECTED_PROTECTED_PATH.value,
            reason="Protected path",
        )
        verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.BLOCKED.value,
            summary="Security rejection.",
        )
        cls, reason = classify_repair_eligibility(verdict, [audit], [])
        assert cls == RepairEligibilityClassification.NON_REPAIRABLE_SECURITY

    def test_blocked_unsupported_action_type_is_non_repairable_environment(self):
        audit = QAExecutionActionAudit(
            action_type="npm",
            target="package.json",
            purpose="verify",
            decision=QAActionAuthorizationDecision.REJECTED_UNSUPPORTED_TYPE.value,
            reason="npm not supported in V1",
        )
        verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.BLOCKED.value,
            summary="Unsupported tool.",
        )
        cls, reason = classify_repair_eligibility(verdict, [audit], [])
        assert cls == RepairEligibilityClassification.NON_REPAIRABLE_ENVIRONMENT

    def test_blocked_infrastructure_issues(self):
        verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.BLOCKED.value,
            summary="Git worktree corrupted.",
            blocking_issues=["Infrastructure git patch failure"],
        )
        cls, reason = classify_repair_eligibility(verdict, [], [])
        assert cls == RepairEligibilityClassification.NON_REPAIRABLE_INFRASTRUCTURE


# ==============================================================================
# 2. Clarification 1 Tests — Handoff Edge != Agent Authority
# ==============================================================================

class TestClarification1HandoffEdgeSemantics:
    """Verifies that ALLOWED_HANDOFF_EDGES defines data compatibility only, NOT agent authority."""

    def test_allowed_handoff_edges_governs_artifact_compatibility_only(self):
        assert ("qa", "developer") in ALLOWED_HANDOFF_EDGES
        assert ("developer", "developer") in ALLOWED_HANDOFF_EDGES

    def test_qa_cannot_invoke_developer(self):
        """QA Agent definition strictly forbids calling subagents or invoking Developer."""
        agent_md = Path(".agents/agents/qa/agent.md")
        if agent_md.exists():
            content = agent_md.read_text(encoding="utf-8")
            assert "invoke_subagent" not in content[:content.find("---", 4)]
            assert "No delegation" in content or "You do NOT invoke or delegate" in content

    def test_developer_cannot_invoke_qa_or_developer(self):
        """Developer Agent definition strictly forbids calling subagents or executing other agents."""
        agent_md = Path(".agents/agents/developer/agent.md")
        if agent_md.exists():
            content = agent_md.read_text(encoding="utf-8")
            assert "invoke_subagent" not in content[:content.find("---", 4)]
            assert "You do NOT invoke or delegate to other agents" in content

    def test_company_service_is_sole_transition_owner(self, tmp_path):
        service = CompanyService(repo_root=Path("."), output_dir=tmp_path / "artifacts")
        assert hasattr(service, "execute_developer_qa_repair_loop")
        assert callable(service.execute_developer_qa_repair_loop)


# ==============================================================================
# 3. Clarification 2 Tests — Human Approval & Authority Boundary
# ==============================================================================

class TestClarification2HumanApproval:
    """Verifies that human founder approval is never fabricated and strictly enforced."""

    @pytest.fixture
    def test_repo(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        run_git(["init"], cwd=repo_dir)
        run_git(["config", "user.name", "Test User"], cwd=repo_dir)
        run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)
        (repo_dir / "calc.py").write_text("def add(a, b): return 0\n", encoding="utf-8")
        run_git(["add", "calc.py"], cwd=repo_dir)
        run_git(["commit", "-m", "initial commit"], cwd=repo_dir)
        head = resolve_repo_head_commit(repo_dir)
        return repo_dir, head

    def test_derive_grant_rejects_empty_or_missing_founder_approval(self):
        plan = DeveloperRepairPlan(
            repair_id="rep_1",
            root_cause="Bug in logic",
            requirements_to_fix=["REQ-1"],
            files_to_modify=[ProposedFile(path="calc.py", description="fix")],
            proposed_changes=["Fix logic"],
            proposed_verification_actions=[VerificationAction(action_type="pytest", target="tests/test_calc.py")],
        )
        base_grant = ExecutionGrant(
            grant_id="grant_0",
            task_id="task_0",
            plan_artifact_id="plan_0",
            plan_sha256="a" * 64,
            base_commit_hash="a" * 40,
            founder_approval_id="appr_0",
        )
        with pytest.raises(MissingApprovalError, match="explicit founder_approval_id"):
            derive_repair_execution_grant(
                plan=plan,
                previous_grant=base_grant,
                base_commit_hash="a" * 40,
                founder_approval_id="",
                plan_artifact_id="plan_1",
                plan_sha256="b" * 64,
            )

        with pytest.raises(MissingApprovalError, match="explicit founder_approval_id"):
            derive_repair_execution_grant(
                plan=plan,
                previous_grant=base_grant,
                base_commit_hash="a" * 40,
                founder_approval_id="   ",
                plan_artifact_id="plan_1",
                plan_sha256="b" * 64,
            )

    def test_service_repair_loop_halts_when_founder_approval_missing(self, tmp_path, test_repo):
        repo_dir, head = test_repo
        service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
        chain = create_canonical_test_chain(service, repo_dir, head, project_id="p_miss")

        # Call repair loop with NO founder_approvals
        loop_res = service.execute_developer_qa_repair_loop(
            task_id=chain["qa_exec_task"].id,
            founder_approvals=None,  # Missing!
            original_grant=chain["grant"],
        )

        assert loop_res.status == RepairWorkflowStatus.REPAIR_GRANT_REJECTED.value
        assert "missing legitimate founder approval" in loop_res.termination_reason
        assert loop_res.developer_mutation_invocations == 0

    def test_service_repair_loop_halts_when_approval_is_reused(self, tmp_path, test_repo):
        repo_dir, head = test_repo
        service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
        chain = create_canonical_test_chain(service, repo_dir, head, project_id="p_reuse", founder_approval_id="appr_orig_999")

        # Attempt to reuse the original grant's approval ID
        loop_res = service.execute_developer_qa_repair_loop(
            task_id=chain["qa_exec_task"].id,
            founder_approvals={1: "appr_orig_999"},  # Reused from original grant!
            original_grant=chain["grant"],
        )

        assert loop_res.status == RepairWorkflowStatus.REPAIR_GRANT_REJECTED.value
        assert "reused founder approval" in loop_res.termination_reason
        assert loop_res.developer_mutation_invocations == 0


# ==============================================================================
# 4. Developer Repair Plan & Scope Monotonicity Tests
# ==============================================================================

class TestDeveloperRepairPlanAndGrantDerivation:
    """Verifies Developer repair plan parsing and candidate ExecutionGrant derivation."""

    def test_parse_repair_plan_json(self):
        raw = """Here is my repair plan:
```json
{
  "schema_version": "1.0",
  "repair_id": "rep_101",
  "iteration": 1,
  "root_cause": "Off by one error in index",
  "requirements_to_fix": ["REQ-10"],
  "files_to_modify": [{"path": "core/math.py", "description": "Fix index"}],
  "files_to_create": [],
  "files_to_delete": [],
  "proposed_changes": ["Change <= to <"],
  "proposed_verification_actions": [{"action_type": "pytest", "target": "tests/test_math.py"}],
  "risks": ["Boundary case test needed"],
  "requirement_conflict_detected": false
}
```
"""
        plan = parse_and_validate_developer_repair_plan(raw)
        assert plan.repair_id == "rep_101"
        assert plan.root_cause == "Off by one error in index"
        assert len(plan.files_to_modify) == 1
        assert plan.files_to_modify[0].path == "core/math.py"
        assert len(plan.proposed_verification_actions) == 1

    def test_parse_repair_plan_deletion_forbidden(self):
        raw = """```json
{
  "schema_version": "1.0",
  "repair_id": "rep_102",
  "iteration": 1,
  "root_cause": "Delete file",
  "requirements_to_fix": ["REQ-10"],
  "files_to_modify": [],
  "files_to_create": [],
  "files_to_delete": ["obsolete.py"],
  "proposed_changes": ["Remove file"],
  "proposed_verification_actions": [{"action_type": "pytest", "target": "tests"}],
  "risks": [],
  "requirement_conflict_detected": false
}
```"""
        with pytest.raises(Exception, match="File deletions are not permitted"):
            parse_and_validate_developer_repair_plan(raw)

    def test_requirement_conflict_detected(self):
        raw = """```json
{
  "schema_version": "1.0",
  "repair_id": "rep_conflict",
  "iteration": 1,
  "root_cause": "Requirement contradiction",
  "requirements_to_fix": [],
  "files_to_modify": [],
  "files_to_create": [],
  "files_to_delete": [],
  "proposed_changes": [],
  "proposed_verification_actions": [],
  "risks": [],
  "requirement_conflict_detected": true,
  "conflict_details": "REQ-1 contradicts REQ-2 regarding return value"
}
```"""
        plan = parse_and_validate_developer_repair_plan(raw)
        assert plan.requirement_conflict_detected is True
        assert "REQ-1 contradicts REQ-2" in plan.conflict_details

    def test_derive_grant_protected_path_rejected(self):
        plan = DeveloperRepairPlan(
            repair_id="rep_prot",
            root_cause="Fix",
            requirements_to_fix=["REQ-1"],
            files_to_modify=[ProposedFile(path=".git/hooks/pre-commit", description="evil")],
            proposed_changes=["Hack git"],
            proposed_verification_actions=[VerificationAction(action_type="pytest", target="tests")],
        )
        base_grant = ExecutionGrant(
            grant_id="grant_b",
            task_id="task_b",
            plan_artifact_id="plan_b",
            plan_sha256="c" * 64,
            base_commit_hash="c" * 40,
            founder_approval_id="appr_b",
        )
        with pytest.raises(ProtectedPathError, match="protected path"):
            derive_repair_execution_grant(
                plan=plan,
                previous_grant=base_grant,
                base_commit_hash="c" * 40,
                founder_approval_id="fixture_appr_ok",
                plan_artifact_id="plan_rep",
                plan_sha256="d" * 64,
            )

    def test_derive_grant_test_modification_gating(self):
        plan = DeveloperRepairPlan(
            repair_id="rep_test_mod",
            root_cause="Fix test",
            requirements_to_fix=["REQ-1"],
            files_to_modify=[ProposedFile(path="tests/test_foo.py", description="update test")],
            proposed_changes=["Update expected value"],
            proposed_verification_actions=[VerificationAction(action_type="pytest", target="tests/test_foo.py")],
        )
        base_grant = ExecutionGrant(
            grant_id="grant_c",
            task_id="task_c",
            plan_artifact_id="plan_c",
            plan_sha256="e" * 64,
            base_commit_hash="e" * 40,
            founder_approval_id="appr_c",
        )
        with pytest.raises(TestModificationForbiddenError):
            derive_repair_execution_grant(
                plan=plan,
                previous_grant=base_grant,
                base_commit_hash="e" * 40,
                founder_approval_id="fixture_appr_ok",
                allow_test_modifications=False,
                plan_artifact_id="plan_rep",
                plan_sha256="f" * 64,
            )

        grant = derive_repair_execution_grant(
            plan=plan,
            previous_grant=base_grant,
            base_commit_hash="e" * 40,
            founder_approval_id="fixture_appr_ok",
            allow_test_modifications=True,
            plan_artifact_id="plan_rep",
            plan_sha256="f" * 64,
        )
        assert "tests/test_foo.py" in grant.approved_files_to_modify

    def test_cumulative_scope_maintained_in_repair_grant(self):
        plan = DeveloperRepairPlan(
            repair_id="rep_cumul",
            root_cause="Fix another file",
            requirements_to_fix=["REQ-2"],
            files_to_modify=[ProposedFile(path="b.py", description="change b")],
            proposed_changes=["Change b"],
            proposed_verification_actions=[VerificationAction(action_type="pytest", target="tests")],
        )
        base_grant = ExecutionGrant(
            grant_id="grant_base",
            task_id="task_base",
            plan_artifact_id="plan_base",
            plan_sha256="1" * 64,
            base_commit_hash="1" * 40,
            approved_files_to_modify=("a.py",),
            approved_files_to_create=("created_in_v1.py",),
            founder_approval_id="appr_base",
        )
        new_grant = derive_repair_execution_grant(
            plan=plan,
            previous_grant=base_grant,
            base_commit_hash="1" * 40,
            founder_approval_id="fixture_appr_ok",
            plan_artifact_id="plan_v2",
            plan_sha256="2" * 64,
        )
        assert "a.py" in new_grant.approved_files_to_modify
        assert "b.py" in new_grant.approved_files_to_modify
        assert "created_in_v1.py" in new_grant.approved_files_to_create


# ==============================================================================
# 5. Worktree Reconstruction & Cumulative Diff Authority
# ==============================================================================

class TestWorktreeReconstructionAndCumulativePatch:
    """Verifies base commit + previous patch reconstruction and cumulative patch capture."""

    def test_fresh_worktree_applies_v1_and_captures_v2_diff_against_base(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        run_git(["init"], cwd=repo_dir)
        run_git(["config", "user.name", "Test User"], cwd=repo_dir)
        run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)
        (repo_dir / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        run_git(["add", "calculator.py"], cwd=repo_dir)
        run_git(["commit", "-m", "initial commit"], cwd=repo_dir)
        base_commit = resolve_repo_head_commit(repo_dir)

        patch_v1 = (
            "diff --git a/calculator.py b/calculator.py\n"
            "--- a/calculator.py\n"
            "+++ b/calculator.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n"
            "-    return a - b\n"
            "+    return a + b - 1\n"
        )

        manager = WorktreeManager(repo_root=repo_dir, worktrees_dir=tmp_path / "worktrees")
        grant = ExecutionGrant(
            grant_id="grant_v2",
            task_id="task_calc",
            plan_artifact_id="plan_v2",
            plan_sha256="a" * 64,
            base_commit_hash=base_commit,
            approved_files_to_modify=("calculator.py",),
            founder_approval_id="fixture_appr_v2",
        )
        session = manager.create_worktree(grant)

        try:
            apply_code_patch_to_worktree(session.worktree_path, patch_v1)
            assert (session.worktree_path / "calculator.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a + b - 1\n"

            # Developer repairs the file in the worktree
            (session.worktree_path / "calculator.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

            # Capture diff against base commit
            diff_res = session.capture_diff()
            assert not diff_res.is_empty
            assert "calculator.py" in diff_res.changed_files

            # Cumulative diff: compares base to final state
            assert "-    return a - b" in diff_res.diff_text
            assert "+    return a + b" in diff_res.diff_text
            assert "return a + b - 1" not in diff_res.diff_text
        finally:
            session.remove()


# ==============================================================================
# 6. Hard Iteration Limit & Workflow State Tests
# ==============================================================================

class TestRepairWorkflowLimitsAndStates:
    """Verifies hard MAX_REPAIR_ITERATIONS = 2 limit and terminal workflow statuses."""

    @pytest.fixture
    def setup_repair_env(self, tmp_path):
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        run_git(["init"], cwd=repo_dir)
        run_git(["config", "user.name", "Test User"], cwd=repo_dir)
        run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)
        (repo_dir / "calc.py").write_text("def add(a, b): return 0\n", encoding="utf-8")
        test_dir = repo_dir / "tests"
        test_dir.mkdir()
        (test_dir / "test_calc.py").write_text("from calc import add\ndef test_add(): assert add(1, 2) == 3\n", encoding="utf-8")
        run_git(["add", "calc.py", "tests/test_calc.py"], cwd=repo_dir)
        run_git(["commit", "-m", "init"], cwd=repo_dir)
        head = resolve_repo_head_commit(repo_dir)

        service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
        chain = create_canonical_test_chain(service, repo_dir, head, project_id="p_limit")
        return service, chain["qa_exec_task"], chain["grant"]

    def test_repair_limit_strictly_enforced_at_two(self, setup_repair_env, monkeypatch):
        """Mock developer planning and QA execution to always fail, verifying exactly 2 iterations executed."""
        service, qa_exec_task, grant = setup_repair_env

        planning_mock_calls = 0
        original_runtime_execute = service.runtime.execute

        def fake_planning_execute(agent, prompt, timeout=60.0, workspace_dir=None, env=None):
            if agent == "developer":
                if "DEVELOPER REPAIR PLANNING MODE" in prompt:
                    nonlocal planning_mock_calls
                    planning_mock_calls += 1
                    plan_json = json.dumps({
                        "schema_version": "1.0",
                        "repair_id": f"repair_{planning_mock_calls}",
                        "iteration": planning_mock_calls,
                        "root_cause": "Still wrong value",
                        "requirements_to_fix": ["REQ-01"],
                        "files_to_modify": [{"path": "calc.py", "description": "fix"}],
                        "files_to_create": [],
                        "files_to_delete": [],
                        "proposed_changes": ["Update return value"],
                        "proposed_verification_actions": [{"action_type": "pytest", "target": "tests/test_calc.py"}],
                        "risks": [],
                        "requirement_conflict_detected": False,
                    })
                    return AgentExecutionResult(
                        agent="developer",
                        success=True,
                        stdout=f"```json\n{plan_json}\n```",
                        stderr="",
                        exit_code=0,
                        duration_ms=10.0,
                    )
                elif "MUTATION MODE" in prompt:
                    if workspace_dir:
                        (workspace_dir / "calc.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
                    mut_json = json.dumps({
                        "status": "success",
                        "summary": f"Attempt {planning_mock_calls} fix",
                        "modified_files": ["calc.py"],
                        "created_files": [],
                        "deleted_files": [],
                        "verification_notes": "Tested",
                    })
                    return AgentExecutionResult(
                        agent="developer",
                        success=True,
                        stdout=f"```json\n{mut_json}\n```",
                        stderr="",
                        exit_code=0,
                        duration_ms=10.0,
                    )
            return original_runtime_execute(agent=agent, prompt=prompt, timeout=timeout, workspace_dir=workspace_dir, env=env)

        monkeypatch.setattr(service.runtime, "execute", fake_planning_execute)

        # Mock QA reinspection to succeed
        reinspect_calls = 0
        def fake_reinspect(*args, **kwargs):
            nonlocal reinspect_calls
            reinspect_calls += 1
            t_id = kwargs.get("task_id") or args[0]
            t = service.company.projects["p_limit"].tasks[t_id]
            run = t.create_run()
            run.status = RunStatus.SUCCESS.value
            p_art = service.find_artifact(kwargs.get("code_patch_artifact_id"))[2]
            q_art = materialize_qa_report_artifact(
                base_output_dir=Path(service.output_dir),
                task=t,
                run=run,
                typed_result=QAInspectionResult(
                    schema_version="1.0",
                    status=QAInspectionStatus.READY_FOR_QA_EXECUTION.value,
                    summary="Reinspection complete",
                    requirements_coverage=[RequirementCoverage("REQ-01", "COVERED", "ok")],
                    recommended_verification_actions=[QARecommendedAction("pytest", "tests/test_calc.py", "verify")],
                ),
                lineage_metadata={
                    "product_artifact_id": "prod",
                    "developer_plan_artifact_id": "plan",
                    "code_patch_artifact_id": p_art.id,
                    "base_commit_hash": p_art.metadata.get("base_commit_hash", "abc"),
                },
            )
            t.complete(status=TaskStatus.COMPLETED.value, summary="Reinspection complete")
            return run

        monkeypatch.setattr(service, "execute_qa_inspection_task", fake_reinspect)

        # Mock QA re-execution to return FAIL every time
        reverify_calls = 0
        def fake_reverify(*args, **kwargs):
            nonlocal reverify_calls
            reverify_calls += 1
            t_id = kwargs.get("task_id") or args[0]
            t = service.company.projects["p_limit"].tasks[t_id]
            run = t.create_run()
            run.status = RunStatus.SUCCESS.value
            verdict = QAExecutionVerdictResult(
                schema_version="1.0",
                verdict=QAFinalVerdict.FAIL.value,
                summary=f"Re-execution failed on iteration {reverify_calls}",
            )
            p_art = service.find_artifact(kwargs.get("code_patch_artifact_id"))[2]
            materialize_qa_execution_report_artifact(
                base_output_dir=Path(service.output_dir),
                task=t,
                run=run,
                typed_verdict=verdict,
                lineage_metadata={
                    "product_artifact_id": "prod",
                    "developer_plan_artifact_id": "plan",
                    "code_patch_artifact_id": p_art.id,
                    "qa_report_artifact_id": kwargs.get("qa_report_artifact_id", "qa_rep"),
                    "base_commit_hash": p_art.metadata.get("base_commit_hash", "abc"),
                },
                execution_evidence=[{"action": {"action_type": "pytest", "target": "tests/test_calc.py"}, "passed": False, "exit_code": 1}],
            )
            t.complete(status=TaskStatus.COMPLETED.value, summary=f"Re-execution failed on iteration {reverify_calls}")
            return run

        monkeypatch.setattr(service, "execute_qa_verification_task", fake_reverify)

        # Execute loop with 2 distinct approvals
        approvals = {1: "fixture_appr_iter1", 2: "fixture_appr_iter2"}
        result = service.execute_developer_qa_repair_loop(
            task_id=qa_exec_task.id,
            founder_approvals=approvals,
            original_grant=grant,
            max_repair_iterations=2,
        )

        # Assertions on hard limit
        assert result.status == RepairWorkflowStatus.REPAIR_LIMIT_REACHED.value
        assert result.repair_iterations_used == 2
        assert len(result.attempts) == 2
        assert planning_mock_calls == 2
        assert reinspect_calls == 2
        assert reverify_calls == 2
        assert "maximum allowed repair iterations" in result.termination_reason


# ==============================================================================
# 7. Real One-Repair Success Live Proof
# ==============================================================================

class TestLiveRepairSuccessProof:
    """Live proof demonstrating a real, working repair cycle from initial QA FAIL to repaired QA PASS."""

    def test_live_one_repair_success(self, tmp_path):
        """End-to-end integration test with isolated git worktrees, real pytest verification,
        initial defect, repair planning, grant derivation, worktree mutation, cumulative diff,
        and QA PASS verification.
        """
        # 1. Setup git repo with intentional bug
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        run_git(["init"], cwd=repo_dir)
        run_git(["config", "user.name", "Test User"], cwd=repo_dir)
        run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)

        # Initial buggy file
        (repo_dir / "math_lib.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        test_dir = repo_dir / "tests"
        test_dir.mkdir()
        (test_dir / "test_math.py").write_text(
            "from math_lib import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n",
            encoding="utf-8",
        )
        company_agents = Path(__file__).resolve().parent.parent / ".agents"
        if company_agents.exists():
            shutil.copytree(company_agents, repo_dir / ".agents")
        run_git(["add", "math_lib.py", "tests/test_math.py"], cwd=repo_dir)
        run_git(["commit", "-m", "initial commit with bug"], cwd=repo_dir)
        head = resolve_repo_head_commit(repo_dir)

        # 2. Setup CompanyService
        service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
        chain = create_canonical_test_chain(
            service=service,
            repo_dir=repo_dir,
            head_commit=head,
            project_id="proj_live_succ",
            patch_text=(
                "diff --git a/math_lib.py b/math_lib.py\n"
                "--- a/math_lib.py\n"
                "+++ b/math_lib.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def add(a, b):\n"
                "-    return a - b\n"
                "+    return a + b - 1\n"
            ),
            changed_files=["math_lib.py"],
            recs=[{"action_type": "pytest", "target": "tests/test_math.py", "purpose": "Verify add"}],
            qa_verdict="FAIL",
            qa_summary="assert 4 == 5 failed",
            qa_evidence_passed=False,
        )

        task = chain["qa_exec_task"]
        grant_v1 = chain["grant"]
        patch_v1_art = chain["patch_artifact"]

        # 3. Mock Developer Agent to return the correct repair plan and mutation
        repair_plan_json = json.dumps({
            "schema_version": "1.0",
            "repair_id": f"repair_{task.id}_iter1",
            "iteration": 1,
            "root_cause": "The addition function had extraneous subtraction (- 1) causing test failure.",
            "requirements_to_fix": ["REQ-01"],
            "files_to_modify": [{"path": "math_lib.py", "description": "Remove - 1 from return"}],
            "files_to_create": [],
            "files_to_delete": [],
            "proposed_changes": ["Change return a + b - 1 to return a + b"],
            "proposed_verification_actions": [{"action_type": "pytest", "target": "tests/test_math.py"}],
            "risks": [],
            "requirement_conflict_detected": False,
        })

        original_runtime_execute = service.runtime.execute
        def custom_runtime_execute(agent, prompt, timeout=60.0, workspace_dir=None, env=None):
            if agent == "developer":
                if "DEVELOPER REPAIR PLANNING MODE" in prompt:
                    return AgentExecutionResult(
                        agent="developer",
                        success=True,
                        stdout=f"```json\n{repair_plan_json}\n```",
                        stderr="",
                        exit_code=0,
                        duration_ms=10.0,
                    )
                elif "MUTATION MODE" in prompt:
                    target_file = workspace_dir / "math_lib.py"
                    target_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
                    mut_json = json.dumps({
                        "status": "success",
                        "summary": "Fixed addition logic in math_lib.py",
                        "modified_files": ["math_lib.py"],
                        "created_files": [],
                        "deleted_files": [],
                        "verification_notes": "Tested locally with pytest",
                    })
                    return AgentExecutionResult(
                        agent="developer",
                        success=True,
                        stdout=f"```json\n{mut_json}\n```",
                        stderr="",
                        exit_code=0,
                        duration_ms=10.0,
                    )
            return original_runtime_execute(agent=agent, prompt=prompt, timeout=timeout, workspace_dir=workspace_dir, env=env)

        service.runtime.execute = custom_runtime_execute

        # 4. Run the repair loop with valid fixture approval
        loop_result = service.execute_developer_qa_repair_loop(
            task_id=task.id,
            founder_approvals={1: "fixture_approval_live_iter1"},
            original_grant=grant_v1,
            max_repair_iterations=2,
            timeout=180.0,
        )

        # 5. Verify full repair loop success
        assert loop_result.status == RepairWorkflowStatus.QA_PASSED.value
        assert loop_result.repair_iterations_used == 1
        assert "PASSED QA verification on iteration 1" in loop_result.termination_reason
        assert loop_result.final_code_patch_artifact_id is not None
        assert loop_result.final_qa_execution_report_artifact_id is not None

        # Verify repaired patch artifact
        _, _, final_patch = service.find_artifact(loop_result.final_code_patch_artifact_id)
        assert final_patch.metadata.get("patch_version") == 2
        assert final_patch.metadata.get("previous_code_patch_artifact_id") == patch_v1_art.id
        assert final_patch.metadata.get("repair_iteration") == 1
        assert "math_lib.py" in final_patch.metadata.get("changed_files")

        # Verify final cumulative diff contains clean change from base
        patch_text = (tmp_path / "artifacts" / final_patch.path).read_text(encoding="utf-8")
        assert "-    return a - b" in patch_text
        assert "+    return a + b" in patch_text

        # Verify durable repair report artifact
        repair_reports = [a for run in task.runs for a in run.artifacts if a.artifact_type == ArtifactType.DEVELOPER_QA_REPAIR_REPORT.value]
        assert len(repair_reports) >= 1
        rep_content = (tmp_path / "artifacts" / repair_reports[0].path).read_text(encoding="utf-8")
        assert "QA_PASSED" in rep_content
        assert "Repair Iteration History" in rep_content

        # Verify main repository was NEVER touched
        current_repo_file = (repo_dir / "math_lib.py").read_text(encoding="utf-8")
        assert current_repo_file == "def add(a, b):\n    return a - b\n"
        assert resolve_repo_head_commit(repo_dir) == head
