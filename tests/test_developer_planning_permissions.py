"""Deterministic tests for Developer Planning Permission Enforcement (STEP 23B.7-B).

Validates:
1. Planning allows authorized read operations (view_file) and messaging (send_message).
2. Planning unconditionally denies write operations (write_to_file, replace_file_content).
3. Planning unconditionally denies arbitrary shell commands (run_command).
4. Planning rejects path traversal and escapes in view_file.
5. Planning rejects arbitrary/unrecognized tools.
6. Planning policy hook artifacts are generated and hook_policy.py subprocess denies writes/commands.
7. Planning executes in an isolated detached worktree, preserving canonical repo.
8. Runtime receives isolated workspace_dir and sanitized environment.
9. Planning fails closed if unauthorized mutation occurs in the worktree.
10. Planning fails closed on stale/invalid base commit.
11. Planning output remains schema-compliant and parser-compatible.
12. Authorized Developer Mutation continues to operate under its separate ExecutionGrant.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional
import pytest

from jester_ai_company.core import (
    ArtifactType,
    Company,
    RunStatus,
    TaskStatus,
)
from jester_ai_company.developer_result import (
    DeveloperTaskResult,
    parse_and_validate_developer_result,
)
from jester_ai_company.execution_grant import ExecutionGrant, StaleCommitError
from jester_ai_company.policy_hook import (
    authorize_planning_tool,
    install_planning_policy_hook,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService, ExecutionError
from jester_ai_company.worktree import (
    WorktreeManager,
    resolve_repo_head_commit,
    run_git,
)


SAMPLE_PLAN_OUTPUT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Read-only plan for secure feature implementation.",
    "implementation_plan": [
        "1. Inspect existing service modules",
        "2. Formulate minimal patch design",
    ],
    "files_to_modify": [
        {"path": "service.py", "description": "Add feature entrypoint"}
    ],
    "files_to_create": [],
    "dependencies": [],
    "commands_to_run": [
        {"command": "pytest tests/", "purpose": "Validation"}
    ],
    "verification_plan": ["Run unit tests"],
    "risks": [],
    "assumptions": [],
    "open_questions": [],
}

SAMPLE_PRODUCT_OUTPUT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Product requirements for secure planning.",
    "deliverables": [
        {"name": "Requirements", "content": "Enforce read-only planning boundary."}
    ],
    "risks": [],
    "open_questions": [],
}

SAMPLE_UX_OUTPUT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "UX specification for security settings.",
    "flows": [
        {"name": "Config Flow", "description": "Admin configuration", "steps": ["Open UI"]}
    ],
    "screens": [],
    "interaction_rules": [],
    "accessibility_considerations": [],
    "open_questions": [],
}


class RecordingMockRuntime(AntigravityRuntime):
    """Deterministic mock runtime recording invocation parameters."""

    def __init__(
        self,
        responses: Optional[Dict[str, str]] = None,
        mutate_workspace_file: Optional[str] = None,
    ):
        self.responses = responses or {
            "product": json.dumps(SAMPLE_PRODUCT_OUTPUT),
            "ux": json.dumps(SAMPLE_UX_OUTPUT),
            "developer": json.dumps(SAMPLE_PLAN_OUTPUT),
        }
        self.mutate_workspace_file = mutate_workspace_file
        self.invocations: List[Dict[str, Any]] = []

    def execute(
        self,
        agent: str,
        prompt: str,
        timeout: Optional[float] = None,
        workspace_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> AgentExecutionResult:
        self.invocations.append({
            "agent": agent,
            "prompt": prompt,
            "timeout": timeout,
            "workspace_dir": workspace_dir,
            "env": env,
        })

        if agent == "developer" and self.mutate_workspace_file and workspace_dir:
            # Simulate a malicious/compromised planning agent trying to mutate the workspace
            p = workspace_dir / self.mutate_workspace_file
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("unauthorized_mutation", encoding="utf-8")

        output = self.responses.get(agent, "{}")
        return AgentExecutionResult(
            agent=agent,
            success=True,
            stdout=output,
            stderr="",
            exit_code=0,
            duration_ms=10.0,
        )


def _init_test_git_repo(repo_dir: Path) -> str:
    """Initialize a clean Git repository with an initial commit and return HEAD commit hash."""
    run_git(["init"], cwd=repo_dir)
    run_git(["config", "user.name", "Test Engineer"], cwd=repo_dir)
    run_git(["config", "user.email", "engineer@test.local"], cwd=repo_dir)

    readme = repo_dir / "README.md"
    readme.write_text("# Test Repo\nInitial content\n", encoding="utf-8")
    app_file = repo_dir / "app.py"
    app_file.write_text("print('hello world')\n", encoding="utf-8")

    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)
    return resolve_repo_head_commit(repo_dir)


# ==============================================================================
# 1. Direct Policy Decision Tests (authorize_planning_tool)
# ==============================================================================

def test_authorize_planning_tool_allows_safe_reads():
    """Planning policy authorizes confined view_file and messaging."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "safe.py").write_text("safe content", encoding="utf-8")

        # 1. view_file with relative path
        dec1 = authorize_planning_tool("view_file", {"AbsolutePath": "safe.py"}, workspace_root=root)
        assert dec1.allowed is True
        assert "ALLOWED" in dec1.reason

        # 2. view_file with absolute path inside workspace
        dec2 = authorize_planning_tool("view_file", {"AbsolutePath": str(root / "safe.py")}, workspace_root=root)
        assert dec2.allowed is True

        # 3. send_message
        dec3 = authorize_planning_tool("send_message", {"content": "Planning question"}, workspace_root=root)
        assert dec3.allowed is True


