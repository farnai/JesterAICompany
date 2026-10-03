"""Tests for STEP 17B-3: Deterministic Company Execution Engine & Non-Code Workflow.

Covers requirements A through AJ:
A. create CompanyRun -> CREATED
B. valid CREATED -> PLANNING
C. invalid CREATED -> COMPLETED rejected
D. CEO plan acceptance -> PLAN_READY
E. CEO invocation count increments exactly once
F. start -> RUNNING
G. deterministic ready-node selection
H. one-step executes at most one work item
I. Research dispatch uses existing Research executor
J. Product dispatch uses existing Product executor
K. UX dispatch uses existing UX executor
L. Marketing dispatch uses existing Marketing executor
M. Developer node stops/fails closed in STEP 17B-3
N. unknown role rejected
O. completed dependency unlocks downstream node
P. incomplete dependency blocks downstream node
Q. dependency does not bypass artifact handoff policy
R. successful work item binds Task/TaskRun
S. successful work item binds verified artifact
T. artifact verification failure prevents COMPLETED
U. EmployeeResultSummary created
V. successful specialist does NOT invoke CEO again
W. Research->Product progresses without CEO
X. Product->Marketing progresses without CEO
Y. CEO count remains 1 across three successful specialists
Z. specialist count becomes 3
AA. all-complete non-code plan -> COMPLETED
AB. specialist failure prevents dependent execution
AC. specialist failure makes run FAILED/BLOCKED according to policy
AD. terminal run cannot execute more work
AE. run-until-boundary respects maximum steps
AF. plan containing Developer does not silently skip it
AG. CompanyRun serialization after execution preserves states
AH. no direct agent-to-agent invocation path
AI. existing Developer Product+UX invariant remains unchanged
AJ. READY_FOR_HUMAN_APPLY cannot be entered by non-code workflow
"""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

from jester_ai_company.core import (
    ALLOWED_HANDOFF_EDGES,
    Artifact,
    ArtifactVerificationError,
    RunStatus,
    TaskStatus,
)
from jester_ai_company.dag import (
    DAGValidationError,
    validate_dag_structure,
)
from jester_ai_company.orchestrator import (
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
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService


# Sample payloads for specialists
SAMPLE_RESEARCH_PAYLOAD = {
    "schema_version": "1.1",
    "status": "completed",
    "summary": "Completed research on developer preview positioning.",
    "sources": [
        {
            "source_id": "src_1",
            "title": "Developer Preview Benchmark",
            "reference": "docs/preview_benchmark.md",
            "source_type": "local_file",
            "accessed_at": "2026-10-03T12:00:00Z",
        }
    ],
    "findings": [
        {
            "claim": "Developer previews require clear CLI quickstart flows.",
            "evidence": "Benchmark of top 5 developer tools.",
            "evidence_status": "verified_source",
            "source_ids": ["src_1"],
            "certainty": "high",
        }
    ],
    "recommendations": ["Position as verifiable AI company infrastructure."],
    "risks": ["Adoption friction if documentation is unclear."],
    "open_questions": [],
}

SAMPLE_PRODUCT_PAYLOAD = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Product framing for developer preview.",
    "deliverables": [
        {
            "name": "PRODUCT_REQUIREMENTS.md",
            "content": "# Product Requirements\n\nDeveloper preview requirements and scope.",
        }
    ],
    "risks": ["Scope creep in initial release."],
    "open_questions": [],
}

SAMPLE_UX_PAYLOAD = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "UX architecture and flows for developer preview.",
    "flows": [
        {
            "name": "Quickstart Flow",
            "description": "Onboarding from repo clone to verified run.",
            "steps": ["Step 1", "Step 2"],
        }
    ],
    "screens": [
        {
            "name": "CLI Console",
            "purpose": "Provide execution feedback.",
            "states": ["default", "running", "completed"],
        }
    ],
    "interaction_rules": ["Non-blocking feedback"],
    "accessibility_considerations": ["Plain text mode"],
    "open_questions": [],
}

