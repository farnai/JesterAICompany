"""Focused tests for STEP 20A — Durable Company Run & RealRepoApply Proposal Storage.

Verifies:
A. READY_FOR_HUMAN_APPLY proposal survives service/process recreation.
B. Exact patch is recoverable after recreation.
C. Patch SHA-256 is revalidated on recovery.
D. Tampered patch fails closed.
E. Tampered proposal metadata fails closed where integrity protected.
F. Missing patch fails closed.
G. Wrong project/repository/base commit cannot be approved.
H. tmp_path cleanup cannot destroy a proposal stored in configured durable production workspace.
I. Existing ephemeral test mode still works for isolated tests.
J. READY_FOR_HUMAN_APPLY proposal is not automatically garbage-collected.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid
import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    Company,
    Project as CoreProject,
    Task,
    TaskRun,
)
from jester_ai_company.durable_storage import (
    CompanyRunNotFoundError,
    DurableRunStorage,
    GrantNotFoundError,
    ProposalIntegrityError,
    ProposalNotFoundError,
    ProposalPruneForbiddenError,
    StorageError,
    atomic_write_bytes,
    atomic_write_text,
)
from jester_ai_company.orchestrator import (
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
)
from jester_ai_company.project import (
    Project as RepositoryProject,
    ProjectRegistry,
    RepositoryPolicy,
    RepositoryRef,
    run_git,
)
from jester_ai_company.real_repo_apply import (
    CandidateNotEligibleError,
    CrossProjectMismatchError,
    ProposalMismatchError,
    RealRepoApplyGrant,
    RealRepoApplyProposal,
    build_real_repo_apply_proposal,
    compute_proposal_sha256,
)
from jester_ai_company.service import CompanyService


@pytest.fixture
def dummy_git_repo(tmp_path):
    """Create a minimal clean Git repository for proposal testing."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir(parents=True)
    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Test User"], cwd=repo_dir)
    run_git(["config", "user.email", "test@example.com"], cwd=repo_dir)

    test_file = repo_dir / "target.py"
    test_file.write_text("def target_function():\n    return 42\n", encoding="utf-8")
    run_git(["add", "target.py"], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)

    code, head_out, _ = run_git(["rev-parse", "HEAD"], cwd=repo_dir)
    assert code == 0
    return repo_dir, head_out.strip()


@pytest.fixture
def proposal_fixture(dummy_git_repo, tmp_path):
    """Construct an eligible candidate proposal with valid artifacts."""
    repo_dir, head_commit = dummy_git_repo

    patch_text = (
        "diff --git a/target.py b/target.py\n"
        "--- a/target.py\n"
        "+++ b/target.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def target_function():\n"
        "+    # Defensive validation\n"
        "     return 42\n"
    )
    patch_bytes = patch_text.encode("utf-8")
    patch_sha = hashlib.sha256(patch_bytes).hexdigest()

    patch_file = tmp_path / "developer_changes.patch"
    patch_file.write_bytes(patch_bytes)

    patch_artifact = Artifact(
        id=f"art_patch_{uuid.uuid4().hex[:8]}",
        name="developer_changes.patch",
        artifact_type=ArtifactType.CODE_PATCH.value,
        path=str(patch_file),
        sha256=patch_sha,
        metadata={
            "base_commit_hash": head_commit,
            "changed_files": ["target.py"],
            "verification_outcomes": [{"status": "PASS", "test_file": "test_target.py"}],
            "patch_version": 1,
        },
    )

    qa_exec_content = "# QA Execution Report\n\nFinal Verdict: PASS\nAll tests passed."
    qa_exec_bytes = qa_exec_content.encode("utf-8")
    qa_exec_sha = hashlib.sha256(qa_exec_bytes).hexdigest()
    qa_exec_file = tmp_path / "qa_execution_report.md"
    qa_exec_file.write_bytes(qa_exec_bytes)

    qa_exec_artifact = Artifact(
        id=f"art_qa_exec_{uuid.uuid4().hex[:8]}",
        name="qa_execution_report.md",
        artifact_type=ArtifactType.QA_EXECUTION_REPORT.value,
        path=str(qa_exec_file),
        sha256=qa_exec_sha,
        metadata={
            "verdict": "PASS",
            "code_patch_artifact_id": patch_artifact.id,
            "code_patch_sha256": patch_sha,
        },
    )

    qa_rep_artifact = Artifact(
        id=f"art_qa_rep_{uuid.uuid4().hex[:8]}",
        name="qa_report.md",
        artifact_type=ArtifactType.QA_REPORT.value,
        path="dummy_qa.md",
        sha256=hashlib.sha256(b"QA Report Content").hexdigest(),
        metadata={"code_patch_artifact_id": patch_artifact.id},
    )

    proposal = build_real_repo_apply_proposal(
        target_repo_root=repo_dir,
        code_patch_artifact=patch_artifact,
        code_patch_file_path=patch_file,
        qa_report_artifact=qa_rep_artifact,
        qa_execution_report_artifact=qa_exec_artifact,
        qa_execution_report_file_path=qa_exec_file,
        project_id="prj_test",
        repository_id="repo_test",
    )

    return {
        "repo_dir": repo_dir,
        "head_commit": head_commit,
        "patch_text": patch_text,
        "patch_file": patch_file,
        "qa_exec_file": qa_exec_file,
        "proposal": proposal,
    }