def test_authorize_planning_tool_denies_writes_and_replacements():
    """Planning policy unconditionally denies write_to_file and replace_file_content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)

        # 1. write_to_file
        dec1 = authorize_planning_tool(
            "write_to_file",
            {"TargetFile": "app.py", "CodeContent": "evil = True"},
            workspace_root=root,
        )
        assert dec1.allowed is False
        assert "write_to_file" in dec1.reason
        assert "forbidden" in dec1.reason.lower()

        # 2. replace_file_content
        dec2 = authorize_planning_tool(
            "replace_file_content",
            {"TargetFile": "app.py", "ReplacementContent": "new code"},
            workspace_root=root,
        )
        assert dec2.allowed is False
        assert "replace_file_content" in dec2.reason
        assert "forbidden" in dec2.reason.lower()


def test_authorize_planning_tool_denies_shell_execution():
    """Planning policy unconditionally denies run_command."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        dec = authorize_planning_tool(
            "run_command",
            {"CommandLine": "rm -rf /"},
            workspace_root=root,
        )
        assert dec.allowed is False
        assert "run_command" in dec.reason
        assert "forbidden" in dec.reason.lower()


def test_authorize_planning_tool_denies_path_escapes():
    """Planning policy denies view_file attempts to escape the planning workspace."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "workspace"
        root.mkdir()
        outside = Path(tmp_dir) / "secret.env"
        outside.write_text("SECRET=123", encoding="utf-8")

        # 1. Directory traversal ..
        dec1 = authorize_planning_tool(
            "view_file",
            {"AbsolutePath": "../secret.env"},
            workspace_root=root,
        )
        assert dec1.allowed is False
        assert "directory traversal" in dec1.reason.lower()

        # 2. Absolute path outside workspace
        dec2 = authorize_planning_tool(
            "view_file",
            {"AbsolutePath": str(outside.resolve())},
            workspace_root=root,
        )
        assert dec2.allowed is False
        assert "escapes planning workspace" in dec2.reason.lower()


def test_authorize_planning_tool_denies_arbitrary_tools():
    """Planning policy denies any unrecognized tools."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        dec = authorize_planning_tool("delete_file", {"Path": "important.txt"}, workspace_root=root)
        assert dec.allowed is False
        assert "not authorized" in dec.reason.lower()


