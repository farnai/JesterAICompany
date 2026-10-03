"""Pure deterministic DAG validation and traversal engine for CEO Orchestration (STEP 17).

Provides mathematical dependency graph validation, cycle detection, depth calculation,
topological ordering, and ready-node selection without external graph libraries,
LLM calls, or filesystem mutations.
"""

from collections import deque
from typing import Dict, List, Optional, Set

from .orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    DAGValidationError,
    PlanValidationError,
    WorkItemState,
)

MAX_PLANNED_WORK_ITEMS: int = 6
MAX_GRAPH_DEPTH: int = 4

RECOGNIZED_MACRO_ROLES: Set[str] = {
    "product",
    "research",
    "ux",
    "marketing",
    "developer",
    "qa",
}


def validate_dag_structure(plan: CEOOrchestrationPlan) -> None:
    """Deterministically validate the structural integrity of a CEOOrchestrationPlan DAG.

    Enforces:
    1. Work item count between 1 and MAX_PLANNED_WORK_ITEMS (6).
    2. Unique work_item_id for all nodes.
    3. Recognized macro specialist roles (CEO role rejected).
    4. Valid dependency references (no self-dependencies, no unknown targets).
    5. No direct Developer -> QA edge (QA is application-owned in code pipelines).
    6. Critical Developer Fan-In invariant (Developer must depend on both Product and UX).
    7. Acyclic structure (cycle detection via Kahn's algorithm).
    8. Maximum graph depth <= MAX_GRAPH_DEPTH (4).

    Raises:
        PlanValidationError: If basic plan properties, work item counts, or roles are invalid.
        DAGValidationError: If graph topology, dependencies, cycles, or depths are invalid.
    """
    if not isinstance(plan, CEOOrchestrationPlan):
        raise PlanValidationError("Expected CEOOrchestrationPlan instance.")

    # 1. Bounds on work item count
    if not plan.work_items or len(plan.work_items) == 0:
        raise PlanValidationError("Plan must contain at least 1 work item.")

    if len(plan.work_items) > MAX_PLANNED_WORK_ITEMS:
        raise DAGValidationError(
            f"Work item count ({len(plan.work_items)}) exceeds maximum allowed "
            f"limit of {MAX_PLANNED_WORK_ITEMS}."
        )

    # 2. Unique work_item_id & basic node validation
    items_by_id: Dict[str, CEOPlannedWorkItem] = {}
    for item in plan.work_items:
        if not item.work_item_id or not item.work_item_id.strip():
            raise PlanValidationError("Work item missing work_item_id.")

        item_id = item.work_item_id.strip()
        if item_id in items_by_id:
            raise DAGValidationError(f"Duplicate work_item_id '{item_id}' detected.")

        # 3. Role validation
        role_norm = (item.role or "").strip().lower()
        if role_norm == "ceo":
            raise PlanValidationError(
                "CEO cannot appear as a work item role in orchestration plans."
            )
        if role_norm not in RECOGNIZED_MACRO_ROLES:
            raise PlanValidationError(
                f"Unknown specialist role '{item.role}'. Must be one of: "
                f"{sorted(RECOGNIZED_MACRO_ROLES)}."
            )

        items_by_id[item_id] = item

    all_ids = set(items_by_id.keys())

    # 4. Dependency reference & role-specific invariants
    for item_id, item in items_by_id.items():
        dep_set: Set[str] = set()
        for dep in item.depends_on:
            dep_clean = dep.strip()
            if dep_clean == item_id:
                raise DAGValidationError(
                    f"Self-dependency detected for work item '{item_id}'."
                )
            if dep_clean not in all_ids:
                raise DAGValidationError(
                    f"Work item '{item_id}' depends on unknown item '{dep_clean}'."
                )
            dep_set.add(dep_clean)

        # 5. QA code-pipeline rule: Developer -> QA is forbidden in CEO plans
        if item.role.lower() == "qa":
            for dep in dep_set:
                if items_by_id[dep].role.lower() == "developer":
                    raise DAGValidationError(
                        f"Direct Developer -> QA dependency is forbidden in CEO plans "
                        f"('{dep}' -> '{item_id}'). QA is application-owned inside code pipelines."
                    )

        # 6. Critical Developer Fan-In invariant:
        # Developer must directly depend on both a Product item and a UX item
        if item.role.lower() == "developer":
            dep_roles = {items_by_id[dep].role.lower() for dep in dep_set}
            has_product = "product" in dep_roles
            has_ux = "ux" in dep_roles
            if not (has_product and has_ux):
                raise DAGValidationError(
                    f"Developer work item '{item_id}' requires both Product and UX "
                    f"prerequisites in depends_on. Found dependent roles: {sorted(dep_roles)}."
                )

    # 7. Cycle detection via Kahn's algorithm & topological sort
    in_degree: Dict[str, int] = {item_id: 0 for item_id in all_ids}
    adj: Dict[str, List[str]] = {item_id: [] for item_id in all_ids}

    for item_id, item in items_by_id.items():
        for dep in item.depends_on:
            adj[dep.strip()].append(item_id)
            in_degree[item_id] += 1

    queue: deque[str] = deque(
        [item_id for item_id in sorted(all_ids) if in_degree[item_id] == 0]
    )
    visited_count = 0

    while queue:
        curr = queue.popleft()
        visited_count += 1
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(all_ids):
        raise DAGValidationError("Cycle detected in work item dependencies.")

    # 8. Graph depth calculation
    depth = compute_graph_depth(plan)
    if depth > MAX_GRAPH_DEPTH:
        raise DAGValidationError(
            f"Graph depth {depth} exceeds maximum allowed depth {MAX_GRAPH_DEPTH}."
        )


