"""Three-Level Authority Model for JesterAICompany (Stage 0B + 0B-polish).

Separates authority into three strictly distinct, non-interchangeable types:
  A. SandboxExecutionToken   — bounded, automated, single-use ephemeral permission for
                               isolated worktree execution and bounded repair loops.
                               NEVER authorizes real repository mutations and NEVER
                               carries a human approval ID.
  B. FounderDecision         — human decision bound to an authenticated server session
                               with cryptographic HMAC-SHA256 `session_proof` verified
                               by `FounderSessionAuthenticator`. A well-formed actor
                               name, session ID, or SHA-256 value alone is explicitly
                               marked `UNVERIFIED_STRUCTURAL` and MUST NOT count as
                               proof of authenticated human authorization.
  C. ProtectedOperationGrant — authenticated, single-use, time-bounded, narrowly scoped
                               grant derived strictly from a session-verified
                               FounderDecision for a specific approved operation
                               (REAL_REPO_APPLY, GIT_COMMIT, GIT_PUSH, DEPLOY).

Concurrency & Replay Guarantees (`AuthorityRegistry`):
  - Thread-level mutual exclusion via per-path `threading.RLock`.
  - Process-level mutual exclusion via atomic `O_CREAT | O_EXCL` lockfile
    (`<registry>.lock`) with bounded backoff and conservative stale-lock handling.
  - Atomic check-and-consume (`consume_once`, `verify_and_consume_*`) that reloads
    fresh disk state inside the dual lock, validates all keys, and persists via
    unique temp file + `os.fsync` + `os.replace` so check and consumption cannot
    be separated by a thread or process race condition.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Dict, Iterable, Iterator, Optional, Sequence, Set, Tuple
import uuid


class AuthorityLevel(str, Enum):
    SANDBOX_EXECUTION = "SANDBOX_EXECUTION"
    FOUNDER_DECISION = "FOUNDER_DECISION"
    PROTECTED_OPERATION = "PROTECTED_OPERATION"


class FounderDecisionType(str, Enum):
    CLARIFICATION = "CLARIFICATION"
    DESIGN_APPROVAL = "DESIGN_APPROVAL"
    SCOPE_EXPANSION = "SCOPE_EXPANSION"
    CONFLICT_RESOLUTION = "CONFLICT_RESOLUTION"
    PROTECTED_OPERATION_APPROVAL = "PROTECTED_OPERATION_APPROVAL"


class ProtectedOperationType(str, Enum):
    REAL_REPO_APPLY = "REAL_REPO_APPLY"
    GIT_COMMIT = "GIT_COMMIT"
    GIT_PUSH = "GIT_PUSH"
    DEPLOY = "DEPLOY"


PROVENANCE_UNVERIFIED_STRUCTURAL = "UNVERIFIED_STRUCTURAL"
PROVENANCE_VERIFIED_SESSION_BOUND = "VERIFIED_SESSION_BOUND"

FORBIDDEN_SYNTHETIC_APPROVAL_PREFIXES: Tuple[str, ...] = (
    "founder_grant_",
    "founder_repair_",
    "founder_ui_",
    "appr_",
    "auto_",
    "synthetic_",
    "mock_founder_",
)


class AuthorityError(Exception):
    """Base exception for the 3-level authority model."""


class AuthorityTypeMismatchError(AuthorityError):
    """Raised when an authority object of the wrong level is supplied."""


class ForgedApprovalError(AuthorityError):
    """Raised when a synthetic, auto-generated, tampered, or forged approval is detected."""


class FounderAuthenticationRequiredError(AuthorityError):
    """Raised when a human decision or protected grant lacks verified server session proof."""


class AuthorityExpiredError(AuthorityError):
    """Raised when a token or grant has exceeded its validity TTL."""


class AuthorityReplayError(AuthorityError):
    """Raised when a single-use grant, sandbox token, or decision nonce is reused."""


class StaleRepositoryHeadError(AuthorityError):
    """Raised when target repository HEAD no longer matches expected_head_hash."""


class ScopeExpansionForbiddenError(AuthorityError):
    """Raised when an operation attempts to exceed the granted file set, repo, run, or operation type."""


class AuthorityLockError(AuthorityError):
    """Raised when the cross-process AuthorityRegistry lock cannot be acquired within timeout."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_iso(ts: str) -> datetime:
    cleaned = ts.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def _norm_rel(path_str: str) -> str:
    cleaned = path_str.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/").rstrip("/").lower()


def is_synthetic_approval_id(approval_id: str) -> bool:
    """Return True if an identifier matches forbidden synthetic/fabricated patterns."""
    if not isinstance(approval_id, str) or not approval_id.strip():
        return True
    lower = approval_id.strip().lower()
    return any(lower.startswith(prefix) for prefix in FORBIDDEN_SYNTHETIC_APPROVAL_PREFIXES)