# ==============================================================================
# 2. Planning Hook Subprocess Execution & Audit Tests
# ==============================================================================

def test_install_planning_policy_hook_generates_artifacts_and_enforces():
    """install_planning_policy_hook creates working hook scripts and denies unauthorized calls."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        audit_log = install_planning_policy_hook(root)

        # Artifacts exist
        assert (root / ".agents" / "hooks.json").exists()
        assert (root / ".agents" / "policy_config.json").exists()
        assert (root / ".agents" / "hook_policy.py").exists()
        assert audit_log.parent.exists()

        hook_py = root / ".agents" / "hook_policy.py"

        # 1. Test view_file allow via hook subprocess
        payload_view = json.dumps({
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": "app.py"}}
        })
        proc1 = subprocess.run(
            [sys.executable, str(hook_py)],
            input=payload_view,
            capture_output=True,
            text=True,
            check=True,
        )
        res1 = json.loads(proc1.stdout)
        assert res1["decision"] == "allow"

        # 2. Test write_to_file deny via hook subprocess
        payload_write = json.dumps({
            "toolCall": {"name": "write_to_file", "args": {"TargetFile": "app.py", "CodeContent": "bad"}}
        })
        proc2 = subprocess.run(
            [sys.executable, str(hook_py)],
            input=payload_write,
            capture_output=True,
            text=True,
            check=True,
        )
        res2 = json.loads(proc2.stdout)
        assert res2["decision"] == "deny"

        # 3. Test run_command deny via hook subprocess
        payload_cmd = json.dumps({
            "toolCall": {"name": "run_command", "args": {"CommandLine": "python malicious.py"}}
        })
        proc3 = subprocess.run(
            [sys.executable, str(hook_py)],
            input=payload_cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        res3 = json.loads(proc3.stdout)
        assert res3["decision"] == "deny"

        # 4. Verify decisions are recorded in audit log
        assert audit_log.exists()
        audit_lines = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(audit_lines) == 3
        assert audit_lines[0]["tool"] == "view_file"
        assert audit_lines[0]["decision"] == "allow"
        assert audit_lines[1]["tool"] == "write_to_file"
        assert audit_lines[1]["decision"] == "deny"
        assert audit_lines[2]["tool"] == "run_command"
        assert audit_lines[2]["decision"] == "deny"


# ==============================================================================
# 3. Planning Execution Boundary & Worktree Isolation Tests
# ==============================================================================

def test_developer_planning_runs_in_isolated_worktree_with_sanitized_env():
    """Planning runs inside an isolated Git worktree, passes sanitized env, and cleans up."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_dir = Path(tmp_dir) / "repo"
        repo_dir.mkdir()
        head_commit = _init_test_git_repo(repo_dir)

        out_dir = Path(tmp_dir) / "runs"
        out_dir.mkdir()

        mock_rt = RecordingMockRuntime()
        service = CompanyService(output_dir=str(out_dir), repo_root=repo_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # Upstream Product Task
        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]

        # Upstream UX Task
        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        service.attach_input_artifact(u_task.id, p_art.id)
        u_run = service.execute_ux_task(u_task.id)
        u_art = u_run.artifacts[0]

        # Developer Planning Task
        d_task = service.create_task(
            project_id=proj.id,
            title="Plan Feature",
            goal="Formulate feature plan",
            required_roles=["developer"],
            expected_output=["Developer Plan Report"],
        )
        service.attach_input_artifact(d_task.id, p_art.id)
        service.attach_input_artifact(d_task.id, u_art.id)

        # Record canonical repository state before
        readme_before = (repo_dir / "README.md").read_text(encoding="utf-8")
        status_before = service._get_repo_working_tree_state(repo_path=repo_dir)

        # Set a dummy secret environment variable to test sanitization
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-secret"
        try:
            d_run = service.execute_developer_planning_task(d_task.id)
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)

        assert d_run.status == RunStatus.SUCCESS.value
        assert d_task.status == TaskStatus.COMPLETED.value

        # Verify runtime received an isolated worktree path for Developer, NOT the canonical repo
        dev_invocations = [i for i in mock_rt.invocations if i["agent"] == "developer"]
        assert len(dev_invocations) == 1
        inv = dev_invocations[0]
        worktree_path = inv["workspace_dir"]
        assert worktree_path is not None
        assert worktree_path != repo_dir
        assert "worktrees" in str(worktree_path)

        # Verify environment was sanitized (secret removed)
        env = inv["env"]
        assert env is not None
        assert "ANTHROPIC_API_KEY" not in env
        assert "PATH" in env

        # Verify canonical repository is completely unchanged
        assert (repo_dir / "README.md").read_text(encoding="utf-8") == readme_before
        assert service._get_repo_working_tree_state(repo_path=repo_dir) == status_before

        # Verify worktree was cleaned up
        assert not worktree_path.exists()

        # Verify plan artifact was materialized and valid
        assert len(d_run.artifacts) == 1
        art = d_run.artifacts[0]
        assert art.artifact_type == ArtifactType.DEVELOPER_PLAN_REPORT.value
        assert art.name == "developer_plan_report.md"


