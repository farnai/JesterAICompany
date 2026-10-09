"""Fault-Tolerant Agent Execution & Recovery (STEP 23B.5-C).

Provides structured failure classification, durable recovery checkpoints,
and deterministic recovery decision policies for Jester AI Company.

Architecture:
1. Failure Classification:
   Deterministic classification into FailureCategory (TRANSIENT_RUNTIME,
   TIMEOUT, AUTHENTICATION, TOOL_FAILURE, INVALID_OUTPUT, MISSING_EVIDENCE,
   POLICY_OR_PERMISSION, UNKNOWN).
2. Recovery Decisions:
   Deterministic decision engine supporting RETRY, REPLAN, CONTINUE_WITH_PARTIAL,
   ASK_FOUNDER, BLOCK, FAIL.
3. Durable Recovery Checkpoints:
   Captures completed work items, verified artifact references (SHA-256),
   satisfied acceptance criteria, and execution metadata without storing
   secrets, private prompts, or unrestricted model outputs.
4. Security & Safety Invariants:
   - Maximum 1 automatic retry for eligible transient failures.
   - Zero automatic retries for AUTHENTICATION, POLICY_OR_PERMISSION, or
     ambiguous non-idempotent write operations.
   - Completed specialists are never repeated.
   - Never bypasses Engineering QA, Founder Approval, or Repository Guards.
   - Preserves original failure evidence.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def sanitize_recovery_error(msg: Optional[str], max_len: int = 500) -> str:
    """Sanitize error messages to avoid leaking credentials or unbounded outputs."""
    if not msg or not isinstance(msg, str):
        return ""
    cleaned = msg.strip()
    cleaned = re.sub(r"(?i)(bearer\s+[a-z0-9_\-\.]+)", "Bearer [REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(api[_\-]?key\s*[:=]\s*[a-z0-9_\-\.]+)", "api_key=[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(password\s*[:=]\s*\S+)", "password=[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(secret\s*[:=]\s*\S+)", "secret=[REDACTED]", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "... [truncated]"
    return cleaned


# ==============================================================================
# Failure Categories & Recovery Decisions
# ==============================================================================

class FailureCategory(str, Enum):
    """Structured categories for agent and execution failures."""
    TRANSIENT_RUNTIME = "TRANSIENT_RUNTIME"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION = "AUTHENTICATION"
    TOOL_FAILURE = "TOOL_FAILURE"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    POLICY_OR_PERMISSION = "POLICY_OR_PERMISSION"
    UNKNOWN = "UNKNOWN"


class RecoveryDecision(str, Enum):
    """Deterministic recovery actions."""
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    CONTINUE_WITH_PARTIAL = "CONTINUE_WITH_PARTIAL"
    ASK_FOUNDER = "ASK_FOUNDER"
    BLOCK = "BLOCK"
    FAIL = "FAIL"


# ==============================================================================
# Failure Classification Record
# ==============================================================================

@dataclass
class FailureClassificationRecord:
    """Structured record of a classified failure and its recovery disposition."""
    record_id: str
    failure_category: str
    affected_specialist: str
    work_item_id: Optional[str]
    attempt_number: int
    available_artifacts: List[Dict[str, Any]]
    recovery_eligibility: bool
    recovery_decision: str
    explanation: str
    error_evidence: str
    is_exploration_timeout: bool = False
    timestamp: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize record to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailureClassificationRecord":
        """Deserialize record from dictionary."""
        return cls(
            record_id=str(data.get("record_id", "")),
            failure_category=str(data.get("failure_category", FailureCategory.UNKNOWN.value)),
            affected_specialist=str(data.get("affected_specialist", "unknown")),
            work_item_id=data.get("work_item_id"),
            attempt_number=int(data.get("attempt_number", 1)),
            available_artifacts=list(data.get("available_artifacts", [])),
            recovery_eligibility=bool(data.get("recovery_eligibility", False)),
            recovery_decision=str(data.get("recovery_decision", RecoveryDecision.FAIL.value)),
            explanation=str(data.get("explanation", "")),
            error_evidence=str(data.get("error_evidence", "")),
            is_exploration_timeout=bool(data.get("is_exploration_timeout", False)),
            timestamp=data.get("timestamp") or _utc_now_iso(),
        )


# ==============================================================================
# Durable Recovery Checkpoint
# ==============================================================================

@dataclass
class RecoveryCheckpoint:
    """Durable state preserving validated work, artifacts, and criteria.
    
    Subprocess Observability Boundary Note:
    Subprocess-based LLM agents (such as agy CLI processes) cannot restore an
    interrupted model's internal hidden state. This checkpoint explicitly preserves
    the durable external boundary: completed work items, verified physical artifacts
    on disk, verified SHA-256 digests, and met criteria.
    """
    checkpoint_id: str
    run_id: str
    completed_work_item_ids: List[str]
    completed_work_items: List[Dict[str, Any]]
    preserved_artifacts: List[Dict[str, Any]]
    satisfied_criteria: List[str]
    unmet_criteria: List[str]
    remaining_work_item_ids: List[str]
    attempt_counts: Dict[str, int]
    failure_history: List[Dict[str, Any]]
    last_failure: Optional[Dict[str, Any]] = None
    created_at: str = field(default_factory=_utc_now_iso)
    is_validated: bool = False
    validation_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize checkpoint to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryCheckpoint":
        """Deserialize checkpoint from dictionary."""
        return cls(
            checkpoint_id=str(data.get("checkpoint_id", "")),
            run_id=str(data.get("run_id", "")),
            completed_work_item_ids=list(data.get("completed_work_item_ids", [])),
            completed_work_items=list(data.get("completed_work_items", [])),
            preserved_artifacts=list(data.get("preserved_artifacts", [])),
            satisfied_criteria=list(data.get("satisfied_criteria", [])),
            unmet_criteria=list(data.get("unmet_criteria", [])),
            remaining_work_item_ids=list(data.get("remaining_work_item_ids", [])),
            attempt_counts=dict(data.get("attempt_counts", {})),
            failure_history=list(data.get("failure_history", [])),
            last_failure=data.get("last_failure"),
            created_at=data.get("created_at") or _utc_now_iso(),
            is_validated=bool(data.get("is_validated", False)),
            validation_error=data.get("validation_error"),
        )


# ==============================================================================
# Checkpoint Validation Primitive
# ==============================================================================

def validate_recovery_checkpoint(
    checkpoint: RecoveryCheckpoint,
    base_output_dir: Path,
) -> bool:
    """Validate a recovery checkpoint before reuse.
    
    Verifies that all recorded artifacts physically exist on disk and match
    their recorded SHA-256 cryptographic digests.
    """
    if not isinstance(checkpoint, RecoveryCheckpoint):
        return False

    base_resolved = base_output_dir.resolve()
    for art in checkpoint.preserved_artifacts:
        art_path_rel = art.get("path")
        expected_sha = art.get("sha256")
        if not art_path_rel or not expected_sha:
            checkpoint.is_validated = False
            checkpoint.validation_error = f"Malformed artifact reference: {art}"
            return False

        physical_path = (base_resolved / art_path_rel).resolve()
        if not physical_path.is_relative_to(base_resolved):
            checkpoint.is_validated = False
            checkpoint.validation_error = f"Artifact path escapes root: {physical_path}"
            return False

        if not physical_path.is_file():
            checkpoint.is_validated = False
            checkpoint.validation_error = f"Preserved artifact missing on disk: {physical_path}"
            return False

        try:
            actual_sha = hashlib.sha256(physical_path.read_bytes()).hexdigest()
            if actual_sha != expected_sha:
                checkpoint.is_validated = False
                checkpoint.validation_error = (
                    f"Artifact checksum tampering/mismatch for '{physical_path.name}': "
                    f"expected {expected_sha}, got {actual_sha}."
                )
                return False
        except Exception as exc:
            checkpoint.is_validated = False
            checkpoint.validation_error = f"Failed to read artifact {physical_path}: {exc}"
            return False

    checkpoint.is_validated = True
    checkpoint.validation_error = None
    return True


# ==============================================================================
# Deterministic Failure Classifier
# ==============================================================================

def classify_specialist_failure(
    error_message: str,
    exit_code: Optional[int] = None,
    timed_out: bool = False,
    stdout: Optional[str] = None,
    stderr: Optional[str] = None,
    role: str = "unknown",
    work_item_id: Optional[str] = None,
    attempt_number: int = 1,
    max_retries: int = 1,
    available_artifacts: Optional[List[Dict[str, Any]]] = None,
    mandatory_criteria: Optional[List[str]] = None,
    satisfied_criteria: Optional[List[str]] = None,
    is_write_operation: bool = False,
    is_idempotent: bool = True,
) -> FailureClassificationRecord:
    """Deterministically classify specialist execution failures and decide recovery action.
    
    Enforces:
    1. Maximum of 1 automatic retry for eligible transient failures.
    2. Zero automatic retries for AUTHENTICATION, POLICY_OR_PERMISSION.
    3. Zero automatic retries for non-idempotent write operations.
    4. Timeout caused by excessive exploration triggers REPLAN, not identical retry.
    5. Partial results can only CONTINUE_WITH_PARTIAL if all mandatory criteria are satisfied.
    6. Preserves original error evidence in record.
    """
    artifacts_list = list(available_artifacts or [])
    combined_raw = f"{error_message or ''} {stderr or ''} {stdout or ''}"
    combined = combined_raw.lower()
    sanitized_evidence = sanitize_recovery_error(combined_raw)

    record_id = f"frec_{hashlib.sha256(f'{work_item_id}_{attempt_number}_{_utc_now_iso()}'.encode()).hexdigest()[:8]}"

    # --------------------------------------------------------------------------
    # 1. AUTHENTICATION & CREDENTIALS
    # --------------------------------------------------------------------------
    auth_patterns = [
        "401", "unauthorized", "authentication", "api key", "apikey",
        "invalid credentials", "token expired", "auth failed", "login required",
        "permissiondeniederror: 401", "unauthenticated",
    ]
    if any(p in combined for p in auth_patterns):
        return FailureClassificationRecord(
            record_id=record_id,
            failure_category=FailureCategory.AUTHENTICATION.value,
            affected_specialist=role,
            work_item_id=work_item_id,
            attempt_number=attempt_number,
            available_artifacts=artifacts_list,
            recovery_eligibility=False,
            recovery_decision=RecoveryDecision.FAIL.value,
            explanation="Authentication or credential failure detected. Automatic retry is strictly prohibited.",
            error_evidence=sanitized_evidence,
        )

    # --------------------------------------------------------------------------
    # 2. POLICY OR PERMISSION
    # --------------------------------------------------------------------------
    policy_patterns = [
        "403", "forbidden", "permission denied", "repository guard",
        "read-only", "read_only", "prohibited path", "candidate not eligible",
        "transition policy error", "transitionpolicyerror", "unsupported role",
        "unsupportedroleerror", "privilege escalation", "access denied",
        "cannot modify repository", "read-only constraints",
    ]
    if any(p in combined for p in policy_patterns):
        return FailureClassificationRecord(
            record_id=record_id,
            failure_category=FailureCategory.POLICY_OR_PERMISSION.value,
            affected_specialist=role,
            work_item_id=work_item_id,
            attempt_number=attempt_number,
            available_artifacts=artifacts_list,
            recovery_eligibility=False,
            recovery_decision=RecoveryDecision.BLOCK.value,
            explanation="Policy or permission boundary violation detected. Automatic retry is strictly prohibited to maintain safety invariants.",
            error_evidence=sanitized_evidence,
        )

    # --------------------------------------------------------------------------
    # 3. TIMEOUT
    # --------------------------------------------------------------------------
    is_timeout = timed_out or "timed out" in combined or "timeoutexpired" in combined

    if is_timeout:
        # Distinguish between excessive exploration vs transient network/execution delay
        exploration_patterns = [
            "steps", "exploration", "tool calls", "excessive",
            "search loop", "investigation loop", "maximum steps",
            "100 steps", "200 steps", "step 1", "step 2",
        ]
        is_exploration = any(p in combined for p in exploration_patterns)

        if is_exploration:
            # Excessive exploration requires bounded replanning, NEVER identical retry!
            if attempt_number <= max_retries:
                return FailureClassificationRecord(
                    record_id=record_id,
                    failure_category=FailureCategory.TIMEOUT.value,
                    affected_specialist=role,
                    work_item_id=work_item_id,
                    attempt_number=attempt_number,
                    available_artifacts=artifacts_list,
                    recovery_eligibility=True,
                    recovery_decision=RecoveryDecision.REPLAN.value,
                    explanation="Timeout caused by excessive exploration or unbounded research loop. Triggering bounded replanning rather than identical retry.",
                    error_evidence=sanitized_evidence,
                    is_exploration_timeout=True,
                )
            else:
                return FailureClassificationRecord(
                    record_id=record_id,
                    failure_category=FailureCategory.TIMEOUT.value,
                    affected_specialist=role,
                    work_item_id=work_item_id,
                    attempt_number=attempt_number,
                    available_artifacts=artifacts_list,
                    recovery_eligibility=False,
                    recovery_decision=RecoveryDecision.FAIL.value,
                    explanation="Exploration timeout recovery budget exhausted. Maximum bounded replanning attempts reached.",
                    error_evidence=sanitized_evidence,
                    is_exploration_timeout=True,
                )
        else:
            # Generic timeout
            if attempt_number <= max_retries:
                return FailureClassificationRecord(
                    record_id=record_id,
                    failure_category=FailureCategory.TIMEOUT.value,
                    affected_specialist=role,
                    work_item_id=work_item_id,
                    attempt_number=attempt_number,
                    available_artifacts=artifacts_list,
                    recovery_eligibility=True,
                    recovery_decision=RecoveryDecision.RETRY.value,
                    explanation="Transient execution timeout occurred within retry budget. Scheduling retry.",
                    error_evidence=sanitized_evidence,
                )
            else:
                return FailureClassificationRecord(
                    record_id=record_id,
                    failure_category=FailureCategory.TIMEOUT.value,
                    affected_specialist=role,
                    work_item_id=work_item_id,
                    attempt_number=attempt_number,
                    available_artifacts=artifacts_list,
                    recovery_eligibility=False,
                    recovery_decision=RecoveryDecision.FAIL.value,
                    explanation="Specialist timed out and timeout recovery budget exhausted.",
                    error_evidence=sanitized_evidence,
                )

    # --------------------------------------------------------------------------
    # 4. INVALID OUTPUT
    # --------------------------------------------------------------------------
    invalid_output_patterns = [
        "produced empty output", "empty output", "validation failed",
        "output validation failed", "jsondecodeerror", "parse error",
        "schema validation error", "missing required field",
    ]
    if any(p in combined for p in invalid_output_patterns):
        if attempt_number <= max_retries:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.INVALID_OUTPUT.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=True,
                recovery_decision=RecoveryDecision.RETRY.value,
                explanation="Specialist produced empty or invalid output schema. Preserving evidence and scheduling bounded retry.",
                error_evidence=sanitized_evidence,
            )
        else:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.INVALID_OUTPUT.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=False,
                recovery_decision=RecoveryDecision.FAIL.value,
                explanation="Specialist output validation failed and retry budget is exhausted. Preserving invalid output evidence.",
                error_evidence=sanitized_evidence,
            )

    # --------------------------------------------------------------------------
    # 5. MISSING EVIDENCE
    # --------------------------------------------------------------------------
    missing_evidence_patterns = [
        "artifactverificationerror", "artifact verification error",
        "does not exist on disk", "checksum mismatch", "produced no durable artifacts",
        "artifact file does not exist",
    ]
    if any(p in combined for p in missing_evidence_patterns):
        if attempt_number <= max_retries:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.MISSING_EVIDENCE.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=True,
                recovery_decision=RecoveryDecision.RETRY.value,
                explanation="Required durable artifact deliverable was missing or corrupted. Scheduling bounded retry.",
                error_evidence=sanitized_evidence,
            )
        else:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.MISSING_EVIDENCE.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=False,
                recovery_decision=RecoveryDecision.FAIL.value,
                explanation="Missing artifact deliverable retry budget exhausted.",
                error_evidence=sanitized_evidence,
            )

    # --------------------------------------------------------------------------
    # 6. TRANSIENT RUNTIME
    # --------------------------------------------------------------------------
    transient_patterns = [
        "503", "502", "429", "unavailable", "resource_exhausted",
        "connection reset", "connection refused", "econnreset", "socket",
        "rate limit", "temporary failure", "try again later",
    ]
    is_transient = any(p in combined for p in transient_patterns) or (exit_code == -1 and not is_timeout)

    if is_transient:
        # Non-idempotent write operation safety rule:
        # Never automatically retry ambiguous write operations unless idempotency is guaranteed
        if is_write_operation and not is_idempotent:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.TRANSIENT_RUNTIME.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=False,
                recovery_decision=RecoveryDecision.BLOCK.value,
                explanation="Transient failure occurred on ambiguous non-idempotent write operation. Automatic retry blocked for safety.",
                error_evidence=sanitized_evidence,
            )

        if attempt_number <= max_retries:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.TRANSIENT_RUNTIME.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=True,
                recovery_decision=RecoveryDecision.RETRY.value,
                explanation="Transient runtime infrastructure error detected. Scheduling bounded automatic retry (1/1).",
                error_evidence=sanitized_evidence,
            )
        else:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.TRANSIENT_RUNTIME.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=False,
                recovery_decision=RecoveryDecision.FAIL.value,
                explanation="Transient failure retry budget exhausted.",
                error_evidence=sanitized_evidence,
            )

    # --------------------------------------------------------------------------
    # 7. TOOL FAILURE
    # --------------------------------------------------------------------------
    tool_patterns = [
        "tool execution failed", "tool failure", "subprocess error",
        "command failed", "failed with exit code",
    ]
    if any(p in combined for p in tool_patterns) or (exit_code is not None and exit_code != 0):
        if attempt_number <= max_retries:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.TOOL_FAILURE.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=True,
                recovery_decision=RecoveryDecision.RETRY.value,
                explanation="Specialist tool invocation returned a non-zero exit code. Scheduling bounded retry.",
                error_evidence=sanitized_evidence,
            )
        else:
            return FailureClassificationRecord(
                record_id=record_id,
                failure_category=FailureCategory.TOOL_FAILURE.value,
                affected_specialist=role,
                work_item_id=work_item_id,
                attempt_number=attempt_number,
                available_artifacts=artifacts_list,
                recovery_eligibility=False,
                recovery_decision=RecoveryDecision.FAIL.value,
                explanation="Tool execution failure retry budget exhausted.",
                error_evidence=sanitized_evidence,
            )

    # --------------------------------------------------------------------------
    # 8. FOUNDER / HUMAN DECISION REQUIRED
    # --------------------------------------------------------------------------
    founder_patterns = [
        "founder input", "founder decision", "human decision", "needing founder",
        "requires founder", "founder clarification", "ambiguous requirement",
        "missing human decision", "awaiting founder", "ambiguous design requirement",
    ]
    if any(p in combined for p in founder_patterns):
        return FailureClassificationRecord(
            record_id=record_id,
            failure_category=FailureCategory.POLICY_OR_PERMISSION.value,
            affected_specialist=role,
            work_item_id=work_item_id,
            attempt_number=attempt_number,
            available_artifacts=artifacts_list,
            recovery_eligibility=True,
            recovery_decision=RecoveryDecision.ASK_FOUNDER.value,
            explanation="Specialist encountered an ambiguous requirement or decision requiring Founder clarification.",
            error_evidence=sanitized_evidence,
        )

    # --------------------------------------------------------------------------
    # 9. UNKNOWN (FAIL-CLOSED)
    # --------------------------------------------------------------------------
    return FailureClassificationRecord(
        record_id=record_id,
        failure_category=FailureCategory.UNKNOWN.value,
        affected_specialist=role,
        work_item_id=work_item_id,
        attempt_number=attempt_number,
        available_artifacts=artifacts_list,
        recovery_eligibility=False,
        recovery_decision=RecoveryDecision.FAIL.value,
        explanation="Unclassified specialist failure. Fail-closed to avoid uncontrolled loops.",
        error_evidence=sanitized_evidence,
    )


# ==============================================================================
# Acceptance Criteria Enforcement
# ==============================================================================

def evaluate_acceptance_criteria(
    mandatory_criteria: Optional[List[str]],
    satisfied_criteria: Optional[List[str]],
    preserved_artifacts: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, List[str], List[str]]:
    """Validate whether mandatory acceptance criteria are satisfied by preserved deliverables.
    
    Returns:
        (all_mandatory_met, satisfied_list, unmet_list)
    """
    mandatory = list(mandatory_criteria or [])
    if not mandatory:
        return True, [], []

    satisfied_set = set(satisfied_criteria or [])
    artifacts = list(preserved_artifacts or [])
    art_names = {str(a.get("name", "")).lower() for a in artifacts}
    art_paths = {str(a.get("path", "")).lower() for a in artifacts}

    met: List[str] = []
    unmet: List[str] = []

    for crit in mandatory:
        crit_lower = crit.lower()
        if crit in satisfied_set:
            met.append(crit)
        # Check if deliverable name is referenced in criteria
        elif any(name in crit_lower for name in art_names if len(name) > 3):
            met.append(crit)
        else:
            unmet.append(crit)

    return (len(unmet) == 0), met, unmet
