"""Deterministic unit tests for Research Task Execution and Provenance Integrity (STEP 8).

Verifies:
A. unique source IDs
B. duplicate source IDs rejected
C. valid finding -> source linkage
D. dangling source ID rejected
E. externally verified finding without source rejected
F. inference / unverified representation accepted when valid
G. invalid evidence status rejected
H. invalid certainty rejected
I. empty source reference rejected
J. existing Research lifecycle still works (RunStatus.SUCCESS, TaskStatus.COMPLETED)
K. Product regression remains green
L. malformed JSON fails safely
M. runtime failure fails safely
N. empty output fails safely
O. wrong schema version fails
P. non-Research task rejected
Q. multi-role task rejected
R. completed task rejected
S. no other agent executes
T. no retries
U. no artifacts invented
"""

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

from jester_ai_company.core import RunStatus, TaskStatus
from jester_ai_company.research_result import (
    RESEARCH_SCHEMA_VERSION,
    ResearchFinding,
    ResearchResultError,
    ResearchResultParseError,
    ResearchResultValidationError,
    ResearchSource,
    ResearchTaskResult,
    build_research_execution_prompt,
    extract_research_json_text,
    parse_and_validate_research_result,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService, InvalidTaskStateError, TaskNotFoundError


def make_mock_runtime(
    stdout: str = "",
    stderr: str = "",
    success: bool = True,
    exit_code: int = 0,
    timed_out: bool = False,
    duration_ms: float = 220.0,
) -> MagicMock:
    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.return_value = AgentExecutionResult(
        agent="research",
        success=success,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        timed_out=timed_out,
        command=["agy", "--agent", "research", "-p", "..."],
    )
    return runtime


VALID_RESEARCH_RESULT_V11_DICT = {
    "schema_version": "1.1",
    "status": "completed",
    "summary": "Comparative investigation of onboarding patterns in leading developer and collaboration tools.",
    "sources": [
        {
            "source_id": "src_bench_1",
            "title": "Onboarding Benchmark Study 2026",
            "reference": "docs/benchmarks/onboarding_2026.md",
            "source_type": "local_file",
            "accessed_at": "2026-10-02T00:00:00Z",
        },
        {
            "source_id": "src_web_1",
            "title": "Local-First Architecture Patterns",
            "reference": "https://example.org/local-first-onboarding",
            "source_type": "web",
            "accessed_at": "2026-10-02T00:05:00Z",
        },
    ],
    "findings": [
        {
            "claim": "Interactive checklists with 3-4 steps reduce drop-off by up to 25% compared to linear modals.",
            "evidence": "Observed pattern in benchmarked apps (Linear, Notion) where setup tasks are non-modal and persistent.",
            "evidence_status": "verified_source",
            "source_ids": ["src_bench_1"],
            "certainty": "high",
        },
        {
            "claim": "Deferred authentication increases time-to-first-value significantly.",
            "evidence": "Local-first apps allow immediate sandbox interaction before requesting cloud accounts.",
            "evidence_status": "verified_source",
            "source_ids": ["src_web_1"],
            "certainty": "medium",
        },
        {
            "claim": "Teams that skip architectural research encounter 2x more onboarding refactors.",
            "evidence": "Logical deduction based on historical development velocity metrics.",
            "evidence_status": "inference",
            "source_ids": [],
            "certainty": "medium",
        },
        {
            "claim": "Mobile app stores might mandate specific permission prompts in 2027.",
            "evidence": "Speculative regulatory trends discussed in industry forums.",
            "evidence_status": "unverified",
            "source_ids": [],
            "certainty": "low",
        },
    ],
    "uncertainties": [
        "Quantitative conversion data for Jester's exact target developer demographic is not publicly available.",
    ],
    "open_questions": [
        "Will Jester require local git initialization prior to onboarding completion?",
    ],
}


# -----------------------------------------------------------------------------
# Parser & Provenance Contract Tests (A, B, C, D, E, F, G, H, I, O)
# -----------------------------------------------------------------------------

def test_research_registration():
    """Verifies that 'research' is registered in AntigravityRuntime."""
    runtime = AntigravityRuntime()
    assert "research" in runtime.valid_roles
    assert runtime.validate_agent("research") == "research"


def test_extract_and_parse_valid_v11_research_json():
    """Verifies C, F: Valid v1.1 JSON parses with sources and findings linkage."""
    raw = json.dumps(VALID_RESEARCH_RESULT_V11_DICT, indent=2)
    result = parse_and_validate_research_result(raw)

    assert result.schema_version == "1.1"
    assert result.status == "completed"
    assert "Comparative investigation" in result.summary
    assert len(result.sources) == 2
    assert len(result.findings) == 4

    # Finding 1 linked to src_bench_1
    assert result.findings[0].evidence_status == "verified_source"
    assert result.findings[0].source_ids == ["src_bench_1"]

    # Finding 3 is inference with empty source_ids
    assert result.findings[2].evidence_status == "inference"
    assert result.findings[2].source_ids == []


def test_duplicate_source_ids_rejected():
    """Verifies B: Duplicate source_id values are rejected."""
    bad_data = json.loads(json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
    bad_data["sources"].append(
        {
            "source_id": "src_bench_1",  # duplicate ID
            "title": "Duplicate Source",
            "reference": "https://example.org/dup",
        }
    )
    with pytest.raises(ResearchResultValidationError) as exc_info:
        parse_and_validate_research_result(json.dumps(bad_data))
    assert "Duplicate source_id 'src_bench_1'" in str(exc_info.value)


def test_dangling_source_id_rejected():
    """Verifies D: Finding referencing non-existent source_id is rejected."""
    bad_data = json.loads(json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
    bad_data["findings"][0]["source_ids"] = ["non_existent_source_99"]
    with pytest.raises(ResearchResultValidationError) as exc_info:
        parse_and_validate_research_result(json.dumps(bad_data))
    assert "references unknown/dangling source_id 'non_existent_source_99'" in str(exc_info.value)


def test_verified_finding_without_source_rejected():
    """Verifies E: Finding marked as 'verified_source' without source_ids is rejected."""
    bad_data = json.loads(json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
    bad_data["findings"][0]["source_ids"] = []
    with pytest.raises(ResearchResultValidationError) as exc_info:
        parse_and_validate_research_result(json.dumps(bad_data))
    assert "marked as 'verified_source' but provides no source_ids" in str(exc_info.value)


def test_invalid_evidence_status_rejected():
    """Verifies G: Unknown evidence_status is rejected."""
    bad_data = json.loads(json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
    bad_data["findings"][0]["evidence_status"] = "absolute_truth"
    with pytest.raises(ResearchResultValidationError) as exc_info:
        parse_and_validate_research_result(json.dumps(bad_data))
    assert "invalid evidence_status 'absolute_truth'" in str(exc_info.value)


def test_invalid_certainty_rejected():
    """Verifies H: Unknown certainty level is rejected."""
    bad_data = json.loads(json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
    bad_data["findings"][0]["certainty"] = "100_percent_sure"
    with pytest.raises(ResearchResultValidationError) as exc_info:
        parse_and_validate_research_result(json.dumps(bad_data))
    assert "invalid certainty '100_percent_sure'" in str(exc_info.value)


def test_empty_source_reference_rejected():
    """Verifies I: Source with empty reference is rejected."""
    bad_data = json.loads(json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
    bad_data["sources"][0]["reference"] = "   "
    with pytest.raises(ResearchResultValidationError) as exc_info:
        parse_and_validate_research_result(json.dumps(bad_data))
    assert "must have a non-empty 'reference'" in str(exc_info.value)


def test_wrong_schema_version_fails():
    """Verifies O: Outdated or unsupported schema version fails."""
    bad_data = json.loads(json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
    bad_data["schema_version"] = "1.0"
    with pytest.raises(ResearchResultValidationError) as exc_info:
        parse_and_validate_research_result(json.dumps(bad_data))
    assert "Invalid schema_version '1.0'. Expected '1.1'" in str(exc_info.value)


def test_malformed_json_fails():
    """Verifies L: Malformed JSON syntax fails safely."""
    with pytest.raises(ResearchResultParseError):
        parse_and_validate_research_result("{broken json: 123")


def test_empty_output_fails():
    """Verifies N: Empty or whitespace-only response fails."""
    with pytest.raises(ResearchResultParseError):
        parse_and_validate_research_result("    ")


# -----------------------------------------------------------------------------
# Execution Prompt Builder Tests
# -----------------------------------------------------------------------------

def test_build_research_execution_prompt_contains_provenance_instructions():
    """Verifies prompt instructs Research agent on provenance and security."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Benchmark Onboarding Flow",
            goal="Identify patterns",
            constraints=["Cite sources"],
            required_roles=["research"],
            expected_output=["Matrix"],
        )

        prompt = build_research_execution_prompt(task)

        assert "1.1" in prompt
        assert "source_id" in prompt
        assert "evidence_status" in prompt
        assert "verified_source" in prompt
        assert "UNTRUSTED DATA" in prompt
        assert f"Task ID: {task.id}" in prompt


# -----------------------------------------------------------------------------
# Service Execution Lifecycle Tests (J, M, P, Q, R, S, T, U)
# -----------------------------------------------------------------------------

def test_execute_research_task_provenance_lifecycle_success():
    """Verifies J, S, T, U: Full lifecycle with provenance tracking."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(stdout=json.dumps(VALID_RESEARCH_RESULT_V11_DICT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Market Research Task",
            goal="Research onboarding patterns",
            required_roles=["research"],
        )

        run = service.execute_research_task(task.id)

        assert run.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value
        assert task.result is not None
        assert task.result.details["schema_version"] == "1.1"
        assert len(task.result.details["sources"]) == 2
        assert len(task.result.details["findings"]) == 4

        # Invariant checks
        mock_runtime.execute.assert_called_once()
        assert mock_runtime.execute.call_args.kwargs["agent"] == "research"
        assert len(task.runs) == 1
        assert len(run.artifacts) == 1
        assert run.artifacts[0].name == "research_report.md"
        assert run.artifacts[0].producer_role == "research"
        assert run.artifacts[0].sha256 is not None



def test_execute_research_task_runtime_failure():
    """Verifies M: Antigravity failure creates controlled FAILED run."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(success=False, exit_code=1, stderr="Subprocess error")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Failing Task",
            goal="Will fail",
            required_roles=["research"],
        )

        run = service.execute_research_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert task.status == TaskStatus.FAILED.value
        assert "exit code 1" in run.error


def test_execute_research_task_rejects_non_research_role():
    """Verifies P: Product task is rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Product Task",
            goal="Define PRD",
            required_roles=["product"],
        )

        with pytest.raises(ValueError):
            service.execute_research_task(task.id)


def test_execute_research_task_rejects_multi_role():
    """Verifies Q: Multi-role task is rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Multi Role",
            goal="Both",
            required_roles=["research", "product"],
        )

        with pytest.raises(ValueError):
            service.execute_research_task(task.id)


def test_execute_research_task_rejects_completed_task():
    """Verifies R: Already completed task is rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Done Task",
            goal="Done",
            required_roles=["research"],
        )
        task.status = TaskStatus.COMPLETED.value

        with pytest.raises(InvalidTaskStateError):
            service.execute_research_task(task.id)
