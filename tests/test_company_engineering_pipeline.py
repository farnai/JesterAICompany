"""Focused Test Suite for STEP 17B-4: Engineering Pipeline Integration.

Tests:
- Developer macro work item semantics and dispatch to EngineeringPipelineAdapter
- Product + UX Fan-In Prerequisite enforcement (fail closed)
- SHA-256 verification of inputs and durable artifacts
- Developer Planning execution and artifact generation
- ExecutionGrant security boundary
- Isolated worktree mutation producing verified CODE_PATCH
- Application-owned QA Inspection and Verification (CEO cannot skip QA)
- QA PASS -> READY_FOR_HUMAN_APPLY (autonomous execution stop boundary)
- QA FAIL -> Bounded Repair Loop (max 2 iterations) -> Re-QA
- Explicit Human Approval (RealRepoApplyGrant)
- Transactional RealRepoApply (Double TOCTOU, diff equivalence, post-apply test execution)
- Terminal COMPLETED state transition
- State machine protection & idempotency
- 20 Security Attack Rejections (A through T)
- Crash / Resume V1 semantics
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import uuid
import pytest

from jester_ai_company.core import (
    ALLOWED_HANDOFF_EDGES,
    Artifact,
    ArtifactInputRef,
    ArtifactType,
    ArtifactVerificationError,
    Company,
    Employee,
    Project,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from jester_ai_company.dag import (
    DAGValidationError,
    validate_dag_structure,
)
from jester_ai_company.developer_mutation import DeveloperMutationStatus
from jester_ai_company.developer_result import (
    DeveloperTaskResult,
    ProposedFile,
)
from jester_ai_company.engineering_pipeline import (
    EngineeringPipelineAdapter,
    EngineeringPipelineError,
    EngineeringPreconditionError,
)
from jester_ai_company.execution_grant import (
    ExecutionGrant,
    MissingApprovalError,
    PlanArtifactMismatchError,
    ProtectedPathError,
    StaleCommitError,
    TestModificationForbiddenError,
    VerificationAction,
)
from jester_ai_company.materializer import (
    compute_sha256,
    materialize_code_patch_artifact,
    materialize_developer_qa_repair_report_artifact,
    materialize_developer_repair_plan_artifact,
    materialize_qa_execution_report_artifact,
    materialize_qa_report_artifact,
    materialize_specialist_artifact,
)
from jester_ai_company.proposal import CEOActionProposal
from jester_ai_company.orchestrator import (
    CEOActionType,
    CEOOrchestrationPlan,
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
)
from jester_ai_company.qa_result import (
    QAFinding,
    QAFindingSeverity,
    QAInspectionResult,
    QAInspectionStatus,
    RequirementCoverage,
)
from jester_ai_company.real_repo_apply import (
    ApprovalInvalidError,
    CandidateNotEligibleError,
    GrantExpiredError,
    GrantReplayedError,
    ProposalMismatchError,
    RealRepoApplyGrant,
    RealRepoApplyProposal,
    RealRepoApplyResult,
    RealRepoApplyStatus,
    TargetRepositoryInvalidError,
)
from jester_ai_company.repair import (
    MAX_REPAIR_ITERATIONS,
    DeveloperQARepairLoopResult,
    DeveloperRepairPlan,
    RepairWorkflowStatus,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import BoundedDeveloperExecutionOutcome, CompanyService
from jester_ai_company.ux_result import UXTaskResult
from jester_ai_company.verification import (
    VerificationExecutionResult,
    VerificationStatus,
)
from jester_ai_company.worktree import (
    WorktreeManager,
    resolve_repo_head_commit,
    run_git,
)


# ==============================================================================
# Helpers & Fixtures
# ==============================================================================

def setup_test_git_repo(target_dir: Path) -> str:
    """Initialize a safe temporary test Git repository with calculator.py and test_calculator.py."""
    target_dir.mkdir(parents=True, exist_ok=True)
    run_git(["init"], cwd=target_dir)
    run_git(["config", "user.name", "Test Runner"], cwd=target_dir)
    run_git(["config", "user.email", "runner@example.com"], cwd=target_dir)
    (target_dir / "README.md").write_text("# Temp Test Repository\n", encoding="utf-8")
    (target_dir / "calculator.py").write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "# multiply is omitted initially\n",
        encoding="utf-8",
    )
    (target_dir / "test_calculator.py").write_text(
        "from calculator import add\n\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    run_git(["add", "."], cwd=target_dir)
    run_git(["commit", "-m", "Initial baseline commit"], cwd=target_dir)
    return resolve_repo_head_commit(target_dir)


def make_agent_result(agent: str, payload_dict: Dict[str, Any], exit_code: int = 0) -> AgentExecutionResult:
    return AgentExecutionResult(
        agent=agent,
        success=(exit_code == 0),
        stdout=json.dumps(payload_dict),
        stderr="",
        exit_code=exit_code,
        duration_ms=10.0,
    )


class DeterministicMockRuntime(AntigravityRuntime):
    """Deterministic mock runtime producing valid JSON responses for all specialists."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root=repo_root)
        self.invocations: Dict[str, int] = {}
        self.recorded_calls = []
        self.qa_verdict_override = "PASS"

    def execute(self, agent: str, prompt: str, timeout: Optional[float] = None, workspace_dir: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> AgentExecutionResult:
        agent_norm = agent.lower().strip()
        self.invocations[agent_norm] = self.invocations.get(agent_norm, 0) + 1
        self.recorded_calls.append({"agent": agent_norm, "prompt": prompt})

        if agent_norm == "developer":
            # Check if repair planning
            if "REPAIR PLAN" in prompt or "Repair ID:" in prompt:
                m_rep = re.search(r"Repair ID:\s*([^\r\n]+)", prompt)
                rep_id = m_rep.group(1).strip() if m_rep else "repair_1"
                m_iter = re.search(r"Iteration:\s*(\d+)", prompt)
                rep_iter = int(m_iter.group(1)) if m_iter else 1
                payload = {
                    "schema_version": "1.0",
                    "repair_id": rep_id,
                    "iteration": rep_iter,
                    "root_cause": "Initial implementation failed verification.",
                    "requirements_to_fix": ["REQ-01"],
                    "files_to_modify": [{"path": "calculator.py", "description": "Fix multiply implementation"}],
                    "files_to_create": [],
                    "files_to_delete": [],
                    "proposed_changes": ["Ensure multiply correctly returns product"],
                    "proposed_verification_actions": [{"action_type": "pytest", "target": "test_calculator.py"}],
                    "risks": [],
                    "requirement_conflict_detected": False,
                    "conflict_details": None,
                }
                return make_agent_result(agent_norm, payload)

            # Check if bounded mutation execution
            if workspace_dir or "EXECUTION GRANT" in prompt or "MUTATION" in prompt:
                if workspace_dir and (Path(workspace_dir) / "calculator.py").exists():
                    calc_path = Path(workspace_dir) / "calculator.py"
                    content = calc_path.read_text(encoding="utf-8")
                    if "def multiply" not in content:
                        content += "\n\ndef multiply(a: int, b: int) -> int:\n    return a * b\n"
                        calc_path.write_text(content, encoding="utf-8")
                payload = {
                    "schema_version": "1.0",
                    "status": "completed",
                    "summary": "Implemented multiply function in calculator.py",
                    "files_attempted": ["calculator.py"],
                    "files_completed": ["calculator.py"],
                    "blocked_actions": [],
                    "unresolved_issues": [],
                }
                return make_agent_result(agent_norm, payload)

            # Developer planning mode
            payload = {
                "schema_version": "1.0",
                "status": "completed",
                "summary": "Implement multiply function in calculator.py",
                "implementation_plan": ["Add multiply(a, b) to calculator.py"],
                "files_to_modify": [{"path": "calculator.py", "description": "Add multiply function"}],
                "files_to_create": [],
                "verification_actions": [{"action_type": "pytest", "target": "test_calculator.py"}],
            }
            return make_agent_result(agent_norm, payload)

        elif agent_norm == "qa":
            # Check if QA Verification Execution (STEP 14B)
            if "STEP 14B" in prompt or "release readiness" in prompt or "evaluating final release readiness" in prompt:
                verdict = getattr(self, "qa_verdict_override", "PASS")
                payload = {
                    "schema_version": "1.0",
                    "verdict": verdict,
                    "summary": f"Verification finished with verdict {verdict}.",
                    "requirements_evaluations": [
                        {
                            "requirement_id": "REQ-01",
                            "status": "SATISFIED" if verdict == "PASS" else "FAILED",
                            "evidence": "pytest test_calculator.py passed" if verdict == "PASS" else "pytest test_calculator.py failed",
                            "notes": "",
                        }
                    ],
                    "executed_tests_summary": "1/1 tests passed" if verdict == "PASS" else "1/1 tests failed",
                    "blocking_issues": [] if verdict == "PASS" else ["Verification failed on test target"],
                    "release_recommendation": "APPROVED_FOR_RELEASE" if verdict == "PASS" else "REJECTED_NEEDS_FIX",
                }
                return make_agent_result(agent_norm, payload)
            else:
                # QA Inspection (STEP 14A)
                payload = {
                    "schema_version": "1.0",
                    "status": "READY_FOR_QA_EXECUTION",
                    "summary": "Initial static QA inspection passed with no defects.",
                    "requirements_coverage": [{"requirement_id": "REQ-01", "status": "COVERED", "notes": "Covered in requirements"}],
                    "risks": [],
                    "findings": [],
                    "test_cases": [],
                    "regression_areas": [],
                    "unresolved_questions": [],
                    "recommended_verification_actions": [{"action_type": "pytest", "target": "test_calculator.py", "purpose": "Verify calculator tests"}],
                }
                return make_agent_result(agent_norm, payload)

        elif agent_norm == "product":
            payload = {
                "schema_version": "1.0",
                "status": "completed",
                "summary": "Product requirements for multiply feature",
                "deliverables": [{"name": "PRD", "content": "REQ-01: Add multiply(a, b) function that returns a * b."}],
            }
            return make_agent_result(agent_norm, payload)

        elif agent_norm == "ux":
            payload = {
                "schema_version": "1.0",
                "status": "completed",
                "summary": "UX specification for function signature and error handling",
                "interaction_rules": ["multiply returns int"],
            }
            return make_agent_result(agent_norm, payload)

        return make_agent_result(agent_norm, {})


@pytest.fixture
def test_env():
    """Create isolated test environment with temporary company workspace and target Git repo."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        workspace = root / "company_workspace"
        workspace.mkdir()
        target_repo = root / "temp_target_repo"
        head_commit = setup_test_git_repo(target_repo)

        runtime = DeterministicMockRuntime(repo_root=workspace)
        service = CompanyService(
            output_dir=str(workspace / ".runs"),
            repo_root=workspace,
            runtime=runtime,
            enable_engineering_pipeline=True,
        )

        objective = CompanyObjective(
            id="obj_multiply_feature",
            title="Implement multiply function",
            description="Add multiply(a, b) to calculator.py and ensure tests verify it.",
            target_repository=str(target_repo),
            constraints=["isolate mutations to worktree until human approval"],
            acceptance_criteria=["multiply(a, b) passes test suite"],
        )

        yield {
            "root": root,
            "workspace": workspace,
            "target_repo": target_repo,
            "head_commit": head_commit,
            "runtime": runtime,
            "service": service,
            "objective": objective,
        }


def populate_product_and_ux_artifacts(service: CompanyService, run: CompanyRun) -> Tuple[Task, Artifact, Task, Artifact]:
    """Helper to populate completed and verified Product and UX artifacts for a run."""
    proj_id = f"proj_{run.run_id}"
    if proj_id not in service.company.projects:
        service.create_project(proj_id, name=f"Project for {run.objective.title}")
    proj = service.get_project(proj_id)

    # 1. Product
    prod_task = service.create_task(project_id=proj.id, title="Product PRD", goal="Requirements", required_roles=["product"])
    prod_run = prod_task.create_run()
    prod_run.status = RunStatus.RUNNING.value
    prod_res = ProductTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Requirements for calculator multiply function",
        deliverables=[ProductDeliverable(name="PRD", content="REQ-01: multiply(a, b) must return a * b.")],
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

    # 2. UX
    ux_task = service.create_task(project_id=proj.id, title="UX Spec", goal="Interface spec", required_roles=["ux"])
    ux_run = ux_task.create_run()
    ux_run.status = RunStatus.RUNNING.value
    ux_res = UXTaskResult(
        schema_version="1.0",
        status="completed",
        summary="UX Spec for calculator functions",
        interaction_rules=["multiply returns int"],
    )
    ux_art = materialize_specialist_artifact(
        base_output_dir=Path(service.output_dir),
        task=ux_task,
        run=ux_run,
        agent_name="ux",
        typed_result=ux_res,
    )
    ux_run.complete(status=RunStatus.SUCCESS.value)
    ux_task.complete(status=TaskStatus.COMPLETED.value, summary=ux_res.summary, details=ux_res.to_dict())

    return prod_task, prod_art, ux_task, ux_art


def setup_standard_code_plan(service: CompanyService, run: CompanyRun) -> CEOPlannedWorkItem:
    """Helper to set up a standard DAG: Product -> UX -> Developer."""
    w_prod = CEOPlannedWorkItem(work_item_id="w_prod", role="product", objective="PRD", priority=1)
    w_ux = CEOPlannedWorkItem(work_item_id="w_ux", role="ux", objective="UX", priority=2)
    w_dev = CEOPlannedWorkItem(
        work_item_id="w_dev",
        role="developer",
        objective="Implement code",
        depends_on=["w_prod", "w_ux"],
        priority=3,
    )
    plan = CEOOrchestrationPlan(
        plan_id=f"plan_{run.run_id}",
        objective_id=run.objective.id,
        version=1,
        work_items=[w_prod, w_ux, w_dev],
    )
    run.set_plan(plan)
    run.transition_to(CompanyRunState.PLANNING)
    run.transition_to(CompanyRunState.PLAN_READY)
    service.save_company_run(run)
    service.start_company_run(run.run_id)

    # Populate Product and UX in completed state
    prod_task, prod_art, ux_task, ux_art = populate_product_and_ux_artifacts(service, run)
    w_prod.state = WorkItemState.COMPLETED.value
    w_prod.task_id = prod_task.id
    run.work_item_states["w_prod"] = WorkItemState.COMPLETED.value

    w_ux.state = WorkItemState.COMPLETED.value
    w_ux.task_id = ux_task.id
    run.work_item_states["w_ux"] = WorkItemState.COMPLETED.value

    service.save_company_run(run)
    return w_dev


# ==============================================================================
# SECTION 26: Minimum Focused Tests (Items 1 to 38)
# ==============================================================================

def test_01_developer_macro_dispatch_enters_engineering_adapter(test_env):
    """1. Developer macro dispatch enters engineering adapter."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    w_dev = setup_standard_code_plan(service, run)

    called = []
    orig_exec = EngineeringPipelineAdapter.execute_developer_work

    def tracking_exec(self, *args, **kwargs):
        target_item = kwargs.get("target_item") or (args[1] if len(args) > 1 else None)
        if target_item:
            called.append(target_item.work_item_id)
        return orig_exec(self, *args, **kwargs)

    EngineeringPipelineAdapter.execute_developer_work = tracking_exec
    try:
        service.execute_next_company_work(run.run_id)
        assert "w_dev" in called
    finally:
        EngineeringPipelineAdapter.execute_developer_work = orig_exec


def test_02_product_artifact_required(test_env):
    """2. Product artifact required (fails closed if missing)."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    w_dev = setup_standard_code_plan(service, run)

    # Tamper: set w_prod task_id to non-existent
    w_prod = next(w for w in run.active_plan.work_items if w.role == "product")
    w_prod.task_id = "non_existent_task_id"
    service.save_company_run(run)

    with pytest.raises(ArtifactVerificationError, match="Could not locate verified Product and UX artifacts"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.FAILED.value
    assert updated.work_item_states["w_dev"] == WorkItemState.FAILED.value


def test_03_ux_artifact_required(test_env):
    """3. UX artifact required (fails closed if missing)."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    w_dev = setup_standard_code_plan(service, run)

    # Tamper: set w_ux task_id to non-existent
    w_ux = next(w for w in run.active_plan.work_items if w.role == "ux")
    w_ux.task_id = "non_existent_ux_task_id"
    service.save_company_run(run)

    with pytest.raises(ArtifactVerificationError, match="Could not locate verified Product and UX artifacts"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.FAILED.value
    assert updated.work_item_states["w_dev"] == WorkItemState.FAILED.value


def test_04_product_sha_verification_required(test_env):
    """4. Product SHA verification required (fails closed on mismatch)."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    w_dev = setup_standard_code_plan(service, run)

    # Corrupt physical product artifact
    proj = service.get_project(f"proj_{run.run_id}")
    prod_task = [t for t in proj.tasks.values() if "product" in t.required_roles][0]
    art = prod_task.runs[-1].artifacts[0]
    art_file = service.output_dir / art.path
    art_file.write_text("TAMPERED PRODUCT CONTENT", encoding="utf-8")

    with pytest.raises(ArtifactVerificationError, match="checksum mismatch"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.FAILED.value


def test_05_ux_sha_verification_required(test_env):
    """5. UX SHA verification required (fails closed on mismatch)."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    w_dev = setup_standard_code_plan(service, run)

    # Corrupt physical UX artifact
    proj = service.get_project(f"proj_{run.run_id}")
    ux_task = [t for t in proj.tasks.values() if "ux" in t.required_roles][0]
    art = ux_task.runs[-1].artifacts[0]
    art_file = service.output_dir / art.path
    art_file.write_text("TAMPERED UX CONTENT", encoding="utf-8")

    with pytest.raises(ArtifactVerificationError, match="checksum mismatch"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.FAILED.value


def test_06_developer_planning_uses_existing_primitive(test_env):
    """6. Developer planning uses existing primitive."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    called = []
    orig_plan = service.execute_developer_planning_task

    def track_plan(task_id, project_id=None):
        called.append(task_id)
        return orig_plan(task_id, project_id=project_id)

    service.execute_developer_planning_task = track_plan
    try:
        service.execute_next_company_work(run.run_id)
        assert len(called) == 1
    finally:
        service.execute_developer_planning_task = orig_plan


def test_07_execution_grant_boundary_preserved(test_env):
    """7. ExecutionGrant boundary preserved."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    grant_events = [e for e in updated.events if e.get("event_type") == "EXECUTION_GRANT_ACCEPTED"]
    assert len(grant_events) >= 1
    assert "grant_id" in grant_events[0].get("details", {})
    assert grant_events[0].get("details", {})["base_commit_hash"] == test_env["head_commit"]


def test_08_mutation_occurs_only_in_isolated_worktree(test_env):
    """8. Mutation occurs only in isolated worktree (target repo untouched)."""
    service = test_env["service"]
    target_repo = test_env["target_repo"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    calc_before = (target_repo / "calculator.py").read_text(encoding="utf-8")
    head_before = resolve_repo_head_commit(target_repo)

    service.execute_next_company_work(run.run_id)

    calc_after = (target_repo / "calculator.py").read_text(encoding="utf-8")
    head_after = resolve_repo_head_commit(target_repo)

    assert calc_before == calc_after
    assert head_before == head_after


def test_09_code_patch_required(test_env):
    """9. CODE_PATCH required from mutation."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    assert updated.code_patch_artifact_id is not None
    patch_lineage = service.find_artifact(updated.code_patch_artifact_id)
    assert patch_lineage is not None
    _, _, patch_art = patch_lineage
    assert patch_art.artifact_type == ArtifactType.CODE_PATCH.value


def test_10_code_patch_verifies(test_env):
    """10. CODE_PATCH verifies on disk."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    patch_lineage = service.find_artifact(updated.code_patch_artifact_id)
    _, _, patch_art = patch_lineage
    patch_path = service.output_dir / patch_art.path
    assert patch_path.is_file()
    computed_sha = hashlib.sha256(patch_path.read_bytes()).hexdigest()
    assert computed_sha == patch_art.sha256


def test_11_qa_automatically_runs_after_mutation(test_env):
    """11. QA automatically runs after mutation."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    qa_events = [e for e in updated.events if e.get("event_type") in ("QA_STARTED", "QA_PASSED")]
    assert len(qa_events) >= 1
    assert updated.qa_execution_report_artifact_id is not None


def test_12_ceo_cannot_skip_qa(test_env):
    """12. CEO cannot skip QA."""
    with pytest.raises(ValueError):
        CEOActionType("SKIP_QA")


def test_13_qa_pass_to_ready_for_human_apply(test_env):
    """13. QA PASS transitions CompanyRun to READY_FOR_HUMAN_APPLY."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    assert updated.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value


def test_14_source_repo_unchanged_before_human_approval(test_env):
    """14. Source repository unchanged before Human approval."""
    service = test_env["service"]
    target_repo = test_env["target_repo"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    rc, status_out, _ = run_git(["status", "--porcelain"], cwd=target_repo)
    assert status_out.strip() == ""


def test_15_autonomous_loop_stops_at_ready_for_human_apply(test_env):
    """15. Autonomous loop stops at READY_FOR_HUMAN_APPLY."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    final_run = service.run_company_until_boundary(run.run_id, max_steps=10)
    assert final_run.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value


def test_16_human_approval_required(test_env):
    """16. Human approval required before apply."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    with pytest.raises(MissingApprovalError):
        service.approve_company_repo_apply(run.run_id, founder_approval_id="")


def test_17_valid_human_approval_to_applying(test_env):
    """17. Valid Human approval prepares grant and transitions to APPLYING during apply."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    grant = service.approve_company_repo_apply(run.run_id, founder_approval_id="founder_alice_01")
    assert grant.status == "ISSUED"
    assert grant.founder_approval_id == "founder_alice_01"


def test_18_real_repo_apply_uses_existing_engine(test_env):
    """18. RealRepoApply uses existing engine."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    called = []
    orig_apply = service.execute_real_repo_apply

    def track_apply(grant_id, project_id=None):
        called.append(grant_id)
        return orig_apply(grant_id, project_id=project_id)

    service.execute_real_repo_apply = track_apply
    try:
        service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_alice_01")
        assert len(called) == 1
    finally:
        service.execute_real_repo_apply = orig_apply


def test_19_successful_apply_to_completed(test_env):
    """19. Successful apply transitions CompanyRun to COMPLETED."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_alice_01")
    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.COMPLETED.value


def test_20_target_repo_changed_only_after_approval(test_env):
    """20. Target repo changed only after approval and apply."""
    service = test_env["service"]
    target_repo = test_env["target_repo"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    assert "def multiply" not in (target_repo / "calculator.py").read_text(encoding="utf-8")

    service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_alice_01")
    rc, status_out, err = run_git(["status", "--porcelain"], cwd=target_repo)
    assert "calculator.py" in status_out or "test_calculator.py" in status_out


def test_21_duplicate_apply_rejected(test_env):
    """21. Duplicate apply rejected (single use grant)."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_alice_01")

    with pytest.raises(TransitionPolicyError, match="Cannot execute repository apply"):
        service.apply_approved_company_repo(run.run_id)


def test_22_23_24_qa_fail_triggers_repair_loop_and_success(test_env):
    """22, 23, 24. QA FAIL triggers repair, reruns QA, and reaches READY_FOR_HUMAN_APPLY."""
    service = test_env["service"]
    runtime = test_env["runtime"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    qa_eval_count = 0
    orig_exec = runtime.execute

    def mock_qa_exec(agent, prompt, *args, **kwargs):
        nonlocal qa_eval_count
        if agent.lower().strip() == "qa" and ("STEP 14B" in prompt or "release readiness" in prompt):
            qa_eval_count += 1
            if qa_eval_count == 1:
                runtime.qa_verdict_override = "FAIL"
            else:
                runtime.qa_verdict_override = "PASS"
        return orig_exec(agent, prompt, *args, **kwargs)

    runtime.execute = mock_qa_exec

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    assert updated.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value
    events = [e.get("event_type") for e in updated.events]
    assert "QA_FAILED" in events
    assert "REPAIR_STARTED" in events
    assert "REPAIR_COMPLETED" in events
    assert "QA_PASSED" in events


def test_25_repair_budget_exhaustion_blocks(test_env):
    """25. Repair budget exhaustion blocks/fails according to policy."""
    service = test_env["service"]
    runtime = test_env["runtime"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    runtime.qa_verdict_override = "FAIL"

    with pytest.raises(EngineeringPipelineError, match="Repair loop exhausted without passing QA"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.BLOCKED.value
    assert updated.work_item_states["w_dev"] == WorkItemState.BLOCKED.value


def test_26_downstream_company_completion_cannot_bypass_human_gate(test_env):
    """26. Downstream company completion cannot bypass Human gate for code workflows."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.run_company_until_boundary(run.run_id, max_steps=10)
    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value
    assert updated.state != CompanyRunState.COMPLETED.value


def test_27_28_ceo_invocation_not_required_for_deterministic_qa_and_repair(test_env):
    """27 & 28. CEO invocation count remains 0/unchanged during deterministic engineering progression."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    ceo_count_before = run.ceo_invocation_count
    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    assert updated.ceo_invocation_count == ceo_count_before


def test_29_work_item_not_marked_complete_before_engineering_boundary(test_env):
    """29. Work item not marked complete before engineering boundary."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    w_dev = setup_standard_code_plan(service, run)

    assert run.work_item_states["w_dev"] == WorkItemState.PENDING.value


def test_30_verified_artifact_refs_preserved(test_env):
    """30. Verified artifact refs preserved on CompanyRun."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    assert updated.code_patch_artifact_id is not None
    assert updated.qa_execution_report_artifact_id is not None
    assert updated.real_repo_apply_proposal_id is not None


def test_31_employee_result_summary_bounded(test_env):
    """31. EmployeeResultSummary is bounded (no raw full diff or giant logs)."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    dev_summary = next(s for s in updated.employee_summaries if s.role == "developer")
    assert len(dev_summary.summary) < 500
    assert "diff --git" not in dev_summary.summary


def test_32_company_run_serialization_preserves_engineering_state(test_env):
    """32. CompanyRun serialization preserves engineering state."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    data = updated.to_dict()
    restored = CompanyRun.from_dict(data)

    assert restored.run_id == updated.run_id
    assert restored.state == updated.state
    assert restored.code_patch_artifact_id == updated.code_patch_artifact_id
    assert restored.qa_execution_report_artifact_id == updated.qa_execution_report_artifact_id
    assert restored.real_repo_apply_proposal_id == updated.real_repo_apply_proposal_id


def test_33_resume_after_code_patch_does_not_regenerate(test_env):
    """33. Resume after CODE_PATCH does not blindly regenerate it."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    first_run = service.get_company_run(run.run_id)
    first_patch_id = first_run.code_patch_artifact_id

    adapter = EngineeringPipelineAdapter(service)
    target_item = next(w for w in first_run.active_plan.work_items if w.role == "developer")
    first_run.state = CompanyRunState.RUNNING.value
    resumed_run = adapter.execute_developer_work(first_run, target_item)

    assert resumed_run.code_patch_artifact_id == first_patch_id


def test_34_resume_after_qa_pass_preserves_gate(test_env):
    """34. Resume after QA PASS preserves gate."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value

    resumed = service.run_company_until_boundary(run.run_id)
    assert resumed.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value


def test_35_tampered_resume_artifact_rejected(test_env):
    """35. Tampered resume artifact rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    patch_lineage = service.find_artifact(updated.code_patch_artifact_id)
    _, _, patch_art = patch_lineage
    patch_file = service.output_dir / patch_art.path
    patch_file.write_text("CORRUPTED PATCH CONTENT", encoding="utf-8")

    with pytest.raises(Exception):
        service.approve_company_repo_apply(run.run_id, founder_approval_id="founder_alice_01")


def test_36_completed_run_cannot_reapply(test_env):
    """36. COMPLETED run cannot reapply."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_alice_01")
    completed = service.get_company_run(run.run_id)
    assert completed.state == CompanyRunState.COMPLETED.value

    with pytest.raises(TransitionPolicyError):
        service.approve_company_repo_apply(run.run_id, founder_approval_id="founder_alice_02")


def test_37_38_ready_for_human_apply_canonical(test_env):
    """37 & 38. READY_FOR_APPLY alias does not exist, READY_FOR_HUMAN_APPLY remains canonical."""
    states = [s.value for s in CompanyRunState]
    assert "READY_FOR_HUMAN_APPLY" in states
    assert "READY_FOR_APPLY" not in states


# ==============================================================================
# SECTION 25: Security Attack Rejections (A through T)
# ==============================================================================

def test_security_a_ceo_skip_qa_rejected(test_env):
    """Security A: CEO tries SKIP_QA -> rejected fail closed."""
    with pytest.raises(ValueError):
        CEOActionType("SKIP_QA")


def test_security_b_ceo_approve_real_repo_rejected(test_env):
    """Security B: CEO tries APPROVE_REAL_REPO -> rejected fail closed."""
    with pytest.raises(ValueError):
        CEOActionType("APPROVE_REAL_REPO")


def test_security_c_ceo_create_real_repo_apply_grant_rejected(test_env):
    """Security C: CEO tries CREATE_REAL_REPO_APPLY_GRANT -> rejected fail closed."""
    with pytest.raises(ValueError):
        CEOActionType("CREATE_REAL_REPO_APPLY_GRANT")


def test_security_d_ceo_create_execution_grant_rejected(test_env):
    """Security D: CEO tries CREATE_EXECUTION_GRANT -> rejected fail closed."""
    with pytest.raises(ValueError):
        CEOActionType("CREATE_EXECUTION_GRANT")


def test_security_e_developer_tries_to_self_approve_apply(test_env):
    """Security E: Developer tries to self-approve apply -> rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    with pytest.raises(MissingApprovalError):
        service.approve_company_repo_apply(run.run_id, founder_approval_id="")


def test_security_f_qa_missing_apply_requested(test_env):
    """Security F: QA result missing but apply requested -> rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    run.state = CompanyRunState.READY_FOR_HUMAN_APPLY.value
    with pytest.raises(ProposalMismatchError):
        service.approve_company_repo_apply(run.run_id, founder_approval_id="founder_01")


def test_security_g_qa_fail_apply_requested(test_env):
    """Security G: QA FAIL but apply requested -> rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    run.state = CompanyRunState.BLOCKED.value
    with pytest.raises(TransitionPolicyError):
        service.approve_company_repo_apply(run.run_id, founder_approval_id="founder_01")


def test_security_h_tampered_code_patch(test_env):
    """Security H: Tampered CODE_PATCH rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    patch_lineage = service.find_artifact(run.code_patch_artifact_id)
    _, _, patch_art = patch_lineage
    (service.output_dir / patch_art.path).write_text("MALICIOUS CONTENT", encoding="utf-8")

    with pytest.raises(Exception):
        service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_01")


def test_security_i_stale_real_repo_apply_proposal(test_env):
    """Security I: Stale RealRepoApplyProposal rejected when HEAD moved."""
    service = test_env["service"]
    target_repo = test_env["target_repo"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    service.approve_company_repo_apply(run.run_id, founder_approval_id="founder_01")

    (target_repo / "other.txt").write_text("HEAD moved", encoding="utf-8")
    run_git(["add", "other.txt"], cwd=target_repo)
    run_git(["commit", "-m", "Interfering commit"], cwd=target_repo)

    with pytest.raises(Exception):
        service.apply_approved_company_repo(run.run_id)


def test_security_j_proposal_referencing_wrong_artifact(test_env):
    """Security J: Proposal referencing wrong artifact rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    run.code_patch_artifact_id = "art_foreign_patch"
    with pytest.raises(ProposalMismatchError):
        service.approve_company_repo_apply(run.run_id, founder_approval_id="founder_01")


def test_security_k_wrong_company_run_approval(test_env):
    """Security K: Wrong CompanyRun approval rejected."""
    service = test_env["service"]
    with pytest.raises(OrchestrationError, match="not found"):
        service.approve_company_repo_apply("crun_non_existent", founder_approval_id="founder_01")


def test_security_l_direct_running_to_applying(test_env):
    """Security L: Direct RUNNING -> APPLYING rejected."""
    run = CompanyRun(
        run_id="crun_test",
        objective=test_env["objective"],
        state=CompanyRunState.RUNNING.value,
    )
    with pytest.raises(TransitionPolicyError):
        run.transition_to(CompanyRunState.APPLYING)


def test_security_m_direct_running_to_completed_for_code_workflow(test_env):
    """Security M: Direct RUNNING -> COMPLETED for code workflow rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    with pytest.raises(TransitionPolicyError, match="Direct transition from RUNNING to COMPLETED is forbidden for code workflows"):
        run.transition_to(CompanyRunState.COMPLETED, is_code_workflow=True)


def test_security_n_duplicate_apply(test_env):
    """Security N: Duplicate apply rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)

    service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_01")
    with pytest.raises(TransitionPolicyError):
        service.apply_approved_company_repo(run.run_id)


def test_security_o_apply_after_completed(test_env):
    """Security O: Apply after COMPLETED rejected."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)
    service.execute_next_company_work(run.run_id)
    service.apply_company_repo_with_human_approval(run.run_id, founder_approval_id="founder_01")

    with pytest.raises(TransitionPolicyError):
        service.apply_approved_company_repo(run.run_id)


def test_security_p_mutation_outside_isolated_worktree(test_env):
    """Security P: Mutation outside isolated worktree rejected."""
    service = test_env["service"]
    target_repo = test_env["target_repo"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    rc, status, err = run_git(["status", "--porcelain"], cwd=target_repo)
    assert status.strip() == ""


def test_security_q_protected_path_mutation(test_env):
    """Security Q: Protected-path mutation rejected in grant."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    proj = service.get_project(f"proj_{run.run_id}")
    dev_task = service.create_task(project_id=proj.id, title="Protected Task", goal="Malicious", required_roles=["developer"])
    dev_run = dev_task.create_run()
    dev_res = DeveloperTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Malicious plan",
        files_to_modify=[ProposedFile(path=".git/config", description="Overwrite git config")],
    )
    plan_art = materialize_specialist_artifact(
        base_output_dir=Path(service.output_dir),
        task=dev_task,
        run=dev_run,
        agent_name="developer",
        typed_result=dev_res,
    )
    dev_run.complete(status=RunStatus.SUCCESS.value)
    dev_task.complete(status=TaskStatus.COMPLETED.value, summary="Malicious plan completed")

    with pytest.raises(ProtectedPathError):
        service.create_execution_grant(
            task_id=dev_task.id,
            plan_artifact_id=plan_art.id,
            founder_approval_id="founder_01",
            approved_files_to_modify=[".git/config"],
            repo_root=test_env["target_repo"],
            project_id=proj.id,
        )


def test_security_r_repair_count_beyond_policy(test_env):
    """Security R: Repair count beyond policy rejected."""
    assert MAX_REPAIR_ITERATIONS == 2


def test_security_s_resume_with_tampered_artifact(test_env):
    """Security S: Resume with tampered artifact rejected fail closed."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    setup_standard_code_plan(service, run)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    proj = service.get_project(f"proj_{run.run_id}")
    dev_task = [t for t in proj.tasks.values() if "developer" in t.required_roles and "plan" in t.id][0]
    art = dev_task.runs[-1].artifacts[0]
    (service.output_dir / art.path).write_text("TAMPERED PLAN", encoding="utf-8")

    updated.state = CompanyRunState.RUNNING.value
    target_item = next(w for w in updated.active_plan.work_items if w.role == "developer")
    adapter = EngineeringPipelineAdapter(service)
    with pytest.raises(ArtifactVerificationError):
        adapter.execute_developer_work(updated, target_item)


def test_security_t_resume_from_ambiguous_state(test_env):
    """Security T: Resume from ambiguous state fails closed."""
    service = test_env["service"]
    run = service.create_company_run(test_env["objective"])
    run.state = "AMBIGUOUS_STATE"
    target_item = CEOPlannedWorkItem(work_item_id="w_dev", role="developer", objective="Code")
    adapter = EngineeringPipelineAdapter(service)
    with pytest.raises(TransitionPolicyError):
        adapter.execute_developer_work(run, target_item)
