"""Tests for STEP 17B-1: Orchestrator Domain Models and Schemas.

Covers requirements:
A. CompanyObjective valid construction and serialization
B. CompanyRun valid construction and serialization
C. Canonical CompanyRun states serialize correctly
D. READY_FOR_HUMAN_APPLY exists in CompanyRunState
E. READY_FOR_APPLY does NOT exist in CompanyRunState
Z. CEOOrchestrationPlan serialization round-trip
AA. CompanyRun serialization round-trip
AB. Malformed serialized state rejected (fail-closed)
AC. Plan version preserved
AD. Plan history preserves old versions
AE. CEOActionType contains no privileged mutation/apply/grant actions
Security tests: CEOAction rejects privileged action types
HumanEscalation and EmployeeResultSummary valid construction and round-trips
"""

import json
import pytest

from jester_ai_company.orchestrator import (
    CEOAction,
    CEOActionType,
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    EmployeeResultSummary,
    HumanEscalation,
    OrchestrationError,
    PlanValidationError,
    TransitionPolicyError,
    WorkItemState,
)


def test_requirement_a_company_objective_valid_construction():
    """Requirement A: CompanyObjective valid construction and serialization."""
    obj = CompanyObjective(
        id="obj_101",
        title="Implement Rate Limiting",
        description="Add sliding window rate limiting to API endpoints.",
        constraints=["Zero external network dependencies", "Python 3.11+"],
        acceptance_criteria=["Return 429 when quota exceeded", "100% unit test pass"],
        target_repository="/repos/jester",
    )
    assert obj.id == "obj_101"
    assert obj.title == "Implement Rate Limiting"
    assert obj.created_by == "HUMAN"
    assert len(obj.constraints) == 2
    assert len(obj.acceptance_criteria) == 2

    # Serialization round-trip
    d = obj.to_dict()
    assert d["id"] == "obj_101"
    assert d["created_by"] == "HUMAN"

    restored = CompanyObjective.from_dict(d)
    assert restored.id == obj.id
    assert restored.title == obj.title
    assert restored.description == obj.description
    assert restored.constraints == obj.constraints
    assert restored.acceptance_criteria == obj.acceptance_criteria
    assert restored.target_repository == obj.target_repository


def test_company_objective_missing_fields_rejected():
    """CompanyObjective fails closed on missing or empty required fields."""
    with pytest.raises(OrchestrationError, match="missing or invalid 'id'"):
        CompanyObjective.from_dict({"title": "Test", "description": "Desc"})

    with pytest.raises(OrchestrationError, match="missing or invalid 'title'"):
        CompanyObjective.from_dict({"id": "1", "title": "  ", "description": "Desc"})

    with pytest.raises(OrchestrationError, match="missing or invalid 'description'"):
        CompanyObjective.from_dict({"id": "1", "title": "Test", "description": ""})


def test_requirement_b_company_run_valid_construction():
    """Requirement B: CompanyRun valid construction and initial state."""
    obj = CompanyObjective(
        id="obj_202",
        title="Test Mission",
        description="Validate company run lifecycle.",
    )
    run = CompanyRun(
        run_id="run_c_001",
        objective=obj,
    )
    assert run.run_id == "run_c_001"
    assert run.state == CompanyRunState.CREATED.value
    assert run.active_plan is None
    assert len(run.plan_history) == 0
    assert run.ceo_invocation_count == 0
    assert run.specialist_invocation_count == 0
    assert run.replan_count == 0


def test_requirement_c_canonical_company_run_states():
    """Requirement C: Canonical CompanyRun states serialize correctly."""
    expected_states = {
        "CREATED",
        "PLANNING",
        "PLAN_READY",
        "RUNNING",
        "WAITING_FOR_HUMAN",
        "READY_FOR_HUMAN_APPLY",
        "APPLYING",
        "COMPLETED",
        "BLOCKED",
        "FAILED",
    }
    actual_states = {s.value for s in CompanyRunState}
    assert actual_states == expected_states

    # Verify each state serializes as a string matching its name
    for s in CompanyRunState:
        assert s.value == s.name


def test_requirement_d_e_ready_for_human_apply_security_boundary():
    """Requirements D & E: READY_FOR_HUMAN_APPLY exists; READY_FOR_APPLY does NOT exist."""
    assert hasattr(CompanyRunState, "READY_FOR_HUMAN_APPLY")
    assert CompanyRunState.READY_FOR_HUMAN_APPLY.value == "READY_FOR_HUMAN_APPLY"

    # CRITICAL: Verify READY_FOR_APPLY is strictly absent
    assert not hasattr(CompanyRunState, "READY_FOR_APPLY")
    assert "READY_FOR_APPLY" not in {s.value for s in CompanyRunState}


