"""Product Execution Result Contract (STEP 6B).

Defines the typed domain model, parser, and deterministic validation for
Product Agent execution results.
"""

from dataclasses import asdict, dataclass, field
import json
import re
from typing import Any, Dict, List, Optional, Set

from .core import Task

PRODUCT_SCHEMA_VERSION: str = "1.0"
ALLOWED_PRODUCT_STATUSES: Set[str] = {"completed", "failed"}


class ProductResultError(Exception):
    """Base exception for Product execution result errors."""
    pass


class ProductResultParseError(ProductResultError):
    """Raised when JSON cannot be extracted or parsed from Product output."""
    pass


class ProductResultValidationError(ProductResultError):
    """Raised when Product output violates schema or validation rules."""
    pass


@dataclass
class ProductDeliverable:
    """Represents a discrete deliverable produced by Product Agent."""
    name: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "content": self.content}


@dataclass
class ProductTaskResult:
    """Typed domain representation of a validated Product Agent result."""
    schema_version: str
    status: str  # "completed" | "failed"
    summary: str
    deliverables: List[ProductDeliverable] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "summary": self.summary,
            "deliverables": [d.to_dict() for d in self.deliverables],
            "risks": list(self.risks),
            "open_questions": list(self.open_questions),
        }


def extract_product_json_text(raw_text: str) -> str:
    """Extract raw JSON text from model output, handling fences and whitespace."""
    if not raw_text or not isinstance(raw_text, str):
        raise ProductResultParseError("Product output is empty or not a string.")

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


def parse_and_validate_product_result(raw_text: str) -> ProductTaskResult:
    """Extract, parse, and validate JSON against ProductTaskResult contract."""
    json_text = extract_product_json_text(raw_text)
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ProductResultParseError(f"Malformed JSON in Product response: {exc}") from exc

    if not isinstance(data, dict):
        raise ProductResultValidationError("Product payload must be a JSON object.")

    # 1. Validate schema_version
    schema_ver = data.get("schema_version")
    if schema_ver != PRODUCT_SCHEMA_VERSION:
        raise ProductResultValidationError(
            f"Invalid schema_version '{schema_ver}'. Expected '{PRODUCT_SCHEMA_VERSION}'."
        )

    # 2. Validate status
    status = data.get("status")
    if status not in ALLOWED_PRODUCT_STATUSES:
        raise ProductResultValidationError(
            f"Invalid status '{status}'. Allowed statuses: {sorted(ALLOWED_PRODUCT_STATUSES)}."
        )

    # 3. Validate summary
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ProductResultValidationError("Field 'summary' must be a non-empty string.")

    # 4. Validate deliverables
    deliverables_raw = data.get("deliverables")
    if not isinstance(deliverables_raw, list):
        raise ProductResultValidationError("Field 'deliverables' must be a list.")

    deliverables: List[ProductDeliverable] = []
    for idx, d in enumerate(deliverables_raw):
        if not isinstance(d, dict):
            raise ProductResultValidationError(f"Deliverable at index {idx} must be an object.")
        name = d.get("name")
        content = d.get("content")
        if not isinstance(name, str) or not name.strip():
            raise ProductResultValidationError(f"Deliverable at index {idx} must have a non-empty 'name' string.")
        if not isinstance(content, str) or not content.strip():
            raise ProductResultValidationError(f"Deliverable at index {idx} must have a non-empty 'content' string.")
        deliverables.append(ProductDeliverable(name=name.strip(), content=content.strip()))

    # 5. Validate risks
    risks_raw = data.get("risks", [])
    if not isinstance(risks_raw, list):
        raise ProductResultValidationError("Field 'risks' must be a list.")
    for idx, r in enumerate(risks_raw):
        if not isinstance(r, str):
            raise ProductResultValidationError(f"Risk at index {idx} must be a string.")

    # 6. Validate open_questions
    oq_raw = data.get("open_questions", [])
    if not isinstance(oq_raw, list):
        raise ProductResultValidationError("Field 'open_questions' must be a list.")
    for idx, oq in enumerate(oq_raw):
        if not isinstance(oq, str):
            raise ProductResultValidationError(f"Open question at index {idx} must be a string.")

    return ProductTaskResult(
        schema_version=PRODUCT_SCHEMA_VERSION,
        status=status,
        summary=summary.strip(),
        deliverables=deliverables,
        risks=[r.strip() for r in risks_raw],
        open_questions=[oq.strip() for oq in oq_raw],
    )


def build_product_execution_prompt(task: Task) -> str:
    """Build the prompt instructing Product Agent to execute a registered Task."""
    constraints_block = (
        "\n".join(f"- {c}" for c in task.constraints)
        if task.constraints
        else "- None specified"
    )
    expected_output_block = (
        "\n".join(f"- {eo}" for eo in task.expected_output)
        if task.expected_output
        else "- None specified"
    )

    return (
        "SYSTEM INSTRUCTION: You are operating in STRUCTURED PRODUCT EXECUTION MODE.\n"
        "Execute the assigned product task and return a single valid JSON object adhering strictly to schema_version '1.0'.\n\n"
        "ROLE BOUNDARIES & RESTRICTIONS:\n"
        "- You are the Product Agent. Perform ONLY product strategy, scoping, and requirements work.\n"
        "- Do NOT perform user research or pretend user studies were conducted (defer to Research).\n"
        "- Do NOT create wireframes or interface designs (defer to UX).\n"
        "- Do NOT write code, migrations, or implementation details (defer to Developer).\n"
        "- Do NOT build test harnesses or run tests (defer to QA).\n"
        "- Do NOT invoke any other agent and do NOT modify any files.\n\n"
        "REQUIRED JSON OUTPUT STRUCTURE:\n"
        "{\n"
        '  "schema_version": "1.0",\n'
        '  "status": "completed",\n'
        '  "summary": "<Executive summary of the product decisions and deliverables>",\n'
        '  "deliverables": [\n'
        '    {\n'
        '      "name": "<Deliverable Name, e.g., Onboarding PRD>",\n'
        '      "content": "<Full markdown text of the deliverable>"\n'
        '    }\n'
        '  ],\n'
        '  "risks": ["<Identified product or market risk 1>", ...],\n'
        '  "open_questions": ["<Open question for founder/stakeholders 1>", ...]\n'
        "}\n\n"
        "CRITICAL FORMAT RULES:\n"
        "- Output ONLY the raw JSON object (or fenced ```json ... ```).\n"
        "- Do NOT include any commentary, conversation, or text before or after the JSON.\n\n"
        "ASSIGNED TASK SPECIFICATION:\n"
        f"Task ID: {task.id}\n"
        f"Title: {task.title}\n"
        f"Goal: {task.goal}\n\n"
        f"Constraints:\n{constraints_block}\n\n"
        f"Expected Output:\n{expected_output_block}\n"
    )