def _canonical_sha256(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ==============================================================================
# Server-Side Founder Session Authenticator (Cryptographic Provenance)
# ==============================================================================

class FounderSessionAuthenticator:
    """Server-side verifier binding FounderDecisions to authenticated human sessions.

    A well-formed actor name, session ID string, or SHA-256 hash alone NEVER proves
    human authentication. Only a FounderDecision signed with HMAC-SHA256 by an active
    registered session in this authenticator carries `VERIFIED_SESSION_BOUND` provenance.
    """

    def __init__(self, secret_key: Optional[bytes] = None) -> None:
        self._secret_key: bytes = secret_key if secret_key is not None else secrets.token_bytes(32)
        if len(self._secret_key) < 32:
            raise AuthorityError("FounderSessionAuthenticator secret_key must be at least 32 bytes.")
        self._lock = threading.RLock()
        self._sessions: Dict[str, Dict[str, str]] = {}

    def issue_session(self, actor: str, *, ttl_seconds: int = 3600) -> str:
        """Issue a new authenticated human session ID bound to `actor`."""
        cleaned_actor = (actor or "").strip()
        if not cleaned_actor or cleaned_actor.lower() in ("system", "orchestrator", "auto"):
            raise FounderAuthenticationRequiredError(
                f"Cannot issue founder session for non-human actor '{actor}'."
            )
        session_id = f"fsess_{secrets.token_hex(16)}"
        self.register_session(session_id, cleaned_actor, ttl_seconds=ttl_seconds)
        return session_id

    def register_session(self, session_id: str, actor: str, *, ttl_seconds: int = 3600) -> None:
        cleaned_sid = (session_id or "").strip()
        cleaned_actor = (actor or "").strip()
        if len(cleaned_sid) < 16:
            raise FounderAuthenticationRequiredError("Authenticated session_id must be >= 16 characters.")
        if not cleaned_actor or cleaned_actor.lower() in ("system", "orchestrator", "auto"):
            raise FounderAuthenticationRequiredError(
                f"Cannot register session for non-human actor '{actor}'."
            )
        now = _utc_now()
        with self._lock:
            self._sessions[cleaned_sid] = {
                "actor": cleaned_actor,
                "issued_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=max(ttl_seconds, 1))).isoformat(),
            }

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop((session_id or "").strip(), None)

    def _compute_decision_hmac(self, decision: "FounderDecision") -> str:
        msg = "|".join(
            [
                decision.decision_id,
                decision.decision_type,
                decision.run_id,
                decision.subject_artifact_id,
                decision.subject_sha256,
                decision.actor,
                decision.auth_session_id,
                decision.nonce,
                decision.decision_sha256,
            ]
        ).encode("utf-8")
        return hmac.new(self._secret_key, msg, hashlib.sha256).hexdigest()

    def _assert_session_active(self, session_id: str, actor: str, now: Optional[datetime] = None) -> None:
        with self._lock:
            rec = self._sessions.get((session_id or "").strip())
        if not rec:
            raise FounderAuthenticationRequiredError(
                f"Session '{session_id}' is not an active server-authenticated founder session."
            )
        if rec["actor"] != (actor or "").strip():
            raise FounderAuthenticationRequiredError(
                f"Session actor mismatch: session belongs to '{rec['actor']}', not '{actor}'."
            )
        ref = now or _utc_now()
        if ref > _parse_iso(rec["expires_at"]):
            raise AuthorityExpiredError(f"Authenticated founder session '{session_id}' has expired.")

    def sign_decision(self, decision: "FounderDecision", now: Optional[datetime] = None) -> "FounderDecision":
        """Bind a FounderDecision cryptographically to an active authenticated session."""
        if not isinstance(decision, FounderDecision):
            raise AuthorityTypeMismatchError(f"Expected FounderDecision, got {type(decision).__name__}.")
        if decision.decision_sha256 != compute_founder_decision_sha256(decision):
            raise ForgedApprovalError("Cannot sign tampered FounderDecision (SHA-256 mismatch).")
        self._assert_session_active(decision.auth_session_id, decision.actor, now=now)
        proof = self._compute_decision_hmac(decision)
        return replace(
            decision,
            session_proof=proof,
            provenance_status=PROVENANCE_VERIFIED_SESSION_BOUND,
        )

    def verify_decision(self, decision: "FounderDecision", now: Optional[datetime] = None) -> None:
        """Fail-closed verification that FounderDecision carries genuine server-issued session proof."""
        if not isinstance(decision, FounderDecision):
            raise AuthorityTypeMismatchError(f"Expected FounderDecision, got {type(decision).__name__}.")
        if decision.decision_sha256 != compute_founder_decision_sha256(decision):
            raise ForgedApprovalError("FounderDecision integrity check failed (tampered content).")
        if (
            decision.provenance_status != PROVENANCE_VERIFIED_SESSION_BOUND
            or not decision.session_proof
            or len(decision.session_proof) != 64
            or not _is_hex(decision.session_proof)
        ):
            raise FounderAuthenticationRequiredError(
                "FounderDecision lacks verified cryptographic session_proof; "
                "structural actor/session_id/SHA-256 values alone do not prove human authentication."
            )
        self._assert_session_active(decision.auth_session_id, decision.actor, now=now)
        expected = self._compute_decision_hmac(decision)
        if not hmac.compare_digest(decision.session_proof, expected):
            raise ForgedApprovalError(
                f"FounderDecision '{decision.decision_id}' failed cryptographic session_proof verification."
            )

    def verify_grant_session(self, grant: "ProtectedOperationGrant", now: Optional[datetime] = None) -> None:
        """Verify that a ProtectedOperationGrant references an active authenticated session."""
        if (
            grant.provenance_status != PROVENANCE_VERIFIED_SESSION_BOUND
            or not grant.founder_session_proof
            or len(grant.founder_session_proof) != 64
            or not _is_hex(grant.founder_session_proof)
        ):
            raise FounderAuthenticationRequiredError(
                f"ProtectedOperationGrant '{grant.grant_id}' lacks verified founder session provenance."
            )
        self._assert_session_active(grant.auth_session_id, grant.approver, now=now)


# ==============================================================================
# Level A: SandboxExecutionToken (Automated, Bounded, Single-Use, Worktree Only)
# ==============================================================================

@dataclass(frozen=True)
class SandboxExecutionToken:
    """Automated, bounded permission strictly for disposable worktree mutation & repair.

    Intentionally has NO founder_approval_id or human_approval_id field and CANNOT
    authorize any real repository mutation or protected operation.
    """

    token_id: str
    run_id: str
    task_id: str
    base_commit_hash: str
    plan_artifact_id: str
    plan_sha256: str
    approved_files_to_modify: Tuple[str, ...] = field(default_factory=tuple)
    approved_files_to_create: Tuple[str, ...] = field(default_factory=tuple)
    allow_test_modifications: bool = False
    max_files_changed: int = 3
    max_bytes_written: int = 100_000
    max_duration_seconds: int = 300
    iteration: int = 0
    worktree_path: Optional[str] = None
    issuer: str = "SYSTEM_ORCHESTRATOR"
    authority_level: str = AuthorityLevel.SANDBOX_EXECUTION.value
    created_at: str = field(default_factory=_utc_now_iso)
    expires_at: str = ""

    def __post_init__(self) -> None:
        if not self.token_id or not self.token_id.startswith("sbx_"):
            raise AuthorityError(f"SandboxExecutionToken 'token_id' must start with 'sbx_', got '{self.token_id}'.")
        if self.authority_level != AuthorityLevel.SANDBOX_EXECUTION.value:
            raise AuthorityTypeMismatchError(
                f"Invalid authority_level '{self.authority_level}' for SandboxExecutionToken."
            )
        if self.issuer != "SYSTEM_ORCHESTRATOR":
            raise AuthorityError(f"SandboxExecutionToken issuer must be 'SYSTEM_ORCHESTRATOR', got '{self.issuer}'.")
        if not self.run_id or not self.task_id:
            raise AuthorityError("SandboxExecutionToken requires non-empty run_id and task_id.")
        if not self.plan_artifact_id or len(self.plan_sha256) != 64 or not _is_hex(self.plan_sha256):
            raise AuthorityError("SandboxExecutionToken requires valid plan_artifact_id and 64-hex plan_sha256.")
        if not self.base_commit_hash or not (7 <= len(self.base_commit_hash) <= 40) or not _is_hex(self.base_commit_hash):
            raise AuthorityError("SandboxExecutionToken requires valid git base_commit_hash.")
        if self.iteration < 0 or self.iteration > 5:
            raise AuthorityError(f"SandboxExecutionToken iteration out of bounds: {self.iteration}.")
        if self.max_files_changed <= 0 or self.max_bytes_written <= 0 or self.max_duration_seconds <= 0:
            raise AuthorityError("SandboxExecutionToken budgets must be positive.")
        total_files = len(self.approved_files_to_modify) + len(self.approved_files_to_create)
        if total_files > self.max_files_changed:
            raise ScopeExpansionForbiddenError(
                f"SandboxExecutionToken approved files ({total_files}) exceed max_files_changed ({self.max_files_changed})."
            )
        if not self.expires_at:
            exp = (_parse_iso(self.created_at) + timedelta(seconds=max(self.max_duration_seconds, 60))).isoformat()
            object.__setattr__(self, "expires_at", exp)

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        ref = now or _utc_now()
        return ref > _parse_iso(self.expires_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "authority_level": self.authority_level,
            "issuer": self.issuer,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "base_commit_hash": self.base_commit_hash,
            "plan_artifact_id": self.plan_artifact_id,
            "plan_sha256": self.plan_sha256,
            "approved_files_to_modify": list(self.approved_files_to_modify),
            "approved_files_to_create": list(self.approved_files_to_create),
            "allow_test_modifications": self.allow_test_modifications,
            "max_files_changed": self.max_files_changed,
            "max_bytes_written": self.max_bytes_written,
            "max_duration_seconds": self.max_duration_seconds,
            "iteration": self.iteration,
            "worktree_path": self.worktree_path,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


def issue_sandbox_execution_token(
    *,
    run_id: str,
    task_id: str,
    base_commit_hash: str,
    plan_artifact_id: str,
    plan_sha256: str,
    approved_files_to_modify: Sequence[str] = (),
    approved_files_to_create: Sequence[str] = (),
    allow_test_modifications: bool = False,
    max_files_changed: int = 3,
    max_bytes_written: int = 100_000,
    max_duration_seconds: int = 600,
    iteration: int = 0,
    worktree_path: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> SandboxExecutionToken:
    """Issue a bounded, automated SandboxExecutionToken for isolated worktree execution."""
    now = _utc_now()
    effective_ttl = ttl_seconds if ttl_seconds is not None else max(max_duration_seconds, 300)
    mod_tuple = tuple(sorted({_norm_rel(f) for f in approved_files_to_modify if f and f.strip()}))
    create_tuple = tuple(sorted({_norm_rel(f) for f in approved_files_to_create if f and f.strip()}))
    effective_max_files = max(max_files_changed, len(mod_tuple) + len(create_tuple), 1)
    return SandboxExecutionToken(
        token_id=f"sbx_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        task_id=task_id,
        base_commit_hash=base_commit_hash,
        plan_artifact_id=plan_artifact_id,
        plan_sha256=plan_sha256,
        approved_files_to_modify=mod_tuple,
        approved_files_to_create=create_tuple,
        allow_test_modifications=allow_test_modifications,
        max_files_changed=effective_max_files,
        max_bytes_written=max_bytes_written,
        max_duration_seconds=max_duration_seconds,
        iteration=iteration,
        worktree_path=worktree_path,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=effective_ttl)).isoformat(),
    )


# ==============================================================================
# Level B: FounderDecision (Authenticated Human Decision)
# ==============================================================================

@dataclass(frozen=True)
class FounderDecision:
    """Record of a human founder decision.

    NOTE ON PROVENANCE:
    Constructing a FounderDecision with well-formed `actor`, `auth_session_id`, and
    `decision_sha256` sets `provenance_status = UNVERIFIED_STRUCTURAL` and DOES NOT
    constitute authenticated human proof. Protected operations require cryptographic
    `session_proof` issued and verified by `FounderSessionAuthenticator`
    (`provenance_status == VERIFIED_SESSION_BOUND`).
    """

    decision_id: str
    decision_type: str
    run_id: str
    subject_artifact_id: str
    subject_sha256: str
    actor: str
    auth_session_id: str
    nonce: str
    decision_payload: Dict[str, Any] = field(default_factory=dict)
    authenticated_at: str = field(default_factory=_utc_now_iso)
    authority_level: str = AuthorityLevel.FOUNDER_DECISION.value
    decision_sha256: str = ""
    session_proof: str = ""
    provenance_status: str = PROVENANCE_UNVERIFIED_STRUCTURAL

    def __post_init__(self) -> None:
        if not self.decision_id or not self.decision_id.startswith("fdec_"):
            raise ForgedApprovalError(
                f"FounderDecision 'decision_id' must start with 'fdec_', got '{self.decision_id}'."
            )
        if is_synthetic_approval_id(self.decision_id):
            raise ForgedApprovalError(f"Forbidden synthetic FounderDecision id '{self.decision_id}'.")
        if self.authority_level != AuthorityLevel.FOUNDER_DECISION.value:
            raise AuthorityTypeMismatchError(
                f"Invalid authority_level '{self.authority_level}' for FounderDecision."
            )
        valid_types = {t.value for t in FounderDecisionType}
        if self.decision_type not in valid_types:
            raise AuthorityError(f"Unsupported FounderDecisionType '{self.decision_type}'.")
        if not self.actor or not self.actor.strip() or self.actor.strip().lower() in ("system", "orchestrator", "auto"):
            raise FounderAuthenticationRequiredError(
                f"FounderDecision actor must be an authenticated human identity, got '{self.actor}'."
            )
        if not self.auth_session_id or len(self.auth_session_id.strip()) < 16:
            raise FounderAuthenticationRequiredError(
                "FounderDecision requires an auth_session_id (>= 16 chars)."
            )
        if not self.nonce or len(self.nonce.strip()) < 16:
            raise FounderAuthenticationRequiredError(
                "FounderDecision requires a cryptographic anti-replay nonce (>= 16 chars)."
            )
        if not self.run_id or not self.subject_artifact_id or len(self.subject_sha256) != 64 or not _is_hex(self.subject_sha256):
            raise AuthorityError("FounderDecision requires run_id, subject_artifact_id, and 64-hex subject_sha256.")

        expected_sha = compute_founder_decision_sha256(self)
        if not self.decision_sha256:
            object.__setattr__(self, "decision_sha256", expected_sha)
        elif self.decision_sha256 != expected_sha:
            raise ForgedApprovalError("FounderDecision SHA-256 integrity verification failed (tampered decision).")

        if self.provenance_status not in (PROVENANCE_UNVERIFIED_STRUCTURAL, PROVENANCE_VERIFIED_SESSION_BOUND):
            raise ForgedApprovalError(f"Invalid provenance_status '{self.provenance_status}'.")
        if self.provenance_status == PROVENANCE_VERIFIED_SESSION_BOUND and not self.session_proof:
            raise FounderAuthenticationRequiredError(
                "FounderDecision cannot claim VERIFIED_SESSION_BOUND without a cryptographic session_proof."
            )

    @property
    def is_cryptographically_authenticated(self) -> bool:
        return (
            self.provenance_status == PROVENANCE_VERIFIED_SESSION_BOUND
            and len(self.session_proof) == 64
            and _is_hex(self.session_proof)
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "authority_level": self.authority_level,
            "decision_type": self.decision_type,
            "run_id": self.run_id,
            "subject_artifact_id": self.subject_artifact_id,
            "subject_sha256": self.subject_sha256,
            "actor": self.actor,
            "auth_session_id": self.auth_session_id,
            "nonce": self.nonce,
            "decision_payload": dict(self.decision_payload),
            "authenticated_at": self.authenticated_at,
            "decision_sha256": self.decision_sha256,
            "session_proof": self.session_proof,
            "provenance_status": self.provenance_status,
        }


def compute_founder_decision_sha256(decision: FounderDecision) -> str:
    return _canonical_sha256(
        {
            "decision_id": decision.decision_id,
            "authority_level": decision.authority_level,
            "decision_type": decision.decision_type,
            "run_id": decision.run_id,
            "subject_artifact_id": decision.subject_artifact_id,
            "subject_sha256": decision.subject_sha256,
            "actor": decision.actor,
            "auth_session_id": decision.auth_session_id,
            "nonce": decision.nonce,
            "decision_payload": decision.decision_payload,
            "authenticated_at": decision.authenticated_at,
        }
    )


def create_authenticated_founder_decision(
    *,
    decision_type: FounderDecisionType | str,
    run_id: str,
    subject_artifact_id: str,
    subject_sha256: str,
    actor: str,
    auth_session_id: str,
    decision_payload: Optional[Dict[str, Any]] = None,
    nonce: Optional[str] = None,
    authenticator: Optional[FounderSessionAuthenticator] = None,
) -> FounderDecision:
    """Create a FounderDecision.

    When `authenticator` is provided, binds the decision with HMAC-SHA256 `session_proof`
    (`VERIFIED_SESSION_BOUND`). Without `authenticator`, produces an `UNVERIFIED_STRUCTURAL`
    decision which is strictly REJECTED by protected-operation derivation.
    """
    dtype = decision_type.value if isinstance(decision_type, FounderDecisionType) else str(decision_type)
    resolved_nonce = nonce.strip() if isinstance(nonce, str) and nonce.strip() else secrets.token_hex(16)
    decision = FounderDecision(
        decision_id=f"fdec_{uuid.uuid4().hex[:12]}",
        decision_type=dtype,
        run_id=run_id,
        subject_artifact_id=subject_artifact_id,
        subject_sha256=subject_sha256,
        actor=actor.strip(),
        auth_session_id=auth_session_id.strip(),
        nonce=resolved_nonce,
        decision_payload=dict(decision_payload or {}),
        session_proof="",
        provenance_status=PROVENANCE_UNVERIFIED_STRUCTURAL,
    )
    if authenticator is not None:
        return authenticator.sign_decision(decision)
    return decision


# ==============================================================================
# Level C: ProtectedOperationGrant (Authenticated, Single-Use, High-Risk Ops)
# ==============================================================================

@dataclass(frozen=True)
class ProtectedOperationGrant:
    """Narrowly scoped, single-use, time-bounded grant for high-risk protected operations."""

    grant_id: str
    operation_type: str
    founder_decision_id: str
    founder_decision_sha256: str
    auth_session_id: str
    approver: str
    proposal_id: str
    proposal_sha256: str
    target_repository_root: str
    target_branch: str
    expected_head_hash: str
    code_patch_artifact_id: str
    code_patch_sha256: str
    qa_execution_report_artifact_id: str
    qa_execution_report_sha256: str
    expected_changed_files: Tuple[str, ...]
    created_at: str = field(default_factory=_utc_now_iso)
    expires_at: str = ""
    authority_level: str = AuthorityLevel.PROTECTED_OPERATION.value
    grant_sha256: str = ""
    founder_session_proof: str = ""
    provenance_status: str = PROVENANCE_UNVERIFIED_STRUCTURAL

    def __post_init__(self) -> None:
        if not self.grant_id or not self.grant_id.startswith("pog_"):
            raise ForgedApprovalError(
                f"ProtectedOperationGrant 'grant_id' must start with 'pog_', got '{self.grant_id}'."
            )
        if self.authority_level != AuthorityLevel.PROTECTED_OPERATION.value:
            raise AuthorityTypeMismatchError(
                f"Invalid authority_level '{self.authority_level}' for ProtectedOperationGrant."
            )
        valid_ops = {op.value for op in ProtectedOperationType}
        if self.operation_type not in valid_ops:
            raise AuthorityError(f"Unsupported ProtectedOperationType '{self.operation_type}'.")
        if not self.founder_decision_id or not self.founder_decision_id.startswith("fdec_"):
            raise ForgedApprovalError(
                f"ProtectedOperationGrant must reference an authenticated FounderDecision ('fdec_*'), got '{self.founder_decision_id}'."
            )
        if len(self.founder_decision_sha256) != 64 or not _is_hex(self.founder_decision_sha256):
            raise ForgedApprovalError("ProtectedOperationGrant requires 64-hex founder_decision_sha256.")
        if not self.auth_session_id or len(self.auth_session_id.strip()) < 16:
            raise FounderAuthenticationRequiredError(
                "ProtectedOperationGrant requires verified auth_session_id (>= 16 chars)."
            )
        if not self.approver or not self.approver.strip():
            raise FounderAuthenticationRequiredError("ProtectedOperationGrant requires non-empty approver.")
        if not self.proposal_id or len(self.proposal_sha256) != 64 or not _is_hex(self.proposal_sha256):
            raise AuthorityError("ProtectedOperationGrant requires proposal_id and 64-hex proposal_sha256.")
        if not self.expected_head_hash or not (7 <= len(self.expected_head_hash) <= 40) or not _is_hex(self.expected_head_hash):
            raise AuthorityError("ProtectedOperationGrant requires valid expected_head_hash.")
        if not self.expected_changed_files:
            raise AuthorityError("ProtectedOperationGrant requires at least one expected_changed_file.")
        if not self.expires_at:
            exp = (_parse_iso(self.created_at) + timedelta(seconds=900)).isoformat()
            object.__setattr__(self, "expires_at", exp)

        expected_sha = compute_protected_operation_grant_sha256(self)
        if not self.grant_sha256:
            object.__setattr__(self, "grant_sha256", expected_sha)
        elif self.grant_sha256 != expected_sha:
            raise ForgedApprovalError("ProtectedOperationGrant SHA-256 integrity verification failed (tampered grant).")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        ref = now or _utc_now()
        return ref > _parse_iso(self.expires_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "authority_level": self.authority_level,
            "operation_type": self.operation_type,
            "founder_decision_id": self.founder_decision_id,
            "founder_decision_sha256": self.founder_decision_sha256,
            "auth_session_id": self.auth_session_id,
            "approver": self.approver,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "target_repository_root": self.target_repository_root,
            "target_branch": self.target_branch,
            "expected_head_hash": self.expected_head_hash,
            "code_patch_artifact_id": self.code_patch_artifact_id,
            "code_patch_sha256": self.code_patch_sha256,
            "qa_execution_report_artifact_id": self.qa_execution_report_artifact_id,
            "qa_execution_report_sha256": self.qa_execution_report_sha256,
            "expected_changed_files": list(self.expected_changed_files),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "grant_sha256": self.grant_sha256,
            "founder_session_proof": self.founder_session_proof,
            "provenance_status": self.provenance_status,
        }


def compute_protected_operation_grant_sha256(grant: ProtectedOperationGrant) -> str:
    return _canonical_sha256(
        {
            "grant_id": grant.grant_id,
            "authority_level": grant.authority_level,
            "operation_type": grant.operation_type,
            "founder_decision_id": grant.founder_decision_id,
            "founder_decision_sha256": grant.founder_decision_sha256,
            "auth_session_id": grant.auth_session_id,
            "approver": grant.approver,
            "proposal_id": grant.proposal_id,
            "proposal_sha256": grant.proposal_sha256,
            "target_repository_root": grant.target_repository_root,
            "target_branch": grant.target_branch,
            "expected_head_hash": grant.expected_head_hash,
            "code_patch_artifact_id": grant.code_patch_artifact_id,
            "code_patch_sha256": grant.code_patch_sha256,
            "qa_execution_report_artifact_id": grant.qa_execution_report_artifact_id,
            "qa_execution_report_sha256": grant.qa_execution_report_sha256,
            "expected_changed_files": list(grant.expected_changed_files),
            "created_at": grant.created_at,
            "expires_at": grant.expires_at,
            "founder_session_proof": grant.founder_session_proof,
            "provenance_status": grant.provenance_status,
        }
    )


def derive_protected_operation_grant(
    *,
    decision: Any,
    operation_type: ProtectedOperationType | str,
    proposal_id: str,
    proposal_sha256: str,
    target_repository_root: str,
    target_branch: str,
    expected_head_hash: str,
    code_patch_artifact_id: str,
    code_patch_sha256: str,
    qa_execution_report_artifact_id: str,
    qa_execution_report_sha256: str,
    expected_changed_files: Sequence[str],
    authenticator: Optional[FounderSessionAuthenticator] = None,
    ttl_seconds: int = 900,
) -> ProtectedOperationGrant:
    """Derive a ProtectedOperationGrant strictly from a cryptographically verified FounderDecision.

    Fail-closed rules:
    - Rejects SandboxExecutionToken (`AuthorityTypeMismatchError`).
    - Rejects wrong FounderDecision types (`AuthorityTypeMismatchError`).
    - Rejects any FounderDecision lacking a server-verified `FounderSessionAuthenticator`
      HMAC `session_proof` (`FounderAuthenticationRequiredError`).
    """
    if isinstance(decision, SandboxExecutionToken):
        raise AuthorityTypeMismatchError(
            "Privilege escalation blocked: SandboxExecutionToken cannot derive a ProtectedOperationGrant."
        )
    if not isinstance(decision, FounderDecision):
        raise AuthorityTypeMismatchError(
            f"ProtectedOperationGrant requires an authenticated FounderDecision, got {type(decision).__name__}."
        )
    if decision.decision_type != FounderDecisionType.PROTECTED_OPERATION_APPROVAL.value:
        raise AuthorityTypeMismatchError(
            f"FounderDecision of type '{decision.decision_type}' cannot authorize protected operation "
            f"(requires '{FounderDecisionType.PROTECTED_OPERATION_APPROVAL.value}')."
        )
    if decision.subject_artifact_id != proposal_id or decision.subject_sha256 != proposal_sha256:
        raise ForgedApprovalError(
            f"FounderDecision '{decision.decision_id}' is bound to proposal '{decision.subject_artifact_id}' "
            f"({decision.subject_sha256[:12]}), not '{proposal_id}' ({proposal_sha256[:12]})."
        )
    if decision.decision_sha256 != compute_founder_decision_sha256(decision):
        raise ForgedApprovalError("FounderDecision integrity verification failed.")

    if authenticator is None:
        raise FounderAuthenticationRequiredError(
            "ProtectedOperationGrant derivation requires a FounderSessionAuthenticator to verify human provenance."
        )
    authenticator.verify_decision(decision)

    op = operation_type.value if isinstance(operation_type, ProtectedOperationType) else str(operation_type)
    now = _utc_now()
    return ProtectedOperationGrant(
        grant_id=f"pog_{uuid.uuid4().hex[:12]}",
        operation_type=op,
        founder_decision_id=decision.decision_id,
        founder_decision_sha256=decision.decision_sha256,
        auth_session_id=decision.auth_session_id,
        approver=decision.actor,
        proposal_id=proposal_id,
        proposal_sha256=proposal_sha256,
        target_repository_root=target_repository_root,
        target_branch=target_branch,
        expected_head_hash=expected_head_hash,
        code_patch_artifact_id=code_patch_artifact_id,
        code_patch_sha256=code_patch_sha256,
        qa_execution_report_artifact_id=qa_execution_report_artifact_id,
        qa_execution_report_sha256=qa_execution_report_sha256,
        expected_changed_files=tuple(sorted({_norm_rel(f) for f in expected_changed_files if f and f.strip()})),
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=max(ttl_seconds, 1))).isoformat(),
        founder_session_proof=decision.session_proof,
        provenance_status=PROVENANCE_VERIFIED_SESSION_BOUND,
    )


