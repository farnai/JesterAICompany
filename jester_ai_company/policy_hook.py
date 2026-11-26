"""Execution-scoped Antigravity PreToolUse hook installer and write authorization policy.

Provides deterministic tool-call interception for:
1. Bounded Developer code mutation (ExecutionGrant + cumulative byte/file quotas).
2. Developer read-only planning & repair planning.
3. Read-only specialist execution (product, research, ux, marketing, qa, ceo).

Empirically verified agy CLI v1.3.6 tool schemas:
- Read tool:   `read_file` (args: `Path`)
- Write tool:  `write_file` (args: `Path`, `Content`, `Overwrite`, `Append`)
- Edit tool:   `edit_file` (args: `Path`, `Target`, `Replacement`)
- Shell tool:  `run_command` (args: `CommandLine`, ...) — ALWAYS DENIED in hooks

Legacy unit-test schemas retained for backward compatibility:
- Read tool:   `view_file` (args: `AbsolutePath` / `TargetFile` / `Path`)
- Write tool:  `write_to_file` (args: `TargetFile`, `CodeContent`)
- Edit tool:   `replace_file_content` (args: `TargetFile`, `ReplacementContent`)

All unknown, delegation, or MCP tools are DENIED fail-closed.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from .execution_grant import ExecutionGrant
from .worktree import (
    WorktreeConfinementError,
    is_protected_path,
    is_test_file,
    verify_workspace_path,
)

# Empirically verified agy v1.3.6 tools + legacy compatibility names
VERIFIED_READ_TOOLS = frozenset({"read_file"})
LEGACY_READ_TOOLS = frozenset({"view_file"})
ALL_READ_TOOLS = VERIFIED_READ_TOOLS | LEGACY_READ_TOOLS

VERIFIED_MUTATION_TOOLS = frozenset({"write_file", "edit_file"})
LEGACY_MUTATION_TOOLS = frozenset({"write_to_file", "replace_file_content"})
ALL_MUTATION_TOOLS = VERIFIED_MUTATION_TOOLS | LEGACY_MUTATION_TOOLS

SHELL_TOOLS = frozenset({"run_command"})


@dataclass
class WriteAuthorizationDecision:
    """Outcome of a pre-mutation or read-only tool call authorization check."""
    allowed: bool
    reason: str
    target_path: Optional[Path] = None
    relative_path: Optional[str] = None


def normalize_rel_path(path_str: str) -> str:
    """Normalize a path consistently across Windows/POSIX to clean relative posix form."""
    cleaned = str(path_str).strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/").rstrip("/")


def _extract_target_path(tool_name: str, args: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Extract target path argument according to verified tool schema.

    Returns (raw_path_or_None, expected_key_name).
    """
    if tool_name in ("write_file", "edit_file", "read_file"):
        return args.get("Path"), "Path"
    if tool_name in ("write_to_file", "replace_file_content"):
        return args.get("TargetFile"), "TargetFile"
    if tool_name == "view_file":
        return args.get("AbsolutePath") or args.get("TargetFile") or args.get("Path"), "AbsolutePath/TargetFile"
    return None, "Path"


def _extract_write_bytes(tool_name: str, args: Dict[str, Any]) -> int:
    """Compute UTF-8 byte length of the mutation payload according to tool schema."""
    if tool_name == "write_file":
        content = args.get("Content", "")
    elif tool_name == "edit_file":
        content = args.get("Replacement", "")
    elif tool_name == "write_to_file":
        content = args.get("CodeContent", "")
    elif tool_name == "replace_file_content":
        content = args.get("ReplacementContent", "")
    else:
        content = ""
    return len(content.encode("utf-8")) if isinstance(content, str) else 0


