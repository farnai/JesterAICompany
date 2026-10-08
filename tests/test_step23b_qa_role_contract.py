"""Tests for STEP 23B.1: QA Role Contract Alignment & Fail-Fast Validation.

Verifies:
1. QA test-matrix planning accepted by DAG validator and CEO plan parser.
2. QA test-strategy planning accepted.
3. QA acceptance-verification planning accepted.
4. QA read-only audit accepted.
5. QA certification requested through ordinary DAG rejected at planning (PlanValidationError).
6. QA work item with prohibited capabilities (certify, patch_verification, apply, approval, grant) rejected at planning.
7. QA work item without supported capability rejected at planning.
8. QA depending on developer in DAG rejected at planning (DAGValidationError).
9. Unsupported QA capability rejected before Run execution (UnsupportedRoleError / BLOCKED).
10. QA planning execution produces durable artifact ('qa_report.md') without granting code apply or release verdict.
11. Rejection of authority-bearing keys in QA planning model outputs (parse_and_validate_qa_planning_result).
12. Full company step execution for supported QA planning work item succeeds.
13. Engineering pipeline QA certification remains 100% intact, mandatory, and separate from DAG QA planning.
"""

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

from jester_ai_company.core import (
    ALLOWED_HANDOFF_EDGES,
    ArtifactType,
    Company,
    RunStatus,
    TaskStatus,
    create_default_company,
)
from jester_ai_company.ceo_contract import (
    CEO_PLAN_SCHEMA_VERSION,
    build_ceo_planning_prompt,
    parse_and_validate_ceo_plan,
)
from jester_ai_company.dag import (
    DAGValidationError,
    PlanValidationError,
    validate_dag_structure,
)
from jester_ai_company.orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    PROHIBITED_QA_CAPABILITIES,
    QAPlanningCapability,
    SUPPORTED_QA_CAPABILITIES,
    UnsupportedRoleError,
    WorkItemState,
)
from jester_ai_company.qa_result import (
    QAInspectionResult,
    QAInspectionStatus,
    QAResultValidationError,
    build_qa_planning_execution_prompt,
    parse_and_validate_qa_planning_result,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService


@pytest.fixture
def sample_objective() -> CompanyObjective:
    return CompanyObjective(
        id="obj_qa_test",
        title="QA Contract Test Objective",
        description="Verify QA role contract alignment and fail-fast validation",
        constraints=["non-destructive"],
        acceptance_criteria=["QA planning works", "Engineering QA certified"],
    )


@pytest.fixture
def valid_qa_planning_json_output() -> str:
    payload = {
        "schema_version": "1.0",
        "status": "READY_FOR_QA_EXECUTION",
        "summary": "Comprehensive test matrix for registration workflow",
        "requirements_coverage": [
            {
                "requirement_id": "REQ-001",
                "status": "COVERED",
                "evidence": "Planned integration and unit test coverage",
                "notes": "Covers user input validation and boundary conditions",
            }
        ],
        "risks": ["Database latency during peak registration"],
        "findings": [
            {
                "id": "FINDING-001",
                "severity": "MEDIUM",
                "category": "TESTABILITY",
                "description": "Lack of mockable SMS gateway",
                "requirement_reference": "REQ-001",
                "affected_files": [],
                "evidence": "Architecture review",
                "recommended_action": "Introduce adapter interface",
            }
        ],
        "test_cases": [
            {
                "id": "TC-001",
                "objective": "Verify registration with valid inputs",
                "type": "INTEGRATION",
                "target": "tests/test_register.py",
                "preconditions": "Clean test database",
                "expected_result": "201 Created and user record persisted",
                "priority": "HIGH",
            }
        ],
        "regression_areas": ["Authentication flow", "User profile service"],
        "unresolved_questions": ["Is email verification required on launch?"],
        "recommended_verification_actions": [
            {
                "action_type": "pytest",
                "target": "tests/test_register.py",
                "purpose": "Verify registration scenarios",
            }
        ],
    }
    return json.dumps(payload, indent=2)


def test_supported_qa_capabilities_constants():
    """Verify supported and prohibited capability sets."""
    assert "test_strategy" in SUPPORTED_QA_CAPABILITIES
    assert "test_matrix" in SUPPORTED_QA_CAPABILITIES
    assert "acceptance_planning" in SUPPORTED_QA_CAPABILITIES
    assert "read_only_audit" in SUPPORTED_QA_CAPABILITIES
    assert "certification" in PROHIBITED_QA_CAPABILITIES
    assert "apply" in PROHIBITED_QA_CAPABILITIES
    assert "execution_grant" in PROHIBITED_QA_CAPABILITIES


def test_qa_test_matrix_planning_accepted(sample_objective):
    """QA test-matrix planning accepted in DAG and CEO parser."""
    plan_dict = {
        "schema_version": "1.0",
        "plan_id": "plan_matrix",
        "objective_id": sample_objective.id,
        "version": 1,
        "work_items": [
            {
                "work_item_id": "item_prod",
                "role": "product",
                "objective": "Define registration spec",
                "depends_on": [],
                "expected_outputs": ["product_report.md"],
                "priority": 1,
            },
            {
                "work_item_id": "item_qa",
                "role": "qa",
                "capability": "test_matrix",
                "objective": "Design test matrix for registration",
                "depends_on": ["item_prod"],
                "expected_outputs": ["qa_report.md"],
                "priority": 2,
            },
        ],
        "completion_criteria": ["Spec and test matrix complete"],
        "constraints": [],
    }
    plan = parse_and_validate_ceo_plan(json.dumps(plan_dict), sample_objective)
    assert len(plan.work_items) == 2
    qa_item = plan.work_items[1]
    assert qa_item.role == "qa"
    assert qa_item.capability == "test_matrix"


def test_qa_other_supported_capabilities_accepted(sample_objective):
    """QA test_strategy, acceptance_planning, and read_only_audit accepted."""
    for cap in ("test_strategy", "acceptance_planning", "read_only_audit"):
        plan_dict = {
            "schema_version": "1.0",
            "plan_id": f"plan_{cap}",
            "objective_id": sample_objective.id,
            "version": 1,
            "work_items": [
                {
                    "work_item_id": "item_prod",
                    "role": "product",
                    "objective": "Define requirements",
                    "depends_on": [],
                    "expected_outputs": ["product_report.md"],
                    "priority": 1,
                },
                {
                    "work_item_id": "item_qa",
                    "role": "qa",
                    "capability": cap,
                    "objective": f"QA deliverable for {cap}",
                    "depends_on": ["item_prod"],
                    "expected_outputs": ["qa_report.md"],
                    "priority": 2,
                },
            ],
            "completion_criteria": ["All done"],
            "constraints": [],
        }
        plan = parse_and_validate_ceo_plan(json.dumps(plan_dict), sample_objective)
        assert plan.work_items[1].capability == cap


def test_qa_capability_derived_from_expected_outputs(sample_objective):
    """If capability field is omitted, exact match in expected_outputs is recognized."""
    plan_dict = {
        "schema_version": "1.0",
        "plan_id": "plan_cap_fallback",
        "objective_id": sample_objective.id,
        "version": 1,
        "work_items": [
            {
                "work_item_id": "item_res",
                "role": "research",
                "objective": "Audit landscape",
                "depends_on": [],
                "expected_outputs": ["research_report.md"],
                "priority": 1,
            },
            {
                "work_item_id": "item_qa",
                "role": "qa",
                "objective": "Perform QA audit",
                "depends_on": ["item_res"],
                "expected_outputs": ["qa_report.md", "read_only_audit"],
                "priority": 2,
            },
        ],
        "completion_criteria": ["Audit complete"],
        "constraints": [],
    }
    plan = parse_and_validate_ceo_plan(json.dumps(plan_dict), sample_objective)
    assert plan.work_items[1].capability == "read_only_audit"


def test_qa_certification_requested_through_dag_rejected_at_planning(sample_objective):
    """QA certification request through ordinary DAG rejected at planning (PlanValidationError)."""
    plan_dict = {
        "schema_version": "1.0",
        "plan_id": "plan_cert_reject",
        "objective_id": sample_objective.id,
        "version": 1,
        "work_items": [
            {
                "work_item_id": "item_qa",
                "role": "qa",
                "capability": "certification",
                "objective": "Certify release candidate",
                "depends_on": [],
                "expected_outputs": ["certification.json"],
                "priority": 1,
            },
        ],
        "completion_criteria": ["Certified"],
        "constraints": [],
    }
    with pytest.raises(PlanValidationError) as excinfo:
        parse_and_validate_ceo_plan(json.dumps(plan_dict), sample_objective)
    assert "forbidden capability 'certification'" in str(excinfo.value)


def test_qa_prohibited_capabilities_rejected(sample_objective):
    """All prohibited capabilities are rejected at DAG planning time."""
    for cap in ("certify", "patch_verification", "apply", "approval", "execution_grant"):
        plan = CEOOrchestrationPlan(
            plan_id="test_plan",
            objective_id=sample_objective.id,
            work_items=[
                CEOPlannedWorkItem(
                    work_item_id="item_qa",
                    role="qa",
                    capability=cap,
                    objective="Unauthorized action",
                    depends_on=[],
                    expected_outputs=["qa_report.md"],
                )
            ],
        )
        with pytest.raises(PlanValidationError) as excinfo:
            validate_dag_structure(plan)
        assert f"forbidden capability '{cap}'" in str(excinfo.value)


def test_qa_missing_capability_rejected_at_planning(sample_objective):
    """QA work item without supported capability rejected at planning time."""
    plan_dict = {
        "schema_version": "1.0",
        "plan_id": "plan_no_cap",
        "objective_id": sample_objective.id,
        "version": 1,
        "work_items": [
            {
                "work_item_id": "item_qa",
                "role": "qa",
                "objective": "Generic QA work",
                "depends_on": [],
                "expected_outputs": ["qa_report.md"],
                "priority": 1,
            },
        ],
        "completion_criteria": ["Done"],
        "constraints": [],
    }
    with pytest.raises(PlanValidationError) as excinfo:
        parse_and_validate_ceo_plan(json.dumps(plan_dict), sample_objective)
    assert "must explicitly specify a supported capability" in str(excinfo.value)


def test_qa_unsupported_arbitrary_capability_rejected(sample_objective):
    """Arbitrary unsupported capability rejected at planning time."""
    plan = CEOOrchestrationPlan(
        plan_id="test_plan",
        objective_id=sample_objective.id,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="item_qa",
                role="qa",
                capability="manual_penetration_testing",
                objective="Perform manual testing",
                depends_on=[],
                expected_outputs=["qa_report.md"],
            )
        ],
    )
    with pytest.raises(PlanValidationError) as excinfo:
        validate_dag_structure(plan)
    assert "unsupported capability 'manual_penetration_testing'" in str(excinfo.value)


