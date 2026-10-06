"""Git Worktree Lifecycle & Isolation Manager (STEP 13B-1).

Provides application-owned, deterministic Git worktree creation, inspection,
diff capture, and safe cleanup for isolated execution without mutating the
user's main working tree.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import fnmatch
import hashlib
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Set, Tuple

from .execution_grant import (
    ExecutionGrant,
    ProtectedPathError,
    StaleCommitError,
    TestModificationForbiddenError,
)

logger = logging.getLogger(__name__)


class WorktreeError(Exception):
    """Base exception for Git worktree errors."""
    pass


class WorktreeGitError(WorktreeError):
    """Raised when an application-owned git command fails."""
    pass


class WorktreeConfinementError(WorktreeError):
    """Raised when a path escapes the isolated workspace boundary."""
    pass


# Default protected patterns across any repository
BASE_PROTECTED_PATTERNS: List[str] = [
    ".git",
    ".git/**",
    ".agents",
    ".agents/**",
    ".env",
    ".env.*",
    "*.env",
    "*credentials*",
    "*secrets*",
    "*.pem",
    "*.key",
]

# Company-control repository patterns (protected when operating on JesterAICompany itself)
COMPANY_CONTROL_PATTERNS: List[str] = [
    "jester_ai_company",
    "jester_ai_company/**",
]

# Secret variable patterns for environment sanitization
SECRET_ENV_PATTERNS: List[re.Pattern] = [
    re.compile(r"^.*_KEY$", re.IGNORECASE),
    re.compile(r"^.*_TOKEN$", re.IGNORECASE),
    re.compile(r"^.*_SECRET$", re.IGNORECASE),
    re.compile(r"^AWS_.*$", re.IGNORECASE),
    re.compile(r"^GITHUB_.*$", re.IGNORECASE),
    re.compile(r"^OPENAI_.*$", re.IGNORECASE),
    re.compile(r"^ANTHROPIC_.*$", re.IGNORECASE),
    re.compile(r"^GEMINI_.*$", re.IGNORECASE),
    re.compile(r"^API_.*$", re.IGNORECASE),
    re.compile(r"^CREDENTIALS_.*$", re.IGNORECASE),
    re.compile(r"^.*PASSWORD.*$", re.IGNORECASE),
    re.compile(r"^AUTH_.*$", re.IGNORECASE),
]

# Safe system environment variables preserved during sanitization
SAFE_ENV_ALLOWLIST: Set[str] = {
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "PATH",
    "PYTHONPATH",
    "PYTHONHOME",
    "LANG",
    "LC_ALL",
    "USER",
    "USERNAME",
    "HOME",
    "USERPROFILE",
    "VIRTUAL_ENV",
}


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def run_git(args: List[str], cwd: Path, timeout: float = 30.0) -> Tuple[int, str, str]:
    """Execute an application-owned git command using an argument array (shell=False)."""
    cmd = ["git", "-c", "core.longpaths=true"] + args
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        raise WorktreeGitError(f"Git command '{' '.join(args)}' timed out after {timeout}s.") from exc
    except Exception as exc:
        raise WorktreeGitError(f"Failed to execute git command '{' '.join(args)}': {exc}") from exc


def resolve_repo_head_commit(repo_root: Path) -> str:
    """Resolve current HEAD commit hash using application-owned Git."""
    exit_code, stdout, stderr = run_git(["rev-parse", "HEAD"], cwd=repo_root)
    if exit_code != 0:
        raise WorktreeGitError(f"Failed to resolve git HEAD commit in '{repo_root}': {stderr.strip()}")
    commit = stdout.strip()
    if not commit or len(commit) < 7:
        raise WorktreeGitError(f"Invalid git HEAD commit returned: '{commit}'.")
    return commit


def is_protected_path(rel_path: str, protect_company_control: bool = False) -> bool:
    """Determine whether a relative path matches protected file policies."""
    norm = Path(rel_path).as_posix().lstrip("/")
    while norm.startswith("./") or norm.startswith(".\\"):
        norm = norm[2:]
    norm = norm.rstrip("/")

    patterns = list(BASE_PROTECTED_PATTERNS)
    if protect_company_control:
        patterns.extend(COMPANY_CONTROL_PATTERNS)

    for pat in patterns:
        if fnmatch.fnmatch(norm, pat):
            return True
        first_segment = norm.split("/")[0]
        if fnmatch.fnmatch(first_segment, pat):
            return True
        if pat.endswith("/**") and (norm == pat[:-3] or norm.startswith(pat[:-3] + "/")):
            return True
        if pat.endswith("/*") and (norm == pat[:-2] or norm.startswith(pat[:-2] + "/")):
            return True
    return False


def is_test_file(rel_path: str) -> bool:
    """Determine whether a relative path matches test file conventions."""
    norm = Path(rel_path).as_posix()
    filename = Path(norm).name
    parts = Path(norm).parts

    if "tests" in parts or "test" in parts:
        return True
    if filename.startswith("test_") or filename.endswith("_test.py"):
        return True
    if filename.endswith(".spec.ts") or filename.endswith(".test.js") or filename.endswith(".test.ts"):
        return True
    return False


def verify_workspace_path(rel_path: str, workspace_root: Path) -> Path:
    """Verify that a relative path strictly resolves inside the workspace root without escape."""
    if not rel_path or not isinstance(rel_path, str):
        raise WorktreeConfinementError("Path must be a non-empty string.")

    cleaned = rel_path.strip()
    p = Path(cleaned)

    # 1. Reject absolute or drive-relative paths
    if p.is_absolute() or ":" in cleaned:
        raise WorktreeConfinementError(f"Path '{cleaned}' is absolute or drive-qualified.")

    # 2. Reject parent traversal markers
    if ".." in p.parts:
        raise WorktreeConfinementError(f"Path '{cleaned}' contains directory traversal '..'.")

    # 3. Resolve target path
    root_resolved = workspace_root.resolve()
    target = (root_resolved / p).resolve()

    # 4. Check confinement
    if not target.is_relative_to(root_resolved):
        raise WorktreeConfinementError(f"Path '{cleaned}' escapes workspace root '{root_resolved}'.")

    # 5. Check symlinks or junctions
    if target.is_symlink() or os.path.islink(str(target)):
        raise WorktreeConfinementError(f"Path '{cleaned}' is a symlink or junction, which is forbidden.")

    return target


def sanitize_execution_environment(base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Sanitize environment variables for isolated execution, stripping secret-like variables."""
    source_env = dict(base_env if base_env is not None else os.environ)
    clean_env: Dict[str, str] = {}

    for k, v in source_env.items():
        k_upper = k.upper()
        # 1. Check against secret patterns
        is_secret = any(pat.match(k_upper) for pat in SECRET_ENV_PATTERNS)
        if is_secret:
            continue

        # 2. Check safe allowlist or general non-secret vars
        if k_upper in SAFE_ENV_ALLOWLIST or k_upper.startswith("PYTHON") or k_upper.startswith("PYTEST"):
            clean_env[k] = v

    return clean_env