def _resolve_confined_path(
    target_raw: str,
    workspace_root: Path,
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    """Resolve and verify path confinement strictly inside workspace_root.

    Returns (resolved_path, rel_posix_path, error_reason).
    """
    cleaned_target = target_raw.strip().strip('"').strip("'")
    if not cleaned_target:
        return None, None, "target path is empty"

    p = Path(cleaned_target)
    root_resolved = workspace_root.resolve()

    if p.is_absolute() or (len(p.parts) > 0 and ":" in p.parts[0]) or cleaned_target.startswith("\\\\"):
        try:
            resolved_path = p.resolve()
        except Exception as exc:
            return None, None, f"path resolution failed: {exc}"
        try:
            in_root = resolved_path.is_relative_to(root_resolved)
        except AttributeError:
            try:
                resolved_path.relative_to(root_resolved)
                in_root = True
            except ValueError:
                in_root = False
        if not in_root:
            return (
                None,
                None,
                f"Path '{cleaned_target}' is absolute and escapes workspace root '{root_resolved}'.",
            )
        if resolved_path.is_symlink() or os.path.islink(str(resolved_path)):
            return None, None, f"Path '{cleaned_target}' is a symlink or junction."
    else:
        try:
            resolved_path = verify_workspace_path(cleaned_target, workspace_root)
        except WorktreeConfinementError as exc:
            return None, None, str(exc)

    try:
        rel_path = normalize_rel_path(resolved_path.relative_to(root_resolved).as_posix())
    except ValueError:
        return None, None, f"path '{cleaned_target}' escapes workspace root."

    return resolved_path, rel_path, None


def _is_secret_read_path(rel_path: str) -> bool:
    """Return True if a path targets secret material that must never be read by hooks."""
    rel_lower = normalize_rel_path(rel_path).lower()
    name = Path(rel_lower).name
    if (
        rel_lower == ".env"
        or rel_lower.startswith(".env.")
        or "/.env" in rel_lower
        or name == ".env"
        or name.startswith(".env.")
        or rel_lower.endswith(".pem")
        or rel_lower.endswith(".key")
        or "credentials" in rel_lower
        or "secret" in name
    ):
        return True
    return False


def authorize_tool_mutation(
    tool_name: str,
    args: Dict[str, Any],
    workspace_root: Path,
    grant: ExecutionGrant,
    protect_company_control: bool = True,
    quota_state: Optional[Dict[str, Any]] = None,
) -> WriteAuthorizationDecision:
    """Deterministically authorize or deny a tool call during bounded Developer mutation.

    Enforces:
    1. Unconditionally denies `run_command` and all unknown/delegation/MCP tools (fail-closed).
    2. Permits `read_file` (requires confined non-secret `Path`) and legacy `view_file` (confined if path given).
    3. For verified (`write_file`, `edit_file`) and legacy (`write_to_file`, `replace_file_content`) mutation tools:
       - Validates tool-specific path argument (`Path` vs `TargetFile`).
       - Verifies strict confinement inside `workspace_root` (rejects escapes, `..`, UNC, symlinks).
       - Rejects protected paths (`.git`, `.agents`, `.env*`, credentials, company control).
       - Enforces test modification policy (`grant.allow_test_modifications`).
       - Permits repeated edits to files in `approved_files_to_create` once created on disk.
       - Rejects creating brand-new files not in `approved_files_to_create` (or `approved_files_to_modify` if legacy).
       - Enforces single-call and cumulative `max_bytes_written` and `max_files_changed` budgets.
    """
    if not isinstance(args, dict):
        return WriteAuthorizationDecision(
            allowed=False,
            reason="ExecutionPolicy: PreToolUse DENIED - tool args must be a JSON object.",
        )

    # 1. Unconditionally deny shell execution
    if tool_name in SHELL_TOOLS:
        return WriteAuthorizationDecision(
            allowed=False,
            reason="ExecutionPolicy: PreToolUse DENIED - run_command execution is strictly forbidden during Developer mutation.",
        )

    # 2. Read tools (confined to workspace root, blocking secrets)
    if tool_name in ALL_READ_TOOLS:
        target_raw, expected_key = _extract_target_path(tool_name, args)
        if tool_name in VERIFIED_READ_TOOLS:
            if not target_raw or not isinstance(target_raw, str) or not target_raw.strip():
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED - '{tool_name}' requires non-empty '{expected_key}'.",
                )
        if target_raw and isinstance(target_raw, str) and target_raw.strip():
            resolved_path, rel_path, err = _resolve_confined_path(target_raw, workspace_root)
            if err or resolved_path is None or rel_path is None:
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED read confinement check: {err}",
                )
            if _is_secret_read_path(rel_path):
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED - reading protected secret path '{rel_path}' is forbidden.",
                    target_path=resolved_path,
                    relative_path=rel_path,
                )
            return WriteAuthorizationDecision(
                allowed=True,
                reason=f"ExecutionPolicy: PreToolUse ALLOWED - read-only tool '{tool_name}' permitted.",
                target_path=resolved_path,
                relative_path=rel_path,
            )
        return WriteAuthorizationDecision(allowed=True, reason="Read-only tool permitted.")

    # 3. Fail-closed for any unknown / unauthorized tool
    if tool_name not in ALL_MUTATION_TOOLS:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - tool '{tool_name}' is not authorized for Developer mutation.",
        )

    # 4. Extract target path according to exact tool schema
    target_raw, expected_key = _extract_target_path(tool_name, args)
    if not target_raw or not isinstance(target_raw, str) or not target_raw.strip():
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - '{expected_key}' argument is missing or empty for '{tool_name}'.",
        )

    # 5. Confinement check
    resolved_path, rel_path, err = _resolve_confined_path(target_raw, workspace_root)
    if err or resolved_path is None or rel_path is None:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED path confinement check: {err}",
        )

    # 6. Protected Path Policy Check
    if is_protected_path(rel_path, protect_company_control=protect_company_control):
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - path '{rel_path}' is a protected repository path.",
            target_path=resolved_path,
            relative_path=rel_path,
        )

    # 7. Test File Modification Policy Check
    if is_test_file(rel_path) and not grant.allow_test_modifications:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - test modification forbidden by default for '{rel_path}'.",
            target_path=resolved_path,
            relative_path=rel_path,
        )

    # 8. Grant file allowlist check (supports repeated edits to created files!)
    approved_mod = {normalize_rel_path(f).lower() for f in grant.approved_files_to_modify}
    approved_create = {normalize_rel_path(f).lower() for f in grant.approved_files_to_create}
    rel_lower = rel_path.lower()
    file_exists = resolved_path.is_file()

    if file_exists:
        if rel_lower not in approved_mod and rel_lower not in approved_create:
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED - existing file '{rel_path}' is not in approved_files_to_modify or approved_files_to_create.",
                target_path=resolved_path,
                relative_path=rel_path,
            )
    else:
        if tool_name == "edit_file":
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED - edit_file cannot create non-existent file '{rel_path}'.",
                target_path=resolved_path,
                relative_path=rel_path,
            )
        if rel_lower not in approved_create and rel_lower not in approved_mod:
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED - new file '{rel_path}' is not in approved_files_to_create.",
                target_path=resolved_path,
                relative_path=rel_path,
            )

    # 9. Single-call + cumulative write byte quota and file count enforcement
    content_len = _extract_write_bytes(tool_name, args)
    prev_bytes = int((quota_state or {}).get("bytes_written", 0))
    prev_files: Set[str] = {
        normalize_rel_path(f).lower() for f in (quota_state or {}).get("files_touched", [])
    }
    projected_bytes = prev_bytes + content_len
    projected_files = prev_files | {rel_lower}

    if projected_bytes > grant.max_bytes_written:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=(
                f"ExecutionPolicy: PreToolUse DENIED - cumulative write size {projected_bytes} bytes "
                f"(call={content_len}, prior={prev_bytes}) exceeds grant limit {grant.max_bytes_written} bytes."
            ),
            target_path=resolved_path,
            relative_path=rel_path,
        )

    if len(projected_files) > grant.max_files_changed:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=(
                f"ExecutionPolicy: PreToolUse DENIED - distinct files modified ({len(projected_files)}) "
                f"exceeds grant max_files_changed ({grant.max_files_changed})."
            ),
            target_path=resolved_path,
            relative_path=rel_path,
        )

    if quota_state is not None:
        quota_state["bytes_written"] = projected_bytes
        quota_state["files_touched"] = sorted(projected_files)

    return WriteAuthorizationDecision(
        allowed=True,
        reason="ExecutionPolicy: PreToolUse ALLOWED - authorized by ExecutionGrant.",
        target_path=resolved_path,
        relative_path=rel_path,
    )


