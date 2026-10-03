"""Tests for STEP 17B-1: Pure Deterministic DAG Validation and Traversal Engine.

Covers requirements:
F. Valid Research-only DAG accepted
G. Valid Product+UX DAG accepted
H. Valid Product+UX -> Developer DAG accepted
I. Product-only -> Developer rejected
J. UX-only -> Developer rejected
K. Research -> Developer rejected
L. Developer without prerequisites rejected
M. Duplicate work_item_id rejected
N. Unknown dependency rejected
O. Self dependency rejected
P. Cycle rejected
Q. Empty DAG rejected
R. >6 work items rejected
S. Depth 4 accepted
T. Depth 5 rejected
U. Unknown role rejected
V. CEO as work item rejected
W. Normal QA node after Developer rejected
X. Deterministic ready-node ordering (priority ASC, work_item_id ASC)
Y. Dependency completion controls readiness
Topological sort deterministic tie-breaking
"""

import pytest

from jester_ai_company.dag import (
    MAX_GRAPH_DEPTH,
    MAX_PLANNED_WORK_ITEMS,
    compute_graph_depth,
    get_topological_order,
    select_ready_work_items,
    validate_dag_structure,
)
from jester_ai_company.orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    DAGValidationError,
    PlanValidationError,
    WorkItemState,
)


def _make_plan(items, plan_id="test_plan", obj_id="test_obj"):
    return CEOOrchestrationPlan(
        plan_id=plan_id,
        objective_id=obj_id,
        work_items=items,
    )


def test_requirement_f_valid_research_only_dag_accepted():
    """Requirement F: Valid Research-only DAG accepted."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="item_res_1",
            role="research",
            objective="Market discovery",
        ),
        CEOPlannedWorkItem(
            work_item_id="item_res_2",
            role="research",
            objective="Competitor pricing",
            depends_on=["item_res_1"],
        ),
    ]
    plan = _make_plan(items)
    validate_dag_structure(plan)
    assert compute_graph_depth(plan) == 2


def test_requirement_g_valid_product_ux_dag_accepted():
    """Requirement G: Valid Product+UX DAG accepted."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="prod_01",
            role="product",
            objective="Write PRD",
        ),
        CEOPlannedWorkItem(
            work_item_id="ux_01",
            role="ux",
            objective="Design Figma mockups",
            depends_on=["prod_01"],
        ),
    ]
    plan = _make_plan(items)
    validate_dag_structure(plan)
    assert compute_graph_depth(plan) == 2


def test_requirement_h_valid_product_ux_to_developer_dag_accepted():
    """Requirement H: Valid Product+UX -> Developer DAG accepted (Fan-in satisfied)."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="prod_01",
            role="product",
            objective="Write PRD",
        ),
        CEOPlannedWorkItem(
            work_item_id="ux_01",
            role="ux",
            objective="Design Mockups",
            depends_on=["prod_01"],
        ),
        CEOPlannedWorkItem(
            work_item_id="dev_01",
            role="developer",
            objective="Implement feature",
            depends_on=["prod_01", "ux_01"],
        ),
    ]
    plan = _make_plan(items)
    validate_dag_structure(plan)
    assert compute_graph_depth(plan) == 3


def test_requirement_i_product_only_to_developer_rejected():
    """Requirement I: Product-only -> Developer rejected (missing UX)."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="prod_01",
            role="product",
            objective="Write PRD",
        ),
        CEOPlannedWorkItem(
            work_item_id="dev_01",
            role="developer",
            objective="Implement feature",
            depends_on=["prod_01"],
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="requires both Product and UX"):
        validate_dag_structure(plan)


def test_requirement_j_ux_only_to_developer_rejected():
    """Requirement J: UX-only -> Developer rejected (missing Product)."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="ux_01",
            role="ux",
            objective="Design Mockups",
        ),
        CEOPlannedWorkItem(
            work_item_id="dev_01",
            role="developer",
            objective="Implement feature",
            depends_on=["ux_01"],
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="requires both Product and UX"):
        validate_dag_structure(plan)


def test_requirement_k_research_to_developer_rejected():
    """Requirement K: Research -> Developer rejected (Research does not replace Product/UX)."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="res_01",
            role="research",
            objective="Background study",
        ),
        CEOPlannedWorkItem(
            work_item_id="dev_01",
            role="developer",
            objective="Implement feature",
            depends_on=["res_01"],
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="requires both Product and UX"):
        validate_dag_structure(plan)


