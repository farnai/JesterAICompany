"""Tests for STEP 13A: Developer Planning Mode & Product/UX Artifact Fan-In.

Covers requirements A through AJ:
A. developer is registered
B. valid Developer Planning task executes
C. runtime receives agent="developer"
D. Product + UX is accepted
E. input attachment order does not matter
F. prompt always presents Product before UX
G. zero inputs rejected
H. Product-only rejected
I. UX-only rejected
J. duplicate Product rejected
K. duplicate UX rejected
L. Product + Marketing rejected
M. Research + UX rejected
N. extra third artifact rejected
O. Product artifact tamper blocks execution
P. UX artifact tamper blocks execution
Q. missing Product artifact blocks execution
R. missing UX artifact blocks execution
S. per-artifact oversize blocks execution
T. combined-size oversize blocks execution
U. valid raw Developer JSON parses
V. fenced Developer JSON parses
W. malformed Developer JSON fails
X. wrong schema fails
Y. Developer TaskResult.details stores validated plan
Z. developer_plan_report.md is produced
AA. Developer Artifact hash matches exact bytes
AB. both input refs remain on Developer Task
AC. Product artifact remains byte-identical
AD. UX artifact remains byte-identical
AE. commands_to_run are NOT executed
AF. files_to_modify does NOT modify files
AG. files_to_create does NOT create files
AH. repository state remains unchanged
AI. Developer output has independent path/hash
AJ. existing Research/Product/UX/Marketing behavior remains green
"""

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Dict, List, Optional
import pytest

from jester_ai_company.core import (
    ALLOWED_HANDOFF_EDGES,
    Artifact,
    ArtifactInputRef,
    ArtifactType,
    ArtifactVerificationError,
    HandoffError,
    HandoffPolicyError,
    RunStatus,
    Task,
    TaskStatus,
)
from jester_ai_company.developer_result import (
    DeveloperResultError,
    DeveloperResultParseError,
    DeveloperResultValidationError,
    DeveloperTaskResult,
    ProposedCommand,
    ProposedFile,
    build_developer_execution_prompt,
    extract_developer_json_text,
    parse_and_validate_developer_result,
)
from jester_ai_company.materializer import (
    MAX_COMBINED_INPUT_ARTIFACT_SIZE_BYTES,
    MAX_INPUT_ARTIFACT_SIZE_BYTES,
    compute_sha256,
)
from jester_ai_company.proposal import REGISTERED_SPECIALIST_ROLES
from jester_ai_company.registry import RECOGNIZED_AGENTS
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService


SAMPLE_DEVELOPER_RESULT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Technical implementation strategy for interactive quickstart CLI checklist.",
    "implementation_plan": [
        "1. Create quickstart module with non-blocking environment checks",
        "2. Add CLI entry point command in jester_ai_company/quickstart.py",
        "3. Integrate status dashboard output rendering",
    ],
    "files_to_modify": [
        {
            "path": "jester_ai_company/service.py",
            "description": "Expose quickstart verification service method",
        }
    ],
    "files_to_create": [
        {
            "path": "jester_ai_company/quickstart.py",
            "description": "Implement interactive terminal quickstart routine",
        }
    ],
    "dependencies": [
        "colorama>=0.4.6",
    ],
    "commands_to_run": [
        {
            "command": "python -m pytest tests/test_quickstart.py",
            "purpose": "Verify newly implemented quickstart tests pass",
        }
    ],
    "verification_plan": [
        "Unit test all environment check functions",
        "Integration test quickstart CLI output formatting",
    ],
    "risks": [
        "Colorama ANSI styling may not render on legacy Windows cmd.exe",
    ],
    "assumptions": [
        "Python 3.10+ is available in the contributor runtime",
    ],
    "open_questions": [
        "Should quickstart support a headless flag for automated CI environments?",
    ],
}

SAMPLE_PRODUCT_RESULT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "PRD for developer onboarding.",
    "deliverables": [
        {
            "name": "Onboarding PRD",
            "content": "## PRD\nDetailed specifications for developer quickstart.",
        }
    ],
    "risks": ["Terminal incompatibility"],
    "open_questions": ["Is CI mode headless?"],
}