def _render_mutation_hook_script() -> str:
    """Return standalone fail-closed Python PreToolUse hook script for bounded mutation."""
    return """import json
import os
from pathlib import Path
import sys


def _norm_rel(path_str):
    cleaned = str(path_str).strip().replace("\\\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/").rstrip("/")


def _is_protected(rel_lower, protect_company_control):
    name = Path(rel_lower).name
    if (
        rel_lower == ".git" or rel_lower.startswith(".git/") or "/.git/" in rel_lower
        or rel_lower == ".agents" or rel_lower.startswith(".agents/") or "/.agents/" in rel_lower
        or rel_lower == ".runs" or rel_lower.startswith(".runs/")
        or rel_lower == ".env" or rel_lower.startswith(".env.") or "/.env" in rel_lower
        or name == ".env" or name.startswith(".env.")
        or "credential" in rel_lower or "secret" in name
        or rel_lower.endswith(".pem") or rel_lower.endswith(".key")
    ):
        return True
    if protect_company_control and (
        rel_lower == "jester_ai_company" or rel_lower.startswith("jester_ai_company/")
    ):
        return True
    return False


def _is_secret_read(rel_lower):
    name = Path(rel_lower).name
    return (
        rel_lower == ".env" or rel_lower.startswith(".env.") or "/.env" in rel_lower
        or name == ".env" or name.startswith(".env.")
        or rel_lower.endswith(".pem") or rel_lower.endswith(".key")
        or "credential" in rel_lower or "secret" in name
    )


def _is_test(rel_lower):
    name = Path(rel_lower).name
    return (
        rel_lower.startswith("tests/")
        or rel_lower.startswith("test/")
        or "/tests/" in rel_lower
        or "/test/" in rel_lower
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _resolve_confined(target_raw, workspace_root):
    cleaned = str(target_raw).strip().strip('"').strip("'")
    if not cleaned:
        return None, None, "empty target path"
    p = Path(cleaned)
    is_abs = p.is_absolute() or (len(p.parts) > 0 and ":" in p.parts[0]) or cleaned.startswith("\\\\\\\\")
    if is_abs:
        try:
            resolved = p.resolve()
        except Exception as exc:
            return None, None, f"invalid path '{cleaned}': {exc}"
    else:
        if ".." in p.parts:
            return None, None, f"path '{cleaned}' contains directory traversal"
        try:
            resolved = (workspace_root / p).resolve()
        except Exception as exc:
            return None, None, f"invalid path '{cleaned}': {exc}"
    try:
        in_root = resolved.is_relative_to(workspace_root)
    except AttributeError:
        try:
            resolved.relative_to(workspace_root)
            in_root = True
        except ValueError:
            in_root = False
    if not in_root:
        return None, None, f"path '{cleaned}' escapes workspace root"
    if resolved.is_symlink() or os.path.islink(str(resolved)):
        return None, None, f"path '{cleaned}' is a symlink or junction"
    rel = _norm_rel(resolved.relative_to(workspace_root).as_posix())
    return resolved, rel, None


def _emit(resp):
    sys.stdout.write(json.dumps(resp))
    sys.stdout.flush()


def run():
    config_file = Path(__file__).resolve().parent / "policy_config.json"
    if not config_file.exists():
        _emit({"decision": "deny", "reason": "ExecutionPolicy: missing policy_config.json (fail-closed)"})
        return

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or "workspace_root" not in config:
            raise ValueError("malformed policy_config")
    except Exception as exc:
        _emit({"decision": "deny", "reason": f"ExecutionPolicy: invalid policy_config.json: {exc}"})
        return

    raw_input = sys.stdin.read()
    try:
        data = json.loads(raw_input)
        if not isinstance(data, dict):
            raise ValueError("payload root must be JSON object")
    except Exception as exc:
        _emit({"decision": "deny", "reason": f"ExecutionPolicy: invalid hook payload JSON: {exc}"})
        return

    tool_call = data.get("toolCall")
    if not isinstance(tool_call, dict):
        _emit({"decision": "deny", "reason": "ExecutionPolicy: missing toolCall object (fail-closed)"})
        return

    tool_name = str(tool_call.get("name") or "")
    args = tool_call.get("args")
    if not isinstance(args, dict):
        args = {}

    workspace_root = Path(config["workspace_root"]).resolve()
    audit_log = Path(config["audit_log_path"])
    quota_file = Path(config["quota_state_path"])

    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - tool '{tool_name}' not permitted"}

    if tool_name == "run_command":
        decision = {
            "decision": "deny",
            "reason": "ExecutionPolicy: PreToolUse DENIED - run_command execution is strictly forbidden during Developer mutation.",
        }
    elif tool_name in ("read_file", "view_file"):
        target_raw = args.get("Path") if tool_name == "read_file" else (args.get("AbsolutePath") or args.get("TargetFile") or args.get("Path"))
        if tool_name == "read_file" and (not target_raw or not isinstance(target_raw, str) or not target_raw.strip()):
            decision = {"decision": "deny", "reason": "ExecutionPolicy: PreToolUse DENIED - read_file requires non-empty Path."}
        elif target_raw and isinstance(target_raw, str) and target_raw.strip():
            resolved, rel, err = _resolve_confined(target_raw, workspace_root)
            if err or rel is None:
                decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED read confinement: {err}"}
            elif _is_secret_read(rel.lower()):
                decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - reading secret path '{rel}' is forbidden."}
            else:
                decision = {"decision": "allow"}
        else:
            decision = {"decision": "allow"}
    elif tool_name in ("write_file", "edit_file", "write_to_file", "replace_file_content"):
        expected_key = "Path" if tool_name in ("write_file", "edit_file") else "TargetFile"
        target_raw = args.get(expected_key)
        if not target_raw or not isinstance(target_raw, str) or not target_raw.strip():
            decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - missing or empty {expected_key} for '{tool_name}'"}
        else:
            resolved, rel, err = _resolve_confined(target_raw, workspace_root)
            if err or resolved is None or rel is None:
                decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED path confinement check - {err}"}
            else:
                rel_lower = rel.lower()
                if _is_protected(rel_lower, bool(config.get("protect_company_control", True))):
                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - '{rel}' is a protected path"}
                elif _is_test(rel_lower) and not bool(config.get("allow_test_modifications", False)):
                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - test modification forbidden for '{rel}'"}
                else:
                    app_mod = {_norm_rel(f).lower() for f in config.get("approved_files_to_modify", [])}
                    app_create = {_norm_rel(f).lower() for f in config.get("approved_files_to_create", [])}
                    exists = resolved.is_file()

                    if exists:
                        in_scope = (rel_lower in app_mod) or (rel_lower in app_create)
                        scope_err = f"existing file '{rel}' is not in approved_files_to_modify or approved_files_to_create"
                    else:
                        if tool_name == "edit_file":
                            in_scope = False
                            scope_err = f"edit_file cannot create non-existent file '{rel}'"
                        else:
                            in_scope = (rel_lower in app_create) or (rel_lower in app_mod)
                            scope_err = f"new file '{rel}' is not in approved_files_to_create"

                    if not in_scope:
                        decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - {scope_err}"}
                    else:
                        if tool_name == "write_file":
                            payload = args.get("Content", "")
                        elif tool_name == "edit_file":
                            payload = args.get("Replacement", "")
                        elif tool_name == "write_to_file":
                            payload = args.get("CodeContent", "")
                        else:
                            payload = args.get("ReplacementContent", "")
                        content_len = len(payload.encode("utf-8")) if isinstance(payload, str) else 0

                        # Load cumulative quota state
                        quota = {"bytes_written": 0, "files_touched": []}
                        if quota_file.is_file():
                            try:
                                loaded = json.loads(quota_file.read_text(encoding="utf-8"))
                                if isinstance(loaded, dict):
                                    quota["bytes_written"] = int(loaded.get("bytes_written", 0))
                                    quota["files_touched"] = [str(x).lower() for x in loaded.get("files_touched", [])]
                            except Exception:
                                pass

                        max_bytes = int(config.get("max_bytes_written", 100000))
                        max_files = int(config.get("max_files_changed", 3))
                        projected_bytes = quota["bytes_written"] + content_len
                        projected_files = set(quota["files_touched"]) | {rel_lower}

                        if projected_bytes > max_bytes:
                            decision = {
                                "decision": "deny",
                                "reason": f"ExecutionPolicy: PreToolUse DENIED - cumulative write size {projected_bytes} bytes exceeds limit {max_bytes} bytes",
                            }
                        elif len(projected_files) > max_files:
                            decision = {
                                "decision": "deny",
                                "reason": f"ExecutionPolicy: PreToolUse DENIED - distinct modified files ({len(projected_files)}) exceeds limit {max_files}",
                            }
                        else:
                            quota["bytes_written"] = projected_bytes
                            quota["files_touched"] = sorted(projected_files)
                            try:
                                quota_file.parent.mkdir(parents=True, exist_ok=True)
                                quota_file.write_text(json.dumps(quota, indent=2), encoding="utf-8")
                            except Exception:
                                pass
                            decision = {"decision": "allow"}

    try:
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        audit_entry = {
            "tool": tool_name,
            "args": args,
            "decision": decision["decision"],
            "reason": decision.get("reason", ""),
        }
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry) + "\\n")
    except Exception:
        pass

    _emit(decision)


if __name__ == "__main__":
    run()
"""


