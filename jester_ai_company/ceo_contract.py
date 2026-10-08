"""CEO Orchestration Planning Contract & Parsing Pipeline (STEP 17B-2).

Enforces the boundary between the untrusted CEO LLM and the deterministic application:
- CEO Planning Prompt Builder for CompanyObjective
- Untrusted output extraction & multi-payload detection
- Strict schema parsing & trust boundary enforcement
- DAG structural and prerequisite validation via STEP 17B-1 DAG engine
- Zero executable authority in parsed plans
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
import uuid

from .dag import (
    MAX_GRAPH_DEPTH,
    MAX_PLANNED_WORK_ITEMS,
    RECOGNIZED_MACRO_ROLES,
    validate_dag_structure,
)
from .orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    DAGValidationError,
    OrchestrationError,
    PlanValidationError,
    PROHIBITED_QA_CAPABILITIES,
    SUPPORTED_QA_CAPABILITIES,
    WorkItemState,
)

CEO_PLAN_SCHEMA_VERSION: str = "1.0"
MAX_RAW_CEO_OUTPUT_CHARS: int = 30_000

# Prohibited authority-bearing fields/actions in CEO output
PRIVILEGED_TOP_LEVEL_KEYS: Set[str] = {
    "grant",
    "grants",
    "execution_grant",
    "real_repo_apply_grant",
    "approve_real_repo",
    "skip_qa",
    "override_qa",
    "apply_patch",
    "git_apply",
    "run_shell",
    "write_file",
    "shell",
    "command",
    "commands",
    "actions",
    "action_type",
    "certification",
    "certify",
    "qa_certification",
}

PRIVILEGED_WORK_ITEM_KEYS: Set[str] = {
    "grant",
    "grants",
    "execution_grant",
    "real_repo_apply_grant",
    "shell",
    "command",
    "commands",
    "callback",
    "callbacks",
    "apply",
    "approval",
    "approved",
    "actions",
    "certification",
    "certify",
    "qa_certification",
}


class CEOPlanExtractionError(PlanValidationError):
    """Raised when structured JSON cannot be extracted from raw CEO output."""
    pass


class CEOPlanSecurityError(PlanValidationError):
    """Raised when CEO output attempts to express privileged or unauthorized authority."""
    pass


def build_ceo_planning_prompt(
    objective: CompanyObjective,
    project_knowledge: Optional[Any] = None,
) -> str:
    """Build a deterministic, bounded planning prompt for the CEO agent.

    Instructs the CEO to evaluate the CompanyObjective and formulate a pure data
    macro orchestration plan matching the strict schema.
    """
    if not isinstance(objective, CompanyObjective):
        raise PlanValidationError("Expected CompanyObjective instance.")

    roles_str = ", ".join(f"'{r}'" for r in sorted(RECOGNIZED_MACRO_ROLES))
    qa_caps_str = ", ".join(f"'{c}'" for c in sorted(SUPPORTED_QA_CAPABILITIES))
    constraints_str = (
        "\n".join(f"- {c}" for c in objective.constraints)
        if objective.constraints
        else "- None specified"
    )
    criteria_str = (
        "\n".join(f"- {ac}" for ac in objective.acceptance_criteria)
        if objective.acceptance_criteria
        else "- None specified"
    )
    repo_str = (
        f"\nTARGET REPOSITORY: {objective.target_repository}\n"
        if objective.target_repository
        else ""
    )

    knowledge_block = ""
    if project_knowledge:
        from .context import format_project_knowledge_prompt_block
        knowledge_block = format_project_knowledge_prompt_block(project_knowledge)

    return (
        "SYSTEM INSTRUCTION: You are the CEO of Jester AI Company operating in "
        "ORCHESTRATION PLANNING MODE.\n\n"
        "GOVERNANCE & BOUNDARIES:\n"
        "1. The Human Founder is the ultimate decision maker and strategic authority.\n"
        "2. Your role is strategic and operational coordination. You produce a macro execution plan as DATA ONLY.\n"
        "3. You do NOT execute specialists or invoke subagents.\n"
        "4. You have NO authority to run shell commands, write files, create execution grants, or apply repository patches.\n"
        "5. You cannot skip QA, override QA, or claim work is completed.\n"
        "6. Work items must NOT contain shell commands, grants, callbacks, or execution authority.\n"
        f"7. Work item count must be between 1 and {MAX_PLANNED_WORK_ITEMS}.\n"
        f"8. Maximum graph depth is {MAX_GRAPH_DEPTH} (root nodes have depth 1).\n"
        f"9. Eligible macro specialist roles are: {roles_str}. Never assign work items to 'ceo'.\n"
        "10. Critical Developer Fan-In invariant: If a 'developer' work item is planned, it MUST directly depend on BOTH a 'product' work item and a 'ux' work item in 'depends_on'.\n"
        f"11. QA Role Contract: Engineering QA certification is strictly application-owned inside code pipelines. If a 'qa' work item is planned in the DAG, it must be delegated ONLY for non-mutating planning or audit work with an explicit 'capability' field matching one of: {qa_caps_str}. A 'qa' work item must NEVER depend on 'developer', must NEVER request certification or patch verification, and must NEVER issue execution grants or apply permissions.\n"
        "12. 'depends_on' represents execution ordering; it is NOT automatic artifact sharing.\n\n"
        f"{knowledge_block}"
        f"COMPANY OBJECTIVE:\n"
        f"ID: {objective.id}\n"
        f"TITLE: {objective.title}\n"
        f"DESCRIPTION: {objective.description}\n"
        f"CONSTRAINTS:\n{constraints_str}\n"
        f"ACCEPTANCE CRITERIA:\n{criteria_str}"
        f"{repo_str}\n\n"
        "REQUIRED OUTPUT FORMAT:\n"
        "Return strictly a single valid JSON object adhering to schema_version '1.0'.\n"
        "Do NOT include any explanatory text, markdown prose, or conversation outside the JSON block.\n\n"
        "JSON SCHEMA:\n"
        "{\n"
        '  "schema_version": "1.0",\n'
        '  "plan_id": "plan_<concise_id>",\n'
        f'  "objective_id": "{objective.id}",\n'
        '  "version": 1,\n'
        '  "work_items": [\n'
        '    {\n'
        '      "work_item_id": "<unique_id>",\n'
        f'      "role": "<one of: {roles_str}>",\n'
        f'      "capability": "<required for qa: one of {qa_caps_str}; optional for other roles>",\n'
        '      "objective": "<clear macro task goal>",\n'
        '      "depends_on": ["<prerequisite_work_item_id>", ...],\n'
        '      "expected_outputs": ["<deliverable_name>", ...],\n'
        '      "priority": 1\n'
        '    }\n'
        '  ],\n'
        '  "completion_criteria": ["<milestone 1>", ...],\n'
        '  "constraints": ["<constraint 1>", ...]\n'
        "}\n"
    )


def extract_ceo_plan_json(raw_text: str) -> str:
    """Extract structured JSON payload from raw CEO model output.

    Handles:
    - Pure raw JSON: '{"schema_version": "1.0", ...}'
    - Fenced JSON: '```json\\n{...}\\n```' or '```\\n{...}\\n```'
    - Surrounding whitespace

    Enforces fail-closed rules:
    - Rejects empty input.
    - Rejects oversized input (> MAX_RAW_CEO_OUTPUT_CHARS).
    - Rejects ambiguous multiple JSON objects.
    """
    if not raw_text or not isinstance(raw_text, str):
        raise CEOPlanExtractionError("Raw CEO output is empty or not a string.")

    if len(raw_text) > MAX_RAW_CEO_OUTPUT_CHARS:
        raise CEOPlanExtractionError(
            f"Oversized CEO output ({len(raw_text)} chars) exceeds maximum allowed "
            f"limit of {MAX_RAW_CEO_OUTPUT_CHARS} characters."
        )

    cleaned = raw_text.strip()

    # 1. Check for fenced code blocks
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fenced_blocks:
        valid_candidates: List[str] = []
        for block in fenced_blocks:
            b_clean = block.strip()
            if b_clean.startswith("{") and b_clean.endswith("}"):
                valid_candidates.append(b_clean)

        if len(valid_candidates) > 1:
            raise CEOPlanExtractionError(
                f"Multiple ambiguous JSON payloads ({len(valid_candidates)}) detected in CEO output."
            )
        if len(valid_candidates) == 1:
            return valid_candidates[0]

        # If fenced blocks didn't have strict braces, fallback to first non-empty fenced content
        for block in fenced_blocks:
            if block.strip():
                return block.strip()

    # 2. Check for outer { ... }
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise CEOPlanExtractionError("No JSON object detected in CEO output.")

    candidate = cleaned[first_brace : last_brace + 1].strip()

    # 3. Check for multiple consecutive top-level JSON objects (e.g. '}{')
    # A single valid object should decode completely with JSONDecoder
    decoder = json.JSONDecoder()
    try:
        obj, end_idx = decoder.raw_decode(candidate)
        remainder = candidate[end_idx:].strip()
        if remainder:
            # Check if remainder contains another JSON object
            if "{" in remainder and "}" in remainder:
                raise CEOPlanExtractionError(
                    "Multiple ambiguous top-level JSON payloads detected in CEO output."
                )
    except json.JSONDecodeError as exc:
        raise CEOPlanExtractionError(f"Malformed JSON syntax in CEO output: {exc}") from exc

    return candidate


def parse_and_validate_ceo_plan(
    raw_text: str,
    objective: CompanyObjective,
) -> CEOOrchestrationPlan:
    """Parse, validate against trust boundary, and verify DAG structure of CEO output.

    Pipeline:
    raw text -> bounded extraction -> schema checks -> security checks
             -> trusted domain model construction -> validate_dag_structure

    Raises:
        CEOPlanExtractionError: If JSON cannot be cleanly extracted.
        CEOPlanSecurityError: If privileged authority or runtime-owned fields are supplied.
        PlanValidationError: If schema, versions, or objective references are invalid.
        DAGValidationError: If graph structure, cycles, depths, or fan-in rules are violated.
    """
    if not isinstance(objective, CompanyObjective):
        raise PlanValidationError("Expected CompanyObjective instance.")

    json_text = extract_ceo_plan_json(raw_text)

    try:
        data = json.loads(json_text, strict=False)
    except (json.JSONDecodeError, TypeError) as exc:
        raise CEOPlanExtractionError(f"Malformed JSON in CEO response: {exc}") from exc

    if not isinstance(data, dict):
        raise PlanValidationError("CEO plan payload must be a JSON dictionary.")

    # 1. Schema version verification
    schema_ver = data.get("schema_version")
    if schema_ver != CEO_PLAN_SCHEMA_VERSION:
        raise PlanValidationError(
            f"Unsupported schema_version '{schema_ver}'. Expected '{CEO_PLAN_SCHEMA_VERSION}'."
        )

    # 2. Objective ID verification (CEO cannot redirect plan to another objective)
    obj_id = data.get("objective_id")
    if not obj_id or str(obj_id).strip() != objective.id:
        raise PlanValidationError(
            f"Plan objective_id '{obj_id}' does not match expected objective ID '{objective.id}'."
        )

    # 3. Version verification (initial planning must be version 1)
    plan_ver = data.get("version")
    if plan_ver != 1:
        raise PlanValidationError(
            f"Initial CEO plan version must be 1, got '{plan_ver}'."
        )

    # 4. Security checks: reject privileged top-level keys
    for key in PRIVILEGED_TOP_LEVEL_KEYS:
        if key in data:
            raise CEOPlanSecurityError(
                f"Unauthorized privileged key '{key}' detected in CEO plan payload."
            )

    # 5. Work items existence and structure
    raw_items = data.get("work_items")
    if raw_items is None:
        raise PlanValidationError("Field 'work_items' is required in CEO plan.")
    if not isinstance(raw_items, list):
        raise PlanValidationError("Field 'work_items' must be a list.")
    if len(raw_items) == 0:
        raise PlanValidationError("Plan must contain at least 1 work item.")
    if len(raw_items) > MAX_PLANNED_WORK_ITEMS:
        raise DAGValidationError(
            f"Work item count ({len(raw_items)}) exceeds maximum allowed "
            f"limit of {MAX_PLANNED_WORK_ITEMS}."
        )

    # 6. Parse and sanitize work items under strict trust boundary
    parsed_items: List[CEOPlannedWorkItem] = []
    seen_ids: Set[str] = set()

    for idx, item_data in enumerate(raw_items):
        if not isinstance(item_data, dict):
            raise PlanValidationError(f"Work item at index {idx} must be a dictionary.")

        # Check for privileged keys in work item
        for key in PRIVILEGED_WORK_ITEM_KEYS:
            if key in item_data:
                raise CEOPlanSecurityError(
                    f"Unauthorized privileged key '{key}' detected in work item at index {idx}."
                )

        # Enforce application ownership of runtime fields:
        # Reject if CEO attempts to supply task_id, run_id, or non-pending state
        if item_data.get("task_id") is not None and str(item_data.get("task_id")).strip():
            raise CEOPlanSecurityError(
                f"Work item at index {idx} specifies application-owned 'task_id'."
            )
        if item_data.get("run_id") is not None and str(item_data.get("run_id")).strip():
            raise CEOPlanSecurityError(
                f"Work item at index {idx} specifies application-owned 'run_id'."
            )

        state_val = item_data.get("state")
        if state_val is not None:
            norm_state = str(state_val).strip()
            if norm_state != WorkItemState.PENDING.value:
                raise CEOPlanSecurityError(
                    f"Work item at index {idx} specifies unauthorized runtime state '{norm_state}' "
                    f"(initial state must be PENDING)."
                )

        item_id = item_data.get("work_item_id")
        if not item_id or not isinstance(item_id, str) or not item_id.strip():
            raise PlanValidationError(f"Work item at index {idx} missing valid 'work_item_id'.")
        clean_id = item_id.strip()

        role = item_data.get("role")
        if not role or not isinstance(role, str) or not role.strip():
            raise PlanValidationError(f"Work item '{clean_id}' missing valid 'role'.")
        clean_role = role.strip().lower()

        objective_text = item_data.get("objective")
        if not objective_text or not isinstance(objective_text, str) or not objective_text.strip():
            raise PlanValidationError(f"Work item '{clean_id}' missing valid 'objective'.")

        depends_on = item_data.get("depends_on", [])
        if not isinstance(depends_on, list):
            raise PlanValidationError(f"Work item '{clean_id}' 'depends_on' must be a list.")
        clean_deps = [str(d).strip() for d in depends_on if str(d).strip()]

        expected_outputs = item_data.get("expected_outputs", [])
        if not isinstance(expected_outputs, list):
            raise PlanValidationError(f"Work item '{clean_id}' 'expected_outputs' must be a list.")
        clean_outputs = [str(o).strip() for o in expected_outputs if str(o).strip()]

        try:
            priority_val = int(item_data.get("priority", 1))
        except (ValueError, TypeError):
            priority_val = 1

        raw_cap = item_data.get("capability") or item_data.get("work_type")
        clean_cap = str(raw_cap).strip().lower() if raw_cap and isinstance(raw_cap, str) else None

        parsed_items.append(
            CEOPlannedWorkItem(
                work_item_id=clean_id,
                role=clean_role,
                capability=clean_cap,
                objective=objective_text.strip(),
                depends_on=clean_deps,
                expected_outputs=clean_outputs,
                priority=max(1, priority_val),
                state=WorkItemState.PENDING.value,
                refinement_count=0,
                task_id=None,
                run_id=None,
            )
        )

    # 7. Construct trusted CEOOrchestrationPlan
    plan_id = str(data.get("plan_id", "")).strip() or f"plan_{uuid.uuid4().hex[:8]}"
    completion_criteria = [
        str(c).strip() for c in data.get("completion_criteria", []) if str(c).strip()
    ]
    constraints = [
        str(con).strip() for con in data.get("constraints", []) if str(con).strip()
    ]

    plan = CEOOrchestrationPlan(
        schema_version=CEO_PLAN_SCHEMA_VERSION,
        plan_id=plan_id,
        objective_id=objective.id,
        version=1,
        work_items=parsed_items,
        completion_criteria=completion_criteria,
        constraints=constraints,
    )

    # 8. Deterministic DAG validation (roles, cycles, depth, Developer Fan-In, QA pipeline)
    validate_dag_structure(plan)

    return plan
