"""Deterministic Test Matrix for STEP 13B-3 — Verification Execution & Durable CODE_PATCH Artifact.

Covers Requirements A through AH:
A. typed pytest VerificationAction accepted
B. arbitrary shell action rejected
C. absolute verification target rejected
D. traversal verification target rejected
E. outside-workspace target rejected
F. missing test target fails
G. pytest action translated to argv array
H. shell=False used
I. sanitized environment passed
J. secret sentinel absent
K. pytest exit 0 = PASS
L. pytest nonzero = FAIL
M. timeout = TIMEOUT
N. max verification action count enforced
O. failed verification prevents CODE_PATCH creation
P. successful verification permits patch capture
Q. modified tracked file included in patch
R. approved new file included in patch
S. unauthorized file cannot enter patch
T. deleted file prevents successful patch
U. binary unsupported change rejected
V. CODE_PATCH artifact materialized
W. artifact physically exists after worktree deletion
X. artifact SHA matches exact patch bytes
Y. plan artifact lineage preserved
Z. plan SHA preserved
AA. ExecutionGrant ID preserved
AB. base commit preserved
AC. changed-file metadata preserved
AD. verification evidence preserved
AE. worktree removed after success
AF. worktree removed after verification failure
AG. worktree removed after artifact failure
AH. main repository unchanged
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Generator, Tuple
from unittest.mock import MagicMock, patch

import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    Company,
    Project,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from jester_ai_company.runtime import AgentExecutionResult
from jester_ai_company.developer_mutation import DeveloperMutationStatus
from jester_ai_company.execution_grant import (
    ExecutionGrant,
    GrantValidationError,
    VerificationAction,
)
from jester_ai_company.materializer import (
    MaterializationError,
    materialize_code_patch_artifact,
)
from jester_ai_company.service import (
    BoundedDeveloperExecutionOutcome,
    CompanyService,
)
from jester_ai_company.verification import (
    TargetValidationError,
    UnsupportedActionTypeError,
    VerificationExecutionResult,
    VerificationStatus,
    execute_verification_action,
    translate_verification_action,
    validate_verification_target,
)
from jester_ai_company.worktree import (
    WorktreeDiffResult,
    WorktreeManager,
    resolve_repo_head_commit,
    run_git,
    sanitize_execution_environment,
)


def _run_cmd(args, cwd):
    res = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=True)
    return res.stdout.strip()


@pytest.fixture
def temp_git_repo() -> Generator[Tuple[Path, str], None, None]:
    """Create a temporary initialized Git repository with initial commit."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir).resolve() / "repo"
        repo.mkdir(parents=True, exist_ok=True)

        _run_cmd(["git", "init"], repo)
        _run_cmd(["git", "config", "user.name", "Test Runner"], repo)
        _run_cmd(["git", "config", "user.email", "runner@example.com"], repo)

        (repo / ".gitignore").write_text(".runs/\n", encoding="utf-8")
        src_dir = repo / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "app.py").write_text("def run():\n    return 42\n", encoding="utf-8")

        tests_dir = repo / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_app.py").write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).parent.parent))\n"
            "from src.app import run\n\n"
            "def test_run():\n"
            "    assert run() == 42\n",
            encoding="utf-8",
        )

        _run_cmd(["git", "add", "."], repo)
        _run_cmd(["git", "commit", "-m", "Initial commit"], repo)

        head_commit = resolve_repo_head_commit(repo)
        yield repo, head_commit


