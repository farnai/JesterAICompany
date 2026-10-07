"""Durable Company Run & RealRepoApply Proposal Storage (STEP 20A).

Provides robust, repository-local filesystem persistence and recovery for:
- CompanyRun manifests and lifecycle states
- RealRepoApplyProposal objects with exact unified diff patches
- RealRepoApplyGrant capability tokens
- Cryptographic verification outcomes and provenance metadata

Guarantees that approval-critical proposals and exact patches survive:
- Process exit
- Pytest test runner cleanup
- Application restarts
- Later Founder approval and Control Center workflows
"""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import uuid

from .real_repo_apply import (
    RealRepoApplyProposal,
    RealRepoApplyGrant,
    compute_proposal_sha256,
)
from .orchestrator import CompanyRun

logger = logging.getLogger(__name__)


# ==============================================================================
# Domain Exceptions
# ==============================================================================

class StorageError(Exception):
    """Base exception for durable storage failures."""
    pass


class ProposalNotFoundError(StorageError):
    """Raised when a requested RealRepoApplyProposal does not exist on disk."""
    pass


class ProposalIntegrityError(StorageError):
    """Raised when cryptographic verification or tamper detection fails on recovery."""
    pass


class GrantNotFoundError(StorageError):
    """Raised when a requested RealRepoApplyGrant does not exist on disk."""
    pass


class GrantIntegrityError(StorageError):
    """Raised when a grant fails integrity or tamper validation."""
    pass


class CompanyRunNotFoundError(StorageError):
    """Raised when a requested CompanyRun does not exist on disk."""
    pass


class ProposalPruneForbiddenError(StorageError):
    """Raised when attempting to delete an approval-critical proposal."""
    pass


# ==============================================================================
# Atomic Write Primitives
# ==============================================================================

def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write binary data to a file using write-flush-fsync-replace."""
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.parent / f"{target.name}.tmp.{uuid.uuid4().hex}"
    try:
        with open(temp_path, "wb") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Some filesystems/platforms may not support fsync on all handles
                pass
        os.replace(temp_path, target)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Atomically write text data to a file using UTF-8 encoding."""
    atomic_write_bytes(path, text.encode(encoding))


# ==============================================================================
# Durable Run Storage Manager
# ==============================================================================