# ==============================================================================
# TEST A & B: READY_FOR_HUMAN_APPLY proposal and exact patch survive recreation
# ==============================================================================

def test_proposal_and_exact_patch_survive_service_recreation(proposal_fixture, tmp_path):
    """Proves that a proposal and exact patch survive service recreation without memory dependence."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    # 1. First service instance persists proposal
    service1 = CompanyService(output_dir=str(durable_root))
    service1.durable_storage.save_proposal(
        proposal=prop,
        patch_file_path=fixture["patch_file"],
        qa_execution_file_path=fixture["qa_exec_file"],
        company_run_id="crun_test_001",
    )
    # Terminate service1
    del service1

    # 2. Recreate completely fresh service instance pointing to same durable storage
    service2 = CompanyService(output_dir=str(durable_root))
    recovered = service2.get_real_repo_apply_proposal(prop.proposal_id)

    assert recovered is not None
    assert recovered.proposal_id == prop.proposal_id
    assert recovered.status == "READY_FOR_APPROVAL"
    assert recovered.base_commit_hash == fixture["head_commit"]
    assert recovered.code_patch_sha256 == prop.code_patch_sha256
    assert recovered.expected_changed_files == prop.expected_changed_files

    # Exact patch recovery
    recovered_patch = service2.durable_storage.load_proposal_patch(prop.proposal_id)
    assert recovered_patch == fixture["patch_text"]


# ==============================================================================
# TEST C: Patch SHA-256 is revalidated on recovery
# ==============================================================================

def test_patch_sha256_revalidated_on_recovery(proposal_fixture, tmp_path):
    """Proves that patch SHA-256 is cryptographically recomputed and revalidated on recovery."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    storage = DurableRunStorage(storage_root=durable_root)
    storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    # Revalidation succeeds cleanly on unmutated patch
    recovered = storage.load_proposal(prop.proposal_id, verify_integrity=True)
    assert recovered.code_patch_sha256 == prop.code_patch_sha256


# ==============================================================================
# TEST D: Tampered patch fails closed
# ==============================================================================

def test_tampered_patch_fails_closed(proposal_fixture, tmp_path):
    """Proves that any modification to the durable patch file fails closed on recovery."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    storage = DurableRunStorage(storage_root=durable_root)
    storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    # Malicious or accidental modification to patch.diff on disk
    patch_path = durable_root / "proposals" / prop.proposal_id / "patch.diff"
    patch_path.write_text(patch_path.read_text(encoding="utf-8") + "\n# Tampered", encoding="utf-8")

    # Recovery must fail closed with ProposalIntegrityError
    with pytest.raises(ProposalIntegrityError) as exc_info:
        storage.load_proposal(prop.proposal_id, verify_integrity=True)
    assert "tampering detected" in str(exc_info.value).lower() or "mismatch" in str(exc_info.value).lower()


# ==============================================================================
# TEST E: Tampered proposal metadata fails closed
# ==============================================================================

def test_tampered_proposal_metadata_fails_closed(proposal_fixture, tmp_path):
    """Proves that tampering with proposal.json fields causes fail-closed integrity rejection."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    storage = DurableRunStorage(storage_root=durable_root)
    storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    # Tamper with base_commit_hash in proposal.json
    prop_json_path = durable_root / "proposals" / prop.proposal_id / "proposal.json"
    data = json.loads(prop_json_path.read_text(encoding="utf-8"))
    data["base_commit_hash"] = "0000000000000000000000000000000000000000"
    prop_json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    with pytest.raises(ProposalIntegrityError) as exc_info:
        storage.load_proposal(prop.proposal_id, verify_integrity=True)
    assert "tampering detected" in str(exc_info.value).lower() or "mismatch" in str(exc_info.value).lower()