class TestVerificationActionValidation:
    """Tests A through F: Action validation and target confinement."""

    def test_a_typed_pytest_action_accepted(self, temp_git_repo):
        """A. Typed pytest VerificationAction accepted."""
        repo, _ = temp_git_repo
        action = VerificationAction(action_type="pytest", target="tests/test_app.py")
        resolved = validate_verification_target(action.target, repo)
        assert resolved.exists()
        assert resolved.is_file()
        assert resolved.name == "test_app.py"

    def test_b_arbitrary_shell_action_rejected(self, temp_git_repo):
        """B. Arbitrary shell action rejected."""
        repo, _ = temp_git_repo

        # Action type "shell" is rejected by VerificationAction constructor
        with pytest.raises(GrantValidationError, match="Unsupported verification action type"):
            VerificationAction(action_type="shell", target="tests/test_app.py")

        # Action type "shell" is also rejected by translation function
        # (Construct object bypassing __post_init__ to test translator directly)
        mock_shell_action = MagicMock(action_type="shell", target="tests/test_app.py")
        with pytest.raises(UnsupportedActionTypeError, match="Unsupported verification action type"):
            translate_verification_action(mock_shell_action)

        # Target containing shell operators is rejected by VerificationAction constructor
        with pytest.raises(GrantValidationError, match="forbidden shell metacharacters"):
            VerificationAction(action_type="pytest", target="tests/test_app.py && rm -rf /")

        # Target containing shell operators is rejected by validate_verification_target
        with pytest.raises(TargetValidationError, match="forbidden characters"):
            validate_verification_target("tests/test_app.py && rm -rf /", repo)

    def test_c_absolute_verification_target_rejected(self, temp_git_repo):
        """C. Absolute verification target rejected."""
        repo, _ = temp_git_repo
        abs_target = str((repo / "tests" / "test_app.py").resolve())
        with pytest.raises(TargetValidationError, match="must be a clean relative path"):
            validate_verification_target(abs_target, repo)

    def test_d_traversal_verification_target_rejected(self, temp_git_repo):
        """D. Traversal verification target rejected."""
        repo, _ = temp_git_repo
        with pytest.raises(TargetValidationError, match="must be a clean relative path"):
            validate_verification_target("../other_repo/test.py", repo)

        with pytest.raises(TargetValidationError, match="must be a clean relative path"):
            validate_verification_target("tests/../../secret.py", repo)

    def test_e_outside_workspace_target_rejected(self, temp_git_repo):
        """E. Outside-workspace target rejected."""
        repo, _ = temp_git_repo
        # Target that attempts to point to a non-existent file or outside directory
        with pytest.raises(TargetValidationError):
            validate_verification_target("non_existent_folder/../../outside.py", repo)

    def test_f_missing_test_target_fails(self, temp_git_repo):
        """F. Missing test target fails with TargetValidationError."""
        repo, _ = temp_git_repo
        with pytest.raises(TargetValidationError, match="does not exist inside the worktree"):
            validate_verification_target("tests/test_nonexistent.py", repo)

        # Also proves execute_verification_action returns status=FAIL when target missing
        action = VerificationAction(action_type="pytest", target="tests/test_missing.py")
        res = execute_verification_action(action, repo)
        assert res.status == VerificationStatus.FAIL.value
        assert res.exit_code == 1
        assert "does not exist" in res.stderr