def test_requirement_z_plan_serialization_round_trip():
    """Requirement Z: CEOOrchestrationPlan serialization round-trip."""
    item1 = CEOPlannedWorkItem(
        work_item_id="item_prod",
        role="product",
        objective="Draft PRD",
        depends_on=[],
        expected_outputs=["PRD.md"],
        priority=1,
    )
    item2 = CEOPlannedWorkItem(
        work_item_id="item_ux",
        role="ux",
        objective="Draft UX Spec",
        depends_on=["item_prod"],
        expected_outputs=["UX.md"],
        priority=2,
    )
    plan = CEOOrchestrationPlan(
        plan_id="plan_001",
        objective_id="obj_101",
        version=1,
        work_items=[item1, item2],
        completion_criteria=["PRD and UX approved"],
        constraints=["No code changes in phase 1"],
    )

    plan_dict = plan.to_dict()
    assert plan_dict["schema_version"] == "1.0"
    assert plan_dict["plan_id"] == "plan_001"
    assert len(plan_dict["work_items"]) == 2

    # Round trip
    restored = CEOOrchestrationPlan.from_dict(plan_dict)
    assert restored.plan_id == plan.plan_id
    assert restored.objective_id == plan.objective_id
    assert restored.version == 1
    assert len(restored.work_items) == 2
    assert restored.work_items[0].work_item_id == "item_prod"
    assert restored.work_items[0].role == "product"
    assert restored.work_items[1].work_item_id == "item_ux"
    assert restored.work_items[1].depends_on == ["item_prod"]


def test_requirement_aa_company_run_serialization_round_trip():
    """Requirement AA: CompanyRun serialization round-trip."""
    obj = CompanyObjective(
        id="obj_303",
        title="Round Trip Objective",
        description="Test complete serialization.",
    )
    plan = CEOOrchestrationPlan(
        plan_id="plan_v1",
        objective_id=obj.id,
        version=1,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="i1",
                role="research",
                objective="Investigate",
            )
        ],
    )
    run = CompanyRun(
        run_id="run_full_001",
        objective=obj,
        state=CompanyRunState.RUNNING.value,
        ceo_invocation_count=2,
        specialist_invocation_count=1,
        replan_count=0,
    )
    run.set_plan(plan)

    run_dict = run.to_dict()
    restored = CompanyRun.from_dict(run_dict)

    assert restored.run_id == run.run_id
    assert restored.objective.id == obj.id
    assert restored.state == CompanyRunState.RUNNING.value
    assert restored.active_plan is not None
    assert restored.active_plan.plan_id == "plan_v1"
    assert restored.ceo_invocation_count == 2
    assert restored.specialist_invocation_count == 1
    assert "i1" in restored.work_item_states


def test_requirement_ab_malformed_serialized_state_rejected():
    """Requirement AB: Malformed serialized state rejected fail-closed."""
    obj_dict = {"id": "o1", "title": "T", "description": "D"}

    # Invalid state value
    with pytest.raises(TransitionPolicyError, match="Invalid CompanyRunState"):
        CompanyRun.from_dict({
            "run_id": "r1",
            "objective": obj_dict,
            "state": "READY_FOR_APPLY",  # Illegal non-canonical state
        })

    with pytest.raises(TransitionPolicyError, match="Invalid CompanyRunState"):
        CompanyRun.from_dict({
            "run_id": "r1",
            "objective": obj_dict,
            "state": "UNKNOWN_CUSTOM_STATE",
        })

    # Missing run_id
    with pytest.raises(OrchestrationError, match="missing or invalid 'run_id'"):
        CompanyRun.from_dict({"objective": obj_dict, "state": "CREATED"})

    # Non-dictionary payload
    with pytest.raises(OrchestrationError, match="Expected dictionary"):
        CompanyRun.from_dict("not-a-dict")  # type: ignore