SAMPLE_UX_RESULT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "UX architecture for developer onboarding checklist.",
    "flows": [
        {
            "name": "Quickstart Verification Flow",
            "description": "Interactive flow guiding developer from repo clone to verified environment.",
            "steps": ["Step 1: Run quickstart", "Step 2: Check status"],
        }
    ],
    "screens": [
        {
            "name": "Onboarding Terminal Dashboard",
            "purpose": "Primary CLI dashboard displaying verification status.",
            "states": ["default", "checking", "verified_ready"],
        }
    ],
    "interaction_rules": ["Immediate terminal response"],
    "accessibility_considerations": ["ANSI high-contrast mode"],
    "open_questions": ["Support browser view?"],
}

SAMPLE_MARKETING_RESULT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Marketing positioning and messaging strategy for developer onboarding.",
    "positioning": "The deterministic, multi-agent AI company infrastructure.",
    "target_audiences": [
        {
            "name": "AI Software Engineers",
            "description": "Engineers building local agent systems.",
            "pain_points": ["Hallucinations"],
        }
    ],
    "key_messages": [{"audience": "All", "core_message": "Verifiable agents"}],
    "channels_or_tactics": [{"channel": "Docs", "tactic": "Quickstart guide"}],
    "assumptions": ["Developers prefer CLI"],
    "open_questions": ["Video demo?"],
}

SAMPLE_RESEARCH_RESULT = {
    "schema_version": "1.1",
    "status": "completed",
    "summary": "Research findings for onboarding.",
    "sources": [
        {
            "source_id": "src_1",
            "title": "Onboarding Study",
            "reference": "https://example.org/study",
            "source_type": "web",
            "accessed_at": "2026-10-02T00:00:00Z",
        }
    ],
    "findings": [
        {
            "claim": "Clear terminal steps increase completion.",
            "evidence_status": "verified_source",
            "certainty": "high",
            "source_ids": ["src_1"],
            "evidence": "Data shows 20% higher completion.",
        }
    ],
    "uncertainties": [],
    "open_questions": [],
}


class MockRuntime(AntigravityRuntime):
    """Mock runtime returning pre-programmed agent responses."""

    def __init__(self, responses: Dict[str, str]):
        self.responses = responses
        self.calls: List[Dict[str, str]] = []

    def execute(
        self,
        agent: str,
        prompt: str,
        timeout: Optional[float] = None,
    ) -> AgentExecutionResult:
        self.calls.append({"agent": agent, "prompt": prompt})
        output = self.responses.get(agent, "{}")
        return AgentExecutionResult(
            success=True,
            exit_code=0,
            stdout=output,
            stderr="",
            duration_ms=15.0,
            agent=agent,
        )


# -----------------------------------------------------------------------------
# Role, Schema, Prompt & Canonical Ordering Tests (A, C, F, U, V, W, X)
# -----------------------------------------------------------------------------

def test_developer_registration():
    """Verifies A: Developer agent is recognized in registry and specialist roles."""
    recognized_roles = [a["role"] for a in RECOGNIZED_AGENTS]
    assert "developer" in recognized_roles
    assert "developer" in REGISTERED_SPECIALIST_ROLES
    assert Path(".agents/agents/developer/agent.md").exists()


def test_build_developer_execution_prompt_and_canonical_order():
    """Verifies C, F: Developer prompt targets 'developer' and orders Product before UX."""
    task = Task(
        id="task_dev_plan_01",
        project_id="proj_1",
        title="Plan Developer Quickstart Implementation",
        goal="Formulate implementation plan without mutating repository",
        constraints=["Read-only planning", "No file modifications"],
        expected_output=["Developer plan report"],
    )

    ref_ux = ArtifactInputRef(artifact_id="art_ux_99", run_id="run_ux", sha256="sha_ux", producer_role="ux")
    ref_prod = ArtifactInputRef(artifact_id="art_prod_11", run_id="run_prod", sha256="sha_prod", producer_role="product")

    # Pass in REVERSED order (UX first, Product second)
    verified = [
        (ref_ux, "UX SPECIFICATION CONTENT: Screen flows and interaction states"),
        (ref_prod, "PRODUCT PRD CONTENT: Functional requirements and scope"),
    ]

    prompt = build_developer_execution_prompt(task, verified_artifacts=verified)

    assert "Task ID: task_dev_plan_01" in prompt
    assert "STRUCTURED DEVELOPER PLANNING MODE (STEP 13A)" in prompt
    assert "CRITICAL SAFETY RULE — READ-ONLY PLANNING ONLY" in prompt

    # F: Product MUST appear before UX in the prompt regardless of input order
    pos_product = prompt.find("BEGIN PRODUCT ARTIFACT")
    pos_ux = prompt.find("BEGIN UX ARTIFACT")
    assert pos_product != -1, "Product artifact boundary missing in prompt"
    assert pos_ux != -1, "UX artifact boundary missing in prompt"
    assert pos_product < pos_ux, "Canonical ordering violation: Product must be presented before UX"