SAMPLE_MARKETING_PAYLOAD = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Positioning brief for developer preview launch.",
    "positioning": "Verifiable multi-agent company orchestration for developers.",
    "target_audiences": [
        {
            "name": "Software Developers",
            "description": "Developers building agent workflows.",
            "pain_points": ["Hallucinations", "Unverifiable outputs"],
        }
    ],
    "key_messages": [
        {
            "audience": "Software Developers",
            "core_message": "Deterministic orchestration with verified artifacts.",
        }
    ],
    "channels_or_tactics": [
        {
            "channel": "Developer Blog",
            "tactic": "Technical walkthrough of multi-agent pipeline.",
        }
    ],
    "deliverables": [
        {
            "name": "MARKETING_POSITIONING_BRIEF.md",
            "content": "# Positioning Brief\n\nJester AI Company Developer Preview Positioning.",
        }
    ],
    "risks": ["Market crowdedness"],
    "open_questions": [],
}

SAMPLE_CEO_PLAN_PAYLOAD = {
    "schema_version": "1.0",
    "plan_id": "plan_preview_001",
    "objective_id": "obj_preview_001",
    "version": 1,
    "work_items": [
        {
            "work_item_id": "wi_research",
            "role": "research",
            "objective": "Inspect landscape and operating principles",
            "depends_on": [],
            "expected_outputs": ["research_brief.md"],
            "priority": 1,
        },
        {
            "work_item_id": "wi_product",
            "role": "product",
            "objective": "Define product framing for developer preview",
            "depends_on": ["wi_research"],
            "expected_outputs": ["product_framing.md"],
            "priority": 2,
        },
        {
            "work_item_id": "wi_marketing",
            "role": "marketing",
            "objective": "Produce marketing positioning brief",
            "depends_on": ["wi_product"],
            "expected_outputs": ["positioning_brief.md"],
            "priority": 3,
        },
    ],
    "completion_criteria": ["Marketing positioning brief produced and verified"],
    "constraints": ["No code changes", "No Developer role"],
}


class MockMultiAgentRuntime(AntigravityRuntime):
    """Deterministic mock runtime returning typed responses per agent role."""

    def __init__(self, objective_id: str = "obj_preview_001") -> None:
        super().__init__()
        self.objective_id = objective_id
        self.execution_counts = {
            "ceo": 0,
            "research": 0,
            "product": 0,
            "ux": 0,
            "marketing": 0,
            "developer": 0,
            "qa": 0,
        }
        self.recorded_calls = []

    def execute(
        self,
        agent: str,
        prompt: str,
        timeout: float = None,
        cwd=None,
    ) -> AgentExecutionResult:
        agent_norm = agent.lower()
        self.execution_counts[agent_norm] = self.execution_counts.get(agent_norm, 0) + 1
        self.recorded_calls.append({"agent": agent_norm, "prompt": prompt})

        if agent_norm == "ceo":
            payload = copy.deepcopy(SAMPLE_CEO_PLAN_PAYLOAD)
            payload["objective_id"] = self.objective_id
            stdout = json.dumps(payload)
        elif agent_norm == "research":
            stdout = json.dumps(SAMPLE_RESEARCH_PAYLOAD)
        elif agent_norm == "product":
            stdout = json.dumps(SAMPLE_PRODUCT_PAYLOAD)
        elif agent_norm == "ux":
            stdout = json.dumps(SAMPLE_UX_PAYLOAD)
        elif agent_norm == "marketing":
            stdout = json.dumps(SAMPLE_MARKETING_PAYLOAD)
        else:
            stdout = "{}"

        return AgentExecutionResult(
            agent=agent_norm,
            success=True,
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration_ms=100.0,
            timed_out=False,
            command=["agy", "--agent", agent_norm],
        )


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def service_and_obj(temp_dir):
    runtime = MockMultiAgentRuntime(objective_id="obj_preview_001")
    service = CompanyService(
        output_dir=str(temp_dir / ".runs"),
        repo_root=temp_dir,
        runtime=runtime,
    )
    objective = CompanyObjective(
        id="obj_preview_001",
        title="Prepare Developer Preview Positioning Brief",
        description="Define product framing and produce marketing positioning brief.",
        constraints=["no source-code mutation", "no Developer role"],
        acceptance_criteria=["final deliverable must be a canonical Marketing artifact"],
    )
    return service, objective, runtime