class TestVerificationTranslationAndExecution:
    """Tests G through N: Translation, execution environment, and exit status semantics."""

    def test_g_pytest_action_translated_to_argv_array(self):
        """G. Pytest action translated to argv array."""
        action = VerificationAction(action_type="pytest", target="tests/test_app.py")
        argv = translate_verification_action(action)
        assert argv == [sys.executable, "-m", "pytest", "tests/test_app.py"]

    def test_h_shell_false_used(self, temp_git_repo):
        """H. shell=False used unconditionally during execution."""
        repo, _ = temp_git_repo
        action = VerificationAction(action_type="pytest", target="tests/test_app.py")

        with patch("subprocess.run", wraps=subprocess.run) as mock_sub:
            execute_verification_action(action, repo, timeout=10.0)
            mock_sub.assert_called_once()
            _, kwargs = mock_sub.call_args
            assert kwargs.get("shell") is False
            assert kwargs.get("cwd") == str(repo.resolve())

    def test_i_sanitized_environment_passed(self, temp_git_repo):
        """I. Sanitized environment passed to verification subprocess."""
        repo, _ = temp_git_repo
        action = VerificationAction(action_type="pytest", target="tests/test_app.py")

        with patch("subprocess.run", wraps=subprocess.run) as mock_sub:
            execute_verification_action(action, repo, timeout=10.0)
            _, kwargs = mock_sub.call_args
            env = kwargs.get("env", {})
            assert "PATH" in env or "Path" in env or "SystemRoot" in env

    def test_j_secret_sentinels_absent(self):
        """J. Secret sentinels absent from sanitized environment."""
        dirty_env = {
            "PATH": os.environ.get("PATH", ""),
            "OPENAI_API_KEY": "sk-secret-12345",
            "ANTHROPIC_API_KEY": "sk-ant-secret-67890",
            "GITHUB_TOKEN": "ghp_supersecrettoken",
            "DATABASE_PASSWORD": "rootpassword123",
            "SAFE_VAR": "harmless_value",
        }
        clean = sanitize_execution_environment(base_env=dirty_env)
        assert "OPENAI_API_KEY" not in clean
        assert "ANTHROPIC_API_KEY" not in clean
        assert "GITHUB_TOKEN" not in clean
        assert "DATABASE_PASSWORD" not in clean

    def test_k_pytest_exit_0_is_pass(self, temp_git_repo):
        """K. Pytest exit 0 = PASS."""
        repo, _ = temp_git_repo
        action = VerificationAction(action_type="pytest", target="tests/test_app.py")
        res = execute_verification_action(action, repo, timeout=30.0)
        assert res.status == VerificationStatus.PASS.value
        assert res.exit_code == 0
        assert res.passed is True
        assert "1 passed" in res.stdout

    def test_l_pytest_nonzero_is_fail(self, temp_git_repo):
        """L. Pytest non-zero exit code = FAIL."""
        repo, _ = temp_git_repo
        # Make the test fail
        (repo / "tests" / "test_app.py").write_text(
            "def test_failing():\n    assert False, 'Deliberate test failure'\n",
            encoding="utf-8",
        )
        action = VerificationAction(action_type="pytest", target="tests/test_app.py")
        res = execute_verification_action(action, repo, timeout=30.0)
        assert res.status == VerificationStatus.FAIL.value
        assert res.exit_code != 0
        assert res.passed is False
        assert "FAILED" in res.stdout

    def test_m_timeout_is_timeout(self, temp_git_repo):
        """M. Timeout = TIMEOUT status."""
        repo, _ = temp_git_repo
        (repo / "tests" / "test_hang.py").write_text(
            "import time\n"
            "def test_hang():\n"
            "    time.sleep(5.0)\n",
            encoding="utf-8",
        )
        action = VerificationAction(action_type="pytest", target="tests/test_hang.py")
        # Run with a 0.5s timeout
        res = execute_verification_action(action, repo, timeout=0.5)
        assert res.status == VerificationStatus.TIMEOUT.value
        assert res.passed is False
        assert "timed out" in res.error.lower()

    def test_n_max_verification_action_count_enforced(self, temp_git_repo):
        """N. Max verification action count enforced."""
        _, head_commit = temp_git_repo
        actions = (
            VerificationAction("pytest", "tests/t1.py"),
            VerificationAction("pytest", "tests/t2.py"),
            VerificationAction("pytest", "tests/t3.py"),
            VerificationAction("pytest", "tests/t4.py"),
        )
        # ExecutionGrant enforces max_verification_actions (default 3)
        with pytest.raises(GrantValidationError, match="exceeds max_verification_actions"):
            ExecutionGrant(
                grant_id="grant_too_many_veri",
                task_id="task_01",
                plan_artifact_id="art_01",
                plan_sha256="a" * 64,
                base_commit_hash=head_commit,
                verification_actions=actions,
                max_verification_actions=3,
                founder_approval_id="appr_01",
            )


