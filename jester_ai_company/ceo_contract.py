"""CEO Orchestration Planning Contract & Parsing Pipeline (STEP 17B-2).

Enforces the boundary between the untrusted CEO LLM and the deterministic application:
- CEO Planning Prompt Builder for CompanyObjective
- Untrusted output extraction & multi-payload detection
- Strict schema parsing & trust boundary enforcement
- DAG structural and prerequisite validation via STEP 17B-1 DAG engine
- Zero executable authority in parsed plans
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
import uuid

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

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


class CEODecisionValidationError(PlanValidationError):
    """Raised when CEO decision evaluation result fails contract validation."""
    pass


class CEODecisionSecurityError(CEOPlanSecurityError):
    """Raised when CEO decision evaluation result contains unauthorized privileged authority."""
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
    team_selection: Optional[Any] = None,
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

        if team_selection is not None:
            sel_roles = getattr(team_selection, "selected_roles", None)
            if sel_roles is None and isinstance(team_selection, dict):
                sel_roles = team_selection.get("selected_roles")
            enforce_strict = getattr(team_selection, "enforce_strict_roles", False)
            if isinstance(team_selection, dict):
                enforce_strict = team_selection.get("enforce_strict_roles", False)
            if enforce_strict and sel_roles and clean_role not in [str(r).lower() for r in sel_roles]:
                raise PlanValidationError(
                    f"Work item '{clean_id}' specifies role '{clean_role}' which was omitted in CEO team selection."
                )
            elif sel_roles and clean_role not in [str(r).lower() for r in sel_roles]:
                sel_roles.append(clean_role)
                if hasattr(team_selection, "actual_specialist_count"):
                    team_selection.actual_specialist_count = len(sel_roles)
                elif isinstance(team_selection, dict):
                    team_selection["actual_specialist_count"] = len(sel_roles)

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

    task_category = data.get("task_category")
    allow_direct_developer = bool(data.get("allow_direct_developer", False))
    if team_selection is not None:
        sel_cat = getattr(team_selection, "task_category", None)
        sel_direct = getattr(team_selection, "allow_direct_developer", False)
        if isinstance(team_selection, dict):
            sel_cat = team_selection.get("task_category")
            sel_direct = bool(team_selection.get("allow_direct_developer", False))
        if not task_category and sel_cat:
            task_category = sel_cat
        if sel_direct:
            allow_direct_developer = True
    elif task_category in ("BUG_FIX", "SECURITY_SENSITIVE"):
        allow_direct_developer = True

    plan = CEOOrchestrationPlan(
        schema_version=CEO_PLAN_SCHEMA_VERSION,
        plan_id=plan_id,
        objective_id=objective.id,
        version=1,
        work_items=parsed_items,
        completion_criteria=completion_criteria,
        constraints=constraints,
        task_category=task_category,
        allow_direct_developer=allow_direct_developer,
    )

    # 8. Deterministic DAG validation (roles, cycles, depth, Developer Fan-In, QA pipeline)
    validate_dag_structure(plan)

    return plan


# -----------------------------------------------------------------------------
# STEP 23B.2: CEO Requirement Evaluation & Autonomous Investigation Contract
# -----------------------------------------------------------------------------

class CEODecisionType(str, Enum):
    """The three controlled outcomes of CEO requirement evaluation."""
    EXECUTE = "EXECUTE"
    INVESTIGATE = "INVESTIGATE"
    ASK_FOUNDER = "ASK_FOUNDER"


@dataclass
class CEODecisionResult:
    """Structured, validated decision result of CEO requirement evaluation (STEP 23B.2)."""
    decision: str
    reasoning_summary: str
    known_facts: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    missing_critical_information: List[str] = field(default_factory=list)
    proposed_next_action: str = ""
    clarification_question: Optional[str] = None
    investigation_targets: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        valid_decisions = {d.value for d in CEODecisionType}
        if self.decision not in valid_decisions:
            raise CEODecisionValidationError(
                f"Invalid CEO decision '{self.decision}' (missing or invalid 'decision'). Must be one of: {sorted(valid_decisions)}."
            )
        if not self.reasoning_summary or not str(self.reasoning_summary).strip():
            raise CEODecisionValidationError("CEODecisionResult must include a non-empty 'reasoning_summary'.")
        if self.decision == CEODecisionType.ASK_FOUNDER.value:
            if not self.clarification_question or not str(self.clarification_question).strip():
                raise CEODecisionValidationError("CEODecisionResult with ASK_FOUNDER must include a 'clarification_question'.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision,
            "reasoning_summary": self.reasoning_summary,
            "known_facts": list(self.known_facts),
            "assumptions": list(self.assumptions),
            "missing_critical_information": list(self.missing_critical_information),
            "proposed_next_action": self.proposed_next_action,
            "clarification_question": self.clarification_question,
            "investigation_targets": list(self.investigation_targets),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CEODecisionResult":
        if not isinstance(data, dict):
            raise CEODecisionValidationError("Expected dictionary for CEODecisionResult.")

        for key in data.keys():
            k_lower = key.lower()
            if (
                k_lower in PRIVILEGED_TOP_LEVEL_KEYS
                or k_lower in PRIVILEGED_WORK_ITEM_KEYS
                or "grant" in k_lower
                or "bypass" in k_lower
                or "skip_qa" in k_lower
                or "override" in k_lower
            ):
                raise CEODecisionSecurityError(f"Prohibited authority key '{key}' in CEO decision result.")

        decision = data.get("decision")
        if not decision or not isinstance(decision, str):
            raise CEODecisionValidationError("CEODecisionResult missing or invalid 'decision'.")
        decision_clean = decision.strip().upper()
        valid_decisions = {d.value for d in CEODecisionType}
        if decision_clean not in valid_decisions:
            raise CEODecisionValidationError(
                f"CEODecisionResult missing or invalid 'decision': '{decision_clean}'. Must be one of: {sorted(valid_decisions)}."
            )

        reasoning = data.get("reasoning_summary") or data.get("reasoning")
        if not reasoning or not isinstance(reasoning, str):
            raise CEODecisionValidationError("CEODecisionResult missing or invalid 'reasoning_summary'.")

        known_facts = [str(f) for f in data.get("known_facts", [])]
        assumptions = [str(a) for a in data.get("assumptions", [])]
        missing_info = [str(m) for m in data.get("missing_critical_information", [])]
        proposed_action = str(data.get("proposed_next_action", "")).strip()
        clarification_q = data.get("clarification_question")
        if clarification_q is not None:
            clarification_q = str(clarification_q).strip() or None
        targets = [str(t) for t in data.get("investigation_targets", [])]

        return cls(
            decision=decision_clean,
            reasoning_summary=reasoning.strip(),
            known_facts=known_facts,
            assumptions=assumptions,
            missing_critical_information=missing_info,
            proposed_next_action=proposed_action,
            clarification_question=clarification_q,
            investigation_targets=targets,
            created_at=data.get("created_at") or _utc_now_iso(),
        )


def build_ceo_evaluation_prompt(
    objective: CompanyObjective,
    project_knowledge: Optional[Any] = None,
    investigation_findings: Optional[List[str]] = None,
    founder_clarifications: Optional[List[Dict[str, Any]]] = None,
    investigation_count: int = 0,
    max_investigations: int = 2,
) -> str:
    """Build a deterministic evaluation prompt for the CEO to evaluate requirements."""
    prompt_lines = [
        "You are the CEO of Jester AI Company.",
        "Your task is to evaluate the Founder's objective and decide the immediate workflow outcome.",
        "",
        "AVAILABLE OUTCOMES:",
        "1. EXECUTE: Sufficient unambiguous information to proceed with DAG planning.",
        "2. INVESTIGATE: Read-only codebase / doc inspection can resolve uncertainty.",
        "3. ASK_FOUNDER: Essential missing business / policy / scope information requires human decision.",
        "",
        f"OBJECTIVE TITLE: {objective.title}",
        f"OBJECTIVE DESCRIPTION: {objective.description}",
        f"CONSTRAINTS: {objective.constraints}",
        f"ACCEPTANCE CRITERIA: {objective.acceptance_criteria}",
        f"INVESTIGATION BUDGET: {investigation_count}/{max_investigations} used",
    ]

    if investigation_findings:
        prompt_lines.append("")
        prompt_lines.append("AUTONOMOUS INVESTIGATION FINDINGS SO FAR:")
        for finding in investigation_findings:
            prompt_lines.append(f"- {finding}")

    if founder_clarifications:
        prompt_lines.append("")
        prompt_lines.append("FOUNDER CLARIFICATIONS PROVIDED:")
        for clar in founder_clarifications:
            resp = clar.get("response", "")
            prompt_lines.append(f"- {resp}")

    prompt_lines.extend([
        "",
        "STRICT OUTPUT INSTRUCTIONS:",
        "Output ONLY a single JSON object matching this schema:",
        "{",
        '  "decision": "EXECUTE" | "INVESTIGATE" | "ASK_FOUNDER",',
        '  "reasoning_summary": "Concise summary of rationale",',
        '  "known_facts": ["fact 1", "fact 2"],',
        '  "assumptions": ["assumption 1"],',
        '  "missing_critical_information": ["missing info"],',
        '  "proposed_next_action": "Action to be taken",',
        '  "clarification_question": "Required only if ASK_FOUNDER, else null",',
        '  "investigation_targets": ["files or topics to inspect if INVESTIGATE"]',
        "}",
    ])

    return "\n".join(prompt_lines)


def parse_and_validate_ceo_decision(raw_output: str) -> CEODecisionResult:
    """Extract and validate CEODecisionResult from raw LLM output."""
    if not raw_output or not isinstance(raw_output, str) or not raw_output.strip():
        raise CEOPlanExtractionError("Raw CEO evaluation output is empty or whitespace.")

    cleaned = raw_output.strip()
    if len(cleaned) > MAX_RAW_CEO_OUTPUT_CHARS:
        raise CEOPlanExtractionError(
            f"Raw CEO output exceeded maximum allowed length ({len(cleaned)} > {MAX_RAW_CEO_OUTPUT_CHARS})."
        )

    json_str = extract_ceo_plan_json(cleaned)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise CEOPlanExtractionError(f"Extracted payload is not valid JSON: {exc}")

    return CEODecisionResult.from_dict(data)


def evaluate_objective_heuristically(
    objective: CompanyObjective,
    project_knowledge: Optional[Any] = None,
    investigation_findings: Optional[List[str]] = None,
    founder_clarifications: Optional[List[Dict[str, Any]]] = None,
    investigation_count: int = 0,
    max_investigations: int = 2,
    repo_root: Optional[Path] = None,
) -> CEODecisionResult:
    """Deterministic heuristic evaluator for testing and fallback evaluation."""
    # 1. If Founder already clarified, check if resolution is reached
    if founder_clarifications and len(founder_clarifications) > 0:
        latest = founder_clarifications[-1].get("response", "").strip()
        if latest:
            return CEODecisionResult(
                decision=CEODecisionType.EXECUTE.value,
                reasoning_summary=f"Founder clarification received: '{latest}'. Ambiguity is resolved.",
                known_facts=[f"Founder clarified: {latest}"],
                assumptions=[],
                missing_critical_information=[],
                proposed_next_action="Formulate DAG orchestration plan and proceed to specialist execution.",
                clarification_question=None,
                investigation_targets=[],
            )

    # 2. Check for fundamental business policy / external vendor choices
    full_text = f"{objective.title} {objective.description}".lower()
    policy_keywords = [
        "pricing", "subscription", "charge", "billing", "choose vendor", "select provider",
        "which provider", "external auth provider", "delete all inactive", "delete all users",
        "business policy", "policy choice", "decide whether", "tier"
    ]
    if any(pk in full_text for pk in policy_keywords):
        return CEODecisionResult(
            decision=CEODecisionType.ASK_FOUNDER.value,
            reasoning_summary="Objective entails a critical business policy or external vendor decision requiring Founder authority.",
            known_facts=[f"Objective: {objective.title}"],
            assumptions=[],
            missing_critical_information=["Founder policy decision / provider preference"],
            proposed_next_action="Awaiting Founder business policy decision.",
            clarification_question=f"Please specify the preferred business policy or provider choice for '{objective.title}'.",
            investigation_targets=[],
        )

    # 3. Check for clear acceptance criteria
    if objective.acceptance_criteria and any(str(a).strip() for a in objective.acceptance_criteria):
        return CEODecisionResult(
            decision=CEODecisionType.EXECUTE.value,
            reasoning_summary="Objective is clear with explicit acceptance criteria and unambiguous execution scope.",
            known_facts=[f"Criteria: {c}" for c in objective.acceptance_criteria],
            assumptions=[],
            missing_critical_information=[],
            proposed_next_action="Proceed to DAG plan formulation.",
            clarification_question=None,
            investigation_targets=[],
        )

    # 4. If investigation budget is exhausted -> MUST ASK_FOUNDER
    if investigation_count >= max_investigations:
        return CEODecisionResult(
            decision=CEODecisionType.ASK_FOUNDER.value,
            reasoning_summary=f"Autonomous investigation budget exhausted ({investigation_count}/{max_investigations}). Code inspection could not establish specific expected behavior without Founder clarification.",
            known_facts=list(investigation_findings or []),
            assumptions=[],
            missing_critical_information=["Acceptance criteria", "Expected behavior"],
            proposed_next_action="Awaiting Founder response to resume company run.",
            clarification_question=f"Could you specify the expected behavior or acceptance criteria for '{objective.title}'?",
            investigation_targets=[],
        )

    # 5. Handle underspecified objectives (investigation budget remains)
    is_georgian = bool(re.search(r"[\u10A0-\u10FF]", f"{objective.title} {objective.description}"))
    targets: List[str] = []
    if "auth" in full_text:
        auth_file = "backend/app/routers/auth.py"
        if repo_root and (repo_root / auth_file).exists():
            targets.append(auth_file)
        else:
            targets.append("auth")
    if "რეგისტრაცია" in full_text or "registration" in full_text or "register" in full_text:
        targets.append("registration")

    for token in full_text.split():
        cleaned_token = token.strip("(),;:'\"")
        if "/" in cleaned_token or cleaned_token.endswith(".py") or cleaned_token.endswith(".ts") or cleaned_token.endswith(".tsx"):
            if cleaned_token not in targets:
                targets.insert(0, cleaned_token)

    for fallback in ["backend/app", "docs", "tests"]:
        if fallback not in targets:
            targets.append(fallback)

    if is_georgian:
        reasoning = (
            f"Georgian objective '{objective.title}' (ქართულენოვანი) is underspecified with empty acceptance criteria. "
            f"Autonomous read-only inspection of repository structure, routes, and docs will clarify scope."
        )
    else:
        reasoning = (
            f"Objective '{objective.title}' has empty acceptance criteria. "
            f"Autonomous read-only inspection of repository code and tests will investigate implementation context."
        )

    return CEODecisionResult(
        decision=CEODecisionType.INVESTIGATE.value,
        reasoning_summary=reasoning,
        known_facts=[f"Objective title: {objective.title}", f"Language: {'Georgian' if is_georgian else 'English'}"],
        assumptions=[],
        missing_critical_information=["Acceptance criteria", "Target files", "Expected behavior"],
        proposed_next_action="Conduct read-only inspection of repository structure and docs.",
        clarification_question=None,
        investigation_targets=targets,
    )


# -----------------------------------------------------------------------------
# STEP 23B.3: CEO Adaptive Team Selection & Execution Efficiency Contract
# -----------------------------------------------------------------------------


class TaskCategory(str, Enum):
    """Classification of tasks for adaptive workforce allocation."""
    BUG_FIX = "BUG_FIX"
    SMALL_FEATURE = "SMALL_FEATURE"
    LARGE_FEATURE = "LARGE_FEATURE"
    UI_UX_CHANGE = "UI_UX_CHANGE"
    RESEARCH = "RESEARCH"
    PRODUCT_SPECIFICATION = "PRODUCT_SPECIFICATION"
    MARKETING = "MARKETING"
    SECURITY_SENSITIVE = "SECURITY_SENSITIVE"
    MIXED_UNKNOWN = "MIXED_UNKNOWN"


class ComplexityLevel(str, Enum):
    """Qualitative complexity rating."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class UncertaintyLevel(str, Enum):
    """Qualitative uncertainty rating."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RiskLevel(str, Enum):
    """Qualitative risk rating."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class RoleRequirement:
    """Requirement specification for a single specialist role in the team."""
    role: str
    why_necessary: str
    expected_deliverable: str
    required_upstream_inputs: List[str] = field(default_factory=list)
    is_essential: bool = True

    def __post_init__(self) -> None:
        clean_role = (self.role or "").strip().lower()
        if clean_role not in RECOGNIZED_MACRO_ROLES:
            raise CEODecisionValidationError(
                f"RoleRequirement role '{clean_role}' is not a recognized macro role. "
                f"Allowed: {sorted(RECOGNIZED_MACRO_ROLES)}."
            )
        self.role = clean_role
        if not self.why_necessary or not str(self.why_necessary).strip():
            raise CEODecisionValidationError("RoleRequirement missing 'why_necessary'.")
        if not self.expected_deliverable or not str(self.expected_deliverable).strip():
            raise CEODecisionValidationError("RoleRequirement missing 'expected_deliverable'.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "why_necessary": self.why_necessary,
            "expected_deliverable": self.expected_deliverable,
            "required_upstream_inputs": list(self.required_upstream_inputs),
            "is_essential": self.is_essential,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoleRequirement":
        if not isinstance(data, dict):
            raise CEODecisionValidationError("Expected dictionary for RoleRequirement.")
        role_raw = data.get("role")
        if not role_raw or not isinstance(role_raw, str):
            raise CEODecisionValidationError("RoleRequirement missing or invalid 'role'.")
        clean_role = role_raw.strip().lower()
        why = data.get("why_necessary", "")
        deliverable = data.get("expected_deliverable", "")
        return cls(
            role=clean_role,
            why_necessary=str(why).strip(),
            expected_deliverable=str(deliverable).strip(),
            required_upstream_inputs=[str(i).strip() for i in data.get("required_upstream_inputs", []) if str(i).strip()],
            is_essential=bool(data.get("is_essential", True)),
        )


@dataclass
class TeamSelectionResult:
    """Structured team-selection result produced by CEO before DAG construction."""
    task_category: str
    complexity: str
    uncertainty: str
    risk: str
    required_capabilities: List[str]
    selected_roles: List[str]
    role_requirements: List[RoleRequirement]
    omitted_roles_rationale: Dict[str, str]
    selection_reasoning: str
    escalation_conditions: List[str]
    estimated_specialist_count: int
    actual_specialist_count: int
    avoidable_delegation_warnings: List[str] = field(default_factory=list)
    allow_direct_developer: bool = False
    enforce_strict_roles: bool = False
    evaluated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_category": self.task_category,
            "complexity": self.complexity,
            "uncertainty": self.uncertainty,
            "risk": self.risk,
            "required_capabilities": list(self.required_capabilities),
            "selected_roles": list(self.selected_roles),
            "role_requirements": [r.to_dict() for r in self.role_requirements],
            "omitted_roles_rationale": dict(self.omitted_roles_rationale),
            "selection_reasoning": self.selection_reasoning,
            "escalation_conditions": list(self.escalation_conditions),
            "estimated_specialist_count": self.estimated_specialist_count,
            "actual_specialist_count": self.actual_specialist_count,
            "avoidable_delegation_warnings": list(self.avoidable_delegation_warnings),
            "allow_direct_developer": self.allow_direct_developer,
            "enforce_strict_roles": self.enforce_strict_roles,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamSelectionResult":
        if not isinstance(data, dict):
            raise CEODecisionValidationError("Expected dictionary for TeamSelectionResult.")

        # Reject privileged top-level keys
        for key in PRIVILEGED_TOP_LEVEL_KEYS:
            if key in data:
                raise CEODecisionSecurityError(
                    f"Unauthorized privileged key '{key}' detected in TeamSelectionResult payload."
                )

        cat_raw = data.get("task_category")
        if not cat_raw or not isinstance(cat_raw, str):
            raise CEODecisionValidationError("TeamSelectionResult missing or invalid 'task_category'.")
        clean_cat = cat_raw.strip().upper()
        valid_cats = {c.value for c in TaskCategory}
        if clean_cat not in valid_cats:
            raise CEODecisionValidationError(
                f"Invalid task_category '{clean_cat}'. Must be one of: {sorted(valid_cats)}."
            )

        comp_raw = str(data.get("complexity", "MEDIUM")).strip().upper()
        unc_raw = str(data.get("uncertainty", "LOW")).strip().upper()
        risk_raw = str(data.get("risk", "LOW")).strip().upper()

        valid_levels = {"LOW", "MEDIUM", "HIGH"}
        if comp_raw not in valid_levels:
            raise CEODecisionValidationError(f"Invalid complexity '{comp_raw}'.")
        if unc_raw not in valid_levels:
            raise CEODecisionValidationError(f"Invalid uncertainty '{unc_raw}'.")
        if risk_raw not in valid_levels:
            raise CEODecisionValidationError(f"Invalid risk '{risk_raw}'.")

        roles_raw = data.get("selected_roles")
        if not isinstance(roles_raw, list) or len(roles_raw) == 0:
            raise CEODecisionValidationError("TeamSelectionResult must specify at least one role in 'selected_roles'.")

        selected_roles: List[str] = []
        for r in roles_raw:
            if not isinstance(r, str) or not r.strip():
                continue
            cr = r.strip().lower()
            if cr not in RECOGNIZED_MACRO_ROLES:
                raise CEODecisionValidationError(
                    f"Selected role '{cr}' is not a recognized macro role. Allowed: {sorted(RECOGNIZED_MACRO_ROLES)}."
                )
            if cr == "ceo":
                raise CEODecisionValidationError("CEO cannot be scheduled as a specialist in selected_roles.")
            if cr not in selected_roles:
                selected_roles.append(cr)

        req_items = data.get("role_requirements", [])
        if not isinstance(req_items, list):
            raise CEODecisionValidationError("Field 'role_requirements' must be a list.")
        parsed_reqs = [RoleRequirement.from_dict(item) for item in req_items]
        req_roles = {pr.role for pr in parsed_reqs}

        # Validate that each selected role has a requirement specification
        for sr in selected_roles:
            if sr not in req_roles:
                raise CEODecisionValidationError(f"Missing RoleRequirement for selected role '{sr}'.")

        reasoning = data.get("selection_reasoning", "")
        if not reasoning or not str(reasoning).strip():
            raise CEODecisionValidationError("TeamSelectionResult must include non-empty 'selection_reasoning'.")

        omitted_raw = data.get("omitted_roles_rationale", {})
        if not isinstance(omitted_raw, dict):
            omitted_raw = {}

        allow_direct = bool(data.get("allow_direct_developer", False))
        if clean_cat in ("BUG_FIX", "SECURITY_SENSITIVE") or (
            "developer" in selected_roles and "product" not in selected_roles and "ux" not in selected_roles
        ):
            allow_direct = True

        actual_count = len(selected_roles)
        est_count = int(data.get("estimated_specialist_count", actual_count))

        warnings = list(data.get("avoidable_delegation_warnings", []))
        if clean_cat == "BUG_FIX" and actual_count > 2:
            warnings.append("Warning: More than minimal workforce selected for bug fix.")
        if clean_cat == "RESEARCH" and "developer" in selected_roles:
            warnings.append("Warning: Developer assigned to research objective.")

        return cls(
            task_category=clean_cat,
            complexity=comp_raw,
            uncertainty=unc_raw,
            risk=risk_raw,
            required_capabilities=[str(c).strip() for c in data.get("required_capabilities", []) if str(c).strip()],
            selected_roles=selected_roles,
            role_requirements=parsed_reqs,
            omitted_roles_rationale={str(k): str(v) for k, v in omitted_raw.items()},
            selection_reasoning=str(reasoning).strip(),
            escalation_conditions=[str(ec).strip() for ec in data.get("escalation_conditions", []) if str(ec).strip()],
            estimated_specialist_count=est_count,
            actual_specialist_count=actual_count,
            avoidable_delegation_warnings=warnings,
            allow_direct_developer=allow_direct,
            enforce_strict_roles=bool(data.get("enforce_strict_roles", False)),
            evaluated_at=data.get("evaluated_at") or _utc_now_iso(),
        )


def build_ceo_team_selection_prompt(
    objective: CompanyObjective,
    project_knowledge: Optional[Any] = None,
    investigation_findings: Optional[List[str]] = None,
    founder_clarifications: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build bounded prompt instructing CEO to determine minimum sufficient team."""
    roles_str = ", ".join(f"'{r}'" for r in sorted(RECOGNIZED_MACRO_ROLES) if r != "ceo")
    categories_str = ", ".join(f"'{c.value}'" for c in TaskCategory)

    findings_block = ""
    if investigation_findings:
        findings_block = "\nINVESTIGATION EVIDENCE:\n" + "\n".join(f"- {f}" for f in investigation_findings)

    clarifications_block = ""
    if founder_clarifications:
        clarifications_block = "\nFOUNDER CLARIFICATIONS:\n" + "\n".join(
            f"- {c.get('response', '')}" for c in founder_clarifications
        )

    return f"""You are the CEO of Jester AI Company.
Assess the following objective and select the MINIMUM SUFFICIENT SPECIALIST TEAM.

OBJECTIVE:
Title: {objective.title}
Description: {objective.description}
Constraints: {json.dumps(objective.constraints)}
Criteria: {json.dumps(objective.acceptance_criteria)}{findings_block}{clarifications_block}

AVAILABLE SPECIALIST ROLES:
{roles_str}

ALLOWED TASK CATEGORIES:
{categories_str}

TEAM SELECTION PRINCIPLES:
1. MINIMUM SUFFICIENT WORKFORCE: Select only roles strictly required to fulfill the deliverable.
   - Simple backend bug: developer only (Engineering QA is handled deterministically by the platform).
   - UI styling adjustment: ux and developer only.
   - Research-only task: research only (no developer or ux).
   - Marketing objective: marketing only.
   - Large new feature: product, ux, developer as needed.
2. LATENCY & EFFICIENCY: Do NOT assign product or UX when specifications are already actionable.
3. FAIL-CLOSED SECURITY: You have zero executable authority. Do NOT emit grants or attempt to bypass QA.

Output MUST be a single valid JSON dictionary matching this exact schema:
{{
  "task_category": "<one of allowed categories>",
  "complexity": "LOW" | "MEDIUM" | "HIGH",
  "uncertainty": "LOW" | "MEDIUM" | "HIGH",
  "risk": "LOW" | "MEDIUM" | "HIGH",
  "required_capabilities": ["<capability 1>", ...],
  "selected_roles": ["<role 1>", ...],
  "role_requirements": [
    {{
      "role": "<role>",
      "why_necessary": "<justification>",
      "expected_deliverable": "<deliverable>",
      "required_upstream_inputs": [],
      "is_essential": true
    }}
  ],
  "omitted_roles_rationale": {{
    "<omitted_role>": "<why omitted>"
  }},
  "selection_reasoning": "<concise workforce explanation>",
  "escalation_conditions": ["<trigger 1>", ...],
  "estimated_specialist_count": <int>,
  "avoidable_delegation_warnings": []
}}
"""


def parse_and_validate_team_selection(raw_text_or_dict: Any) -> TeamSelectionResult:
    """Extract and validate TeamSelectionResult from raw JSON string or dictionary."""
    if isinstance(raw_text_or_dict, dict):
        return TeamSelectionResult.from_dict(raw_text_or_dict)
    if not isinstance(raw_text_or_dict, str):
        raise CEODecisionValidationError("Expected JSON string or dictionary for TeamSelectionResult.")
    json_text = extract_ceo_plan_json(raw_text_or_dict)
    try:
        data = json.loads(json_text, strict=False)
    except Exception as exc:
        raise CEOPlanExtractionError(f"Malformed JSON in team selection: {exc}") from exc
    return TeamSelectionResult.from_dict(data)


def evaluate_team_selection_heuristically(
    objective: CompanyObjective,
    investigation_findings: Optional[List[str]] = None,
    founder_clarifications: Optional[List[Dict[str, Any]]] = None,
    repo_root: Optional[Path] = None,
) -> TeamSelectionResult:
    """Deterministically classify task and formulate minimum sufficient team (STEP 23B.3).

    Handles English and Georgian objectives, repo evidence, and investigation findings.
    """
    full_text = f"{objective.title} {objective.description} " + " ".join(objective.acceptance_criteria)
    if investigation_findings:
        full_text += " " + " ".join(investigation_findings)
    if founder_clarifications:
        for fc in founder_clarifications:
            full_text += " " + str(fc.get("response", ""))

    text_lower = full_text.lower()
    is_georgian = bool(re.search(r"[\u10A0-\u10FF]", full_text))

    # 1. Security-sensitive task
    sec_terms = [
        "vulnerability", "cve", "sql injection", "xss", "csrf",
        "auth bypass", "secret leak", "privilege escalation", "permission bypass",
        "უსაფრთხოების ხარვეზი", "ავტორიზაციის გვერდის ავლა"
    ]
    if any(st in text_lower for st in sec_terms):
        selected_roles = ["developer"]
        task_category = TaskCategory.SECURITY_SENSITIVE.value
        complexity = ComplexityLevel.MEDIUM.value
        uncertainty = UncertaintyLevel.LOW.value
        risk = RiskLevel.HIGH.value
        capabilities = ["security_patching", "isolated_verification"]
        reasoning = (
            "Security-sensitive vulnerability requires focused Developer patch with "
            "mandatory application-owned Engineering QA verification and Founder Approval."
        )

    # 2. Research-only objective
    elif any(rt in text_lower for rt in [
        "research", "analyze market", "investigate alternatives", "feasibility study",
        "literature review", "competitor analysis", "survey", "იკვლიე", "კვლევა", "ბაზრის ანალიზი"
    ]) and not any(bt in text_lower for bt in ["fix", "bug", "implement", "patch", "შეასწორე", "კოდი"]):
        selected_roles = ["research"]
        task_category = TaskCategory.RESEARCH.value
        complexity = ComplexityLevel.LOW.value
        uncertainty = UncertaintyLevel.LOW.value
        risk = RiskLevel.LOW.value
        capabilities = ["market_research", "competitive_analysis", "synthesis"]
        reasoning = (
            "Pure research deliverable. Developer, UX, and Product are omitted as no "
            "code, styling, or specifications are required."
        )

    # 3. Marketing objective
    elif any(mt in text_lower for mt in [
        "marketing", "copywriting", "announcement", "launch post", "blog post",
        "social media", "campaign", "press release", "newsletter", "მარკეტინგი", "რეკლამა", "პოსტი"
    ]) and not any(bt in text_lower for bt in ["fix", "bug", "implement", "შეასწორე"]):
        selected_roles = ["marketing"]
        task_category = TaskCategory.MARKETING.value
        complexity = ComplexityLevel.LOW.value
        uncertainty = UncertaintyLevel.LOW.value
        risk = RiskLevel.LOW.value
        capabilities = ["content_creation", "messaging", "copywriting"]
        reasoning = (
            "Marketing messaging and announcement deliverable. Technical roles (Developer, QA) "
            "and UX design are omitted to optimize execution latency."
        )

    # 4. UI/UX styling adjustment
    elif any(ut in text_lower for ut in [
        "styling", "css", "color", "padding", "margin", "button style",
        "layout adjustment", "dark mode", "ui adjustment", "ui styling",
        "დიზაინი", "სტილი", "ღილაკი", "ფერი", "ინტერფეისი"
    ]) and not any(be in text_lower for be in ["backend", "500", "sql", "database", "router"]):
        selected_roles = ["ux", "developer"]
        task_category = TaskCategory.UI_UX_CHANGE.value
        complexity = ComplexityLevel.LOW.value
        uncertainty = UncertaintyLevel.LOW.value
        risk = RiskLevel.LOW.value
        capabilities = ["ui_design", "css_adjustment", "frontend_implementation"]
        reasoning = (
            "UI styling requires UX design specifications followed by Developer frontend "
            "implementation with mandatory Engineering QA. Product and Research omitted."
        )

    # 5. Simple backend bug / bug fix
    elif any(bt in text_lower for bt in [
        "fix", "bug", "crash", "500", "error", "exception", "broken", "failed",
        "repair", "defect", "patch", "შეასწორე", "ხარვეზი", "ბაგი", "გაასწორე",
        "არ მუშაობს", "შეცდომა", "ვალიდაცია"
    ]):
        selected_roles = ["developer"]
        task_category = TaskCategory.BUG_FIX.value
        complexity = ComplexityLevel.LOW.value
        uncertainty = UncertaintyLevel.LOW.value
        risk = RiskLevel.LOW.value
        capabilities = ["backend_investigation", "code_patch", "automated_testing"]
        reasoning = (
            "Focused bug fix requires only Developer implementation and mandatory application-owned "
            "Engineering QA. Product, UX, and Research omitted to minimize latency and unnecessary model calls."
        )

    # 6. Large / complex feature
    elif any(lt in text_lower for lt in [
        "complex feature", "large feature", "multi-tenant", "payment gateway",
        "integration", "oauth", "ახალი ფუნქციონალი: მრავალმომხმარებლიანი", "ახალი ფუნქციონალი"
    ]):
        selected_roles = ["product", "ux", "developer"]
        task_category = TaskCategory.LARGE_FEATURE.value
        complexity = ComplexityLevel.HIGH.value
        uncertainty = UncertaintyLevel.MEDIUM.value
        risk = RiskLevel.MEDIUM.value
        capabilities = ["product_specification", "interaction_design", "full_stack_implementation"]
        reasoning = (
            "Complex new feature requires Product requirements, UX interaction design, "
            "and Developer implementation with mandatory Engineering QA."
        )

    # 7. Small feature / default engineering
    else:
        selected_roles = ["developer"]
        task_category = TaskCategory.SMALL_FEATURE.value
        complexity = ComplexityLevel.LOW.value
        uncertainty = UncertaintyLevel.LOW.value
        risk = RiskLevel.LOW.value
        capabilities = ["code_patch", "automated_testing"]
        reasoning = (
            "Small feature requires direct Developer implementation with application-owned Engineering QA."
        )

    # Build RoleRequirements
    role_reqs: List[RoleRequirement] = []
    for r in selected_roles:
        if r == "developer":
            role_reqs.append(
                RoleRequirement(
                    role="developer",
                    why_necessary="Implement code modifications and unit tests.",
                    expected_deliverable="Verified code patch and test assertions.",
                    required_upstream_inputs=["product_spec", "ux_wireframes"] if ("product" in selected_roles or "ux" in selected_roles) else [],
                    is_essential=True,
                )
            )
        elif r == "ux":
            role_reqs.append(
                RoleRequirement(
                    role="ux",
                    why_necessary="Produce visual specifications and user interface layout.",
                    expected_deliverable="UI design specification and style definitions.",
                    required_upstream_inputs=["product_spec"] if "product" in selected_roles else [],
                    is_essential=True,
                )
            )
        elif r == "product":
            role_reqs.append(
                RoleRequirement(
                    role="product",
                    why_necessary="Specify user stories, acceptance criteria, and behavioral scope.",
                    expected_deliverable="Product requirement specification.",
                    required_upstream_inputs=[],
                    is_essential=True,
                )
            )
        elif r == "research":
            role_reqs.append(
                RoleRequirement(
                    role="research",
                    why_necessary="Investigate problem domain and summarize empirical findings.",
                    expected_deliverable="Synthesized research report.",
                    required_upstream_inputs=[],
                    is_essential=True,
                )
            )
        elif r == "marketing":
            role_reqs.append(
                RoleRequirement(
                    role="marketing",
                    why_necessary="Create target messaging and launch announcement copy.",
                    expected_deliverable="Marketing positioning and communication brief.",
                    required_upstream_inputs=[],
                    is_essential=True,
                )
            )

    # Build Omitted Roles Rationale
    omitted_rationale: Dict[str, str] = {}
    for r in ["product", "ux", "developer", "research", "marketing", "qa"]:
        if r not in selected_roles:
            if r == "product":
                omitted_rationale[r] = "Requirements are already sufficiently clear; separate product spec not required."
            elif r == "ux":
                omitted_rationale[r] = "No UI/UX design deliverables or interaction modifications required."
            elif r == "research":
                omitted_rationale[r] = "Problem context is well-understood; empirical research not required."
            elif r == "marketing":
                omitted_rationale[r] = "Internal engineering task with no external messaging deliverables."
            elif r == "developer":
                omitted_rationale[r] = "Non-code objective; code modifications not permitted or required."
            elif r == "qa":
                omitted_rationale[r] = "Application-owned Engineering QA verification runs deterministically during code pipeline execution."

    avoided_count = 5 - len(selected_roles)
    warnings: List[str] = []
    if avoided_count > 0:
        warnings.append(
            f"Minimal sufficient team selected ({len(selected_roles)} roles). "
            f"Saved {avoided_count} unnecessary specialist invocations vs fixed 5-role template."
        )

    allow_direct = (
        task_category in (TaskCategory.BUG_FIX.value, TaskCategory.SECURITY_SENSITIVE.value)
        or ("developer" in selected_roles and "product" not in selected_roles and "ux" not in selected_roles)
    )

    escalation_conditions = [
        "Uncovered missing business requirements or policy decisions",
        "Discovered unanticipated visual/UI ambiguity during implementation",
        "Technical investigation reveals structural architectural complexity beyond bug fix",
    ]

    return TeamSelectionResult(
        task_category=task_category,
        complexity=complexity,
        uncertainty=uncertainty,
        risk=risk,
        required_capabilities=capabilities,
        selected_roles=selected_roles,
        role_requirements=role_reqs,
        omitted_roles_rationale=omitted_rationale,
        selection_reasoning=reasoning,
        escalation_conditions=escalation_conditions,
        estimated_specialist_count=len(selected_roles),
        actual_specialist_count=len(selected_roles),
        avoidable_delegation_warnings=warnings,
        allow_direct_developer=allow_direct,
    )
