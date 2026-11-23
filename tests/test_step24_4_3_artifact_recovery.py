"""Focused Deterministic Test Suite for STEP 24.4.3: Controlled Design Artifact Recovery.

Verifies:
1. Original artifact preservation (snapshots, HTML prototypes, SVG fallbacks).
2. Unique recovered artifact IDs (no collisions, no stubs like proto_concept_).
3. Correct recovery lineage (original run ID, task run ID, recovery event).
4. No historical artifact impersonation (explicit provenance for derived PNG renders).
5. Coherent official persistence reads (all read paths return identical state).
6. Detection of mismatched hashes (tampered HTML or PNG fails closed).
7. Founder approval bound to exact recovered package (cryptographic binding).
8. Developer blocked before genuine Founder approval (gating preserved).
9. No cross-project approval leakage (strict project isolation).
10. Canonical Jester unchanged (external repository 100% clean).
"""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import pytest

from jester_ai_company.core import ArtifactType
from jester_ai_company.design_approval import (
    DesignApprovalMissingError,
    DesignApprovalProjectMismatchError,
    DesignApprovalTamperedError,
    FounderDesignApproval,
    create_founder_design_approval,
    validate_design_approval_for_developer_handoff,
)
from jester_ai_company.design_concept import DesignConcept, TamperedPrototypeError
from jester_ai_company.design_recovery import (
    DesignRecoveryCollisionError,
    DesignRecoveryIntegrityError,
    DesignRecoveryPackage,
    build_crun_29fcdd4a_recovery_package,
    validate_design_recovery_package,
)
from jester_ai_company.durable_storage import DurableRunStorage
from jester_ai_company.orchestrator import CompanyRunState, WorkItemState
from jester_ai_company.service import CompanyService

COMPANY_ROOT = Path(r"c:\Users\fiord\.gemini\antigravity-ide\scratch\JesterAICompany").resolve()
REAL_JESTER_PATH = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester").resolve()
EXPECTED_JESTER_HEAD = "cb7135cafa7386dc30fdb099fb52ab109fcbaee0"


@pytest.fixture
def service():
    srv = CompanyService(output_dir=str(COMPANY_ROOT / ".runs"), repo_root=COMPANY_ROOT)
    srv.create_project(project_id="prj_jester", name="Jester")
    return srv


@pytest.fixture
def recovery_package():
    return build_crun_29fcdd4a_recovery_package(COMPANY_ROOT)