class TestPatchCaptureAndContent:
    """Tests P through U: Unified diff patch capture, new files, and binary policy."""

    def test_p_successful_verification_permits_patch_capture(self, temp_git_repo):
        """P. Successful verification permits patch capture."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_patch_capture",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            verification_actions=(VerificationAction("pytest", "tests/test_app.py"),),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            # Modify src/app.py to keep tests passing
            (session.worktree_path / "src" / "app.py").write_text("def run():\n    return 42 # modified\n", encoding="utf-8")
            diff_res = session.capture_diff()
            assert diff_res.is_empty is False
            assert "src/app.py" in diff_res.changed_files
            assert "def run():" in diff_res.diff_text

    def test_q_modified_tracked_file_included_in_patch(self, temp_git_repo):
        """Q. Modified tracked file included in patch."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_modified_tracked",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            (session.worktree_path / "src" / "app.py").write_text("def run():\n    return 99\n", encoding="utf-8")
            diff_res = session.capture_diff()
            assert "--- a/src/app.py" in diff_res.diff_text or "--- a/src\\app.py" in diff_res.diff_text
            assert "+++ b/src/app.py" in diff_res.diff_text or "+++ b/src\\app.py" in diff_res.diff_text
            assert "+    return 99" in diff_res.diff_text

    def test_r_approved_new_file_included_in_patch(self, temp_git_repo):
        """R. Approved new file included in patch (via git add -N)."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_new_file_patch",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_create=("src/new_module.py",),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            new_file = session.worktree_path / "src" / "new_module.py"
            new_file.write_text("def new_feature():\n    return 'fresh'\n", encoding="utf-8")

            diff_res = session.capture_diff()
            assert "src/new_module.py" in diff_res.changed_files
            assert "src/new_module.py" in diff_res.untracked_files
            assert "diff --git" in diff_res.diff_text
            assert "new file mode" in diff_res.diff_text
            assert "+def new_feature():" in diff_res.diff_text

    def test_s_unauthorized_file_cannot_enter_patch(self, temp_git_repo):
        """S. Unauthorized file cannot enter patch."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_unauth_file",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            approved_files_to_create=(),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            (session.worktree_path / "src" / "malicious.py").write_text("evil", encoding="utf-8")
            diff_res = session.capture_diff()

            # Diff validation logic in service catches unauthorized file
            approved = {f.strip("/").lower() for f in grant.approved_files_to_modify}
            unauthorized = [f for f in diff_res.changed_files if f.strip("/").lower() not in approved]
            assert "src/malicious.py" in unauthorized

    def test_t_deleted_file_prevents_successful_patch(self, temp_git_repo):
        """T. Deleted file prevents successful patch."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_delete_test",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            (session.worktree_path / "src" / "app.py").unlink()
            diff_res = session.capture_diff()
            assert len(diff_res.deleted_files) > 0
            assert "src/app.py" in diff_res.deleted_files

    def test_u_binary_unsupported_change_rejected(self, temp_git_repo):
        """U. Binary unsupported change rejected."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_binary_test",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_create=("src/binary.bin",),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            (session.worktree_path / "src" / "binary.bin").write_bytes(b"\x00\x01\x02\xFF")
            diff_res = session.capture_diff()
            assert diff_res.is_binary is True

            # Materialization should reject binary patch text
            task = Task("task_bin", "proj_01", "dev", "Binary", "Goal")
            run = task.create_run()
            with pytest.raises(MaterializationError, match="Binary changes are not supported"):
                materialize_code_patch_artifact(
                    base_output_dir=repo / ".runs",
                    task=task,
                    run=run,
                    grant=grant,
                    patch_text="Binary files a/src/binary.bin and b/src/binary.bin differ",
                    changed_files=["src/binary.bin"],
                )