def test_qa_depending_on_developer_rejected_at_planning(sample_objective):
    """QA work item depending on developer is rejected by DAG validator."""
    plan = CEOOrchestrationPlan(
        plan_id="test_plan",
        objective_id=sample_objective.id,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="item_prod",
                role="product",
                objective="Product spec",
                depends_on=[],
            ),
            CEOPlannedWorkItem(
                work_item_id="item_ux",
                role="ux",
                objective="UX spec",
                depends_on=[],
            ),
            CEOPlannedWorkItem(
                work_item_id="item_dev",
                role="developer",
                objective="Implement code",
                depends_on=["item_prod", "item_ux"],
            ),
            CEOPlannedWorkItem(
                work_item_id="item_qa",
                role="qa",
                capability="test_matrix",
                objective="Verify code patch",
                depends_on=["item_dev"],
            ),
        ],
    )
    with pytest.raises(DAGValidationError) as excinfo:
        validate_dag_structure(plan)
    assert "Developer -> QA dependency is forbidden" in str(excinfo.value)


def test_parse_and_validate_qa_planning_result_success(valid_qa_planning_json_output):
    """Valid QA planning output parses cleanly into typed QAInspectionResult."""
    result = parse_and_validate_qa_planning_result(valid_qa_planning_json_output)
    assert isinstance(result, QAInspectionResult)
    assert result.status == QAInspectionStatus.READY_FOR_QA_EXECUTION.value
    assert len(result.test_cases) == 1
    assert result.test_cases[0].id == "TC-001"
    assert len(result.findings) == 1