# ==============================================================================
# Thread-Safe & Cross-Process Atomic Durable Replay Registry
# ==============================================================================

_REGISTRY_LOCKS_GUARD = threading.Lock()
_REGISTRY_THREAD_LOCKS: Dict[str, threading.RLock] = {}


def _get_thread_lock_for_path(key: str) -> threading.RLock:
    with _REGISTRY_LOCKS_GUARD:
        lock = _REGISTRY_THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _REGISTRY_THREAD_LOCKS[key] = lock
        return lock


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return True
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return True  # Fail-safe: assume alive if uncertain
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


class AuthorityRegistry:
    """Thread-safe, process-safe, atomic durable registry preventing authority replay.

    Guarantees:
    - All reads and writes serialize via both an in-process per-path `threading.RLock`
      and a cross-process atomic `O_CREAT | O_EXCL` lockfile (`<registry>.lock`).
    - Every locked operation reloads fresh JSON from disk before checking state so
      concurrent threads and independent OS processes see consistent state.
    - `consume_once(...)` checks and persists all keys inside ONE locked transaction
      using unique temporary file + `os.fsync` + atomic `os.replace`.
    """

    def __init__(
        self,
        registry_file: Optional[Path] = None,
        *,
        lock_timeout_seconds: float = 5.0,
    ) -> None:
        self.registry_file = registry_file.resolve() if registry_file is not None else None
        self.lock_timeout_seconds = max(lock_timeout_seconds, 0.2)
        lock_key = str(self.registry_file).lower() if self.registry_file else f"mem:{id(self)}"
        self._thread_lock = _get_thread_lock_for_path(lock_key)
        self._consumed: Dict[str, Dict[str, Any]] = {}
        if self.registry_file and self.registry_file.is_file():
            with self._locked_transaction():
                self._reload_locked()

    @property
    def lock_file(self) -> Optional[Path]:
        if self.registry_file is None:
            return None
        return self.registry_file.with_name(f"{self.registry_file.name}.lock")

    def _acquire_process_lock(self) -> Optional[Path]:
        lf = self.lock_file
        if lf is None:
            return None
        lf.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.lock_timeout_seconds
        sleep_s = 0.005
        while True:
            try:
                fd = os.open(str(lf), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    payload = json.dumps(
                        {
                            "pid": os.getpid(),
                            "tid": threading.get_ident(),
                            "acquired_at": _utc_now_iso(),
                        }
                    ).encode("utf-8")
                    os.write(fd, payload)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                return lf
            except FileExistsError:
                # Conservative stale lock check: ONLY reclaim if recorded PID is provably dead
                try:
                    raw = lf.read_text(encoding="utf-8")
                    meta = json.loads(raw)
                    holder_pid = int(meta.get("pid", -1))
                    if holder_pid > 0 and holder_pid != os.getpid() and not _pid_is_alive(holder_pid):
                        try:
                            lf.unlink(missing_ok=True)
                            continue
                        except OSError:
                            pass
                except Exception:
                    pass
                if time.monotonic() >= deadline:
                    raise AuthorityLockError(
                        f"Timed out waiting for AuthorityRegistry cross-process lock '{lf}' "
                        f"after {self.lock_timeout_seconds:.2f}s."
                    )
                time.sleep(sleep_s)
                sleep_s = min(sleep_s * 1.5, 0.05)

    def _release_process_lock(self, lf: Optional[Path]) -> None:
        if lf is not None:
            try:
                lf.unlink(missing_ok=True)
            except OSError:
                pass

    @contextmanager
    def _locked_transaction(self) -> Iterator[None]:
        with self._thread_lock:
            lf = self._acquire_process_lock()
            try:
                self._reload_locked()
                yield
            finally:
                self._release_process_lock(lf)

    def _reload_locked(self) -> None:
        if self.registry_file is None:
            return
        if not self.registry_file.is_file():
            self._consumed = {}
            return
        try:
            loaded = json.loads(self.registry_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self._consumed = loaded
            else:
                raise AuthorityError(f"AuthorityRegistry file '{self.registry_file}' root must be a JSON object.")
        except AuthorityError:
            raise
        except Exception as exc:
            raise AuthorityError(
                f"Fail-closed: corrupted AuthorityRegistry file '{self.registry_file}': {exc}"
            ) from exc

    def _persist_locked(self) -> None:
        if self.registry_file is None:
            return
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        unique_tmp = self.registry_file.with_name(
            f"{self.registry_file.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.tmp"
        )
        serialized = json.dumps(self._consumed, indent=2, sort_keys=True).encode("utf-8")
        try:
            with open(unique_tmp, "wb") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            # Bounded retry on transient Windows file-replace contention
            for attempt in range(5):
                try:
                    os.replace(unique_tmp, self.registry_file)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        finally:
            if unique_tmp.exists():
                try:
                    unique_tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    def is_consumed(self, key: str) -> bool:
        with self._locked_transaction():
            return key in self._consumed

    def assert_not_replayed(self, key: str, kind: str = "authority") -> None:
        with self._locked_transaction():
            if key in self._consumed:
                raise AuthorityReplayError(f"Replay blocked: {kind} '{key}' has already been consumed.")

    def consume_once(
        self,
        keys: Sequence[str],
        metadata: Optional[Dict[str, Any]] = None,
        *,
        kind: str = "authority",
    ) -> None:
        """Atomically verify none of `keys` are consumed and persist all of them in one transaction."""
        cleaned = [k.strip() for k in keys if isinstance(k, str) and k.strip()]
        if not cleaned:
            raise AuthorityError("consume_once requires at least one non-empty key.")
        with self._locked_transaction():
            for k in cleaned:
                if k in self._consumed:
                    raise AuthorityReplayError(f"Replay blocked: {kind} '{k}' has already been consumed.")
            now_iso = _utc_now_iso()
            for k in cleaned:
                self._consumed[k] = {
                    "consumed_at": now_iso,
                    "pid": os.getpid(),
                    **(metadata or {}),
                }
            self._persist_locked()

    def mark_consumed(self, key: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Atomically verify `key` is unconsumed and persist it."""
        self.consume_once([key], metadata=metadata)


# ==============================================================================
# Enforcement Validators (Stateless + Atomic Check-and-Consume)
# ==============================================================================

def verify_sandbox_token_for_worktree(
    token: Any,
    *,
    worktree_root: Path,
    real_repo_root: Path,
    requested_files: Optional[Iterable[str]] = None,
    run_id: Optional[str] = None,
    task_id: Optional[str] = None,
    plan_artifact_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Verify SandboxExecutionToken strictly targets an isolated worktree (never real repo)."""
    if not isinstance(token, SandboxExecutionToken):
        raise AuthorityTypeMismatchError(
            f"Isolated worktree execution requires SandboxExecutionToken, got {type(token).__name__}."
        )
    if token.is_expired(now=now):
        raise AuthorityExpiredError(f"SandboxExecutionToken '{token.token_id}' expired at {token.expires_at}.")

    if run_id is not None and token.run_id != run_id:
        raise ScopeExpansionForbiddenError(
            f"SandboxExecutionToken '{token.token_id}' is bound to run '{token.run_id}', not '{run_id}'."
        )
    if task_id is not None and token.task_id != task_id:
        raise ScopeExpansionForbiddenError(
            f"SandboxExecutionToken '{token.token_id}' is bound to task '{token.task_id}', not '{task_id}'."
        )
    if plan_artifact_id is not None and token.plan_artifact_id != plan_artifact_id:
        raise ScopeExpansionForbiddenError(
            f"SandboxExecutionToken '{token.token_id}' is bound to plan '{token.plan_artifact_id}', not '{plan_artifact_id}'."
        )

    wt_resolved = worktree_root.resolve()
    real_resolved = real_repo_root.resolve()
    if wt_resolved == real_resolved:
        raise ScopeExpansionForbiddenError(
            "Privilege escalation blocked: SandboxExecutionToken cannot target the real repository root."
        )
    if token.worktree_path and Path(token.worktree_path).resolve() != wt_resolved:
        raise ScopeExpansionForbiddenError(
            f"SandboxExecutionToken '{token.token_id}' is bound to worktree '{token.worktree_path}', not '{wt_resolved}'."
        )

    if requested_files is not None:
        allowed: Set[str] = {_norm_rel(f) for f in token.approved_files_to_modify} | {
            _norm_rel(f) for f in token.approved_files_to_create
        }
        extra = sorted({_norm_rel(f) for f in requested_files} - allowed)
        if extra:
            raise ScopeExpansionForbiddenError(
                f"SandboxExecutionToken '{token.token_id}' scope expansion denied for files: {extra}."
            )


def verify_and_consume_sandbox_token(
    token: Any,
    *,
    worktree_root: Path,
    real_repo_root: Path,
    registry: AuthorityRegistry,
    requested_files: Optional[Iterable[str]] = None,
    run_id: Optional[str] = None,
    task_id: Optional[str] = None,
    plan_artifact_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Atomically verify SandboxExecutionToken scope/binding and consume it single-use."""
    verify_sandbox_token_for_worktree(
        token,
        worktree_root=worktree_root,
        real_repo_root=real_repo_root,
        requested_files=requested_files,
        run_id=run_id,
        task_id=task_id,
        plan_artifact_id=plan_artifact_id,
        now=now,
    )
    registry.consume_once(
        [f"sbx:{token.token_id}"],
        metadata={
            "kind": "SandboxExecutionToken",
            "run_id": token.run_id,
            "task_id": token.task_id,
            "iteration": token.iteration,
            "worktree_root": str(worktree_root.resolve()),
        },
        kind="SandboxExecutionToken",
    )


def verify_protected_operation_grant(
    grant: Any,
    *,
    operation_type: ProtectedOperationType | str,
    target_repository_root: Path,
    current_head_hash: str,
    requested_files: Sequence[str],
    registry: Optional[AuthorityRegistry] = None,
    authenticator: Optional[FounderSessionAuthenticator] = None,
    now: Optional[datetime] = None,
) -> None:
    """Enforce all invariants before executing a protected operation (fail-closed)."""
    if isinstance(grant, SandboxExecutionToken):
        raise AuthorityTypeMismatchError(
            "Privilege escalation blocked: SandboxExecutionToken cannot authorize a protected operation."
        )
    if isinstance(grant, FounderDecision):
        raise AuthorityTypeMismatchError(
            "Privilege confusion blocked: FounderDecision cannot directly execute a protected operation without a ProtectedOperationGrant."
        )
    if not isinstance(grant, ProtectedOperationGrant):
        raise AuthorityTypeMismatchError(
            f"Protected operation requires ProtectedOperationGrant, got {type(grant).__name__}."
        )

    if grant.grant_sha256 != compute_protected_operation_grant_sha256(grant):
        raise ForgedApprovalError(f"ProtectedOperationGrant '{grant.grant_id}' failed SHA-256 integrity check.")

    if (
        grant.provenance_status != PROVENANCE_VERIFIED_SESSION_BOUND
        or not grant.founder_session_proof
        or len(grant.founder_session_proof) != 64
        or not _is_hex(grant.founder_session_proof)
    ):
        raise FounderAuthenticationRequiredError(
            f"ProtectedOperationGrant '{grant.grant_id}' lacks verified cryptographic session provenance."
        )

    if authenticator is not None:
        authenticator.verify_grant_session(grant, now=now)

    if grant.is_expired(now=now):
        raise AuthorityExpiredError(f"ProtectedOperationGrant '{grant.grant_id}' expired at {grant.expires_at}.")

    if registry is not None:
        registry.assert_not_replayed(grant.grant_id, kind="ProtectedOperationGrant")
        registry.assert_not_replayed(grant.founder_decision_id, kind="FounderDecision")

    expected_op = operation_type.value if isinstance(operation_type, ProtectedOperationType) else str(operation_type)
    if grant.operation_type != expected_op:
        raise ScopeExpansionForbiddenError(
            f"ProtectedOperationGrant '{grant.grant_id}' authorizes '{grant.operation_type}', not '{expected_op}'."
        )

    if Path(grant.target_repository_root).resolve() != target_repository_root.resolve():
        raise ScopeExpansionForbiddenError(
            f"ProtectedOperationGrant '{grant.grant_id}' target repo mismatch: "
            f"'{grant.target_repository_root}' != '{target_repository_root}'."
        )

    if current_head_hash.strip() != grant.expected_head_hash.strip():
        raise StaleRepositoryHeadError(
            f"Stale repository HEAD: current '{current_head_hash}' != approved '{grant.expected_head_hash}'."
        )

    granted_files = {_norm_rel(f) for f in grant.expected_changed_files}
    req_files = {_norm_rel(f) for f in requested_files}
    extra_files = sorted(req_files - granted_files)
    if extra_files:
        raise ScopeExpansionForbiddenError(
            f"Unauthorized scope expansion: files {extra_files} are outside ProtectedOperationGrant '{grant.grant_id}'."
        )


def verify_and_consume_protected_operation_grant(
    grant: Any,
    *,
    operation_type: ProtectedOperationType | str,
    target_repository_root: Path,
    current_head_hash: str,
    requested_files: Sequence[str],
    registry: AuthorityRegistry,
    authenticator: Optional[FounderSessionAuthenticator] = None,
    extra_keys: Sequence[str] = (),
    now: Optional[datetime] = None,
) -> None:
    """Atomically verify AND consume a ProtectedOperationGrant inside ONE dual-locked transaction."""
    with registry._locked_transaction():
        verify_protected_operation_grant(
            grant,
            operation_type=operation_type,
            target_repository_root=target_repository_root,
            current_head_hash=current_head_hash,
            requested_files=requested_files,
            registry=None,  # Checked atomically below inside this same locked transaction
            authenticator=authenticator,
            now=now,
        )
        keys = [grant.grant_id, grant.founder_decision_id, *extra_keys]
        for k in keys:
            if k and k in registry._consumed:
                raise AuthorityReplayError(f"Replay blocked: ProtectedOperationGrant key '{k}' has already been consumed.")
        now_iso = _utc_now_iso()
        for k in keys:
            if k:
                registry._consumed[k] = {
                    "consumed_at": now_iso,
                    "pid": os.getpid(),
                    "kind": "ProtectedOperationGrant",
                    "grant_id": grant.grant_id,
                    "proposal_id": grant.proposal_id,
                }
        registry._persist_locked()
