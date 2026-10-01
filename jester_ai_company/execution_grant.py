"""Execution Grant & Authority Domain Model (STEP 13B-1).

Defines the immutable ExecutionGrant, typed VerificationAction, and validation
machinery that provides bounded, explicit authority before any developer
execution can occur in an isolated workspace.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import fnmatch
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# Allowed verification action types in V1
ALLOWED_VERIFICATION_ACTION_TYPES: Set[str] = {"pytest"}

# Disallowed characters in verification targets (prevent command injection)
DISALLOWED_TARGET_CHARS_PATTERN: re.Pattern = re.compile(r"[|&;><$`\n\r]")


class GrantError(Exception):
    """Base exception for ExecutionGrant errors."""
    pass


class GrantValidationError(GrantError):
    """Raised when an ExecutionGrant fails schema or constraint validation."""
    pass


class MissingApprovalError(GrantError):
    """Raised when an ExecutionGrant lacks an explicit founder approval identifier."""
    pass


class PlanArtifactMismatchError(GrantError):
    """Raised when the plan artifact referenced by a grant does not match company state."""
    pass


class StaleCommitError(GrantError):
    """Raised when target repository HEAD does not match the approved base commit."""
    pass


class ProtectedPathError(GrantError):
    """Raised when an approved file path violates protected path policies."""
    pass


class TestModificationForbiddenError(GrantError):
    """Raised when a test file modification is attempted without explicit authorization."""
    __test__ = False


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VerificationAction:
    """Represents a typed, deterministic verification action (NO raw shell strings)."""
    action_type: str
    target: str

    def __post_init__(self) -> None:
        if not self.action_type or not isinstance(self.action_type, str):
            raise GrantValidationError("VerificationAction 'action_type' must be a non-empty string.")
        norm_type = self.action_type.strip().lower()
        if norm_type not in ALLOWED_VERIFICATION_ACTION_TYPES:
            raise GrantValidationError(
                f"Unsupported verification action type: '{self.action_type}'. "
                f"Allowed types in V1: {sorted(ALLOWED_VERIFICATION_ACTION_TYPES)}."
            )
        if not self.target or not isinstance(self.target, str):
            raise GrantValidationError("VerificationAction 'target' must be a non-empty string.")
        cleaned_target = self.target.strip()
        if DISALLOWED_TARGET_CHARS_PATTERN.search(cleaned_target):
            raise GrantValidationError(
                f"VerificationAction target '{cleaned_target}' contains forbidden shell metacharacters."
            )
        # Target must be relative
        target_path = Path(cleaned_target)
        if target_path.is_absolute() or ":" in cleaned_target or ".." in target_path.parts:
            raise GrantValidationError(
                f"VerificationAction target '{cleaned_target}' must be a clean relative path."
            )

    def to_argument_vector(self) -> List[str]:
        """Convert typed action deterministically to argument array (shell=False)."""
        if self.action_type.strip().lower() == "pytest":
            return ["python", "-m", "pytest", self.target.strip()]
        raise GrantValidationError(f"Unsupported verification action type: '{self.action_type}'.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target": self.target,
        }


@dataclass(frozen=True)
class ExecutionGrant:
    """Immutable capability grant providing explicit authority for isolated execution."""
    grant_id: str
    task_id: str
    plan_artifact_id: str
    plan_sha256: str
    base_commit_hash: str
    approved_files_to_modify: Tuple[str, ...] = field(default_factory=tuple)
    approved_files_to_create: Tuple[str, ...] = field(default_factory=tuple)
    verification_actions: Tuple[VerificationAction, ...] = field(default_factory=tuple)
    allow_test_modifications: bool = False
    max_files_changed: int = 3
    max_bytes_written: int = 100_000
    max_verification_actions: int = 3
    max_duration_seconds: int = 120
    network_enabled: bool = False
    founder_approval_id: str = ""
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        validate_execution_grant(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "task_id": self.task_id,
            "plan_artifact_id": self.plan_artifact_id,
            "plan_sha256": self.plan_sha256,
            "base_commit_hash": self.base_commit_hash,
            "approved_files_to_modify": list(self.approved_files_to_modify),
            "approved_files_to_create": list(self.approved_files_to_create),
            "verification_actions": [va.to_dict() for va in self.verification_actions],
            "allow_test_modifications": self.allow_test_modifications,
            "max_files_changed": self.max_files_changed,
            "max_bytes_written": self.max_bytes_written,
            "max_verification_actions": self.max_verification_actions,
            "max_duration_seconds": self.max_duration_seconds,
            "network_enabled": self.network_enabled,
            "founder_approval_id": self.founder_approval_id,
            "created_at": self.created_at,
        }


def _is_hex(s: str) -> bool:
    """Check whether a string contains only valid hexadecimal characters."""
    try:
        int(s, 16)
        return True
    except ValueError:
        return False


def validate_execution_grant(grant: ExecutionGrant) -> None:
    """Validate all structural and security invariants of an ExecutionGrant."""
    if not grant.grant_id or not isinstance(grant.grant_id, str):
        raise GrantValidationError("ExecutionGrant 'grant_id' must be a non-empty string.")

    if not grant.task_id or not isinstance(grant.task_id, str):
        raise GrantValidationError("ExecutionGrant 'task_id' must be a non-empty string.")

    if not grant.plan_artifact_id or not isinstance(grant.plan_artifact_id, str):
        raise GrantValidationError("ExecutionGrant 'plan_artifact_id' must be a non-empty string.")

    if not grant.plan_sha256 or len(grant.plan_sha256) != 64 or not _is_hex(grant.plan_sha256):
        raise GrantValidationError(
            f"ExecutionGrant 'plan_sha256' must be a valid 64-character hex string. Got: '{grant.plan_sha256}'."
        )

    if not grant.base_commit_hash or len(grant.base_commit_hash) < 7 or len(grant.base_commit_hash) > 40 or not _is_hex(grant.base_commit_hash):
        raise GrantValidationError(
            f"ExecutionGrant 'base_commit_hash' must be a valid git commit hex hash. Got: '{grant.base_commit_hash}'."
        )

    # Founder approval enforcement (Requirement 4)
    if not grant.founder_approval_id or not grant.founder_approval_id.strip():
        raise MissingApprovalError(
            f"ExecutionGrant '{grant.grant_id}' lacks explicit founder_approval_id."
        )

    # Network enforcement (Requirement 2 & 15)
    if grant.network_enabled:
        raise GrantValidationError("Network access is strictly forbidden in V1 ExecutionGrant.")

    # Budgets
    if grant.max_files_changed <= 0:
        raise GrantValidationError("max_files_changed must be greater than 0.")
    if grant.max_bytes_written <= 0:
        raise GrantValidationError("max_bytes_written must be greater than 0.")
    if grant.max_duration_seconds <= 0:
        raise GrantValidationError("max_duration_seconds must be greater than 0.")

    # Paths validation
    total_approved = len(grant.approved_files_to_modify) + len(grant.approved_files_to_create)
    if total_approved > grant.max_files_changed:
        raise GrantValidationError(
            f"Total approved files ({total_approved}) exceeds max_files_changed ({grant.max_files_changed})."
        )

    # Overlap check
    modify_set = set(grant.approved_files_to_modify)
    create_set = set(grant.approved_files_to_create)
    overlap = modify_set.intersection(create_set)
    if overlap:
        raise GrantValidationError(
            f"Paths cannot be in both approved_files_to_modify and approved_files_to_create: {sorted(overlap)}."
        )

    # Verification actions limit
    if len(grant.verification_actions) > grant.max_verification_actions:
        raise GrantValidationError(
            f"Number of verification actions ({len(grant.verification_actions)}) "
            f"exceeds max_verification_actions ({grant.max_verification_actions})."
        )