def test_requirement_l_developer_without_prerequisites_rejected():
    """Requirement L: Developer with no prerequisites rejected."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="dev_01",
            role="developer",
            objective="Implement feature without PRD/UX",
            depends_on=[],
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="requires both Product and UX"):
        validate_dag_structure(plan)


def test_requirement_m_duplicate_work_item_id_rejected():
    """Requirement M: Duplicate work_item_id rejected."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="item_dup",
            role="research",
            objective="Step 1",
        ),
        CEOPlannedWorkItem(
            work_item_id="item_dup",
            role="product",
            objective="Step 2",
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="Duplicate work_item_id 'item_dup'"):
        validate_dag_structure(plan)


def test_requirement_n_unknown_dependency_rejected():
    """Requirement N: Unknown dependency reference rejected."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="item_01",
            role="product",
            objective="Step 1",
            depends_on=["non_existent_item"],
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="depends on unknown item 'non_existent_item'"):
        validate_dag_structure(plan)


def test_requirement_o_self_dependency_rejected():
    """Requirement O: Self-dependency rejected."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="item_self",
            role="product",
            objective="Step 1",
            depends_on=["item_self"],
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="Self-dependency detected"):
        validate_dag_structure(plan)


def test_requirement_p_cycle_rejected():
    """Requirement P: Cycle rejected."""
    # 2-node cycle: A -> B -> A
    items = [
        CEOPlannedWorkItem(
            work_item_id="node_a",
            role="product",
            objective="A",
            depends_on=["node_b"],
        ),
        CEOPlannedWorkItem(
            work_item_id="node_b",
            role="ux",
            objective="B",
            depends_on=["node_a"],
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="Cycle detected"):
        validate_dag_structure(plan)

    # 3-node cycle: A -> B -> C -> A
    items_3 = [
        CEOPlannedWorkItem(work_item_id="c_1", role="product", objective="1", depends_on=["c_3"]),
        CEOPlannedWorkItem(work_item_id="c_2", role="ux", objective="2", depends_on=["c_1"]),
        CEOPlannedWorkItem(work_item_id="c_3", role="marketing", objective="3", depends_on=["c_2"]),
    ]
    plan_3 = _make_plan(items_3)
    with pytest.raises(DAGValidationError, match="Cycle detected"):
        validate_dag_structure(plan_3)


def test_requirement_q_empty_dag_rejected():
    """Requirement Q: Empty DAG rejected."""
    plan = _make_plan([])
    with pytest.raises(PlanValidationError, match="at least 1 work item"):
        validate_dag_structure(plan)


def test_requirement_r_over_max_work_items_rejected():
    """Requirement R: >6 work items rejected (MAX_PLANNED_WORK_ITEMS = 6)."""
    # 6 items accepted
    items_6 = [
        CEOPlannedWorkItem(work_item_id=f"item_{i}", role="research", objective=f"Task {i}")
        for i in range(1, 7)
    ]
    plan_6 = _make_plan(items_6)
    validate_dag_structure(plan_6)

    # 7 items rejected
    items_7 = [
        CEOPlannedWorkItem(work_item_id=f"item_{i}", role="research", objective=f"Task {i}")
        for i in range(1, 8)
    ]
    plan_7 = _make_plan(items_7)
    with pytest.raises(DAGValidationError, match="exceeds maximum allowed limit of 6"):
        validate_dag_structure(plan_7)


def test_requirement_s_depth_4_accepted():
    """Requirement S: Depth 4 accepted (boundary condition)."""
    # Chain of 4: Research -> Product -> UX -> Developer (+Product)
    items = [
        CEOPlannedWorkItem(work_item_id="d1", role="research", objective="Study"),
        CEOPlannedWorkItem(work_item_id="d2", role="product", objective="PRD", depends_on=["d1"]),
        CEOPlannedWorkItem(work_item_id="d3", role="ux", objective="UX Spec", depends_on=["d2"]),
        CEOPlannedWorkItem(
            work_item_id="d4",
            role="developer",
            objective="Build",
            depends_on=["d2", "d3"],  # Developer Fan-In satisfied
        ),
    ]
    plan = _make_plan(items)
    assert compute_graph_depth(plan) == 4
    validate_dag_structure(plan)  # Passes without error


def test_requirement_t_depth_5_rejected():
    """Requirement T: Depth 5 rejected (MAX_GRAPH_DEPTH = 4)."""
    # Chain of 5: Res1 -> Res2 -> Prod -> UX -> Dev (+Prod)
    items = [
        CEOPlannedWorkItem(work_item_id="d1", role="research", objective="Study 1"),
        CEOPlannedWorkItem(work_item_id="d2", role="research", objective="Study 2", depends_on=["d1"]),
        CEOPlannedWorkItem(work_item_id="d3", role="product", objective="PRD", depends_on=["d2"]),
        CEOPlannedWorkItem(work_item_id="d4", role="ux", objective="UX", depends_on=["d3"]),
        CEOPlannedWorkItem(
            work_item_id="d5",
            role="developer",
            objective="Build",
            depends_on=["d3", "d4"],
        ),
    ]
    plan = _make_plan(items)
    assert compute_graph_depth(plan) == 5
    with pytest.raises(DAGValidationError, match="Graph depth 5 exceeds maximum allowed depth 4"):
        validate_dag_structure(plan)


def test_requirement_u_unknown_role_rejected():
    """Requirement U: Unknown specialist role rejected."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="item_unknown",
            role="devops_engineer",  # Non-existent role
            objective="Configure Kubernetes",
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(PlanValidationError, match="Unknown specialist role 'devops_engineer'"):
        validate_dag_structure(plan)


def test_requirement_v_ceo_as_work_item_rejected():
    """Requirement V: CEO cannot appear as a specialist work item."""
    items = [
        CEOPlannedWorkItem(
            work_item_id="ceo_item",
            role="ceo",
            objective="Direct company strategy",
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(PlanValidationError, match="CEO cannot appear as a work item role"):
        validate_dag_structure(plan)


def test_requirement_w_normal_qa_node_after_developer_rejected():
    """Requirement W: Normal QA node after Developer rejected (QA is application-owned)."""
    items = [
        CEOPlannedWorkItem(work_item_id="prod_01", role="product", objective="PRD"),
        CEOPlannedWorkItem(work_item_id="ux_01", role="ux", objective="UX", depends_on=["prod_01"]),
        CEOPlannedWorkItem(
            work_item_id="dev_01",
            role="developer",
            objective="Code",
            depends_on=["prod_01", "ux_01"],
        ),
        CEOPlannedWorkItem(
            work_item_id="qa_01",
            role="qa",
            objective="Verify code changes",
            depends_on=["dev_01"],  # Developer -> QA directly forbidden in CEO plan
        ),
    ]
    plan = _make_plan(items)
    with pytest.raises(DAGValidationError, match="Direct Developer -> QA dependency is forbidden"):
        validate_dag_structure(plan)


def test_requirement_x_deterministic_ready_node_ordering():
    """Requirement X: Ready work items sorted by (priority ASC, work_item_id ASC)."""
    items = [
        CEOPlannedWorkItem(work_item_id="task_z", role="research", objective="Z", priority=2),
        CEOPlannedWorkItem(work_item_id="task_b", role="product", objective="B", priority=1),
        CEOPlannedWorkItem(work_item_id="task_a", role="ux", objective="A", priority=1),
        CEOPlannedWorkItem(work_item_id="task_m", role="marketing", objective="M", priority=3),
    ]
    plan = _make_plan(items)

    ready = select_ready_work_items(plan, completed_item_ids=set())
    # Should be sorted: priority 1 (task_a, task_b), priority 2 (task_z), priority 3 (task_m)
    ready_ids = [r.work_item_id for r in ready]
    assert ready_ids == ["task_a", "task_b", "task_z", "task_m"]


def test_requirement_y_dependency_completion_controls_readiness():
    """Requirement Y: Dependency completion controls work item readiness."""
    items = [
        CEOPlannedWorkItem(work_item_id="prod", role="product", objective="PRD", priority=1),
        CEOPlannedWorkItem(work_item_id="ux", role="ux", objective="UX", depends_on=["prod"], priority=1),
        CEOPlannedWorkItem(
            work_item_id="dev",
            role="developer",
            objective="Dev",
            depends_on=["prod", "ux"],
            priority=1,
        ),
    ]
    plan = _make_plan(items)

    # Initial state: only prod is ready
    ready_0 = select_ready_work_items(plan, completed_item_ids=set())
    assert [r.work_item_id for r in ready_0] == ["prod"]

    # Prod completed: ux becomes ready, dev is still not ready (needs ux)
    ready_1 = select_ready_work_items(plan, completed_item_ids={"prod"})
    assert [r.work_item_id for r in ready_1] == ["ux"]

    # Prod and UX completed: dev becomes ready
    ready_2 = select_ready_work_items(plan, completed_item_ids={"prod", "ux"})
    assert [r.work_item_id for r in ready_2] == ["dev"]

    # All completed: nothing ready
    ready_3 = select_ready_work_items(plan, completed_item_ids={"prod", "ux", "dev"})
    assert ready_3 == []


def test_topological_sort_deterministic_tie_breaking():
    """Topological sorting breaks ties deterministically by (priority ASC, work_item_id ASC)."""
    items = [
        CEOPlannedWorkItem(work_item_id="root_c", role="research", objective="C", priority=2),
        CEOPlannedWorkItem(work_item_id="root_b", role="product", objective="B", priority=1),
        CEOPlannedWorkItem(work_item_id="root_a", role="product", objective="A", priority=1),
    ]
    plan = _make_plan(items)
    order = get_topological_order(plan)
    assert order == ["root_a", "root_b", "root_c"]
