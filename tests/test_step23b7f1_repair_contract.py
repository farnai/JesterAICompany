"""STEP 23B.7-F.1: Direct Developer QA Repair Contract Fix Tests.

Deterministic regression test suite verifying:
- Scenario A: Direct Developer Repair Success (no Product/UX artifacts, repaired successfully).
- Scenario B: Direct Developer Repair Failure (bounded limits respected, failure state preserved).
- Scenario C: Product + UX Engineering Repair (full-team workflow retains complete dependency chain).
- Scenario D: Missing Mandatory Artifact (DAG requires Product/UX but artifact missing or corrupted -> fail closed).
- Scenario E: Repair Authorization (mutation outside ExecutionGrant denied, zero repo changes).
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    RunStatus,
    TaskStatus,
)
from jester_ai_company.developer_result import (
    DeveloperTaskResult,
    ProposedFile,
)
from jester_ai_company.execution_grant import (
    ExecutionGrant,
    GrantValidationError,
    ProtectedPathError,
    VerificationAction,
)
from jester_ai_company.materializer import (
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
    QAExecutionVerdictResult,
    QAFinalVerdict,
    QARecommendedAction,
    QARequirementExecutionEvaluation,
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
    RepairEligibilityClassification,
    RepairError,
    RepairWorkflowStatus,
    build_developer_repair_planning_prompt,
    build_developer_repair_task,
)
from jester_ai_company.runtime import AgentExecutionResult
from jester_ai_company.service import CompanyService
from jester_ai_company.ux_result import UXFlow, UXTaskResult
from jester_ai_company.worktree import resolve_repo_head_commit, run_git


def _create_base_repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    run_git(["init"], cwd=repo_dir)
    run_git(["config", "user.name", "Test User"], cwd=repo_dir)
    run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)

    math_file = repo_dir / "math_lib.py"
    math_file.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    tests_dir = repo_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_file = tests_dir / "test_math.py"
    test_file.write_text("from math_lib import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")

    run_git(["add", "math_lib.py", "tests/test_math.py"], cwd=repo_dir)
    run_git(["commit", "-m", "initial commit"], cwd=repo_dir)
    return repo_dir


def _setup_direct_developer_chain(service: CompanyService, repo_dir: Path, project_id: str = "proj_dd"):
    service.create_project(project_id, name="Direct Dev Project")
    head_commit = resolve_repo_head_commit(repo_dir)

    # Developer Planning WITHOUT Product or UX artifacts
    dev_task = service.create_task(
        project_id=project_id,
        title="Direct Developer Planning",
        goal="Fix math_lib addition",
        required_roles=["developer"],
    )
    dev_task.allow_direct_developer = True
    dev_run = dev_task.create_run()
    dev_run.status = RunStatus.RUNNING.value
    dev_res = DeveloperTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Plan module directly without product or UX",
        implementation_plan=["Implement math_lib.py addition"],
        files_to_modify=[ProposedFile(path="math_lib.py", description="Fix add function")],
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

    # ExecutionGrant
    grant = ExecutionGrant(
        grant_id=f"grant_{project_id}_01",
        task_id=dev_task.id,
        plan_artifact_id=plan_art.id,
        plan_sha256=plan_art.sha256,
        base_commit_hash=head_commit,
        approved_files_to_modify=("math_lib.py",),
        verification_actions=(VerificationAction("pytest", "tests/test_math.py"),),
        founder_approval_id="founder_direct_appr_1",
    )

    # Initial Failed Patch v1
    patch_task = service.create_task(
        project_id=project_id,
        title="Developer Mutation",
        goal="Create patch",
        required_roles=["developer"],
    )
    patch_run = patch_task.create_run()
    patch_run.status = RunStatus.RUNNING.value
    patch_art = materialize_code_patch_artifact(
        base_output_dir=Path(service.output_dir),
        task=patch_task,
        run=patch_run,
        grant=grant,
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
        verifications=[],
        patch_version=1,
    )
    patch_run.complete(status=RunStatus.SUCCESS.value)
    patch_task.complete(status=TaskStatus.COMPLETED.value, summary="Patch created")

    # QA Inspection (No Product/UX artifacts)
    qa_insp_task = service.create_task(
        project_id=project_id,
        title="QA Inspection",
        goal="Inspect patch",
        required_roles=["qa"],
    )
    service.attach_input_artifact(qa_insp_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, patch_art.id, project_id=project_id)
    qa_insp_run = qa_insp_task.create_run()
    qa_insp_run.status = RunStatus.RUNNING.value
    qa_insp_result = QAInspectionResult(
        schema_version="1.0",
        status=QAInspectionStatus.READY_FOR_QA_EXECUTION.value,
        summary="Direct Dev QA Inspection complete",
        requirements_coverage=[RequirementCoverage(requirement_id="REQ-01", status="COVERED", evidence="tested")],
        recommended_verification_actions=[
            QARecommendedAction(action_type="pytest", target="tests/test_math.py", purpose="Verify math")
        ],
    )
    lineage_meta = {
        "product_artifact_id": None,
        "product_sha256": None,
        "ux_artifact_id": None,
        "ux_sha256": None,
        "developer_plan_artifact_id": plan_art.id,
        "developer_plan_sha256": plan_art.sha256,
        "execution_grant_id": grant.grant_id,
        "code_patch_artifact_id": patch_art.id,
        "code_patch_sha256": patch_art.sha256,
        "base_commit_hash": head_commit,
        "verification_evidence": [],
        "recommended_verification_actions": [
            {"action_type": "pytest", "target": "tests/test_math.py", "purpose": "Verify math"}
        ],
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

    # QA Verification Execution -> Verdict FAIL
    qa_exec_task = service.create_task(
        project_id=project_id,
        task_id=f"{dev_task.id}_qa_verify",
        title="QA Verification",
        goal="Verify patch",
        required_roles=["qa"],
    )
    service.attach_input_artifact(qa_exec_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, patch_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, qa_rep_art.id, project_id=project_id)
    qa_exec_run = qa_exec_task.create_run()
    qa_exec_run.status = RunStatus.RUNNING.value
    verdict_res = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict="FAIL",
        summary="QA Verification failed: addition requirement unmet (assert 4 == 5)",
        requirements_evaluations=[QARequirementExecutionEvaluation("REQ-01", "FAILED", "Output was 4 instead of 5")],
        release_recommendation="HOLD",
    )
    exec_meta = {
        "product_artifact_id": None,
        "product_sha256": None,
        "ux_artifact_id": None,
        "ux_sha256": None,
        "developer_plan_artifact_id": plan_art.id,
        "code_patch_artifact_id": patch_art.id,
        "qa_report_artifact_id": qa_rep_art.id,
        "base_commit_hash": head_commit,
        "action_audits": [
            {
                "action_type": "pytest",
                "target": "tests/test_math.py",
                "purpose": "Verify math",
                "decision": "AUTHORIZED",
                "reason": "Safe target",
            }
        ],
    }
    qa_exec_art = materialize_qa_execution_report_artifact(
        base_output_dir=Path(service.output_dir),
        task=qa_exec_task,
        run=qa_exec_run,
        typed_verdict=verdict_res,
        lineage_metadata=exec_meta,
        execution_evidence=[{
            "action": {"action_type": "pytest", "target": "tests/test_math.py"},
            "passed": False,
            "exit_code": 1,
            "stdout": "FAILED test_add - assert 4 == 5",
        }],
    )
    qa_exec_run.complete(status=RunStatus.SUCCESS.value)
    qa_exec_task.complete(status=TaskStatus.COMPLETED.value, summary=verdict_res.summary, details=verdict_res.to_dict())

    return {
        "dev_task": dev_task,
        "plan_art": plan_art,
        "grant": grant,
        "patch_art": patch_art,
        "qa_rep_art": qa_rep_art,
        "qa_exec_task": qa_exec_task,
        "qa_exec_art": qa_exec_art,
        "head_commit": head_commit,
    }


def _setup_multi_actor_chain(service: CompanyService, repo_dir: Path, project_id: str = "proj_multi"):
    service.create_project(project_id, name="Multi Actor Project")
    head_commit = resolve_repo_head_commit(repo_dir)

    # 1. Product Task & Artifact
    prod_task = service.create_task(
        project_id=project_id,
        title="Product Requirements",
        goal="Define math requirements",
        required_roles=["product"],
    )
    prod_run = prod_task.create_run()
    prod_run.status = RunStatus.RUNNING.value
    prod_res = ProductTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Canonical math spec",
        deliverables=[ProductDeliverable(name="Math Spec", content="Exact addition required")],
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

    # 2. UX Task & Artifact
    ux_task = service.create_task(
        project_id=project_id,
        title="UX Specification",
        goal="Define UX",
        required_roles=["ux"],
    )
    ux_run = ux_task.create_run()
    ux_run.status = RunStatus.RUNNING.value
    ux_res = UXTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Canonical UX spec",
        flows=[UXFlow(name="MathFlow", description="Display numbers clearly", steps=["step1"])],
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

    # 3. Developer Task & Plan
    dev_task = service.create_task(
        project_id=project_id,
        title="Developer Planning",
        goal="Plan implementation",
        required_roles=["developer"],
    )
    service.attach_input_artifact(dev_task.id, prod_art.id, project_id=project_id)
    service.attach_input_artifact(dev_task.id, ux_art.id, project_id=project_id)
    dev_run = dev_task.create_run()
    dev_run.status = RunStatus.RUNNING.value
    dev_res = DeveloperTaskResult(
        schema_version="1.0",
        status="completed",
        summary="Plan module with product & ux",
        implementation_plan=["Implement math_lib.py addition"],
        files_to_modify=[ProposedFile(path="math_lib.py", description="Fix add function")],
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

    grant = ExecutionGrant(
        grant_id=f"grant_{project_id}_01",
        task_id=dev_task.id,
        plan_artifact_id=plan_art.id,
        plan_sha256=plan_art.sha256,
        base_commit_hash=head_commit,
        approved_files_to_modify=("math_lib.py",),
        verification_actions=(VerificationAction("pytest", "tests/test_math.py"),),
        founder_approval_id="founder_multi_appr_1",
    )

    patch_task = service.create_task(
        project_id=project_id,
        title="Developer Mutation",
        goal="Create patch",
        required_roles=["developer"],
    )
    patch_run = patch_task.create_run()
    patch_run.status = RunStatus.RUNNING.value
    patch_art = materialize_code_patch_artifact(
        base_output_dir=Path(service.output_dir),
        task=patch_task,
        run=patch_run,
        grant=grant,
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
        verifications=[],
        patch_version=1,
    )
    patch_run.complete(status=RunStatus.SUCCESS.value)
    patch_task.complete(status=TaskStatus.COMPLETED.value, summary="Patch created")

    qa_insp_task = service.create_task(
        project_id=project_id,
        title="QA Inspection",
        goal="Inspect patch",
        required_roles=["qa"],
    )
    service.attach_input_artifact(qa_insp_task.id, prod_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, ux_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_insp_task.id, patch_art.id, project_id=project_id)
    qa_insp_run = qa_insp_task.create_run()
    qa_insp_run.status = RunStatus.RUNNING.value
    qa_insp_result = QAInspectionResult(
        schema_version="1.0",
        status=QAInspectionStatus.READY_FOR_QA_EXECUTION.value,
        summary="Inspection complete",
        requirements_coverage=[RequirementCoverage(requirement_id="REQ-01", status="COVERED", evidence="tested")],
        recommended_verification_actions=[
            QARecommendedAction(action_type="pytest", target="tests/test_math.py", purpose="Verify math")
        ],
    )
    lineage_meta = {
        "product_artifact_id": prod_art.id,
        "product_sha256": prod_art.sha256,
        "ux_artifact_id": ux_art.id,
        "ux_sha256": ux_art.sha256,
        "developer_plan_artifact_id": plan_art.id,
        "developer_plan_sha256": plan_art.sha256,
        "execution_grant_id": grant.grant_id,
        "code_patch_artifact_id": patch_art.id,
        "code_patch_sha256": patch_art.sha256,
        "base_commit_hash": head_commit,
        "verification_evidence": [],
        "recommended_verification_actions": [
            {"action_type": "pytest", "target": "tests/test_math.py", "purpose": "Verify math"}
        ],
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

    qa_exec_task = service.create_task(
        project_id=project_id,
        task_id=f"{dev_task.id}_qa_verify",
        title="QA Verification",
        goal="Verify patch",
        required_roles=["qa"],
    )
    service.attach_input_artifact(qa_exec_task.id, prod_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, ux_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, plan_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, patch_art.id, project_id=project_id)
    service.attach_input_artifact(qa_exec_task.id, qa_rep_art.id, project_id=project_id)
    qa_exec_run = qa_exec_task.create_run()
    qa_exec_run.status = RunStatus.RUNNING.value
    verdict_res = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict="FAIL",
        summary="QA Verification failed in multi-actor workflow",
        requirements_evaluations=[QARequirementExecutionEvaluation("REQ-01", "FAILED", "Failed calculation")],
        release_recommendation="HOLD",
    )
    exec_meta = {
        "product_artifact_id": prod_art.id,
        "product_sha256": prod_art.sha256,
        "ux_artifact_id": ux_art.id,
        "ux_sha256": ux_art.sha256,
        "developer_plan_artifact_id": plan_art.id,
        "code_patch_artifact_id": patch_art.id,
        "qa_report_artifact_id": qa_rep_art.id,
        "base_commit_hash": head_commit,
        "action_audits": [
            {
                "action_type": "pytest",
                "target": "tests/test_math.py",
                "purpose": "Verify math",
                "decision": "AUTHORIZED",
                "reason": "Safe target",
            }
        ],
    }
    qa_exec_art = materialize_qa_execution_report_artifact(
        base_output_dir=Path(service.output_dir),
        task=qa_exec_task,
        run=qa_exec_run,
        typed_verdict=verdict_res,
        lineage_metadata=exec_meta,
        execution_evidence=[{
            "action": {"action_type": "pytest", "target": "tests/test_math.py"},
            "passed": False,
            "exit_code": 1,
            "stdout": "FAILED test_add",
        }],
    )
    qa_exec_run.complete(status=RunStatus.SUCCESS.value)
    qa_exec_task.complete(status=TaskStatus.COMPLETED.value, summary=verdict_res.summary, details=verdict_res.to_dict())

    return {
        "prod_art": prod_art,
        "ux_art": ux_art,
        "dev_task": dev_task,
        "plan_art": plan_art,
        "grant": grant,
        "patch_art": patch_art,
        "qa_rep_art": qa_rep_art,
        "qa_exec_task": qa_exec_task,
        "qa_exec_art": qa_exec_art,
        "head_commit": head_commit,
    }


# ==============================================================================
# SCENARIO A: Direct Developer Repair Success
# ==============================================================================

def test_scenario_a_direct_developer_repair_success(tmp_path, monkeypatch):
    """CEO-selected direct Developer workflow, no Product/UX artifacts.

    QA returns FAIL. Repair receives original objective and QA evidence,
    produces a corrected authorized patch, passes verification, and reaches QA_PASSED
    with zero null-artifact exceptions.
    """
    repo_dir = _create_base_repo(tmp_path)
    service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
    chain = _setup_direct_developer_chain(service, repo_dir, project_id="proj_dd_success")
    dev_task = chain["dev_task"]
    grant = chain["grant"]

    prompt_inspected = {}

    def mock_runtime_execute(agent, prompt, timeout=60.0, workspace_dir=None, env=None):
        if agent == "developer":
            if "DEVELOPER REPAIR PLANNING MODE" in prompt:
                prompt_inspected["planning_prompt"] = prompt
                plan_json = json.dumps({
                    "schema_version": "1.0",
                    "repair_id": f"repair_{dev_task.id}_iter1",
                    "iteration": 1,
                    "root_cause": "math_lib subtracts 1 from add result",
                    "requirements_to_fix": ["REQ-01"],
                    "files_to_modify": [{"path": "math_lib.py", "description": "Fix return value"}],
                    "files_to_create": [],
                    "files_to_delete": [],
                    "proposed_changes": ["Change return a + b - 1 to return a + b"],
                    "proposed_verification_actions": [{"action_type": "pytest", "target": "tests/test_math.py"}],
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
                    (workspace_dir / "math_lib.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
                mut_json = json.dumps({
                    "status": "success",
                    "summary": "Fixed addition return statement",
                    "modified_files": ["math_lib.py"],
                    "created_files": [],
                    "deleted_files": [],
                    "verification_notes": "Tested locally",
                })
                return AgentExecutionResult(
                    agent="developer",
                    success=True,
                    stdout=f"```json\n{mut_json}\n```",
                    stderr="",
                    exit_code=0,
                    duration_ms=10.0,
                )
        elif agent == "qa":
            if "STEP 14B" in prompt or "evaluating final release readiness" in prompt:
                verdict_json = json.dumps({
                    "schema_version": "1.0",
                    "verdict": "PASS",
                    "summary": "QA verification passed cleanly after repair",
                    "requirements_evaluations": [{"requirement_id": "REQ-01", "status": "SATISFIED", "evidence": "Tested math addition"}],
                    "blocking_issues": [],
                    "release_recommendation": "RELEASE",
                })
                return AgentExecutionResult(agent="qa", success=True, stdout=f"```json\n{verdict_json}\n```", stderr="", exit_code=0, duration_ms=10.0)
            else:
                qa_insp_json = json.dumps({
                    "schema_version": "1.0",
                    "status": "READY_FOR_QA_EXECUTION",
                    "summary": "Repaired code verified safe and ready",
                    "requirements_coverage": [{"requirement_id": "REQ-01", "status": "COVERED", "evidence": "Fixed math"}],
                    "recommended_verification_actions": [
                        {"action_type": "pytest", "target": "tests/test_math.py", "purpose": "Verify math"}
                    ],
                })
                return AgentExecutionResult(agent="qa", success=True, stdout=f"```json\n{qa_insp_json}\n```", stderr="", exit_code=0, duration_ms=10.0)
        return AgentExecutionResult(agent=agent, success=True, stdout="", stderr="", exit_code=0, duration_ms=1.0)

    monkeypatch.setattr(service.runtime, "execute", mock_runtime_execute)

    # Execute Developer <-> QA repair loop using automated SandboxExecutionToken (Stage 0B)
    repair_res = service.execute_developer_qa_repair_loop(
        task_id=dev_task.id,
        founder_approvals=None,
        original_grant=grant,
        max_repair_iterations=2,
        target_repo_root=repo_dir,
        sandbox_run_id="crun_step23b7f1_direct",
    )

    print("TERMINATION REASON:", repair_res.termination_reason)
    assert repair_res.status == RepairWorkflowStatus.QA_PASSED.value
    assert repair_res.repair_iterations_used == 1
    assert "PASSED QA verification on iteration 1" in repair_res.termination_reason
    assert repair_res.final_code_patch_artifact_id is not None
    assert repair_res.final_qa_execution_report_artifact_id is not None

    # Verify planning prompt did NOT have undefined or crash-inducing sections
    assert "CANONICAL PRODUCT SPECIFICATION" not in prompt_inspected.get("planning_prompt", "")
    assert "CANONICAL UX SPECIFICATION" not in prompt_inspected.get("planning_prompt", "")
    assert "ORIGINAL DEVELOPER PLAN" in prompt_inspected.get("planning_prompt", "")
    assert "PREVIOUS CODE_PATCH TEXT" in prompt_inspected.get("planning_prompt", "")

    # Verify repaired patch artifact
    _, _, final_patch = service.find_artifact(repair_res.final_code_patch_artifact_id)
    assert final_patch.metadata.get("patch_version") == 2
    assert final_patch.metadata.get("repair_iteration") == 1
    assert "math_lib.py" in final_patch.metadata.get("changed_files")

    # Verify final diff
    patch_text = (tmp_path / "artifacts" / final_patch.path).read_text(encoding="utf-8")
    assert "-    return a - b" in patch_text
    assert "+    return a + b" in patch_text

    # Main repo remained untouched (canonical integrity preserved)
    assert (repo_dir / "math_lib.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"


# ==============================================================================
# SCENARIO B: Direct Developer Repair Failure
# ==============================================================================

def test_scenario_b_direct_developer_repair_failure(tmp_path, monkeypatch):
    """Direct Developer workflow where repair is unsuccessful.

    Expected: Bounded repair limit reached (REPAIR_LIMIT_REACHED),
    all attempts tracked with evidence, no invalid founder proposal.
    """
    repo_dir = _create_base_repo(tmp_path)
    service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
    chain = _setup_direct_developer_chain(service, repo_dir, project_id="proj_dd_fail")
    dev_task = chain["dev_task"]
    grant = chain["grant"]

    attempts_count = 0

    def mock_runtime_execute(agent, prompt, timeout=60.0, workspace_dir=None, env=None):
        nonlocal attempts_count
        if agent == "developer":
            if "DEVELOPER REPAIR PLANNING MODE" in prompt:
                attempts_count += 1
                plan_json = json.dumps({
                    "schema_version": "1.0",
                    "repair_id": f"repair_{dev_task.id}_iter{attempts_count}",
                    "iteration": attempts_count,
                    "root_cause": "Still cannot fix math",
                    "requirements_to_fix": ["REQ-01"],
                    "files_to_modify": [{"path": "math_lib.py", "description": "Attempted fix"}],
                    "files_to_create": [],
                    "files_to_delete": [],
                    "proposed_changes": ["Try return a * b"],
                    "proposed_verification_actions": [{"action_type": "pytest", "target": "tests/test_math.py"}],
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
                    (workspace_dir / "math_lib.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
                mut_json = json.dumps({
                    "status": "success",
                    "summary": "Attempted fix",
                    "modified_files": ["math_lib.py"],
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
        elif agent == "qa":
            if "STEP 14B" in prompt or "evaluating final release readiness" in prompt:
                verdict_json = json.dumps({
                    "schema_version": "1.0",
                    "verdict": "FAIL",
                    "summary": "QA verification failed: test assertions unmet",
                    "requirements_evaluations": [{"requirement_id": "REQ-01", "status": "FAILED", "evidence": "assert failed"}],
                    "blocking_issues": ["Calculation mismatch"],
                    "release_recommendation": "HOLD",
                })
                return AgentExecutionResult(agent="qa", success=True, stdout=f"```json\n{verdict_json}\n```", stderr="", exit_code=0, duration_ms=10.0)
            else:
                qa_insp_json = json.dumps({
                    "schema_version": "1.0",
                    "status": "READY_FOR_QA_EXECUTION",
                    "summary": "Reinspection complete",
                    "requirements_coverage": [{"requirement_id": "REQ-01", "status": "COVERED", "evidence": "Tested"}],
                    "recommended_verification_actions": [
                        {"action_type": "pytest", "target": "tests/test_math.py", "purpose": "Verify math"}
                    ],
                })
                return AgentExecutionResult(agent="qa", success=True, stdout=f"```json\n{qa_insp_json}\n```", stderr="", exit_code=0, duration_ms=10.0)
        return AgentExecutionResult(agent=agent, success=True, stdout="", stderr="", exit_code=0, duration_ms=1.0)

    monkeypatch.setattr(service.runtime, "execute", mock_runtime_execute)

    repair_res = service.execute_developer_qa_repair_loop(
        task_id=dev_task.id,
        founder_approvals={1: "founder_appr_1", 2: "founder_appr_2"},
        original_grant=grant,
        max_repair_iterations=2,
        target_repo_root=repo_dir,
    )

    # Verifications
    assert repair_res.status == RepairWorkflowStatus.REPAIR_LIMIT_REACHED.value
    assert repair_res.repair_iterations_used == 2
    assert "Reached maximum allowed repair iterations (2)" in repair_res.termination_reason
    assert len(repair_res.attempts) == 2
    for attempt in repair_res.attempts:
        assert attempt.qa_verdict == "FAIL"
        assert attempt.status == "COMPLETED"


# ==============================================================================
# SCENARIO C: Product + UX Engineering Repair
# ==============================================================================

def test_scenario_c_product_ux_engineering_repair(tmp_path, monkeypatch):
    """Multi-actor workflow with verified Product & UX artifacts.

    QA returns FAIL. Repair loop retains complete upstream dependency chain,
    preserves Product/UX artifact IDs and hashes, and passes cleanly.
    """
    repo_dir = _create_base_repo(tmp_path)
    service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
    chain = _setup_multi_actor_chain(service, repo_dir, project_id="proj_multi_succ")
    dev_task = chain["dev_task"]
    grant = chain["grant"]
    prod_art = chain["prod_art"]
    ux_art = chain["ux_art"]

    prompt_inspected = {}

    def mock_runtime_execute(agent, prompt, timeout=60.0, workspace_dir=None, env=None):
        if agent == "developer":
            if "DEVELOPER REPAIR PLANNING MODE" in prompt:
                prompt_inspected["planning_prompt"] = prompt
                plan_json = json.dumps({
                    "schema_version": "1.0",
                    "repair_id": f"repair_{dev_task.id}_iter1",
                    "iteration": 1,
                    "root_cause": "Fix logic according to product spec",
                    "requirements_to_fix": ["REQ-01"],
                    "files_to_modify": [{"path": "math_lib.py", "description": "Fix return"}],
                    "files_to_create": [],
                    "files_to_delete": [],
                    "proposed_changes": ["Return a + b"],
                    "proposed_verification_actions": [{"action_type": "pytest", "target": "tests/test_math.py"}],
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
                    (workspace_dir / "math_lib.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
                mut_json = json.dumps({
                    "status": "success",
                    "summary": "Fixed return",
                    "modified_files": ["math_lib.py"],
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
        elif agent == "qa":
            if "STEP 14B" in prompt or "evaluating final release readiness" in prompt:
                verdict_json = json.dumps({
                    "schema_version": "1.0",
                    "verdict": "PASS",
                    "summary": "QA verification passed cleanly in multi-actor workflow",
                    "requirements_evaluations": [{"requirement_id": "REQ-01", "status": "SATISFIED", "evidence": "Tested math addition"}],
                    "blocking_issues": [],
                    "release_recommendation": "RELEASE",
                })
                return AgentExecutionResult(agent="qa", success=True, stdout=f"```json\n{verdict_json}\n```", stderr="", exit_code=0, duration_ms=10.0)
            else:
                qa_insp_json = json.dumps({
                    "schema_version": "1.0",
                    "status": "READY_FOR_QA_EXECUTION",
                    "summary": "Reinspection complete",
                    "requirements_coverage": [{"requirement_id": "REQ-01", "status": "COVERED", "evidence": "Tested"}],
                    "recommended_verification_actions": [
                        {"action_type": "pytest", "target": "tests/test_math.py", "purpose": "Verify math"}
                    ],
                })
                return AgentExecutionResult(agent="qa", success=True, stdout=f"```json\n{qa_insp_json}\n```", stderr="", exit_code=0, duration_ms=10.0)
        return AgentExecutionResult(agent=agent, success=True, stdout="", stderr="", exit_code=0, duration_ms=1.0)

    monkeypatch.setattr(service.runtime, "execute", mock_runtime_execute)

    repair_res = service.execute_developer_qa_repair_loop(
        task_id=dev_task.id,
        founder_approvals={1: "founder_multi_repair_1"},
        original_grant=grant,
        max_repair_iterations=2,
        target_repo_root=repo_dir,
    )

    assert repair_res.status == RepairWorkflowStatus.QA_PASSED.value
    assert repair_res.repair_iterations_used == 1

    # Verify Product and UX specifications were included in the repair prompt
    assert "CANONICAL PRODUCT SPECIFICATION" in prompt_inspected["planning_prompt"]
    assert "Exact addition required" in prompt_inspected["planning_prompt"]
    assert "CANONICAL UX SPECIFICATION" in prompt_inspected["planning_prompt"]
    assert "Display numbers clearly" in prompt_inspected["planning_prompt"]

    # Verify latest QA execution report preserved product and UX lineage
    _, _, final_qa_exec = service.find_artifact(repair_res.final_qa_execution_report_artifact_id)
    assert final_qa_exec.metadata.get("product_artifact_id") == prod_art.id
    assert final_qa_exec.metadata.get("ux_artifact_id") == ux_art.id


# ==============================================================================
# SCENARIO D: Missing Mandatory Artifact (Fail Closed)
# ==============================================================================

def test_scenario_d_missing_mandatory_artifact_fails_closed(tmp_path):
    """DAG required Product artifact, but product_artifact_id is missing or corrupted.

    Expected: Explicit validation failure (RepairError / ArtifactVerificationError).
    Must NOT silently convert to Direct Developer mode.
    """
    repo_dir = _create_base_repo(tmp_path)
    service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
    chain = _setup_multi_actor_chain(service, repo_dir, project_id="proj_missing_art")
    dev_task = chain["dev_task"]
    grant = chain["grant"]
    qa_exec_art = chain["qa_exec_art"]

    # Case 1: Corrupt metadata by removing product_artifact_id from QA report
    qa_exec_art.metadata["product_artifact_id"] = None

    with pytest.raises(RepairError, match="Missing or mismatched mandatory Product artifact"):
        service.execute_developer_qa_repair_loop(
            task_id=dev_task.id,
            founder_approvals={1: "appr_1"},
            original_grant=grant,
            target_repo_root=repo_dir,
        )

    # Case 2: Product artifact file is deleted from disk
    prod_art = chain["prod_art"]
    qa_exec_art.metadata["product_artifact_id"] = prod_art.id

    disk_file = Path(service.output_dir) / prod_art.path
    if disk_file.is_file():
        disk_file.unlink()

    with pytest.raises(Exception) as exc_info:
        service.execute_developer_qa_repair_loop(
            task_id=dev_task.id,
            founder_approvals={1: "appr_1"},
            original_grant=grant,
            target_repo_root=repo_dir,
        )
    assert "Artifact file not found" in str(exc_info.value) or "does not exist" in str(exc_info.value)


# ==============================================================================
# SCENARIO E: Repair Authorization (Scope Enforcement)
# ==============================================================================

def test_scenario_e_repair_authorization_scope_enforcement(tmp_path, monkeypatch):
    """Repair attempts to modify a protected file or file outside grant boundaries.

    Expected: Repair grant derivation or mutation fails, no canonical repo changes.
    """
    repo_dir = _create_base_repo(tmp_path)
    service = CompanyService(repo_root=repo_dir, output_dir=tmp_path / "artifacts")
    chain = _setup_direct_developer_chain(service, repo_dir, project_id="proj_scope_enf")
    dev_task = chain["dev_task"]
    grant = chain["grant"]

    # Developer repair plan proposes modifying protected path .git/config
    def mock_illegal_planning(agent, prompt, timeout=60.0, workspace_dir=None, env=None):
        if agent == "developer" and "DEVELOPER REPAIR PLANNING MODE" in prompt:
            plan_json = json.dumps({
                "schema_version": "1.0",
                "repair_id": f"repair_{dev_task.id}_iter1",
                "iteration": 1,
                "root_cause": "Attempt breach",
                "requirements_to_fix": ["REQ-01"],
                "files_to_modify": [{"path": ".git/config", "description": "Protected path attempt"}],
                "files_to_create": [],
                "files_to_delete": [],
                "proposed_changes": ["Modify git config"],
                "proposed_verification_actions": [{"action_type": "pytest", "target": "tests/test_math.py"}],
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
        return AgentExecutionResult(agent=agent, success=True, stdout="", stderr="", exit_code=0, duration_ms=1.0)

    monkeypatch.setattr(service.runtime, "execute", mock_illegal_planning)

    repair_res = service.execute_developer_qa_repair_loop(
        task_id=dev_task.id,
        founder_approvals={1: "appr_1"},
        original_grant=grant,
        max_repair_iterations=2,
        target_repo_root=repo_dir,
    )

    # Must be rejected at grant boundary
    assert repair_res.status == RepairWorkflowStatus.REPAIR_GRANT_REJECTED.value
    assert "protected path" in repair_res.termination_reason.lower()
    # Canonical repo untouched
    assert (repo_dir / "math_lib.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"