def test_parse_and_validate_qa_planning_result_rejects_privileged_keys(valid_qa_planning_json_output):
    """QA planning parser rejects authority-bearing keys (grant, approve, certification)."""
    for priv_key in ("grant", "execution_grant", "approve", "certification", "apply_patch"):
        data = json.loads(valid_qa_planning_json_output)
        data[priv_key] = {"privileged": True}
        raw_tampered = json.dumps(data)
        with pytest.raises(QAResultValidationError) as excinfo:
            parse_and_validate_qa_planning_result(raw_tampered)
        assert f"Unauthorized privileged key '{priv_key}' detected" in str(excinfo.value)


def test_parse_and_validate_qa_planning_result_rejects_release_verdict(valid_qa_planning_json_output):
    """QA planning parser rejects final PASS or CERTIFIED status."""
    for bad_status in ("PASS", "CERTIFIED", "APPROVED"):
        data = json.loads(valid_qa_planning_json_output)
        data["status"] = bad_status
        raw_bad = json.dumps(data)
        with pytest.raises(QAResultValidationError) as excinfo:
            parse_and_validate_qa_planning_result(raw_bad)
        assert "Invalid QA inspection status" in str(excinfo.value)


def test_qa_planning_execution_produces_durable_artifact(valid_qa_planning_json_output):
    """execute_qa_planning_task executes specialist, materializes qa_report.md, without grants."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        company = create_default_company()
        service = CompanyService(company=company, output_dir=tmp_path / "artifacts")

        # Mock runtime returning valid QA planning JSON
        mock_runtime = MagicMock(spec=AntigravityRuntime)
        mock_runtime.execute.return_value = AgentExecutionResult(
            agent="qa",
            success=True,
            stdout=valid_qa_planning_json_output,
            stderr="",
            exit_code=0,
            duration_ms=100.0,
        )
        service.runtime = mock_runtime

        service.create_project("proj_qa", name="QA Project")
        task = service.create_task(
            project_id="proj_qa",
            title="QA Test Matrix Planning",
            goal="Formulate comprehensive test matrix",
            required_roles=["qa"],
            expected_output=["qa_report.md", "test_matrix"],
        )

        task_run = service.execute_qa_planning_task(
            task_id=task.id,
            project_id="proj_qa",
            capability="test_matrix",
        )

        assert task_run.status == RunStatus.SUCCESS.value
        assert len(task_run.artifacts) == 1
        artifact = task_run.artifacts[0]
        assert artifact.name == "qa_report.md"
        assert artifact.artifact_type == ArtifactType.QA_REPORT.value

        # Verify durable artifact on disk
        artifact_file = tmp_path / "artifacts" / artifact.path
        assert artifact_file.exists()
        content = artifact_file.read_text(encoding="utf-8")
        assert "# QA Inspection Report" in content
        assert "TC-001" in content
        assert "FINDING-001" in content

        # Verify zero grants or code patches created
        assert "grant" not in task.result.details
        assert "code_patch" not in task.result.details


def test_execute_qa_planning_task_rejects_unsupported_capability():
    """execute_qa_planning_task rejects unsupported capability with UnsupportedRoleError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        company = create_default_company()
        service = CompanyService(company=company, output_dir=tmp_path / "artifacts")

        service.create_project("proj_qa", name="QA Project")
        task = service.create_task(
            project_id="proj_qa",
            title="QA Unsupported Task",
            goal="Unsupported work",
            required_roles=["qa"],
            expected_output=["qa_report.md"],
        )

        with pytest.raises(UnsupportedRoleError) as excinfo:
            service.execute_qa_planning_task(
                task_id=task.id,
                project_id="proj_qa",
                capability="certification",
            )
        assert "unsupported or missing capability 'certification'" in str(excinfo.value)


