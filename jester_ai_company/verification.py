"""Verification Execution Engine for Isolated Worktrees (STEP 13B-3).

Provides deterministic, typed verification execution (such as pytest) inside an
isolated Git worktree. Disallows raw shell commands, metacharacters, or arbitrary
scripts. Enforces path confinement, sanitized environments, and bounded execution.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Set

from .execution_grant import (
    ALLOWED_VERIFICATION_ACTION_TYPES,
    DISALLOWED_TARGET_CHARS_PATTERN,
    VerificationAction,
)
from .worktree import (
    WorktreeConfinementError,
    is_protected_path,
    is_test_file,
    sanitize_execution_environment,
    verify_workspace_path,
)


class VerificationStatus(str, Enum):
    """Outcome status of a single verification action."""
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class VerificationError(Exception):
    """Base exception for verification execution errors."""
    pass


class TargetValidationError(VerificationError):
    """Raised when a verification target path is invalid or unsafe."""
    pass


class UnsupportedActionTypeError(VerificationError):
    """Raised when an unrecognized action type is provided."""
    pass


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class VerificationExecutionResult:
    """Represents the structured result of an executed VerificationAction."""
    action: VerificationAction
    status: str  # VerificationStatus value
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    executed_at: str = field(default_factory=_utc_now_iso)
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASS.value and self.exit_code == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "status": self.status,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "executed_at": self.executed_at,
            "error": self.error,
        }


def validate_verification_target(
    target: str,
    worktree_path: Path,
    action_type: str = "pytest",
) -> Path:
    """Validate that a verification target strictly resolves inside the worktree and exists.

    Enforces:
    1. Non-empty string.
    2. No shell metacharacters.
    3. Relative path (no drive-colon or leading slash).
    4. Path confinement inside worktree (no traversal '..').
    5. Symlink / junction rejection.
    6. Protected path rejection (.git, .agents, .env, secrets).
    7. File or directory must physically exist inside the worktree.
    8. For frontend build actions, target must contain a valid package.json with a 'build' script.
    """
    if not target or not isinstance(target, str) or not target.strip():
        raise TargetValidationError("Verification target must be a non-empty string.")

    cleaned = target.strip().strip('"').strip("'")
    if DISALLOWED_TARGET_CHARS_PATTERN.search(cleaned):
        raise TargetValidationError(f"Verification target '{cleaned}' contains forbidden characters.")

    target_p = Path(cleaned)
    if target_p.is_absolute() or ":" in cleaned or ".." in target_p.parts:
        raise TargetValidationError(f"Verification target '{cleaned}' must be a clean relative path.")

    # Confinement check
    try:
        resolved = verify_workspace_path(cleaned, worktree_path)
    except WorktreeConfinementError as exc:
        raise TargetValidationError(f"Verification target '{cleaned}' escapes worktree: {exc}") from exc

    # Protected path check
    try:
        rel = resolved.relative_to(worktree_path.resolve()).as_posix()
    except ValueError as exc:
        raise TargetValidationError(f"Verification target '{cleaned}' escapes worktree root: {exc}") from exc

    if is_protected_path(rel):
        raise TargetValidationError(f"Verification target '{rel}' is a protected repository path.")

    # Target existence check
    if not resolved.exists():
        raise TargetValidationError(f"Verification target '{rel}' does not exist inside the worktree.")

    # Frontend build validation
    norm_type = str(action_type or "").strip().lower()
    if norm_type in {"npm_build", "frontend_build"}:
        pkg_json = resolved if resolved.is_file() and resolved.name == "package.json" else (resolved / "package.json")
        if not pkg_json.is_file():
            raise TargetValidationError(f"Frontend build target '{rel}' is missing 'package.json'.")
        try:
            pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TargetValidationError(f"Target '{rel}' package.json is invalid JSON: {exc}") from exc

        if not isinstance(pkg_data, dict):
            raise TargetValidationError(f"Target '{rel}' package.json must be a JSON object.")

        scripts = pkg_data.get("scripts", {})
        if not isinstance(scripts, dict) or "build" not in scripts:
            raise TargetValidationError(
                f"Target '{rel}' package.json does not define a 'build' script in 'scripts'."
            )

    return resolved


def translate_verification_action(action: VerificationAction) -> List[str]:
    """Translate a typed VerificationAction deterministically to an argv array (shell=False).

    Rejects arbitrary shell strings or unsupported verifiers.
    """
    norm_type = action.action_type.strip().lower()
    if norm_type == "pytest":
        # Use sys.executable to ensure the exact running Python interpreter is used
        return [sys.executable, "-m", "pytest", action.target.strip()]

    if norm_type in {"npm_build", "frontend_build"}:
        npm_bin = shutil.which("npm") or shutil.which("npm.cmd")
        if not npm_bin:
            raise UnsupportedActionTypeError("The 'npm' command is not available on system PATH.")
        return [npm_bin, "run", "build"]

    raise UnsupportedActionTypeError(
        f"Unsupported verification action type: '{action.action_type}'. "
        f"Allowed types: {sorted(ALLOWED_VERIFICATION_ACTION_TYPES)}."
    )


MAX_VERIFICATION_OUTPUT_CHARS: int = 50_000


def execute_verification_action(
    action: VerificationAction,
    worktree_path: Path,
    timeout: float = 60.0,
    sanitized_env: Optional[Dict[str, str]] = None,
) -> VerificationExecutionResult:
    """Execute a single typed VerificationAction within the isolated worktree.

    Guarantees:
    - Target validated before execution (target must exist inside worktree).
    - Subprocess argv array executed with shell=False.
    - Working directory strictly confined to target directory inside worktree.
    - Subprocess receives sanitized environment (secrets stripped).
    - Timeout strictly bounded.
    - Output bounded to prevent unbounded memory growth.
    """
    # 1. Validate target
    try:
        resolved_target = validate_verification_target(
            action.target,
            worktree_path,
            action_type=action.action_type,
        )
    except TargetValidationError as exc:
        return VerificationExecutionResult(
            action=action,
            status=VerificationStatus.FAIL.value,
            exit_code=1,
            stdout="",
            stderr=str(exc),
            duration_ms=0,
            error=str(exc),
        )

    # 2. Translate action to argv
    try:
        argv = translate_verification_action(action)
    except UnsupportedActionTypeError as exc:
        return VerificationExecutionResult(
            action=action,
            status=VerificationStatus.EXECUTION_ERROR.value,
            exit_code=1,
            stdout="",
            stderr=str(exc),
            duration_ms=0,
            error=str(exc),
        )

    # 3. Determine working directory and setup isolated dependencies if needed
    norm_type = action.action_type.strip().lower()
    if norm_type in {"npm_build", "frontend_build"}:
        working_dir = resolved_target if resolved_target.is_dir() else resolved_target.parent
    else:
        working_dir = worktree_path

    # Security check: verify working directory is strictly confined in worktree
    try:
        working_dir.resolve().relative_to(worktree_path.resolve())
    except ValueError:
        return VerificationExecutionResult(
            action=action,
            status=VerificationStatus.EXECUTION_ERROR.value,
            exit_code=1,
            stdout="",
            stderr="Working directory escapes worktree confinement.",
            duration_ms=0,
            error="Working directory escapes worktree confinement.",
        )

    # Link node_modules inside isolated worktree if needed
    created_junction = False
    target_node_modules = working_dir / "node_modules"
    if norm_type in {"npm_build", "frontend_build"} and not target_node_modules.exists():
        candidate_roots = [
            worktree_path.parent.parent / "frontend" / "node_modules",
            worktree_path.parent.parent.parent / "frontend" / "node_modules",
        ]
        git_pointer = worktree_path / ".git"
        if git_pointer.is_file():
            try:
                line = git_pointer.read_text(encoding="utf-8").strip()
                if line.startswith("gitdir:"):
                    gitdir_path = Path(line[7:].strip())
                    canonical_repo = gitdir_path.resolve().parent.parent.parent
                    candidate_roots.insert(0, canonical_repo / "frontend" / "node_modules")
                    candidate_roots.insert(1, canonical_repo / working_dir.name / "node_modules")
            except Exception:
                pass

        for cand in candidate_roots:
            if cand.is_dir():
                try:
                    if sys.platform == "win32":
                        import _winapi
                        _winapi.CreateJunction(str(cand.resolve()), str(target_node_modules.resolve()))
                    else:
                        target_node_modules.symlink_to(cand.resolve(), target_is_directory=True)
                    created_junction = True
                    break
                except Exception as exc:
                    print(f"DEBUG CREATE JUNCTION ERROR: {exc} on cand={cand} target={target_node_modules}")

    # 4. Prepare environment
    env = sanitized_env if sanitized_env is not None else sanitize_execution_environment()

    # 5. Execute via subprocess
    start_time = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(working_dir.resolve()),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        stdout_bounded = proc.stdout[:MAX_VERIFICATION_OUTPUT_CHARS]
        stderr_bounded = proc.stderr[:MAX_VERIFICATION_OUTPUT_CHARS]

        status = VerificationStatus.PASS.value if proc.returncode == 0 else VerificationStatus.FAIL.value

        return VerificationExecutionResult(
            action=action,
            status=status,
            exit_code=proc.returncode,
            stdout=stdout_bounded,
            stderr=stderr_bounded,
            duration_ms=elapsed_ms,
        )

    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        out = (exc.stdout or "")[:MAX_VERIFICATION_OUTPUT_CHARS]
        err = (exc.stderr or "")[:MAX_VERIFICATION_OUTPUT_CHARS]
        return VerificationExecutionResult(
            action=action,
            status=VerificationStatus.TIMEOUT.value,
            exit_code=-1,
            stdout=out,
            stderr=err + f"\nTimed out after {timeout} seconds.",
            duration_ms=elapsed_ms,
            error=f"Verification timed out after {timeout}s.",
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        return VerificationExecutionResult(
            action=action,
            status=VerificationStatus.EXECUTION_ERROR.value,
            exit_code=-1,
            stdout="",
            stderr=str(exc),
            duration_ms=elapsed_ms,
            error=f"Subprocess execution error: {exc}",
        )
    finally:
        is_junc = getattr(os.path, "isjunction", lambda p: False)(str(target_node_modules))
        if created_junction or is_junc or os.path.islink(str(target_node_modules)) or target_node_modules.is_symlink():
            try:
                if sys.platform == "win32":
                    os.rmdir(str(target_node_modules))
                else:
                    target_node_modules.unlink()
            except Exception:
                pass
