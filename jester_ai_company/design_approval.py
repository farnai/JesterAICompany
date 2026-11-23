"""Founder Design Approval Domain Model and Policy Enforcement (STEP 24.3).

Establishes the explicit, immutable DESIGN APPROVAL milestone:
- Approves a specific visual design concept for implementation before Developer Mutation.
- Strictly independent from CODE APPROVAL (RealRepoApplyGrant). Never interchangeable.
- Binds to exact artifact SHA-256 hashes and target project ID.
- Prevents UX agent recommendation self-approval.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, Optional

from .design_concept import (
    DesignConcept,
    PreviewProvenanceError,
    TamperedPrototypeError,
    compute_sha256_text,
    validate_preview_provenance,
)


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# -----------------------------------------------------------------------------
# Domain Exceptions
# -----------------------------------------------------------------------------

class DesignApprovalError(Exception):
    """Base exception for design approval errors."""
    pass


class DesignApprovalMissingError(DesignApprovalError):
    """Raised when Developer mutation is attempted without required Founder Design Approval."""
    pass


class DesignApprovalTamperedError(DesignApprovalError):
    """Raised when approved design concept artifacts or hashes do not match the approval record."""
    pass


class DesignApprovalProjectMismatchError(DesignApprovalError):
    """Raised when attempting to apply a design approval belonging to another project."""
    pass


class DesignApprovalSelfApprovalForbiddenError(DesignApprovalError):
    """Raised when a UX agent recommendation or non-human actor attempts to self-approve a concept."""
    pass


class DesignApprovalInterchangeabilityError(DesignApprovalError):
    """Raised when Design Approval and Code Approval (RealRepoApply) are conflated or interchanged."""
    pass


class DesignApprovalStatus(str, Enum):
    """Decision states for Founder Design Review."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


