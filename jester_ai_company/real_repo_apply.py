"""Human-Approved Transactional Real Repository Apply (STEP 16).

Provides deterministic, fail-closed, application-owned application of verified
and QA-PASSED CODE_PATCH artifacts to the human owner's real target repository.

Core Safety Invariants:
1. Zero Agent Mutation: No agent (Developer, QA, CEO, etc.) possesses authority
   to mutate the real repository. Only deterministic application software executes.
2. Mandatory Human Approval: Explicit, transaction-specific human approval is required
   prior to mutation. Never synthesized in production.
3. Clean Repository Precondition: Real repository working tree must be 100% clean
   (git status --porcelain == "") before apply.
4. TOCTOU Protection: Double pre-mutation check under external lock re-validates exact HEAD
   commit and clean state immediately before filesystem modification.
5. Exact Diff Equivalence: Final commit point requires exact correspondence between
   applied diff and verified CODE_PATCH.
6. Non-Destructive Rollback: Reverse patch apply as primary rollback; restores clean state
   without destructive git reset --hard or git clean -fd.
7. External Lock: Stored in JesterAICompany runtime state (.runs/locks/), NEVER inside
   target .git.
8. No Agent Runtime: Zero LLM / subagent invocations during real apply.
9. No Auto-Commit / Auto-Push: Applies changes to working tree only. Human founder commits.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from .core import (
    Artifact,
    ArtifactType,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from .execution_grant import (
    GrantValidationError,
    MissingApprovalError,
    ProtectedPathError,
)
from .qa_execution import QAFinalVerdict
from .project import CrossProjectMismatchError as BaseCrossProjectMismatchError
from .worktree import (
    is_protected_path,
    resolve_repo_head_commit,
    run_git,
    verify_workspace_path,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ==============================================================================
# Domain Exceptions
# ==============================================================================

class RealRepoApplyError(Exception):
    """Base exception for real repository apply errors."""
    pass


class TargetRepositoryInvalidError(RealRepoApplyError):
    """Raised when target path is not a valid git repository."""
    pass


class TargetRepositoryDirtyError(RealRepoApplyError):
    """Raised when target repository working tree is not completely clean."""
    pass


class BaseCommitMismatchError(RealRepoApplyError):
    """Raised when target repository HEAD does not match patch base commit."""
    pass


class CandidateNotEligibleError(RealRepoApplyError):
    """Raised when CODE_PATCH or QA execution report fails eligibility criteria."""
    pass


class ProposalMismatchError(RealRepoApplyError):
    """Raised when proposal data or hash does not match expected state."""
    pass


class ApprovalInvalidError(RealRepoApplyError):
    """Raised when human approval is missing, invalid, or forged."""
    pass


class GrantReplayedError(RealRepoApplyError):
    """Raised when a single-use grant or approval has already been consumed."""
    pass


class GrantExpiredError(RealRepoApplyError):
    """Raised when a grant exceeds its maximum validity duration."""
    pass


class RepositoryStateChangedError(RealRepoApplyError):
    """Raised when TOCTOU check detects repository state modified after approval."""
    pass


class ConcurrentApplyError(RealRepoApplyError):
    """Raised when another apply transaction holds the external repository lock."""
    pass


class CrossProjectMismatchError(RealRepoApplyError, BaseCrossProjectMismatchError):
    """Raised when an apply proposal or grant targets an unauthorized project or repository."""
    pass


class PatchPrecheckFailedError(RealRepoApplyError):
    """Raised when git apply --check fails on candidate patch."""
    pass


class PatchApplyFailedError(RealRepoApplyError):
    """Raised when git apply fails during transaction execution."""
    pass


class PostApplyDiffMismatchError(RealRepoApplyError):
    """Raised when post-apply diff does not equal the approved CODE_PATCH."""
    pass


class RollbackFailedError(RealRepoApplyError):
    """Raised when rollback fails to restore the exact clean pre-apply state."""
    pass


class CrashRecoveryBlockError(RealRepoApplyError):
    """Raised when target repository has an unresolved crash/partial apply state."""
    pass


# ==============================================================================
# Enums and Statuses
# ==============================================================================

class RealRepoApplyStatus(str, Enum):
    """Terminal and lifecycle statuses for real repository apply transactions."""
    CANDIDATE_READY = "CANDIDATE_READY"
    PREPARED = "PREPARED"
    APPROVED = "APPROVED"
    APPLYING = "APPLYING"
    VALIDATING = "VALIDATING"
    APPLIED_SUCCESSFULLY = "APPLIED_SUCCESSFULLY"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    ABORTED_STATE_CHANGED = "ABORTED_STATE_CHANGED"
    ABORTED_DIRTY = "ABORTED_DIRTY"
    FAILED = "FAILED"


class CrashStateClassification(str, Enum):
    """Deterministic classification of repository state after crash / preflight."""
    NOT_APPLIED = "NOT_APPLIED"
    EXACT_APPROVED_PATCH_PRESENT = "EXACT_APPROVED_PATCH_PRESENT"
    PARTIAL_OR_UNKNOWN_STATE = "PARTIAL_OR_UNKNOWN_STATE"


# ==============================================================================
# Identity and Fingerprint Models
# ==============================================================================

@dataclass(frozen=True)
class TargetRepositoryIdentity:
    """Simplified local repository identity model (Principle 2)."""
    canonical_root: str
    current_head: str
    current_branch: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepositoryStateFingerprint:
    """Deterministic fingerprint of repository state at a specific point in time."""
    canonical_root: str
    head_commit_hash: str
    branch_name: str
    is_clean: bool
    state_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_repo_fingerprint(repo_root: Path) -> RepositoryStateFingerprint:
    """Compute deterministic fingerprint of target repository state."""
    root_resolved = repo_root.resolve()
    if not (root_resolved / ".git").exists():
        raise TargetRepositoryInvalidError(f"Directory '{root_resolved}' is not a valid Git repository.")

    head = resolve_repo_head_commit(root_resolved)
    code, branch_out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root_resolved)
    branch = branch_out.strip() if code == 0 else "DETACHED"

    code, stat_out, _ = run_git(["status", "--porcelain"], cwd=root_resolved)
    is_clean = (code == 0 and stat_out.strip() == "")

    fingerprint_raw = f"{root_resolved.as_posix()}:{head}:{branch}:{is_clean}"
    state_sha = hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()

    return RepositoryStateFingerprint(
        canonical_root=root_resolved.as_posix(),
        head_commit_hash=head,
        branch_name=branch,
        is_clean=is_clean,
        state_sha256=state_sha,
    )


def verify_target_repo_cleanliness(repo_root: Path, allow_untracked: bool = False) -> Tuple[bool, str]:
    """Verify that target repository working tree is clean.
    
    If allow_untracked is True, untracked files are excluded (--untracked-files=no),
    preserving the distinction between tracked state and pre-existing untracked files.
    """
    cmd = ["status", "--porcelain"]
    if allow_untracked:
        cmd.append("--untracked-files=no")
    code, stdout, stderr = run_git(cmd, cwd=repo_root)
    if code != 0:
        raise TargetRepositoryInvalidError(f"Failed to inspect git status: {stderr.strip()}")
    trimmed = stdout.strip()
    return (trimmed == ""), trimmed



# ==============================================================================
# Proposal & Grant Data Models
# ==============================================================================

@dataclass(frozen=True)
class RealRepoApplyProposal:
    """Immutable typed proposal for human review before real repository mutation."""
    schema_version: str
    proposal_id: str
    target_repository_root: str
    target_branch: str
    target_head_hash: str
    base_commit_hash: str

    code_patch_artifact_id: str
    code_patch_sha256: str
    patch_version: int

    qa_report_artifact_id: str
    qa_report_sha256: str
    qa_execution_report_artifact_id: str
    qa_execution_report_sha256: str
    qa_verdict: str

    expected_changed_files: Tuple[str, ...]
    expected_diff_stat: Dict[str, int]
    is_clean: bool

    created_at: str
    proposal_sha256: str
    project_id: Optional[str] = None
    repository_id: Optional[str] = None

    @property
    def target_repo_root(self) -> str:
        """Alias for target_repository_root."""
        return self.target_repository_root

    @property
    def status(self) -> str:
        """Lifecycle status of proposal before founder grant."""
        return "READY_FOR_APPROVAL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "proposal_id": self.proposal_id,
            "target_repository_root": self.target_repository_root,
            "target_branch": self.target_branch,
            "target_head_hash": self.target_head_hash,
            "base_commit_hash": self.base_commit_hash,
            "code_patch_artifact_id": self.code_patch_artifact_id,
            "code_patch_sha256": self.code_patch_sha256,
            "patch_version": self.patch_version,
            "qa_report_artifact_id": self.qa_report_artifact_id,
            "qa_report_sha256": self.qa_report_sha256,
            "qa_execution_report_artifact_id": self.qa_execution_report_artifact_id,
            "qa_execution_report_sha256": self.qa_execution_report_sha256,
            "qa_verdict": self.qa_verdict,
            "expected_changed_files": list(self.expected_changed_files),
            "expected_diff_stat": self.expected_diff_stat,
            "is_clean": self.is_clean,
            "created_at": self.created_at,
            "proposal_sha256": self.proposal_sha256,
            "project_id": self.project_id,
            "repository_id": self.repository_id,
        }


@dataclass(frozen=True)
class RealRepoApplyGrant:
    """Single-use, replay-protected capability grant for real repository apply."""
    schema_version: str
    grant_id: str
    proposal_id: str
    proposal_sha256: str

    target_repository_root: str
    expected_head_hash: str

    code_patch_artifact_id: str
    code_patch_sha256: str
    qa_execution_report_artifact_id: str
    qa_execution_report_sha256: str

    expected_changed_files: Tuple[str, ...]

    human_approval_id: str
    approver: str
    approved_at: str

    status: str = "ISSUED"  # "ISSUED" -> "CONSUMED" -> "INVALIDATED"
    validity_duration_seconds: int = 3600
    project_id: Optional[str] = None
    repository_id: Optional[str] = None

    @property
    def founder_approval_id(self) -> str:
        """Alias for human_approval_id for founder approval workflows."""
        return self.human_approval_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "grant_id": self.grant_id,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "target_repository_root": self.target_repository_root,
            "expected_head_hash": self.expected_head_hash,
            "code_patch_artifact_id": self.code_patch_artifact_id,
            "code_patch_sha256": self.code_patch_sha256,
            "qa_execution_report_artifact_id": self.qa_execution_report_artifact_id,
            "qa_execution_report_sha256": self.qa_execution_report_sha256,
            "expected_changed_files": list(self.expected_changed_files),
            "human_approval_id": self.human_approval_id,
            "approver": self.approver,
            "approved_at": self.approved_at,
            "status": self.status,
            "validity_duration_seconds": self.validity_duration_seconds,
            "project_id": self.project_id,
            "repository_id": self.repository_id,
        }


@dataclass
class RealRepoApplyResult:
    """Durable outcome of an executed real repository apply transaction."""
    grant_id: str
    proposal_id: str
    target_repository_root: str
    status: str  # RealRepoApplyStatus
    summary: str
    pre_apply_head: str
    post_apply_head: str
    expected_files: List[str]
    actual_files: List[str]
    report_artifact_id: Optional[str] = None
    error: Optional[str] = None
    applied_at: str = field(default_factory=_utc_now_iso)
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "proposal_id": self.proposal_id,
            "target_repository_root": self.target_repository_root,
            "status": self.status,
            "summary": self.summary,
            "pre_apply_head": self.pre_apply_head,
            "post_apply_head": self.post_apply_head,
            "expected_files": self.expected_files,
            "actual_files": self.actual_files,
            "error": self.error,
            "applied_at": self.applied_at,
            "duration_ms": self.duration_ms,
        }


# ==============================================================================
# External Repository Lock (Principle 1)
# Stored in JesterAICompany runtime state (.runs/locks/), NOT in target .git
# ==============================================================================

class RealRepoApplyLock:
    """Process-level external repository apply lock stored in company runtime state."""

    def __init__(self, locks_dir: Path, repo_root: Path, timeout_seconds: float = 10.0):
        self.locks_dir = locks_dir.resolve()
        self.repo_root = repo_root.resolve()
        self.timeout_seconds = timeout_seconds

        repo_hash = hashlib.sha256(self.repo_root.as_posix().encode("utf-8")).hexdigest()[:16]
        self.lock_file = self.locks_dir / f"apply_{repo_hash}.lock"
        self._acquired = False

    def acquire(self, proposal_id: str) -> None:
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            try:
                content = json.loads(self.lock_file.read_text(encoding="utf-8"))
                holder_pid = content.get("pid")
                holder_prop = content.get("proposal_id")
                raise ConcurrentApplyError(
                    f"Repository '{self.repo_root}' is already locked by PID {holder_pid} (proposal: {holder_prop})."
                )
            except (json.JSONDecodeError, OSError):
                raise ConcurrentApplyError(f"Repository '{self.repo_root}' lock file exists: '{self.lock_file}'.")

        try:
            fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                payload = {
                    "pid": os.getpid(),
                    "proposal_id": proposal_id,
                    "target_repo": self.repo_root.as_posix(),
                    "acquired_at": _utc_now_iso(),
                }
                json.dump(payload, f)
            self._acquired = True
        except FileExistsError as exc:
            raise ConcurrentApplyError(f"Repository '{self.repo_root}' was locked concurrently.") from exc

    def release(self) -> None:
        if self._acquired:
            try:
                self.lock_file.unlink(missing_ok=True)
            except OSError as err:
                logger.warning("Failed to remove lock file '%s': %s", self.lock_file, err)
            finally:
                self._acquired = False

    def __enter__(self) -> "RealRepoApplyLock":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


# ==============================================================================
# Candidate Eligibility & Proposal Builder
# ==============================================================================

def validate_candidate_eligibility(
    code_patch_artifact: Artifact,
    code_patch_file_path: Path,
    qa_execution_report_artifact: Artifact,
    qa_execution_report_file_path: Path,
    target_repo_root: Path,
) -> None:
    """Deterministically validate eligibility of candidate artifacts before proposal."""
    # 1. Physical patch file existence & SHA
    if not code_patch_file_path.is_file():
        raise CandidateNotEligibleError(f"CODE_PATCH physical file missing at '{code_patch_file_path}'.")
    patch_bytes = code_patch_file_path.read_bytes()
    actual_patch_sha = hashlib.sha256(patch_bytes).hexdigest()
    if actual_patch_sha != code_patch_artifact.sha256:
        raise CandidateNotEligibleError(
            f"CODE_PATCH SHA mismatch: computed '{actual_patch_sha}' != recorded '{code_patch_artifact.sha256}'."
        )

    # 2. Patch metadata validation
    meta = code_patch_artifact.metadata or {}
    base_commit = meta.get("base_commit_hash")
    if not base_commit or not isinstance(base_commit, str) or len(base_commit) < 7:
        raise CandidateNotEligibleError("CODE_PATCH metadata missing valid base_commit_hash.")

    changed_files = meta.get("changed_files", [])
    if not changed_files or not isinstance(changed_files, list):
        raise CandidateNotEligibleError("CODE_PATCH metadata missing valid changed_files list.")

    # Validate each path does not escape or violate protected paths
    for rel_path in changed_files:
        verify_workspace_path(rel_path, target_repo_root)
        if is_protected_path(rel_path):
            raise ProtectedPathError(f"CODE_PATCH contains protected path: '{rel_path}'.")

    # Verification outcomes
    veri_outcomes = meta.get("verification_outcomes", [])
    if not veri_outcomes or not isinstance(veri_outcomes, list):
        raise CandidateNotEligibleError("CODE_PATCH has no verification outcomes recorded.")
    if not all(vo.get("status") == "PASS" for vo in veri_outcomes if isinstance(vo, dict)):
        raise CandidateNotEligibleError("CODE_PATCH has non-passing verification outcomes.")

    # 3. QA Execution Report existence & SHA
    if not qa_execution_report_file_path.is_file():
        raise CandidateNotEligibleError(f"QA_EXECUTION_REPORT physical file missing at '{qa_execution_report_file_path}'.")
    qa_bytes = qa_execution_report_file_path.read_bytes()
    actual_qa_sha = hashlib.sha256(qa_bytes).hexdigest()
    if actual_qa_sha != qa_execution_report_artifact.sha256:
        raise CandidateNotEligibleError(
            f"QA_EXECUTION_REPORT SHA mismatch: computed '{actual_qa_sha}' != recorded '{qa_execution_report_artifact.sha256}'."
        )

    # 4. QA Final Verdict must be PASS
    qa_meta = qa_execution_report_artifact.metadata or {}
    verdict = qa_meta.get("verdict")
    if verdict != QAFinalVerdict.PASS.value:
        raise CandidateNotEligibleError(
            f"Cannot apply candidate patch: QA execution verdict is '{verdict}', expected 'PASS'."
        )

    # 5. Lineage match
    qa_patch_id = qa_meta.get("code_patch_artifact_id")
    qa_patch_sha = qa_meta.get("code_patch_sha256")
    if qa_patch_id != code_patch_artifact.id or qa_patch_sha != code_patch_artifact.sha256:
        raise CandidateNotEligibleError(
            f"QA_EXECUTION_REPORT lineage mismatch: targets patch '{qa_patch_id}' (sha: '{qa_patch_sha}'), "
            f"candidate is '{code_patch_artifact.id}' (sha: '{code_patch_artifact.sha256}')."
        )


def build_real_repo_apply_proposal(
    target_repo_root: Path,
    code_patch_artifact: Artifact,
    code_patch_file_path: Path,
    qa_report_artifact: Artifact,
    qa_execution_report_artifact: Artifact,
    qa_execution_report_file_path: Path,
    project_id: Optional[str] = None,
    repository_id: Optional[str] = None,
    allow_untracked: bool = False,
) -> RealRepoApplyProposal:
    """Build an immutable, typed proposal for human review. PERFORMS ZERO REPOSITORY MUTATION."""
    # 1. Eligibility validation
    validate_candidate_eligibility(
        code_patch_artifact=code_patch_artifact,
        code_patch_file_path=code_patch_file_path,
        qa_execution_report_artifact=qa_execution_report_artifact,
        qa_execution_report_file_path=qa_execution_report_file_path,
        target_repo_root=target_repo_root,
    )

    # 2. Inspect target repository state
    repo_resolved = target_repo_root.resolve()
    current_head = resolve_repo_head_commit(repo_resolved)
    code, branch_out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_resolved)
    branch = branch_out.strip() if code == 0 else "DETACHED"

    patch_meta = code_patch_artifact.metadata or {}
    base_commit = patch_meta.get("base_commit_hash", "")
    if current_head != base_commit:
        raise BaseCommitMismatchError(
            f"Target repository HEAD '{current_head}' does not match CODE_PATCH base commit '{base_commit}'."
        )

    # Read candidate patch text
    patch_text = code_patch_file_path.read_text(encoding="utf-8")
    changed_files = tuple(patch_meta.get("changed_files", []))

    # Cleanliness check & Crash State Classification (Principles 3 & 4)
    is_clean, dirty_stdout = verify_target_repo_cleanliness(repo_resolved, allow_untracked=allow_untracked)
    if not is_clean:
        crash_state = classify_crash_state(repo_resolved, patch_text, changed_files, allow_untracked=allow_untracked)
        if crash_state == CrashStateClassification.PARTIAL_OR_UNKNOWN_STATE:
            raise CrashRecoveryBlockError(
                f"Target repository '{repo_resolved}' has an unresolved crash/partial apply state ({crash_state.value}). "
                f"Fails closed and blocks new apply.\nStatus:\n{dirty_stdout}"
            )
        raise TargetRepositoryDirtyError(
            f"Target repository '{repo_resolved}' is dirty:\n{dirty_stdout}\n"
            f"A clean repository working tree is mandatory prior to real repository apply."
        )

    # Non-mutating precheck in isolation
    precheck_code_patch_applicability(repo_resolved, patch_text)

    # Calculate expected diffstat

    insertions = 0
    deletions = 0
    for line in patch_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    diff_stat = {
        "files_changed": len(changed_files),
        "insertions": insertions,
        "deletions": deletions,
    }

    proposal_id = f"prop_apply_{uuid.uuid4().hex[:8]}"
    created_at = _utc_now_iso()

    # Canonical dictionary for hash calculation
    canonical_dict = {
        "schema_version": "1.0",
        "proposal_id": proposal_id,
        "target_repository_root": repo_resolved.as_posix(),
        "target_branch": branch,
        "target_head_hash": current_head,
        "base_commit_hash": base_commit,
        "code_patch_artifact_id": code_patch_artifact.id,
        "code_patch_sha256": code_patch_artifact.sha256 or "",
        "patch_version": patch_meta.get("patch_version", 1),
        "qa_report_artifact_id": qa_report_artifact.id,
        "qa_report_sha256": qa_report_artifact.sha256 or "",
        "qa_execution_report_artifact_id": qa_execution_report_artifact.id,
        "qa_execution_report_sha256": qa_execution_report_artifact.sha256 or "",
        "qa_verdict": qa_execution_report_artifact.metadata.get("verdict", "PASS"),
        "expected_changed_files": list(changed_files),
        "expected_diff_stat": diff_stat,
        "is_clean": is_clean,
        "created_at": created_at,
    }
    if project_id:
        canonical_dict["project_id"] = project_id
    if repository_id:
        canonical_dict["repository_id"] = repository_id

    canonical_json = json.dumps(canonical_dict, sort_keys=True)
    proposal_sha = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    return RealRepoApplyProposal(
        schema_version="1.0",
        proposal_id=proposal_id,
        target_repository_root=repo_resolved.as_posix(),
        target_branch=branch,
        target_head_hash=current_head,
        base_commit_hash=base_commit,
        code_patch_artifact_id=code_patch_artifact.id,
        code_patch_sha256=code_patch_artifact.sha256 or "",
        patch_version=patch_meta.get("patch_version", 1),
        qa_report_artifact_id=qa_report_artifact.id,
        qa_report_sha256=qa_report_artifact.sha256 or "",
        qa_execution_report_artifact_id=qa_execution_report_artifact.id,
        qa_execution_report_sha256=qa_execution_report_artifact.sha256 or "",
        qa_verdict=qa_execution_report_artifact.metadata.get("verdict", "PASS"),
        expected_changed_files=changed_files,
        expected_diff_stat=diff_stat,
        is_clean=is_clean,
        created_at=created_at,
        proposal_sha256=proposal_sha,
        project_id=project_id,
        repository_id=repository_id,
    )


def derive_real_repo_apply_grant(
    proposal: RealRepoApplyProposal,
    founder_approval_id: str,
    approver: str = "Human Founder",
    validity_duration_seconds: int = 3600,
    project_id: Optional[str] = None,
    repository_id: Optional[str] = None,
) -> RealRepoApplyGrant:
    """Derive a single-use mutation grant bound to the approved proposal. ZERO REPO MUTATION."""
    if not founder_approval_id or not isinstance(founder_approval_id, str) or not founder_approval_id.strip():
        raise MissingApprovalError("Cannot derive RealRepoApplyGrant without explicit founder_approval_id.")

    # Cross-project mismatch protection
    effective_project_id = proposal.project_id or project_id
    if project_id and proposal.project_id and project_id != proposal.project_id:
        raise CrossProjectMismatchError(
            f"Cannot derive grant: project_id '{project_id}' != proposal project_id '{proposal.project_id}'."
        )

    effective_repository_id = proposal.repository_id or repository_id
    if repository_id and proposal.repository_id and repository_id != proposal.repository_id:
        raise CrossProjectMismatchError(
            f"Cannot derive grant: repository_id '{repository_id}' != proposal repository_id '{proposal.repository_id}'."
        )

    cleaned_approval = founder_approval_id.strip()
    grant_id = f"grant_apply_{uuid.uuid4().hex[:8]}"

    return RealRepoApplyGrant(
        schema_version="1.0",
        grant_id=grant_id,
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal.proposal_sha256,
        target_repository_root=proposal.target_repository_root,
        expected_head_hash=proposal.target_head_hash,
        code_patch_artifact_id=proposal.code_patch_artifact_id,
        code_patch_sha256=proposal.code_patch_sha256,
        qa_execution_report_artifact_id=proposal.qa_execution_report_artifact_id,
        qa_execution_report_sha256=proposal.qa_execution_report_sha256,
        expected_changed_files=proposal.expected_changed_files,
        human_approval_id=cleaned_approval,
        approver=approver,
        approved_at=_utc_now_iso(),
        status="ISSUED",
        validity_duration_seconds=validity_duration_seconds,
        project_id=effective_project_id,
        repository_id=effective_repository_id,
    )


# ==============================================================================
# Non-Mutating Precheck & Transactional Execution Primitives
# ==============================================================================

def precheck_code_patch_applicability(repo_root: Path, patch_text: str) -> None:
    """Perform non-mutating applicability preflight check via git apply --check."""
    if not patch_text or not patch_text.strip():
        raise PatchPrecheckFailedError("Cannot precheck empty CODE_PATCH text.")

    # Normalize to LF and write in binary mode to prevent Windows newline translation
    normalized_patch = patch_text.replace("\r\n", "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".patch", delete=False) as f:
        f.write(normalized_patch)
        temp_patch_path = Path(f.name)

    try:
        code, stdout, stderr = run_git(
            ["-c", "core.hooksPath=/dev/null", "apply", "--check", "--whitespace=nowarn", "--ignore-whitespace", str(temp_patch_path)],
            cwd=repo_root,
        )
        if code != 0:
            err_msg = stderr.strip() or stdout.strip()
            raise PatchPrecheckFailedError(f"Patch applicability preflight check failed (exit {code}): {err_msg}")
    finally:
        temp_patch_path.unlink(missing_ok=True)


def apply_code_patch_to_real_repo(repo_root: Path, patch_text: str) -> None:
    """Deterministically apply CODE_PATCH to real repository working tree via git apply (shell=False)."""
    normalized_patch = patch_text.replace("\r\n", "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".patch", delete=False) as f:
        f.write(normalized_patch)
        temp_patch_path = Path(f.name)

    try:
        code, stdout, stderr = run_git(
            ["-c", "core.hooksPath=/dev/null", "apply", "--whitespace=nowarn", "--ignore-whitespace", str(temp_patch_path)],
            cwd=repo_root,
        )
        if code != 0:
            err_msg = stderr.strip() or stdout.strip()
            raise PatchApplyFailedError(f"Real repository patch apply failed (exit {code}): {err_msg}")
    finally:
        temp_patch_path.unlink(missing_ok=True)


def validate_real_repo_diff(
    repo_root: Path,
    expected_files: Tuple[str, ...],
) -> List[str]:
    """Validate that actual modified/untracked files in real repo match expected changed files."""
    code, status_out, status_err = run_git(["status", "--porcelain"], cwd=repo_root)
    if code != 0:
        raise PostApplyDiffMismatchError(f"Failed to inspect working tree status after apply: {status_err.strip()}")

    actual_changed: List[str] = []
    untracked_files: List[str] = []
    deleted_files: List[str] = []

    for line in status_out.splitlines():
        line = line.rstrip()
        if not line:
            continue
        status_code = line[:2]
        filename = line[3:].strip()
        norm_fn = filename.replace("\\", "/").lower()

        # Ignore internal company artifacts if repo is the engine repo
        if norm_fn == ".agents" or norm_fn.startswith(".agents/") or norm_fn == ".runs" or norm_fn.startswith(".runs/"):
            continue

        if status_code == "??":
            untracked_files.append(norm_fn)
            actual_changed.append(norm_fn)
        elif "D" in status_code:
            deleted_files.append(norm_fn)
            actual_changed.append(norm_fn)
        else:
            actual_changed.append(norm_fn)

    expected_set = {Path(f).as_posix().lstrip("/").lower() for f in expected_files}
    actual_set = set(actual_changed)

    extra_files = actual_set - expected_set
    if extra_files:
        raise PostApplyDiffMismatchError(f"Real repository contains unexpected changed file(s): {sorted(extra_files)}")

    missing_files = expected_set - actual_set
    if missing_files:
        raise PostApplyDiffMismatchError(f"Real repository is missing expected changed file(s): {sorted(missing_files)}")

    if deleted_files:
        raise PostApplyDiffMismatchError(f"Unexpected file deletion(s) detected in real repository: {sorted(deleted_files)}")

    return actual_changed


def rollback_real_repo_apply(
    repo_root: Path,
    patch_text: str,
    expected_files: Tuple[str, ...],
    allow_untracked: bool = False,
) -> None:
    """Safely restore the real repository to exact clean pre-apply state (Principles 5 & 6).

    Uses exact reverse patch apply as primary rollback without dangerous git reset --hard
    or git clean -fd.
    """
    logger.info("Initiating targeted safe rollback for repository '%s'", repo_root)

    normalized_patch = patch_text.replace("\r\n", "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".patch", delete=False) as f:
        f.write(normalized_patch)
        temp_patch_path = Path(f.name)

    try:
        # 1. Primary rollback: git apply --reverse
        code, stdout, stderr = run_git(
            ["-c", "core.hooksPath=/dev/null", "apply", "--reverse", "--whitespace=nowarn", "--ignore-whitespace", str(temp_patch_path)],
            cwd=repo_root,
        )
        if code != 0:
            logger.warning("Primary reverse patch apply failed (%s): %s. Attempting targeted per-file restore.", code, stderr)

        # Ensure any newly created files that did not exist in HEAD are removed
        for rel_path in expected_files:
            target_file = repo_root / rel_path
            cat_code, _, _ = run_git(["cat-file", "-e", f"HEAD:{rel_path}"], cwd=repo_root)
            if cat_code != 0 and target_file.is_file():
                target_file.unlink(missing_ok=True)

        # 2. Check clean state; if not clean, perform targeted checkout on expected files
        is_clean, status_out = verify_target_repo_cleanliness(repo_root, allow_untracked=allow_untracked)
        if not is_clean:
            logger.warning("Working tree not fully clean after reverse apply. Performing targeted checkout on expected files.")
            for rel_path in expected_files:
                target_file = repo_root / rel_path
                cat_code, _, _ = run_git(["cat-file", "-e", f"HEAD:{rel_path}"], cwd=repo_root)
                if cat_code == 0:
                    run_git(["-c", "core.hooksPath=/dev/null", "checkout", "HEAD", "--", rel_path], cwd=repo_root)
                else:
                    if target_file.is_file():
                        target_file.unlink(missing_ok=True)
            is_clean, status_out = verify_target_repo_cleanliness(repo_root, allow_untracked=allow_untracked)

        if not is_clean:
            raise RollbackFailedError(
                f"CRITICAL: Rollback failed to restore clean repository state in '{repo_root}'.\n"
                f"Remaining status:\n{status_out}"
            )
        logger.info("Targeted rollback succeeded. Repository '%s' restored to 100% clean state.", repo_root)

    finally:
        temp_patch_path.unlink(missing_ok=True)


# ==============================================================================
# Crash Recovery State Classifier (Principles 3 & 4)
# ==============================================================================

def classify_crash_state(
    repo_root: Path,
    patch_text: str,
    expected_files: Tuple[str, ...],
    allow_untracked: bool = False,
) -> CrashStateClassification:
    """Classify repository state to detect incomplete or crashed transactions."""
    is_clean, _ = verify_target_repo_cleanliness(repo_root, allow_untracked=allow_untracked)
    if is_clean:
        return CrashStateClassification.NOT_APPLIED

    try:
        actual_files = validate_real_repo_diff(repo_root, expected_files)
        if set(actual_files) == {Path(f).as_posix().lstrip("/").lower() for f in expected_files}:
            return CrashStateClassification.EXACT_APPROVED_PATCH_PRESENT
    except PostApplyDiffMismatchError:
        pass

    return CrashStateClassification.PARTIAL_OR_UNKNOWN_STATE


# ==============================================================================
# Report Formatters
# ==============================================================================

def format_real_repo_apply_proposal_report(proposal: RealRepoApplyProposal) -> str:
    """Format human-readable review report for RealRepoApplyProposal."""
    files_list = "\n".join(f"- `{f}`" for f in proposal.expected_changed_files)
    return (
        f"# Real Repository Apply Proposal\n\n"
        f"**Proposal ID:** `{proposal.proposal_id}`  \n"
        f"**Proposal SHA-256:** `{proposal.proposal_sha256}`  \n"
        f"**Created At:** {proposal.created_at}  \n\n"
        f"## Target Repository\n\n"
        f"- **Path:** `{proposal.target_repository_root}`\n"
        f"- **Branch:** `{proposal.target_branch}`\n"
        f"- **HEAD Commit:** `{proposal.target_head_hash}`\n"
        f"- **Cleanliness:** {'CLEAN (git status --porcelain is empty)' if proposal.is_clean else 'DIRTY'}\n\n"
        f"## Candidate Patch\n\n"
        f"- **CODE_PATCH Artifact ID:** `{proposal.code_patch_artifact_id}`\n"
        f"- **CODE_PATCH SHA-256:** `{proposal.code_patch_sha256}`\n"
        f"- **Patch Version:** v{proposal.patch_version}\n"
        f"- **Base Commit:** `{proposal.base_commit_hash}`\n"
        f"- **Files Changed:** {proposal.expected_diff_stat.get('files_changed', 0)}\n"
        f"- **Insertions / Deletions:** +{proposal.expected_diff_stat.get('insertions', 0)} / -{proposal.expected_diff_stat.get('deletions', 0)}\n\n"
        f"### Files to Modify / Create\n\n{files_list}\n\n"
        f"## QA Verification Evidence\n\n"
        f"- **QA_REPORT Artifact ID:** `{proposal.qa_report_artifact_id}`\n"
        f"- **QA_EXECUTION_REPORT Artifact ID:** `{proposal.qa_execution_report_artifact_id}`\n"
        f"- **Final QA Verdict:** **{proposal.qa_verdict}**\n\n"
        f"> [!IMPORTANT]\n"
        f"> **Human Decision Gate:** This proposal is NOT authorization to mutate the repository. "
        f"Real repository mutation will occur ONLY upon your explicit approval."
    )


def format_real_repo_apply_report(task: Task, result: RealRepoApplyResult) -> str:
    """Format durable receipt artifact for REAL_REPO_APPLY_REPORT."""
    files_list = "\n".join(f"- `{f}`" for f in result.actual_files) or "None"
    return (
        f"# Real Repository Apply Report\n\n"
        f"**Transaction Status:** **{result.status}**  \n"
        f"**Grant ID:** `{result.grant_id}`  \n"
        f"**Proposal ID:** `{result.proposal_id}`  \n"
        f"**Target Repository:** `{result.target_repository_root}`  \n"
        f"**Timestamp:** {result.applied_at}  \n"
        f"**Duration:** {result.duration_ms:.2f} ms  \n\n"
        f"## Execution Summary\n\n"
        f"{result.summary}\n\n"
        f"## Git State\n\n"
        f"- **Pre-Apply HEAD:** `{result.pre_apply_head}`\n"
        f"- **Post-Apply HEAD:** `{result.post_apply_head}`\n\n"
        f"## Changed Files\n\n"
        f"{files_list}\n\n"
        f"## Status & Notes\n\n"
        f"- **Error:** {result.error or 'None'}\n"
    )