# -----------------------------------------------------------------------------
# Test Cases (Requirements A through AJ)
# -----------------------------------------------------------------------------

def test_requirement_a_create_company_run(service_and_obj):
    """Requirement A: create CompanyRun -> CREATED state with initialized fields."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)

    assert run.run_id.startswith("crun_")
    assert run.state == CompanyRunState.CREATED.value
    assert run.objective.id == obj.id
    assert run.ceo_invocation_count == 0
    assert run.specialist_invocation_count == 0
    assert run.replan_count == 0
    assert run.active_plan is None
    assert len(run.plan_history) == 0
    assert run.escalation is None
    assert len(run.events) >= 1
    assert run.events[0]["event_type"] == "RUN_CREATED"


def test_requirement_b_valid_created_to_planning(service_and_obj):
    """Requirement B: valid CREATED -> PLANNING transition."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    run.transition_to(CompanyRunState.PLANNING)
    assert run.state == CompanyRunState.PLANNING.value


def test_requirement_c_invalid_created_to_completed_rejected(service_and_obj):
    """Requirement C: invalid CREATED -> COMPLETED transition is rejected."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    with pytest.raises(TransitionPolicyError, match="Invalid CompanyRun transition from 'CREATED' to 'COMPLETED'"):
        run.transition_to(CompanyRunState.COMPLETED)


def test_requirement_d_e_ceo_plan_acceptance_and_count(service_and_obj):
    """Requirements D & E: CEO plan acceptance -> PLAN_READY, invocation count increments exactly once."""
    service, obj, runtime = service_and_obj
    run = service.create_company_run(obj)
    assert run.ceo_invocation_count == 0

    planned_run = service.plan_company_run(run.run_id)
    assert planned_run.state == CompanyRunState.PLAN_READY.value
    assert planned_run.active_plan is not None
    assert planned_run.active_plan.plan_id == "plan_preview_001"
    assert planned_run.ceo_invocation_count == 1
    assert runtime.execution_counts["ceo"] == 1


def test_requirement_f_start_running(service_and_obj):
    """Requirement F: start -> RUNNING."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    started_run = service.start_company_run(run.run_id)

    assert started_run.state == CompanyRunState.RUNNING.value
    assert any(e["event_type"] == "RUN_STARTED" for e in started_run.events)


def test_requirement_g_deterministic_ready_node_selection(service_and_obj):
    """Requirement G: deterministic ready-node selection (priority ASC, work_item_id ASC)."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)

    # Custom plan with multiple root items
    item_b = CEOPlannedWorkItem(work_item_id="wi_b", role="research", objective="B", priority=2)
    item_a = CEOPlannedWorkItem(work_item_id="wi_a", role="research", objective="A", priority=1)
    item_c = CEOPlannedWorkItem(work_item_id="wi_c", role="product", objective="C", priority=1)
    plan = CEOOrchestrationPlan(
        plan_id="p1", objective_id=obj.id, version=1,
        work_items=[item_b, item_c, item_a],
    )
    run.set_plan(plan)
    run.transition_to(CompanyRunState.PLANNING)
    run.transition_to(CompanyRunState.PLAN_READY)
    service.save_company_run(run)
    service.start_company_run(run.run_id)

    # First ready should be wi_a (priority 1, 'wi_a' < 'wi_c')
    service.execute_next_company_work(run.run_id)
    updated_run = service.get_company_run(run.run_id)
    assert updated_run.work_item_states["wi_a"] == WorkItemState.COMPLETED.value
    assert updated_run.work_item_states["wi_c"] == WorkItemState.PENDING.value
    assert updated_run.work_item_states["wi_b"] == WorkItemState.PENDING.value


def test_requirement_h_one_step_executes_at_most_one(service_and_obj):
    """Requirement H: one-step executes at most one work item per call."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    assert run.specialist_invocation_count == 0
    service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.specialist_invocation_count == 1
    # Only research completed, product is still pending
    assert updated.work_item_states["wi_research"] == WorkItemState.COMPLETED.value
    assert updated.work_item_states["wi_product"] == WorkItemState.PENDING.value
    assert updated.work_item_states["wi_marketing"] == WorkItemState.PENDING.value


