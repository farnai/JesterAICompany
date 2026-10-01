"""CEO Structured Task Proposal Contract (STEP 4).

Defines the typed domain model, schema validation, and parser for translating
natural-language founder requests into validated, machine-readable CEOActionProposal
objects without persistence or task execution side effects.
"""

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Dict, List, Optional, Set

from .registry import RECOGNIZED_AGENTS

SCHEMA_VERSION: str = "1.0"
ALLOWED_ACTIONS: Set[str] = {"propose_task", "respond"}

# Registered specialist roles eligible for assignment (CEO cannot assign to CEO)
REGISTERED_SPECIALIST_ROLES: Set[str] = {
    agent["role"].lower()
    for agent in RECOGNIZED_AGENTS
    if agent["role"].lower() != "ceo"
}


class ProposalError(Exception):
    """Base exception for CEO action proposal failures."""
    pass


class ProposalParseError(ProposalError):
    """Raised when JSON cannot be extracted or parsed from model output."""
    pass


class ProposalValidationError(ProposalError):
    """Raised when the proposal violates the schema or domain validation constraints."""
    pass


@dataclass
class CEOActionProposal:
    """Typed domain representation of a structured CEO proposal."""
    schema_version: str
    action: str  # "propose_task" | "respond"
    title: Optional[str] = None
    objective: Optional[str] = None
    assigned_agent: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    expected_output: List[str] = field(default_factory=list)
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize proposal to dictionary, matching the contract format."""
        res: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "action": self.action,
        }
        if self.action == "propose_task":
            res["title"] = self.title
            res["objective"] = self.objective
            res["assigned_agent"] = self.assigned_agent
            res["constraints"] = list(self.constraints)
            res["expected_output"] = list(self.expected_output)
        elif self.action == "respond":
            res["message"] = self.message
        return res


def extract_json_text(raw_text: str) -> str:
    """Extract raw JSON text from model output, handling fences and whitespace.

    Supports:
    - Pure raw JSON: '{"schema_version": "1.0", ...}'
    - Markdown fenced JSON: '```json\\n{...}\\n```' or '```\\n{...}\\n```'
    - Surrounding whitespace

    Does NOT attempt aggressive repair or guesswork on broken syntax.
    """
    if not raw_text or not isinstance(raw_text, str):
        raise ProposalParseError("Model output is empty or not a string.")

    cleaned = raw_text.strip()

    # 1. Match code fences (```json ... ``` or ``` ... ```)
    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fenced_match:
        extracted = fenced_match.group(1).strip()
        if extracted:
            return extracted

    # 2. Match outer { ... } if present
    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return cleaned[first_brace : last_brace + 1].strip()

    return cleaned


def parse_and_validate_proposal(raw_text: str) -> CEOActionProposal:
    """Extract, parse, and validate JSON against the CEOActionProposal contract.

    Enforces deterministic validation rules:
    - valid JSON
    - schema_version == '1.0'
    - action in {'propose_task', 'respond'}
    - required fields present
    - assigned_agent is a registered specialist (not 'ceo', not arbitrary)
    - field types (str, list of str)
    - non-empty title and objective
    """
    json_text = extract_json_text(raw_text)
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProposalParseError(f"Malformed JSON in CEO response: {exc}") from exc

    if not isinstance(data, dict):
        raise ProposalValidationError("Proposal payload must be a JSON object.")

    # 1. Validate schema_version
    schema_ver = data.get("schema_version")
    if schema_ver != SCHEMA_VERSION:
        raise ProposalValidationError(
            f"Invalid schema_version '{schema_ver}'. Expected '{SCHEMA_VERSION}'."
        )

    # 2. Validate action
    action = data.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ProposalValidationError(
            f"Invalid action '{action}'. Allowed actions: {sorted(ALLOWED_ACTIONS)}."
        )

    # 3. Validate 'propose_task' action
    if action == "propose_task":
        required_fields = ["title", "objective", "assigned_agent", "constraints", "expected_output"]
        for field_name in required_fields:
            if field_name not in data:
                raise ProposalValidationError(
                    f"Missing required field for 'propose_task': '{field_name}'."
                )

        title = data["title"]
        if not isinstance(title, str) or not title.strip():
            raise ProposalValidationError("Field 'title' must be a non-empty string.")

        objective = data["objective"]
        if not isinstance(objective, str) or not objective.strip():
            raise ProposalValidationError("Field 'objective' must be a non-empty string.")

        assigned_agent = data["assigned_agent"]
        if not isinstance(assigned_agent, str):
            raise ProposalValidationError("Field 'assigned_agent' must be a string.")

        normalized_agent = assigned_agent.strip().lower()
        if normalized_agent == "ceo":
            raise ProposalValidationError(
                "CEO cannot assign work to 'ceo'. Work must be assigned to a registered specialist."
            )
        if normalized_agent not in REGISTERED_SPECIALIST_ROLES:
            raise ProposalValidationError(
                f"Unknown or unauthorized specialist '{assigned_agent}'. "
                f"Must be one of registered specialists: {sorted(REGISTERED_SPECIALIST_ROLES)}."
            )

        constraints = data["constraints"]
        if not isinstance(constraints, list):
            raise ProposalValidationError("Field 'constraints' must be a list.")
        for idx, c in enumerate(constraints):
            if not isinstance(c, str):
                raise ProposalValidationError(f"Constraint at index {idx} must be a string.")

        expected_output = data["expected_output"]
        if not isinstance(expected_output, list):
            raise ProposalValidationError("Field 'expected_output' must be a list.")
        for idx, eo in enumerate(expected_output):
            if not isinstance(eo, str):
                raise ProposalValidationError(f"Expected output at index {idx} must be a string.")

        return CEOActionProposal(
            schema_version=SCHEMA_VERSION,
            action="propose_task",
            title=title.strip(),
            objective=objective.strip(),
            assigned_agent=normalized_agent,
            constraints=[c.strip() for c in constraints],
            expected_output=[eo.strip() for eo in expected_output],
        )

    # 4. Validate 'respond' action
    elif action == "respond":
        if "message" not in data:
            raise ProposalValidationError("Missing required field for 'respond': 'message'.")

        message = data["message"]
        if not isinstance(message, str) or not message.strip():
            raise ProposalValidationError("Field 'message' must be a non-empty string.")

        return CEOActionProposal(
            schema_version=SCHEMA_VERSION,
            action="respond",
            message=message.strip(),
        )

    raise ProposalValidationError(f"Unhandled action '{action}'.")


def build_task_proposal_prompt(founder_request: str) -> str:
    """Build the prompt instructing the CEO to output a structured proposal."""
    clean_request = (founder_request or "").strip()
    if not clean_request:
        raise ValueError("Founder request must not be empty.")

    specialists_str = ", ".join(f"'{role}'" for role in sorted(REGISTERED_SPECIALIST_ROLES))
    return (
        "SYSTEM INSTRUCTION: You are operating in STRUCTURED MACHINE PROPOSAL MODE.\n"
        "Evaluate the following founder request and return a single valid JSON object adhering strictly to schema_version '1.0'.\n\n"
        "ALLOWED ACTIONS:\n"
        "1. 'propose_task' — Use when the request describes actionable company work to be scoped and assigned to a specialist.\n"
        "   Required JSON structure:\n"
        "   {\n"
        '     "schema_version": "1.0",\n'
        '     "action": "propose_task",\n'
        '     "title": "<Concise task title>",\n'
        '     "objective": "<Clear, actionable goal statement>",\n'
        f'     "assigned_agent": "<Exactly one specialist role from: {specialists_str}>",\n'
        '     "constraints": ["<constraint 1>", ...],\n'
        '     "expected_output": ["<expected deliverable 1>", ...]\n'
        "   }\n"
        f"   CRITICAL: 'assigned_agent' MUST be chosen from: {specialists_str}. Do NOT assign to 'ceo'.\n\n"
        "2. 'respond' — Use ONLY when the request is purely informational/greeting and requires no specialist work.\n"
        "   Required JSON structure:\n"
        "   {\n"
        '     "schema_version": "1.0",\n'
        '     "action": "respond",\n'
        '     "message": "<Direct CEO explanation or greeting>"\n'
        "   }\n\n"
        "CRITICAL FORMAT RULES:\n"
        "- Return ONLY the raw JSON object (or fenced ```json ... ```).\n"
        "- Do NOT include any commentary, conversation, or text before or after the JSON.\n"
        "- Do NOT execute the task or invoke any specialists.\n\n"
        f"FOUNDER REQUEST:\n{clean_request}"
    )