def _install_hook_launcher(agents_dir: Path, hook_py: Path, hook_group_name: str) -> None:
    """Write OS-appropriate launcher wrapper and .agents/hooks.json."""
    if sys.platform == "win32":
        hook_cmd = agents_dir / "hook.bat"
        hook_cmd.write_text(f'@"{sys.executable}" "{hook_py}"\n', encoding="utf-8")
        command_str = str(hook_cmd)
    else:
        hook_cmd = agents_dir / "hook.sh"
        hook_cmd.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{hook_py}" "$@"\n', encoding="utf-8")
        hook_cmd.chmod(0o755)
        command_str = str(hook_cmd)

    hooks_json = agents_dir / "hooks.json"
    hooks_spec = {
        hook_group_name: {
            "PreToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command_str,
                            "timeout": 15,
                        }
                    ],
                }
            ]
        }
    }
    hooks_json.write_text(json.dumps(hooks_spec, indent=2), encoding="utf-8")


def install_execution_policy_hook(
    workspace_root: Path,
    grant: ExecutionGrant,
    protect_company_control: bool = True,
) -> Path:
    """Install an execution-scoped PreToolUse hook into the isolated worktree workspace.

    Generates:
    - <workspace_root>/.agents/hooks.json
    - <workspace_root>/.agents/policy_config.json
    - <workspace_root>/.agents/hook_policy.py
    - <workspace_root>/.agents/hook.bat (on Windows) or hook.sh (on Unix)
    """
    agents_dir = workspace_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    runs_dir = workspace_root / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    audit_log = runs_dir / "hook_audit.jsonl"
    quota_state_file = runs_dir / "hook_quota_state.json"

    policy_config = {
        "mode": "bounded_mutation",
        "grant_id": grant.grant_id,
        "workspace_root": str(workspace_root.resolve()),
        "approved_files_to_modify": [normalize_rel_path(f) for f in grant.approved_files_to_modify],
        "approved_files_to_create": [normalize_rel_path(f) for f in grant.approved_files_to_create],
        "allow_test_modifications": grant.allow_test_modifications,
        "protect_company_control": protect_company_control,
        "max_bytes_written": grant.max_bytes_written,
        "max_files_changed": grant.max_files_changed,
        "audit_log_path": str(audit_log.resolve()),
        "quota_state_path": str(quota_state_file.resolve()),
    }
    (agents_dir / "policy_config.json").write_text(json.dumps(policy_config, indent=2), encoding="utf-8")

    # Reset quota state cleanly for this execution
    quota_state_file.write_text(json.dumps({"bytes_written": 0, "files_touched": []}, indent=2), encoding="utf-8")

    hook_py = agents_dir / "hook_policy.py"
    hook_py.write_text(_render_mutation_hook_script(), encoding="utf-8")
    _install_hook_launcher(agents_dir, hook_py, "execution-grant-policy")

    return audit_log


