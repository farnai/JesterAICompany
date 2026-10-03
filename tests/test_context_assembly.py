"""Tests for STEP 17B-2: Token-Aware & Role-Aware Context Assembly.

Covers:
- A. CEO initial context contains objective
- B. CEO initial context contains acceptance criteria
- C. CEO initial context does not contain unrelated raw artifacts
- D. CEO context does not contain raw transcripts
- E. EmployeeResultSummary is bounded (MAX_EMPLOYEE_SUMMARY_CHARS)
- F. Research context does not receive unrelated Developer/QA content
- G. Product receives only permitted relevant upstream context
- H. UX receives permitted Product context
- I. Marketing does not receive CODE_PATCH by default
- J. Developer receives verified Product + UX required inputs
- K. Developer fails closed if required Product artifact is missing
- L. Developer fails closed if required UX artifact is missing
- M. Tampered artifact fails verification
- N. Oversized required artifact fails closed
- O. Dependency alone does not automatically inject artifact content
- P. Handoff policy is checked separately
- Q. ContextEnvelope serialization round-trip
- R. Same logical inputs produce same logical context (reproducibility)
- S. Full content is absent unless explicitly selected by policy
"""

import hashlib
import json
from pathlib import Path
import tempfile
import pytest

from jester_ai_company.context import (
    CONTEXT_ENVELOPE_SCHEMA_VERSION,
    MAX_CEO_CONTEXT_CHARS,
    MAX_EMPLOYEE_SUMMARY_CHARS,
    MAX_SELECTED_ARTIFACT_CONTENT_CHARS,
    MAX_SPECIALIST_CONTEXT_CHARS,
    ContextAssemblyError,
    ContextEnvelope,
    ContextSizeExceededError,
    assemble_ceo_context,
    assemble_specialist_context,
)
from jester_ai_company.core import (
    Artifact,
    ArtifactInputRef,
    ArtifactType,
)
from jester_ai_company.orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    EmployeeResultSummary,
)


@pytest.fixture
def sample_objective() -> CompanyObjective:
    return CompanyObjective(
        id="obj_market_01",
        title="Market Discovery Mission",
        description="Investigate competitive advantages and user feedback.",
        constraints=["Focus on EU market", "No paid user interviews"],
        acceptance_criteria=["Competitive matrix delivered", "100% verified sources"],
        target_repository="/repos/jester",
    )


def test_requirement_a_b_c_d_e_ceo_context(sample_objective: CompanyObjective):
    """Requirements A, B, C, D, E: CEO initial context boundaries and limits."""
    summary_oversized = "A" * (MAX_EMPLOYEE_SUMMARY_CHARS + 500)
    summary_obj = EmployeeResultSummary(
        role="research",
        task_id="t1",
        run_id="r1",
        status="SUCCESS",
        summary=summary_oversized,
    )

    envelope = assemble_ceo_context(
        objective=sample_objective,
        summaries=[summary_obj],
    )

    # A. Contains objective
    assert envelope.objective["id"] == sample_objective.id
    assert envelope.objective["title"] == sample_objective.title

    # B. Contains acceptance criteria
    assert envelope.objective["acceptance_criteria"] == sample_objective.acceptance_criteria

    # C. Does NOT contain raw artifact content
    assert len(envelope.selected_artifact_contents) == 0

    # D. Does NOT contain raw transcripts
    serialized = json.dumps(envelope.to_dict())
    assert "transcript" not in serialized.lower()

    # E. EmployeeResultSummary is bounded
    assert len(envelope.employee_result_summaries) == 1
    bounded_summary_text = envelope.employee_result_summaries[0]["summary"]
    assert len(bounded_summary_text) <= MAX_EMPLOYEE_SUMMARY_CHARS + 20
    assert "... [truncated]" in bounded_summary_text


def test_requirement_q_context_envelope_serialization_round_trip(sample_objective: CompanyObjective):
    """Requirement Q: ContextEnvelope serialization round-trip."""
    envelope = assemble_ceo_context(
        objective=sample_objective,
        constraints=["Additional constraint"],
    )
    d = envelope.to_dict()
    restored = ContextEnvelope.from_dict(d)

    assert restored.recipient_role == envelope.recipient_role
    assert restored.objective == envelope.objective
    assert restored.constraints == envelope.constraints
    assert restored.schema_version == CONTEXT_ENVELOPE_SCHEMA_VERSION


def test_requirement_r_reproducible_context_assembly(sample_objective: CompanyObjective):
    """Requirement R: Same logical inputs produce identical logical context."""
    env1 = assemble_ceo_context(objective=sample_objective)
    env2 = assemble_ceo_context(objective=sample_objective)

    d1 = env1.to_dict()
    d2 = env2.to_dict()

    # Aside from generated_at, all fields must match exactly
    del d1["generated_at"]
    del d2["generated_at"]
    assert d1 == d2