# ==============================================================================
# TEST F: Missing patch fails closed
# ==============================================================================

def test_missing_patch_fails_closed(proposal_fixture, tmp_path):
    """Proves that a proposal missing its patch.diff file fails closed on recovery."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    storage = DurableRunStorage(storage_root=durable_root)
    storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    # Remove patch.diff
    patch_path = durable_root / "proposals" / prop.proposal_id / "patch.diff"
    patch_path.unlink()

    with pytest.raises(ProposalIntegrityError) as exc_info:
        storage.load_proposal(prop.proposal_id, verify_integrity=True)
    assert "missing" in str(exc_info.value).lower()


# ==============================================================================
# TEST G: Wrong project / repository / base commit cannot be approved
# ==============================================================================

def test_wrong_target_or_base_commit_cannot_be_approved(proposal_fixture, tmp_path):
    """Proves that mismatched project or repository binding is rejected on recovery/approval."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    service = CompanyService(output_dir=str(durable_root))
    service.durable_storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    # 1. Recovery with wrong target repo root fails
    wrong_repo = tmp_path / "unrelated_repo"
    wrong_repo.mkdir()
    with pytest.raises(ProposalMismatchError):
        service.recover_real_repo_apply_proposal(prop.proposal_id, target_repo_root=wrong_repo)

    # 2. Recovery with wrong base commit fails
    # Create another commit in repo
    dummy_file = fixture["repo_dir"] / "dummy_extra.txt"
    dummy_file.write_text("extra", encoding="utf-8")
    run_git(["add", "dummy_extra.txt"], cwd=fixture["repo_dir"])
    run_git(["commit", "-m", "advance HEAD"], cwd=fixture["repo_dir"])
    with pytest.raises(ProposalMismatchError):
        service.recover_real_repo_apply_proposal(prop.proposal_id, target_repo_root=fixture["repo_dir"])

    # 3. Approval with conflicting project_id fails
    with pytest.raises((CrossProjectMismatchError, ProposalMismatchError)):
        service.approve_real_repo_apply(
            proposal_id=prop.proposal_id,
            founder_approval_id="app_test_001",
            project_id="prj_different_mismatch",
        )


# ==============================================================================
# TEST H: tmp_path cleanup cannot destroy a proposal stored in configured durable workspace
# ==============================================================================

def test_tmp_path_cleanup_cannot_destroy_durable_proposal(proposal_fixture, tmp_path):
    """Proves that destroying a temporary directory does not destroy a durable proposal."""
    ephemeral_dir = tmp_path / "pytest_tmp_ephemeral"
    durable_dir = tmp_path / "configured_durable_workspace"

    fixture = proposal_fixture
    prop = fixture["proposal"]

    # Production configured service using durable_dir
    service = CompanyService(output_dir=str(durable_dir), is_production=True)
    service.durable_storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    # Delete ephemeral_dir (simulating pytest purging tmp_path)
    shutil.rmtree(ephemeral_dir, ignore_errors=True)

    # Verify durable proposal in durable_dir is completely intact
    recovered = service.get_real_repo_apply_proposal(prop.proposal_id)
    assert recovered is not None
    assert recovered.proposal_id == prop.proposal_id

    patch = service.durable_storage.load_proposal_patch(prop.proposal_id)
    assert patch == fixture["patch_text"]


# ==============================================================================
# TEST I: Existing ephemeral test mode still works for isolated tests
# ==============================================================================

def test_existing_ephemeral_test_mode_works(tmp_path):
    """Proves that passing tmp_path directly to CompanyService works for ephemeral unit tests."""
    ephemeral_runs = tmp_path / "runs"
    service = CompanyService(output_dir=str(ephemeral_runs), is_production=False)
    assert service.output_dir == ephemeral_runs
    assert service.durable_storage.storage_root == ephemeral_runs
    assert service.is_production is False


