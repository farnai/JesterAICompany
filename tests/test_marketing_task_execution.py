"""Tests for STEP 12: Marketing Agent Execution & Product Artifact Fan-Out.

Covers requirements A through Y:
A. marketing registered
B. valid Marketing task executes
C. runtime receives agent="marketing"
D. Marketing prompt contains canonical Task fields
E. valid raw JSON parses
F. fenced JSON parses
G. malformed result fails
H. wrong schema fails
I. successful Marketing Task completes
J. validated result stored in Task.result.details
K. marketing_report.md produced
L. artifact SHA matches exact bytes
M. Product artifact attaches to Marketing
N. Product -> Marketing lineage preserved
O. UX -> Marketing rejected
P. Marketing -> UX rejected
Q. Research -> Marketing rejected
R. tampered Product artifact prevents Marketing execution
S. missing artifact prevents Marketing execution
T. oversized artifact prevents Marketing execution
U. one Product Artifact can be attached to BOTH UX and Marketing
V. both refs contain same artifact_id/run_id/hash
W. Product Artifact remains byte-identical after both consumers
X. UX and Marketing outputs have independent paths/hashes
Y. existing Research/Product/UX behavior remains green
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
from jester_ai_company.materializer import (
    MAX_INPUT_ARTIFACT_SIZE_BYTES,
    compute_sha256,
)
from jester_ai_company.product_result import ProductTaskResult
from jester_ai_company.proposal import REGISTERED_SPECIALIST_ROLES
from jester_ai_company.registry import RECOGNIZED_AGENTS
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService
from jester_ai_company.marketing_result import (
    ChannelTactic,
    KeyMessage,
    MarketingResultError,
    MarketingResultParseError,
    MarketingResultValidationError,
    MarketingTaskResult,
    TargetAudience,
    build_marketing_execution_prompt,
    extract_marketing_json_text,
    parse_and_validate_marketing_result,
)
from jester_ai_company.ux_result import UXTaskResult


SAMPLE_MARKETING_RESULT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Marketing positioning and messaging strategy for developer onboarding.",
    "positioning": "The deterministic, multi-agent AI company infrastructure for verifiable software engineering.",
    "target_audiences": [
        {
            "name": "AI Software Engineers & Contributors",
            "description": "Developers building and integrating multi-agent AI workflows locally.",
            "pain_points": [
                "Unpredictable hallucinated agent outputs",
                "Lack of deterministic, verifiable handoff contracts between specialist agents",
            ],
        }
    ],
    "key_messages": [
        {
            "audience": "AI Software Engineers & Contributors",
            "core_message": "Verifiable multi-agent workflows with strict contracts, SHA-256 provenance, and zero hallucinations.",
        }
    ],
    "channels_or_tactics": [
        {
            "channel": "GitHub Documentation & Quickstart",
            "tactic": "Add an interactive 3-step quickstart command with instant verification status output.",
        }
    ],
    "assumptions": [
        "Developers prefer CLI and terminal-first workflows over browser-only UIs.",
    ],
    "open_questions": [
        "Should we create a dedicated video demo of the four-specialist pipeline?",
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
# Role, Schema & Parsing Tests (A, C, D, E, F, G, H)
# -----------------------------------------------------------------------------

def test_marketing_registration():
    """Verifies A: Marketing agent is recognized in registry and specialist roles."""
    recognized_roles = [a["role"] for a in RECOGNIZED_AGENTS]
    assert "marketing" in recognized_roles
    assert "marketing" in REGISTERED_SPECIALIST_ROLES
    assert Path(".agents/agents/marketing/agent.md").exists()


def test_build_marketing_execution_prompt_and_agent_target():
    """Verifies C, D: Marketing prompt contains canonical task fields and targets 'marketing'."""
    task = Task(
        id="task_mkt_01",
        project_id="proj_1",
        title="Formulate Onboarding Messaging",
        goal="Develop positioning and key messages for onboarding",
        constraints=["Focus on AI developers", "Grounded in repo capabilities"],
        expected_output=["Marketing Report"],
    )
    prompt = build_marketing_execution_prompt(task)
    assert "Task ID: task_mkt_01" in prompt
    assert "Title: Formulate Onboarding Messaging" in prompt
    assert "Goal: Develop positioning and key messages for onboarding" in prompt
    assert "- Focus on AI developers" in prompt
    assert "- Grounded in repo capabilities" in prompt
    assert "- Marketing Report" in prompt
    assert "STRUCTURED MARKETING EXECUTION MODE" in prompt


def test_extract_and_parse_valid_marketing_json():
    """Verifies E, F: Raw and fenced JSON parse into validated MarketingTaskResult."""
    # E: Raw JSON
    raw_json = json.dumps(SAMPLE_MARKETING_RESULT)
    res = parse_and_validate_marketing_result(raw_json)
    assert isinstance(res, MarketingTaskResult)
    assert res.schema_version == "1.0"
    assert res.status == "completed"
    assert "verifiable software engineering" in res.positioning
    assert len(res.target_audiences) == 1
    assert res.target_audiences[0].name == "AI Software Engineers & Contributors"
    assert len(res.target_audiences[0].pain_points) == 2
    assert len(res.key_messages) == 1
    assert len(res.channels_or_tactics) == 1
    assert len(res.assumptions) == 1
    assert len(res.open_questions) == 1

    # F: Markdown-fenced JSON
    fenced_json = f"```json\n{raw_json}\n```"
    res_fenced = parse_and_validate_marketing_result(fenced_json)
    assert res_fenced.summary == res.summary
    assert res_fenced.positioning == res.positioning


def test_malformed_and_wrong_schema_marketing_result_fails():
    """Verifies G, H: Malformed JSON and schema violations fail safely."""
    # G: Malformed JSON
    with pytest.raises(MarketingResultParseError):
        parse_and_validate_marketing_result("{not valid json")

    # H: Wrong schema
    bad_schema = dict(SAMPLE_MARKETING_RESULT)
    bad_schema["schema_version"] = "2.0"
    with pytest.raises(MarketingResultValidationError) as exc:
        parse_and_validate_marketing_result(json.dumps(bad_schema))
    assert "Invalid schema_version" in str(exc.value)

    # Empty summary
    bad_summary = dict(SAMPLE_MARKETING_RESULT)
    bad_summary["summary"] = "   "
    with pytest.raises(MarketingResultValidationError) as exc:
        parse_and_validate_marketing_result(json.dumps(bad_summary))
    assert "summary" in str(exc.value)

    # Empty positioning
    bad_pos = dict(SAMPLE_MARKETING_RESULT)
    bad_pos["positioning"] = ""
    with pytest.raises(MarketingResultValidationError) as exc:
        parse_and_validate_marketing_result(json.dumps(bad_pos))
    assert "positioning" in str(exc.value)


# -----------------------------------------------------------------------------
# Marketing Task Execution Lifecycle & Materialization (B, I, J, K, L)
# -----------------------------------------------------------------------------

def test_execute_marketing_task_lifecycle_and_materialization():
    """Verifies B, I, J, K, L: Valid Marketing task executes, completes, populates details, and creates report artifact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({"marketing": json.dumps(SAMPLE_MARKETING_RESULT)})
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Formulate Quickstart Marketing",
            goal="Define messaging and positioning",
            required_roles=["marketing"],
            expected_output=["Marketing Report"],
        )

        run = service.execute_marketing_task(task.id)

        # I: Task completes, run succeeds
        assert run.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value

        # J: TaskResult.details contains validated Marketing result
        assert task.result is not None
        assert task.result.details["schema_version"] == "1.0"
        assert "verifiable software engineering" in task.result.details["positioning"]
        assert task.result.details["target_audiences"][0]["name"] == "AI Software Engineers & Contributors"

        # K: Exactly one marketing_report.md artifact created
        assert len(run.artifacts) == 1
        art = run.artifacts[0]
        assert art.name == "marketing_report.md"
        assert art.producer_role == "marketing"
        assert art.run_id == run.id

        # L: Hash matches exact bytes
        art_path = Path(tmp_dir) / art.path
        assert art_path.exists()
        raw_bytes = art_path.read_bytes()
        assert art.sha256 == hashlib.sha256(raw_bytes).hexdigest()

        # Content verification
        content = raw_bytes.decode("utf-8")
        assert "# Marketing Report: Formulate Quickstart Marketing" in content
        assert "## Core Positioning" in content
        assert "verifiable software engineering" in content
        assert "## Target Audiences" in content
        assert "AI Software Engineers & Contributors" in content
        assert "## Key Messages" in content
        assert "## Channels & Tactics" in content
        assert "## Assumptions & Uncertainties" in content


