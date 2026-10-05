"""Comprehensive tests for Generic Project and Repository Foundation (STEP 19B).

Covers:
1. Synthetic Git repository fixtures and registration
2. RepositoryRef and RepositoryStateFingerprint validation
3. RepositoryPolicy access boundaries (DENIED precedence, fail-closed)
4. Path traversal, normalization bypass, and escape prevention
5. Policy ↔ ExecutionGrant integration validation
6. CompanyRun project, repository, branch, and base revision binding
7. Cross-project security proof: Project A authorization CANNOT mutate Project B
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Tuple

import pytest

from jester_ai_company.core import Artifact, ArtifactType, Task, TaskStatus
from jester_ai_company.execution_grant import ExecutionGrant, VerificationAction
from jester_ai_company.orchestrator import CompanyObjective, CompanyRun, CompanyRunState
from jester_ai_company.project import (
    CrossProjectMismatchError,
    DuplicateProjectError,
    DuplicateRepositoryError,
    PolicyViolationError,
    Project,
    ProjectNotFoundError,
    ProjectRegistry,
    ProjectValidationError,
    RepositoryPolicy,
    RepositoryRef,
    RepositoryStateFingerprint,
    RepositoryValidationError,
    inspect_repository_state,
    validate_grant_against_project_policy,
)
from jester_ai_company.real_repo_apply import (
    BaseCommitMismatchError,
    RealRepoApplyGrant,
    RealRepoApplyProposal,
    build_real_repo_apply_proposal,
    derive_real_repo_apply_grant,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.worktree import resolve_repo_head_commit, run_git


# ==============================================================================
# Synthetic Git Repository Test Fixtures (Phase 20)
# ==============================================================================

@pytest.fixture
def temp_git_repo():
    """Create a temporary initialized Git repository with an initial commit on 'main'."""
    temp_dir = tempfile.mkdtemp(prefix="test_repo_")
    repo_path = Path(temp_dir).resolve()

    # Initialize Git repository
    run_git(["init", "-b", "main"], cwd=repo_path)
    run_git(["config", "user.name", "Test Committer"], cwd=repo_path)
    run_git(["config", "user.email", "committer@example.com"], cwd=repo_path)

    # Initial file and commit
    readme = repo_path / "README.md"
    readme.write_text("# Test Repository\n", encoding="utf-8")
    run_git(["add", "README.md"], cwd=repo_path)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_path)

    yield repo_path

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def two_temp_git_repos():
    """Create two separate temporary Git repositories for cross-project isolation tests."""
    temp_dir_a = tempfile.mkdtemp(prefix="test_repo_a_")
    temp_dir_b = tempfile.mkdtemp(prefix="test_repo_b_")

    repo_a = Path(temp_dir_a).resolve()
    repo_b = Path(temp_dir_b).resolve()

    for r, name in ((repo_a, "Project Alpha"), (repo_b, "Project Beta")):
        run_git(["init", "-b", "main"], cwd=r)
        run_git(["config", "user.name", "Test Committer"], cwd=r)
        run_git(["config", "user.email", "committer@example.com"], cwd=r)
        (r / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        run_git(["add", "README.md"], cwd=r)
        run_git(["commit", "-m", f"Initial commit for {name}"], cwd=r)

    yield repo_a, repo_b

    shutil.rmtree(temp_dir_a, ignore_errors=True)
    shutil.rmtree(temp_dir_b, ignore_errors=True)


# ==============================================================================
# Unit Tests: RepositoryRef & Validation (Phases 3 & 4)
# ==============================================================================

def test_repository_ref_creation_and_canonicalization(temp_git_repo):
    """Test RepositoryRef normalizes and canonicalizes path."""
    repo_ref = RepositoryRef(
        repository_id="repo_synthetic",
        root_path=str(temp_git_repo),
        target_branch="main",
    )
    assert repo_ref.repository_id == "repo_synthetic"
    assert repo_ref.canonical_root == temp_git_repo
    assert repo_ref.target_branch == "main"

    # Serialization roundtrip
    data = repo_ref.to_dict()
    restored = RepositoryRef.from_dict(data)
    assert restored == repo_ref


def test_repository_ref_rejects_empty_fields():
    """Test RepositoryRef fails on empty parameters."""
    with pytest.raises(ProjectValidationError, match="repository_id"):
        RepositoryRef(repository_id="", root_path="/valid/path")

    with pytest.raises(ProjectValidationError, match="root_path"):
        RepositoryRef(repository_id="repo_1", root_path="")

    with pytest.raises(ProjectValidationError, match="target_branch"):
        RepositoryRef(repository_id="repo_1", root_path="/valid/path", target_branch="")


def test_inspect_repository_state_clean_and_dirty(temp_git_repo):
    """Test deterministic read-only repository inspection."""
    repo_ref = RepositoryRef(repository_id="repo_1", root_path=str(temp_git_repo), target_branch="main")
    fingerprint = inspect_repository_state(repo_ref)

    assert fingerprint.repository_id == "repo_1"
    assert fingerprint.branch == "main"
    assert len(fingerprint.head_commit) == 40
    assert fingerprint.is_clean is True
    assert len(fingerprint.state_sha256) == 64

    # Make working tree dirty
    dirty_file = temp_git_repo / "dirty.txt"
    dirty_file.write_text("uncommitted work", encoding="utf-8")

    dirty_fp = inspect_repository_state(repo_ref)
    assert dirty_fp.is_clean is False
    assert dirty_fp.state_sha256 != fingerprint.state_sha256

    # Clean up dirty file
    dirty_file.unlink()


def test_inspect_repository_state_fails_on_non_git_or_missing(tmp_path):
    """Test inspection fails closed if path is missing or not a git repository."""
    missing_ref = RepositoryRef(repository_id="repo_missing", root_path=str(tmp_path / "missing"))
    with pytest.raises(RepositoryValidationError, match="does not exist"):
        inspect_repository_state(missing_ref)

    not_git_ref = RepositoryRef(repository_id="repo_not_git", root_path=str(tmp_path))
    with pytest.raises(RepositoryValidationError, match="no .git"):
        inspect_repository_state(not_git_ref)


# ==============================================================================
# Unit Tests: RepositoryPolicy (Phases 6, 7 & 17)
# ==============================================================================

def test_repository_policy_denied_precedence():
    """Test that DENIED patterns strictly override ALLOWED patterns (fail-closed)."""
    policy = RepositoryPolicy(
        read_allowed=("**",),
        mutation_allowed=("backend/**", "frontend/**"),
        denied=(".git/**", ".env*", "config/secrets.yaml"),
    )

    # Allowed read and mutation
    assert policy.can_read("backend/routes.py") is True
    assert policy.can_mutate("backend/routes.py") is True

    # Read allowed, mutation forbidden
    assert policy.can_read("docs/spec.md") is True
    assert policy.can_mutate("docs/spec.md") is False

    # Denied paths: CANNOT READ and CANNOT MUTATE even if in mutation_allowed
    assert policy.is_denied(".env") is True
    assert policy.can_read(".env") is False
    assert policy.can_mutate(".env") is False

    assert policy.is_denied(".git/config") is True
    assert policy.can_read(".git/config") is False

    assert policy.is_denied("config/secrets.yaml") is True
    assert policy.can_read("config/secrets.yaml") is False
    assert policy.can_mutate("config/secrets.yaml") is False


def test_repository_policy_rejects_path_traversal():
    """Test policy evaluation fails closed on directory traversal or escape attempts."""
    policy = RepositoryPolicy(read_allowed=("**",), mutation_allowed=("src/**",))

    with pytest.raises(PolicyViolationError, match="Directory traversal"):
        policy.can_read("../outside.py")

    with pytest.raises(PolicyViolationError, match="Directory traversal"):
        policy.can_mutate("src/../../escape.py")

    with pytest.raises(PolicyViolationError, match="Absolute or drive-qualified"):
        policy.can_read("/etc/passwd")

    with pytest.raises(PolicyViolationError, match="Absolute or drive-qualified"):
        policy.can_read("C:/Windows/System32")


def test_repository_policy_validate_mutation_scope():
    """Test validate_mutation_scope raises PolicyViolationError on violation."""
    policy = RepositoryPolicy(
        mutation_allowed=("src/**", "tests/**"),
        denied=(".env*", "src/secret_keys.py"),
    )

    # Valid mutation scope passes cleanly
    policy.validate_mutation_scope(["src/app.py", "tests/test_app.py"])

    # Path not in mutation_allowed raises
    with pytest.raises(PolicyViolationError, match="not within authorized mutation_allowed"):
        policy.validate_mutation_scope(["src/app.py", "README.md"])

    # Explicitly denied path raises
    with pytest.raises(PolicyViolationError, match="explicitly DENIED"):
        policy.validate_mutation_scope(["src/secret_keys.py"])


# ==============================================================================
# Unit Tests: Project & ProjectRegistry (Phases 5, 8 & 9)
# ==============================================================================

def test_project_registry_registration_and_retrieval(temp_git_repo):
    """Test Project creation, validation, registration, and duplicate rejection."""
    registry = ProjectRegistry()

    repo_ref = RepositoryRef(
        repository_id="repo_alpha",
        root_path=str(temp_git_repo),
        target_branch="main",
    )
    policy = RepositoryPolicy(
        read_allowed=("**",),
        mutation_allowed=("src/**",),
    )
    project = Project(
        project_id="prj_alpha",
        name="Project Alpha",
        description="Test project for registry",
        repository=repo_ref,
        policy=policy,
    )

    registered = registry.register_project(project, validate_repo=True)
    assert registered.project_id == "prj_alpha"
    assert registry.get_project("prj_alpha") == project
    assert registry.require_project("prj_alpha") == project
    assert registry.get_project_by_repository_id("repo_alpha") == project
    assert registry.get_project_by_root_path(temp_git_repo) == project
    assert len(registry.list_projects()) == 1

    # Duplicate project_id rejection
    with pytest.raises(DuplicateProjectError, match="already registered"):
        registry.register_project(project)

    # Missing project lookup
    assert registry.get_project("prj_non_existent") is None
    with pytest.raises(ProjectNotFoundError, match="not registered"):
        registry.require_project("prj_non_existent")


def test_project_registry_rejects_wrong_target_branch(temp_git_repo):
    """Test registration fails closed if configured target branch does not exist."""
    registry = ProjectRegistry()
    repo_ref = RepositoryRef(
        repository_id="repo_branch_test",
        root_path=str(temp_git_repo),
        target_branch="non_existent_branch",
    )
    project = Project(
        project_id="prj_bad_branch",
        name="Bad Branch Project",
        repository=repo_ref,
    )
    with pytest.raises(RepositoryValidationError, match="target branch.*does not exist"):
        registry.register_project(project, validate_repo=True)


# ==============================================================================
# Unit Tests: Policy ↔ ExecutionGrant Integration (Phase 16)
# ==============================================================================

def test_validate_grant_against_project_policy():
    """Test that ExecutionGrant mutation scope must be a subset of RepositoryPolicy."""
    policy = RepositoryPolicy(
        mutation_allowed=("backend/**", "tests/**"),
        denied=("*.env*", "backend/auth/secret_key.py"),
    )

    # Valid grant targets pass
    validate_grant_against_project_policy(
        approved_files_to_modify=["backend/routes.py"],
        approved_files_to_create=["tests/test_routes.py"],
        policy=policy,
    )

    # Grant attempting to modify denied path fails closed
    with pytest.raises(PolicyViolationError, match="explicitly DENIED"):
        validate_grant_against_project_policy(
            approved_files_to_modify=["backend/auth/secret_key.py"],
            approved_files_to_create=[],
            policy=policy,
        )

    # Grant attempting to modify unauthorized path fails closed
    with pytest.raises(PolicyViolationError, match="not within authorized mutation_allowed"):
        validate_grant_against_project_policy(
            approved_files_to_modify=["package.json"],
            approved_files_to_create=[],
            policy=policy,
        )


# ==============================================================================
# Unit Tests: CompanyRun Binding (Phases 10, 11 & 22)
# ==============================================================================

def test_company_run_project_binding(temp_git_repo):
    """Test CompanyRun binds project_id, repository_id, target_branch, base_commit_hash."""
    obj = CompanyObjective(
        id="obj_test_1",
        title="Implement Feature",
        description="Add feature under Project Alpha",
        project_id="prj_alpha",
    )
    run = CompanyRun(
        run_id="crun_test_1",
        objective=obj,
        project_id="prj_alpha",
        repository_id="repo_alpha",
        target_branch="main",
        base_commit_hash="abc1234567890123456789012345678901234567",
    )
    assert run.project_id == "prj_alpha"
    assert run.repository_id == "repo_alpha"
    assert run.target_branch == "main"
    assert run.base_commit_hash == "abc1234567890123456789012345678901234567"

    # Serialization roundtrip
    data = run.to_dict()
    assert data["project_id"] == "prj_alpha"
    assert data["repository_id"] == "repo_alpha"
    restored = CompanyRun.from_dict(data)
    assert restored.project_id == "prj_alpha"
    assert restored.repository_id == "repo_alpha"


def test_company_run_rejects_conflicting_project_id():
    """Test CompanyRun fails closed on mismatched project_id between run and objective."""
    obj = CompanyObjective(
        id="obj_test_conflict",
        title="Conflict Test",
        description="Mismatched project IDs",
        project_id="prj_alpha",
    )
    with pytest.raises(Exception, match="Conflicting project_id"):
        CompanyRun(
            run_id="crun_conflict",
            objective=obj,
            project_id="prj_beta",  # Mismatch!
        )


# ==============================================================================
# Security Proof: Cross-Project Mismatch Rejection (Phases 14, 15 & 23)
# ==============================================================================

def test_cross_project_security_proof(two_temp_git_repos):
    """MANDATORY SECURITY PROOF:
    
    Prove that:
    1. Project A proposal cannot target Project B.
    2. Project A grant cannot authorize Project B.
    3. Cross-project apply causes ZERO target mutation and fails closed.
    """
    repo_a, repo_b = two_temp_git_repos
    head_a = resolve_repo_head_commit(repo_a)
    head_b = resolve_repo_head_commit(repo_b)

    # Construct synthetic proposal for Project A
    proposal_a = RealRepoApplyProposal(
        schema_version="1.0",
        proposal_id="prop_alpha_01",
        target_repository_root=repo_a.as_posix(),
        target_branch="main",
        target_head_hash=head_a,
        base_commit_hash=head_a,
        code_patch_artifact_id="art_patch_a",
        code_patch_sha256="dummy_sha_a",
        patch_version=1,
        qa_report_artifact_id="art_qa_a",
        qa_report_sha256="dummy_qa_sha_a",
        qa_execution_report_artifact_id="art_qa_exec_a",
        qa_execution_report_sha256="dummy_qa_exec_sha_a",
        qa_verdict="PASS",
        expected_changed_files=("README.md",),
        expected_diff_stat={"files_changed": 1, "insertions": 1, "deletions": 0},
        is_clean=True,
        created_at="2026-10-05T12:00:00Z",
        proposal_sha256="proposal_hash_alpha",
        project_id="prj_alpha",
        repository_id="repo_alpha",
    )

    # 1. Deriving grant with mismatched project_id fails closed
    with pytest.raises(CrossProjectMismatchError, match="project_id.*!= proposal project_id"):
        derive_real_repo_apply_grant(
            proposal=proposal_a,
            founder_approval_id="founder_appr_1",
            project_id="prj_beta",  # Attempting to authorize under Project B!
        )

    # Derive valid grant for Project A
    grant_a = derive_real_repo_apply_grant(
        proposal=proposal_a,
        founder_approval_id="founder_appr_1",
        project_id="prj_alpha",
    )
    assert grant_a.project_id == "prj_alpha"

    # 2. Service execution: attempt to execute Project A grant against Project B
    service = CompanyService(repo_root=repo_a)
    service._real_repo_apply_proposals[proposal_a.proposal_id] = proposal_a
    service._real_repo_apply_grants[grant_a.grant_id] = grant_a

    # Execution specifying target project_id="prj_beta" FAILS CLOSED
    with pytest.raises(CrossProjectMismatchError, match="Cross-project apply rejected"):
        service.execute_real_repo_apply(
            grant_id=grant_a.grant_id,
            project_id="prj_beta",
        )

    # 3. Verify ZERO target repository mutation on either repo
    code_a, stat_a, _ = run_git(["status", "--porcelain"], cwd=repo_a)
    code_b, stat_b, _ = run_git(["status", "--porcelain"], cwd=repo_b)

    assert code_a == 0 and stat_a.strip() == "", "Repo A must remain 100% clean."
    assert code_b == 0 and stat_b.strip() == "", "Repo B must remain 100% clean."
    assert resolve_repo_head_commit(repo_a) == head_a
    assert resolve_repo_head_commit(repo_b) == head_b