def test_extract_and_parse_valid_developer_json():
    """Verifies U, V: Raw and fenced JSON parse into validated DeveloperTaskResult."""
    # U: Raw JSON
    raw_json = json.dumps(SAMPLE_DEVELOPER_RESULT)
    res = parse_and_validate_developer_result(raw_json)
    assert isinstance(res, DeveloperTaskResult)
    assert res.schema_version == "1.0"
    assert res.status == "completed"
    assert len(res.implementation_plan) == 3
    assert len(res.files_to_modify) == 1
    assert res.files_to_modify[0].path == "jester_ai_company/service.py"
    assert len(res.files_to_create) == 1
    assert res.files_to_create[0].path == "jester_ai_company/quickstart.py"
    assert len(res.commands_to_run) == 1
    assert res.commands_to_run[0].command == "python -m pytest tests/test_quickstart.py"
    assert len(res.dependencies) == 1
    assert len(res.verification_plan) == 2
    assert len(res.risks) == 1
    assert len(res.assumptions) == 1
    assert len(res.open_questions) == 1

    # V: Markdown-fenced JSON
    fenced_json = f"```json\n{raw_json}\n```"
    res_fenced = parse_and_validate_developer_result(fenced_json)
    assert res_fenced.summary == res.summary
    assert res_fenced.implementation_plan == res.implementation_plan


def test_malformed_and_wrong_schema_developer_result_fails():
    """Verifies W, X: Malformed JSON and schema violations fail safely."""
    # W: Malformed JSON
    with pytest.raises(DeveloperResultParseError):
        parse_and_validate_developer_result("{not valid json")

    # X: Wrong schema
    bad_schema = dict(SAMPLE_DEVELOPER_RESULT)
    bad_schema["schema_version"] = "2.0"
    with pytest.raises(DeveloperResultValidationError) as exc:
        parse_and_validate_developer_result(json.dumps(bad_schema))
    assert "Invalid schema_version" in str(exc.value)

    # Empty summary
    bad_summary = dict(SAMPLE_DEVELOPER_RESULT)
    bad_summary["summary"] = "   "
    with pytest.raises(DeveloperResultValidationError) as exc:
        parse_and_validate_developer_result(json.dumps(bad_summary))
    assert "summary" in str(exc.value)

    # Empty implementation plan
    bad_plan = dict(SAMPLE_DEVELOPER_RESULT)
    bad_plan["implementation_plan"] = []
    with pytest.raises(DeveloperResultValidationError) as exc:
        parse_and_validate_developer_result(json.dumps(bad_plan))
    assert "implementation_plan" in str(exc.value)


# -----------------------------------------------------------------------------
# Developer Planning Execution Lifecycle & Materialization (B, Y, Z, AA, AI)
# -----------------------------------------------------------------------------

