"""Deterministic Unit & Integration Tests for ExecutionGrant & Worktree Manager (STEP 13B-1).

Tests cover requirements A through AA:
- ExecutionGrant creation and validation
- Founder approval enforcement
- Plan artifact binding & SHA verification
- Base commit binding & stale commit detection
- Isolated Git worktree lifecycle (create, inspect, diff, cleanup)
- Main repo immutability with dirty working tree
- Path confinement, protected paths, and test file policy
- VerificationAction validation
- Environment sanitization
- Context-manager cleanup on success and exception
"""

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import uuid
import pytest

from jester_ai_company.core import (
    Artifact,
    Company,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from jester_ai_company.execution_grant import (
    ExecutionGrant,
    GrantError,
    GrantValidationError,
    MissingApprovalError,
    PlanArtifactMismatchError,
    ProtectedPathError,
    StaleCommitError,
    TestModificationForbiddenError,
    VerificationAction,
    validate_execution_grant,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.worktree import (
    WorktreeConfinementError,
    WorktreeGitError,
    WorktreeManager,
    WorktreeSession,
    is_protected_path,
    is_test_file,
    resolve_repo_head_commit,
    run_git,
    sanitize_execution_environment,
    verify_workspace_path,
)


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Create a temporary initialized Git repository with an initial commit."""
    repo = tmp_path / "target_repo"
    repo.mkdir(parents=True, exist_ok=True)

    # Initialize Git
    run_git(["init"], cwd=repo)
    run_git(["config", "user.name", "Test Runner"], cwd=repo)
    run_git(["config", "user.email", "runner@example.com"], cwd=repo)

    # Create initial commit
    readme = repo / "README.md"
    readme.write_text("# Target Repo Baseline\n", encoding="utf-8")
    run_git(["add", "README.md"], cwd=repo)
    run_git(["commit", "-m", "Initial baseline commit"], cwd=repo)

    head = resolve_repo_head_commit(repo)
    return repo, head


class TestExecutionGrantModel:
    """Test suite for ExecutionGrant and VerificationAction models."""

    def test_valid_execution_grant_creation(self):
        # A. valid ExecutionGrant creation
        action = VerificationAction(action_type="pytest", target="tests/test_basic.py")
        grant = ExecutionGrant(
            grant_id="grant_12345",
            task_id="task_dev_01",
            plan_artifact_id="art_plan_abc",
            plan_sha256="a" * 64,
            base_commit_hash="0123456789abcdef0123456789abcdef01234567",
            approved_files_to_modify=("src/core.py",),
            approved_files_to_create=("src/feature.py",),
            verification_actions=(action,),
            allow_test_modifications=False,
            founder_approval_id="founder_appr_999",
        )
        assert grant.grant_id == "grant_12345"
        assert grant.founder_approval_id == "founder_appr_999"
        assert len(grant.verification_actions) == 1
        d = grant.to_dict()
        assert d["grant_id"] == "grant_12345"
        assert d["approved_files_to_modify"] == ["src/core.py"]

    def test_missing_founder_approval_rejected(self):
        # B. missing founder approval rejected
        with pytest.raises(MissingApprovalError, match="lacks explicit founder_approval_id"):
            ExecutionGrant(
                grant_id="grant_12345",
                task_id="task_dev_01",
                plan_artifact_id="art_plan_abc",
                plan_sha256="a" * 64,
                base_commit_hash="0123456789abcdef0123456789abcdef01234567",
                founder_approval_id="",  # empty
            )

    def test_invalid_plan_sha_rejected(self):
        # D. wrong plan SHA rejected
        with pytest.raises(GrantValidationError, match="valid 64-character hex string"):
            ExecutionGrant(
                grant_id="grant_12345",
                task_id="task_dev_01",
                plan_artifact_id="art_plan_abc",
                plan_sha256="invalid-sha",
                base_commit_hash="0123456789abcdef0123456789abcdef01234567",
                founder_approval_id="appr_1",
            )

    def test_invalid_base_commit_hash_rejected(self):
        with pytest.raises(GrantValidationError, match="valid git commit hex hash"):
            ExecutionGrant(
                grant_id="grant_12345",
                task_id="task_dev_01",
                plan_artifact_id="art_plan_abc",
                plan_sha256="a" * 64,
                base_commit_hash="non-hex-not-a-hash!",
                founder_approval_id="appr_1",
            )

    def test_network_enabled_forbidden_in_v1(self):
        with pytest.raises(GrantValidationError, match="Network access is strictly forbidden"):
            ExecutionGrant(
                grant_id="grant_12345",
                task_id="task_dev_01",
                plan_artifact_id="art_plan_abc",
                plan_sha256="a" * 64,
                base_commit_hash="0123456789abcdef0123456789abcdef01234567",
                network_enabled=True,
                founder_approval_id="appr_1",
            )

    def test_overlapping_modify_and_create_rejected(self):
        with pytest.raises(GrantValidationError, match="Paths cannot be in both"):
            ExecutionGrant(
                grant_id="grant_12345",
                task_id="task_dev_01",
                plan_artifact_id="art_plan_abc",
                plan_sha256="a" * 64,
                base_commit_hash="0123456789abcdef0123456789abcdef01234567",
                approved_files_to_modify=("same_file.py",),
                approved_files_to_create=("same_file.py",),
                founder_approval_id="appr_1",
            )

    def test_typed_pytest_verification_action_validates(self):
        # T. typed pytest VerificationAction validates
        va = VerificationAction(action_type="pytest", target="tests/test_unit.py")
        assert va.to_argument_vector() == ["python", "-m", "pytest", "tests/test_unit.py"]

    def test_raw_arbitrary_command_rejected_as_verification_action(self):
        # U. raw arbitrary command is not accepted as VerificationAction
        with pytest.raises(GrantValidationError, match="Unsupported verification action type"):
            VerificationAction(action_type="bash -c 'rm -rf /'", target="target")

        # Metacharacters in target rejected
        with pytest.raises(GrantValidationError, match="forbidden shell metacharacters"):
            VerificationAction(action_type="pytest", target="tests; rm -rf /")


class TestPathConfinementAndPolicies:
    """Test suite for path validation, protected files, and test file policy."""

    def test_absolute_writable_path_rejected(self, tmp_path: Path):
        # K. absolute writable path rejected
        with pytest.raises(WorktreeConfinementError, match="absolute or drive-qualified"):
            verify_workspace_path("C:/Windows/System32/calc.exe", tmp_path)

    def test_parent_traversal_rejected(self, tmp_path: Path):
        # L. ../ traversal rejected
        with pytest.raises(WorktreeConfinementError, match="traversal"):
            verify_workspace_path("../outside.py", tmp_path)

    def test_outside_workspace_resolution_rejected(self, tmp_path: Path):
        # M. outside-workspace resolution rejected
        with pytest.raises(WorktreeConfinementError):
            verify_workspace_path("sub/../../escape.py", tmp_path)

    def test_protected_git_path_rejected(self):
        # N. protected .git path rejected
        assert is_protected_path(".git") is True
        assert is_protected_path(".git/config") is True
        assert is_protected_path(".git/HEAD") is True

    def test_protected_agents_path_rejected(self):
        # O. protected .agents path rejected
        assert is_protected_path(".agents") is True
        assert is_protected_path(".agents/agents/developer/agent.md") is True

    def test_protected_env_path_rejected(self):
        # P. protected .env path rejected
        assert is_protected_path(".env") is True
        assert is_protected_path(".env.local") is True
        assert is_protected_path("config/.env") is True
        assert is_protected_path("credentials.json") is True
        assert is_protected_path("secret.pem") is True

    def test_company_control_path_protected_when_flagged(self):
        assert is_protected_path("jester_ai_company/core.py", protect_company_control=True) is True
        assert is_protected_path("jester_ai_company/service.py", protect_company_control=True) is True
        # False if company control protection is not requested (generic repo)
        assert is_protected_path("jester_ai_company/service.py", protect_company_control=False) is False

    def test_test_file_classification(self):
        assert is_test_file("tests/test_sample.py") is True
        assert is_test_file("test_core.py") is True
        assert is_test_file("core_test.py") is True
        assert is_test_file("src/app.py") is False


class TestEnvironmentSanitization:
    """Test suite for subprocess environment sanitization."""

    def test_secret_environment_variables_stripped(self):
        # S. secret environment variables stripped
        raw_env = {
            "PATH": "/usr/bin;C:\\Windows",
            "SYSTEMROOT": "C:\\Windows",
            "TEMP": "C:\\Temp",
            "OPENAI_API_KEY": "sk-secret12345",
            "ANTHROPIC_API_KEY": "ant-secret999",
            "GITHUB_TOKEN": "ghp_supersecret",
            "AWS_SECRET_ACCESS_KEY": "aws123",
            "MY_APP_SECRET": "topsecret",
            "DB_PASSWORD": "admin",
            "PYTHONPATH": "C:\\project",
        }
        clean_env = sanitize_execution_environment(raw_env)

        assert "PATH" in clean_env
        assert "SYSTEMROOT" in clean_env
        assert "TEMP" in clean_env
        assert "PYTHONPATH" in clean_env

        # Secrets stripped
        assert "OPENAI_API_KEY" not in clean_env
        assert "ANTHROPIC_API_KEY" not in clean_env
        assert "GITHUB_TOKEN" not in clean_env
        assert "AWS_SECRET_ACCESS_KEY" not in clean_env
        assert "MY_APP_SECRET" not in clean_env
        assert "DB_PASSWORD" not in clean_env


class TestWorktreeLifecycle:
    """Test suite for Git worktree creation, diff capture, and isolation."""

    def test_valid_detached_worktree_created(self, temp_git_repo):
        # G. valid detached worktree created & H. worktree uses exact approved commit
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_test_01",
            task_id="task_01",
            plan_artifact_id="art_1",
            plan_sha256="b" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("README.md",),
            founder_approval_id="approval_123",
        )

        with manager.create_worktree(grant) as session:
            assert session.worktree_path.exists()
            assert (session.worktree_path / "README.md").exists()
            worktree_head = resolve_repo_head_commit(session.worktree_path)
            assert worktree_head == head_commit

        # Y. cleanup removes worktree
        assert not session.worktree_path.exists()
        assert session.is_cleaned_up is True

    def test_stale_base_commit_rejected(self, temp_git_repo):
        # F. stale base commit rejected
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees")

        grant = ExecutionGrant(
            grant_id="grant_stale",
            task_id="task_01",
            plan_artifact_id="art_1",
            plan_sha256="b" * 64,
            base_commit_hash="0000000000000000000000000000000000000000",
            approved_files_to_modify=("README.md",),
            founder_approval_id="approval_123",
        )

        with pytest.raises(StaleCommitError, match="Approval is stale"):
            manager.create_worktree(grant)

    def test_dirty_main_working_tree_remains_untouched_and_absent_from_worktree(self, temp_git_repo):
        # I. dirty main working tree remains untouched
        # J. uncommitted main changes are absent from isolated worktree
        repo, head_commit = temp_git_repo

        # Mutate main repository working tree WITHOUT committing (dirty state)
        dirty_file = repo / "uncommitted_work.txt"
        dirty_file.write_text("Secret in-progress draft", encoding="utf-8")
        main_readme = repo / "README.md"
        main_readme.write_text("# Main Tree Modified Content\n", encoding="utf-8")

        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)
        grant = ExecutionGrant(
            grant_id="grant_dirty_test",
            task_id="task_01",
            plan_artifact_id="art_1",
            plan_sha256="b" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("README.md",),
            founder_approval_id="approval_123",
        )

        with manager.create_worktree(grant) as session:
            # Uncommitted dirty file from main tree is ABSENT from worktree
            assert not (session.worktree_path / "uncommitted_work.txt").exists()
            # README in worktree is clean committed version, NOT dirty main tree version
            assert (session.worktree_path / "README.md").read_text(encoding="utf-8") == "# Target Repo Baseline\n"

        # Main tree dirty changes remain 100% intact
        assert dirty_file.exists()
        assert dirty_file.read_text(encoding="utf-8") == "Secret in-progress draft"
        assert main_readme.read_text(encoding="utf-8") == "# Main Tree Modified Content\n"

    def test_worktree_diff_capture_and_main_repo_immutability(self, temp_git_repo):
        # V. deterministic test-code mutation appears in worktree diff
        # W. diff lists actual changed file
        # X. main repository remains unchanged
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_diff_test",
            task_id="task_01",
            plan_artifact_id="art_1",
            plan_sha256="b" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("README.md",),
            approved_files_to_create=("feature.py",),
            founder_approval_id="approval_123",
        )

        with manager.create_worktree(grant) as session:
            # 1. Check empty diff initially
            initial_diff = session.capture_diff()
            assert initial_diff.is_empty is True
            assert initial_diff.changed_files == []

            # 2. Mutate files using deterministic test code (NOT an LLM)
            wt_readme = session.worktree_path / "README.md"
            wt_readme.write_text("# Target Repo Baseline\n- New verified feature\n", encoding="utf-8")
            wt_feature = session.worktree_path / "feature.py"
            wt_feature.write_text("def hello(): return 'world'\n", encoding="utf-8")

            # 3. Capture diff
            diff_res = session.capture_diff()
            assert diff_res.is_empty is False
            assert "README.md" in diff_res.changed_files
            assert "feature.py" in diff_res.changed_files
            assert "feature.py" in diff_res.untracked_files
            assert "+- New verified feature" in diff_res.diff_text
            assert "def hello():" in diff_res.diff_text
            assert len(diff_res.diff_sha256) == 64

        # Main repository README is byte-for-byte identical to baseline
        main_readme = repo / "README.md"
        assert main_readme.read_text(encoding="utf-8") == "# Target Repo Baseline\n"
        assert not (repo / "feature.py").exists()

    def test_cleanup_occurs_on_exception(self, temp_git_repo):
        # Z. cleanup occurs on exception
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        grant = ExecutionGrant(
            grant_id="grant_exc_test",
            task_id="task_01",
            plan_artifact_id="art_1",
            plan_sha256="b" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("README.md",),
            founder_approval_id="approval_123",
        )

        with pytest.raises(RuntimeError, match="Simulated crash during worktree execution"):
            with manager.create_worktree(grant) as session:
                wt_path = session.worktree_path
                assert wt_path.exists()
                raise RuntimeError("Simulated crash during worktree execution")

        # Worktree cleaned up despite exception
        assert not wt_path.exists()
        assert session.is_cleaned_up is True
        assert "Simulated crash" in session.audit.error

    def test_test_modification_policy_enforcement(self, temp_git_repo):
        # Q. test modification rejected by default
        # R. explicitly allowed test path accepted
        repo, head_commit = temp_git_repo
        manager = WorktreeManager(repo_root=repo, worktrees_dir=repo / ".worktrees", protect_company_control=False)

        # Rejected by default
        grant_disallowed = ExecutionGrant(
            grant_id="grant_test_disallowed",
            task_id="task_01",
            plan_artifact_id="art_1",
            plan_sha256="b" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("tests/test_login.py",),
            allow_test_modifications=False,
            founder_approval_id="appr_1",
        )
        with pytest.raises(TestModificationForbiddenError, match="cannot be modified: grant.allow_test_modifications is False"):
            manager.create_worktree(grant_disallowed)

        # Accepted when allow_test_modifications=True
        grant_allowed = ExecutionGrant(
            grant_id="grant_test_allowed",
            task_id="task_01",
            plan_artifact_id="art_1",
            plan_sha256="b" * 64,
            base_commit_hash=head_commit,
            approved_files_to_modify=("tests/test_login.py",),
            allow_test_modifications=True,
            founder_approval_id="appr_1",
        )
        with manager.create_worktree(grant_allowed) as session:
            assert session.worktree_path.exists()


class TestServiceGrantIntegration:
    """Test suite for CompanyService.create_execution_grant verification of company state."""

    def test_service_plan_artifact_verification(self, temp_git_repo):
        # C. wrong plan artifact rejected
        # D. wrong plan SHA rejected
        # E. non-Developer plan artifact rejected
        repo, head_commit = temp_git_repo
        service = CompanyService(repo_root=repo, output_dir=repo / ".runs")
        service.create_project("proj_01", "Test Project")
        task = service.create_task("proj_01", "Plan Task", "Plan goal", task_id="task_plan_01")
        run = task.create_run()

        # Create dummy plan artifact on disk
        plan_content = "# Developer Plan Report\n"
        plan_sha = hashlib.sha256(plan_content.encode("utf-8")).hexdigest()
        plan_file = service.output_dir / "task_plan_01" / run.id / "artifacts" / "developer_plan_report.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_bytes(plan_content.encode("utf-8"))

        # 1. Non-Developer role rejected (E)
        art_product = run.add_artifact(
            name="developer_plan_report.md",
            artifact_type="DEVELOPER_PLAN_REPORT",
            path=str(plan_file.relative_to(service.output_dir)),
            durable=True,
            sha256=plan_sha,
            producer_role="product",  # WRONG ROLE
        )
        run.complete(status=RunStatus.SUCCESS.value)
        task.complete(status=TaskStatus.COMPLETED.value, summary="Planning done")

        with pytest.raises(PlanArtifactMismatchError, match="expected 'developer'"):
            service.create_execution_grant(
                task_id=task.id,
                plan_artifact_id=art_product.id,
                founder_approval_id="appr_123",
            )

        # 2. Correct role developer
        art_product.producer_role = "developer"

        # 3. Missing artifact rejected (C)
        with pytest.raises(PlanArtifactMismatchError, match="could not be found"):
            service.create_execution_grant(
                task_id=task.id,
                plan_artifact_id="non_existent_art_id",
                founder_approval_id="appr_123",
            )

        # 4. Tampered disk bytes rejected (D)
        plan_file.write_bytes(b"# TAMPERED CONTENT\n")
        with pytest.raises(PlanArtifactMismatchError, match="disk SHA mismatch"):
            service.create_execution_grant(
                task_id=task.id,
                plan_artifact_id=art_product.id,
                founder_approval_id="appr_123",
            )

        # 5. Restore correct content -> success!
        plan_file.write_bytes(plan_content.encode("utf-8"))
        grant = service.create_execution_grant(
            task_id=task.id,
            plan_artifact_id=art_product.id,
            founder_approval_id="appr_123",
            approved_files_to_modify=["README.md"],
        )
        assert grant.plan_sha256 == plan_sha
        assert grant.base_commit_hash == head_commit
        assert grant.founder_approval_id == "appr_123"
