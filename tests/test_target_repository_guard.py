"""Target Repository Identity Guard Tests.

Verifies fail-closed enforcement of target repository identity:
- Authoritative Real Jester (C:\\Users\\fiord\\OneDrive\\Desktop\\Jester) passes all checks.
- Scratch shadow repository (scratch\\jester, scratch\\JesteChat, JesterAI) is strictly rejected.
- Mismatched paths, remotes, branches, and commits fail-closed.
"""

from pathlib import Path
import pytest

from jester_ai_company.project import (
    Project,
    RepositoryRef,
    RepositoryPolicy,
    TargetRepositoryMismatchError,
    TargetRepositoryVerification,
    verify_target_repository_identity,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.orchestrator import CompanyObjective


REAL_JESTER_PATH = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester").resolve()
REAL_JESTER_HEAD = "2173b2dd72c9802421963788e7dd0d0087af68af"
SCRATCH_JESTER_PATH = Path(r"C:\Users\fiord\.gemini\antigravity-ide\scratch\jester").resolve()


def _make_jester_project(root_path: Path, expected_remote: str = "git@github.com:farnai/Jester.git") -> Project:
    return Project(
        project_id="prj_jester",
        name="Jester — People Discovery & Relationship Intelligence Engine",
        description="Authoritative Jester project",
        repository=RepositoryRef(
            repository_id="repo_jester",
            root_path=str(root_path),
            target_branch="main",
            expected_remote=expected_remote,
            allow_untracked=True,
        ),
        policy=RepositoryPolicy(
            read_allowed=("docs/**", "backend/**", "frontend/**", "tests/**", "*.md"),
            mutation_allowed=(),
            denied=(".git", ".git/**", ".env*"),
        ),
    )


def test_real_jester_passes_target_identity_verification():
    """Verify that the real Jester repository passes all identity checks."""
    project = _make_jester_project(REAL_JESTER_PATH)

    verification = verify_target_repository_identity(
        project=project,
        candidate_repo_path=REAL_JESTER_PATH,
        expected_head=REAL_JESTER_HEAD,
        expected_branch="main",
        expected_remote="farnai/Jester",
    )

    assert isinstance(verification, TargetRepositoryVerification)
    assert verification.project_id == "prj_jester"
    assert verification.project_name == "Jester — People Discovery & Relationship Intelligence Engine"
    assert verification.repository_root == REAL_JESTER_PATH.as_posix()
    assert verification.repository_head == REAL_JESTER_HEAD
    assert verification.branch == "main"
    assert "CLEAN" in verification.working_tree_state
    assert verification.is_valid is True
    assert "farnai/Jester" in (verification.remote_url or "")


def test_scratch_jester_is_strictly_rejected():
    """Verify that scratch/jester (formerly JesteChat) is rejected fail-closed."""
    if not SCRATCH_JESTER_PATH.exists():
        pytest.skip("Scratch jester directory not present on this machine")

    scratch_project = _make_jester_project(
        SCRATCH_JESTER_PATH,
        expected_remote="https://github.com/farnai/JesterAI.git",
    )

    with pytest.raises(TargetRepositoryMismatchError) as exc_info:
        verify_target_repository_identity(project=scratch_project)

    err_msg = str(exc_info.value)
    assert "scratch shadow repository" in err_msg or "JesterAI.git" in err_msg or "REJECTED" in err_msg


def test_candidate_repo_path_mismatch_fails_closed():
    """Verify that passing an unexpected candidate path fails closed."""
    project = _make_jester_project(REAL_JESTER_PATH)
    fake_path = Path(r"C:\Users\fiord\SomeOtherPath").resolve()

    with pytest.raises(TargetRepositoryMismatchError) as exc_info:
        verify_target_repository_identity(
            project=project,
            candidate_repo_path=fake_path,
        )

    assert "does not match registered Project" in str(exc_info.value)


def test_mismatched_expected_head_fails_closed():
    """Verify that head commit mismatch fails closed."""
    project = _make_jester_project(REAL_JESTER_PATH)

    with pytest.raises(TargetRepositoryMismatchError) as exc_info:
        verify_target_repository_identity(
            project=project,
            expected_head="0000000000000000000000000000000000000000",
        )

    assert "does not match expected commit" in str(exc_info.value)


def test_mismatched_expected_branch_fails_closed():
    """Verify that branch mismatch fails closed."""
    project = _make_jester_project(REAL_JESTER_PATH)

    with pytest.raises(TargetRepositoryMismatchError) as exc_info:
        verify_target_repository_identity(
            project=project,
            expected_branch="nonexistent-target-branch",
        )

    assert "does not match expected branch" in str(exc_info.value)


def test_company_service_create_run_verifies_target_identity(tmp_path):
    """Verify that CompanyService verifies target identity when creating a run."""
    service = CompanyService(output_dir=str(tmp_path))
    real_project = _make_jester_project(REAL_JESTER_PATH)
    service.register_repository_project(real_project)

    objective = CompanyObjective(
        id="obj_guard_test",
        title="Target Guard Test",
        description="Verify service run identity guard",
        target_repository=str(REAL_JESTER_PATH),
    )

    run = service.create_company_run(
        project_id="prj_jester",
        objective=objective,
        base_commit_hash=REAL_JESTER_HEAD,
        target_branch="main",
    )

    assert run.target_repository_verification is not None
    assert run.target_repository_verification["project_id"] == "prj_jester"
    assert run.target_repository_verification["repository_root"] == REAL_JESTER_PATH.as_posix()
    assert run.target_repository_verification["repository_head"] == REAL_JESTER_HEAD
    assert run.target_repository_verification["branch"] == "main"
    assert run.target_repository_verification["is_valid"] is True

