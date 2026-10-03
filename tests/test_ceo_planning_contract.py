"""Tests for STEP 17B-2: CEO Planning Contract & Extraction Pipeline.

Covers:
- Prompt generation containing objective, constraints, criteria
- A. Valid pure JSON accepted
- B. Valid fenced JSON accepted
- C. Malformed JSON rejected
- D. Ambiguous multiple JSON payloads rejected
- E. Unknown schema version rejected
- F. Wrong objective_id rejected
- G. Version != 1 rejected for initial plan
- H. >6 work items rejected
- I. Cycle rejected
- J. Developer missing Product rejected
- K. Developer missing UX rejected
- L. Developer -> QA ordinary pipeline rejected
- M. CEO role as work item rejected
- N. Privileged top-level field attempt rejected
- O. task_id supplied by CEO rejected
- P. run_id supplied by CEO rejected
- Q. Non-pending runtime state supplied by CEO rejected
- R. Oversized CEO output rejected
- S. Arbitrary prose with no valid payload rejected
- T. Attempted CREATE_EXECUTION_GRANT action rejected
- U. Attempted APPROVE_REAL_REPO action rejected
- V. Attempted SKIP_QA rejected
- CompanyService.propose_initial_company_plan with mock runtime
"""

import json
from unittest.mock import MagicMock
import pytest