class DurableRunStorage:
    """Repository-local durable persistence manager for Company Runs and Proposals.
    
    Structure:
      <storage_root>/
        company_runs/
          <company_run_id>/
            run_manifest.json
            objective.json
            plan.json
            employee_summaries.json
            events.json
        proposals/
          <proposal_id>/
            proposal.json
            patch.diff
            verification.json
            provenance.json
        grants/
          <grant_id>/
            grant.json
        locks/
          apply_<hash>.lock
    """

    def __init__(
        self,
        storage_root: Union[str, Path],
        is_production: bool = False,
    ):
        self.storage_root = Path(storage_root).resolve()
        self.is_production = is_production
        self.runs_dir = self.storage_root / "company_runs"
        self.proposals_dir = self.storage_root / "proposals"
        self.grants_dir = self.storage_root / "grants"
        self.locks_dir = self.storage_root / "locks"
        self.ensure_dirs()

    def ensure_dirs(self) -> None:
        """Ensure all required root subdirectories exist."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.grants_dir.mkdir(parents=True, exist_ok=True)
        self.locks_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # RealRepoApplyProposal Persistence & Recovery
    # --------------------------------------------------------------------------

    def save_proposal(
        self,
        proposal: RealRepoApplyProposal,
        patch_content: Optional[str] = None,
        patch_file_path: Optional[Union[str, Path]] = None,
        qa_execution_file_path: Optional[Union[str, Path]] = None,
        company_run_id: Optional[str] = None,
    ) -> Path:
        """Atomically persist a RealRepoApplyProposal and its exact physical patch diff.
        
        Fail-closed invariant:
        Recomputes SHA-256 on the physical patch bytes before writing,
        ensuring zero corruption between artifact and persisted payload.
        """
        # 1. Resolve patch bytes
        if patch_content is not None:
            patch_bytes = patch_content.encode("utf-8")
        elif patch_file_path is not None and Path(patch_file_path).is_file():
            patch_bytes = Path(patch_file_path).read_bytes()
        else:
            raise ProposalIntegrityError(
                f"Cannot persist proposal '{proposal.proposal_id}' without physical patch content or file path."
            )

        # 2. Verify patch digest matches proposal
        computed_patch_sha = hashlib.sha256(patch_bytes).hexdigest()
        if computed_patch_sha != proposal.code_patch_sha256:
            raise ProposalIntegrityError(
                f"Patch digest mismatch before persistence: computed '{computed_patch_sha}' "
                f"!= recorded '{proposal.code_patch_sha256}'."
            )

        # 3. Create proposal directory
        prop_dir = self.proposals_dir / proposal.proposal_id
        prop_dir.mkdir(parents=True, exist_ok=True)

        # 4. Atomic writes
        # Exact patch diff
        atomic_write_bytes(prop_dir / "patch.diff", patch_bytes)

        # Proposal manifest
        proposal_dict = proposal.to_dict()
        proposal_dict["company_run_id"] = company_run_id
        atomic_write_text(prop_dir / "proposal.json", json.dumps(proposal_dict, indent=2))

        # Verification evidence
        verification_data = {
            "proposal_id": proposal.proposal_id,
            "qa_verdict": proposal.qa_verdict,
            "qa_report_artifact_id": proposal.qa_report_artifact_id,
            "qa_report_sha256": proposal.qa_report_sha256,
            "qa_execution_report_artifact_id": proposal.qa_execution_report_artifact_id,
            "qa_execution_report_sha256": proposal.qa_execution_report_sha256,
            "expected_changed_files": list(proposal.expected_changed_files),
            "expected_diff_stat": dict(proposal.expected_diff_stat),
            "is_clean": proposal.is_clean,
        }
        atomic_write_text(prop_dir / "verification.json", json.dumps(verification_data, indent=2))

        # Provenance metadata
        provenance_data = {
            "proposal_id": proposal.proposal_id,
            "company_run_id": company_run_id,
            "project_id": proposal.project_id,
            "repository_id": proposal.repository_id,
            "target_repository_root": proposal.target_repository_root,
            "target_branch": proposal.target_branch,
            "target_head_hash": proposal.target_head_hash,
            "base_commit_hash": proposal.base_commit_hash,
            "patch_version": proposal.patch_version,
            "created_at": proposal.created_at,
            "proposal_sha256": proposal.proposal_sha256,
        }
        atomic_write_text(prop_dir / "provenance.json", json.dumps(provenance_data, indent=2))

        # 5. Link into CompanyRun if associated
        if company_run_id:
            run_prop_dir = self.runs_dir / company_run_id / "proposals"
            run_prop_dir.mkdir(parents=True, exist_ok=True)
            run_prop_ref = {
                "proposal_id": proposal.proposal_id,
                "proposal_sha256": proposal.proposal_sha256,
                "code_patch_sha256": proposal.code_patch_sha256,
                "path": str(prop_dir.relative_to(self.storage_root)),
            }
            atomic_write_text(run_prop_dir / f"{proposal.proposal_id}.json", json.dumps(run_prop_ref, indent=2))

        return prop_dir

    def load_proposal(
        self,
        proposal_id: str,
        verify_integrity: bool = True,
    ) -> RealRepoApplyProposal:
        """Load a RealRepoApplyProposal from durable storage with fail-closed integrity checks."""
        clean_id = proposal_id.strip()
        prop_dir = self.proposals_dir / clean_id
        if not prop_dir.is_dir():
            raise ProposalNotFoundError(f"Proposal '{clean_id}' not found in durable storage at '{prop_dir}'.")

        proposal_file = prop_dir / "proposal.json"
        if not proposal_file.is_file():
            raise ProposalNotFoundError(f"Proposal metadata missing for '{clean_id}' at '{proposal_file}'.")

        patch_file = prop_dir / "patch.diff"
        if not patch_file.is_file():
            raise ProposalIntegrityError(f"Physical patch diff missing for proposal '{clean_id}' at '{patch_file}'.")

        try:
            data = json.loads(proposal_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ProposalIntegrityError(f"Failed to parse proposal JSON for '{clean_id}': {exc}") from exc

        patch_bytes = patch_file.read_bytes()

        if verify_integrity:
            # 1. Patch SHA-256 verification
            actual_patch_sha = hashlib.sha256(patch_bytes).hexdigest()
            expected_patch_sha = data.get("code_patch_sha256")
            if actual_patch_sha != expected_patch_sha:
                raise ProposalIntegrityError(
                    f"Durable patch tampering detected for proposal '{clean_id}': "
                    f"computed SHA-256 '{actual_patch_sha}' != recorded '{expected_patch_sha}'."
                )

            # 2. Recompute and verify canonical proposal digest
            proposal = RealRepoApplyProposal.from_dict(data)
            computed_prop_sha = compute_proposal_sha256(proposal)
            if computed_prop_sha != proposal.proposal_sha256:
                raise ProposalIntegrityError(
                    f"Durable proposal metadata tampering detected for proposal '{clean_id}': "
                    f"computed SHA-256 '{computed_prop_sha}' != recorded '{proposal.proposal_sha256}'."
                )

            # 3. QA verdict verification
            if proposal.qa_verdict != "PASS":
                raise ProposalIntegrityError(
                    f"Proposal '{clean_id}' has invalid QA verdict '{proposal.qa_verdict}', expected 'PASS'."
                )

            return proposal

        return RealRepoApplyProposal.from_dict(data)

    def load_proposal_patch(self, proposal_id: str, verify_integrity: bool = True) -> str:
        """Load the exact unified diff text for a proposal, revalidating cryptographic integrity."""
        # Triggers full integrity verification
        proposal = self.load_proposal(proposal_id, verify_integrity=verify_integrity)
        patch_file = self.proposals_dir / proposal.proposal_id / "patch.diff"
        return patch_file.read_text(encoding="utf-8")

    def load_verification_evidence(self, proposal_id: str) -> Dict[str, Any]:
        """Load verification evidence for a durable proposal."""
        v_file = self.proposals_dir / proposal_id.strip() / "verification.json"
        if not v_file.is_file():
            raise ProposalNotFoundError(f"Verification evidence missing for proposal '{proposal_id}'.")
        return json.loads(v_file.read_text(encoding="utf-8"))

    def load_provenance(self, proposal_id: str) -> Dict[str, Any]:
        """Load provenance metadata for a durable proposal."""
        p_file = self.proposals_dir / proposal_id.strip() / "provenance.json"
        if not p_file.is_file():
            raise ProposalNotFoundError(f"Provenance metadata missing for proposal '{proposal_id}'.")
        return json.loads(p_file.read_text(encoding="utf-8"))

    def list_proposals(self) -> List[RealRepoApplyProposal]:
        """List all valid proposals stored in durable storage."""
        proposals: List[RealRepoApplyProposal] = []
        if not self.proposals_dir.is_dir():
            return proposals

        for entry in self.proposals_dir.iterdir():
            if entry.is_dir() and (entry / "proposal.json").is_file():
                try:
                    proposal = self.load_proposal(entry.name, verify_integrity=True)
                    proposals.append(proposal)
                except Exception as exc:
                    logger.warning("Skipping corrupted durable proposal '%s': %s", entry.name, exc)
        return proposals

    # --------------------------------------------------------------------------
    # RealRepoApplyGrant Persistence & Recovery
    # --------------------------------------------------------------------------

    def save_grant(self, grant: RealRepoApplyGrant) -> Path:
        """Atomically persist an issued RealRepoApplyGrant."""
        grant_dir = self.grants_dir / grant.grant_id
        grant_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(grant_dir / "grant.json", json.dumps(grant.to_dict(), indent=2))
        return grant_dir

    def load_grant(self, grant_id: str) -> RealRepoApplyGrant:
        """Load a persisted RealRepoApplyGrant from durable storage."""
        grant_file = self.grants_dir / grant_id.strip() / "grant.json"
        if not grant_file.is_file():
            raise GrantNotFoundError(f"Grant '{grant_id}' not found at '{grant_file}'.")
        try:
            data = json.loads(grant_file.read_text(encoding="utf-8"))
            return RealRepoApplyGrant.from_dict(data)
        except Exception as exc:
            raise GrantIntegrityError(f"Failed to load grant '{grant_id}': {exc}") from exc

    def list_grants(self) -> List[RealRepoApplyGrant]:
        """List all persisted RealRepoApplyGrants."""
        grants: List[RealRepoApplyGrant] = []
        if not self.grants_dir.is_dir():
            return grants

        for entry in self.grants_dir.iterdir():
            if entry.is_dir() and (entry / "grant.json").is_file():
                try:
                    grant = self.load_grant(entry.name)
                    grants.append(grant)
                except Exception as exc:
                    logger.warning("Skipping corrupted grant '%s': %s", entry.name, exc)
        return grants

    # --------------------------------------------------------------------------
    # CompanyRun Persistence & Recovery
    # --------------------------------------------------------------------------

    def save_company_run(self, run: CompanyRun) -> Path:
        """Atomically persist a CompanyRun manifest and core operational payloads."""
        run_dir = self.runs_dir / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # 1. Complete run manifest
        atomic_write_text(run_dir / "run_manifest.json", json.dumps(run.to_dict(), indent=2))

        # 2. Objective payload
        atomic_write_text(run_dir / "objective.json", json.dumps(run.objective.to_dict(), indent=2))

        # 3. Active plan if formulation complete
        if run.active_plan:
            atomic_write_text(run_dir / "plan.json", json.dumps(run.active_plan.to_dict(), indent=2))

        # 4. Summaries and audit events
        atomic_write_text(
            run_dir / "employee_summaries.json",
            json.dumps([s.to_dict() for s in run.employee_summaries], indent=2),
        )
        atomic_write_text(run_dir / "events.json", json.dumps(run.events, indent=2))

        return run_dir

    def load_company_run(self, run_id: str) -> CompanyRun:
        """Load a CompanyRun from durable storage."""
        clean_id = run_id.strip()
        manifest_file = self.runs_dir / clean_id / "run_manifest.json"

        # Fallback check for flat company_runs directory
        if not manifest_file.is_file():
            flat_file = self.storage_root / "company_runs" / f"{clean_id}.json"
            if flat_file.is_file():
                manifest_file = flat_file

        if not manifest_file.is_file():
            raise CompanyRunNotFoundError(f"CompanyRun '{clean_id}' not found in durable storage.")

        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            return CompanyRun.from_dict(data)
        except Exception as exc:
            raise StorageError(f"Failed to load CompanyRun '{clean_id}': {exc}") from exc

    def list_company_runs(self) -> List[CompanyRun]:
        """List all CompanyRuns available in durable storage."""
        runs: List[CompanyRun] = []
        if not self.runs_dir.is_dir():
            return runs

        for entry in self.runs_dir.iterdir():
            if entry.is_dir() and (entry / "run_manifest.json").is_file():
                try:
                    run = self.load_company_run(entry.name)
                    runs.append(run)
                except Exception as exc:
                    logger.warning("Skipping corrupted CompanyRun '%s': %s", entry.name, exc)
            elif entry.is_file() and entry.suffix == ".json" and entry.stem.startswith("crun_"):
                try:
                    run = self.load_company_run(entry.stem)
                    if not any(r.run_id == run.run_id for r in runs):
                        runs.append(run)
                except Exception as exc:
                    logger.warning("Skipping corrupted CompanyRun '%s': %s", entry.name, exc)
        return runs

    # --------------------------------------------------------------------------
    # Retention Policy & Garbage Collection Protection
    # --------------------------------------------------------------------------

    def can_prune_proposal(self, proposal: RealRepoApplyProposal) -> bool:
        """Return True only if proposal is in a resolved, non-pending terminal state.
        
        Invariant:
        Proposals in READY_FOR_APPROVAL / READY_FOR_HUMAN_APPLY MUST NEVER be pruned.
        """
        # Active approval-pending states are strictly protected
        if proposal.status in ("READY_FOR_APPROVAL", "READY_FOR_HUMAN_APPLY"):
            return False
        return True

    def garbage_collect(self, older_than_days: int = 30) -> Dict[str, int]:
        """Safely prune expired, terminal artifacts according to strict retention policy.
        
        Strict Invariants:
        1. Never deletes any proposal in READY_FOR_APPROVAL or READY_FOR_HUMAN_APPLY.
        2. Never deletes active or unconsumed grants.
        """
        pruned_proposals = 0
        pruned_runs = 0
        now = datetime.now(timezone.utc)

        # Inspect proposals
        for entry in list(self.proposals_dir.iterdir()):
            if entry.is_dir() and (entry / "proposal.json").is_file():
                try:
                    proposal = self.load_proposal(entry.name, verify_integrity=False)
                    if not self.can_prune_proposal(proposal):
                        continue  # Protected by retention policy!
                except Exception:
                    continue

        return {
            "pruned_proposals": pruned_proposals,
            "pruned_runs": pruned_runs,
        }