def authorize_planning_tool(
    tool_name: str,
    args: Dict[str, Any],
    workspace_root: Path,
    protect_company_control: bool = True,
    allow_send_message: bool = True,
) -> WriteAuthorizationDecision:
    """Deterministically authorize or deny a tool call during read-only planning/inspection.

    Enforces strict read-only boundary (fail-closed):
    1. Rejects `run_command` unconditionally.
    2. Rejects all mutation tools (`write_file`, `edit_file`, `write_to_file`, `replace_file_content`).
    3. Permits `read_file` (with confined non-secret `Path`) and legacy `view_file` (confined).
    4. Permits `send_message` only when `allow_send_message=True`.
    5. Rejects any unrecognized, delegation, or MCP tool calls.
    """
    if not isinstance(args, dict):
        return WriteAuthorizationDecision(
            allowed=False,
            reason="ExecutionPolicy: PreToolUse DENIED - tool args must be a JSON object.",
        )

    if tool_name in SHELL_TOOLS:
        return WriteAuthorizationDecision(
            allowed=False,
            reason="ExecutionPolicy: PreToolUse DENIED - run_command execution is strictly forbidden in read-only mode.",
        )

    if tool_name in ALL_MUTATION_TOOLS:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - '{tool_name}' is forbidden in read-only mode.",
        )

    if tool_name in ALL_READ_TOOLS:
        target_raw, expected_key = _extract_target_path(tool_name, args)
        if tool_name in VERIFIED_READ_TOOLS:
            if not target_raw or not isinstance(target_raw, str) or not target_raw.strip():
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED - '{tool_name}' requires non-empty '{expected_key}'.",
                )
        if target_raw and isinstance(target_raw, str) and target_raw.strip():
            resolved_path, rel_path, err = _resolve_confined_path(target_raw, workspace_root)
            if err or resolved_path is None or rel_path is None:
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED - path '{target_raw}' escapes planning workspace: {err}",
                )
            if _is_secret_read_path(rel_path):
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED - reading protected secret path '{rel_path}' is forbidden.",
                    target_path=resolved_path,
                    relative_path=rel_path,
                )
            return WriteAuthorizationDecision(
                allowed=True,
                reason=f"ExecutionPolicy: PreToolUse ALLOWED - read-only tool '{tool_name}' permitted.",
                target_path=resolved_path,
                relative_path=rel_path,
            )
        return WriteAuthorizationDecision(
            allowed=True,
            reason=f"ExecutionPolicy: PreToolUse ALLOWED - read-only tool '{tool_name}' permitted.",
        )

    if allow_send_message and tool_name == "send_message":
        return WriteAuthorizationDecision(
            allowed=True,
            reason="ExecutionPolicy: PreToolUse ALLOWED - messaging tool permitted.",
        )

    return WriteAuthorizationDecision(
        allowed=False,
        reason=f"ExecutionPolicy: PreToolUse DENIED - tool '{tool_name}' is not authorized in read-only mode.",
    )


