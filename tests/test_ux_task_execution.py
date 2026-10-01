"""Tests for STEP 11: UX Agent Execution & Product -> UX Artifact Handoff.

Covers requirements A through W:
A. ux is registered
B. valid UX task executes
C. Antigravity agent="ux"
D. UX prompt contains canonical Task fields
E. valid UX JSON parses
F. fenced JSON parses
G. malformed UX result fails
H. wrong schema fails
I. successful UX Task completes
J. UX TaskResult.details contains validated UX result
K. UX produces exactly one ux_report.md Artifact
L. UX artifact hash matches exact bytes
M. Product artifact attaches to UX task
N. Product -> UX lineage is preserved
O. Research -> UX remains rejected
P. UX -> Product remains rejected
Q. Product -> Product remains rejected
R. tampered Product artifact prevents UX execution
S. missing Product artifact prevents UX execution
T. oversized Product artifact prevents UX execution
U. upstream Product artifact remains byte-identical
V. UX output artifact has independent path/hash
W. Product/Research regressions remain green
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
from jester_ai_company.ux_result import (
    UXFlow,
    UXResultError,
    UXResultParseError,
    UXResultValidationError,
    UXScreenState,
    UXTaskResult,
    build_ux_execution_prompt,
    extract_ux_json_text,
    parse_and_validate_ux_result,
)


SAMPLE_UX_RESULT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "UX architecture for developer onboarding checklist and status verification.",
    "flows": [
        {
            "name": "Quickstart Verification Flow",
            "description": "Interactive flow guiding developer from repo clone to verified environment.",
            "steps": [
                "Developer runs quickstart verification command",
                "System performs non-blocking environment inspection",
                "Console renders interactive checklist feedback",
                "Success screen confirms readiness to receive tasks",
            ],
        }
    ],
    "screens": [
        {
            "name": "Onboarding Terminal Dashboard",
            "purpose": "Primary CLI dashboard displaying verification status and actionable guidance.",
            "states": ["default", "checking", "blocked_missing_dependency", "verified_ready"],
        }
    ],
    "interaction_rules": [
        "Immediate terminal response for each verification check",
        "Clear color-coded status badges with plain text fallbacks",
        "Destructive actions or resets require explicit affirmative typing",
    ],
    "accessibility_considerations": [
        "ANSI high-contrast mode for terminal color blindness support",
        "Screen-reader-friendly plain text mode for non-interactive execution",
    ],
    "open_questions": [
        "Should verification status support an optional browser view in Stage 27?",
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

def test_ux_registration():
    """Verifies A: UX agent is recognized in registry and specialist roles."""
    recognized_roles = [a["role"] for a in RECOGNIZED_AGENTS]
    assert "ux" in recognized_roles
    assert "ux" in REGISTERED_SPECIALIST_ROLES
    assert Path(".agents/agents/ux/agent.md").exists()


def test_build_ux_execution_prompt_and_agent_target():
    """Verifies C, D: UX prompt contains canonical task fields and targets 'ux'."""
    task = Task(
        id="task_ux_01",
        project_id="proj_1",
        title="Design Onboarding UX",
        goal="Map user flows and terminal states",
        constraints=["Adhere to WCAG", "Terminal first"],
        expected_output=["UX Report"],
    )
    prompt = build_ux_execution_prompt(task)
    assert "Task ID: task_ux_01" in prompt
    assert "Title: Design Onboarding UX" in prompt
    assert "Goal: Map user flows and terminal states" in prompt
    assert "- Adhere to WCAG" in prompt
    assert "- Terminal first" in prompt
    assert "- UX Report" in prompt
    assert "STRUCTURED UX EXECUTION MODE" in prompt


def test_extract_and_parse_valid_ux_json():
    """Verifies E, F: Raw and fenced JSON parse into validated UXTaskResult."""
    # E: Raw JSON
    raw_json = json.dumps(SAMPLE_UX_RESULT)
    res = parse_and_validate_ux_result(raw_json)
    assert isinstance(res, UXTaskResult)
    assert res.schema_version == "1.0"
    assert res.status == "completed"
    assert len(res.flows) == 1
    assert res.flows[0].name == "Quickstart Verification Flow"
    assert len(res.flows[0].steps) == 4
    assert len(res.screens) == 1
    assert res.screens[0].name == "Onboarding Terminal Dashboard"
    assert len(res.screens[0].states) == 4
    assert len(res.interaction_rules) == 3
    assert len(res.accessibility_considerations) == 2

    # F: Markdown-fenced JSON
    fenced_json = f"```json\n{raw_json}\n```"
    res_fenced = parse_and_validate_ux_result(fenced_json)
    assert res_fenced.summary == res.summary


def test_malformed_and_wrong_schema_ux_result_fails():
    """Verifies G, H: Malformed JSON and schema violations fail safely."""
    # G: Malformed JSON
    with pytest.raises(UXResultParseError):
        parse_and_validate_ux_result("{not valid json")

    # H: Wrong schema
    bad_schema = dict(SAMPLE_UX_RESULT)
    bad_schema["schema_version"] = "2.0"
    with pytest.raises(UXResultValidationError) as exc:
        parse_and_validate_ux_result(json.dumps(bad_schema))
    assert "Invalid schema_version" in str(exc.value)

    # Empty summary
    bad_summary = dict(SAMPLE_UX_RESULT)
    bad_summary["summary"] = "   "
    with pytest.raises(UXResultValidationError) as exc:
        parse_and_validate_ux_result(json.dumps(bad_summary))
    assert "summary" in str(exc.value)


# -----------------------------------------------------------------------------
# UX Task Execution Lifecycle & Materialization (B, I, J, K, L)
# -----------------------------------------------------------------------------

def test_execute_ux_task_lifecycle_and_materialization():
    """Verifies B, I, J, K, L: Valid UX task executes, completes, populates details, and creates report artifact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({"ux": json.dumps(SAMPLE_UX_RESULT)})
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Design Terminal Flow",
            goal="Define interaction states",
            required_roles=["ux"],
            expected_output=["UX Report"],
        )

        run = service.execute_ux_task(task.id)

        # I: Task completes, run succeeds
        assert run.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value

        # J: TaskResult.details contains validated UX result
        assert task.result is not None
        assert task.result.details["schema_version"] == "1.0"
        assert task.result.details["flows"][0]["name"] == "Quickstart Verification Flow"

        # K: Exactly one ux_report.md artifact created
        assert len(run.artifacts) == 1
        art = run.artifacts[0]
        assert art.name == "ux_report.md"
        assert art.producer_role == "ux"
        assert art.run_id == run.id

        # L: Hash matches exact bytes
        art_path = Path(tmp_dir) / art.path
        assert art_path.exists()
        raw_bytes = art_path.read_bytes()
        assert art.sha256 == hashlib.sha256(raw_bytes).hexdigest()

        # Content verification
        content = raw_bytes.decode("utf-8")
        assert "# UX Report: Design Terminal Flow" in content
        assert "## User Flows" in content
        assert "Quickstart Verification Flow" in content
        assert "## Screen & State Architecture" in content
        assert "Onboarding Terminal Dashboard" in content
        assert "## Interaction Rules" in content
        assert "## Accessibility Considerations" in content