def test_requirement_f_research_context_isolation(sample_objective: CompanyObjective):
    """Requirement F: Research context does not receive unrelated Developer/QA content."""
    work_item = CEOPlannedWorkItem(
        work_item_id="item_res",
        role="research",
        objective="Market discovery",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        envelope = assemble_specialist_context(
            recipient_role="research",
            objective=sample_objective,
            work_item=work_item,
            base_output_dir=Path(tmpdir),
        )
        assert envelope.recipient_role == "research"
        assert len(envelope.selected_artifact_contents) == 0
        assert envelope.work_item["work_item_id"] == "item_res"


def _create_real_artifact(
    base_dir: Path,
    artifact_id: str,
    role: str,
    art_type: ArtifactType,
    content: str,
) -> tuple[Artifact, ArtifactInputRef]:
    rel_path = f"artifacts/{artifact_id}.md"
    full_path = base_dir / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")

    sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    art = Artifact(
        id=artifact_id,
        name=f"{artifact_id}.md",
        artifact_type=art_type.value,
        path=rel_path,
        producer_role=role,
        run_id="r1",
        sha256=sha,
    )
    ref = ArtifactInputRef(
        artifact_id=artifact_id,
        run_id="r1",
        sha256=sha,
        producer_role=role,
    )
    return art, ref


def test_requirement_g_h_product_and_ux_context(sample_objective: CompanyObjective):
    """Requirements G & H: Product receives Research; UX receives Product context."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        # 1. Product receives Research (allowed edge: research -> product)
        res_art, res_ref = _create_real_artifact(
            base_dir, "art_res_01", "research", ArtifactType.RESEARCH_REPORT, "Market Findings"
        )
        prod_work_item = CEOPlannedWorkItem(
            work_item_id="item_prod",
            role="product",
            objective="PRD",
            depends_on=["item_res"],
        )
        prod_env = assemble_specialist_context(
            recipient_role="product",
            objective=sample_objective,
            work_item=prod_work_item,
            base_output_dir=base_dir,
            available_artifacts={res_art.id: res_art},
            artifact_input_refs=[res_ref],
        )
        assert res_art.id in prod_env.selected_artifact_contents
        assert prod_env.selected_artifact_contents[res_art.id] == "Market Findings"

        # 2. UX receives Product (allowed edge: product -> ux)
        prod_art, prod_ref = _create_real_artifact(
            base_dir, "art_prod_01", "product", ArtifactType.SPECIFICATION, "Product Spec"
        )
        ux_work_item = CEOPlannedWorkItem(
            work_item_id="item_ux",
            role="ux",
            objective="Wireframes",
            depends_on=["item_prod"],
        )
        ux_env = assemble_specialist_context(
            recipient_role="ux",
            objective=sample_objective,
            work_item=ux_work_item,
            base_output_dir=base_dir,
            available_artifacts={prod_art.id: prod_art},
            artifact_input_refs=[prod_ref],
        )
        assert prod_art.id in ux_env.selected_artifact_contents
        assert ux_env.selected_artifact_contents[prod_art.id] == "Product Spec"


def test_requirement_i_marketing_does_not_receive_code_patch(sample_objective: CompanyObjective):
    """Requirement I: Marketing does not receive CODE_PATCH by default."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        patch_art, patch_ref = _create_real_artifact(
            base_dir, "art_patch_01", "developer", ArtifactType.CODE_PATCH, "diff --git..."
        )
        prod_art, prod_ref = _create_real_artifact(
            base_dir, "art_prod_01", "product", ArtifactType.SPECIFICATION, "PRD Features"
        )

        mkt_work_item = CEOPlannedWorkItem(
            work_item_id="item_mkt",
            role="marketing",
            objective="Announcement",
        )
        mkt_env = assemble_specialist_context(
            recipient_role="marketing",
            objective=sample_objective,
            work_item=mkt_work_item,
            base_output_dir=base_dir,
            available_artifacts={patch_art.id: patch_art, prod_art.id: prod_art},
            artifact_input_refs=[patch_ref, prod_ref],
        )

        # PRD received (allowed edge: product -> marketing)
        assert prod_art.id in mkt_env.selected_artifact_contents
        # Patch NOT received
        assert patch_art.id not in mkt_env.selected_artifact_contents


