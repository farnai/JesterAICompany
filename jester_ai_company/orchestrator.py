"""Domain models and schemas for CEO Orchestration (STEP 17).

Defines the typed foundation for multi-specialist company workflows:
- CompanyObjective: Top-level mission defined by Human Owner
- CompanyRun: Durable coordinator tracking plan execution
- CompanyRunState: Canonical lifecycle state machine
- CEOOrchestrationPlan: Typed DAG work plan proposed by CEO
- CEOPlannedWorkItem: Individual specialist work unit
- WorkItemState: State lifecycle for individual work items
- CEOAction / CEOActionType: Closed vocabulary for semantic CEO proposals
- HumanEscalation: Structured record when Human decision is required
- EmployeeResultSummary: Compact specialist output summary for CEO context
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Orchestration Exceptions
# -----------------------------------------------------------------------------

class OrchestrationError(Exception):
    """Base exception for all orchestration-domain failures."""
    pass


class PlanValidationError(OrchestrationError):
    """Raised when a CEOOrchestrationPlan violates schema or domain constraints."""
    pass


class DAGValidationError(OrchestrationError):
    """Raised when dependency graph structure is invalid (cycles, depth, limits)."""
    pass


class TransitionPolicyError(OrchestrationError):
    """Raised when an invalid state transition or unauthorized transition is attempted."""
    pass


class UnsupportedRoleError(OrchestrationError):
    """Raised when a role is not supported for execution in the current phase."""
    pass


class EscalationRequiredError(OrchestrationError):
    """Raised when an unresolvable conflict requires human intervention."""
    pass


# -----------------------------------------------------------------------------
# States & Action Types
# -----------------------------------------------------------------------------

class CompanyRunState(str, Enum):
    """Canonical lifecycle states for CompanyRun.
    
    CRITICAL SECURITY INVARIANT:
    'READY_FOR_HUMAN_APPLY' is the explicit canonical boundary state.
    'READY_FOR_APPLY' does NOT exist.
    """
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    READY_FOR_HUMAN_APPLY = "READY_FOR_HUMAN_APPLY"
    APPLYING = "APPLYING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


VALID_COMPANY_RUN_TRANSITIONS: Dict[str, Set[str]] = {
    CompanyRunState.CREATED.value: {
        CompanyRunState.PLANNING.value,
        CompanyRunState.FAILED.value,
        CompanyRunState.BLOCKED.value,
    },
    CompanyRunState.PLANNING.value: {
        CompanyRunState.PLAN_READY.value,
        CompanyRunState.FAILED.value,
        CompanyRunState.BLOCKED.value,
    },
    CompanyRunState.PLAN_READY.value: {
        CompanyRunState.RUNNING.value,
        CompanyRunState.PLANNING.value,
        CompanyRunState.FAILED.value,
        CompanyRunState.BLOCKED.value,
    },
    CompanyRunState.RUNNING.value: {
        CompanyRunState.COMPLETED.value,
        CompanyRunState.WAITING_FOR_HUMAN.value,
        CompanyRunState.READY_FOR_HUMAN_APPLY.value,
        CompanyRunState.PLANNING.value,
        CompanyRunState.BLOCKED.value,
        CompanyRunState.FAILED.value,
    },
    CompanyRunState.WAITING_FOR_HUMAN.value: {
        CompanyRunState.RUNNING.value,
        CompanyRunState.PLANNING.value,
        CompanyRunState.BLOCKED.value,
        CompanyRunState.FAILED.value,
    },
    CompanyRunState.READY_FOR_HUMAN_APPLY.value: {
        CompanyRunState.APPLYING.value,
        CompanyRunState.BLOCKED.value,
        CompanyRunState.FAILED.value,
    },
    CompanyRunState.APPLYING.value: {
        CompanyRunState.COMPLETED.value,
        CompanyRunState.BLOCKED.value,
        CompanyRunState.FAILED.value,
    },
    CompanyRunState.COMPLETED.value: set(),
    CompanyRunState.BLOCKED.value: set(),
    CompanyRunState.FAILED.value: set(),
}


class WorkItemState(str, Enum):
    """Lifecycle state of an individual work item within an orchestration plan."""
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class CEOActionType(str, Enum):
    """Closed vocabulary of semantic proposals the CEO Agent may issue.
    
    CRITICAL SECURITY INVARIANT:
    Privileged actions (RUN_SHELL, WRITE_FILE, APPLY_PATCH, GIT_APPLY,
    CREATE_EXECUTION_GRANT, CREATE_REAL_REPO_APPLY_GRANT, APPROVE_REAL_REPO,
    SKIP_QA, OVERRIDE_QA) are strictly forbidden and omitted.
    """
    REQUEST_REPLAN = "REQUEST_REPLAN"
    REQUEST_REFINEMENT = "REQUEST_REFINEMENT"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    CLAIM_OBJECTIVE_COMPLETE = "CLAIM_OBJECTIVE_COMPLETE"
    DECLARE_BLOCKED = "DECLARE_BLOCKED"


# -----------------------------------------------------------------------------
# Domain Models
# -----------------------------------------------------------------------------

@dataclass
class CompanyObjective:
    """Top-level mission submitted by the Human Owner to the company."""
    id: str
    title: str
    description: str
    constraints: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    target_repository: Optional[str] = None
    created_at: str = field(default_factory=_utc_now_iso)
    created_by: str = "HUMAN"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize objective to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "target_repository": self.target_repository,
            "created_at": self.created_at,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanyObjective":
        """Deserialize objective from dictionary with fail-closed validation."""
        if not isinstance(data, dict):
            raise OrchestrationError("Expected dictionary for CompanyObjective.")
        for req in ("id", "title", "description"):
            val = data.get(req)
            if not val or not isinstance(val, str) or not val.strip():
                raise OrchestrationError(f"CompanyObjective missing or invalid '{req}'.")

        return cls(
            id=data["id"].strip(),
            title=data["title"].strip(),
            description=data["description"].strip(),
            constraints=[str(c) for c in data.get("constraints", [])],
            acceptance_criteria=[str(a) for a in data.get("acceptance_criteria", [])],
            target_repository=data.get("target_repository"),
            created_at=data.get("created_at") or _utc_now_iso(),
            created_by=data.get("created_by") or "HUMAN",
        )


@dataclass
class CEOPlannedWorkItem:
    """Individual unit of specialist work declared in a CEOOrchestrationPlan.
    
    Contains NO executable authority (no shell commands, no grants).
    """
    work_item_id: str
    role: str
    objective: str
    depends_on: List[str] = field(default_factory=list)
    expected_outputs: List[str] = field(default_factory=list)
    priority: int = 1
    state: str = WorkItemState.PENDING.value
    refinement_count: int = 0
    task_id: Optional[str] = None
    run_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize work item to dictionary."""
        return {
            "work_item_id": self.work_item_id,
            "role": self.role,
            "objective": self.objective,
            "depends_on": list(self.depends_on),
            "expected_outputs": list(self.expected_outputs),
            "priority": self.priority,
            "state": self.state,
            "refinement_count": self.refinement_count,
            "task_id": self.task_id,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CEOPlannedWorkItem":
        """Deserialize work item from dictionary with fail-closed validation."""
        if not isinstance(data, dict):
            raise PlanValidationError("Expected dictionary for CEOPlannedWorkItem.")
        for req in ("work_item_id", "role", "objective"):
            val = data.get(req)
            if not val or not isinstance(val, str) or not val.strip():
                raise PlanValidationError(f"CEOPlannedWorkItem missing or invalid '{req}'.")

        state_val = data.get("state", WorkItemState.PENDING.value)
        valid_states = {s.value for s in WorkItemState}
        if state_val not in valid_states:
            raise PlanValidationError(f"Invalid WorkItemState '{state_val}'.")

        return cls(
            work_item_id=data["work_item_id"].strip(),
            role=data["role"].strip().lower(),
            objective=data["objective"].strip(),
            depends_on=[str(d).strip() for d in data.get("depends_on", [])],
            expected_outputs=[str(o).strip() for o in data.get("expected_outputs", [])],
            priority=int(data.get("priority", 1)),
            state=state_val,
            refinement_count=int(data.get("refinement_count", 0)),
            task_id=data.get("task_id"),
            run_id=data.get("run_id"),
        )


@dataclass
class CEOOrchestrationPlan:
    """Typed DAG plan proposed by the CEO Agent for a CompanyObjective.
    
    Plan is DATA, not execution authority.
    """
    plan_id: str
    objective_id: str
    work_items: List[CEOPlannedWorkItem] = field(default_factory=list)
    completion_criteria: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    schema_version: str = "1.0"
    version: int = 1
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize plan to dictionary."""
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "objective_id": self.objective_id,
            "version": self.version,
            "work_items": [w.to_dict() for w in self.work_items],
            "completion_criteria": list(self.completion_criteria),
            "constraints": list(self.constraints),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CEOOrchestrationPlan":
        """Deserialize plan from dictionary with fail-closed validation."""
        if not isinstance(data, dict):
            raise PlanValidationError("Expected dictionary for CEOOrchestrationPlan.")

        schema_ver = data.get("schema_version", "1.0")
        if schema_ver != "1.0":
            raise PlanValidationError(f"Unsupported schema_version '{schema_ver}', expected '1.0'.")

        for req in ("plan_id", "objective_id"):
            val = data.get(req)
            if not val or not isinstance(val, str) or not val.strip():
                raise PlanValidationError(f"CEOOrchestrationPlan missing or invalid '{req}'.")

        raw_items = data.get("work_items")
        if not isinstance(raw_items, list):
            raise PlanValidationError("Field 'work_items' must be a list.")

        items = [CEOPlannedWorkItem.from_dict(item) for item in raw_items]

        return cls(
            schema_version=schema_ver,
            plan_id=data["plan_id"].strip(),
            objective_id=data["objective_id"].strip(),
            version=int(data.get("version", 1)),
            work_items=items,
            completion_criteria=[str(c).strip() for c in data.get("completion_criteria", [])],
            constraints=[str(con).strip() for con in data.get("constraints", [])],
            created_at=data.get("created_at") or _utc_now_iso(),
        )


@dataclass
class HumanEscalation:
    """Structured record when autonomous execution halts for a Human decision."""
    escalation_id: str
    run_id: str
    reason: str
    question: str
    options: List[str] = field(default_factory=list)
    evidence_refs: List[str] = field(default_factory=list)
    blocking_work_item_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)
    resolved_at: Optional[str] = None
    human_response: Optional[str] = None

    def resolve(self, response: str) -> None:
        """Record explicit human resolution."""
        if not response or not str(response).strip():
            raise OrchestrationError("Human response must not be empty.")
        self.human_response = str(response).strip()
        self.resolved_at = _utc_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize escalation to dictionary."""
        return {
            "escalation_id": self.escalation_id,
            "run_id": self.run_id,
            "reason": self.reason,
            "question": self.question,
            "options": list(self.options),
            "evidence_refs": list(self.evidence_refs),
            "blocking_work_item_ids": list(self.blocking_work_item_ids),
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "human_response": self.human_response,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HumanEscalation":
        """Deserialize escalation from dictionary."""
        if not isinstance(data, dict):
            raise OrchestrationError("Expected dictionary for HumanEscalation.")
        for req in ("escalation_id", "run_id", "reason", "question"):
            val = data.get(req)
            if not val or not isinstance(val, str) or not val.strip():
                raise OrchestrationError(f"HumanEscalation missing or invalid '{req}'.")

        return cls(
            escalation_id=data["escalation_id"].strip(),
            run_id=data["run_id"].strip(),
            reason=data["reason"].strip(),
            question=data["question"].strip(),
            options=[str(o) for o in data.get("options", [])],
            evidence_refs=[str(e) for e in data.get("evidence_refs", [])],
            blocking_work_item_ids=[str(b) for b in data.get("blocking_work_item_ids", [])],
            created_at=data.get("created_at") or _utc_now_iso(),
            resolved_at=data.get("resolved_at"),
            human_response=data.get("human_response"),
        )


@dataclass
class EmployeeResultSummary:
    """Compact orchestration-facing summary of a completed specialist task.
    
    Contains NO raw model transcripts or unverified dumps.
    """
    role: str
    task_id: str
    run_id: str
    status: str
    artifact_refs: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    blockers: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize result summary to dictionary."""
        return {
            "role": self.role,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "status": self.status,
            "artifact_refs": list(self.artifact_refs),
            "summary": self.summary,
            "blockers": list(self.blockers),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmployeeResultSummary":
        """Deserialize result summary from dictionary."""
        if not isinstance(data, dict):
            raise OrchestrationError("Expected dictionary for EmployeeResultSummary.")
        for req in ("role", "task_id", "run_id", "status"):
            val = data.get(req)
            if not val or not isinstance(val, str) or not val.strip():
                raise OrchestrationError(f"EmployeeResultSummary missing or invalid '{req}'.")

        return cls(
            role=data["role"].strip().lower(),
            task_id=data["task_id"].strip(),
            run_id=data["run_id"].strip(),
            status=data["status"].strip(),
            artifact_refs=list(data.get("artifact_refs", [])),
            summary=str(data.get("summary", "")).strip(),
            blockers=[str(b) for b in data.get("blockers", [])],
            created_at=data.get("created_at") or _utc_now_iso(),
        )


@dataclass
class CEOAction:
    """A semantic proposal issued by the CEO Agent during orchestration."""
    action_type: str
    reason: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        valid_actions = {a.value for a in CEOActionType}
        if self.action_type not in valid_actions:
            raise TransitionPolicyError(
                f"Unauthorized or invalid CEO action '{self.action_type}'. "
                f"Must be one of: {sorted(valid_actions)}."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize action to dictionary."""
        return {
            "action_type": self.action_type,
            "reason": self.reason,
            "parameters": dict(self.parameters),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CEOAction":
        """Deserialize action from dictionary."""
        if not isinstance(data, dict):
            raise OrchestrationError("Expected dictionary for CEOAction.")
        action_type = data.get("action_type")
        reason = data.get("reason", "")
        return cls(
            action_type=str(action_type).strip(),
            reason=str(reason).strip(),
            parameters=dict(data.get("parameters", {})),
            created_at=data.get("created_at") or _utc_now_iso(),
        )


@dataclass
class CompanyRun:
    """Top-level company execution coordinating a multi-specialist plan."""
    run_id: str
    objective: CompanyObjective
    state: str = CompanyRunState.CREATED.value
    active_plan: Optional[CEOOrchestrationPlan] = None
    plan_history: List[CEOOrchestrationPlan] = field(default_factory=list)
    work_item_states: Dict[str, str] = field(default_factory=dict)
    ceo_invocation_count: int = 0
    specialist_invocation_count: int = 0
    replan_count: int = 0
    escalation: Optional[HumanEscalation] = None
    employee_summaries: List[EmployeeResultSummary] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        valid_states = {s.value for s in CompanyRunState}
        if self.state not in valid_states:
            raise TransitionPolicyError(f"Invalid CompanyRunState '{self.state}'.")

    def transition_to(
        self,
        new_state: CompanyRunState,
        error: Optional[str] = None,
        is_code_workflow: bool = False,
    ) -> None:
        """Safely transition state machine according to explicit policy."""
        curr = self.state
        target = new_state.value if isinstance(new_state, CompanyRunState) else str(new_state)

        valid_targets = VALID_COMPANY_RUN_TRANSITIONS.get(curr, set())
        if target not in valid_targets:
            raise TransitionPolicyError(
                f"Invalid CompanyRun transition from '{curr}' to '{target}'. "
                f"Allowed transitions: {sorted(valid_targets) if valid_targets else 'None (terminal state)'}."
            )

        if target == CompanyRunState.READY_FOR_HUMAN_APPLY.value and not is_code_workflow:
            raise TransitionPolicyError(
                f"Invalid transition to '{target}': non-code company workflows cannot enter READY_FOR_HUMAN_APPLY."
            )

        self.state = target
        self.updated_at = _utc_now_iso()
        if error:
            self.error = error
        if target in (
            CompanyRunState.COMPLETED.value,
            CompanyRunState.FAILED.value,
            CompanyRunState.BLOCKED.value,
        ):
            self.completed_at = _utc_now_iso()

    def add_event(
        self,
        event_type: str,
        reason: Optional[str] = None,
        work_item_id: Optional[str] = None,
        role: Optional[str] = None,
        task_id: Optional[str] = None,
        artifact_refs: Optional[List[Dict[str, Any]]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record a bounded operational audit event."""
        event: Dict[str, Any] = {
            "timestamp": _utc_now_iso(),
            "event_type": str(event_type),
            "company_run_id": self.run_id,
            "work_item_id": work_item_id,
            "role": role,
            "task_id": task_id,
            "artifact_refs": list(artifact_refs or []),
            "reason": reason,
            "details": dict(details or {}),
        }
        self.events.append(event)
        self.updated_at = _utc_now_iso()
        return event

    def set_plan(self, plan: CEOOrchestrationPlan) -> None:
        """Register or replace active plan, preserving immutable plan history."""
        if self.active_plan is not None:
            self.plan_history.append(self.active_plan)
        self.active_plan = plan
        # Initialize work item states from plan
        for item in plan.work_items:
            if item.work_item_id not in self.work_item_states:
                self.work_item_states[item.work_item_id] = item.state
        self.updated_at = _utc_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize CompanyRun to dictionary."""
        return {
            "run_id": self.run_id,
            "objective": self.objective.to_dict(),
            "state": self.state,
            "active_plan": self.active_plan.to_dict() if self.active_plan else None,
            "plan_history": [p.to_dict() for p in self.plan_history],
            "work_item_states": dict(self.work_item_states),
            "ceo_invocation_count": self.ceo_invocation_count,
            "specialist_invocation_count": self.specialist_invocation_count,
            "replan_count": self.replan_count,
            "escalation": self.escalation.to_dict() if self.escalation else None,
            "employee_summaries": [s.to_dict() for s in self.employee_summaries],
            "events": [dict(e) for e in self.events],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanyRun":
        """Deserialize CompanyRun from dictionary with fail-closed validation."""
        if not isinstance(data, dict):
            raise OrchestrationError("Expected dictionary for CompanyRun.")

        run_id = data.get("run_id")
        if not run_id or not isinstance(run_id, str):
            raise OrchestrationError("CompanyRun missing or invalid 'run_id'.")

        raw_obj = data.get("objective")
        if not isinstance(raw_obj, dict):
            raise OrchestrationError("CompanyRun missing or invalid 'objective'.")
        objective = CompanyObjective.from_dict(raw_obj)

        state_val = data.get("state", CompanyRunState.CREATED.value)
        valid_states = {s.value for s in CompanyRunState}
        if state_val not in valid_states:
            raise TransitionPolicyError(f"Invalid CompanyRunState '{state_val}'.")

        active_plan = None
        if data.get("active_plan"):
            active_plan = CEOOrchestrationPlan.from_dict(data["active_plan"])

        plan_history = [
            CEOOrchestrationPlan.from_dict(p)
            for p in data.get("plan_history", [])
        ]

        escalation = None
        if data.get("escalation"):
            escalation = HumanEscalation.from_dict(data["escalation"])

        employee_summaries = [
            EmployeeResultSummary.from_dict(s)
            for s in data.get("employee_summaries", [])
        ]
        events = list(data.get("events", []))

        return cls(
            run_id=run_id.strip(),
            objective=objective,
            state=state_val,
            active_plan=active_plan,
            plan_history=plan_history,
            work_item_states=dict(data.get("work_item_states", {})),
            ceo_invocation_count=int(data.get("ceo_invocation_count", 0)),
            specialist_invocation_count=int(data.get("specialist_invocation_count", 0)),
            replan_count=int(data.get("replan_count", 0)),
            escalation=escalation,
            employee_summaries=employee_summaries,
            events=events,
            created_at=data.get("created_at") or _utc_now_iso(),
            updated_at=data.get("updated_at") or _utc_now_iso(),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
        )