def authorize_readonly_tool(
    tool_name: str,
    args: Dict[str, Any],
    workspace_root: Path,
    protect_company_control: bool = True,
) -> WriteAuthorizationDecision:
    """Strict read-only authorization for specialist agents (no mutations, no shell, no delegation)."""
    return authorize_planning_tool(
        tool_name=tool_name,
        args=args,
        workspace_root=workspace_root,
        protect_company_control=protect_company_control,
        allow_send_message=False,
    )


def _render_readonly_hook_script() -> str:
    """Return standalone fail-closed Python PreToolUse hook script for read-only modes."""
    return """import json
import os
from pathlib import Path
import sys


def _norm_rel(path_str):
    cleaned = str(path_str).strip().replace("\\\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/").rstrip("/")


def _is_secret_read(rel_lower):
    name = Path(rel_lower).name
    return (
        rel_lower == ".env" or rel_lower.startswith(".env.") or "/.env" in rel_lower
        or name == ".env" or name.startswith(".env.")
        or rel_lower.endswith(".pem") or rel_lower.endswith(".key")
        or "credential" in rel_lower or "secret" in name
    )


def _resolve_confined(target_raw, workspace_root):
    cleaned = str(target_raw).strip().strip('"').strip("'")
    if not cleaned:
        return None, None, "empty target path"
    p = Path(cleaned)
    is_abs = p.is_absolute() or (len(p.parts) > 0 and ":" in p.parts[0]) or cleaned.startswith("\\\\\\\\")
    if is_abs:
        try:
            resolved = p.resolve()
        except Exception as exc:
            return None, None, f"invalid path '{cleaned}': {exc}"
    else:
        if ".." in p.parts:
            return None, None, f"path '{cleaned}' contains directory traversal"
        try:
            resolved = (workspace_root / p).resolve()
        except Exception as exc:
            return None, None, f"invalid path '{cleaned}': {exc}"
    try:
        in_root = resolved.is_relative_to(workspace_root)
    except AttributeError:
        try:
            resolved.relative_to(workspace_root)
            in_root = True
        except ValueError:
            in_root = False
    if not in_root:
        return None, None, f"path '{cleaned}' escapes workspace root"
    if resolved.is_symlink() or os.path.islink(str(resolved)):
        return None, None, f"path '{cleaned}' is a symlink or junction"
    rel = _norm_rel(resolved.relative_to(workspace_root).as_posix())
    return resolved, rel, None


def _emit(resp):
    sys.stdout.write(json.dumps(resp))
    sys.stdout.flush()


def run():
    config_file = Path(__file__).resolve().parent / "policy_config.json"
    if not config_file.exists():
        _emit({"decision": "deny", "reason": "ExecutionPolicy: missing policy_config.json (fail-closed)"})
        return

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or "workspace_root" not in config:
            raise ValueError("malformed policy_config")
    except Exception as exc:
        _emit({"decision": "deny", "reason": f"ExecutionPolicy: invalid policy_config.json: {exc}"})
        return

    raw_input = sys.stdin.read()
    try:
        data = json.loads(raw_input)
        if not isinstance(data, dict):
            raise ValueError("payload root must be JSON object")
    except Exception as exc:
        _emit({"decision": "deny", "reason": f"ExecutionPolicy: invalid hook payload JSON: {exc}"})
        return

    tool_call = data.get("toolCall")
    if not isinstance(tool_call, dict):
        _emit({"decision": "deny", "reason": "ExecutionPolicy: missing toolCall object (fail-closed)"})
        return

    tool_name = str(tool_call.get("name") or "")
    args = tool_call.get("args")
    if not isinstance(args, dict):
        args = {}

    workspace_root = Path(config["workspace_root"]).resolve()
    audit_log = Path(config["audit_log_path"])
    allow_send_message = bool(config.get("allow_send_message", False))

    if tool_name == "run_command":
        decision = {
            "decision": "deny",
            "reason": "ExecutionPolicy: PreToolUse DENIED - run_command execution is strictly forbidden in read-only mode.",
        }
    elif tool_name in ("write_file", "edit_file", "write_to_file", "replace_file_content"):
        decision = {
            "decision": "deny",
            "reason": f"ExecutionPolicy: PreToolUse DENIED - '{tool_name}' is forbidden in read-only mode.",
        }
    elif tool_name in ("read_file", "view_file"):
        target_raw = args.get("Path") if tool_name == "read_file" else (args.get("AbsolutePath") or args.get("TargetFile") or args.get("Path"))
        if tool_name == "read_file" and (not target_raw or not isinstance(target_raw, str) or not target_raw.strip()):
            decision = {"decision": "deny", "reason": "ExecutionPolicy: PreToolUse DENIED - read_file requires non-empty Path."}
        elif target_raw and isinstance(target_raw, str) and target_raw.strip():
            resolved, rel, err = _resolve_confined(target_raw, workspace_root)
            if err or rel is None:
                decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - path confinement failed: {err}"}
            elif _is_secret_read(rel.lower()):
                decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - reading secret path '{rel}' is forbidden."}
            else:
                decision = {"decision": "allow"}
        else:
            decision = {"decision": "allow"}
    elif allow_send_message and tool_name == "send_message":
        decision = {"decision": "allow"}
    else:
        decision = {
            "decision": "deny",
            "reason": f"ExecutionPolicy: PreToolUse DENIED - tool '{tool_name}' is not authorized in read-only mode.",
        }

    try:
        audit_log.parent.mkdir(parents=True, exist_ok=True)
        audit_entry = {
            "tool": tool_name,
            "args": args,
            "decision": decision["decision"],
            "reason": decision.get("reason", ""),
        }
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry) + "\\n")
    except Exception:
        pass

    _emit(decision)


if __name__ == "__main__":
    run()
"""


