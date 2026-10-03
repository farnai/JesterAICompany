"""Token-Aware & Role-Aware Context Assembly Engine (STEP 17B-2).

Implements deterministic, bounded, auditable context assembly for CEO and specialist roles:
- Three separate artifact context levels (Reference, Summary, Full Verified Content).
- Recipient-specific context policies (CEO compact context vs. specialist role inputs).
- Developer Product + UX prerequisite enforcement and fail-closed integrity verification.
- Deterministic character/byte limits (no external tokenizer dependency).
- Full ContextEnvelope domain model and serialization round-trips.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .core import (
    ALLOWED_HANDOFF_EDGES,
    Artifact,
    ArtifactInputRef,
    ArtifactVerificationError,
)
from .dag import RECOGNIZED_MACRO_ROLES
from .materializer import (
    MAX_COMBINED_INPUT_ARTIFACT_SIZE_BYTES,
    MAX_INPUT_ARTIFACT_SIZE_BYTES,
    load_and_verify_input_artifact,
)
from .orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    EmployeeResultSummary,
    OrchestrationError,
)

CONTEXT_ENVELOPE_SCHEMA_VERSION: str = "1.0"

# Deterministic safety bounds (V1 character approximation)
MAX_CEO_CONTEXT_CHARS: int = 25_000
MAX_SPECIALIST_CONTEXT_CHARS: int = 150_000
MAX_EMPLOYEE_SUMMARY_CHARS: int = 2_000
MAX_SELECTED_ARTIFACT_CONTENT_CHARS: int = 100_000


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContextError(OrchestrationError):
    """Base exception for context assembly and policy errors."""
    pass


class ContextAssemblyError(ContextError):
    """Raised when context requirements or prerequisite inputs are not satisfied."""
    pass


class ContextSizeExceededError(ContextError):
    """Raised when constructed context exceeds deterministic size budgets."""
    pass


class ArtifactPolicyViolationError(ContextError):
    """Raised when artifact injection violates handoff boundaries or security policies."""
    pass


@dataclass
class ContextEnvelope:
    """Typed, auditable envelope holding recipient-specific execution context."""
    recipient_role: str
    objective: Dict[str, Any]
    schema_version: str = CONTEXT_ENVELOPE_SCHEMA_VERSION
    active_plan_summary: Optional[Dict[str, Any]] = None
    work_item: Optional[Dict[str, Any]] = None
    company_run_state: Optional[str] = None
    employee_result_summaries: List[Dict[str, Any]] = field(default_factory=list)
    artifact_refs: List[Dict[str, Any]] = field(default_factory=list)
    selected_artifact_contents: Dict[str, str] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    generated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize context envelope to dictionary."""
        return {
            "schema_version": self.schema_version,
            "recipient_role": self.recipient_role,
            "objective": dict(self.objective),
            "active_plan_summary": dict(self.active_plan_summary) if self.active_plan_summary else None,
            "work_item": dict(self.work_item) if self.work_item else None,
            "company_run_state": self.company_run_state,
            "employee_result_summaries": [dict(s) for s in self.employee_result_summaries],
            "artifact_refs": [dict(r) for r in self.artifact_refs],
            "selected_artifact_contents": dict(self.selected_artifact_contents),
            "constraints": list(self.constraints),
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextEnvelope":
        """Deserialize context envelope from dictionary with fail-closed validation."""
        if not isinstance(data, dict):
            raise ContextError("Expected dictionary for ContextEnvelope.")

        schema_ver = data.get("schema_version", CONTEXT_ENVELOPE_SCHEMA_VERSION)
        if schema_ver != CONTEXT_ENVELOPE_SCHEMA_VERSION:
            raise ContextError(f"Unsupported schema_version '{schema_ver}'.")

        recipient_role = data.get("recipient_role")
        if not recipient_role or not isinstance(recipient_role, str):
            raise ContextError("ContextEnvelope missing or invalid 'recipient_role'.")

        objective = data.get("objective")
        if not isinstance(objective, dict):
            raise ContextError("ContextEnvelope missing or invalid 'objective'.")

        return cls(
            schema_version=schema_ver,
            recipient_role=recipient_role.strip().lower(),
            objective=dict(objective),
            active_plan_summary=dict(data["active_plan_summary"]) if data.get("active_plan_summary") else None,
            work_item=dict(data["work_item"]) if data.get("work_item") else None,
            company_run_state=data.get("company_run_state"),
            employee_result_summaries=[dict(s) for s in data.get("employee_result_summaries", [])],
            artifact_refs=[dict(r) for r in data.get("artifact_refs", [])],
            selected_artifact_contents=dict(data.get("selected_artifact_contents", {})),
            constraints=[str(c) for c in data.get("constraints", [])],
            generated_at=data.get("generated_at") or _utc_now_iso(),
        )


def assemble_ceo_context(
    objective: CompanyObjective,
    active_plan: Optional[CEOOrchestrationPlan] = None,
    summaries: Optional[List[EmployeeResultSummary]] = None,
    constraints: Optional[List[str]] = None,
    company_run_state: Optional[str] = None,
) -> ContextEnvelope:
    """Assemble compact, bounded context for the CEO Agent.

    CEO context rules:
    - Receives CompanyObjective (title, description, constraints, criteria).
    - Receives optional active plan summary (not raw full plan).
    - Receives compact EmployeeResultSummary objects (bounded to MAX_EMPLOYEE_SUMMARY_CHARS).
    - NEVER receives raw specialist artifact content, raw transcripts, or full diffs.
    - Bound to MAX_CEO_CONTEXT_CHARS.
    """
    if not isinstance(objective, CompanyObjective):
        raise ContextAssemblyError("Expected CompanyObjective instance.")

    # 1. Bounded summaries
    bounded_summaries: List[Dict[str, Any]] = []
    if summaries:
        for s in summaries:
            s_dict = s.to_dict() if isinstance(s, EmployeeResultSummary) else dict(s)
            summary_text = str(s_dict.get("summary", ""))
            if len(summary_text) > MAX_EMPLOYEE_SUMMARY_CHARS:
                s_dict["summary"] = summary_text[:MAX_EMPLOYEE_SUMMARY_CHARS] + "... [truncated]"
            bounded_summaries.append(s_dict)

    # 2. Plan summary
    plan_summary = None
    if active_plan:
        plan_summary = {
            "plan_id": active_plan.plan_id,
            "version": active_plan.version,
            "work_items_count": len(active_plan.work_items),
            "completion_criteria": list(active_plan.completion_criteria),
            "work_item_ids": [w.work_item_id for w in active_plan.work_items],
        }

    merged_constraints = list(objective.constraints)
    if constraints:
        for c in constraints:
            if c not in merged_constraints:
                merged_constraints.append(c)

    envelope = ContextEnvelope(
        recipient_role="ceo",
        objective=objective.to_dict(),
        active_plan_summary=plan_summary,
        work_item=None,
        company_run_state=company_run_state,
        employee_result_summaries=bounded_summaries,
        artifact_refs=[],
        selected_artifact_contents={},  # CEO NEVER receives raw full artifacts
        constraints=merged_constraints,
    )

    serialized = json.dumps(envelope.to_dict())
    if len(serialized) > MAX_CEO_CONTEXT_CHARS:
        raise ContextSizeExceededError(
            f"Assembled CEO context ({len(serialized)} chars) exceeds maximum allowed "
            f"limit of {MAX_CEO_CONTEXT_CHARS} chars."
        )

    return envelope


def assemble_specialist_context(
    recipient_role: str,
    objective: CompanyObjective,
    work_item: CEOPlannedWorkItem,
    base_output_dir: Path,
    available_artifacts: Optional[Dict[str, Artifact]] = None,
    artifact_input_refs: Optional[List[ArtifactInputRef]] = None,
    summaries: Optional[List[EmployeeResultSummary]] = None,
    constraints: Optional[List[str]] = None,
    company_run_state: Optional[str] = None,
) -> ContextEnvelope:
    """Assemble role-aware, verified context for a specialist employee.

    Enforces:
    1. Role recognition (must be one of RECOGNIZED_MACRO_ROLES).
    2. Developer Fan-In prerequisite validation:
       Developer MUST have verified Product artifact AND verified UX artifact.
    3. Handoff policy compliance: (producer_role, recipient_role) in ALLOWED_HANDOFF_EDGES.
    4. Deterministic artifact verification via load_and_verify_input_artifact.
    5. Maximum context size budget (MAX_SPECIALIST_CONTEXT_CHARS).
    """
    if not isinstance(objective, CompanyObjective):
        raise ContextAssemblyError("Expected CompanyObjective instance.")
    if not isinstance(work_item, CEOPlannedWorkItem):
        raise ContextAssemblyError("Expected CEOPlannedWorkItem instance.")

    norm_recipient = recipient_role.strip().lower()
    if norm_recipient not in RECOGNIZED_MACRO_ROLES or norm_recipient == "ceo":
        raise ContextAssemblyError(f"Invalid specialist recipient role '{recipient_role}'.")

    artifacts = available_artifacts or {}
    input_refs = artifact_input_refs or []
    input_refs_by_id = {ref.artifact_id: ref for ref in input_refs}

    # Bounded summaries
    bounded_summaries: List[Dict[str, Any]] = []
    if summaries:
        for s in summaries:
            s_dict = s.to_dict() if isinstance(s, EmployeeResultSummary) else dict(s)
            summary_text = str(s_dict.get("summary", ""))
            if len(summary_text) > MAX_EMPLOYEE_SUMMARY_CHARS:
                s_dict["summary"] = summary_text[:MAX_EMPLOYEE_SUMMARY_CHARS] + "... [truncated]"
            bounded_summaries.append(s_dict)

    # -------------------------------------------------------------------------
    # Role-Specific Artifact Selection & Verification
    # -------------------------------------------------------------------------
    selected_contents: Dict[str, str] = {}
    artifact_refs: List[Dict[str, Any]] = []

    # Map available artifacts by producer role
    artifacts_by_producer: Dict[str, List[Tuple[Artifact, ArtifactInputRef]]] = {}
    for art_id, art in artifacts.items():
        if art_id in input_refs_by_id:
            ref = input_refs_by_id[art_id]
            prod_role = art.producer_role.strip().lower()
            artifacts_by_producer.setdefault(prod_role, []).append((art, ref))

    # CRITICAL: Developer Fan-In Invariant
    if norm_recipient == "developer":
        has_product = "product" in artifacts_by_producer and len(artifacts_by_producer["product"]) > 0
        has_ux = "ux" in artifacts_by_producer and len(artifacts_by_producer["ux"]) > 0
        if not (has_product and has_ux):
            raise ContextAssemblyError(
                f"Developer context requires both verified Product and UX artifacts. "
                f"Available producer roles: {sorted(artifacts_by_producer.keys())}."
            )

    # Determine which artifacts may be verified and loaded into full content
    for prod_role, pair_list in artifacts_by_producer.items():
        # Check handoff policy
        if (prod_role, norm_recipient) not in ALLOWED_HANDOFF_EDGES:
            # Policy does not permit this edge: do NOT inject full content
            # May record reference only if relevant
            continue

        # Role-specific content policies:
        # Marketing does not receive CODE_PATCH
        for art, ref in pair_list:
            art_type_str = str(art.artifact_type)
            if norm_recipient == "marketing" and "patch" in art_type_str.lower():
                continue

            # Verify and load artifact content
            try:
                content = load_and_verify_input_artifact(
                    base_output_dir=base_output_dir,
                    artifact=art,
                    expected_ref=ref,
                    max_bytes=MAX_SELECTED_ARTIFACT_CONTENT_CHARS,
                )
            except ArtifactVerificationError as exc:
                raise ContextAssemblyError(
                    f"Artifact verification failed for '{art.id}': {exc}"
                ) from exc

            selected_contents[art.id] = content
            artifact_refs.append({
                "artifact_id": art.id,
                "name": art.name,
                "type": art_type_str,
                "producer_role": art.producer_role,
                "sha256": art.sha256,
                "path": art.path,
            })

    merged_constraints = list(objective.constraints)
    if constraints:
        for c in constraints:
            if c not in merged_constraints:
                merged_constraints.append(c)

    envelope = ContextEnvelope(
        recipient_role=norm_recipient,
        objective=objective.to_dict(),
        active_plan_summary=None,
        work_item=work_item.to_dict(),
        company_run_state=company_run_state,
        employee_result_summaries=bounded_summaries,
        artifact_refs=artifact_refs,
        selected_artifact_contents=selected_contents,
        constraints=merged_constraints,
    )

    serialized = json.dumps(envelope.to_dict())
    if len(serialized) > MAX_SPECIALIST_CONTEXT_CHARS:
        raise ContextSizeExceededError(
            f"Assembled specialist context ({len(serialized)} chars) exceeds maximum allowed "
            f"limit of {MAX_SPECIALIST_CONTEXT_CHARS} chars."
        )

    return envelope