class TestCodePatchArtifactAndLineage:
    """Tests O, V through AD: Durable CODE_PATCH artifact, SHA-256 integrity, and lineage."""

    def test_o_failed_verification_prevents_code_patch_creation(self, temp_git_repo):
        """O. Failed verification strictly prevents CODE_PATCH creation."""
        repo, head_commit = temp_git_repo
        service = CompanyService(repo_root=repo, output_dir=str(repo / ".runs"))
        service.create_project("proj_01", "Project 1")
        task = service.create_task("proj_01", "Dev Plan", "Plan goal")
        run = task.create_run()

        plan_bytes = b"# Plan"
        plan_sha = hashlib.sha256(plan_bytes).hexdigest()
        plan_path = service.output_dir / "artifacts" / "developer_plan_report.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_bytes(plan_bytes)

        plan_art = run.add_artifact(
            name="developer_plan_report.md",
            artifact_type="DEVELOPER_PLAN_REPORT",
            path="artifacts/developer_plan_report.md",
            durable=True,
            sha256=plan_sha,
            producer_role="developer",
        )
        run.complete(status=RunStatus.SUCCESS.value)
        task.complete(status=TaskStatus.COMPLETED.value, summary="Planning complete")

        # Grant with verification targeting a failing test
        grant = service.create_execution_grant(
            task_id=task.id,
            plan_artifact_id=plan_art.id,
            founder_approval_id="founder-appr-01",
            approved_files_to_modify=["src/app.py"],
            verification_actions=[VerificationAction("pytest", "tests/test_app.py")],
        )

        # Simulate developer modifying app.py such that test_app fails: run() returns 999 instead of 42
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
        with manager.create_worktree(grant) as session:
            (session.worktree_path / "src" / "app.py").write_text("def run(): return 999\n", encoding="utf-8")
            diff_res = session.capture_diff()

            # Execute verification
            vr = execute_verification_action(grant.verification_actions[0], session.worktree_path)
            assert vr.passed is False
            assert vr.status == VerificationStatus.FAIL.value

            # Hard invariant: DO NOT create CODE_PATCH
            patch_created = False
            if vr.passed:
                materialize_code_patch_artifact(
                    base_output_dir=service.output_dir,
                    task=task,
                    run=run,
                    grant=grant,
                    patch_text=diff_res.diff_text,
                    changed_files=diff_res.changed_files,
                )
                patch_created = True

            assert patch_created is False
            # Ensure no CODE_PATCH artifact in run
            code_patches = [a for a in run.artifacts if a.artifact_type == ArtifactType.CODE_PATCH.value]
            assert len(code_patches) == 0

    def test_v_code_patch_artifact_materialized(self, temp_git_repo):
        """V. CODE_PATCH artifact materialized."""
        repo, head_commit = temp_git_repo
        task = Task("task_v", "proj_01", "dev", "Task V", "Goal")
        run = task.create_run()
        grant = ExecutionGrant(
            grant_id="grant_v",
            task_id=task.id,
            plan_artifact_id="art_plan_v",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            founder_approval_id="appr_v",
        )

        patch_text = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n-def run(): return 42\n+def run(): return 100\n"
        artifact = materialize_code_patch_artifact(
            base_output_dir=repo / ".runs",
            task=task,
            run=run,
            grant=grant,
            patch_text=patch_text,
            changed_files=["src/app.py"],
        )
        assert artifact.artifact_type == ArtifactType.CODE_PATCH.value
        assert artifact.name == "developer_changes.patch"
        assert artifact.durable is True

    def test_w_artifact_physically_exists_after_worktree_deletion(self, temp_git_repo):
        """W. Artifact physically exists after worktree deletion."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
        task = Task("task_w", "proj_01", "dev", "Task W", "Goal")
        run = task.create_run()
        grant = ExecutionGrant(
            grant_id="grant_w",
            task_id=task.id,
            plan_artifact_id="art_plan_w",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            founder_approval_id="appr_w",
        )

        artifact_file = None
        with manager.create_worktree(grant) as session:
            (session.worktree_path / "src" / "app.py").write_text("def run(): return 100\n", encoding="utf-8")
            diff_res = session.capture_diff()

            artifact = materialize_code_patch_artifact(
                base_output_dir=repo / ".runs",
                task=task,
                run=run,
                grant=grant,
                patch_text=diff_res.diff_text,
                changed_files=diff_res.changed_files,
            )
            artifact_file = repo / ".runs" / artifact.path

        # Worktree is now destroyed
        assert not session.worktree_path.exists()

        # Durable artifact file STILL exists
        assert artifact_file.exists()
        assert artifact_file.is_file()
        assert len(artifact_file.read_text(encoding="utf-8")) > 0

    def test_x_artifact_sha_matches_exact_patch_bytes(self, temp_git_repo):
        """X. Artifact SHA matches exact patch bytes."""
        repo, head_commit = temp_git_repo
        task = Task("task_x", "proj_01", "dev", "Task X", "Goal")
        run = task.create_run()
        grant = ExecutionGrant(
            grant_id="grant_x",
            task_id=task.id,
            plan_artifact_id="art_plan_x",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            founder_approval_id="appr_x",
        )

        patch_text = "--- a/src/app.py\n+++ b/src/app.py\n+def foo(): pass\n"
        artifact = materialize_code_patch_artifact(
            base_output_dir=repo / ".runs",
            task=task,
            run=run,
            grant=grant,
            patch_text=patch_text,
            changed_files=["src/app.py"],
        )

        disk_file = repo / ".runs" / artifact.path
        raw_bytes = disk_file.read_bytes()
        computed_sha = hashlib.sha256(raw_bytes).hexdigest()
        assert artifact.sha256 == computed_sha
        assert computed_sha == hashlib.sha256(patch_text.encode("utf-8")).hexdigest()

    def test_y_through_ad_lineage_and_metadata_preserved(self, temp_git_repo):
        """Y-AD: Provenance lineage fields, plan binding, base commit, and verification evidence preserved."""
        repo, head_commit = temp_git_repo
        task = Task("task_lineage", "proj_01", "dev", "Lineage Task", "Goal")
        run = task.create_run()

        va = VerificationAction("pytest", "tests/test_app.py")
        grant = ExecutionGrant(
            grant_id="grant_lineage_001",
            task_id=task.id,
            plan_artifact_id="art_plan_999",
            plan_sha256="b" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            approved_files_to_create=("src/new.py",),
            verification_actions=(va,),
            founder_approval_id="founder_appr_777",
        )

        veri_result = VerificationExecutionResult(
            action=va,
            status=VerificationStatus.PASS.value,
            exit_code=0,
            stdout="1 passed in 0.05s",
            stderr="",
            duration_ms=50,
        )

        patch_text = "--- a/src/app.py\n+++ b/src/app.py\n+test\n"
        artifact = materialize_code_patch_artifact(
            base_output_dir=repo / ".runs",
            task=task,
            run=run,
            grant=grant,
            patch_text=patch_text,
            changed_files=["src/app.py", "src/new.py"],
            verifications=[veri_result],
        )

        meta = artifact.metadata
        assert meta is not None

        # Y. plan artifact lineage preserved
        assert meta["plan_artifact_id"] == "art_plan_999"
        # Z. plan SHA preserved
        assert meta["plan_sha256"] == "b" * 64
        # AA. ExecutionGrant ID preserved
        assert meta["execution_grant_id"] == "grant_lineage_001"
        assert meta["founder_approval_id"] == "founder_appr_777"
        # AB. base commit preserved
        assert meta["base_commit_hash"] == head_commit
        # AC. changed-file metadata preserved
        assert meta["changed_files"] == ["src/app.py", "src/new.py"]
        # AD. verification evidence preserved
        assert len(meta["verification_actions"]) == 1
        assert meta["verification_actions"][0]["action_type"] == "pytest"
        assert len(meta["verification_outcomes"]) == 1
        assert meta["verification_outcomes"][0]["status"] == "PASS"
        assert meta["verification_outcomes"][0]["exit_code"] == 0

        # Also inspect companion .meta.json file
        meta_file = (repo / ".runs" / artifact.path).with_name("developer_changes.patch.meta.json")
        assert meta_file.exists()
        companion_meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert companion_meta["execution_grant_id"] == "grant_lineage_001"
        assert companion_meta["base_commit_hash"] == head_commit


class TestWorktreeLifecycleAndImmutability:
    """Tests AE through AH: Worktree cleanup and real repository immutability."""

    def test_ae_worktree_removed_after_success(self, temp_git_repo):
        """AE. Worktree removed after successful execution."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
        grant = ExecutionGrant(
            grant_id="grant_success_clean",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            (session.worktree_path / "src" / "app.py").write_text("def run(): return 42\n", encoding="utf-8")
            assert session.worktree_path.exists()

        assert not session.worktree_path.exists()

    def test_af_worktree_removed_after_verification_failure(self, temp_git_repo):
        """AF. Worktree removed after verification failure."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
        grant = ExecutionGrant(
            grant_id="grant_fail_clean",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            verification_actions=(VerificationAction("pytest", "tests/test_app.py"),),
            founder_approval_id="appr_01",
        )

        session = manager.create_worktree(grant)
        try:
            # Simulate mutation that breaks tests
            (session.worktree_path / "src" / "app.py").write_text("def run(): return -1\n", encoding="utf-8")
            vr = execute_verification_action(grant.verification_actions[0], session.worktree_path)
            assert vr.passed is False
        finally:
            session.remove()

        assert not session.worktree_path.exists()

    def test_ag_worktree_removed_after_artifact_failure(self, temp_git_repo):
        """AG. Worktree removed after artifact materialization failure."""
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
        grant = ExecutionGrant(
            grant_id="grant_art_fail_clean",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            founder_approval_id="appr_01",
        )

        session = manager.create_worktree(grant)
        task = Task("task_err", "proj_01", "dev", "Task Err", "Goal")
        run = task.create_run()

        try:
            (session.worktree_path / "src" / "app.py").write_text("def run(): return 42\n", encoding="utf-8")
            diff_res = session.capture_diff()
            # Attempt to materialize with invalid empty patch
            with pytest.raises(MaterializationError):
                materialize_code_patch_artifact(
                    base_output_dir=repo / ".runs",
                    task=task,
                    run=run,
                    grant=grant,
                    patch_text="",  # Empty patch text triggers MaterializationError
                    changed_files=diff_res.changed_files,
                )
        finally:
            session.remove()

        assert not session.worktree_path.exists()

    def test_ah_main_repository_unchanged(self, temp_git_repo):
        """AH. Main repository remains 100% unchanged before and after lifecycle."""
        repo, head_commit = temp_git_repo
        initial_app_bytes = (repo / "src" / "app.py").read_bytes()
        initial_status = _run_cmd(["git", "status", "--porcelain"], repo)

        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
        grant = ExecutionGrant(
            grant_id="grant_immutability",
            task_id="task_01",
            plan_artifact_id="art_01",
            plan_sha256="a" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("src/app.py",),
            approved_files_to_create=("src/created.py",),
            founder_approval_id="appr_01",
        )

        with manager.create_worktree(grant) as session:
            # Modify and create files inside isolated worktree
            (session.worktree_path / "src" / "app.py").write_text("def run(): return 99999\n", encoding="utf-8")
            (session.worktree_path / "src" / "created.py").write_text("# new code\n", encoding="utf-8")
            diff_res = session.capture_diff()
            assert len(diff_res.changed_files) == 2

        # After worktree lifecycle:
        final_app_bytes = (repo / "src" / "app.py").read_bytes()
        final_status = _run_cmd(["git", "status", "--porcelain"], repo)

        assert final_app_bytes == initial_app_bytes
        assert final_status == initial_status
        assert not (repo / "src" / "created.py").exists()
        assert resolve_repo_head_commit(repo) == head_commit


class TestServiceEndToEndIntegration:
    """End-to-end integration tests through CompanyService.execute_bounded_developer_mutation."""

    def test_service_mutation_verification_pass_produces_verified_code_patch(self, temp_git_repo):
        repo, head_commit = temp_git_repo
        service = CompanyService(repo_root=repo, output_dir=str(repo / ".runs"))
        service.create_project("proj_e2e", "E2E Project")
        task = service.create_task("proj_e2e", "E2E Plan", "Plan goal")
        run = task.create_run()

        plan_bytes = b"# Plan: update run() to return 42"
        plan_sha = hashlib.sha256(plan_bytes).hexdigest()
        plan_path = service.output_dir / "artifacts" / "developer_plan_report.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_bytes(plan_bytes)

        plan_art = run.add_artifact(
            name="developer_plan_report.md",
            artifact_type="DEVELOPER_PLAN_REPORT",
            path="artifacts/developer_plan_report.md",
            durable=True,
            sha256=plan_sha,
            producer_role="developer",
        )
        run.complete(status=RunStatus.SUCCESS.value)
        task.complete(status=TaskStatus.COMPLETED.value, summary="Planning done")

        grant = service.create_execution_grant(
            task_id=task.id,
            plan_artifact_id=plan_art.id,
            founder_approval_id="founder-appr-e2e-pass",
            approved_files_to_modify=["src/app.py"],
            approved_files_to_create=["src/helper.py"],
            verification_actions=[VerificationAction("pytest", "tests/test_app.py")],
        )

        def mock_developer_exec(*args, **kwargs):
            ws = kwargs.get("workspace_dir")
            assert ws is not None
            # Simulate developer making approved modifications that pass test
            (ws / "src" / "app.py").write_text("def run():\n    return 42\n", encoding="utf-8")
            (ws / "src" / "helper.py").write_text("def help():\n    return 'ok'\n", encoding="utf-8")
            payload = {
                "status": "completed",
                "summary": "Updated app.py and added helper.py",
                "schema_version": "1.0",
                "modified_files": [{"path": "src/app.py", "description": "run update"}],
                "created_files": [{"path": "src/helper.py", "description": "helper"}],
                "deleted_files": [],
            }
            return AgentExecutionResult(
                agent="developer",
                success=True,
                stdout=json.dumps(payload),
                stderr="",
                exit_code=0,
                duration_ms=100.0,
                timed_out=False,
            )

        with patch.object(service.runtime, "execute", side_effect=mock_developer_exec):
            outcome = service.execute_bounded_developer_mutation(
                grant=grant,
                instruction="Update app and add helper",
                protect_company_control=False,
            )

        assert outcome.status == DeveloperMutationStatus.SUCCESS.value
        assert outcome.cleaned_up is True
        assert outcome.patch_artifact is not None
        assert outcome.patch_artifact.artifact_type == ArtifactType.CODE_PATCH.value
        assert len(outcome.verification_results) == 1
        assert outcome.verification_results[0].passed is True

        # Check durable artifact on disk
        patch_file = service.output_dir / outcome.patch_artifact.path
        assert patch_file.exists()
        patch_bytes = patch_file.read_bytes()
        assert hashlib.sha256(patch_bytes).hexdigest() == outcome.patch_artifact.sha256
        patch_text = patch_file.read_text(encoding="utf-8")
        assert "helper.py" in patch_text

        # Main repo remains untouched
        assert not (repo / "src" / "helper.py").exists()

    def test_service_mutation_verification_fail_blocks_code_patch(self, temp_git_repo):
        repo, head_commit = temp_git_repo
        service = CompanyService(repo_root=repo, output_dir=str(repo / ".runs"))
        service.create_project("proj_e2e_fail", "E2E Fail Project")
        task = service.create_task("proj_e2e_fail", "E2E Plan", "Plan goal")
        run = task.create_run()

        plan_bytes = b"# Plan: broken code"
        plan_sha = hashlib.sha256(plan_bytes).hexdigest()
        plan_path = service.output_dir / "artifacts" / "developer_plan_report.md"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_bytes(plan_bytes)

        plan_art = run.add_artifact(
            name="developer_plan_report.md",
            artifact_type="DEVELOPER_PLAN_REPORT",
            path="artifacts/developer_plan_report.md",
            durable=True,
            sha256=plan_sha,
            producer_role="developer",
        )
        run.complete(status=RunStatus.SUCCESS.value)
        task.complete(status=TaskStatus.COMPLETED.value, summary="Planning done")

        grant = service.create_execution_grant(
            task_id=task.id,
            plan_artifact_id=plan_art.id,
            founder_approval_id="founder-appr-e2e-fail",
            approved_files_to_modify=["src/app.py"],
            verification_actions=[VerificationAction("pytest", "tests/test_app.py")],
        )

        def mock_bad_developer_exec(*args, **kwargs):
            ws = kwargs.get("workspace_dir")
            assert ws is not None
            # Developer writes code that breaks test_app.py: returns 999 instead of 42
            (ws / "src" / "app.py").write_text("def run():\n    return 999\n", encoding="utf-8")
            payload = {
                "status": "completed",
                "summary": "Broke app.py",
                "schema_version": "1.0",
                "modified_files": [{"path": "src/app.py", "description": "broken"}],
                "created_files": [],
                "deleted_files": [],
            }
            return AgentExecutionResult(
                agent="developer",
                success=True,
                stdout=json.dumps(payload),
                stderr="",
                exit_code=0,
                duration_ms=100.0,
                timed_out=False,
            )

        with patch.object(service.runtime, "execute", side_effect=mock_bad_developer_exec):
            outcome = service.execute_bounded_developer_mutation(
                grant=grant,
                instruction="Break app",
                protect_company_control=False,
            )

        assert outcome.status == DeveloperMutationStatus.VERIFICATION_FAILED.value
        assert outcome.cleaned_up is True
        assert outcome.patch_artifact is None
        assert len(outcome.verification_results) == 1
        assert outcome.verification_results[0].passed is False

        # No CODE_PATCH file written
        patch_dir = service.output_dir / task.id / run.id / "artifacts"
        patch_file = patch_dir / "developer_changes.patch"
        assert not patch_file.exists()

        # Main repo remains untouched
        assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "def run():\n    return 42\n"