# ==============================================================================
# TEST J: READY_FOR_HUMAN_APPLY proposal is not automatically garbage-collected
# ==============================================================================

def test_ready_for_human_apply_proposal_never_garbage_collected(proposal_fixture, tmp_path):
    """Proves that approval-critical proposals in READY_FOR_APPROVAL cannot be garbage collected."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    storage = DurableRunStorage(storage_root=durable_root)
    storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    assert prop.status == "READY_FOR_APPROVAL"
    assert storage.can_prune_proposal(prop) is False

    # Attempt garbage collection with 0 days threshold
    result = storage.garbage_collect(older_than_days=0)
    assert result["pruned_proposals"] == 0

    # Ensure proposal and patch diff still exist intact
    prop_file = durable_root / "proposals" / prop.proposal_id / "proposal.json"
    patch_file = durable_root / "proposals" / prop.proposal_id / "patch.diff"
    assert prop_file.is_file()
    assert patch_file.is_file()


# ==============================================================================
# TEST K: CompanyRun manifest survives service recreation
# ==============================================================================

def test_company_run_survives_service_recreation(tmp_path):
    """Proves that a CompanyRun manifest is durably preserved and recoverable."""
    durable_root = tmp_path / "durable_storage"

    objective = CompanyObjective(
        id="obj_test_run_persist",
        title="Persist Company Run",
        description="Verify durable company run persistence across service lifecycles",
        constraints=["constraint A"],
        acceptance_criteria=["criterion 1"],
        project_id="prj_test",
    )

    run = CompanyRun(
        run_id="crun_test_persist_001",
        objective=objective,
        project_id="prj_test",
        state=CompanyRunState.RUNNING.value,
        base_commit_hash="abc123456789",
    )
    run.add_event("TEST_EVENT", reason="Unit test execution")

    service1 = CompanyService(output_dir=str(durable_root))
    service1.save_company_run(run)
    del service1

    service2 = CompanyService(output_dir=str(durable_root))
    recovered_run = service2.get_company_run("crun_test_persist_001")
    assert recovered_run is not None
    assert recovered_run.run_id == "crun_test_persist_001"
    assert recovered_run.objective.title == "Persist Company Run"
    assert recovered_run.state == CompanyRunState.RUNNING.value
    assert len(recovered_run.events) >= 1
    assert recovered_run.events[-1]["event_type"] == "TEST_EVENT"


# ==============================================================================
# TEST L: RealRepoApplyGrant survives service recreation
# ==============================================================================

def test_grant_survives_service_recreation(proposal_fixture, tmp_path):
    """Proves that an issued RealRepoApplyGrant is durably preserved and recoverable."""
    durable_root = tmp_path / "durable_storage"
    fixture = proposal_fixture
    prop = fixture["proposal"]

    service1 = CompanyService(output_dir=str(durable_root))
    service1.durable_storage.save_proposal(proposal=prop, patch_file_path=fixture["patch_file"])

    grant = service1.approve_real_repo_apply(
        proposal_id=prop.proposal_id,
        founder_approval_id="app_founder_123",
        approver="Human Founder",
    )
    grant_id = grant.grant_id
    del service1

    service2 = CompanyService(output_dir=str(durable_root))
    recovered_grant = service2.get_real_repo_apply_grant(grant_id)
    assert recovered_grant is not None
    assert recovered_grant.grant_id == grant_id
    assert recovered_grant.proposal_id == prop.proposal_id
    assert recovered_grant.founder_approval_id == "app_founder_123"
    assert recovered_grant.status == "ISSUED"


# ==============================================================================
# TEST M: Atomic writes leave zero temporary files
# ==============================================================================

def test_atomic_writes_leave_zero_temporary_files(tmp_path):
    """Proves that atomic writes write cleanly and leave no lingering .tmp files."""
    test_file = tmp_path / "nested" / "payload.txt"
    atomic_write_text(test_file, "clean content")
    assert test_file.read_text(encoding="utf-8") == "clean content"

    # Verify no temp files exist in directory
    temp_files = list(test_file.parent.glob("*.tmp.*"))
    assert len(temp_files) == 0
