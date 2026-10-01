"""Execution-scoped Antigravity PreToolUse hook installer and write authorization policy.

Provides deterministic tool-call interception for bounded Developer code mutation.
Installs an execution-scoped PreToolUse hook into the isolated worktree that intercepts
mutation tools (`write_to_file`, `replace_file_content`, `run_command`) and validates
them strictly against an immutable ExecutionGrant before any filesystem mutation occurs.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

from .execution_grant import ExecutionGrant
from .worktree import (
    WorktreeConfinementError,
    is_protected_path,
    is_test_file,
    verify_workspace_path,
)


@dataclass
class WriteAuthorizationDecision:
    """Outcome of a pre-mutation tool call authorization check."""
    allowed: bool
    reason: str
    target_path: Optional[Path] = None
    relative_path: Optional[str] = None


def normalize_rel_path(path_str: str) -> str:
    """Normalize a path to posix format with leading/trailing slashes removed."""
    return Path(path_str).as_posix().lstrip("/").rstrip("/")


def authorize_tool_mutation(
    tool_name: str,
    args: Dict[str, Any],
    workspace_root: Path,
    grant: ExecutionGrant,
    protect_company_control: bool = True,
) -> WriteAuthorizationDecision:
    """Deterministically authorize or deny a tool mutation before execution.
    
    This function implements the hard security algorithm:
    1. Rejects run_command unconditionally during mutation.
    2. Rejects any non-mutation tool calls not explicitly permitted.
    3. For write_to_file, replace_file_content:
       - Requires and parses TargetFile.
       - Verifies path confinement inside workspace_root (rejects absolute, traversal, escapes).
       - Checks protected-path policy (.git, .agents, .env*, credentials, company control).
       - Checks test modification policy (rejects tests unless allow_test_modifications=True
         AND path is in approved files).
       - Verifies existence on disk:
         * Existing file must be in grant.approved_files_to_modify.
         * New file must be in grant.approved_files_to_create.
       - Enforces max_bytes_written budget.
    """
    # 1. Unconditionally deny run_command
    if tool_name == "run_command":
        return WriteAuthorizationDecision(
            allowed=False,
            reason="ExecutionPolicy: PreToolUse DENIED - run_command execution is strictly forbidden in STEP 13B-2.",
        )

    # 2. Only allow recognized mutation tools (and view_file for reading)
    if tool_name not in ("write_to_file", "replace_file_content"):
        if tool_name == "view_file":
            return WriteAuthorizationDecision(allowed=True, reason="Read-only tool permitted.")
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - tool '{tool_name}' is not authorized for Developer mutation.",
        )

    # 3. Parse TargetFile
    target_raw = args.get("TargetFile")
    if not target_raw or not isinstance(target_raw, str) or not target_raw.strip():
        return WriteAuthorizationDecision(
            allowed=False,
            reason="ExecutionPolicy: PreToolUse DENIED - TargetFile argument is missing or empty.",
        )

    cleaned_target = target_raw.strip().strip('"').strip("'")
    p = Path(cleaned_target)
    root_resolved = workspace_root.resolve()

    # 4. Resolve and verify workspace confinement
    if p.is_absolute() or (len(p.parts) > 0 and ":" in p.parts[0]):
        try:
            resolved_path = p.resolve()
        except Exception as exc:
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED path confinement check: {exc}",
            )
        try:
            if not resolved_path.is_relative_to(root_resolved):
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED path confinement check: Path '{cleaned_target}' is absolute and escapes workspace root '{root_resolved}'.",
                )
        except AttributeError:
            try:
                resolved_path.relative_to(root_resolved)
            except ValueError:
                return WriteAuthorizationDecision(
                    allowed=False,
                    reason=f"ExecutionPolicy: PreToolUse DENIED path confinement check: Path '{cleaned_target}' escapes workspace root.",
                )
        if resolved_path.is_symlink() or os.path.islink(str(resolved_path)):
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED path confinement check: Path '{cleaned_target}' is a symlink or junction.",
            )
    else:
        try:
            resolved_path = verify_workspace_path(cleaned_target, workspace_root)
        except WorktreeConfinementError as exc:
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED path confinement check: {exc}",
            )

    # Calculate relative posix path for policy matching
    try:
        rel_path = resolved_path.relative_to(root_resolved).as_posix()
    except ValueError:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - path '{cleaned_target}' escapes workspace root.",
        )

    # 5. Protected Path Policy Check
    if is_protected_path(rel_path, protect_company_control=protect_company_control):
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - path '{rel_path}' is a protected repository path.",
            target_path=resolved_path,
            relative_path=rel_path,
        )

    # 6. Test File Modification Policy Check
    if is_test_file(rel_path):
        if not grant.allow_test_modifications:
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED - test modification forbidden by default for '{rel_path}'.",
                target_path=resolved_path,
                relative_path=rel_path,
            )

    # 7. Check write authorization: existing file vs new file
    # Normalize granted paths for case-insensitive Windows matching
    approved_mod = {normalize_rel_path(f).lower() for f in grant.approved_files_to_modify}
    approved_create = {normalize_rel_path(f).lower() for f in grant.approved_files_to_create}
    rel_lower = rel_path.lower()

    file_exists = resolved_path.is_file()

    if file_exists:
        if rel_lower not in approved_mod:
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED - existing file '{rel_path}' is not in approved_files_to_modify.",
                target_path=resolved_path,
                relative_path=rel_path,
            )
    else:
        if rel_lower not in approved_create:
            return WriteAuthorizationDecision(
                allowed=False,
                reason=f"ExecutionPolicy: PreToolUse DENIED - new file '{rel_path}' is not in approved_files_to_create.",
                target_path=resolved_path,
                relative_path=rel_path,
            )

    # 8. Check Write Size Budget
    content_len = 0
    if tool_name == "write_to_file":
        code_content = args.get("CodeContent", "")
        content_len = len(code_content.encode("utf-8")) if isinstance(code_content, str) else 0
    elif tool_name == "replace_file_content":
        repl_content = args.get("ReplacementContent", "")
        content_len = len(repl_content.encode("utf-8")) if isinstance(repl_content, str) else 0

    if content_len > grant.max_bytes_written:
        return WriteAuthorizationDecision(
            allowed=False,
            reason=f"ExecutionPolicy: PreToolUse DENIED - write size {content_len} bytes exceeds grant limit {grant.max_bytes_written} bytes.",
            target_path=resolved_path,
            relative_path=rel_path,
        )

    # All checks passed
    return WriteAuthorizationDecision(
        allowed=True,
        reason="ExecutionPolicy: PreToolUse ALLOWED - authorized by ExecutionGrant.",
        target_path=resolved_path,
        relative_path=rel_path,
    )


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
    
    Returns the path to the audit log that will record all hook decisions.
    """
    agents_dir = workspace_root / ".agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    audit_log = workspace_root / ".runs" / "hook_audit.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)

    # 1. Policy configuration
    policy_config = {
        "grant_id": grant.grant_id,
        "workspace_root": str(workspace_root.resolve()),
        "approved_files_to_modify": list(grant.approved_files_to_modify),
        "approved_files_to_create": list(grant.approved_files_to_create),
        "allow_test_modifications": grant.allow_test_modifications,
        "protect_company_control": protect_company_control,
        "max_bytes_written": grant.max_bytes_written,
        "max_files_changed": grant.max_files_changed,
        "audit_log_path": str(audit_log.resolve()),
    }
    policy_config_file = agents_dir / "policy_config.json"
    policy_config_file.write_text(json.dumps(policy_config, indent=2), encoding="utf-8")

    # 2. Hook policy script
    hook_py = agents_dir / "hook_policy.py"
    hook_py_code = """import json
import os
from pathlib import Path
import sys

def run():
    config_file = Path(__file__).resolve().parent / "policy_config.json"
    if not config_file.exists():
        resp = {"decision": "deny", "reason": "ExecutionPolicy: missing policy_config.json"}
        sys.stdout.write(json.dumps(resp))
        sys.stdout.flush()
        return

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception as e:
        resp = {"decision": "deny", "reason": f"ExecutionPolicy: failed to parse policy_config: {e}"}
        sys.stdout.write(json.dumps(resp))
        sys.stdout.flush()
        return

    raw_input = sys.stdin.read()
    try:
        data = json.loads(raw_input)
    except Exception as e:
        resp = {"decision": "deny", "reason": f"ExecutionPolicy: invalid hook payload JSON: {e}"}
        sys.stdout.write(json.dumps(resp))
        sys.stdout.flush()
        return

    tool_call = data.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    workspace_root = Path(config["workspace_root"]).resolve()
    audit_log = Path(config["audit_log_path"])

    # Decision logic
    if tool_name == "run_command":
        decision = {"decision": "deny", "reason": "ExecutionPolicy: PreToolUse DENIED - run_command execution is strictly forbidden in STEP 13B-2."}
    elif tool_name == "view_file":
        decision = {"decision": "allow"}
    elif tool_name in ("write_to_file", "replace_file_content"):
        target_raw = args.get("TargetFile")
        if not target_raw or not isinstance(target_raw, str) or not target_raw.strip():
            decision = {"decision": "deny", "reason": "ExecutionPolicy: PreToolUse DENIED - missing or empty TargetFile"}
        else:
            cleaned = target_raw.strip().strip('"').strip("'")
            p = Path(cleaned)
            # Confinement check
            if p.is_absolute() or (len(p.parts) > 0 and ":" in p.parts[0]):
                try:
                    resolved = p.resolve()
                except Exception as e:
                    resolved = None
                if resolved is None or not resolved.is_relative_to(workspace_root):
                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED path confinement check - path '{cleaned}' is outside workspace root"}
                elif resolved.is_symlink() or os.path.islink(str(resolved)):
                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED path confinement check - path '{cleaned}' is a symlink or junction"}
                else:
                    rel = resolved.relative_to(workspace_root).as_posix()
                    rel_lower = rel.lower()

                    # Protected path check
                    is_prot = (
                        rel_lower == ".git" or rel_lower.startswith(".git/") or
                        rel_lower == ".agents" or rel_lower.startswith(".agents/") or
                        rel_lower == ".env" or rel_lower.startswith(".env.") or "/.env" in rel_lower or
                        "credential" in rel_lower or "secret" in rel_lower or rel_lower.endswith(".pem") or rel_lower.endswith(".key") or
                        (config.get("protect_company_control") and (rel_lower == "jester_ai_company" or rel_lower.startswith("jester_ai_company/")))
                    )
                    if is_prot:
                        decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - '{rel}' is a protected path"}
                    else:
                        # Test file check
                        is_test = (
                            rel_lower.startswith("tests/") or
                            rel_lower.startswith("test/") or
                            "/tests/" in rel_lower or
                            Path(rel_lower).name.startswith("test_") or
                            Path(rel_lower).name.endswith("_test.py")
                        )
                        if is_test and not config.get("allow_test_modifications"):
                            decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - test modification forbidden for '{rel}'"}
                        else:
                            app_mod = [f.strip("/").lower() for f in config.get("approved_files_to_modify", [])]
                            app_create = [f.strip("/").lower() for f in config.get("approved_files_to_create", [])]
                            exists = resolved.is_file()

                            if exists:
                                if rel_lower not in app_mod:
                                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - existing file '{rel}' is not in approved_files_to_modify"}
                                else:
                                    decision = {"decision": "allow"}
                            else:
                                if rel_lower not in app_create:
                                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - new file '{rel}' is not in approved_files_to_create"}
                                else:
                                    decision = {"decision": "allow"}
            else:
                if ".." in p.parts:
                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - path '{cleaned}' contains directory traversal"}
                else:
                    try:
                        resolved = (workspace_root / p).resolve()
                        if not resolved.is_relative_to(workspace_root):
                            decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED path confinement check - path '{cleaned}' escapes workspace root"}
                        elif resolved.is_symlink() or os.path.islink(str(resolved)):
                            decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED path confinement check - path '{cleaned}' is a symlink or junction"}
                        else:
                            rel = resolved.relative_to(workspace_root).as_posix()
                            rel_lower = rel.lower()

                            # Protected path check
                            is_prot = (
                                rel_lower == ".git" or rel_lower.startswith(".git/") or
                                rel_lower == ".agents" or rel_lower.startswith(".agents/") or
                                rel_lower == ".env" or rel_lower.startswith(".env.") or "/.env" in rel_lower or
                                "credential" in rel_lower or "secret" in rel_lower or rel_lower.endswith(".pem") or rel_lower.endswith(".key") or
                                (config.get("protect_company_control") and (rel_lower == "jester_ai_company" or rel_lower.startswith("jester_ai_company/")))
                            )
                            if is_prot:
                                decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - '{rel}' is a protected path"}
                            else:
                                # Test file check
                                is_test = (
                                    rel_lower.startswith("tests/") or
                                    rel_lower.startswith("test/") or
                                    "/tests/" in rel_lower or
                                    Path(rel_lower).name.startswith("test_") or
                                    Path(rel_lower).name.endswith("_test.py")
                                )
                                if is_test and not config.get("allow_test_modifications"):
                                    decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - test modification forbidden for '{rel}'"}
                                else:
                                    app_mod = [f.strip("/").lower() for f in config.get("approved_files_to_modify", [])]
                                    app_create = [f.strip("/").lower() for f in config.get("approved_files_to_create", [])]
                                    exists = resolved.is_file()

                                    if exists:
                                        if rel_lower not in app_mod:
                                            decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - existing file '{rel}' is not in approved_files_to_modify"}
                                        else:
                                            decision = {"decision": "allow"}
                                    else:
                                        if rel_lower not in app_create:
                                            decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - new file '{rel}' is not in approved_files_to_create"}
                                        else:
                                            decision = {"decision": "allow"}
                    except Exception as e:
                        decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse validation error: {e}"}
    else:
        decision = {"decision": "deny", "reason": f"ExecutionPolicy: PreToolUse DENIED - tool '{tool_name}' not permitted"}

    # Audit logging
    try:
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

    sys.stdout.write(json.dumps(decision))
    sys.stdout.flush()

if __name__ == "__main__":
    run()
"""
    hook_py.write_text(hook_py_code, encoding="utf-8")

    # 3. Script launcher wrapper (hook.bat or hook.sh)
    if sys.platform == "win32":
        hook_cmd = agents_dir / "hook.bat"
        hook_cmd.write_text(f'@"{sys.executable}" "{hook_py}"\n', encoding="utf-8")
        command_str = str(hook_cmd)
    else:
        hook_cmd = agents_dir / "hook.sh"
        hook_cmd.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{hook_py}" "$@"\n', encoding="utf-8")
        hook_cmd.chmod(0o755)
        command_str = str(hook_cmd)

    # 4. hooks.json
    hooks_json = agents_dir / "hooks.json"
    hooks_spec = {
        "execution-grant-policy": {
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

    return audit_log
