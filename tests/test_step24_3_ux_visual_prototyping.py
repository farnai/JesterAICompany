"""Deterministic Acceptance Tests for STEP 24.3: UX Visual Prototyping & Founder Design Approval.

Validates all 12 target architectural criteria deterministically using synthetic fixtures
and zero real LLM invocations:
1. Product -> UX concept-only workflow can complete without Developer Mutation.
2. UX can persist visual prototype artifacts with validated hashes.
3. Browser previews correspond to the actual generated prototype source.
4. Three different concepts can be represented independently.
5. Developer Mutation is blocked before authorized Founder concept selection.
6. A recommendation from UX cannot approve itself.
7. Approved concept identity and artifact hashes are preserved.
8. A modified or substituted artifact invalidates the handoff.
9. Concept approval does not automatically approve code application.
10. Another project cannot inherit Jester-specific assets or approvals.
11. The existing nonvisual engineering workflow remains compatible.
12. Frontend repair verification does not default to unrelated backend tests.
"""

import hashlib
import json
from pathlib import Path
import pytest
import tempfile
import uuid

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    Company,
    Employee,
    Project,
    Task,
    TaskRun,
    TaskStatus,
    RunStatus,
    create_default_company,
)
from jester_ai_company.orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    WorkItemState,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.design_concept import (
    DesignConcept,
    DesignProposalPackage,
    compute_sha256_text,
    validate_untrusted_prototype_html,
    sanitize_prototype_html,
)
from jester_ai_company.prototype_renderer import (
    render_prototype_previews,
)
from jester_ai_company.design_approval import (
    FounderDesignApproval,
    DesignApprovalStatus,
    create_founder_design_approval,
    validate_design_approval_for_developer_handoff,
    DesignApprovalError,
    DesignApprovalMissingError,
    DesignApprovalTamperedError,
    DesignApprovalProjectMismatchError,
    DesignApprovalSelfApprovalForbiddenError,
    DesignApprovalInterchangeabilityError,
)
from jester_ai_company.ux_result import UXTaskResult
from jester_ai_company.qa_result import (
    QAVerificationCategory,
    QACategoryStatus,
    QACategoryVerificationRecord,
    QAInspectionResult,
    parse_and_validate_qa_result,
)
from jester_ai_company.materializer import materialize_specialist_artifact
from jester_ai_company.execution_grant import ExecutionGrant, VerificationAction
from jester_ai_company.repair import (
    DeveloperRepairPlan,
    ProposedFile,
    derive_repair_execution_grant,
)
from jester_ai_company.real_repo_apply import (
    RealRepoApplyGrant,
    RealRepoApplyProposal,
)
from jester_ai_company.engineering_pipeline import EngineeringPipelineAdapter


# -----------------------------------------------------------------------------
# Synthetic HTML Prototype Fixtures (3 Meaningfully Different Concepts)
# -----------------------------------------------------------------------------