def test_01_original_artifact_preservation():
    """1. Original artifacts, snapshots, and historical fallbacks are preserved."""
    snapshot_dir = COMPANY_ROOT / ".runs" / "snapshots" / "step24_4_3_pre_recovery_snapshot_crun_29fcdd4a"
    assert snapshot_dir.is_dir(), f"Snapshot directory missing at {snapshot_dir}"

    manifest_file = snapshot_dir / "snapshot_manifest.json"
    assert manifest_file.is_file(), "Snapshot manifest missing."
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest["run_id"] == "crun_29fcdd4a"

    # Verify that all preserved files in snapshot match their recorded hashes
    for fname, meta in manifest["files"].items():
        snap_path = COMPANY_ROOT / meta["snapshot_path"]
        assert snap_path.is_file(), f"Preserved file {fname} not found at {snap_path}"
        actual_sha = hashlib.sha256(snap_path.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"Hash mismatch in snapshot for {fname}"

    # Verify original HTML prototypes on disk
    artifacts_dir = COMPANY_ROOT / ".runs" / "task_crun_29fcdd4a_wi_ux_visual_concepts" / "run_task_crun_29fcdd4a_wi_ux_visual_concepts_01_192435" / "artifacts"
    expected_html_hashes = {
        "prototype_concept_editorial_narrative_split.html": "2e16555dc98e33981a19f2430fe79e3f34e40b5dee9513367753cd96c053c5f0",
        "prototype_concept_conversational_gateway.html": "c72d014dc4e05f4db7d3afde2e892920c83dbf7f6b45cc67661512b967331256",
        "prototype_concept_minimalist_precision.html": "eee381b74a89b84b11edea6f033c2267c1fdf372747267f0889e1675f245db4b",
    }
    for hname, hhash in expected_html_hashes.items():
        hfile = artifacts_dir / hname
        assert hfile.is_file(), f"HTML prototype {hname} missing on disk"
        assert hashlib.sha256(hfile.read_bytes()).hexdigest() == hhash, f"Hash mismatch for {hname}"


def test_02_unique_recovered_artifact_ids(service, recovery_package):
    """2. Every recovered artifact reference has a globally unique, non-colliding ID."""
    run = service.get_company_run("crun_29fcdd4a")
    ux_summaries = [s for s in run.employee_summaries if s.role == "ux"]
    assert len(ux_summaries) >= 1

    artifact_refs = ux_summaries[0].artifact_refs
    assert len(artifact_refs) == 10

    seen_ids = set()
    for ref in artifact_refs:
        aid = ref.get("artifact_id")
        assert aid, f"Artifact {ref.get('name')} has empty ID"
        assert aid not in seen_ids, f"Collision detected for artifact ID '{aid}'"
        seen_ids.add(aid)

        # Invariant: Reject prefix collision stubs
        assert aid not in ("proto_concept_", "desk_concept_", "mob_concept_"), f"Colliding stub '{aid}' found"


def test_03_correct_recovery_lineage(service, recovery_package):
    """3. Recovery package explicitly maintains lineage to original run and task run."""
    assert recovery_package.original_run_id == "crun_29fcdd4a"
    assert recovery_package.original_task_id == "task_crun_29fcdd4a_wi_ux_visual_concepts"
    assert recovery_package.original_task_run_id == "run_task_crun_29fcdd4a_wi_ux_visual_concepts_01_192435"

    run = service.get_company_run("crun_29fcdd4a")
    assert run.design_proposal_package_id == recovery_package.package_id

    # Check recovery event in audit trail
    rec_events = [e for e in run.events if (e.get("event_type") if isinstance(e, dict) else e.event_type) == "DESIGN_ARTIFACTS_RECOVERED"]
    assert len(rec_events) >= 1
    event_details = rec_events[-1].get("details") if isinstance(rec_events[-1], dict) else rec_events[-1].details
    assert event_details["recovery_package_id"] == recovery_package.package_id
    assert event_details["original_run_id"] == "crun_29fcdd4a"


def test_04_no_historical_artifact_impersonation(recovery_package):
    """4. Provenance distinguishes original agent deliverables from later derived browser renders."""
    for ref in recovery_package.artifact_refs:
        if ref.name.endswith(".html"):
            assert ref.is_original_specialist_output is True
            assert "Original autonomous UX specialist" in ref.provenance_note
        elif ref.name.endswith(".png"):
            assert ref.is_original_specialist_output is False
            assert "Derived browser screenshot" in ref.provenance_note
            assert "Headless Chrome" in ref.provenance_note


def test_05_coherent_official_persistence_reads(service, recovery_package):
    """5. All official persistence read paths return a coherent, synchronized state."""
    # 1. CompanyService read
    run_service = service.get_company_run("crun_29fcdd4a")

    # 2. DurableRunStorage direct read
    durable_storage = DurableRunStorage(COMPANY_ROOT / ".runs")
    run_durable = durable_storage.load_company_run("crun_29fcdd4a")

    # 3. Direct manifest file read
    manifest_f = COMPANY_ROOT / ".runs" / "company_runs" / "crun_29fcdd4a" / "run_manifest.json"
    manifest_data = json.loads(manifest_f.read_text(encoding="utf-8"))

    # 4. Flat file read
    flat_f = COMPANY_ROOT / ".runs" / "company_runs" / "crun_29fcdd4a.json"
    flat_data = json.loads(flat_f.read_text(encoding="utf-8"))

    assert run_service.run_id == run_durable.run_id == manifest_data["run_id"] == flat_data["run_id"] == "crun_29fcdd4a"
    assert run_service.state == run_durable.state == manifest_data["state"] == flat_data["state"] == CompanyRunState.WAITING_FOR_HUMAN.value
    assert run_service.design_proposal_package_id == run_durable.design_proposal_package_id == manifest_data["design_proposal_package_id"] == flat_data["design_proposal_package_id"] == recovery_package.package_id

    # Compare UX artifact refs between manifest and flat
    m_refs = [s for s in manifest_data["employee_summaries"] if s["role"] == "ux"][0]["artifact_refs"]
    f_refs = [s for s in flat_data["employee_summaries"] if s["role"] == "ux"][0]["artifact_refs"]
    assert len(m_refs) == len(f_refs) == 10
    assert [r["artifact_id"] for r in m_refs] == [r["artifact_id"] for r in f_refs]


def test_06_detection_of_mismatched_hashes(recovery_package):
    """6. Package and provenance validation fail closed upon any hash mismatch or tampering."""
    artifacts_dir = COMPANY_ROOT / ".runs" / "task_crun_29fcdd4a_wi_ux_visual_concepts" / "run_task_crun_29fcdd4a_wi_ux_visual_concepts_01_192435" / "artifacts"

    # Baseline package must pass
    validate_design_recovery_package(recovery_package, base_artifacts_dir=artifacts_dir)

    # Tamper with HTML hash
    bad_pkg_1 = copy.deepcopy(recovery_package)
    bad_pkg_1.concepts[0].html_sha256 = "f" * 64
    with pytest.raises((DesignRecoveryIntegrityError, TamperedPrototypeError)):
        validate_design_recovery_package(bad_pkg_1, base_artifacts_dir=artifacts_dir)

    # Tamper with Desktop PNG hash
    bad_pkg_2 = copy.deepcopy(recovery_package)
    bad_pkg_2.concepts[0].desktop_preview_sha256 = "0" * 64
    with pytest.raises((DesignRecoveryIntegrityError, TamperedPrototypeError)):
        validate_design_recovery_package(bad_pkg_2, base_artifacts_dir=artifacts_dir)

    # Tamper with artifact ref duplicate ID
    bad_pkg_3 = copy.deepcopy(recovery_package)
    bad_pkg_3.artifact_refs[1].artifact_id = bad_pkg_3.artifact_refs[0].artifact_id
    with pytest.raises(DesignRecoveryCollisionError):
        validate_design_recovery_package(bad_pkg_3, base_artifacts_dir=artifacts_dir)


def test_07_founder_approval_bound_to_exact_recovered_package(recovery_package):
    """7. Founder Design Approval cryptographically binds to the exact concept from the recovery package."""
    rec_concept = recovery_package.get_concept(recovery_package.recommended_concept_id)
    assert rec_concept is not None

    approval = create_founder_design_approval(
        concept=rec_concept,
        project_id=recovery_package.project_id,
        run_id=recovery_package.original_run_id,
        task_id=recovery_package.original_task_id,
        package_id=recovery_package.package_id,
        founder_id="FOUNDER",
        notes="Approved from valid recovery package.",
    )

    # Valid approval passes handoff gate
    validate_design_approval_for_developer_handoff(
        approval=approval,
        concept=rec_concept,
        target_project_id="prj_jester",
    )

    # Tampered concept fails
    tampered_c = copy.deepcopy(rec_concept)
    tampered_c.desktop_preview_sha256 = "e" * 64
    with pytest.raises(DesignApprovalTamperedError):
        validate_design_approval_for_developer_handoff(
            approval=approval,
            concept=tampered_c,
            target_project_id="prj_jester",
        )


def test_08_developer_blocked_before_genuine_founder_approval(service):
    """8. Developer macro execution remains strictly blocked before genuine Founder Design Approval."""
    run = service.get_company_run("crun_29fcdd4a")
    assert run.state == CompanyRunState.WAITING_FOR_HUMAN.value
    assert run.work_item_states["wi_developer_implementation_planning"] == WorkItemState.PENDING.value
    assert run.founder_design_approval_id is None
    assert run.founder_design_approval is None

    # Developer handoff gate rejects None approval
    with pytest.raises(DesignApprovalMissingError):
        validate_design_approval_for_developer_handoff(
            approval=None,
            concept=None,
            target_project_id="prj_jester",
        )


def test_09_no_cross_project_approval_leakage(recovery_package):
    """9. Design approval issued for prj_jester cannot be applied to another project."""
    rec_concept = recovery_package.get_concept(recovery_package.recommended_concept_id)
    approval = create_founder_design_approval(
        concept=rec_concept,
        project_id="prj_jester",
        run_id=recovery_package.original_run_id,
        task_id=recovery_package.original_task_id,
        package_id=recovery_package.package_id,
    )

    with pytest.raises(DesignApprovalProjectMismatchError):
        validate_design_approval_for_developer_handoff(
            approval=approval,
            concept=rec_concept,
            target_project_id="prj_other_enterprise",
        )


def test_10_canonical_jester_unchanged():
    """10. Canonical external Jester repository remains 100% clean and unmutated."""
    assert REAL_JESTER_PATH.is_dir()

    # Check git status
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(REAL_JESTER_PATH),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == "", f"Canonical Jester working tree is dirty:\n{proc.stdout}"

    # Check HEAD commit
    proc_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REAL_JESTER_PATH),
        capture_output=True,
        text=True,
    )
    assert proc_head.returncode == 0
    assert proc_head.stdout.strip() == EXPECTED_JESTER_HEAD, f"HEAD commit mismatch: {proc_head.stdout.strip()}"
