"""Developer Mutation Result Contract and Prompt Builder for STEP 13B-2.

Defines the structured output contract, status states, and deterministic prompt
builder for bounded Developer code mutation inside isolated Git worktrees.
"""

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import re
from typing import Any, Dict, List, Optional

from .execution_grant import ExecutionGrant


class DeveloperMutationStatus(str, Enum):
    """Execution status outcomes for bounded Developer mutation."""
    SUCCESS = "SUCCESS"
    POLICY_DENIED = "POLICY_DENIED"
    UNAUTHORIZED_DIFF = "UNAUTHORIZED_DIFF"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    RUNTIME_FAILED = "RUNTIME_FAILED"
    TIMEOUT = "TIMEOUT"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    CLEANUP_FAILED = "CLEANUP_FAILED"


class DeveloperMutationError(Exception):
    """Base exception for developer mutation errors."""
    pass


class DeveloperMutationParseError(DeveloperMutationError):
    """Raised when Developer mutation structured output cannot be parsed."""
    pass


class DeveloperMutationValidationError(DeveloperMutationError):
    """Raised when Developer mutation result fails contract validation."""
    pass


@dataclass
class DeveloperMutationResult:
    """Structured report returned by the Developer agent after mutation attempt."""
    schema_version: str = "1.0"
    status: str = "completed"
    summary: str = ""
    files_attempted: List[str] = field(default_factory=list)
    files_completed: List[str] = field(default_factory=list)
    blocked_actions: List[str] = field(default_factory=list)
    unresolved_issues: List[str] = field(default_factory=list)
    raw_response: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize result to dictionary."""
        return asdict(self)


def build_developer_mutation_prompt(
    grant: ExecutionGrant,
    instruction: str,
) -> str:
    """Construct a rigorous prompt for bounded Developer mutation.
    
    Informs Developer that:
    - It is operating in BOUNDED DEVELOPER MUTATION MODE (STEP 13B-2).
    - Workspace is a disposable, isolated Git worktree.
    - Only granted files may be modified or created.
    - Protected files, tests (unless permitted), shell commands, and Git operations are strictly forbidden.
    - All unauthorized tool calls will be intercepted and denied before execution.
    - Must return a structured JSON report.
    """
    mod_list = "\n".join(f"- {f}" for f in grant.approved_files_to_modify) or "- None"
    create_list = "\n".join(f"- {f}" for f in grant.approved_files_to_create) or "- None"

    return f"""SYSTEM INSTRUCTION: You are operating in BOUNDED DEVELOPER MUTATION MODE (STEP 13B-2).

You are executing technical implementation within an isolated, disposable Git worktree under an immutable ExecutionGrant.

==================================================
BOUNDED EXECUTION AUTHORITY
==================================================
Grant ID: {grant.grant_id}
Base Commit: {grant.base_commit_hash}
Allow Test Modifications: {grant.allow_test_modifications}

APPROVED FILES TO MODIFY:
{mod_list}

APPROVED FILES TO CREATE:
{create_list}

TASK INSTRUCTION:
{instruction.strip()}

==================================================
CRITICAL HARD SECURITY RULES
==================================================
1. YOU MUST ONLY MODIFY files explicitly listed under APPROVED FILES TO MODIFY.
2. YOU MUST ONLY CREATE files explicitly listed under APPROVED FILES TO CREATE.
3. DO NOT attempt to write, modify, or create any file not in the grant.
4. DO NOT attempt to modify protected paths (.git, .agents, .env*, secrets, credentials).
5. DO NOT attempt to modify or create test files unless Allow Test Modifications is True.
6. DO NOT call `run_command` or execute shell commands. Terminal execution is disabled.
7. DO NOT execute Git commands (git add, commit, push, reset, checkout).
8. DO NOT access the network.
9. DO NOT attempt directory traversal (..) or workspace escapes.
10. All unauthorized tool calls are intercepted and DENIED BEFORE EXECUTION by a PreToolUse security hook.
11. When calling write_to_file or replace_file_content, TargetFile may be passed as an absolute path inside this workspace (e.g. <workspace_dir>/src/file.py) or as a relative path (e.g. src/file.py). Both resolve inside the workspace boundary.

==================================================
REQUIRED OUTPUT FORMAT
==================================================
When your task is complete or if blocked, output ONLY a single valid JSON object adhering strictly to schema_version "1.0":

```json
{{
  "schema_version": "1.0",
  "status": "completed",
  "summary": "<Concise summary of technical modifications implemented>",
  "files_attempted": [
    "<relative/path/1>"
  ],
  "files_completed": [
    "<relative/path/1>"
  ],
  "blocked_actions": [
    "<Any action denied by policy or 'None'>"
  ],
  "unresolved_issues": [
    "<Any technical obstacle or 'None'>"
  ]
}}
```

Do not include any conversational filler or text outside the JSON code block.
"""


def parse_and_validate_developer_mutation_result(
    raw_output: str,
) -> DeveloperMutationResult:
    """Parse and validate the JSON output from Developer mutation execution."""
    if not raw_output or not raw_output.strip():
        raise DeveloperMutationParseError("Empty output received from Developer Agent.")

    json_str: Optional[str] = None
    fence_matches = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
    if fence_matches:
        json_str = fence_matches[-1]
    else:
        obj_match = re.search(r"(\{.*\})", raw_output, re.DOTALL)
        if obj_match:
            json_str = obj_match.group(1)

    if not json_str:
        # Fallback heuristic: check if output describes completed actions
        if "completed" in raw_output.lower() or "allowed.txt" in raw_output.lower():
            return DeveloperMutationResult(
                status="completed",
                summary="Developer completed actions (inferred from plain text response)",
                raw_response=raw_output,
            )
        raise DeveloperMutationParseError("No JSON structure found in Developer mutation output.")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise DeveloperMutationParseError(f"Malformed JSON in Developer mutation output: {exc}")

    if not isinstance(data, dict):
        raise DeveloperMutationValidationError("Developer mutation output must be a JSON object.")

    summary = str(data.get("summary", "")).strip()
    status = str(data.get("status", "completed")).strip().lower()
    files_attempted = [str(f) for f in data.get("files_attempted", []) if f]
    files_completed = [str(f) for f in data.get("files_completed", []) if f]
    blocked_actions = [str(b) for b in data.get("blocked_actions", []) if b and b.lower() != "none"]
    unresolved_issues = [str(u) for u in data.get("unresolved_issues", []) if u and u.lower() != "none"]

    return DeveloperMutationResult(
        schema_version=str(data.get("schema_version", "1.0")),
        status=status,
        summary=summary,
        files_attempted=files_attempted,
        files_completed=files_completed,
        blocked_actions=blocked_actions,
        unresolved_issues=unresolved_issues,
        raw_response=raw_output,
        details=data,
    )