from jester_ai_company.ceo_contract import (
    CEO_PLAN_SCHEMA_VERSION,
    MAX_RAW_CEO_OUTPUT_CHARS,
    CEOPlanExtractionError,
    CEOPlanSecurityError,
    build_ceo_planning_prompt,
    extract_ceo_plan_json,
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
    WorkItemState,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService, ExecutionError


@pytest.fixture
def sample_objective() -> CompanyObjective:
    return CompanyObjective(
        id="obj_launch_01",
        title="Launch Positioning Brief",
        description="Produce a product positioning and marketing brief.",
        constraints=["Zero code changes", "Use macro roles only"],
        acceptance_criteria=["Valid plan", "Depth <= 4", "No developer node without product+ux"],
        target_repository="/repos/jester",
    )


@pytest.fixture
def valid_plan_dict(sample_objective: CompanyObjective) -> dict:
    return {
        "schema_version": "1.0",
        "plan_id": "plan_launch_001",
        "objective_id": sample_objective.id,
        "version": 1,
        "work_items": [
            {
                "work_item_id": "item_res",
                "role": "research",
                "objective": "Research competitive positioning",
                "depends_on": [],
                "expected_outputs": ["research_brief.md"],
                "priority": 1,
            },
            {
                "work_item_id": "item_prod",
                "role": "product",
                "objective": "Draft product scope",
                "depends_on": ["item_res"],
                "expected_outputs": ["product_scope.md"],
                "priority": 2,
            },
            {
                "work_item_id": "item_mkt",
                "role": "marketing",
                "objective": "Draft launch announcement",
                "depends_on": ["item_prod"],
                "expected_outputs": ["announcement.md"],
                "priority": 3,
            },
        ],
        "completion_criteria": ["All briefs approved"],
        "constraints": ["No code changes"],
    }


def test_build_ceo_planning_prompt(sample_objective: CompanyObjective):
    """Verify prompt builder embeds objective fields and boundaries."""
    prompt = build_ceo_planning_prompt(sample_objective)
    assert sample_objective.id in prompt
    assert sample_objective.title in prompt
    assert sample_objective.description in prompt
    assert "Zero code changes" in prompt
    assert "Critical Developer Fan-In invariant" in prompt
    assert "schema_version" in prompt
    assert "ORCHESTRATION PLANNING MODE" in prompt


def test_requirement_a_valid_pure_json_accepted(sample_objective, valid_plan_dict):
    """Requirement A: Pure raw JSON accepted."""
    raw = json.dumps(valid_plan_dict)
    plan = parse_and_validate_ceo_plan(raw, sample_objective)
    assert plan.plan_id == "plan_launch_001"
    assert plan.objective_id == sample_objective.id
    assert len(plan.work_items) == 3
    assert plan.version == 1


def test_requirement_b_valid_fenced_json_accepted(sample_objective, valid_plan_dict):
    """Requirement B: Fenced JSON accepted (both ```json and ```)."""
    raw_json = json.dumps(valid_plan_dict)
    fenced_1 = f"```json\n{raw_json}\n```"
    plan_1 = parse_and_validate_ceo_plan(fenced_1, sample_objective)
    assert len(plan_1.work_items) == 3

    fenced_2 = f"Here is the executive plan:\n```\n{raw_json}\n```\nLet me know your thoughts."
    plan_2 = parse_and_validate_ceo_plan(fenced_2, sample_objective)
    assert len(plan_2.work_items) == 3


def test_requirement_c_malformed_json_rejected(sample_objective):
    """Requirement C: Malformed JSON syntax rejected."""
    raw_unclosed = '{"schema_version": "1.0", "plan_id": "p1", "work_items": [unclosed...'
    with pytest.raises(CEOPlanExtractionError):
        parse_and_validate_ceo_plan(raw_unclosed, sample_objective)

    raw_syntax_error = '{"schema_version": "1.0", "plan_id": "p1", "work_items": [unquoted text]}'
    with pytest.raises(CEOPlanExtractionError, match="Malformed JSON"):
        parse_and_validate_ceo_plan(raw_syntax_error, sample_objective)


def test_requirement_d_ambiguous_multiple_json_payloads_rejected(sample_objective, valid_plan_dict):
    """Requirement D: Multiple ambiguous JSON payloads rejected."""
    j1 = json.dumps(valid_plan_dict)
    j2 = json.dumps({"schema_version": "1.0", "plan_id": "other_plan"})

    # In code blocks
    multi_fenced = f"```json\n{j1}\n```\nAnd alternatively:\n```json\n{j2}\n```"
    with pytest.raises(CEOPlanExtractionError, match="Multiple ambiguous JSON payloads"):
        parse_and_validate_ceo_plan(multi_fenced, sample_objective)

    # In raw text
    multi_raw = f"{j1}\n{j2}"
    with pytest.raises(CEOPlanExtractionError, match="Multiple ambiguous"):
        parse_and_validate_ceo_plan(multi_raw, sample_objective)


def test_requirement_e_unknown_schema_version_rejected(sample_objective, valid_plan_dict):
    """Requirement E: Unknown schema version rejected."""
    valid_plan_dict["schema_version"] = "2.0"
    with pytest.raises(PlanValidationError, match="Unsupported schema_version '2.0'"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_f_wrong_objective_id_rejected(sample_objective, valid_plan_dict):
    """Requirement F: Wrong objective_id rejected."""
    valid_plan_dict["objective_id"] = "obj_wrong_999"
    with pytest.raises(PlanValidationError, match="does not match expected objective ID"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_g_version_not_one_rejected(sample_objective, valid_plan_dict):
    """Requirement G: Version != 1 rejected for initial plan."""
    valid_plan_dict["version"] = 2
    with pytest.raises(PlanValidationError, match="Initial CEO plan version must be 1"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_h_over_max_work_items_rejected(sample_objective, valid_plan_dict):
    """Requirement H: >6 work items rejected."""
    items = []
    for i in range(1, 8):
        items.append({
            "work_item_id": f"item_{i}",
            "role": "research",
            "objective": f"Task {i}",
            "depends_on": [],
            "expected_outputs": [],
            "priority": i,
        })
    valid_plan_dict["work_items"] = items
    with pytest.raises(DAGValidationError, match="exceeds maximum allowed limit of 6"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_i_cycle_rejected(sample_objective, valid_plan_dict):
    """Requirement I: Dependency cycle rejected."""
    valid_plan_dict["work_items"] = [
        {
            "work_item_id": "i1",
            "role": "research",
            "objective": "A",
            "depends_on": ["i2"],
        },
        {
            "work_item_id": "i2",
            "role": "product",
            "objective": "B",
            "depends_on": ["i1"],
        },
    ]
    with pytest.raises(DAGValidationError, match="Cycle detected"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_j_developer_missing_product_rejected(sample_objective, valid_plan_dict):
    """Requirement J: Developer missing Product prerequisite rejected."""
    valid_plan_dict["work_items"] = [
        {"work_item_id": "ux_01", "role": "ux", "objective": "UX", "depends_on": []},
        {"work_item_id": "dev_01", "role": "developer", "objective": "Dev", "depends_on": ["ux_01"]},
    ]
    with pytest.raises(DAGValidationError, match="requires both Product and UX"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_k_developer_missing_ux_rejected(sample_objective, valid_plan_dict):
    """Requirement K: Developer missing UX prerequisite rejected."""
    valid_plan_dict["work_items"] = [
        {"work_item_id": "prod_01", "role": "product", "objective": "PRD", "depends_on": []},
        {"work_item_id": "dev_01", "role": "developer", "objective": "Dev", "depends_on": ["prod_01"]},
    ]
    with pytest.raises(DAGValidationError, match="requires both Product and UX"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_l_developer_to_qa_ordinary_pipeline_rejected(sample_objective, valid_plan_dict):
    """Requirement L: Developer -> QA ordinary pipeline rejected in CEO plan."""
    valid_plan_dict["work_items"] = [
        {"work_item_id": "prod_01", "role": "product", "objective": "PRD", "depends_on": []},
        {"work_item_id": "ux_01", "role": "ux", "objective": "UX", "depends_on": ["prod_01"]},
        {
            "work_item_id": "dev_01",
            "role": "developer",
            "objective": "Dev",
            "depends_on": ["prod_01", "ux_01"],
        },
        {"work_item_id": "qa_01", "role": "qa", "objective": "QA", "depends_on": ["dev_01"]},
    ]
    with pytest.raises(DAGValidationError, match="Direct Developer -> QA dependency is forbidden"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_m_ceo_role_as_work_item_rejected(sample_objective, valid_plan_dict):
    """Requirement M: CEO role as work item rejected."""
    valid_plan_dict["work_items"] = [
        {"work_item_id": "ceo_item", "role": "ceo", "objective": "Direct", "depends_on": []},
    ]
    with pytest.raises(PlanValidationError, match="CEO cannot appear as a work item role"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_n_privileged_top_level_key_rejected(sample_objective, valid_plan_dict):
    """Requirement N: Privileged top-level field rejected."""
    valid_plan_dict["execution_grant"] = {"grant_id": "grant_01"}
    with pytest.raises(CEOPlanSecurityError, match="Unauthorized privileged key 'execution_grant'"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_o_task_id_supplied_by_ceo_rejected(sample_objective, valid_plan_dict):
    """Requirement O: task_id supplied by CEO in work item rejected."""
    valid_plan_dict["work_items"][0]["task_id"] = "task_injected_001"
    with pytest.raises(CEOPlanSecurityError, match="specifies application-owned 'task_id'"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_p_run_id_supplied_by_ceo_rejected(sample_objective, valid_plan_dict):
    """Requirement P: run_id supplied by CEO in work item rejected."""
    valid_plan_dict["work_items"][0]["run_id"] = "run_injected_001"
    with pytest.raises(CEOPlanSecurityError, match="specifies application-owned 'run_id'"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_q_non_pending_state_supplied_by_ceo_rejected(sample_objective, valid_plan_dict):
    """Requirement Q: Non-pending runtime state supplied by CEO rejected."""
    valid_plan_dict["work_items"][0]["state"] = "COMPLETED"
    with pytest.raises(CEOPlanSecurityError, match="unauthorized runtime state 'COMPLETED'"):
        parse_and_validate_ceo_plan(json.dumps(valid_plan_dict), sample_objective)


def test_requirement_r_oversized_ceo_output_rejected(sample_objective):
    """Requirement R: Oversized CEO output rejected."""
    giant_text = "{" + (" " * (MAX_RAW_CEO_OUTPUT_CHARS + 10)) + "}"
    with pytest.raises(CEOPlanExtractionError, match="Oversized CEO output"):
        parse_and_validate_ceo_plan(giant_text, sample_objective)


def test_requirement_s_arbitrary_prose_no_json_rejected(sample_objective):
    """Requirement S: Arbitrary prose without JSON rejected."""
    prose = "I suggest we first look at research, then build the product. That sounds good."
    with pytest.raises(CEOPlanExtractionError, match="No JSON object detected"):
        parse_and_validate_ceo_plan(prose, sample_objective)


def test_requirement_t_u_v_privileged_actions_rejected(sample_objective, valid_plan_dict):
    """Requirements T, U, V: Attempted privileged actions rejected."""
    for priv_action in ["CREATE_EXECUTION_GRANT", "APPROVE_REAL_REPO", "SKIP_QA", "OVERRIDE_QA"]:
        bad_dict = dict(valid_plan_dict)
        bad_dict["actions"] = [priv_action]
        with pytest.raises(CEOPlanSecurityError, match="Unauthorized privileged key 'actions'"):
            parse_and_validate_ceo_plan(json.dumps(bad_dict), sample_objective)

        bad_dict_2 = dict(valid_plan_dict)
        bad_dict_2["work_items"] = [
            {
                "work_item_id": "i1",
                "role": "developer",
                "objective": "hack",
                "command": "rm -rf /",
            }
        ]
        with pytest.raises(CEOPlanSecurityError, match="Unauthorized privileged key 'command'"):
            parse_and_validate_ceo_plan(json.dumps(bad_dict_2), sample_objective)


def test_company_service_propose_initial_company_plan_success(sample_objective, valid_plan_dict):
    """Verify CompanyService.propose_initial_company_plan executes CEO and parses plan."""
    mock_runtime = MagicMock(spec=AntigravityRuntime)
    mock_runtime.execute.return_value = AgentExecutionResult(
        agent="ceo",
        success=True,
        stdout=json.dumps(valid_plan_dict),
        stderr="",
        exit_code=0,
        duration_ms=250.0,
    )

    service = CompanyService(runtime=mock_runtime)
    plan = service.propose_initial_company_plan(sample_objective)

    assert plan.plan_id == "plan_launch_001"
    assert len(plan.work_items) == 3
    mock_runtime.execute.assert_called_once()


def test_company_service_propose_initial_company_plan_runtime_failure(sample_objective):
    """Verify CompanyService.propose_initial_company_plan fails if runtime execution fails."""
    mock_runtime = MagicMock(spec=AntigravityRuntime)
    mock_runtime.execute.return_value = AgentExecutionResult(
        agent="ceo",
        success=False,
        stdout="",
        stderr="Process timed out",
        exit_code=-1,
        duration_ms=60000.0,
        timed_out=True,
    )

    service = CompanyService(runtime=mock_runtime)
    with pytest.raises(ExecutionError, match="CEO agent execution failed"):
        service.propose_initial_company_plan(sample_objective)