def test_requirement_ac_ad_plan_history_and_version_immutability():
    """Requirements AC & AD: Plan version and plan history preserve old versions."""
    obj = CompanyObjective(id="o1", title="T", description="D")
    run = CompanyRun(run_id="r1", objective=obj)

    plan_v1 = CEOOrchestrationPlan(
        plan_id="p1",
        objective_id="o1",
        version=1,
        work_items=[CEOPlannedWorkItem(work_item_id="i1", role="research", objective="R")],
    )
    plan_v2 = CEOOrchestrationPlan(
        plan_id="p2",
        objective_id="o1",
        version=2,
        work_items=[
            CEOPlannedWorkItem(work_item_id="i1", role="research", objective="R"),
            CEOPlannedWorkItem(work_item_id="i2", role="product", objective="P", depends_on=["i1"]),
        ],
    )

    run.set_plan(plan_v1)
    assert run.active_plan.plan_id == "p1"
    assert run.active_plan.version == 1
    assert len(run.plan_history) == 0

    # Replan to v2
    run.set_plan(plan_v2)
    assert run.active_plan.plan_id == "p2"
    assert run.active_plan.version == 2
    assert len(run.plan_history) == 1
    assert run.plan_history[0].plan_id == "p1"
    assert run.plan_history[0].version == 1

    # Round trip preserves history
    d = run.to_dict()
    restored = CompanyRun.from_dict(d)
    assert len(restored.plan_history) == 1
    assert restored.plan_history[0].plan_id == "p1"
    assert restored.active_plan.plan_id == "p2"


def test_requirement_ae_ceo_action_type_vocabulary():
    """Requirement AE: CEOActionType contains no privileged mutation/apply/grant actions."""
    expected_actions = {
        "REQUEST_REPLAN",
        "REQUEST_REFINEMENT",
        "ESCALATE_TO_HUMAN",
        "CLAIM_OBJECTIVE_COMPLETE",
        "DECLARE_BLOCKED",
    }
    actual_actions = {a.value for a in CEOActionType}
    assert actual_actions == expected_actions

    forbidden_actions = {
        "RUN_SHELL",
        "WRITE_FILE",
        "APPLY_PATCH",
        "GIT_APPLY",
        "CREATE_EXECUTION_GRANT",
        "CREATE_REAL_REPO_APPLY_GRANT",
        "APPROVE_REAL_REPO",
        "SKIP_QA",
        "OVERRIDE_QA",
        "READY_FOR_APPLY",
    }
    for forbidden in forbidden_actions:
        assert forbidden not in actual_actions
        assert not hasattr(CEOActionType, forbidden)


def test_security_ceo_action_privileged_rejection():
    """Security Invariant: Attempting to instantiate a privileged CEOAction fails immediately."""
    # Valid actions work
    act = CEOAction(action_type="REQUEST_REPLAN", reason="New competitor data discovered.")
    assert act.action_type == "REQUEST_REPLAN"

    # Privileged actions fail-closed with TransitionPolicyError
    privileged_attempts = [
        "RUN_SHELL",
        "WRITE_FILE",
        "APPLY_PATCH",
        "GIT_APPLY",
        "CREATE_EXECUTION_GRANT",
        "CREATE_REAL_REPO_APPLY_GRANT",
        "APPROVE_REAL_REPO",
        "SKIP_QA",
        "OVERRIDE_QA",
    ]
    for priv in privileged_attempts:
        with pytest.raises(TransitionPolicyError, match="Unauthorized or invalid CEO action"):
            CEOAction(action_type=priv, reason="Malicious attempt")

        with pytest.raises(TransitionPolicyError, match="Unauthorized or invalid CEO action"):
            CEOAction.from_dict({"action_type": priv, "reason": "Malicious attempt"})


def test_human_escalation_lifecycle():
    """HumanEscalation tracks reason, blocking items, and human resolution."""
    esc = HumanEscalation(
        escalation_id="esc_01",
        run_id="run_01",
        reason="AMBIGUOUS_OBJECTIVE",
        question="Should rate limit apply to internal services?",
        options=["Public endpoints only", "All endpoints"],
        blocking_work_item_ids=["item_dev"],
    )
    assert esc.resolved_at is None
    assert esc.human_response is None

    # Resolve escalation
    esc.resolve("Public endpoints only")
    assert esc.human_response == "Public endpoints only"
    assert esc.resolved_at is not None

    # Serialization round trip
    d = esc.to_dict()
    restored = HumanEscalation.from_dict(d)
    assert restored.escalation_id == "esc_01"
    assert restored.human_response == "Public endpoints only"
    assert restored.resolved_at == esc.resolved_at


def test_employee_result_summary_round_trip():
    """EmployeeResultSummary compact serialization without raw transcripts."""
    summary = EmployeeResultSummary(
        role="product",
        task_id="task_prd_01",
        run_id="run_01_01",
        status="SUCCESS",
        summary="PRD approved for rate limiting.",
        blockers=[],
        artifact_refs=[{"artifact_id": "art_1", "sha256": "abc1234"}],
    )
    d = summary.to_dict()
    assert d["role"] == "product"
    assert d["status"] == "SUCCESS"

    restored = EmployeeResultSummary.from_dict(d)
    assert restored.role == "product"
    assert restored.task_id == "task_prd_01"
    assert restored.summary == "PRD approved for rate limiting."
    assert len(restored.artifact_refs) == 1
