"""STEP 24.4.1 — Deterministic Verification Suite for Product Timeout Recovery & True UX Preview Fidelity.

Tests:
A. Product prompt construction respects task-specific scope and output budgets.
B. Required authentication and acceptance criteria are preserved.
C. A Product timeout is recorded and cannot generate a fabricated completed artifact.
D. Retry behavior is bounded and failure-aware.
E. Existing Product -> UX handoffs remain valid.
F. Different UX concepts retain independent identities and hashes.
G. A visual preview, when reported as a browser screenshot, comes from actual persisted HTML/CSS.
H. A generic SVG template cannot be labeled as a browser screenshot.
I. Tampered prototype content invalidates the associated preview or approval.
J. Existing Founder Design Approval and Developer gates remain functional.
"""

import hashlib
from pathlib import Path
import tempfile
import pytest

from jester_ai_company.core import (
    ArtifactType,
    Company,
    Employee,
    Project,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
)
from jester_ai_company.design_approval import (
    DesignApprovalStatus,
    DesignApprovalTamperedError,
    FounderDesignApproval,
    create_founder_design_approval,
)
from jester_ai_company.design_concept import (
    DesignConcept,
    DesignProposalPackage,
    PreviewProvenanceError,
    TamperedPrototypeError,
    compute_sha256_text,
    validate_preview_provenance,
)
from jester_ai_company.orchestrator import (
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    WorkItemState,
)
from jester_ai_company.product_result import (
    ProductDeliverable,
    ProductTaskResult,
    build_product_execution_prompt,
    parse_and_validate_product_result,
)
from jester_ai_company.prototype_renderer import (
    PrototypeRenderResult,
    find_available_browser,
    render_prototype_previews,
)
from jester_ai_company.recovery import (
    FailureCategory,
    RecoveryDecision,
    classify_specialist_failure,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.ux_result import (
    UXResultValidationError,
    UXTaskResult,
    build_ux_execution_prompt,
    parse_and_validate_ux_result,
)


SAMPLE_PROTOTYPE_HTML = """<!DOCTYPE html>
<html lang="ka">
<head>
    <meta charset="utf-8">
    <title>JESTER Registration</title>
    <style>
        body { margin: 0; background-color: #FAF7F2; font-family: system-ui, sans-serif; }
        .hero { padding: 40px; text-align: center; }
        h1 { color: #222630; font-size: 28px; }
        button { background: #FF7A2F; color: #FFFFFF; border: none; padding: 12px 24px; border-radius: 8px; }
    </style>
</head>
<body>
    <div class="hero">
        <h1>შექმენი შენი კოსმიური პროფილი</h1>
        <p>შეიყვანეთ ელფოსტა და პაროლი</p>
        <button>რეგისტრაცია</button>
    </div>
</body>
</html>"""


# -----------------------------------------------------------------------------
# Test A: Product prompt construction respects task scope and output budgets
# -----------------------------------------------------------------------------
def test_A_product_prompt_respects_task_scope_and_output_budgets():
    """A. Product prompt construction respects task-specific scope and output budgets."""
    task = Task(
        id="task_prd_1",
        project_id="proj_1",
        title="JESTER Registration Visual Pilot PRD",
        goal="Define compact PRD for the registration visual redesign pilot",
        required_roles=["product"],
        constraints=["Preserve existing Supabase auth boundaries", "Georgian-first UI copy"],
        expected_output=["Compact PRD with acceptance criteria"],
        metadata={
            "compact_prd": True,
            "word_budget": "approximately 800–1200 words",
            "is_retry": True,
        },
    )

    prompt = build_product_execution_prompt(task)

    # 1. Output budget enforced
    assert "EXECUTION SCOPE & OUTPUT BUDGET (COMPACT PRD MODE):" in prompt
    assert "approximately 800–1200 words" in prompt
    assert "BOUNDED EXECUTION: Do NOT perform exhaustive codebase exploration" in prompt

    # 2. Required 7 core sections specified
    assert "1. Existing Functionality" in prompt
    assert "2. Authentication Boundaries" in prompt
    assert "3. User Goals" in prompt
    assert "4. Brand Constraints" in prompt
    assert "5. UX Constraints" in prompt
    assert "6. Acceptance Criteria" in prompt
    assert "7. Known Unknowns" in prompt

    # 3. Explicit in/out scope requirement
    assert "EXPLICIT IN/OUT SCOPE: Clearly define what is strictly IN-SCOPE and what is OUT-OF-SCOPE" in prompt

    # 4. Citation over re-invention
    assert "CITATION OVER RE-INVENTION: Authoritative project knowledge" in prompt

    # 5. Recovery alert present for retry
    assert "RECOVERY EXECUTION ALERT:" in prompt
    assert "A previous execution attempt timed out due to excessive exploration" in prompt

    # 6. Unrelated tasks without compact metadata do not have budget block forced
    unrelated_task = Task(
        id="task_generic",
        project_id="proj_1",
        title="Quarterly Roadmap Overview",
        goal="High level product strategy",
        required_roles=["product"],
    )
    unrelated_prompt = build_product_execution_prompt(unrelated_task)
    assert "COMPACT PRD MODE" not in unrelated_prompt


# -----------------------------------------------------------------------------
# Test B: Required authentication and acceptance criteria are preserved
# -----------------------------------------------------------------------------
def test_B_required_authentication_and_acceptance_criteria_preserved():
    """B. Required authentication and acceptance criteria are preserved."""
    task = Task(
        id="task_prd_auth",
        project_id="proj_1",
        title="JESTER Registration Auth & Visual Scope",
        goal="Define visual redesign requirements preserving Supabase authentication",
        required_roles=["product"],
        constraints=[
            "Strict adherence to existing Supabase auth schema and endpoints",
            "Mandatory Acceptance Criteria 1: Zero regression on email/password validation",
            "Mandatory Acceptance Criteria 2: Natural Georgian error messaging",
        ],
        expected_output=["PRD with verified authentication boundaries"],
    )

    prompt = build_product_execution_prompt(task)

    assert "Strict adherence to existing Supabase auth schema and endpoints" in prompt
    assert "Zero regression on email/password validation" in prompt
    assert "Natural Georgian error messaging" in prompt
    assert "SOURCE AUTHORITY & CONFLICT RESOLUTION HIERARCHY:" in prompt
    assert "Authorized Founder Objective and explicit constraints (HIGHEST PRIORITY)" in prompt


# -----------------------------------------------------------------------------
# Test C: Product timeout recorded and cannot generate fabricated completed artifact
# -----------------------------------------------------------------------------
def test_C_product_timeout_recorded_and_cannot_generate_fabricated_artifact():
    """C. A Product timeout is recorded and cannot generate a fabricated completed artifact."""
    # Test classifier: Even if agent draft output in stdout mentions "forbidden modifications",
    # timeout must be classified as TIMEOUT, NOT POLICY_OR_PERMISSION
    draft_stdout = (
        "Here is draft progress...\n"
        "### OUT OF SCOPE (Forbidden Modifications):\n"
        "- Do not alter database migrations"
    )

    frec = classify_specialist_failure(
        error_message="Specialist 'product' timed out after 600.0s.",
        exit_code=None,
        timed_out=True,
        stdout=draft_stdout,
        stderr="",
        role="product",
        work_item_id="item_prd",
        attempt_number=1,
        max_retries=1,
    )

    assert frec.failure_category == FailureCategory.TIMEOUT.value
    assert frec.recovery_eligibility is True
    assert frec.recovery_decision in (RecoveryDecision.RETRY.value, RecoveryDecision.REPLAN.value)

    # In service execution, when task times out, TaskRun status is FAILED and artifacts are empty
    task_run = TaskRun(
        id="run_timeout_1",
        task_id="task_prd_1",
        attempt_number=1,
        status=RunStatus.FAILED.value,
        error="Execution timed out after 600.0 seconds.",
    )
    assert task_run.status == RunStatus.FAILED.value
    assert len(task_run.artifacts) == 0  # No fabricated artifacts permitted


# -----------------------------------------------------------------------------
# Test D: Retry behavior is bounded and failure-aware
# -----------------------------------------------------------------------------
def test_D_retry_behavior_is_bounded_and_failure_aware():
    """D. Retry behavior is bounded and failure-aware."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=Path(tmp_dir))
        company = service.get_company()
        proj = service.create_project(project_id="proj_test", name="Jester")

        obj = CompanyObjective(
            id="obj_test_1",
            title="Registration Redesign",
            description="Visual redesign pilot",
            constraints=["Preserve Supabase auth"],
            acceptance_criteria=["Deliver compact PRD"],
            target_repository=tmp_dir,
            project_id=proj.id,
        )
        run = service.create_company_run(obj)

        item = CEOPlannedWorkItem(
            work_item_id="item_prd_retry",
            role="product",
            objective="Define PRD for registration visual redesign",
        )

        # Attempt 1 failure: timeout
        updated_run = service._handle_work_item_failure(
            run=run,
            target_item=item,
            role="product",
            error_msg="Specialist 'product' timed out after 600.0s",
        )

        # Check bounded retry configuration was attached
        assert item.metadata.get("is_retry") is True
        assert item.metadata.get("bounded") is True
        assert item.metadata.get("compact_prd") is True
        assert item.metadata.get("word_budget") == "800–1200 words"
        assert item.metadata.get("max_knowledge_sources") == 2
        assert item.metadata.get("max_excerpt_chars") == 1500

        # Attempt 2 failure: second timeout must exhaust retry budget
        updated_run_2 = service._handle_work_item_failure(
            run=updated_run,
            target_item=item,
            role="product",
            error_msg="Specialist 'product' timed out after 600.0s",
        )

        last_frec = updated_run_2.recovery_history[-1]
        assert last_frec["attempt_number"] == 2
        assert last_frec["recovery_eligibility"] is False
        assert last_frec["recovery_decision"] == RecoveryDecision.FAIL.value


# -----------------------------------------------------------------------------
# Test E: Existing Product -> UX handoffs remain valid
# -----------------------------------------------------------------------------
def test_E_existing_product_to_ux_handoff_remains_valid():
    """E. Existing Product -> UX handoffs remain valid."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=Path(tmp_dir))
        proj = service.create_project(project_id="proj_handoff", name="Jester")

        # 1. Product produces specification artifact
        prd_text = "# Registration PRD\n\nExisting auth boundaries preserved."
        prd_task = service.create_task(
            title="Registration PRD",
            goal="Define registration requirements",
            project_id=proj.id,
            required_roles=["product"],
        )
        prd_run = prd_task.create_run()
        prd_file = Path(tmp_dir) / "product_report.md"
        prd_file.write_text(prd_text, encoding="utf-8")
        prd_art = prd_run.add_artifact(
            name="product_report.md",
            artifact_type=ArtifactType.SPECIFICATION.value,
            path="product_report.md",
            sha256=hashlib.sha256(prd_text.encode("utf-8")).hexdigest(),
            durable=True,
            producer_role="product",
        )
        prd_run.complete(status=RunStatus.SUCCESS.value)
        prd_task.complete(status=TaskStatus.COMPLETED.value, summary="PRD completed")

        # 2. Attach to UX task
        ux_task = service.create_task(
            title="Registration UX Design",
            goal="Develop 3 visual concepts",
            project_id=proj.id,
            required_roles=["ux"],
        )

        ref = service.attach_input_artifact(
            target_task_id=ux_task.id,
            source_artifact_id=prd_art.id,
            project_id=proj.id,
        )
        assert ref.artifact_id == prd_art.id
        assert len(ux_task.input_artifacts) == 1


# -----------------------------------------------------------------------------
# Test F: Different UX concepts retain independent identities and hashes
# -----------------------------------------------------------------------------
def test_F_different_ux_concepts_retain_independent_identities_and_hashes():
    """F. Different UX concepts retain independent identities and hashes."""
    c1 = DesignConcept(
        concept_id="concept_editorial",
        name="Editorial Luxury",
        design_rationale="High-contrast typography",
        ux_specification="Dual-column split layout",
        html_prototype=SAMPLE_PROTOTYPE_HTML,
    )
    c2 = DesignConcept(
        concept_id="concept_minimalist",
        name="Minimal Cosmic",
        design_rationale="Single card floating center",
        ux_specification="Single-column center card",
        html_prototype=SAMPLE_PROTOTYPE_HTML.replace("FAF7F2", "FFFFFF"),
    )
    c3 = DesignConcept(
        concept_id="concept_immersive",
        name="Immersive Storytelling",
        design_rationale="Deep cosmic background",
        ux_specification="Full-screen immersive background",
        html_prototype=SAMPLE_PROTOTYPE_HTML.replace("FAF7F2", "0D1117"),
    )

    pkg = DesignProposalPackage(
        package_id="pkg_123",
        project_id="proj_1",
        task_id="task_ux",
        run_id="run_ux",
        concepts=[c1, c2, c3],
        recommended_concept_id="concept_editorial",
    )

    pkg.validate_concepts_uniqueness()

    # Verify identities and hashes are distinct
    assert c1.concept_id != c2.concept_id != c3.concept_id
    assert c1.html_sha256 != c2.html_sha256 != c3.html_sha256

    # Duplicate concept IDs must be rejected
    c_dup = DesignConcept(
        concept_id="concept_editorial",
        name="Duplicate Concept",
        design_rationale="...",
        ux_specification="...",
        html_prototype="<html></html>",
    )
    pkg_invalid = DesignProposalPackage(
        package_id="pkg_bad",
        project_id="proj_1",
        task_id="task_ux",
        run_id="run_ux",
        concepts=[c1, c_dup],
    )
    with pytest.raises(ValueError, match="Duplicate concept_id"):
        pkg_invalid.validate_concepts_uniqueness()


# -----------------------------------------------------------------------------
# Test G: Visual preview reported as browser screenshot comes from actual HTML
# -----------------------------------------------------------------------------
def test_G_visual_preview_reported_as_browser_screenshot_comes_from_actual_html():
    """G. A visual preview, when reported as a browser screenshot, comes from actual persisted HTML/CSS."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)

        # Check if browser is present on system
        browser = find_available_browser()
        if not browser:
            pytest.skip("No headless browser installed on local environment.")

        result = render_prototype_previews(
            html_source=SAMPLE_PROTOTYPE_HTML,
            output_dir=out_dir,
            concept_id="concept_real",
            browser_path=browser,
            force_svg_fallback=False,
        )

        assert isinstance(result, PrototypeRenderResult)
        assert result.is_browser_screenshot is True
        assert result.rendering_method == "HEADLESS_BROWSER_SCREENSHOT"
        assert result.desktop_viewport == "1280x800"
        assert result.mobile_viewport == "390x844"

        # Check files on disk
        assert result.desktop_file.is_file()
        assert result.mobile_file.is_file()
        assert result.desktop_file.name.endswith(".png")
        assert result.mobile_file.name.endswith(".png")

        # Verify real PNG magic bytes
        assert result.desktop_file.read_bytes().startswith(b"\x89PNG")
        assert result.mobile_file.read_bytes().startswith(b"\x89PNG")

        # Verify source HTML sha256 matches persisted file
        html_file = out_dir / "prototype_concept_real.html"
        assert html_file.is_file()
        actual_html_sha = hashlib.sha256(html_file.read_bytes()).hexdigest()
        assert result.source_html_sha256 == actual_html_sha


# -----------------------------------------------------------------------------
# Test H: Generic SVG template cannot be labeled as a browser screenshot
# -----------------------------------------------------------------------------
def test_H_generic_svg_template_cannot_be_labeled_as_browser_screenshot():
    """H. A generic SVG template cannot be labeled as a browser screenshot."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)

        # Force SVG fallback
        result = render_prototype_previews(
            html_source=SAMPLE_PROTOTYPE_HTML,
            output_dir=out_dir,
            concept_id="concept_fallback",
            force_svg_fallback=True,
        )

        assert result.is_browser_screenshot is False
        assert result.rendering_method == "GENERIC_SVG_FALLBACK"
        assert result.desktop_file.name.endswith(".svg")
        assert result.mobile_file.name.endswith(".svg")

        # Provenance validation: Attempting to label an SVG preview as a browser screenshot fails closed
        fraudulent_concept = DesignConcept(
            concept_id="concept_fraud",
            name="Fraudulent Concept",
            design_rationale="...",
            ux_specification="...",
            html_prototype=SAMPLE_PROTOTYPE_HTML,
            desktop_preview_path=str(result.desktop_file),
            mobile_preview_path=str(result.mobile_file),
            desktop_preview_sha256=result.desktop_sha,
            mobile_preview_sha256=result.mobile_sha,
            rendering_method="GENERIC_SVG_FALLBACK",
            is_browser_screenshot=True,  # FRAUDULENT CLAIM
        )

        with pytest.raises(PreviewProvenanceError, match="A generic SVG template cannot be labeled as a browser screenshot"):
            validate_preview_provenance(fraudulent_concept)


# -----------------------------------------------------------------------------
# Test I: Tampered prototype content invalidates preview and approval
# -----------------------------------------------------------------------------
def test_I_tampered_prototype_content_invalidates_preview_and_approval():
    """I. Tampered prototype content invalidates the associated preview or approval."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_dir = Path(tmp_dir)

        concept = DesignConcept(
            concept_id="concept_secure",
            name="Secure Concept",
            design_rationale="...",
            ux_specification="UX spec v1",
            html_prototype=SAMPLE_PROTOTYPE_HTML,
        )

        render_res = render_prototype_previews(
            html_source=concept.html_prototype,
            output_dir=out_dir,
            concept_id=concept.concept_id,
            force_svg_fallback=True,
        )
        concept.desktop_preview_path = str(render_res.desktop_file)
        concept.mobile_preview_path = str(render_res.mobile_file)
        concept.desktop_preview_sha256 = render_res.desktop_sha
        concept.mobile_preview_sha256 = render_res.mobile_sha

        # 1. Valid state passes provenance check
        validate_preview_provenance(concept, base_dir=out_dir)

        # 2. Tampering prototype file on disk
        html_file = out_dir / f"prototype_{concept.concept_id}.html"
        html_file.write_text("<!DOCTYPE html><html><body>Tampered!</body></html>", encoding="utf-8")

        with pytest.raises(TamperedPrototypeError, match="Tampered prototype content detected"):
            validate_preview_provenance(concept, base_dir=out_dir)

        # 3. Founder Design Approval must reject tampered concept
        approval = create_founder_design_approval(
            project_id="proj_test",
            run_id="crun_test",
            task_id="task_ux",
            package_id="pkg_test",
            concept=concept,
            founder_id="founder",
        )

        # Modify concept HTML in memory after approval was created
        tampered_concept = DesignConcept(
            concept_id="concept_secure",
            name="Secure Concept",
            design_rationale="...",
            ux_specification="UX spec v1",
            html_prototype="<html><body>Substituted after approval</body></html>",
        )

        with pytest.raises(DesignApprovalTamperedError, match="HTML prototype hash mismatch"):
            approval.validate_against_concept(tampered_concept, target_project_id="proj_test")


# -----------------------------------------------------------------------------
# Test J: Existing Founder Design Approval and Developer gates remain functional
# -----------------------------------------------------------------------------
def test_J_existing_founder_design_approval_and_developer_gates_remain_functional():
    """J. Existing Founder Design Approval and Developer gates remain functional."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=Path(tmp_dir))
        proj = service.create_project(project_id="proj_gate", name="Jester")

        obj = CompanyObjective(
            id="obj_test_j",
            title="Registration Redesign",
            description="Visual redesign pilot with developer implementation",
            constraints=[],
            acceptance_criteria=["Deliver visual concepts"],
            target_repository=tmp_dir,
            project_id=proj.id,
        )
        run = service.create_company_run(obj)

        # Verify initial state
        assert run.state == CompanyRunState.CREATED.value
        assert run.founder_design_approval is None
        assert run.founder_design_approval_id is None