# -----------------------------------------------------------------------------
# Handoff Policy & Input Attachment Tests (M, N, O, P, Q)
# -----------------------------------------------------------------------------

def test_product_artifact_attaches_to_marketing_task():
    """Verifies M, N: Product artifact attaches to Marketing task and lineage is preserved."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({"product": json.dumps(SAMPLE_PRODUCT_RESULT)})
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # Create & execute Product task
        p_task = service.create_task(
            project_id=proj.id,
            title="Product PRD",
            goal="Define PRD",
            required_roles=["product"],
        )
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]

        # Create Marketing task
        mkt_task = service.create_task(
            project_id=proj.id,
            title="Marketing Messaging",
            goal="Define Messaging",
            required_roles=["marketing"],
        )

        # M: Attach Product artifact to Marketing task
        ref = service.attach_input_artifact(mkt_task.id, p_art.id)
        assert isinstance(ref, ArtifactInputRef)
        assert ref.artifact_id == p_art.id
        assert ref.producer_role == "product"
        assert ref.sha256 == p_art.sha256

        # N: Lineage preserved
        assert len(mkt_task.input_artifacts) == 1
        assert mkt_task.input_artifacts[0] == ref


def test_marketing_handoff_policy_rejections():
    """Verifies O, P, Q: Disallowed handoff edges are rejected deterministically."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "research": json.dumps(SAMPLE_RESEARCH_RESULT),
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
            "marketing": json.dumps(SAMPLE_MARKETING_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # 1. Research task
        r_task = service.create_task(project_id=proj.id, title="R", goal="R", required_roles=["research"])
        r_run = service.execute_research_task(r_task.id)
        r_art = r_run.artifacts[0]

        # 2. UX task
        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        u_run = service.execute_ux_task(u_task.id)
        u_art = u_run.artifacts[0]

        # 3. Marketing task
        m_task = service.create_task(project_id=proj.id, title="M", goal="M", required_roles=["marketing"])
        m_run = service.execute_marketing_task(m_task.id)
        m_art = m_run.artifacts[0]

        # Targets for rejection testing
        target_mkt = service.create_task(project_id=proj.id, title="Target MKT", goal="T", required_roles=["marketing"])
        target_ux = service.create_task(project_id=proj.id, title="Target UX", goal="T", required_roles=["ux"])

        # O: UX -> Marketing rejected
        with pytest.raises(HandoffPolicyError) as exc_o:
            service.attach_input_artifact(target_mkt.id, u_art.id)
        assert "not permitted" in str(exc_o.value)

        # P: Marketing -> UX rejected
        with pytest.raises(HandoffPolicyError) as exc_p:
            service.attach_input_artifact(target_ux.id, m_art.id)
        assert "not permitted" in str(exc_p.value)

        # Q: Research -> Marketing rejected
        with pytest.raises(HandoffPolicyError) as exc_q:
            service.attach_input_artifact(target_mkt.id, r_art.id)
        assert "not permitted" in str(exc_q.value)


# -----------------------------------------------------------------------------
# Preflight & Tamper Verification (R, S, T)
# -----------------------------------------------------------------------------

def test_tampered_missing_and_oversized_product_artifact_prevents_marketing_execution():
    """Verifies R, S, T: Tampered, missing, or oversized Product artifact fails preflight safely."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "marketing": json.dumps(SAMPLE_MARKETING_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]
        p_file = Path(tmp_dir) / p_art.path

        # R: Tampered Product artifact
        p_file.write_text("Tampered product text!", encoding="utf-8")
        mkt_task_r = service.create_task(project_id=proj.id, title="MKT_R", goal="MKT", required_roles=["marketing"])
        service.attach_input_artifact(mkt_task_r.id, p_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_r:
            service.execute_marketing_task(mkt_task_r.id)
        assert "integrity mismatch" in str(exc_r.value).lower()
        assert mkt_task_r.status == TaskStatus.PENDING.value
        assert len(mkt_task_r.runs) == 0

        # S: Missing Product artifact file
        p_file.unlink()
        mkt_task_s = service.create_task(project_id=proj.id, title="MKT_S", goal="MKT", required_roles=["marketing"])
        ref_s = ArtifactInputRef(artifact_id=p_art.id, run_id=p_art.run_id, sha256=p_art.sha256, producer_role="product")
        mkt_task_s.input_artifacts.append(ref_s)
        with pytest.raises(ArtifactVerificationError) as exc_s:
            service.execute_marketing_task(mkt_task_s.id)
        assert "file not found" in str(exc_s.value).lower()
        assert mkt_task_s.status == TaskStatus.PENDING.value
        assert len(mkt_task_s.runs) == 0

        # T: Oversized Product artifact
        huge_text = "Z" * (MAX_INPUT_ARTIFACT_SIZE_BYTES + 50)
        p_file.write_text(huge_text, encoding="utf-8")
        p_art.sha256 = hashlib.sha256(huge_text.encode("utf-8")).hexdigest()
        mkt_task_t = service.create_task(project_id=proj.id, title="MKT_T", goal="MKT", required_roles=["marketing"])
        service.attach_input_artifact(mkt_task_t.id, p_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_t:
            service.execute_marketing_task(mkt_task_t.id)
        assert "exceeds maximum allowed size" in str(exc_t.value).lower()
        assert mkt_task_t.status == TaskStatus.PENDING.value
        assert len(mkt_task_t.runs) == 0


# -----------------------------------------------------------------------------
# Fan-Out Invariant, Byte Identity & Independence (U, V, W, X, Y)
# -----------------------------------------------------------------------------

def test_product_artifact_fan_out_to_ux_and_marketing():
    """Verifies U, V, W, X: One Product Artifact attaches to BOTH UX and Marketing independently.

    - Both input refs point to exact same artifact_id/run_id/sha256.
    - Product Artifact remains byte-identical after BOTH consumers execute.
    - UX and Marketing produce independent output artifacts with distinct paths/hashes.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
            "marketing": json.dumps(SAMPLE_MARKETING_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # Step 1: Execute Product task
        p_task = service.create_task(project_id=proj.id, title="P Task", goal="Goal P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]
        p_file = Path(tmp_dir) / p_art.path

        p_bytes_initial = p_file.read_bytes()
        p_sha_initial = p_art.sha256

        # Step 2: Create UX and Marketing tasks
        ux_task = service.create_task(project_id=proj.id, title="UX Task", goal="Goal UX", required_roles=["ux"])
        mkt_task = service.create_task(project_id=proj.id, title="MKT Task", goal="Goal MKT", required_roles=["marketing"])

        # U: Attach THE SAME Product artifact to BOTH downstream tasks
        ref_ux = service.attach_input_artifact(ux_task.id, p_art.id)
        ref_mkt = service.attach_input_artifact(mkt_task.id, p_art.id)

        # V: Both refs contain the same artifact_id, run_id, and hash
        assert ref_ux.artifact_id == p_art.id
        assert ref_mkt.artifact_id == p_art.id
        assert ref_ux.run_id == p_run.id
        assert ref_mkt.run_id == p_run.id
        assert ref_ux.sha256 == p_art.sha256
        assert ref_mkt.sha256 == p_art.sha256

        # Step 3: Execute UX consumer
        ux_run = service.execute_ux_task(ux_task.id)
        assert ux_run.status == RunStatus.SUCCESS.value
        assert ux_task.status == TaskStatus.COMPLETED.value

        # Check Product artifact byte identity after UX execution
        p_bytes_after_ux = p_file.read_bytes()
        assert p_bytes_after_ux == p_bytes_initial
        assert hashlib.sha256(p_bytes_after_ux).hexdigest() == p_sha_initial

        # Step 4: Execute Marketing consumer
        mkt_run = service.execute_marketing_task(mkt_task.id)
        assert mkt_run.status == RunStatus.SUCCESS.value
        assert mkt_task.status == TaskStatus.COMPLETED.value

        # W: Product artifact bytes remain 100% identical after BOTH consumers execute
        p_bytes_after_mkt = p_file.read_bytes()
        assert p_bytes_after_mkt == p_bytes_initial
        assert hashlib.sha256(p_bytes_after_mkt).hexdigest() == p_sha_initial

        # X: UX and Marketing outputs have independent paths and hashes
        ux_art = ux_run.artifacts[0]
        mkt_art = mkt_run.artifacts[0]

        assert ux_art.name == "ux_report.md"
        assert mkt_art.name == "marketing_report.md"
        assert ux_art.producer_role == "ux"
        assert mkt_art.producer_role == "marketing"

        assert ux_art.path != mkt_art.path
        assert ux_art.path != p_art.path
        assert mkt_art.path != p_art.path

        assert ux_art.sha256 != mkt_art.sha256
        assert ux_art.sha256 != p_art.sha256
        assert mkt_art.sha256 != p_art.sha256

        ux_disk_file = Path(tmp_dir) / ux_art.path
        mkt_disk_file = Path(tmp_dir) / mkt_art.path

        assert ux_disk_file.exists()
        assert mkt_disk_file.exists()
        assert compute_sha256(ux_disk_file.read_text(encoding="utf-8")) == ux_art.sha256
        assert compute_sha256(mkt_disk_file.read_text(encoding="utf-8")) == mkt_art.sha256