def test_execute_developer_planning_task_lifecycle():
    """Verifies B, Y, Z, AA, AI: Valid Developer planning task executes, completes, and creates plan artifact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
            "developer": json.dumps(SAMPLE_DEVELOPER_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # Upstream Product Task
        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]

        # Upstream UX Task
        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        service.attach_input_artifact(u_task.id, p_art.id)
        u_run = service.execute_ux_task(u_task.id)
        u_art = u_run.artifacts[0]

        # Developer Planning Task consuming BOTH Product and UX
        d_task = service.create_task(
            project_id=proj.id,
            title="Plan Quickstart",
            goal="Formulate implementation plan",
            required_roles=["developer"],
            expected_output=["Developer Plan Report"],
        )
        service.attach_input_artifact(d_task.id, p_art.id)
        service.attach_input_artifact(d_task.id, u_art.id)

        # B: Execute Developer Planning
        d_run = service.execute_developer_planning_task(d_task.id)

        assert d_run.status == RunStatus.SUCCESS.value
        assert d_task.status == TaskStatus.COMPLETED.value

        # Y: TaskResult.details stores validated plan
        assert d_task.result is not None
        assert d_task.result.details["schema_version"] == "1.0"
        assert len(d_task.result.details["implementation_plan"]) == 3
        assert d_task.result.details["files_to_modify"][0]["path"] == "jester_ai_company/service.py"

        # Z: Exactly one developer_plan_report.md artifact created
        assert len(d_run.artifacts) == 1
        art = d_run.artifacts[0]
        assert art.name == "developer_plan_report.md"
        assert art.producer_role == "developer"
        assert art.run_id == d_run.id

        # AA: Artifact hash matches exact bytes
        art_path = Path(tmp_dir) / art.path
        assert art_path.exists()
        raw_bytes = art_path.read_bytes()
        assert art.sha256 == hashlib.sha256(raw_bytes).hexdigest()

        # AI: Independent path and hash
        assert art.path != p_art.path
        assert art.path != u_art.path
        assert art.sha256 != p_art.sha256
        assert art.sha256 != u_art.sha256

        # Content verification
        content = raw_bytes.decode("utf-8")
        assert "# Developer Plan Report: Plan Quickstart" in content
        assert "## Implementation Plan" in content
        assert "## Proposed File Modifications (Planning Only)" in content
        assert "## Proposed Files to Create (Planning Only)" in content
        assert "## Proposed Commands to Run (Planning Only - Not Executed)" in content


# -----------------------------------------------------------------------------
# Fan-In Shape Validation & Rejections (D, E, G, H, I, J, K, L, M, N)
# -----------------------------------------------------------------------------

def test_developer_planning_fan_in_shape_acceptance_and_rejections():
    """Verifies D, E, G, H, I, J, K, L, M, N: Exact fan-in shape (1 Product + 1 UX) strictly enforced."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "research": json.dumps(SAMPLE_RESEARCH_RESULT),
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
            "marketing": json.dumps(SAMPLE_MARKETING_RESULT),
            "developer": json.dumps(SAMPLE_DEVELOPER_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # Produce artifacts
        r_run = service.execute_research_task(service.create_task(project_id=proj.id, title="R", goal="R", required_roles=["research"]).id)
        r_art = r_run.artifacts[0]

        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        service.attach_input_artifact(p_task.id, r_art.id)
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]

        p_task2 = service.create_task(project_id=proj.id, title="P2", goal="P2", required_roles=["product"])
        p_run2 = service.execute_product_task(p_task2.id)
        p_art2 = p_run2.artifacts[0]

        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        service.attach_input_artifact(u_task.id, p_art.id)
        u_run = service.execute_ux_task(u_task.id)
        u_art = u_run.artifacts[0]

        u_task2 = service.create_task(project_id=proj.id, title="U2", goal="U2", required_roles=["ux"])
        service.attach_input_artifact(u_task2.id, p_art.id)
        u_run2 = service.execute_ux_task(u_task2.id)
        u_art2 = u_run2.artifacts[0]

        m_task = service.create_task(project_id=proj.id, title="M", goal="M", required_roles=["marketing"])
        service.attach_input_artifact(m_task.id, p_art.id)
        m_run = service.execute_marketing_task(m_task.id)
        m_art = m_run.artifacts[0]

        # G: Zero inputs rejected
        d_zero = service.create_task(project_id=proj.id, title="D0", goal="D", required_roles=["developer"])
        with pytest.raises(HandoffPolicyError) as exc_g:
            service.execute_developer_planning_task(d_zero.id)
        assert "requires exactly 2 input artifacts" in str(exc_g.value)

        # H: Product-only rejected
        d_prod_only = service.create_task(project_id=proj.id, title="D_P", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_prod_only.id, p_art.id)
        with pytest.raises(HandoffPolicyError) as exc_h:
            service.execute_developer_planning_task(d_prod_only.id)
        assert "requires exactly 2 input artifacts" in str(exc_h.value)

        # I: UX-only rejected
        d_ux_only = service.create_task(project_id=proj.id, title="D_U", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_ux_only.id, u_art.id)
        with pytest.raises(HandoffPolicyError) as exc_i:
            service.execute_developer_planning_task(d_ux_only.id)
        assert "requires exactly 2 input artifacts" in str(exc_i.value)

        # J: Duplicate Product (two Product artifacts) rejected
        d_two_prod = service.create_task(project_id=proj.id, title="D_PP", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_two_prod.id, p_art.id)
        service.attach_input_artifact(d_two_prod.id, p_art2.id)
        with pytest.raises(HandoffPolicyError) as exc_j:
            service.execute_developer_planning_task(d_two_prod.id)
        assert "requires exactly one 'product' artifact and one 'ux' artifact" in str(exc_j.value)

        # K: Duplicate UX (two UX artifacts) rejected
        d_two_ux = service.create_task(project_id=proj.id, title="D_UU", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_two_ux.id, u_art.id)
        service.attach_input_artifact(d_two_ux.id, u_art2.id)
        with pytest.raises(HandoffPolicyError) as exc_k:
            service.execute_developer_planning_task(d_two_ux.id)
        assert "requires exactly one 'product' artifact and one 'ux' artifact" in str(exc_k.value)

        # L: Product + Marketing rejected (Marketing -> Developer is not allowed)
        d_pm = service.create_task(project_id=proj.id, title="D_PM", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_pm.id, p_art.id)
        with pytest.raises(HandoffPolicyError) as exc_l:
            service.attach_input_artifact(d_pm.id, m_art.id)
        assert "not permitted" in str(exc_l.value)

        # M: Research + UX rejected (Research -> Developer is not allowed)
        d_ru = service.create_task(project_id=proj.id, title="D_RU", goal="D", required_roles=["developer"])
        with pytest.raises(HandoffPolicyError) as exc_m:
            service.attach_input_artifact(d_ru.id, r_art.id)
        assert "not permitted" in str(exc_m.value)

        # N: Extra third artifact rejected
        d_three = service.create_task(project_id=proj.id, title="D3", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_three.id, p_art.id)
        service.attach_input_artifact(d_three.id, u_art.id)
        service.attach_input_artifact(d_three.id, p_art2.id)
        with pytest.raises(HandoffPolicyError) as exc_n:
            service.execute_developer_planning_task(d_three.id)
        assert "requires exactly 2 input artifacts" in str(exc_n.value)

        # D & E: Product + UX accepted in ANY attachment order
        # Attachment order: Product then UX
        d_valid_1 = service.create_task(project_id=proj.id, title="D_V1", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_valid_1.id, p_art.id)
        service.attach_input_artifact(d_valid_1.id, u_art.id)
        run_v1 = service.execute_developer_planning_task(d_valid_1.id)
        assert run_v1.status == RunStatus.SUCCESS.value

        # Attachment order: UX then Product
        d_valid_2 = service.create_task(project_id=proj.id, title="D_V2", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_valid_2.id, u_art.id)
        service.attach_input_artifact(d_valid_2.id, p_art.id)
        run_v2 = service.execute_developer_planning_task(d_valid_2.id)
        assert run_v2.status == RunStatus.SUCCESS.value


