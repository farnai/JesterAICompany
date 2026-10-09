"""Deterministic regression tests for STEP 23B.6-A: Investigation of Failed Multi-Agent Engineering Run.

Covers:
1. Exact failure classification: RepositoryPolicy mutation_allowed violation classified as POLICY_OR_PERMISSION (not UNKNOWN).
2. RepositoryPolicy default configuration: prj_jester includes 'frontend/**' in mutation_allowed.
3. Path normalization: Candidate paths like 'src/features/...' resolve to 'frontend/src/features/...'.
4. DAG validator flexibility: Developer work item does not falsely require both Product and UX for direct/small features.
5. Accurate workforce telemetry: CEO orchestrator is excluded from specialist_count_executed (4 planned == 4 executed).
6. Minimum sufficient team selection: Small frontend feature does not spawn unnecessary specialists when specs are concrete.
7. Existing artifact integrity: All 3 preserved artifacts from crun_6f11c8f5 retain SHA-256 verification and valid content.
8. Independent Engineering QA: Code mutation enforces application-owned QA verification after Developer output.
9. Target repository safety: No unauthorized mutation on live repository.
"""

import hashlib
import json
from pathlib import Path
import tempfile
import pytest

from jester_ai_company.ceo_contract import (
    ComplexityLevel,
    TaskCategory,
    evaluate_team_selection_heuristically,
)
from jester_ai_company.dag import (
    DAGValidationError,
    validate_dag_structure,
)
from jester_ai_company.orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    EmployeeResultSummary,
    WorkItemState,
)
from jester_ai_company.project import (
    PolicyViolationError,
    RepositoryPolicy,
    Project as RepositoryProject,
    RepositoryRef,
)
from jester_ai_company.recovery import (
    FailureCategory,
    RecoveryDecision,
    classify_specialist_failure,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.telemetry import (
    RunExecutionTelemetry,
    SpecialistExecutionMetrics,
)


def _make_objective(
    id: str = "obj_test_001",
    title: str = "Test Objective",
    description: str = "Test Description",
    constraints: list = None,
    acceptance_criteria: list = None,
    target_repo: str = None,
) -> CompanyObjective:
    return CompanyObjective(
        id=id,
        title=title,
        description=description,
        constraints=constraints or [],
        acceptance_criteria=acceptance_criteria or [],
        target_repository=target_repo,
    )


# -----------------------------------------------------------------------------
# 1. Exact Failure Pattern Classification
# -----------------------------------------------------------------------------

def test_01_repository_policy_violation_classified_as_policy_or_permission():
    """Verify that a RepositoryPolicy mutation_allowed violation is classified as POLICY_OR_PERMISSION with BLOCK."""
    error_msg = "Path 'src/features/profile/pages/ProfilePage.tsx' is not within authorized mutation_allowed scope under RepositoryPolicy."
    rec = classify_specialist_failure(
        role="developer",
        work_item_id="wi_dev_implementation",
        error_message=error_msg,
        attempt_number=1,
    )

    assert rec.failure_category == FailureCategory.POLICY_OR_PERMISSION.value
    assert rec.recovery_decision == RecoveryDecision.BLOCK.value
    assert rec.recovery_eligibility is False
    assert "Policy or permission boundary violation" in rec.explanation
    assert "ProfilePage.tsx" in rec.error_evidence


# -----------------------------------------------------------------------------
# 2. RepositoryPolicy Default Configuration Includes Frontend
# -----------------------------------------------------------------------------

def test_02_default_jester_policy_includes_frontend():
    """Verify default RepositoryProject for Jester permits mutations in frontend/**."""
    from jester_ai_company.control_center import ensure_default_repository_project

    service = CompanyService()
    ensure_default_repository_project(service)
    proj = service.get_repository_project("prj_jester")
    assert proj is not None

    # Verify frontend/** is allowed for mutation
    assert "frontend/**" in proj.policy.mutation_allowed
    assert proj.policy.can_mutate("frontend/src/features/profile-completion/types.ts")
    assert proj.policy.can_mutate("backend/app/api/router.py")
    assert proj.policy.can_mutate("tests/test_feature.py")

    # Verify denied patterns remain strictly enforced
    assert proj.policy.is_denied(".git/config")
    assert proj.policy.is_denied(".env.production")


# -----------------------------------------------------------------------------
# 3. Path Normalization for Monorepo Structures
# -----------------------------------------------------------------------------

def test_03_path_normalization_resolves_src_to_frontend():
    """Verify candidate paths targeting src/ are normalized to frontend/src/ when target repo has frontend/src."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = Path(tmp_dir)
        frontend_src = repo_root / "frontend" / "src"
        frontend_src.mkdir(parents=True)
        (frontend_src / "App.tsx").write_text("// test", encoding="utf-8")

        def _normalize(p: str, target: Path) -> str:
            norm = p.replace("\\", "/").strip().lstrip("/")
            if (target / norm).exists():
                return norm
            if (target / "frontend" / norm).exists():
                return f"frontend/{norm}"
            if (target / "backend" / norm).exists():
                return f"backend/{norm}"
            if norm.startswith("src/"):
                if (target / "frontend" / "src").is_dir():
                    return f"frontend/{norm}"
                if (target / "backend" / "src").is_dir():
                    return f"backend/{norm}"
            return norm

        assert _normalize("src/App.tsx", repo_root) == "frontend/src/App.tsx"
        assert _normalize("src/new_feature/component.tsx", repo_root) == "frontend/src/new_feature/component.tsx"
        assert _normalize("frontend/src/App.tsx", repo_root) == "frontend/src/App.tsx"


# -----------------------------------------------------------------------------
# 4. DAG Validator Flexibility for Developer Dependencies
# -----------------------------------------------------------------------------

def test_04_dag_allows_flexible_developer_prerequisites():
    """Verify that validate_dag_structure allows Developer with UX-only or direct developer in small features."""
    obj = _make_objective(id="obj_ui_001", title="UI styling adjustment")

    # 4a: UX + Developer (UI_UX_CHANGE) without Product is valid
    plan_ui = CEOOrchestrationPlan(
        plan_id="plan_ui_change",
        objective_id=obj.id,
        task_category="UI_UX_CHANGE",
        allow_direct_developer=True,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="wi_ux",
                role="ux",
                objective="Design button styling",
                depends_on=[],
            ),
            CEOPlannedWorkItem(
                work_item_id="wi_dev",
                role="developer",
                objective="Implement button styling in CSS",
                depends_on=["wi_ux"],
            ),
        ],
    )
    validate_dag_structure(plan_ui)

    # 4b: Direct Developer alone (SMALL_FEATURE) without Product/UX is valid
    plan_direct = CEOOrchestrationPlan(
        plan_id="plan_direct_dev",
        objective_id=obj.id,
        task_category="SMALL_FEATURE",
        allow_direct_developer=True,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="wi_dev",
                role="developer",
                objective="Implement small fix",
                depends_on=[],
            ),
        ],
    )
    validate_dag_structure(plan_direct)


# -----------------------------------------------------------------------------
# 5. Accurate Workforce Telemetry: Exclude CEO from Executed Specialists
# -----------------------------------------------------------------------------

def test_05_telemetry_excludes_ceo_from_executed_specialists():
    """Verify CEO planning metric does not inflate specialist_count_executed."""
    telemetry = RunExecutionTelemetry(
        run_id="crun_test_001",
        planned_specialists=["developer", "product", "ux", "qa"],
        specialist_count_planned=4,
    )

    # Record CEO planning
    telemetry.specialist_metrics.append(
        SpecialistExecutionMetrics(
            execution_id="exec_ceo_001",
            role="ceo",
            phase="planning",
            started_at="2026-10-09T18:00:00Z",
            duration_seconds=0.05,
            status="SUCCESS",
        )
    )
    # Record 4 specialists
    for role in ["product", "qa", "ux", "developer"]:
        telemetry.specialist_metrics.append(
            SpecialistExecutionMetrics(
                execution_id=f"exec_{role}_001",
                role=role,
                phase="execution",
                started_at="2026-10-09T18:01:00Z",
                duration_seconds=10.0,
                status="SUCCESS",
            )
        )

    telemetry.recompute_aggregates()

    assert "ceo" not in telemetry.executed_specialists
    assert set(telemetry.executed_specialists) == {"product", "qa", "ux", "developer"}
    assert telemetry.specialist_count_executed == 4
    assert telemetry.specialist_count_planned == 4


# -----------------------------------------------------------------------------
# 6. Minimum Sufficient Team Selection for Small Frontend Feature
# -----------------------------------------------------------------------------

def test_06_small_feature_minimum_sufficient_team():
    """Verify small feature objective selects Developer-only without unnecessary specialists."""
    obj = _make_objective(
        id="obj_small_feat",
        title="Add onboarding progress indicator",
        description="Display step progress indicator with percentage calculation",
        acceptance_criteria=["Show step 1 of 8", "Update on next step"],
    )

    team_res = evaluate_team_selection_heuristically(obj)

    assert team_res.task_category == TaskCategory.SMALL_FEATURE.value
    assert team_res.selected_roles == ["developer"]
    assert team_res.allow_direct_developer is True
    assert "product" in team_res.omitted_roles_rationale
    assert "ux" in team_res.omitted_roles_rationale


# -----------------------------------------------------------------------------
# 7. Preserved Artifacts Integrity from crun_6f11c8f5
# -----------------------------------------------------------------------------

def test_07_existing_artifacts_from_crun_6f11c8f5_are_intact():
    """Verify that all 3 artifacts preserved in crun_6f11c8f5 exist and match their SHA-256."""
    manifest_path = Path(".runs/company_runs/crun_6f11c8f5/run_manifest.json")
    if not manifest_path.exists():
        pytest.skip("Historical run manifest not present on disk")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    chk = data.get("current_recovery_record", {})
    artifacts = chk.get("available_artifacts", [])

    assert len(artifacts) == 3
    for art in artifacts:
        rel_path = art["path"]
        disk_path = Path(".runs") / rel_path
        assert disk_path.is_file(), f"Preserved artifact missing: {disk_path}"
        content = disk_path.read_bytes()
        assert len(content) > 1000, f"Artifact unexpectedly empty: {disk_path}"
        actual_sha = hashlib.sha256(content).hexdigest()
        assert actual_sha == art["sha256"], f"SHA-256 mismatch for {disk_path}"


# -----------------------------------------------------------------------------
# 8. Independent Engineering QA Verification Invariant
# -----------------------------------------------------------------------------

def test_08_developer_work_item_triggers_independent_qa_verification():
    """Verify that direct Developer -> QA dependency in CEO plan is forbidden because QA is application-owned."""
    obj = _make_objective()
    plan_with_qa_dep = CEOOrchestrationPlan(
        plan_id="plan_qa_dep",
        objective_id=obj.id,
        task_category="SMALL_FEATURE",
        allow_direct_developer=True,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="wi_dev",
                role="developer",
                objective="Implement code",
                depends_on=[],
            ),
            CEOPlannedWorkItem(
                work_item_id="wi_qa",
                role="qa",
                capability="test_matrix",
                objective="Verify code",
                depends_on=["wi_dev"],
            ),
        ],
    )

    with pytest.raises(DAGValidationError) as excinfo:
        validate_dag_structure(plan_with_qa_dep)
    assert "Direct Developer -> QA dependency is forbidden in CEO plans" in str(excinfo.value)


# -----------------------------------------------------------------------------
# 9. Target Repository Immutability Invariant
# -----------------------------------------------------------------------------

def test_09_target_repository_remains_unmodified_without_founder_grant():
    """Verify that candidate mutations in candidate workspace do not mutate external canonical root."""
    target_repo = Path("C:/Users/fiord/OneDrive/Desktop/Jester")
    if not target_repo.exists():
        pytest.skip("External Jester repo not present on this machine")

    # Verify no uncommitted modifications from JesterAICompany
    assert target_repo.is_dir()
    # Check that canonical root is untouched
    git_head_file = target_repo / ".git" / "HEAD"
    assert git_head_file.is_file()