# -----------------------------------------------------------------------------
# Founder Design Approval Record Model
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class FounderDesignApproval:
    """Immutable record of an authorized Founder Design Approval decision."""

    approval_id: str
    project_id: str
    run_id: str
    task_id: str
    package_id: str
    concept_id: str
    founder_id: str
    html_prototype_sha256: str
    ux_spec_sha256: str
    desktop_preview_sha256: Optional[str] = None
    mobile_preview_sha256: Optional[str] = None
    notes: Optional[str] = None
    decided_at: str = field(default_factory=_utc_now_iso)
    status: str = DesignApprovalStatus.APPROVED.value
    approval_sha256: str = ""

    def __post_init__(self):
        if not self.approval_sha256:
            calc_hash = self._compute_fingerprint()
            object.__setattr__(self, "approval_sha256", calc_hash)

    def _compute_fingerprint(self) -> str:
        """Compute deterministic cryptographic fingerprint of approval record."""
        raw = (
            f"{self.approval_id}:{self.project_id}:{self.run_id}:{self.package_id}:"
            f"{self.concept_id}:{self.founder_id}:{self.html_prototype_sha256}:"
            f"{self.ux_spec_sha256}:{self.status}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def validate_against_concept(self, concept: DesignConcept, target_project_id: str) -> None:
        """Verify that this approval strictly matches the candidate concept and target project."""
        # 1. Check Project boundary (Principle 10)
        if self.project_id != target_project_id:
            raise DesignApprovalProjectMismatchError(
                f"Design approval '{self.approval_id}' belongs to project '{self.project_id}', "
                f"cannot be used for target project '{target_project_id}'."
            )

        # 2. Check Concept ID identity (Principle 7)
        if self.concept_id != concept.concept_id:
            raise DesignApprovalTamperedError(
                f"Approved concept ID '{self.concept_id}' does not match candidate concept ID '{concept.concept_id}'."
            )

        # 3. Check HTML prototype hash integrity (Principle 8)
        if self.html_prototype_sha256 != concept.html_sha256:
            raise DesignApprovalTamperedError(
                f"HTML prototype hash mismatch for concept '{concept.concept_id}': "
                f"expected '{self.html_prototype_sha256}', got '{concept.html_sha256}'. "
                "Design artifact was modified or substituted after Founder approval."
            )

        # 4. Check UX spec hash integrity (Principle 8)
        if self.ux_spec_sha256 != concept.spec_sha256:
            raise DesignApprovalTamperedError(
                f"UX specification hash mismatch for concept '{concept.concept_id}': "
                f"expected '{self.ux_spec_sha256}', got '{concept.spec_sha256}'. "
                "Design artifact was modified or substituted after Founder approval."
            )

        # 5. Check Preview Provenance and fidelity (Principle 8 & STEP 24.4.1)
        try:
            validate_preview_provenance(concept)
        except (PreviewProvenanceError, TamperedPrototypeError) as err:
            raise DesignApprovalTamperedError(f"Preview provenance invalid for concept '{concept.concept_id}': {err}") from err

        if self.desktop_preview_sha256 and concept.desktop_preview_sha256 and self.desktop_preview_sha256 != concept.desktop_preview_sha256:
            raise DesignApprovalTamperedError(
                f"Desktop preview hash mismatch for concept '{concept.concept_id}': "
                f"expected '{self.desktop_preview_sha256}', got '{concept.desktop_preview_sha256}'."
            )

        if self.mobile_preview_sha256 and concept.mobile_preview_sha256 and self.mobile_preview_sha256 != concept.mobile_preview_sha256:
            raise DesignApprovalTamperedError(
                f"Mobile preview hash mismatch for concept '{concept.concept_id}': "
                f"expected '{self.mobile_preview_sha256}', got '{concept.mobile_preview_sha256}'."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize approval to dictionary."""
        return {
            "approval_id": self.approval_id,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "package_id": self.package_id,
            "concept_id": self.concept_id,
            "founder_id": self.founder_id,
            "html_prototype_sha256": self.html_prototype_sha256,
            "ux_spec_sha256": self.ux_spec_sha256,
            "desktop_preview_sha256": self.desktop_preview_sha256,
            "mobile_preview_sha256": self.mobile_preview_sha256,
            "notes": self.notes,
            "decided_at": self.decided_at,
            "status": self.status,
            "approval_sha256": self.approval_sha256,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FounderDesignApproval":
        """Deserialize approval from dictionary."""
        return cls(
            approval_id=str(data["approval_id"]).strip(),
            project_id=str(data["project_id"]).strip(),
            run_id=str(data["run_id"]).strip(),
            task_id=str(data["task_id"]).strip(),
            package_id=str(data["package_id"]).strip(),
            concept_id=str(data["concept_id"]).strip(),
            founder_id=str(data.get("founder_id", "FOUNDER")).strip(),
            html_prototype_sha256=str(data["html_prototype_sha256"]).strip(),
            ux_spec_sha256=str(data["ux_spec_sha256"]).strip(),
            desktop_preview_sha256=data.get("desktop_preview_sha256"),
            mobile_preview_sha256=data.get("mobile_preview_sha256"),
            notes=data.get("notes"),
            decided_at=data.get("decided_at") or _utc_now_iso(),
            status=str(data.get("status", DesignApprovalStatus.APPROVED.value)).strip(),
            approval_sha256=str(data.get("approval_sha256", "")).strip(),
        )


def create_founder_design_approval(
    concept: DesignConcept,
    project_id: str,
    run_id: str,
    task_id: str,
    package_id: str,
    founder_id: str = "FOUNDER",
    approval_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> FounderDesignApproval:
    """Factory creating a cryptographically bound FounderDesignApproval."""
    if not founder_id or founder_id.strip().lower() in ("ux", "developer", "ceo", "product", "qa", "agent"):
        raise DesignApprovalSelfApprovalForbiddenError(
            f"Actor '{founder_id}' is not authorized to issue Founder Design Approval. "
            "A specialist agent recommendation cannot self-approve."
        )

    # Ensure concept hashes are computed
    concept.compute_hashes()

    appr_id = approval_id or f"appr_design_{concept.concept_id}_{run_id}"

    return FounderDesignApproval(
        approval_id=appr_id,
        project_id=project_id.strip(),
        run_id=run_id.strip(),
        task_id=task_id.strip(),
        package_id=package_id.strip(),
        concept_id=concept.concept_id.strip(),
        founder_id=founder_id.strip(),
        html_prototype_sha256=concept.html_sha256,
        ux_spec_sha256=concept.spec_sha256,
        desktop_preview_sha256=concept.desktop_preview_sha256,
        mobile_preview_sha256=concept.mobile_preview_sha256,
        notes=notes,
        status=DesignApprovalStatus.APPROVED.value,
    )


def validate_design_approval_for_developer_handoff(
    approval: Optional[Any],
    concept: Optional[DesignConcept],
    target_project_id: str,
) -> None:
    """Strict verification gate ensuring developer work only begins with valid Founder Design Approval.

    Enforces:
    1. Approval exists and is of type FounderDesignApproval (rejects Code Approval objects).
    2. Status is APPROVED.
    3. Project matches target_project_id (prevents cross-project inheritance).
    4. Concept artifact hashes match approved hashes (prevents tampered/substituted designs).
    """
    if approval is None:
        raise DesignApprovalMissingError(
            "Developer Mutation blocked: Visual design concepts require authorized Founder Design Approval before implementation."
        )

    # Check for interchangeability violations (Principle 1 & 9)
    approval_type = type(approval).__name__
    if approval_type in ("RealRepoApplyProposal", "RealRepoApplyGrant", "ExecutionGrant"):
        raise DesignApprovalInterchangeabilityError(
            f"Received '{approval_type}' where FounderDesignApproval was expected. "
            "Code Approval and Design Approval are strictly separate and never interchangeable."
        )

    if not isinstance(approval, FounderDesignApproval):
        # Try deserialization if it is a dict
        if isinstance(approval, dict):
            try:
                approval = FounderDesignApproval.from_dict(approval)
            except Exception as e:
                raise DesignApprovalMissingError(f"Invalid design approval structure: {e}")
        else:
            raise DesignApprovalMissingError(f"Expected FounderDesignApproval, got '{type(approval).__name__}'.")

    if approval.status != DesignApprovalStatus.APPROVED.value:
        raise DesignApprovalMissingError(
            f"Design approval is in status '{approval.status}', expected '{DesignApprovalStatus.APPROVED.value}'."
        )

    if concept is not None:
        approval.validate_against_concept(concept, target_project_id=target_project_id)
    elif approval.project_id != target_project_id:
        raise DesignApprovalProjectMismatchError(
            f"Design approval '{approval.approval_id}' belongs to project '{approval.project_id}', "
            f"cannot be used for target project '{target_project_id}'."
        )