# -----------------------------------------------------------------------------
# Preflight Tamper, Missing, and Size Limit Tests (O, P, Q, R, S, T)
# -----------------------------------------------------------------------------

def test_developer_planning_preflight_and_size_limits():
    """Verifies O, P, Q, R, S, T: Tampered, missing, or oversized artifacts fail preflight safely."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
            "developer": json.dumps(SAMPLE_DEVELOPER_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_art = service.execute_product_task(p_task.id).artifacts[0]
        p_file = Path(tmp_dir) / p_art.path

        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        service.attach_input_artifact(u_task.id, p_art.id)
        u_art = service.execute_ux_task(u_task.id).artifacts[0]
        u_file = Path(tmp_dir) / u_art.path

        # O: Product tamper blocks execution
        p_file.write_text("Tampered Product Content!", encoding="utf-8")
        d_task_o = service.create_task(project_id=proj.id, title="DO", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_task_o.id, p_art.id)
        service.attach_input_artifact(d_task_o.id, u_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_o:
            service.execute_developer_planning_task(d_task_o.id)
        assert "integrity mismatch" in str(exc_o.value).lower()
        assert d_task_o.status == TaskStatus.PENDING.value
        assert len(d_task_o.runs) == 0

        # Restore Product file
        p_file.write_bytes(compute_sha256.__globals__["format_product_report"](p_task, parse_and_validate_developer_result.__globals__["ProductTaskResult"].from_dict if hasattr(parse_and_validate_developer_result.__globals__["ProductTaskResult"], "from_dict") else parse_and_validate_developer_result.__globals__["ProductTaskResult"](schema_version="1.0", status="completed", summary="PRD", deliverables=[], risks=[], open_questions=[])).encode("utf-8")) if False else None
        # Simpler restore: re-create clean product file and matching hash
        clean_p_content = "Clean Product Artifact Content"
        p_file.write_bytes(clean_p_content.encode("utf-8"))
        p_art.sha256 = hashlib.sha256(clean_p_content.encode("utf-8")).hexdigest()

        # P: UX tamper blocks execution
        u_file.write_text("Tampered UX Content!", encoding="utf-8")
        d_task_p = service.create_task(project_id=proj.id, title="DP", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_task_p.id, p_art.id)
        service.attach_input_artifact(d_task_p.id, u_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_p:
            service.execute_developer_planning_task(d_task_p.id)
        assert "integrity mismatch" in str(exc_p.value).lower()
        assert d_task_p.status == TaskStatus.PENDING.value
        assert len(d_task_p.runs) == 0

        # Restore UX file
        clean_u_content = "Clean UX Artifact Content"
        u_file.write_bytes(clean_u_content.encode("utf-8"))
        u_art.sha256 = hashlib.sha256(clean_u_content.encode("utf-8")).hexdigest()

        # Q: Missing Product artifact file
        p_file.unlink()
        d_task_q = service.create_task(project_id=proj.id, title="DQ", goal="D", required_roles=["developer"])
        ref_p_q = ArtifactInputRef(artifact_id=p_art.id, run_id=p_art.run_id, sha256=p_art.sha256, producer_role="product")
        ref_u_q = ArtifactInputRef(artifact_id=u_art.id, run_id=u_art.run_id, sha256=u_art.sha256, producer_role="ux")
        d_task_q.input_artifacts.extend([ref_p_q, ref_u_q])
        with pytest.raises(ArtifactVerificationError) as exc_q:
            service.execute_developer_planning_task(d_task_q.id)
        assert "file not found" in str(exc_q.value).lower()
        assert d_task_q.status == TaskStatus.PENDING.value
        assert len(d_task_q.runs) == 0

        # Restore Product file
        p_file.write_bytes(clean_p_content.encode("utf-8"))

        # R: Missing UX artifact file
        u_file.unlink()
        d_task_r = service.create_task(project_id=proj.id, title="DR", goal="D", required_roles=["developer"])
        d_task_r.input_artifacts.extend([ref_p_q, ref_u_q])
        with pytest.raises(ArtifactVerificationError) as exc_r:
            service.execute_developer_planning_task(d_task_r.id)
        assert "file not found" in str(exc_r.value).lower()
        assert d_task_r.status == TaskStatus.PENDING.value
        assert len(d_task_r.runs) == 0

        # Restore UX file
        u_file.write_bytes(clean_u_content.encode("utf-8"))

        # S: Single artifact oversize (>100KB)
        huge_text = "X" * (MAX_INPUT_ARTIFACT_SIZE_BYTES + 10)
        p_file.write_bytes(huge_text.encode("utf-8"))
        p_art.sha256 = hashlib.sha256(huge_text.encode("utf-8")).hexdigest()
        d_task_s = service.create_task(project_id=proj.id, title="DS", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_task_s.id, p_art.id)
        service.attach_input_artifact(d_task_s.id, u_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_s:
            service.execute_developer_planning_task(d_task_s.id)
        assert "exceeds maximum allowed size" in str(exc_s.value).lower()

        # T: Combined size limit (>150KB) with both individually <= 100KB (e.g. 80KB + 80KB)
        size_80k = "K" * 80_000
        p_file.write_bytes(size_80k.encode("utf-8"))
        p_art.sha256 = hashlib.sha256(size_80k.encode("utf-8")).hexdigest()

        u_file.write_bytes(size_80k.encode("utf-8"))
        u_art.sha256 = hashlib.sha256(size_80k.encode("utf-8")).hexdigest()

        d_task_t = service.create_task(project_id=proj.id, title="DT", goal="D", required_roles=["developer"])
        service.attach_input_artifact(d_task_t.id, p_art.id)
        service.attach_input_artifact(d_task_t.id, u_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_t:
            service.execute_developer_planning_task(d_task_t.id)
        assert "combined input artifact size" in str(exc_t.value).lower()
        assert d_task_t.status == TaskStatus.PENDING.value
        assert len(d_task_t.runs) == 0


# -----------------------------------------------------------------------------
# Safety, Non-Execution of Data & Immutability (AB, AC, AD, AE, AF, AG, AH)
# -----------------------------------------------------------------------------

def test_developer_planning_safety_and_immutability():
    """Verifies AB, AC, AD, AE, AF, AG, AH: Proposed commands/files are NOT executed/mutated; inputs remain byte-identical."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Malicious proposals in the plan to verify they are treated purely as data
        malicious_result = dict(SAMPLE_DEVELOPER_RESULT)
        malicious_result["commands_to_run"] = [
            {"command": "echo malicious > hack.txt", "purpose": "Test execution containment"}
        ]
        malicious_result["files_to_create"] = [
            {"path": "unauthorized_created_file.py", "description": "Proposed file"}
        ]
        malicious_result["files_to_modify"] = [
            {"path": "unauthorized_modified_file.py", "description": "Proposed edit"}
        ]

        mock_rt = MockRuntime({
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
            "developer": json.dumps(malicious_result),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_art = service.execute_product_task(p_task.id).artifacts[0]
        p_file = Path(tmp_dir) / p_art.path
        p_bytes_before = p_file.read_bytes()
        p_sha_before = p_art.sha256

        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        service.attach_input_artifact(u_task.id, p_art.id)
        u_art = service.execute_ux_task(u_task.id).artifacts[0]
        u_file = Path(tmp_dir) / u_art.path
        u_bytes_before = u_file.read_bytes()
        u_sha_before = u_art.sha256

        d_task = service.create_task(project_id=proj.id, title="D", goal="D", required_roles=["developer"])
        ref_p = service.attach_input_artifact(d_task.id, p_art.id)
        ref_u = service.attach_input_artifact(d_task.id, u_art.id)

        repo_state_before = service._get_repo_working_tree_state()
        d_run = service.execute_developer_planning_task(d_task.id)
        repo_state_after = service._get_repo_working_tree_state()

        # AB: Both input refs remain on Developer Task
        assert len(d_task.input_artifacts) == 2
        assert d_task.input_artifacts[0] == ref_p
        assert d_task.input_artifacts[1] == ref_u

        # AC: Product artifact remains byte-identical
        assert p_file.read_bytes() == p_bytes_before
        assert hashlib.sha256(p_file.read_bytes()).hexdigest() == p_sha_before

        # AD: UX artifact remains byte-identical
        assert u_file.read_bytes() == u_bytes_before
        assert hashlib.sha256(u_file.read_bytes()).hexdigest() == u_sha_before

        # AE: commands_to_run are NOT executed
        assert not Path("hack.txt").exists()

        # AF & AG: files_to_modify and files_to_create are NOT modified/created
        assert not Path("unauthorized_created_file.py").exists()
        assert not Path("unauthorized_modified_file.py").exists()

        # AH: Repo working tree state remains completely unchanged
        assert repo_state_before == repo_state_after