@dataclass
class WorktreeDiffResult:
    """Represents the independently captured git diff of an isolated worktree."""
    diff_text: str
    diff_bytes: bytes
    diff_sha256: str
    changed_files: List[str]
    untracked_files: List[str]
    is_empty: bool
    deleted_files: List[str] = field(default_factory=list)
    is_binary: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialize diff result to dictionary."""
        return {
            "diff_text": self.diff_text,
            "diff_sha256": self.diff_sha256,
            "changed_files": self.changed_files,
            "untracked_files": self.untracked_files,
            "deleted_files": self.deleted_files,
            "is_empty": self.is_empty,
            "is_binary": self.is_binary,
        }


@dataclass
class WorktreeAuditRecord:
    """Audit record capturing the lifecycle of an isolated worktree execution."""
    grant_id: str
    task_id: str
    base_commit: str
    worktree_path: str
    created_at: str = field(default_factory=_utc_now_iso)
    cleaned_up: bool = False
    diff_sha256: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WorktreeSession:
    """Manages an active isolated git worktree session with context-manager cleanup."""

    def __init__(
        self,
        manager: "WorktreeManager",
        worktree_path: Path,
        grant: Optional[ExecutionGrant] = None,
        base_commit_hash: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        self.manager = manager
        self.grant = grant
        self.worktree_path = worktree_path
        self.base_commit_hash = base_commit_hash or (grant.base_commit_hash if grant else "")
        self.audit = WorktreeAuditRecord(
            grant_id=grant.grant_id if grant else (session_id or "qa_session"),
            task_id=grant.task_id if grant else (session_id or "qa_session"),
            base_commit=self.base_commit_hash,
            worktree_path=str(worktree_path),
        )
        self._is_cleaned_up = False

    def __enter__(self) -> "WorktreeSession":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_val is not None and not self.audit.error:
            self.audit.error = str(exc_val)
        self.remove()

    @property
    def is_cleaned_up(self) -> bool:
        return self._is_cleaned_up

    def verify_path(self, rel_path: str) -> Path:
        """Verify that a path is safe, confined inside this worktree, and permitted."""
        return verify_workspace_path(rel_path, self.worktree_path)

    def capture_diff(self) -> WorktreeDiffResult:
        """Independently capture the git diff and changed files within this isolated worktree."""
        if self._is_cleaned_up:
            raise WorktreeError("Cannot capture diff: WorktreeSession is already cleaned up.")

        # 1. Run git status --porcelain to find modified, deleted, added, untracked files
        code, status_out, status_err = run_git(["status", "--porcelain"], cwd=self.worktree_path)
        if code != 0:
            raise WorktreeGitError(f"Failed to inspect worktree status: {status_err.strip()}")

        changed_files: List[str] = []
        untracked_files: List[str] = []
        deleted_files: List[str] = []

        for line in status_out.splitlines():
            line = line.rstrip()
            if not line:
                continue
            status_code = line[:2]
            filename = line[3:].strip()
            norm_fn = filename.replace("\\", "/")
            if (
                norm_fn == ".agents"
                or norm_fn.startswith(".agents/")
                or norm_fn == ".runs"
                or norm_fn.startswith(".runs/")
            ):
                continue

            if status_code == "??":
                untracked_files.append(norm_fn)
                changed_files.append(norm_fn)
            elif "D" in status_code:
                deleted_files.append(norm_fn)
                changed_files.append(norm_fn)
            else:
                changed_files.append(norm_fn)

        # 2. Stage intent to add (-N) for untracked files so git diff includes them
        if untracked_files:
            run_git(["add", "-N", "--"] + untracked_files, cwd=self.worktree_path)

        # 3. Capture full unified diff against base commit
        code, diff_out, diff_err = run_git(
            ["diff", self.base_commit_hash, "--", "."],
            cwd=self.worktree_path,
        )
        if code != 0:
            raise WorktreeGitError(f"Failed to capture worktree diff: {diff_err.strip()}")

        diff_bytes = diff_out.encode("utf-8")
        diff_sha256 = hashlib.sha256(diff_bytes).hexdigest()
        is_empty = (len(diff_bytes) == 0)
        is_binary = ("Binary files" in diff_out) or ("GIT binary patch" in diff_out) or (b"\x00" in diff_bytes)

        self.audit.diff_sha256 = diff_sha256

        return WorktreeDiffResult(
            diff_text=diff_out,
            diff_bytes=diff_bytes,
            diff_sha256=diff_sha256,
            changed_files=sorted(list(set(changed_files))),
            untracked_files=sorted(untracked_files),
            deleted_files=sorted(deleted_files),
            is_empty=is_empty,
            is_binary=is_binary,
        )

    def remove(self) -> None:
        """Safely remove the worktree from Git and disk."""
        if self._is_cleaned_up:
            return

        try:
            # 1. Ask git to remove worktree
            exit_code, _, stderr = run_git(
                ["worktree", "remove", "--force", str(self.worktree_path)],
                cwd=self.manager.repo_root,
            )
            if exit_code != 0:
                logger.warning("git worktree remove reported: %s", stderr.strip())

            # 2. Prune git worktree records
            run_git(["worktree", "prune"], cwd=self.manager.repo_root)

            # 3. Ensure disk folder is wiped if git didn't remove it completely
            if self.worktree_path.exists():
                shutil.rmtree(self.worktree_path, ignore_errors=True)
        finally:
            self._is_cleaned_up = True
            self.audit.cleaned_up = True


class WorktreeManager:
    """Manages creation, lifecycle, and confinement validation of isolated Git worktrees."""

    def __init__(
        self,
        repo_root: Path,
        worktrees_dir: Optional[Path] = None,
        protect_company_control: bool = True,
    ):
        self.repo_root = repo_root.resolve()
        self.worktrees_dir = (
            worktrees_dir.resolve()
            if worktrees_dir is not None
            else (self.repo_root / ".runs" / "worktrees").resolve()
        )
        self.protect_company_control = protect_company_control

    def validate_repository(self) -> str:
        """Verify that the configured repo_root is a valid Git repository and return HEAD commit."""
        return resolve_repo_head_commit(self.repo_root)

    def create_worktree(self, grant: ExecutionGrant) -> WorktreeSession:
        """Create a detached isolated Git worktree for an approved ExecutionGrant.

        Enforces:
        1. Repo HEAD matches grant.base_commit_hash (prevents TOCTOU drift).
        2. All approved files satisfy confinement and protected path policies.
        3. Test file modifications are checked against grant.allow_test_modifications.
        4. Worktree is created in detached mode at exact base commit.
        """
        # 1. TOCTOU Base Commit Check (Requirement 5)
        current_head = self.validate_repository()
        if current_head != grant.base_commit_hash and not current_head.startswith(grant.base_commit_hash):
            raise StaleCommitError(
                f"Repository HEAD commit '{current_head}' does not match grant base commit '{grant.base_commit_hash}'. "
                "Approval is stale."
            )

        # 2. Validate approved paths
        all_approved = list(grant.approved_files_to_modify) + list(grant.approved_files_to_create)
        for rel_path in all_approved:
            # Check basic path formatting
            if not rel_path or Path(rel_path).is_absolute() or ":" in rel_path or ".." in Path(rel_path).parts:
                raise WorktreeConfinementError(f"Approved path '{rel_path}' is invalid or absolute.")

            # Check protected path policy (Requirement 12)
            if is_protected_path(rel_path, protect_company_control=self.protect_company_control):
                raise ProtectedPathError(f"Path '{rel_path}' is protected by company policy.")

            # Check test file policy (Requirement 13)
            if is_test_file(rel_path) and not grant.allow_test_modifications:
                raise TestModificationForbiddenError(
                    f"Test file '{rel_path}' cannot be modified: grant.allow_test_modifications is False."
                )

        # 3. Ensure worktrees directory exists
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        worktree_name = grant.grant_id if len(grant.grant_id) <= 40 else f"{grant.grant_id[:24]}_{hashlib.sha256(grant.grant_id.encode()).hexdigest()[:8]}"
        worktree_path = (self.worktrees_dir / worktree_name).resolve()

        # If previous stale worktree exists at path, clean it up
        if worktree_path.exists():
            run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=self.repo_root)
            shutil.rmtree(worktree_path, ignore_errors=True)

        # 4. Create detached worktree at approved commit (Requirement 4 & 7)
        code, stdout, stderr = run_git(
            ["worktree", "add", "--detach", str(worktree_path), grant.base_commit_hash],
            cwd=self.repo_root,
        )
        if code != 0:
            raise WorktreeGitError(f"Failed to create isolated git worktree: {stderr.strip() or stdout.strip()}")

        return WorktreeSession(manager=self, grant=grant, worktree_path=worktree_path)

    def create_qa_worktree(
        self,
        base_commit_hash: str,
        session_id: str,
    ) -> WorktreeSession:
        """Create a detached isolated Git worktree for QA execution directly from base_commit_hash."""
        if not base_commit_hash or len(base_commit_hash) < 7:
            raise WorktreeError(f"Invalid base_commit_hash for QA worktree: '{base_commit_hash}'.")

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        worktree_name = session_id if len(session_id) <= 40 else f"{session_id[:24]}_{hashlib.sha256(session_id.encode()).hexdigest()[:8]}"
        worktree_path = (self.worktrees_dir / worktree_name).resolve()

        if worktree_path.exists():
            run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=self.repo_root)
            shutil.rmtree(worktree_path, ignore_errors=True)

        code, stdout, stderr = run_git(
            ["worktree", "add", "--detach", str(worktree_path), base_commit_hash],
            cwd=self.repo_root,
        )
        if code != 0:
            raise WorktreeGitError(f"Failed to create isolated QA worktree: {stderr.strip() or stdout.strip()}")

        return WorktreeSession(
            manager=self,
            worktree_path=worktree_path,
            base_commit_hash=base_commit_hash,
            session_id=session_id,
        )