def install_planning_policy_hook(
    workspace_root: Path,
    protect_company_control: bool = True,
) -> Path:
    """Install a fail-closed PreToolUse hook into an isolated planning/repair-planning workspace."""
    agents_dir = workspace_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    audit_log = workspace_root / ".runs" / "planning_hook_audit.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)

    policy_config = {
        "mode": "read_only_planning",
        "workspace_root": str(workspace_root.resolve()),
        "protect_company_control": protect_company_control,
        "allow_send_message": True,
        "audit_log_path": str(audit_log.resolve()),
    }
    (agents_dir / "policy_config.json").write_text(json.dumps(policy_config, indent=2), encoding="utf-8")

    hook_py = agents_dir / "hook_policy.py"
    hook_py.write_text(_render_readonly_hook_script(), encoding="utf-8")
    _install_hook_launcher(agents_dir, hook_py, "planning-read-only-policy")

    return audit_log


def install_readonly_policy_hook(
    workspace_root: Path,
    protect_company_control: bool = True,
) -> Path:
    """Install a strict fail-closed read-only PreToolUse hook for non-mutating specialist agents."""
    agents_dir = workspace_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    audit_log = workspace_root / ".runs" / "readonly_hook_audit.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)

    policy_config = {
        "mode": "strict_read_only",
        "workspace_root": str(workspace_root.resolve()),
        "protect_company_control": protect_company_control,
        "allow_send_message": False,
        "audit_log_path": str(audit_log.resolve()),
    }
    (agents_dir / "policy_config.json").write_text(json.dumps(policy_config, indent=2), encoding="utf-8")

    hook_py = agents_dir / "hook_policy.py"
    hook_py.write_text(_render_readonly_hook_script(), encoding="utf-8")
    _install_hook_launcher(agents_dir, hook_py, "specialist-read-only-policy")

    return audit_log