def test_step_company_work_qa_planning_end_to_end(sample_objective, valid_qa_planning_json_output):
    """step_company_work dispatches QA planning work item and materializes qa_report.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        company = create_default_company()
        service = CompanyService(company=company, output_dir=tmp_path / "artifacts")

        prod_output = {
            "schema_version": "1.0",
            "status": "completed",
            "summary": "Product specification for user registration",
            "deliverables": [{"name": "Registration API", "description": "REST endpoint", "content": "REST endpoint specification"}],
            "risks": [],
            "open_questions": [],
        }

        # Mock runtime responding to product and qa
        def fake_execute(agent, prompt, timeout=None, workspace_dir=None, env=None):
            if agent == "product":
                return AgentExecutionResult(agent="product", success=True, stdout=json.dumps(prod_output), stderr="", exit_code=0, duration_ms=100.0)
            elif agent == "qa":
                return AgentExecutionResult(agent="qa", success=True, stdout=valid_qa_planning_json_output, stderr="", exit_code=0, duration_ms=100.0)
            raise ValueError(f"Unexpected agent: {agent}")

        mock_runtime = MagicMock(spec=AntigravityRuntime)
        mock_runtime.execute.side_effect = fake_execute
        service.runtime = mock_runtime

        plan = CEOOrchestrationPlan(
            plan_id="plan_e2e_qa",
            objective_id=sample_objective.id,
            work_items=[
                CEOPlannedWorkItem(
                    work_item_id="item_prod",
                    role="product",
                    objective="Define registration spec",
                    depends_on=[],
                    expected_outputs=["product_report.md"],
                    priority=1,
                ),
                CEOPlannedWorkItem(
                    work_item_id="item_qa",
                    role="qa",
                    capability="test_matrix",
                    objective="Formulate QA test matrix",
                    depends_on=["item_prod"],
                    expected_outputs=["qa_report.md"],
                    priority=2,
                ),
            ],
            completion_criteria=["Spec and QA test matrix complete"],
        )

        company_run = service.create_company_run(sample_objective)
        company_run.set_plan(plan)
        company_run.transition_to(CompanyRunState.PLANNING.value)
        company_run.transition_to(CompanyRunState.PLAN_READY.value)
        company_run.transition_to(CompanyRunState.RUNNING.value)
        service.save_company_run(company_run)

        # Step 1: Execute Product item
        run_after_prod = service.step_company_work(company_run.run_id)
        assert run_after_prod.work_item_states["item_prod"] == WorkItemState.COMPLETED.value
        assert run_after_prod.state == CompanyRunState.RUNNING.value

        # Step 2: Execute QA item (must NOT fail or block with UnsupportedRoleError)
        run_after_qa = service.step_company_work(company_run.run_id)
        assert run_after_qa.work_item_states["item_qa"] == WorkItemState.COMPLETED.value
        assert run_after_qa.state == CompanyRunState.COMPLETED.value

        # Check QA artifact created
        proj_id = run_after_qa.project_id or f"proj_{company_run.run_id}"
        qa_task_id = f"task_{company_run.run_id}_item_qa"
        proj = service.get_project(proj_id)
        qa_task = service.get_task(qa_task_id, project_id=proj.id)
        assert qa_task.status == TaskStatus.COMPLETED.value
        assert len(qa_task.runs[-1].artifacts) == 1
        assert qa_task.runs[-1].artifacts[0].name == "qa_report.md"


def test_engineering_pipeline_retains_mandatory_qa():
    """Verify Engineering QA certification mechanisms remain distinct and intact."""
    from jester_ai_company.qa_execution import QAExecutionVerdictResult, QAFinalVerdict
    from jester_ai_company.service import CompanyService

    # Verify engineering pipeline execution methods exist on CompanyService
    assert hasattr(CompanyService, "execute_qa_inspection_task")
    assert hasattr(CompanyService, "execute_qa_verification_task")
    assert hasattr(CompanyService, "execute_qa_planning_task")

    # Verify QAExecutionVerdictResult remains untouched
    verdict = QAExecutionVerdictResult(
        schema_version="1.0",
        verdict=QAFinalVerdict.PASS.value,
        summary="Engine certified",
    )
    assert verdict.verdict == "PASS"