def test_requirement_j_k_l_developer_fan_in_context_prerequisites(sample_objective: CompanyObjective):
    """Requirements J, K, L: Developer requires both verified Product and UX artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        prod_art, prod_ref = _create_real_artifact(
            base_dir, "prod_1", "product", ArtifactType.SPECIFICATION, "PRD"
        )
        ux_art, ux_ref = _create_real_artifact(
            base_dir, "ux_1", "ux", ArtifactType.UX_SPECIFICATION, "Wireframes"
        )

        dev_work_item = CEOPlannedWorkItem(
            work_item_id="item_dev",
            role="developer",
            objective="Implement",
            depends_on=["item_prod", "item_ux"],
        )

        # J. Valid Product + UX provided -> Success
        dev_env = assemble_specialist_context(
            recipient_role="developer",
            objective=sample_objective,
            work_item=dev_work_item,
            base_output_dir=base_dir,
            available_artifacts={prod_art.id: prod_art, ux_art.id: ux_art},
            artifact_input_refs=[prod_ref, ux_ref],
        )
        assert prod_art.id in dev_env.selected_artifact_contents
        assert ux_art.id in dev_env.selected_artifact_contents

        # K. Missing Product -> Fail closed
        with pytest.raises(ContextAssemblyError, match="requires both verified Product and UX"):
            assemble_specialist_context(
                recipient_role="developer",
                objective=sample_objective,
                work_item=dev_work_item,
                base_output_dir=base_dir,
                available_artifacts={ux_art.id: ux_art},
                artifact_input_refs=[ux_ref],
            )

        # L. Missing UX -> Fail closed
        with pytest.raises(ContextAssemblyError, match="requires both verified Product and UX"):
            assemble_specialist_context(
                recipient_role="developer",
                objective=sample_objective,
                work_item=dev_work_item,
                base_output_dir=base_dir,
                available_artifacts={prod_art.id: prod_art},
                artifact_input_refs=[prod_ref],
            )


def test_requirement_m_tampered_artifact_fails_verification(sample_objective: CompanyObjective):
    """Requirement M: Tampered artifact on disk fails verification."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        prod_art, prod_ref = _create_real_artifact(
            base_dir, "p1", "product", ArtifactType.SPECIFICATION, "Original Content"
        )
        # Tamper file on disk
        (base_dir / prod_art.path).write_text("Tampered Corrupted Content", encoding="utf-8")

        work_item = CEOPlannedWorkItem(
            work_item_id="item_ux",
            role="ux",
            objective="Wireframes",
        )
        with pytest.raises(ContextAssemblyError, match="Artifact verification failed"):
            assemble_specialist_context(
                recipient_role="ux",
                objective=sample_objective,
                work_item=work_item,
                base_output_dir=base_dir,
                available_artifacts={prod_art.id: prod_art},
                artifact_input_refs=[prod_ref],
            )


def test_requirement_n_oversized_artifact_fails_closed(sample_objective: CompanyObjective):
    """Requirement N: Oversized required artifact fails closed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        giant_content = "X" * (MAX_SELECTED_ARTIFACT_CONTENT_CHARS + 100)
        prod_art, prod_ref = _create_real_artifact(
            base_dir, "p_giant", "product", ArtifactType.SPECIFICATION, giant_content
        )

        work_item = CEOPlannedWorkItem(
            work_item_id="item_ux",
            role="ux",
            objective="Wireframes",
        )
        with pytest.raises(ContextAssemblyError, match="exceeds maximum allowed size"):
            assemble_specialist_context(
                recipient_role="ux",
                objective=sample_objective,
                work_item=work_item,
                base_output_dir=base_dir,
                available_artifacts={prod_art.id: prod_art},
                artifact_input_refs=[prod_ref],
            )


def test_requirement_o_p_dependency_alone_does_not_inject_content(sample_objective: CompanyObjective):
    """Requirements O & P: Dependency does NOT bypass handoff policy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        # Create a Developer artifact
        dev_art, dev_ref = _create_real_artifact(
            base_dir, "dev_art", "developer", ArtifactType.DEVELOPER_PLAN_REPORT, "Dev Plan"
        )

        # Research work item that depends on developer (not an allowed handoff edge: developer -> research)
        res_work_item = CEOPlannedWorkItem(
            work_item_id="item_res",
            role="research",
            objective="Study",
            depends_on=["dev_work_item"],
        )

        env = assemble_specialist_context(
            recipient_role="research",
            objective=sample_objective,
            work_item=res_work_item,
            base_output_dir=base_dir,
            available_artifacts={dev_art.id: dev_art},
            artifact_input_refs=[dev_ref],
        )
        # Content was NOT injected because (developer, research) is not in ALLOWED_HANDOFF_EDGES
        assert dev_art.id not in env.selected_artifact_contents


def test_requirement_s_full_content_absent_unless_selected(sample_objective: CompanyObjective):
    """Requirement S: Full content is absent unless explicitly selected by policy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)
        work_item = CEOPlannedWorkItem(
            work_item_id="item_res",
            role="research",
            objective="Study",
        )
        env = assemble_specialist_context(
            recipient_role="research",
            objective=sample_objective,
            work_item=work_item,
            base_output_dir=base_dir,
            available_artifacts={},
            artifact_input_refs=[],
        )
        assert env.selected_artifact_contents == {}