def test_requirement_i_j_k_l_specialist_dispatch(temp_dir):
    """Requirements I, J, K, L: specialist dispatch uses existing specialist executor."""
    runtime = MockMultiAgentRuntime(objective_id="obj_all_specialists")
    service = CompanyService(
        output_dir=str(temp_dir / ".runs"),
        repo_root=temp_dir,
        runtime=runtime,
    )
    obj = CompanyObjective(id="obj_all_specialists", title="All Specialists", description="Test all 4 roles")
    run = service.create_company_run(obj)

    # Plan with Research -> Product -> UX -> Marketing
    i_res = CEOPlannedWorkItem(work_item_id="w_res", role="research", objective="Research task", priority=1)
    i_prod = CEOPlannedWorkItem(work_item_id="w_prod", role="product", objective="Product task", depends_on=["w_res"], priority=2)
    i_ux = CEOPlannedWorkItem(work_item_id="w_ux", role="ux", objective="UX task", depends_on=["w_prod"], priority=3)
    i_mkt = CEOPlannedWorkItem(work_item_id="w_mkt", role="marketing", objective="Marketing task", depends_on=["w_prod"], priority=4)
    plan = CEOOrchestrationPlan(plan_id="p_all", objective_id=obj.id, version=1, work_items=[i_res, i_prod, i_ux, i_mkt])

    run.set_plan(plan)
    run.transition_to(CompanyRunState.PLANNING)
    run.transition_to(CompanyRunState.PLAN_READY)
    service.save_company_run(run)
    service.start_company_run(run.run_id)

    # 1. Research
    service.execute_next_company_work(run.run_id)
    assert runtime.execution_counts["research"] == 1

    # 2. Product
    service.execute_next_company_work(run.run_id)
    assert runtime.execution_counts["product"] == 1

    # 3. UX (priority 3)
    service.execute_next_company_work(run.run_id)
    assert runtime.execution_counts["ux"] == 1

    # 4. Marketing (priority 4)
    service.execute_next_company_work(run.run_id)
    assert runtime.execution_counts["marketing"] == 1