CONCEPT_A_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>JESTER - Celestial Zodiac Wheel Registration</title>
    <style>
        :root {
            --bg-color: #0d0f18;
            --primary-purple: #7928ca;
            --gold-accent: #ff0080;
            --text-main: #f0f4f8;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            font-family: 'Inter', sans-serif;
            margin: 0;
            display: flex;
            min-height: 100vh;
        }
        .hero-wheel {
            width: 45%;
            background: radial-gradient(circle, #2d1b4e 0%, #0d0f18 70%);
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .registration-panel {
            width: 55%;
            padding: 48px;
            box-sizing: border-box;
        }
        h1 {
            color: #ffffff;
            font-size: 32px;
            margin-bottom: 8px;
        }
        .subtitle {
            color: #a0aec0;
            margin-bottom: 32px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        input {
            width: 100%;
            padding: 12px 16px;
            background: #1a1e2e;
            border: 1px solid #2d3748;
            border-radius: 8px;
            color: #ffffff;
        }
        .btn-register {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, var(--primary-purple), var(--gold-accent));
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="hero-wheel">
        <h2>Interactive Zodiac Wheel</h2>
    </div>
    <div class="registration-panel">
        <h1>Begin Your Cosmic Journey</h1>
        <p class="subtitle">Discover natal astrology and synastry compatibility</p>
        <form>
            <div class="form-group"><input type="email" placeholder="Your celestial email" /></div>
            <div class="form-group"><input type="text" placeholder="Birth date (YYYY-MM-DD)" /></div>
            <div class="form-group"><input type="text" placeholder="Birth time & location" /></div>
            <button type="button" class="btn-register">Chart My Sky</button>
        </form>
    </div>
</body>
</html>"""

CONCEPT_B_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>JESTER - Multi-Step Synastry Onboarding Stepper</title>
    <style>
        :root {
            --bg-color: #090a10;
            --accent-cyan: #00f2fe;
            --accent-blue: #4facfe;
            --text-light: #e6edf3;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-light);
            font-family: 'Outfit', sans-serif;
            margin: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .stepper-container {
            max-width: 600px;
            width: 90%;
            background: rgba(22, 27, 34, 0.85);
            border: 1px solid #30363d;
            border-radius: 16px;
            padding: 40px;
            backdrop-filter: blur(12px);
        }
        h1 {
            font-size: 28px;
            text-align: center;
            background: linear-gradient(90deg, var(--accent-cyan), var(--accent-blue));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .step-indicator {
            display: flex;
            justify-content: space-between;
            margin: 24px 0;
        }
        .step {
            font-size: 14px;
            color: #8b949e;
        }
        .step.active {
            color: var(--accent-cyan);
            font-weight: bold;
        }
        .step-content {
            margin-bottom: 28px;
        }
        .btn-next {
            width: 100%;
            padding: 14px;
            background: var(--accent-cyan);
            color: #090a10;
            border: none;
            border-radius: 8px;
            font-weight: 700;
        }
    </style>
</head>
<body>
    <div class="stepper-container">
        <h1>Three Keys to Your Synastry</h1>
        <div class="step-indicator">
            <span class="step active">1. Identity</span>
            <span class="step">2. Natal Sky</span>
            <span class="step">3. Preferences</span>
        </div>
        <div class="step-content">
            <p>Tell us who is entering the celestial ballroom.</p>
            <input type="text" placeholder="Preferred Username" />
        </div>
        <button type="button" class="btn-next">Continue to Natal Sky</button>
    </div>
</body>
</html>"""

CONCEPT_C_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>JESTER - Minimalist Astral Card Flow</title>
    <style>
        :root {
            --bg-color: #050508;
            --card-bg: #11121a;
            --gold: #d4af37;
            --text-color: #f7f7f9;
        }
        body {
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: 'Cinzel', serif;
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .astral-card {
            width: 420px;
            background: var(--card-bg);
            border: 1px solid var(--gold);
            border-radius: 12px;
            padding: 36px;
            box-shadow: 0 0 30px rgba(212, 175, 55, 0.15);
            text-align: center;
        }
        h1 {
            color: var(--gold);
            letter-spacing: 2px;
            font-size: 24px;
        }
        p {
            font-size: 14px;
            color: #a3a3b2;
            line-height: 1.6;
        }
        .btn-astral {
            margin-top: 24px;
            width: 100%;
            padding: 12px;
            background: transparent;
            border: 1px solid var(--gold);
            color: var(--gold);
            font-family: inherit;
            letter-spacing: 1px;
            cursor: pointer;
        }
        .btn-astral:hover {
            background: var(--gold);
            color: var(--bg-color);
        }
    </style>
</head>
<body>
    <div class="astral-card">
        <h1>THE JESTER SANCTUARY</h1>
        <p>A quiet portal for refined astrological synchronization.</p>
        <input type="email" placeholder="Sacred Email" />
        <button type="button" class="btn-astral">Enter Sanctuary</button>
    </div>
</body>
</html>"""


# =============================================================================
# Deterministic Acceptance Test Cases (1 to 12)
# =============================================================================

def test_01_product_ux_concept_only_workflow_completes_without_developer_mutation():
    """1. A Product -> UX concept-only workflow can complete without Developer Mutation."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        service = CompanyService(output_dir=str(tmp_path / "runs"), repo_root=tmp_path)
        
        # Create a concept-only CompanyRun
        obj = CompanyObjective(
            id="obj_concept_pilot",
            title="Design 3 Registration Concepts",
            description="Explore visual registration concepts without implementation mutation",
            constraints=["concept_only=true"],
            acceptance_criteria=["Deliver reviewable visual concepts"],
            target_repository=str(tmp_path),
            project_id="proj_pilot",
        )
        run = service.create_company_run(obj)

        # Plan with Product and UX only (no Developer macro work item)
        p_item = CEOPlannedWorkItem(
            work_item_id="item_prod",
            role="product",
            objective="Define requirements",
            expected_outputs=["product_report.md"],
            depends_on=[],
        )
        ux_item = CEOPlannedWorkItem(
            work_item_id="item_ux",
            role="ux",
            objective="Design visual prototypes",
            expected_outputs=["ux_report.md", "prototype_c1.html"],
            depends_on=["item_prod"],
        )
        plan = CEOOrchestrationPlan(
            plan_id="plan_concept_only",
            objective_id=obj.id,
            work_items=[p_item, ux_item],
        )
        run.set_plan(plan)
        run.transition_to(CompanyRunState.PLANNING)
        run.transition_to(CompanyRunState.PLAN_READY)
        run.transition_to(CompanyRunState.RUNNING)
        service.save_company_run(run)

        # Confirm it is not a code workflow
        assert run.is_code_workflow is False

        # Simulate Product completion
        p_item.state = WorkItemState.COMPLETED.value
        run.work_item_states[p_item.work_item_id] = WorkItemState.COMPLETED.value

        # Simulate UX completion
        ux_item.state = WorkItemState.COMPLETED.value
        run.work_item_states[ux_item.work_item_id] = WorkItemState.COMPLETED.value

        # Complete non-code workflow
        run.transition_to(CompanyRunState.COMPLETED)
        service.save_company_run(run)

        # Invariants: 0 Developer mutations, 0 execution grants, 0 real repo proposals
        assert run.state == CompanyRunState.COMPLETED.value
        assert run.code_patch_artifact_id is None
        assert run.real_repo_apply_proposal_id is None
        assert run.real_repo_apply_grant_id is None


def test_02_ux_persists_visual_prototype_artifacts_with_validated_hashes():
    """2. UX can persist visual prototype artifacts with validated hashes."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        company = create_default_company(tmp_path)
        proj = company.projects.get("proj_test") or Project(id="proj_test", name="Test", root_path=str(tmp_path))
        task = proj.create_task(
            task_id="task_ux_proto",
            title="UX Prototyping",
            goal="Generate HTML prototypes",
            required_roles=["ux"],
        )
        run = task.create_run()

        concept = DesignConcept(
            concept_id="concept_wheel",
            name="Zodiac Wheel",
            design_rationale="Interactive radial composition",
            ux_specification="Spec details for zodiac wheel",
            html_prototype=CONCEPT_A_HTML,
        )
        concept.compute_hashes()

        ux_result = UXTaskResult(
            schema_version="1.0",
            status="READY_FOR_DEVELOPER",
            summary="Designed 1 interactive visual concept",
            concepts=[concept],
            recommended_concept_id="concept_wheel",
        )

        art = materialize_specialist_artifact(
            base_output_dir=tmp_path / "artifacts",
            task=task,
            run=run,
            agent_name="ux",
            typed_result=ux_result,
        )

        # Verify artifacts registered on run
        artifact_types = {a.artifact_type for a in run.artifacts}
        assert ArtifactType.UX_SPECIFICATION.value in artifact_types
        assert ArtifactType.UX_PROTOTYPE.value in artifact_types
        assert ArtifactType.UX_MOCKUP.value in artifact_types

        # Verify physical prototype file existence and SHA-256 integrity
        proto_art = next(a for a in run.artifacts if a.artifact_type == ArtifactType.UX_PROTOTYPE.value)
        proto_file = tmp_path / "artifacts" / proto_art.path
        assert proto_file.is_file()
        computed_sha = hashlib.sha256(proto_file.read_bytes()).hexdigest()
        assert computed_sha == proto_art.sha256
        assert computed_sha == concept.html_sha256


def test_03_browser_previews_correspond_to_actual_generated_prototype_source():
    """3. Browser previews correspond to the actual generated prototype source."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)
        d_path, m_path, d_sha, m_sha = render_prototype_previews(
            html_source=CONCEPT_A_HTML,
            output_dir=out_dir,
            concept_id="concept_wheel",
        )

        assert d_path.is_file()
        assert m_path.is_file()

        if d_path.suffix == ".png":
            # True Headless Browser Screenshot
            assert d_path.read_bytes().startswith(b"\x89PNG")
            assert m_path.read_bytes().startswith(b"\x89PNG")
            assert d_path.stat().st_size > 0
            assert m_path.stat().st_size > 0
        else:
            # SVG Fallback
            desktop_svg = d_path.read_text(encoding="utf-8")
            assert "Celestial Zodiac Wheel Registration" in desktop_svg
            assert "Begin Your Cosmic Journey" in desktop_svg
            assert "width=\"1280\"" in desktop_svg
            assert "height=\"800\"" in desktop_svg

            # Check Mobile preview SVG
            mobile_svg = m_path.read_text(encoding="utf-8")
            assert "Begin Your Cosmic Journey" in mobile_svg
            assert "Chart My Sky" in mobile_svg
            assert "width=\"390\"" in mobile_svg
            assert "height=\"844\"" in mobile_svg


def test_04_three_different_concepts_can_be_represented_independently():
    """4. Three different concepts can be represented independently."""
    c1 = DesignConcept(
        concept_id="concept_zodiac_wheel",
        name="Zodiac Wheel",
        design_rationale="Radial cosmic visualization",
        ux_specification="Spec A",
        html_prototype=CONCEPT_A_HTML,
    )
    c2 = DesignConcept(
        concept_id="concept_synastry_stepper",
        name="Synastry Stepper",
        design_rationale="Step-by-step guided journey",
        ux_specification="Spec B",
        html_prototype=CONCEPT_B_HTML,
    )
    c3 = DesignConcept(
        concept_id="concept_astral_card",
        name="Minimal Astral Card",
        design_rationale="Luxury card portal",
        ux_specification="Spec C",
        html_prototype=CONCEPT_C_HTML,
    )

    pkg = DesignProposalPackage(
        package_id="pkg_registration_pilot",
        project_id="jester",
        task_id="task_ux_01",
        run_id="run_01",
        concepts=[c1, c2, c3],
        recommended_concept_id="concept_synastry_stepper",
    )

    # Verify 3 distinct concept identities and distinct hashes
    assert len(pkg.concepts) == 3
    concept_ids = [c.concept_id for c in pkg.concepts]
    assert len(set(concept_ids)) == 3

    html_hashes = [c.html_sha256 for c in pkg.concepts]
    assert len(set(html_hashes)) == 3  # All 3 HTML sources have distinct hashes


def test_05_developer_mutation_blocked_before_authorized_founder_concept_selection():
    """5. Developer Mutation is blocked before authorized Founder concept selection."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        service = CompanyService(output_dir=str(tmp_path / "runs"), repo_root=tmp_path)
        
        # Setup git repo mock
        (tmp_path / ".git").mkdir()

        obj = CompanyObjective(
            id="obj_visual_redesign",
            title="Redesign Registration",
            description="Visual overhaul",
            target_repository=str(tmp_path),
            project_id="proj_jester",
        )
        run = service.create_company_run(obj)

        p_item = CEOPlannedWorkItem(work_item_id="item_p", role="product", objective="Reqs")
        ux_item = CEOPlannedWorkItem(work_item_id="item_ux", role="ux", objective="Design", depends_on=["item_p"])
        dev_item = CEOPlannedWorkItem(work_item_id="item_dev", role="developer", objective="Implement", depends_on=["item_p", "item_ux"])

        plan = CEOOrchestrationPlan(
            plan_id="plan_full",
            objective_id=obj.id,
            work_items=[p_item, ux_item, dev_item],
        )
        run.set_plan(plan)
        run.transition_to(CompanyRunState.PLANNING)
        run.transition_to(CompanyRunState.PLAN_READY)
        run.transition_to(CompanyRunState.RUNNING)

        # Complete upstream Product and UX with visual prototypes
        p_item.state = WorkItemState.COMPLETED.value
        ux_item.state = WorkItemState.COMPLETED.value
        run.work_item_states[p_item.work_item_id] = WorkItemState.COMPLETED.value
        run.work_item_states[ux_item.work_item_id] = WorkItemState.COMPLETED.value

        # Create physical tasks and artifacts in project
        proj = service.create_project(run.project_id, name="Jester Project")
        p_task = proj.create_task(task_id="p_t", title="Product", goal="Spec", required_roles=["product"])
        p_run = p_task.create_run()
        p_art_file = tmp_path / "runs" / "prod.md"
        p_art_file.parent.mkdir(parents=True, exist_ok=True)
        p_art_file.write_text("# Product Spec", encoding="utf-8")
        p_art = p_run.add_artifact(
            name="product_spec.md",
            artifact_type=ArtifactType.SPECIFICATION.value,
            path="prod.md",
            sha256=hashlib.sha256(b"# Product Spec").hexdigest(),
        )

        ux_task = proj.create_task(task_id="ux_t", title="UX", goal="Prototypes", required_roles=["ux"])
        ux_run = ux_task.create_run()
        ux_art_file = tmp_path / "runs" / "ux.md"
        ux_art_file.write_text("# UX Spec", encoding="utf-8")
        ux_art = ux_run.add_artifact(
            name="ux_spec.md",
            artifact_type=ArtifactType.UX_SPECIFICATION.value,
            path="ux.md",
            sha256=hashlib.sha256(b"# UX Spec").hexdigest(),
        )
        proto_file = tmp_path / "runs" / "prototype.html"
        proto_file.write_text(CONCEPT_A_HTML, encoding="utf-8")
        proto_art = ux_run.add_artifact(
            name="prototype_concept_a.html",
            artifact_type=ArtifactType.UX_PROTOTYPE.value,
            path="prototype.html",
            sha256=hashlib.sha256(CONCEPT_A_HTML.encode("utf-8")).hexdigest(),
        )

        p_item.task_id = p_task.id
        ux_item.task_id = ux_task.id
        service.save_company_run(run)

        # Developer work attempted WITHOUT Founder Design Approval
        adapter = EngineeringPipelineAdapter(service)
        with pytest.raises(DesignApprovalMissingError) as exc_info:
            adapter.execute_developer_work(run, dev_item)

        assert "Visual design concepts require authorized Founder Design Approval" in str(exc_info.value)
        assert run.state == CompanyRunState.BLOCKED.value


def test_06_ux_recommendation_cannot_self_approve():
    """6. A recommendation from UX cannot approve itself."""
    concept = DesignConcept(
        concept_id="c_test",
        name="Test",
        design_rationale="Rationale",
        ux_specification="Spec",
        html_prototype=CONCEPT_A_HTML,
    )

    # Actor 'ux' is forbidden from issuing Founder Design Approval
    with pytest.raises(DesignApprovalSelfApprovalForbiddenError) as exc_info:
        create_founder_design_approval(
            concept=concept,
            project_id="jester",
            run_id="run_1",
            task_id="task_1",
            package_id="pkg_1",
            founder_id="ux",
        )
    assert "A specialist agent recommendation cannot self-approve" in str(exc_info.value)

    # Non-human roles (developer, ceo, agent) also rejected
    for invalid_actor in ["developer", "ceo", "agent", "product"]:
        with pytest.raises(DesignApprovalSelfApprovalForbiddenError):
            create_founder_design_approval(
                concept=concept,
                project_id="jester",
                run_id="run_1",
                task_id="task_1",
                package_id="pkg_1",
                founder_id=invalid_actor,
            )


def test_07_approved_concept_identity_and_artifact_hashes_are_preserved():
    """7. Approved concept identity and artifact hashes are preserved."""
    concept = DesignConcept(
        concept_id="concept_celestial_stepper",
        name="Celestial Stepper",
        design_rationale="Step flow",
        ux_specification="Detailed stepper spec",
        html_prototype=CONCEPT_B_HTML,
    )
    concept.compute_hashes()

    approval = create_founder_design_approval(
        concept=concept,
        project_id="proj_jester",
        run_id="crun_1234",
        task_id="task_ux",
        package_id="pkg_reg",
        founder_id="founder_real_human",
    )

    # Verify preservation of identity and cryptographic hashes
    assert approval.concept_id == "concept_celestial_stepper"
    assert approval.html_prototype_sha256 == concept.html_sha256
    assert approval.ux_spec_sha256 == concept.spec_sha256
    assert approval.approval_sha256 != ""

    # Validation succeeds against unchanged concept and correct project
    validate_design_approval_for_developer_handoff(
        approval=approval,
        concept=concept,
        target_project_id="proj_jester",
    )


def test_08_modified_or_substituted_artifact_invalidates_handoff():
    """8. A modified or substituted artifact invalidates the handoff."""
    concept_original = DesignConcept(
        concept_id="concept_a",
        name="Original Concept",
        design_rationale="Original Rationale",
        ux_specification="Spec Original",
        html_prototype=CONCEPT_A_HTML,
    )
    concept_original.compute_hashes()

    approval = create_founder_design_approval(
        concept=concept_original,
        project_id="proj_jester",
        run_id="run_1",
        task_id="task_1",
        package_id="pkg_1",
        founder_id="founder_alice",
    )

    # Case A: Concept HTML was modified after approval
    tampered_concept = DesignConcept(
        concept_id="concept_a",
        name="Original Concept",
        design_rationale="Original Rationale",
        ux_specification="Spec Original",
        html_prototype=CONCEPT_A_HTML + "<!-- Tampered modification -->",
    )
    tampered_concept.compute_hashes()

    with pytest.raises(DesignApprovalTamperedError) as exc_info:
        validate_design_approval_for_developer_handoff(
            approval=approval,
            concept=tampered_concept,
            target_project_id="proj_jester",
        )
    assert "HTML prototype hash mismatch" in str(exc_info.value)

    # Case B: Concept ID substituted (swapped with another concept)
    substituted_concept = DesignConcept(
        concept_id="concept_b",
        name="Substituted Concept",
        design_rationale="Different Rationale",
        ux_specification="Spec B",
        html_prototype=CONCEPT_B_HTML,
    )
    substituted_concept.compute_hashes()

    with pytest.raises(DesignApprovalTamperedError) as exc_info:
        validate_design_approval_for_developer_handoff(
            approval=approval,
            concept=substituted_concept,
            target_project_id="proj_jester",
        )
    assert "Approved concept ID 'concept_a' does not match" in str(exc_info.value)


def test_09_concept_approval_does_not_automatically_approve_code_application():
    """9. Concept approval does not automatically approve code application."""
    concept = DesignConcept(
        concept_id="concept_c",
        name="Astral Card",
        design_rationale="Card layout",
        ux_specification="Spec C",
        html_prototype=CONCEPT_C_HTML,
    )
    concept.compute_hashes()

    design_approval = create_founder_design_approval(
        concept=concept,
        project_id="proj_jester",
        run_id="run_test",
        task_id="task_ux",
        package_id="pkg_test",
    )

    # Interchangeability check: passing Code Approval (RealRepoApplyGrant) as Design Approval fails
    fake_code_grant = RealRepoApplyGrant(
        schema_version="1.0",
        grant_id="grant_code_apply",
        proposal_id="prop_code_1",
        proposal_sha256="b" * 64,
        target_repository_root="/tmp/repo",
        expected_head_hash="abc1234",
        code_patch_artifact_id="art_patch",
        code_patch_sha256="c" * 64,
        qa_execution_report_artifact_id="art_qa",
        qa_execution_report_sha256="d" * 64,
        expected_changed_files=("frontend/src/App.tsx",),
        human_approval_id="founder_1",
        approver="Human Founder",
        approved_at="2026-10-15T00:00:00Z",
    )

    with pytest.raises(DesignApprovalInterchangeabilityError) as exc_info:
        validate_design_approval_for_developer_handoff(
            approval=fake_code_grant,
            concept=concept,
            target_project_id="proj_jester",
        )
    assert "Code Approval and Design Approval are strictly separate and never interchangeable" in str(exc_info.value)


def test_10_cross_project_inheritance_forbidden():
    """10. Another project cannot inherit Jester-specific assets or approvals."""
    concept = DesignConcept(
        concept_id="concept_jester_reg",
        name="Jester Cosmic Reg",
        design_rationale="Jester branded",
        ux_specification="Jester synastry tokens",
        html_prototype=CONCEPT_A_HTML,
    )
    concept.compute_hashes()

    # Approval issued strictly for 'jester' project
    approval = create_founder_design_approval(
        concept=concept,
        project_id="jester",
        run_id="crun_jester_01",
        task_id="task_ux",
        package_id="pkg_jester",
        founder_id="founder_alice",
    )

    # Attempting to use this approval in project 'other-fintech-project'
    with pytest.raises(DesignApprovalProjectMismatchError) as exc_info:
        validate_design_approval_for_developer_handoff(
            approval=approval,
            concept=concept,
            target_project_id="other-fintech-project",
        )
    assert "belongs to project 'jester', cannot be used for target project 'other-fintech-project'" in str(exc_info.value)


def test_11_existing_nonvisual_engineering_workflow_remains_compatible(tmp_path):
    """11. The existing nonvisual engineering workflow remains compatible."""
    # When UX produces standard textual UX_SPECIFICATION without UX_PROTOTYPE artifacts,
    # the existing pipeline functions without requiring FounderDesignApproval
    from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime

    class MockDevRuntime(AntigravityRuntime):
        def execute(self, agent, prompt, timeout=None, workspace_dir=None, env=None, **kwargs):
            return AgentExecutionResult(
                success=True,
                exit_code=0,
                stdout=json.dumps({
                    "schema_version": "1.0",
                    "status": "completed",
                    "summary": "Plan for backend feature",
                    "implementation_plan": ["1. Implement calculation logic"],
                    "files_to_modify": [{"path": "backend/calc.py", "description": "calc"}],
                    "files_to_create": [],
                    "commands_to_run": [],
                    "risks": [],
                    "assumptions": [],
                    "open_questions": [],
                }),
                stderr="",
                duration_ms=10.0,
                agent=agent,
            )

    service = CompanyService(output_dir=str(tmp_path / "runs"), runtime=MockDevRuntime())

    obj = CompanyObjective(
        id="obj_backend_feature",
        title="Add Backend Calculation",
        description="Pure logic feature",
        project_id="proj_calc",
    )
    run = service.create_company_run(obj)

    p_item = CEOPlannedWorkItem(work_item_id="item_p", role="product", objective="Reqs")
    dev_item = CEOPlannedWorkItem(work_item_id="item_dev", role="developer", objective="Implement", depends_on=["item_p"])

    plan = CEOOrchestrationPlan(
        plan_id="plan_nonvisual",
        objective_id=obj.id,
        work_items=[p_item, dev_item],
        allow_direct_developer=True,
    )
    run.set_plan(plan)
    run.transition_to(CompanyRunState.PLANNING)
    run.transition_to(CompanyRunState.PLAN_READY)
    run.transition_to(CompanyRunState.RUNNING)

    # Product task only
    proj = service.create_project(run.project_id, name="Calc Project")
    p_task = proj.create_task(task_id="p_t", title="Product", goal="Spec", required_roles=["product"])
    p_run = p_task.create_run()
    p_art_file = tmp_path / "runs" / "prod.md"
    p_art_file.parent.mkdir(parents=True, exist_ok=True)
    p_art_file.write_text("# Product Spec", encoding="utf-8")
    p_art = p_run.add_artifact(
        name="product_spec.md",
        artifact_type=ArtifactType.SPECIFICATION.value,
        path="prod.md",
        sha256=hashlib.sha256(b"# Product Spec").hexdigest(),
        producer_role="product",
    )

    p_run.complete(status=RunStatus.SUCCESS.value)
    p_task.complete(status=TaskStatus.COMPLETED.value, summary="Product spec complete")
    p_item.state = WorkItemState.COMPLETED.value
    p_item.task_id = p_task.id
    run.work_item_states[p_item.work_item_id] = WorkItemState.COMPLETED.value

    # Non-visual engineering task proceeds through planning without FounderDesignApproval
    plan_task = service.create_task(
        project_id=proj.id,
        task_id="task_dev_plan",
        title="Developer Plan",
        goal="Implement calculation",
        required_roles=["developer"],
    )
    plan_task.allow_direct_developer = True
    service.attach_input_artifact(plan_task.id, p_art.id, project_id=proj.id)

    # Developer planning executes normally
    plan_run = service.execute_developer_planning_task(plan_task.id, project_id=proj.id)
    assert plan_run.status == RunStatus.SUCCESS.value


def test_12_frontend_repair_verification_does_not_default_to_unrelated_backend_tests():
    """12. Frontend repair verification does not default to unrelated backend tests."""
    # A repair plan modifying only frontend code
    plan = DeveloperRepairPlan(
        repair_id="rep_frontend_visual",
        iteration=1,
        root_cause="Button alignment and contrast defect",
        files_to_modify=[
            ProposedFile(path="frontend/src/pages/Register.tsx", description="Fix layout"),
            ProposedFile(path="frontend/src/styles/register.css", description="Fix styling"),
        ],
        proposed_changes=["Adjust flexbox alignment and color tokens"],
        # Developer accidentally proposed unrelated backend JWT test
        proposed_verification_actions=[
            VerificationAction(action_type="pytest", target="tests/backend/test_jwt_verification.py"),
        ],
    )

    prev_grant = ExecutionGrant(
        grant_id="grant_prev",
        task_id="task_prev",
        plan_artifact_id="plan_prev",
        plan_sha256="a" * 64,
        base_commit_hash="abc1234",
        approved_files_to_modify=("frontend/src/pages/Register.tsx",),
        approved_files_to_create=(),
        verification_actions=(VerificationAction(action_type="frontend_build", target="frontend"),),
        founder_approval_id="founder_1",
    )

    repair_grant = derive_repair_execution_grant(
        plan=plan,
        previous_grant=prev_grant,
        base_commit_hash="abc1234",
        founder_approval_id="founder_1",
        plan_artifact_id="art_plan",
        plan_sha256="b" * 64,
    )

    # Invariant: Unrelated backend pytest was filtered out; frontend_build on frontend was selected
    grant_action_targets = [va.target for va in repair_grant.verification_actions]
    assert "tests/backend/test_jwt_verification.py" not in grant_action_targets
    assert any("frontend" in target for target in grant_action_targets)

    # Verify that QA category distinguishing records exist
    qa_json = json.dumps({
        "schema_version": "1.0",
        "status": "READY_FOR_QA_EXECUTION",
        "summary": "QA inspection completed",
        "requirements_coverage": [{"requirement_id": "REQ-1", "status": "COVERED", "evidence": "Diff verified"}],
        "risks": [],
        "findings": [],
        "test_cases": [],
        "regression_areas": [],
        "unresolved_questions": [],
        "recommended_verification_actions": [{"action_type": "frontend_build", "target": "frontend", "purpose": "build"}],
        "category_verifications": [
            {"category": "FUNCTIONAL_CORRECTNESS", "status": "VERIFIED", "verified": True, "evidence": "Build passed"},
            {"category": "DESIGN_SPECIFICATION_COMPLIANCE", "status": "VERIFIED", "verified": True, "evidence": "UX tokens match"},
            {"category": "VISUAL_FIDELITY", "status": "VERIFIED", "verified": True, "evidence": "Screenshots match approved preview"},
            {"category": "ACCESSIBILITY_AND_RESPONSIVENESS", "status": "UNVERIFIED", "verified": False, "evidence": "Mobile test pending"},
            {"category": "AUTHORIZED_FILE_CHANGES", "status": "VERIFIED", "verified": True, "evidence": "Scope authorized"},
        ]
    })
    qa_res = parse_and_validate_qa_result(qa_json)
    assert len(qa_res.category_verifications) == 5
    assert "VISUAL_FIDELITY" in qa_res.verified_categories
    assert "ACCESSIBILITY_AND_RESPONSIVENESS" in qa_res.unverified_categories
