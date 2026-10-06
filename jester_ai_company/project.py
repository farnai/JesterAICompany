"""Generic Project and Repository Foundation for Jester AI Company.

Provides clean, typed domain abstractions for external software Projects,
Repository identity, Repository access policies, runtime state fingerprints,
and Project registration.

CRITICAL INVARIANTS:
1. JesterAICompany Core remains generic (zero product-specific hardcoding).
2. Exactly one primary repository per Project in V1.
3. Logical repository identity is repository_id under a Project (filesystem root is configuration).
4. RepositoryPolicy defines maximum project authority; ExecutionGrant defines narrower task authority.
5. DENIED paths always take precedence over ALLOWED paths (fail-closed).
6. Project registration and authority belong strictly to the Human / Application layer.
7. Validation performs ZERO mutating Git operations.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from .worktree import resolve_repo_head_commit, run_git, verify_workspace_path


# ==============================================================================
# Domain Exceptions
# ==============================================================================

class ProjectError(Exception):
    """Base exception for all Project and Repository domain errors."""
    pass


class ProjectNotFoundError(ProjectError):
    """Raised when a requested project_id is not registered."""
    pass


class ProjectValidationError(ProjectError):
    """Raised when a Project, RepositoryRef, or Policy fails schema validation."""
    pass


class RepositoryValidationError(ProjectError):
    """Raised when a repository path fails inspection or Git validation."""
    pass


class PolicyViolationError(ProjectError):
    """Raised when an operation or path violates the Project RepositoryPolicy."""
    pass


class CrossProjectMismatchError(ProjectError):
    """Raised when an artifact, proposal, or grant targets the wrong Project."""
    pass


class DuplicateProjectError(ProjectError):
    """Raised when attempting to register a duplicate project_id."""
    pass


class DuplicateRepositoryError(ProjectError):
    """Raised when attempting to register a duplicate repository_id ambiguously."""
    pass


class TargetRepositoryMismatchError(ProjectError):
    """Raised when target repository does not match expected project repository identity."""
    pass


# ==============================================================================
# Helper Utilities
# ==============================================================================

def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_rel_path(path: str) -> str:
    """Normalize a relative path string using forward slashes and stripped whitespace."""
    if not path or not isinstance(path, str):
        raise ProjectValidationError("Path must be a non-empty string.")
    cleaned = path.strip().replace("\\", "/")
    # Disallow parent directory traversal
    parts = [p for p in cleaned.split("/") if p]
    if ".." in parts:
        raise PolicyViolationError(f"Directory traversal '..' forbidden in path: '{path}'.")
    # Disallow absolute or drive-qualified paths
    if cleaned.startswith("/") or ":" in cleaned:
        raise PolicyViolationError(f"Absolute or drive-qualified path forbidden: '{path}'.")
    return "/".join(parts)


def _path_matches_pattern(normalized_path: str, pattern: str) -> bool:
    """Check whether a normalized relative path matches a policy pattern.
    
    Supports:
    - exact matches ("README.md")
    - wildcards ("*.py", "config/*.yaml")
    - directory prefix matches ("backend/**", "tests/*")
    - directory component match (".git" matches any path inside .git/)
    """
    norm_pat = pattern.strip().replace("\\", "/")
    if not norm_pat:
        return False
    if norm_pat == "**":
        return True

    # Check whole path against pattern
    if fnmatch.fnmatch(normalized_path, norm_pat):
        return True

    # Directory wildcard patterns: "dir/**" or "dir/*"
    if norm_pat.endswith("/**"):
        prefix = norm_pat[:-3]
        if normalized_path == prefix or normalized_path.startswith(prefix + "/"):
            return True
    elif norm_pat.endswith("/*"):
        prefix = norm_pat[:-2]
        if normalized_path == prefix or normalized_path.startswith(prefix + "/"):
            # Only match direct children (no deeper slashes after prefix)
            rest = normalized_path[len(prefix) + 1:]
            if "/" not in rest:
                return True

    # Direct directory match: if pattern has no slashes, match individual components
    if "/" not in norm_pat:
        parts = normalized_path.split("/")
        if any(fnmatch.fnmatch(p, norm_pat) for p in parts):
            return True

    return False


# ==============================================================================
# RepositoryRef
# ==============================================================================

@dataclass(frozen=True)
class RepositoryRef:
    """Immutable configured repository identity.
    
    Represents CONFIGURATION, not dynamic runtime state.
    """
    repository_id: str
    root_path: str
    target_branch: str = "main"
    expected_remote: Optional[str] = None
    allow_untracked: bool = False

    def __post_init__(self) -> None:
        if not self.repository_id or not isinstance(self.repository_id, str) or not self.repository_id.strip():
            raise ProjectValidationError("RepositoryRef 'repository_id' must be a non-empty string.")
        if not self.root_path or not isinstance(self.root_path, str) or not self.root_path.strip():
            raise ProjectValidationError("RepositoryRef 'root_path' must be a non-empty string.")
        if not self.target_branch or not isinstance(self.target_branch, str) or not self.target_branch.strip():
            raise ProjectValidationError("RepositoryRef 'target_branch' must be a non-empty string.")

        # Canonicalize root_path to absolute POSIX format
        canonical = Path(self.root_path.strip()).resolve().as_posix()
        object.__setattr__(self, "root_path", canonical)
        object.__setattr__(self, "repository_id", self.repository_id.strip())
        object.__setattr__(self, "target_branch", self.target_branch.strip())
        if self.expected_remote:
            object.__setattr__(self, "expected_remote", self.expected_remote.strip())
        object.__setattr__(self, "allow_untracked", bool(self.allow_untracked))

    @property
    def canonical_root(self) -> Path:
        """Return canonical resolved Path object."""
        return Path(self.root_path)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize RepositoryRef to dictionary."""
        return {
            "repository_id": self.repository_id,
            "root_path": self.root_path,
            "target_branch": self.target_branch,
            "expected_remote": self.expected_remote,
            "allow_untracked": self.allow_untracked,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryRef":
        """Deserialize RepositoryRef with fail-closed validation."""
        if not isinstance(data, dict):
            raise ProjectValidationError("Expected dictionary for RepositoryRef.")
        return cls(
            repository_id=data.get("repository_id", ""),
            root_path=data.get("root_path", ""),
            target_branch=data.get("target_branch", "main"),
            expected_remote=data.get("expected_remote"),
            allow_untracked=bool(data.get("allow_untracked", False)),
        )


# ==============================================================================
# RepositoryStateFingerprint
# ==============================================================================

@dataclass(frozen=True)
class RepositoryStateFingerprint:
    """Immutable snapshot of observed runtime repository state.
    
    Represents observed RUNTIME state, not configured identity.
    """
    repository_id: str
    root_path: str
    branch: str
    head_commit: str
    is_clean: bool
    state_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.state_sha256:
            raw = f"{self.repository_id}:{self.root_path}:{self.head_commit}:{self.branch}:{self.is_clean}"
            sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            object.__setattr__(self, "state_sha256", sha)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize fingerprint to dictionary."""
        return {
            "repository_id": self.repository_id,
            "root_path": self.root_path,
            "branch": self.branch,
            "head_commit": self.head_commit,
            "is_clean": self.is_clean,
            "state_sha256": self.state_sha256,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryStateFingerprint":
        """Deserialize fingerprint from dictionary."""
        if not isinstance(data, dict):
            raise ProjectValidationError("Expected dictionary for RepositoryStateFingerprint.")
        return cls(
            repository_id=str(data.get("repository_id", "")),
            root_path=str(data.get("root_path", "")),
            branch=str(data.get("branch", "")),
            head_commit=str(data.get("head_commit", "")),
            is_clean=bool(data.get("is_clean", False)),
            state_sha256=str(data.get("state_sha256", "")),
        )


def inspect_repository_state(repo_ref: RepositoryRef) -> RepositoryStateFingerprint:
    """Perform deterministic, read-only inspection of a target Git repository.
    
    PERFORMS ZERO MUTATING OPERATIONS.
    """
    root = repo_ref.canonical_root
    if not root.exists():
        raise RepositoryValidationError(f"Repository root does not exist: '{root}'.")
    if not root.is_dir():
        raise RepositoryValidationError(f"Repository root is not a directory: '{root}'.")

    git_dir = root / ".git"
    if not git_dir.exists():
        raise RepositoryValidationError(f"Directory is not a Git repository (no .git): '{root}'.")

    # Verify Git top-level matches expected root (prevents submodule/nested confusion)
    code, toplevel_out, err = run_git(["rev-parse", "--show-toplevel"], cwd=root)
    if code != 0:
        raise RepositoryValidationError(f"Failed to inspect git repository top-level: {err.strip()}")
    observed_toplevel = Path(toplevel_out.strip()).resolve()
    if observed_toplevel != root:
        raise RepositoryValidationError(
            f"Git top-level mismatch: observed '{observed_toplevel}' != configured '{root}'."
        )

    # Resolve HEAD commit
    head = resolve_repo_head_commit(root)

    # Determine current branch
    code, branch_out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    branch = branch_out.strip() if code == 0 else "DETACHED"

    # Determine cleanliness
    code, stat_out, _ = run_git(["status", "--porcelain"], cwd=root)
    code_tr, tracked_out, _ = run_git(["status", "--porcelain", "--untracked-files=no"], cwd=root)
    if repo_ref.allow_untracked:
        is_clean = (code_tr == 0 and tracked_out.strip() == "")
    else:
        is_clean = (code == 0 and stat_out.strip() == "")

    return RepositoryStateFingerprint(
        repository_id=repo_ref.repository_id,
        root_path=root.as_posix(),
        branch=branch,
        head_commit=head,
        is_clean=is_clean,
    )


# ==============================================================================
# Target Repository Identity Guard (STEP 19D TARGET CORRECTION)
# ==============================================================================

@dataclass(frozen=True)
class TargetRepositoryVerification:
    """Deterministic verification record of target repository identity and safety."""
    project_id: str
    project_name: str
    repository_root: str
    repository_head: str
    branch: str
    working_tree_state: str
    remote_url: Optional[str] = None
    is_valid: bool = True
    verified_at: str = field(default_factory=_utc_now_iso)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "repository_root": self.repository_root,
            "repository_head": self.repository_head,
            "branch": self.branch,
            "working_tree_state": self.working_tree_state,
            "remote_url": self.remote_url,
            "is_valid": self.is_valid,
            "verified_at": self.verified_at,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TargetRepositoryVerification":
        return cls(
            project_id=str(data.get("project_id", "")),
            project_name=str(data.get("project_name", "")),
            repository_root=str(data.get("repository_root", "")),
            repository_head=str(data.get("repository_head", "")),
            branch=str(data.get("branch", "")),
            working_tree_state=str(data.get("working_tree_state", "")),
            remote_url=data.get("remote_url"),
            is_valid=bool(data.get("is_valid", True)),
            verified_at=str(data.get("verified_at", "")),
            details=dict(data.get("details", {})),
        )


def verify_target_repository_identity(
    project: Project,
    candidate_repo_path: Optional[Union[str, Path]] = None,
    expected_head: Optional[str] = None,
    expected_branch: Optional[str] = None,
    expected_remote: Optional[str] = None,
    require_clean: bool = False,
) -> TargetRepositoryVerification:
    """Fail-closed verification of target repository identity before any live company run.

    Enforces:
    1. Canonicalized filesystem root matching between registered Project and candidate path.
    2. Zero acceptance of scratch/shadow repositories (e.g. scratch\\jester, scratch\\JesteChat).
    3. Git remote verification against authoritative repository remote (e.g. farnai/Jester.git).
    4. Authoritative repository identity markers on disk (e.g. docs/JESTER_PRODUCT_FOUNDATION.md).
    5. Git top-level alignment and branch / HEAD resolution.
    6. Exposure of Project ID, Project Name, Repository Root, Repository HEAD, Branch, Working Tree State.
    """
    if not isinstance(project, Project):
        raise ProjectValidationError("Expected Project instance for repository identity verification.")

    repo_root = project.repository.canonical_root
    if not repo_root.exists():
        raise TargetRepositoryMismatchError(f"Target repository root does not exist on disk: '{repo_root}'.")
    if not repo_root.is_dir():
        raise TargetRepositoryMismatchError(f"Target repository root is not a directory: '{repo_root}'.")

    # 1. Candidate path alignment check
    if candidate_repo_path is not None:
        cand_resolved = Path(candidate_repo_path).resolve()
        if cand_resolved != repo_root:
            raise TargetRepositoryMismatchError(
                f"Candidate repository '{cand_resolved}' does not match registered Project '{project.project_id}' "
                f"repository root '{repo_root}'."
            )

    # 2. Check Git repository validity
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        raise TargetRepositoryMismatchError(f"Directory is not a Git repository (no .git): '{repo_root}'.")

    code, toplevel_out, err = run_git(["rev-parse", "--show-toplevel"], cwd=repo_root)
    if code != 0:
        raise TargetRepositoryMismatchError(f"Failed to inspect git repository top-level: {err.strip()}")
    observed_toplevel = Path(toplevel_out.strip()).resolve()
    if observed_toplevel != repo_root:
        raise TargetRepositoryMismatchError(
            f"Git top-level mismatch: observed '{observed_toplevel}' != configured '{repo_root}'."
        )

    # 3. Resolve Git Remote
    code, remotes_out, _ = run_git(["remote", "-v"], cwd=repo_root)
    remote_text = remotes_out.strip() if code == 0 else ""

    # 4. Anti-Shadow / Scratch Defense (Prevents scratch/jester, scratch/JesteChat, etc.)
    posix_path = repo_root.as_posix().lower()
    root_parts = [p.lower() for p in repo_root.parts]

    # Universal check: if project_id is prj_jester, NEVER allow scratch shadows or JesteChat
    if project.project_id == "prj_jester":
        # Disallow any scratch directory or JesteChat
        if "/scratch/jester" in posix_path or "/scratch/jestechat" in posix_path or "scratch" in root_parts or "jestechat" in root_parts:
            raise TargetRepositoryMismatchError(
                f"REJECTED: '{repo_root}' is a scratch shadow repository, not the authoritative Jester project."
            )
        # Disallow JesterAI.git remote (scratch repo remote)
        if "jesterai.git" in remote_text.lower():
            raise TargetRepositoryMismatchError(
                f"REJECTED: Repository remote '{remote_text}' points to JesterAI.git, not authoritative farnai/Jester.git."
            )
        # Check required authoritative remote
        authoritative_remote = expected_remote or project.repository.expected_remote or "farnai/jester"
        if authoritative_remote.lower() not in remote_text.lower():
            raise TargetRepositoryMismatchError(
                f"REJECTED: Repository remote does not contain expected authoritative remote '{authoritative_remote}'. "
                f"Found: '{remote_text}'."
            )
        # Check required authoritative repository markers
        if not (repo_root / "docs" / "JESTER_PRODUCT_FOUNDATION.md").is_file():
            raise TargetRepositoryMismatchError(
                f"REJECTED: Authoritative marker 'docs/JESTER_PRODUCT_FOUNDATION.md' missing in '{repo_root}'."
            )
        if not (repo_root / "backend" / "app" / "main.py").is_file():
            raise TargetRepositoryMismatchError(
                f"REJECTED: Authoritative marker 'backend/app/main.py' missing in '{repo_root}'."
            )

    # 5. Generic expected_remote check if set on RepositoryRef
    if project.repository.expected_remote and project.repository.expected_remote.lower() not in remote_text.lower():
        raise TargetRepositoryMismatchError(
            f"Repository remote does not match expected_remote '{project.repository.expected_remote}'. Observed: '{remote_text}'."
        )

    # 6. Resolve HEAD and Branch
    head = resolve_repo_head_commit(repo_root)
    if expected_head and head != expected_head:
        raise TargetRepositoryMismatchError(
            f"Repository HEAD '{head}' does not match expected commit '{expected_head}'."
        )

    code, branch_out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    branch = branch_out.strip() if code == 0 else "DETACHED"
    if expected_branch and branch != expected_branch and branch != "DETACHED":
        raise TargetRepositoryMismatchError(
            f"Repository branch '{branch}' does not match expected branch '{expected_branch}'."
        )

    # 7. Working tree state
    code, stat_out, _ = run_git(["status", "--porcelain"], cwd=repo_root)
    code_tr, tracked_out, _ = run_git(["status", "--porcelain", "--untracked-files=no"], cwd=repo_root)
    lines = [l for l in stat_out.strip().splitlines() if l.strip()]
    tracked_mods = [l for l in tracked_out.strip().splitlines() if l.strip()]
    untracked_files = [l for l in lines if l.startswith("??")]

    if not lines:
        wt_state = "CLEAN"
    elif not tracked_mods:
        wt_state = f"CLEAN_TRACKED ({len(untracked_files)} untracked files)"
    else:
        wt_state = f"DIRTY ({len(tracked_mods)} modified, {len(untracked_files)} untracked)"

    if require_clean:
        if tracked_mods:
            raise TargetRepositoryMismatchError(f"Target repository working tree has tracked modifications: {wt_state}.")
        if not getattr(project.repository, "allow_untracked", False) and wt_state != "CLEAN":
            raise TargetRepositoryMismatchError(f"Target repository working tree is not clean: {wt_state}.")

    return TargetRepositoryVerification(
        project_id=project.project_id,
        project_name=project.name,
        repository_root=repo_root.as_posix(),
        repository_head=head,
        branch=branch,
        working_tree_state=wt_state,
        remote_url=remote_text,
        is_valid=True,
        details={
            "tracked_changes_count": len(tracked_mods),
            "untracked_files_count": len(untracked_files),
            "canonical_root": str(repo_root),
        },
    )


# ==============================================================================
# RepositoryPolicy
# ==============================================================================

DEFAULT_DENIED_PATTERNS: Tuple[str, ...] = (
    ".git",
    ".git/**",
    ".env*",
    "*.env",
    "*credential*",
    "*secret*",
    "*.key",
    "*.pem",
    ".pytest_cache",
    ".pytest_cache/**",
    "__pycache__",
    "__pycache__/**",
)


@dataclass(frozen=True)
class RepositoryPolicy:
    """Immutable policy governing read and mutation access to a repository.
    
    Security Invariants:
    1. DENIED takes precedence over ALLOWED (fail-closed).
    2. Read permission does NOT imply mutation permission.
    3. Mutation permission does NOT bypass ExecutionGrant.
    4. Project policy is the coarse maximum boundary; ExecutionGrant is the fine task boundary.
    """
    read_allowed: Tuple[str, ...] = ("**",)
    mutation_allowed: Tuple[str, ...] = ()
    denied: Tuple[str, ...] = DEFAULT_DENIED_PATTERNS

    def __post_init__(self) -> None:
        # Normalize pattern collections to tuples of clean strings
        norm_read = tuple(str(p).strip() for p in self.read_allowed if str(p).strip())
        norm_mut = tuple(str(p).strip() for p in self.mutation_allowed if str(p).strip())
        norm_den = tuple(str(p).strip() for p in self.denied if str(p).strip())

        object.__setattr__(self, "read_allowed", norm_read)
        object.__setattr__(self, "mutation_allowed", norm_mut)
        object.__setattr__(self, "denied", norm_den)

    def is_denied(self, rel_path: str) -> bool:
        """Check if a path matches any denied pattern (fail-closed)."""
        norm = _normalize_rel_path(rel_path)
        return any(_path_matches_pattern(norm, pat) for pat in self.denied)

    def can_read(self, rel_path: str) -> bool:
        """Check if a path is readable under this policy.
        
        DENIED always takes precedence over ALLOWED.
        """
        norm = _normalize_rel_path(rel_path)
        if self.is_denied(norm):
            return False
        if not self.read_allowed:
            return False
        return any(_path_matches_pattern(norm, pat) for pat in self.read_allowed)

    def can_mutate(self, rel_path: str) -> bool:
        """Check if a path is mutable under this policy.
        
        DENIED always takes precedence over ALLOWED.
        """
        norm = _normalize_rel_path(rel_path)
        if self.is_denied(norm):
            return False
        if not self.mutation_allowed:
            return False
        return any(_path_matches_pattern(norm, pat) for pat in self.mutation_allowed)

    def validate_mutation_scope(self, rel_paths: Iterable[str]) -> None:
        """Validate that all paths in an approved mutation set pass policy.
        
        Raises PolicyViolationError immediately if any path is denied or not allowed.
        """
        for path in rel_paths:
            norm = _normalize_rel_path(path)
            if self.is_denied(norm):
                raise PolicyViolationError(
                    f"Path '{path}' is explicitly DENIED under RepositoryPolicy."
                )
            if not self.can_mutate(norm):
                raise PolicyViolationError(
                    f"Path '{path}' is not within authorized mutation_allowed scope under RepositoryPolicy."
                )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize policy to dictionary."""
        return {
            "read_allowed": list(self.read_allowed),
            "mutation_allowed": list(self.mutation_allowed),
            "denied": list(self.denied),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryPolicy":
        """Deserialize policy from dictionary."""
        if not isinstance(data, dict):
            raise ProjectValidationError("Expected dictionary for RepositoryPolicy.")
        return cls(
            read_allowed=tuple(data.get("read_allowed", ("**",))),
            mutation_allowed=tuple(data.get("mutation_allowed", ())),
            denied=tuple(data.get("denied", DEFAULT_DENIED_PATTERNS)),
        )


# ==============================================================================
# Project
# ==============================================================================

@dataclass(frozen=True)
class Project:
    """Immutable domain representation of an external software project.
    
    In V1, enforces exactly ONE primary repository per Project.
    """
    project_id: str
    name: str
    description: str = ""
    repository: RepositoryRef = field(default_factory=lambda: RepositoryRef("default", "."))
    policy: RepositoryPolicy = field(default_factory=RepositoryPolicy)
    status: str = "ACTIVE"
    created_at: str = field(default_factory=_utc_now_iso)

    def __post_init__(self) -> None:
        if not self.project_id or not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ProjectValidationError("Project 'project_id' must be a non-empty string.")
        if not self.name or not isinstance(self.name, str) or not self.name.strip():
            raise ProjectValidationError("Project 'name' must be a non-empty string.")
        if not isinstance(self.repository, RepositoryRef):
            raise ProjectValidationError("Project 'repository' must be a valid RepositoryRef instance.")
        if not isinstance(self.policy, RepositoryPolicy):
            raise ProjectValidationError("Project 'policy' must be a valid RepositoryPolicy instance.")

        object.__setattr__(self, "project_id", self.project_id.strip())
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "description", (self.description or "").strip())
        object.__setattr__(self, "status", (self.status or "ACTIVE").strip().upper())

    @property
    def id(self) -> str:
        """Compatibility alias for project_id."""
        return self.project_id

    @property
    def root_path(self) -> str:
        """Compatibility accessor for repository root path."""
        return self.repository.root_path

    @property
    def target_branch(self) -> str:
        """Compatibility accessor for configured target branch."""
        return self.repository.target_branch

    def to_dict(self) -> Dict[str, Any]:
        """Serialize Project to dictionary."""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "repository": self.repository.to_dict(),
            "policy": self.policy.to_dict(),
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        """Deserialize Project from dictionary."""
        if not isinstance(data, dict):
            raise ProjectValidationError("Expected dictionary for Project.")
        raw_repo = data.get("repository")
        if isinstance(raw_repo, dict):
            repo = RepositoryRef.from_dict(raw_repo)
        elif isinstance(raw_repo, RepositoryRef):
            repo = raw_repo
        else:
            raise ProjectValidationError("Project dictionary missing valid 'repository' object.")

        raw_policy = data.get("policy")
        if isinstance(raw_policy, dict):
            policy = RepositoryPolicy.from_dict(raw_policy)
        elif isinstance(raw_policy, RepositoryPolicy):
            policy = raw_policy
        else:
            policy = RepositoryPolicy()

        return cls(
            project_id=data.get("project_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            repository=repo,
            policy=policy,
            status=data.get("status", "ACTIVE"),
            created_at=data.get("created_at") or _utc_now_iso(),
        )


# ==============================================================================
# ProjectRegistry
# ==============================================================================

class ProjectRegistry:
    """Application-owned registry for managing registered Projects.
    
    Authority Invariant:
    Only Human / Application authority can register or reconfigure Projects.
    Agents (CEO, specialists) have zero authority to register or repoint Projects.
    """

    def __init__(self) -> None:
        self._projects: Dict[str, Project] = {}
        self._repos_by_id: Dict[str, str] = {}    # repo_id -> project_id
        self._roots_by_path: Dict[str, str] = {}  # canonical_root -> project_id

    def register_project(self, project: Project, validate_repo: bool = True) -> Project:
        """Register a new Project in the registry.
        
        Fails closed on duplicate project_id, duplicate repository_id pointing
        to different projects, or invalid repository state.
        """
        if not isinstance(project, Project):
            raise ProjectValidationError("Expected Project instance for registration.")

        pid = project.project_id
        rid = project.repository.repository_id
        canonical_root = project.repository.canonical_root.as_posix()

        # 1. Reject duplicate project_id
        if pid in self._projects:
            raise DuplicateProjectError(f"Project '{pid}' is already registered.")

        # 2. Reject duplicate repository_id assigned to a different project
        if rid in self._repos_by_id:
            existing_pid = self._repos_by_id[rid]
            if existing_pid != pid:
                raise DuplicateRepositoryError(
                    f"Repository '{rid}' is already registered under Project '{existing_pid}'."
                )

        # 3. Reject duplicate canonical root path assigned to a different project
        if canonical_root in self._roots_by_path:
            existing_pid = self._roots_by_path[canonical_root]
            if existing_pid != pid:
                raise DuplicateRepositoryError(
                    f"Repository root '{canonical_root}' is already registered under Project '{existing_pid}'."
                )

        # 4. Optional read-only repository validation
        if validate_repo:
            fingerprint = inspect_repository_state(project.repository)
            # Verify configured target_branch matches current branch or is a valid ref
            if fingerprint.branch != project.repository.target_branch and fingerprint.branch != "DETACHED":
                # Check if target_branch exists as a branch ref
                code, _, _ = run_git(
                    ["rev-parse", "--verify", project.repository.target_branch],
                    cwd=project.repository.canonical_root,
                )
                if code != 0:
                    raise RepositoryValidationError(
                        f"Configured target branch '{project.repository.target_branch}' does not exist in repository."
                    )

        # Store in registry
        self._projects[pid] = project
        self._repos_by_id[rid] = pid
        self._roots_by_path[canonical_root] = pid
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        """Retrieve a project by ID or None if not found."""
        return self._projects.get(project_id)

    def require_project(self, project_id: str) -> Project:
        """Retrieve a project by ID or raise ProjectNotFoundError."""
        proj = self.get_project(project_id)
        if not proj:
            raise ProjectNotFoundError(f"Project '{project_id}' is not registered.")
        return proj

    def list_projects(self) -> List[Project]:
        """Return all registered Projects."""
        return list(self._projects.values())

    def get_project_by_repository_id(self, repository_id: str) -> Optional[Project]:
        """Lookup project by repository ID."""
        pid = self._repos_by_id.get(repository_id)
        return self.get_project(pid) if pid else None

    def get_project_by_root_path(self, path: Union[str, Path]) -> Optional[Project]:
        """Lookup project by canonical filesystem root path."""
        canonical = Path(path).resolve().as_posix()
        pid = self._roots_by_path.get(canonical)
        return self.get_project(pid) if pid else None

    def clear(self) -> None:
        """Clear registry (primarily for test fixture isolation)."""
        self._projects.clear( )
        self._repos_by_id.clear()
        self._roots_by_path.clear()


# Global default registry instance
DEFAULT_PROJECT_REGISTRY = ProjectRegistry()


# ==============================================================================
# Policy ↔ ExecutionGrant Integration
# ==============================================================================

def validate_grant_against_project_policy(
    approved_files_to_modify: Iterable[str],
    approved_files_to_create: Iterable[str],
    policy: RepositoryPolicy,
) -> None:
    """Validate that an ExecutionGrant's mutation scope complies strictly with Project RepositoryPolicy.
    
    CRITICAL ARCHITECTURAL INVARIANT:
    ExecutionGrant mutation scope MUST be a subset of RepositoryPolicy mutation scope.
    Any path that is DENIED or not in mutation_allowed FAILS CLOSED.
    """
    all_mutation_targets = list(approved_files_to_modify) + list(approved_files_to_create)
    policy.validate_mutation_scope(all_mutation_targets)