def test_requirement_m_af_developer_node_fails_closed(service_and_obj):
    """Requirements M & AF: Developer node stops/fails closed and is NOT silently skipped."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)

    # Plan containing a developer node
    i_prod = CEOPlannedWorkItem(work_item_id="w_prod", role="product", objective="PRD", priority=1)
    i_ux = CEOPlannedWorkItem(work_item_id="w_ux", role="ux", objective="UX", priority=2)
    i_dev = CEOPlannedWorkItem(work_item_id="w_dev", role="developer", objective="Code", depends_on=["w_prod", "w_ux"], priority=3)
    plan = CEOOrchestrationPlan(plan_id="p_dev", objective_id=obj.id, version=1, work_items=[i_prod, i_ux, i_dev])

    run.set_plan(plan)
    run.transition_to(CompanyRunState.PLANNING)
    run.transition_to(CompanyRunState.PLAN_READY)
    service.save_company_run(run)
    service.start_company_run(run.run_id)

    # Execute product and UX
    service.execute_next_company_work(run.run_id)  # product
    service.execute_next_company_work(run.run_id)  # ux

    # Now developer is ready -> MUST fail closed with UnsupportedRoleError
    with pytest.raises(UnsupportedRoleError, match="Role 'developer' is unsupported in STEP 17B-3"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.BLOCKED.value
    assert updated.work_item_states["w_dev"] == WorkItemState.BLOCKED.value


def test_requirement_n_unknown_role_rejected(service_and_obj):
    """Requirement N: unknown role rejected fail closed."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)

    item = CEOPlannedWorkItem(work_item_id="w_fin", role="finance", objective="Budget", priority=1)
    # Bypass dag validation directly into run for test
    run.active_plan = CEOOrchestrationPlan(plan_id="p_fin", objective_id=obj.id, version=1, work_items=[item])
    run.work_item_states["w_fin"] = WorkItemState.PENDING.value
    run.state = CompanyRunState.RUNNING.value
    service.save_company_run(run)

    with pytest.raises(UnsupportedRoleError, match="Unknown or unsupported specialist role 'finance'"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.FAILED.value


def test_requirement_o_p_dependency_readiness_control(service_and_obj):
    """Requirements O & P: dependency unlocks downstream node; incomplete dependency blocks."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Before research executes, product cannot execute
    assert run.work_item_states["wi_product"] == WorkItemState.PENDING.value

    # Execute research -> unlocks product
    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)
    assert updated.work_item_states["wi_research"] == WorkItemState.COMPLETED.value
    # Next ready is product
    service.execute_next_company_work(run.run_id)
    updated2 = service.get_company_run(run.run_id)
    assert updated2.work_item_states["wi_product"] == WorkItemState.COMPLETED.value


def test_requirement_q_handoff_policy_respected(service_and_obj):
    """Requirement Q: dependency does not bypass artifact handoff policy."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)

    # If marketing depends on research directly (forbidden edge in ALLOWED_HANDOFF_EDGES)
    # Research -> Marketing edge is NOT in ALLOWED_HANDOFF_EDGES:
    assert ("research", "marketing") not in ALLOWED_HANDOFF_EDGES

    i_res = CEOPlannedWorkItem(work_item_id="w_res", role="research", objective="Research", priority=1)
    i_mkt = CEOPlannedWorkItem(work_item_id="w_mkt", role="marketing", objective="Marketing", depends_on=["w_res"], priority=2)
    plan = CEOOrchestrationPlan(plan_id="p_nm", objective_id=obj.id, version=1, work_items=[i_res, i_mkt])

    run.set_plan(plan)
    run.transition_to(CompanyRunState.PLANNING)
    run.transition_to(CompanyRunState.PLAN_READY)
    service.save_company_run(run)
    service.start_company_run(run.run_id)

    # Execute research
    service.execute_next_company_work(run.run_id)
    # Execute marketing
    service.execute_next_company_work(run.run_id)

    # Marketing task should execute, but have ZERO attached input artifacts because handoff was not allowed
    mkt_task = service.get_task(i_mkt.task_id)
    assert len(mkt_task.input_artifacts) == 0


def test_requirement_r_s_u_artifact_binding_and_summary(service_and_obj):
    """Requirements R, S, U: successful work item binds Task/TaskRun, verified artifact, and EmployeeResultSummary."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)
    res_item = updated.active_plan.work_items[0]

    assert res_item.task_id is not None
    assert res_item.run_id is not None
    assert len(updated.employee_summaries) == 1

    summary = updated.employee_summaries[0]
    assert summary.role == "research"
    assert summary.task_id == res_item.task_id
    assert summary.run_id == res_item.run_id
    assert summary.status == TaskStatus.COMPLETED.value
    assert len(summary.artifact_refs) >= 1

    # Verify physical file existence and checksum
    art_ref = summary.artifact_refs[0]
    art_path = service.output_dir / art_ref["path"]
    assert art_path.is_file()
    assert hashlib.sha256(art_path.read_bytes()).hexdigest() == art_ref["sha256"]


def test_requirement_t_artifact_verification_failure_fails_closed(service_and_obj):
    """Requirement T: artifact verification failure prevents COMPLETED."""
    service, obj, _ = service_and_obj

    # Create a runtime that generates a result but mock an artifact tampered failure
    class CorruptingRuntime(MockMultiAgentRuntime):
        pass

    service.runtime = CorruptingRuntime(objective_id=obj.id)
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Intercept execute_research_task to corrupt the created artifact
    orig_exec = service.execute_research_task

    def tampered_exec(task_id, project_id=None):
        task_run = orig_exec(task_id, project_id=project_id)
        # Tamper with recorded artifact checksum
        for art in task_run.artifacts:
            art.sha256 = "corrupted_checksum_0000000000000000000000000000000000000000"
        return task_run

    service.execute_research_task = tampered_exec

    with pytest.raises(ArtifactVerificationError, match="Artifact checksum mismatch"):
        service.execute_next_company_work(run.run_id)

    updated = service.get_company_run(run.run_id)
    assert updated.state == CompanyRunState.FAILED.value
    assert updated.work_item_states["wi_research"] == WorkItemState.FAILED.value


def test_requirement_v_w_x_y_z_aa_deterministic_progression(service_and_obj):
    """Requirements V, W, X, Y, Z, AA: deterministic progression executes all 3 steps without CEO calls, reaching COMPLETED."""
    service, obj, runtime = service_and_obj
    run = service.create_company_run(obj)

    # Initial planning
    service.plan_company_run(run.run_id)
    assert run.ceo_invocation_count == 1
    assert runtime.execution_counts["ceo"] == 1

    service.start_company_run(run.run_id)

    # Step 1: Research (Requirement W)
    service.execute_next_company_work(run.run_id)
    r1 = service.get_company_run(run.run_id)
    assert r1.work_item_states["wi_research"] == WorkItemState.COMPLETED.value
    assert r1.ceo_invocation_count == 1  # Requirement V
    assert r1.specialist_invocation_count == 1
    assert runtime.execution_counts["ceo"] == 1

    # Step 2: Product (Requirement X)
    service.execute_next_company_work(run.run_id)
    r2 = service.get_company_run(run.run_id)
    assert r2.work_item_states["wi_product"] == WorkItemState.COMPLETED.value
    assert r2.ceo_invocation_count == 1  # Requirement V
    assert r2.specialist_invocation_count == 2
    assert runtime.execution_counts["ceo"] == 1

    # Step 3: Marketing
    service.execute_next_company_work(run.run_id)
    r3 = service.get_company_run(run.run_id)
    assert r3.work_item_states["wi_marketing"] == WorkItemState.COMPLETED.value
    # Requirement Y: CEO count remains 1 across all three specialists
    assert r3.ceo_invocation_count == 1
    assert runtime.execution_counts["ceo"] == 1
    # Requirement Z: specialist count becomes 3
    assert r3.specialist_invocation_count == 3
    # Requirement AA: all-complete non-code plan reaches COMPLETED
    assert r3.state == CompanyRunState.COMPLETED.value


def test_requirement_ab_ac_specialist_failure_blocks_dependents(service_and_obj):
    """Requirements AB & AC: specialist failure prevents dependent execution and marks run FAILED."""
    service, obj, _ = service_and_obj

    # Create a failing runtime for research
    class FailingResearchRuntime(MockMultiAgentRuntime):
        def execute(self, agent, prompt, timeout=None, cwd=None):
            if agent == "research":
                return AgentExecutionResult(
                    agent="research",
                    success=False,
                    stdout="",
                    stderr="Research model failure",
                    exit_code=1,
                    duration_ms=50.0,
                    timed_out=False,
                    command=["agy"],
                )
            return super().execute(agent, prompt, timeout, cwd)

    service.runtime = FailingResearchRuntime(objective_id=obj.id)
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Execute research (fails)
    service.execute_next_company_work(run.run_id)
    updated = service.get_company_run(run.run_id)

    assert updated.state == CompanyRunState.FAILED.value
    assert updated.work_item_states["wi_research"] == WorkItemState.FAILED.value
    assert updated.work_item_states["wi_product"] == WorkItemState.PENDING.value
    assert updated.work_item_states["wi_marketing"] == WorkItemState.PENDING.value


def test_requirement_ad_terminal_run_cannot_execute_more(service_and_obj):
    """Requirement AD: terminal run cannot execute more work."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Execute all steps to completion
    service.run_company_until_boundary(run.run_id, max_steps=10)
    completed = service.get_company_run(run.run_id)
    assert completed.state == CompanyRunState.COMPLETED.value

    # Attempting to execute next work on completed run raises TransitionPolicyError
    with pytest.raises(TransitionPolicyError, match="Cannot execute work: CompanyRun.*COMPLETED"):
        service.execute_next_company_work(run.run_id)


def test_requirement_ae_run_until_boundary_respects_max_steps(service_and_obj):
    """Requirement AE: run-until-boundary respects maximum steps."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Run with max_steps=1
    bounded_run = service.run_company_until_boundary(run.run_id, max_steps=1)
    assert bounded_run.specialist_invocation_count == 1
    assert bounded_run.state == CompanyRunState.RUNNING.value


def test_requirement_ag_company_run_serialization(service_and_obj):
    """Requirement AG: CompanyRun serialization after execution preserves all states."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)
    service.run_company_until_boundary(run.run_id, max_steps=10)

    final_run = service.get_company_run(run.run_id)
    serialized = final_run.to_dict()

    restored = CompanyRun.from_dict(serialized)
    assert restored.run_id == final_run.run_id
    assert restored.state == CompanyRunState.COMPLETED.value
    assert restored.ceo_invocation_count == 1
    assert restored.specialist_invocation_count == 3
    assert len(restored.employee_summaries) == 3
    assert len(restored.events) >= 5
    assert restored.work_item_states == final_run.work_item_states


def test_requirement_ah_no_direct_agent_to_agent_invocation(service_and_obj):
    """Requirement AH: prove no direct agent-to-agent invocation path."""
    service, obj, runtime = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)
    service.run_company_until_boundary(run.run_id, max_steps=10)

    # Every execution recorded was initiated via CompanyService, never subagent
    for call in runtime.recorded_calls:
        # Prompt contains no invoke_subagent instructions
        assert "invoke_subagent" not in call["prompt"]


def test_requirement_ai_existing_developer_fan_in_invariant_unchanged():
    """Requirement AI: existing Developer Product+UX prerequisite invariant remains unchanged."""
    i_dev = CEOPlannedWorkItem(work_item_id="w_dev", role="developer", objective="Code", depends_on=["w_prod"])
    i_prod = CEOPlannedWorkItem(work_item_id="w_prod", role="product", objective="PRD")
    plan = CEOOrchestrationPlan(plan_id="p1", objective_id="o1", version=1, work_items=[i_dev, i_prod])

    with pytest.raises(DAGValidationError, match="requires both Product and UX prerequisites"):
        validate_dag_structure(plan)


def test_requirement_aj_ready_for_human_apply_rejected_for_non_code(service_and_obj):
    """Requirement AJ: READY_FOR_HUMAN_APPLY cannot be entered by non-code workflow."""
    service, obj, _ = service_and_obj
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Attempting to enter READY_FOR_HUMAN_APPLY with is_code_workflow=False is rejected
    with pytest.raises(TransitionPolicyError, match="non-code company workflows cannot enter READY_FOR_HUMAN_APPLY"):
        run.transition_to(CompanyRunState.READY_FOR_HUMAN_APPLY, is_code_workflow=False)