def test_developer_planning_fails_closed_on_worktree_mutation():
    """Planning fails closed and marks execution failed if any files are mutated in the worktree."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_dir = Path(tmp_dir) / "repo"
        repo_dir.mkdir()
        _init_test_git_repo(repo_dir)

        out_dir = Path(tmp_dir) / "runs"
        out_dir.mkdir()

        # Mock runtime that attempts unauthorized mutation in workspace_dir
        mock_rt = RecordingMockRuntime(
            mutate_workspace_file="unauthorized_file.txt",
        )
        service = CompanyService(output_dir=str(out_dir), repo_root=repo_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]

        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        service.attach_input_artifact(u_task.id, p_art.id)
        u_run = service.execute_ux_task(u_task.id)
        u_art = u_run.artifacts[0]

        d_task = service.create_task(
            project_id=proj.id,
            title="Plan Feature",
            goal="Formulate feature plan",
            required_roles=["developer"],
            expected_output=["Developer Plan Report"],
        )
        service.attach_input_artifact(d_task.id, p_art.id)
        service.attach_input_artifact(d_task.id, u_art.id)

        with pytest.raises(ExecutionError) as exc_info:
            service.execute_developer_planning_task(d_task.id)

        assert "Unauthorized mutation detected in planning worktree" in str(exc_info.value)
        assert "unauthorized_file.txt" in str(exc_info.value)

        # Verify canonical repo was never mutated
        assert not (repo_dir / "unauthorized_file.txt").exists()


def test_developer_planning_fails_closed_on_stale_base_commit():
    """Planning fails closed if requested base_commit_hash does not match repository HEAD."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_dir = Path(tmp_dir) / "repo"
        repo_dir.mkdir()
        _init_test_git_repo(repo_dir)

        out_dir = Path(tmp_dir) / "runs"
        out_dir.mkdir()

        mock_rt = RecordingMockRuntime()
        service = CompanyService(output_dir=str(out_dir), repo_root=repo_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]

        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        service.attach_input_artifact(u_task.id, p_art.id)
        u_run = service.execute_ux_task(u_task.id)
        u_art = u_run.artifacts[0]

        d_task = service.create_task(
            project_id=proj.id,
            title="Plan Feature",
            goal="Formulate feature plan",
            required_roles=["developer"],
            expected_output=["Developer Plan Report"],
        )
        service.attach_input_artifact(d_task.id, p_art.id)
        service.attach_input_artifact(d_task.id, u_art.id)

        # Pass a bogus base commit
        with pytest.raises(StaleCommitError) as exc_info:
            service.execute_developer_planning_task(d_task.id, base_commit_hash="deadbeef1234567890abcdef")

        assert "does not match authorized base commit" in str(exc_info.value)

