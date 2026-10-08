"""Focused regression tests for STEP 22H: Approval Artifact Resolution Failure & Durable Recovery.

Verifies:
1. Durable proposal survives production service reconstruction.
2. Approval resolves the original CODE_PATCH artifact.
3. Artifact ID and SHA-256 match the proposal.
4. Fallback to durable proposal patch works when original task directory is pruned.
5. Missing artifact fails closed.
6. Mismatched artifact fails closed (disk checksum mismatch).
7. Wrong run/proposal identity fails closed.
8. Failed approval cannot leave an unintended grant.
9. Existing approval lifecycle invariants remain intact.
"""

import dataclasses
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict
import uuid
import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    ArtifactVerificationError,
    RunStatus,
    TaskStatus,
)
from jester_ai_company.durable_storage import (
    DurableRunStorage,
    ProposalIntegrityError,
    ProposalNotFoundError,
)
from jester_ai_company.engineering_pipeline import EngineeringPipelineAdapter
from jester_ai_company.execution_grant import MissingApprovalError
from jester_ai_company.orchestrator import (
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    EmployeeResultSummary,
    OrchestrationError,
    TransitionPolicyError,
)
from jester_ai_company.real_repo_apply import (
    ApprovalInvalidError,
    CandidateNotEligibleError,
    ProposalMismatchError,
    RealRepoApplyGrant,
    RealRepoApplyProposal,
    compute_proposal_sha256,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.worktree import resolve_repo_head_commit, run_git


@pytest.fixture
def isolated_env():
    """Create a completely isolated temp environment with mock git repository and durable workspace."""
    temp_dir = Path(tempfile.mkdtemp(prefix="test_step22h_"))
    repo_dir = temp_dir / "target_repo"
    workspace_dir = temp_dir / ".runs"
    repo_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # Initialize a clean git repo
    run_git(["init"], cwd=repo_dir)
    run_git(["config", "user.name", "Test Runner"], cwd=repo_dir)
    run_git(["config", "user.email", "runner@example.com"], cwd=repo_dir)
    (repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    (repo_dir / "app.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "Initial commit"], cwd=repo_dir)
    head_hash = resolve_repo_head_commit(repo_dir)

    service = CompanyService.create_production(repo_root=temp_dir, workspace_dir=workspace_dir)

    try:
        yield {
            "temp_dir": temp_dir,
            "repo_dir": repo_dir,
            "workspace_dir": workspace_dir,
            "head_hash": head_hash,
            "service": service,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _create_sample_patch_and_proposal(env: Dict[str, Any], patch_text: str = None) -> Dict[str, Any]:
    """Helper to create a realistic proposal, patch file, and company run in durable storage."""
    workspace_dir: Path = env["workspace_dir"]
    repo_dir: Path = env["repo_dir"]
    head_hash: str = env["head_hash"]
    service: CompanyService = env["service"]

    if patch_text is None:
        patch_text = (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def hello():\n"
            "+    # Added line\n"
            "     return 'world'\n"
        )

    patch_bytes = patch_text.encode("utf-8")
    patch_sha = hashlib.sha256(patch_bytes).hexdigest()
    art_id = str(uuid.uuid4().hex[:8])
    prop_id = f"prop_apply_{uuid.uuid4().hex[:8]}"
    run_id = f"crun_{uuid.uuid4().hex[:8]}"

    # Write original task artifact to disk
    task_rel_path = f"task_{run_id}_dev/run_{run_id}_01/artifacts/developer_changes.patch"
    task_abs_path = workspace_dir / task_rel_path
    task_abs_path.parent.mkdir(parents=True, exist_ok=True)
    task_abs_path.write_bytes(patch_bytes)

    proposal = RealRepoApplyProposal(
        schema_version="1.0",
        proposal_id=prop_id,
        target_repository_root=str(repo_dir).replace("\\", "/"),
        target_branch="main",
        target_head_hash=head_hash,
        base_commit_hash=head_hash,
        code_patch_artifact_id=art_id,
        code_patch_sha256=patch_sha,
        patch_version=1,
        qa_report_artifact_id="art_qa_rep_01",
        qa_report_sha256="0" * 64,
        qa_execution_report_artifact_id="art_qa_exec_01",
        qa_execution_report_sha256="0" * 64,
        qa_verdict="PASS",
        expected_changed_files=("app.py",),
        expected_diff_stat={"files_changed": 1, "insertions": 1, "deletions": 0},
        is_clean=True,
        created_at=datetime.now(timezone.utc).isoformat(),
        proposal_sha256="",
        project_id="prj_default",
    )
    proposal = dataclasses.replace(proposal, proposal_sha256=compute_proposal_sha256(proposal))

    # Persist proposal into durable storage
    service.durable_storage.save_proposal(
        proposal=proposal,
        patch_content=patch_text,
        company_run_id=run_id,
    )

    # Build and persist CompanyRun
    run = CompanyRun(
        run_id=run_id,
        objective=CompanyObjective(id=f"obj_{run_id}", title="Test", description="Goal", project_id="prj_default"),
        state=CompanyRunState.READY_FOR_HUMAN_APPLY.value,
        project_id="prj_default",
        code_patch_artifact_id=art_id,
        qa_execution_report_artifact_id="art_qa_exec_01",
        real_repo_apply_proposal_id=prop_id,
        employee_summaries=[
            EmployeeResultSummary(
                role="developer",
                task_id=f"task_{run_id}_dev",
                run_id=f"run_{run_id}_01",
                status="COMPLETED",
                artifact_refs=[
                    {
                        "artifact_id": art_id,
                        "name": "developer_changes.patch",
                        "type": "CODE_PATCH",
                        "sha256": patch_sha,
                        "path": task_rel_path,
                    }
                ],
                summary="Developer produced code patch",
            )
        ],
    )
    service.durable_storage.save_company_run(run)

    return {
        "run_id": run_id,
        "proposal_id": prop_id,
        "artifact_id": art_id,
        "patch_sha": patch_sha,
        "task_abs_path": task_abs_path,
        "proposal": proposal,
        "run": run,
    }


def test_durable_proposal_survives_production_service_reconstruction(isolated_env):
    """1. Verify durable proposal and run survive service reconstruction and approval resolves CODE_PATCH."""
    data = _create_sample_patch_and_proposal(isolated_env)
    run_id = data["run_id"]
    prop_id = data["proposal_id"]
    art_id = data["artifact_id"]
    patch_sha = data["patch_sha"]

    # Reconstruct fresh production service instance from disk (simulating restart)
    new_service = CompanyService.create_production(
        repo_root=isolated_env["temp_dir"],
        workspace_dir=isolated_env["workspace_dir"],
    )

    # 1. find_artifact resolves the artifact from durable CompanyRun
    lineage = new_service.find_artifact(art_id)
    assert lineage is not None, "find_artifact must resolve artifact from durable run"
    task, task_run, patch_art = lineage
    assert patch_art.id == art_id
    assert patch_art.sha256 == patch_sha

    # 2. Approve repo apply resolves the artifact and issues grant
    grant = new_service.approve_company_repo_apply(
        run_id=run_id,
        founder_approval_id="founder_signoff_step22h",
        approver="Human Founder",
    )

    assert grant is not None
    assert grant.proposal_id == prop_id
    assert grant.code_patch_artifact_id == art_id
    assert grant.code_patch_sha256 == patch_sha
    assert grant.human_approval_id == "founder_signoff_step22h"

    # Verify run state updated and audit event logged
    updated_run = new_service.get_company_run(run_id)
    assert updated_run.real_repo_apply_grant_id == grant.grant_id
    events = [e for e in updated_run.events if e.get("event_type") == "HUMAN_APPLY_APPROVED"]
    assert len(events) == 1
    assert events[0]["details"]["grant_id"] == grant.grant_id


def test_approval_resolves_via_durable_proposal_fallback_when_task_dir_pruned(isolated_env):
    """2. Verify fallback to durable proposal patch.diff if intermediate task directory was pruned."""
    data = _create_sample_patch_and_proposal(isolated_env)
    run_id = data["run_id"]
    art_id = data["artifact_id"]
    patch_sha = data["patch_sha"]
    task_abs_path: Path = data["task_abs_path"]

    # Prune/delete the original task patch file
    assert task_abs_path.is_file()
    task_abs_path.unlink()
    assert not task_abs_path.is_file()

    # Reconstruct fresh production service
    new_service = CompanyService.create_production(
        repo_root=isolated_env["temp_dir"],
        workspace_dir=isolated_env["workspace_dir"],
    )

    # Approval should resolve via durable proposal storage patch.diff
    grant = new_service.approve_company_repo_apply(
        run_id=run_id,
        founder_approval_id="founder_pruned_test",
        approver="Human Founder",
    )

    assert grant is not None
    assert grant.code_patch_artifact_id == art_id
    assert grant.code_patch_sha256 == patch_sha


def test_missing_artifact_fails_closed(isolated_env):
    """3. Verify missing artifact fails closed when neither task path nor durable patch exists."""
    data = _create_sample_patch_and_proposal(isolated_env)
    run_id = data["run_id"]
    prop_id = data["proposal_id"]
    task_abs_path: Path = data["task_abs_path"]

    # Delete original task artifact AND durable proposal patch.diff
    task_abs_path.unlink()
    durable_patch = isolated_env["workspace_dir"] / "proposals" / prop_id / "patch.diff"
    durable_patch.unlink()

    new_service = CompanyService.create_production(
        repo_root=isolated_env["temp_dir"],
        workspace_dir=isolated_env["workspace_dir"],
    )

    with pytest.raises((ArtifactVerificationError, ProposalMismatchError)):
        new_service.approve_company_repo_apply(
            run_id=run_id,
            founder_approval_id="founder_missing_test",
        )

    # Verify no grant was created
    run = new_service.get_company_run(run_id)
    assert run.real_repo_apply_grant_id is None
    assert len(new_service.durable_storage.list_grants()) == 0


def test_mismatched_artifact_sha256_fails_closed(isolated_env):
    """4. Verify tampered/mismatched patch on disk fails closed."""
    data = _create_sample_patch_and_proposal(isolated_env)
    run_id = data["run_id"]
    task_abs_path: Path = data["task_abs_path"]

    # Tamper with the physical task artifact
    task_abs_path.write_bytes(b"TAMPERED MALICIOUS CONTENT")

    new_service = CompanyService.create_production(
        repo_root=isolated_env["temp_dir"],
        workspace_dir=isolated_env["workspace_dir"],
    )

    with pytest.raises(ArtifactVerificationError, match="checksum mismatch"):
        new_service.approve_company_repo_apply(
            run_id=run_id,
            founder_approval_id="founder_tamper_test",
        )

    # Verify no grant was created
    run = new_service.get_company_run(run_id)
    assert run.real_repo_apply_grant_id is None


def test_wrong_run_or_proposal_identity_fails_closed(isolated_env):
    """5. Verify mismatched run/proposal identity fails closed."""
    data = _create_sample_patch_and_proposal(isolated_env)
    run_id = data["run_id"]

    new_service = CompanyService.create_production(
        repo_root=isolated_env["temp_dir"],
        workspace_dir=isolated_env["workspace_dir"],
    )
    run = new_service.get_company_run(run_id)

    # Scenario A: Run's code_patch_artifact_id doesn't match proposal
    run.code_patch_artifact_id = "art_foreign"
    new_service.save_company_run(run)

    with pytest.raises(ProposalMismatchError):
        new_service.approve_company_repo_apply(
            run_id=run_id,
            founder_approval_id="founder_id_mismatch",
        )

    # Reset
    run.code_patch_artifact_id = data["artifact_id"]
    # Scenario B: Run references nonexistent proposal
    run.real_repo_apply_proposal_id = "prop_nonexistent_99"
    new_service.save_company_run(run)

    with pytest.raises(ProposalMismatchError):
        new_service.approve_company_repo_apply(
            run_id=run_id,
            founder_approval_id="founder_prop_mismatch",
        )


def test_failed_approval_leaves_no_unintended_grant(isolated_env):
    """6. Verify failed approval cannot leave an unintended grant or partial state."""
    data = _create_sample_patch_and_proposal(isolated_env)
    run_id = data["run_id"]

    new_service = CompanyService.create_production(
        repo_root=isolated_env["temp_dir"],
        workspace_dir=isolated_env["workspace_dir"],
    )

    # Empty approval ID fails closed
    with pytest.raises(MissingApprovalError):
        new_service.approve_company_repo_apply(
            run_id=run_id,
            founder_approval_id="",
        )

    # Verify state remains READY_FOR_HUMAN_APPLY with no grant
    run = new_service.get_company_run(run_id)
    assert run.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value
    assert run.real_repo_apply_grant_id is None
    assert len(new_service.durable_storage.list_grants()) == 0


def test_existing_approval_lifecycle_invariants_preserved(isolated_env):
    """7. Verify existing lifecycle invariants: cannot approve if run not in READY_FOR_HUMAN_APPLY."""
    data = _create_sample_patch_and_proposal(isolated_env)
    run_id = data["run_id"]

    new_service = CompanyService.create_production(
        repo_root=isolated_env["temp_dir"],
        workspace_dir=isolated_env["workspace_dir"],
    )
    run = new_service.get_company_run(run_id)
    run.state = CompanyRunState.CREATED.value
    new_service.save_company_run(run)

    with pytest.raises(TransitionPolicyError):
        new_service.approve_company_repo_apply(
            run_id=run_id,
            founder_approval_id="founder_lifecycle_test",
        )