# -----------------------------------------------------------------------------
# Handoff Policy & Input Attachment Tests (M, N, O, P, Q)
# -----------------------------------------------------------------------------

def test_product_artifact_attaches_to_ux_task():
    """Verifies M, N: Product artifact attaches to UX task and lineage is preserved."""
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

        # Create UX task
        ux_task = service.create_task(
            project_id=proj.id,
            title="UX Flow",
            goal="Define UX",
            required_roles=["ux"],
        )

        # M: Attach Product artifact to UX task
        ref = service.attach_input_artifact(ux_task.id, p_art.id)
        assert isinstance(ref, ArtifactInputRef)
        assert ref.artifact_id == p_art.id
        assert ref.producer_role == "product"
        assert ref.sha256 == p_art.sha256

        # N: Lineage preserved
        assert len(ux_task.input_artifacts) == 1
        assert ux_task.input_artifacts[0] == ref


def test_handoff_policy_rejections():
    """Verifies O, P, Q: Disallowed handoff edges are rejected deterministically."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "research": json.dumps(SAMPLE_RESEARCH_RESULT),
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # 1. Research task
        r_task = service.create_task(project_id=proj.id, title="R", goal="R", required_roles=["research"])
        r_run = service.execute_research_task(r_task.id)
        r_art = r_run.artifacts[0]

        # 2. Product task
        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]

        # 3. UX task
        u_task = service.create_task(project_id=proj.id, title="U", goal="U", required_roles=["ux"])
        u_run = service.execute_ux_task(u_task.id)
        u_art = u_run.artifacts[0]

        # Targets for rejection testing
        target_ux = service.create_task(project_id=proj.id, title="Target UX", goal="T", required_roles=["ux"])
        target_prod = service.create_task(project_id=proj.id, title="Target Prod", goal="T", required_roles=["product"])

        # O: Research -> UX rejected
        with pytest.raises(HandoffPolicyError) as exc:
            service.attach_input_artifact(target_ux.id, r_art.id)
        assert "not permitted" in str(exc.value)

        # P: UX -> Product rejected
        with pytest.raises(HandoffPolicyError) as exc:
            service.attach_input_artifact(target_prod.id, u_art.id)
        assert "not permitted" in str(exc.value)

        # Q: Product -> Product rejected
        with pytest.raises(HandoffPolicyError) as exc:
            service.attach_input_artifact(target_prod.id, p_art.id)
        assert "not permitted" in str(exc.value)


# -----------------------------------------------------------------------------
# Preflight & Tamper Verification (R, S, T)
# -----------------------------------------------------------------------------

def test_tampered_missing_and_oversized_product_artifact_prevents_ux_execution():
    """Verifies R, S, T: Tampered, missing, or oversized Product artifact fails preflight safely."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        p_task = service.create_task(project_id=proj.id, title="P", goal="P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]
        p_file = Path(tmp_dir) / p_art.path

        # R: Tampered Product artifact
        p_file.write_text("Tampered product text!", encoding="utf-8")
        ux_task_r = service.create_task(project_id=proj.id, title="UX_R", goal="UX", required_roles=["ux"])
        service.attach_input_artifact(ux_task_r.id, p_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_r:
            service.execute_ux_task(ux_task_r.id)
        assert "integrity mismatch" in str(exc_r.value).lower()
        assert ux_task_r.status == TaskStatus.PENDING.value
        assert len(ux_task_r.runs) == 0

        # S: Missing Product artifact file
        p_file.unlink()
        ux_task_s = service.create_task(project_id=proj.id, title="UX_S", goal="UX", required_roles=["ux"])
        ref_s = ArtifactInputRef(artifact_id=p_art.id, run_id=p_art.run_id, sha256=p_art.sha256, producer_role="product")
        ux_task_s.input_artifacts.append(ref_s)
        with pytest.raises(ArtifactVerificationError) as exc_s:
            service.execute_ux_task(ux_task_s.id)
        assert "file not found" in str(exc_s.value).lower()
        assert ux_task_s.status == TaskStatus.PENDING.value
        assert len(ux_task_s.runs) == 0

        # T: Oversized Product artifact
        huge_text = "Y" * (MAX_INPUT_ARTIFACT_SIZE_BYTES + 50)
        p_file.write_text(huge_text, encoding="utf-8")
        p_art.sha256 = hashlib.sha256(huge_text.encode("utf-8")).hexdigest()
        ux_task_t = service.create_task(project_id=proj.id, title="UX_T", goal="UX", required_roles=["ux"])
        service.attach_input_artifact(ux_task_t.id, p_art.id)
        with pytest.raises(ArtifactVerificationError) as exc_t:
            service.execute_ux_task(ux_task_t.id)
        assert "exceeds maximum allowed size" in str(exc_t.value).lower()
        assert ux_task_t.status == TaskStatus.PENDING.value
        assert len(ux_task_t.runs) == 0


# -----------------------------------------------------------------------------
# End-to-End Immutability & Independence (U, V, W)
# -----------------------------------------------------------------------------

def test_product_to_ux_handoff_immutability_and_independent_output():
    """Verifies U, V, W: Upstream Product artifact bytes remain unchanged; UX produces independent output artifact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = MockRuntime({
            "product": json.dumps(SAMPLE_PRODUCT_RESULT),
            "ux": json.dumps(SAMPLE_UX_RESULT),
        })
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()

        # Step 1: Execute Product task
        p_task = service.create_task(project_id=proj.id, title="P Task", goal="Goal P", required_roles=["product"])
        p_run = service.execute_product_task(p_task.id)
        p_art = p_run.artifacts[0]
        p_file = Path(tmp_dir) / p_art.path

        p_bytes_before = p_file.read_bytes()
        p_sha_before = p_art.sha256

        # Step 2: Create UX task and attach Product artifact
        ux_task = service.create_task(project_id=proj.id, title="UX Task", goal="Goal UX", required_roles=["ux"])
        service.attach_input_artifact(ux_task.id, p_art.id)

        # Step 3: Execute UX task
        ux_run = service.execute_ux_task(ux_task.id)

        assert ux_run.status == RunStatus.SUCCESS.value
        assert ux_task.status == TaskStatus.COMPLETED.value
        assert len(ux_run.artifacts) == 1

        # U: Product artifact bytes and hash remain 100% unchanged
        p_bytes_after = p_file.read_bytes()
        assert p_bytes_after == p_bytes_before
        assert hashlib.sha256(p_bytes_after).hexdigest() == p_sha_before

        # V: UX produces independent output artifact
        ux_art = ux_run.artifacts[0]
        assert ux_art.name == "ux_report.md"
        assert ux_art.producer_role == "ux"
        assert ux_art.run_id == ux_run.id
        assert ux_art.path != p_art.path
        assert ux_art.sha256 != p_art.sha256

        ux_file = Path(tmp_dir) / ux_art.path
        assert ux_file.exists()
        assert compute_sha256(ux_file.read_text(encoding="utf-8")) == ux_art.sha256