def compute_graph_depth(plan: CEOOrchestrationPlan) -> int:
    """Calculate the maximum path depth of the DAG.

    Depth semantics:
    - Root nodes (no dependencies) have depth = 1.
    - Each node's depth = 1 + max(depth of all depends_on nodes).
    - Maximum path depth is the maximum depth across all nodes in the plan.
    """
    if not plan.work_items:
        return 0

    items_by_id = {item.work_item_id.strip(): item for item in plan.work_items}

    # Memoized depth computation
    depth_memo: Dict[str, int] = {}

    def get_node_depth(node_id: str, visited: Set[str]) -> int:
        if node_id in depth_memo:
            return depth_memo[node_id]
        if node_id in visited:
            # Cycle safety fallback (though validate_dag_structure checks cycles first)
            return 999

        item = items_by_id.get(node_id)
        if not item or not item.depends_on:
            depth_memo[node_id] = 1
            return 1

        visited.add(node_id)
        max_parent_depth = max(
            get_node_depth(parent.strip(), visited) for parent in item.depends_on
        )
        visited.remove(node_id)

        d = 1 + max_parent_depth
        depth_memo[node_id] = d
        return d

    max_d = 0
    for item_id in items_by_id:
        d = get_node_depth(item_id, set())
        if d > max_d:
            max_d = d

    return max_d


def get_topological_order(plan: CEOOrchestrationPlan) -> List[str]:
    """Return work_item_ids ordered topologically with deterministic tie-breaking.

    Tie-breaking: (priority ASC, work_item_id ASC)
    """
    items_by_id = {item.work_item_id.strip(): item for item in plan.work_items}
    all_ids = set(items_by_id.keys())

    in_degree: Dict[str, int] = {item_id: len(items_by_id[item_id].depends_on) for item_id in all_ids}
    adj: Dict[str, List[str]] = {item_id: [] for item_id in all_ids}

    for item_id, item in items_by_id.items():
        for dep in item.depends_on:
            adj[dep.strip()].append(item_id)

    order: List[str] = []
    ready = [
        item_id for item_id in all_ids if in_degree[item_id] == 0
    ]
    # Sort deterministically
    ready.sort(key=lambda x: (items_by_id[x].priority, x))

    while ready:
        curr = ready.pop(0)
        order.append(curr)
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                ready.append(neighbor)
                ready.sort(key=lambda x: (items_by_id[x].priority, x))

    if len(order) != len(all_ids):
        raise DAGValidationError("Cycle detected during topological sorting.")

    return order


def select_ready_work_items(
    plan: CEOOrchestrationPlan,
    completed_item_ids: Set[str],
    current_states: Optional[Dict[str, str]] = None,
) -> List[CEOPlannedWorkItem]:
    """Select all work items ready for execution, sorted deterministically.

    A work item is ready when:
    1. Its current state is PENDING.
    2. It is not already in completed_item_ids.
    3. Every prerequisite item in its depends_on is in completed_item_ids.

    Sort order:
        (priority ASC, work_item_id ASC)

    Returns:
        Deterministically ordered list of ready CEOPlannedWorkItem objects.
    """
    states = current_states or {item.work_item_id: item.state for item in plan.work_items}
    ready_items: List[CEOPlannedWorkItem] = []

    for item in plan.work_items:
        item_id = item.work_item_id.strip()
        state = states.get(item_id, item.state)

        # Must be PENDING and not already completed
        if state != WorkItemState.PENDING.value or item_id in completed_item_ids:
            continue

        # All dependencies must be COMPLETED
        deps_satisfied = all(
            dep.strip() in completed_item_ids for dep in item.depends_on
        )
        if deps_satisfied:
            ready_items.append(item)

    # Deterministic sorting
    ready_items.sort(key=lambda x: (x.priority, x.work_item_id))
    return ready_items
