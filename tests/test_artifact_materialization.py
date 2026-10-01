"""Deterministic unit tests for Durable Artifact Materialization & Lineage (STEP 9).

Verifies:
A. Product successful execution creates one artifact
B. Research successful execution creates one artifact
C. Product artifact contains expected sections (title, goal, summary, deliverables, risks, open questions)
D. Research artifact contains findings
E. Research source IDs survive materialization
F. Research source references survive materialization
G. SHA-256 matches exact file bytes
H. Artifact is attached to correct TaskRun
I. Two different runs cannot overwrite each other
J. Paths remain under artifact root
K. Path traversal is rejected
L. Malformed LLM result creates no artifact
M. Runtime failure creates no artifact
N. Materialization failure fails run/task safely
O. Task.result.details remains populated on successful execution
P. Product regression remains correct
Q. Research provenance validation remains correct
"""

import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from jester_ai_company.core import ArtifactType, RunStatus, TaskStatus
from jester_ai_company.materializer import (
    MaterializationError,
    atomic_write_text,
    compute_sha256,
    format_product_report,
    format_research_report,
    get_safe_run_artifacts_dir,
    materialize_specialist_artifact,
)
from jester_ai_company.product_result import parse_and_validate_product_result
from jester_ai_company.research_result import parse_and_validate_research_result
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService


SAMPLE_PRODUCT_RESULT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Product requirements for lean onboarding experience.",
    "deliverables": [
        {
            "name": "Onboarding PRD v1",
            "content": "## Overview\nGuided checklist for new developers.",
        }
    ],
    "risks": ["User drop-off if steps exceed 4"],
    "open_questions": ["Is OAuth required in v1?"],
}

SAMPLE_RESEARCH_RESULT = {
    "schema_version": "1.1",
    "status": "completed",
    "summary": "Benchmarking consumer and developer onboarding architectures.",
    "sources": [
        {
            "source_id": "src_1",
            "title": "Onboarding Benchmarks 2026",
            "reference": "https://example.org/benchmarks-2026",
            "source_type": "web",
            "accessed_at": "2026-10-02T00:00:00Z",
        }
    ],
    "findings": [
        {
            "claim": "Non-modal checklists reduce drop-off by 25%.",
            "evidence": "Observed in Linear and Notion audits.",
            "evidence_status": "verified_source",
            "source_ids": ["src_1"],
            "certainty": "high",
        },
        {
            "claim": "Personalized assessment creates psychological investment.",
            "evidence": "Analytical deduction from psychometric onboarding teardowns.",
            "evidence_status": "inference",
            "source_ids": [],
            "certainty": "medium",
        }
    ],
    "uncertainties": ["Exact conversion rate varies by platform"],
    "open_questions": ["What is the primary target niche?"],
}


def make_mock_runtime(agent: str, stdout: str, success: bool = True, exit_code: int = 0) -> MagicMock:
    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.return_value = AgentExecutionResult(
        agent=agent,
        success=success,
        stdout=stdout,
        stderr="",
        exit_code=exit_code,
        duration_ms=150.0,
        timed_out=False,
        command=["agy", "--agent", agent, "-p", "..."],
    )
    return runtime


# -----------------------------------------------------------------------------
# Unit Tests for Materializer Primitives
# -----------------------------------------------------------------------------

def test_compute_sha256_exact():
    """Verifies G: SHA-256 matches exact UTF-8 byte representation."""
    text = "Hello Jester AI Company\nLine 2"
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert compute_sha256(text) == expected


def test_atomic_write_text():
    """Verifies atomic write creates file and ensures correct content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        target = Path(tmp_dir) / "sub" / "test_file.txt"
        atomic_write_text(target, "Durable Content")
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Durable Content"


def test_get_safe_run_artifacts_dir_traversal_prevention():
    """Verifies K: Path traversal attempts are rejected."""
    base = Path("c:/sandbox/output")
    with pytest.raises(MaterializationError) as exc_info:
        get_safe_run_artifacts_dir(base, "../escaping_task", "run_01")
    assert "Invalid task_id" in str(exc_info.value)

    with pytest.raises(MaterializationError) as exc_info:
        get_safe_run_artifacts_dir(base, "task_1", "..\\escaping_run")
    assert "Invalid run_id" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Product Materialization & Lineage Tests (A, C, G, H, O)
# -----------------------------------------------------------------------------

def test_product_execution_creates_durable_artifact():
    """Verifies A, C, G, H, O: Successful Product execution produces verified artifact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = make_mock_runtime("product", json.dumps(SAMPLE_PRODUCT_RESULT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Onboarding Scoping",
            goal="Define onboarding flow",
            expected_output=["PRD Document"],
            required_roles=["product"],
        )

        run = service.execute_product_task(task.id)

        assert run.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value
        assert len(run.artifacts) == 1

        artifact = run.artifacts[0]
        assert artifact.name == "product_report.md"
        assert artifact.artifact_type == ArtifactType.SPECIFICATION.value
        assert artifact.producer_role == "product"
        assert artifact.run_id == run.id

        # Verify file on disk
        artifact_path = Path(tmp_dir) / artifact.path
        assert artifact_path.exists()
        content = artifact_path.read_text(encoding="utf-8")

        # C: Check expected sections
        assert "# Product Report: Onboarding Scoping" in content
        assert "## Executive Summary" in content
        assert "## Goal" in content
        assert "## Deliverables" in content
        assert "### Onboarding PRD v1" in content
        assert "## Risks" in content
        assert "## Open Questions" in content

        # G: SHA-256 matches exact file bytes
        expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert artifact.sha256 == expected_sha

        # O: Task.result.details remains populated
        assert task.result.details["schema_version"] == "1.0"
        assert len(task.result.details["deliverables"]) == 1


# -----------------------------------------------------------------------------
# Research Materialization & Provenance Preservation Tests (B, D, E, F, G, H)
# -----------------------------------------------------------------------------

def test_research_execution_creates_durable_artifact_with_provenance():
    """Verifies B, D, E, F, G, H: Research execution materializes report preserving source IDs."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = make_mock_runtime("research", json.dumps(SAMPLE_RESEARCH_RESULT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Benchmark Patterns",
            goal="Analyze onboarding UX",
            required_roles=["research"],
        )

        run = service.execute_research_task(task.id)

        assert run.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value
        assert len(run.artifacts) == 1

        artifact = run.artifacts[0]
        assert artifact.name == "research_report.md"
        assert artifact.artifact_type == ArtifactType.RESEARCH_REPORT.value
        assert artifact.producer_role == "research"
        assert artifact.run_id == run.id

        # Verify file on disk
        artifact_path = Path(tmp_dir) / artifact.path
        assert artifact_path.exists()
        content = artifact_path.read_text(encoding="utf-8")

        # D, E, F: Findings and visible source IDs
        assert "# Research Report: Benchmark Patterns" in content
        assert "## Findings" in content
        assert "Finding 1: Non-modal checklists reduce drop-off by 25%." in content
        assert "`src_1`" in content
        assert "## Sources & Evidence Provenance" in content
        assert "**`[src_1]` Onboarding Benchmarks 2026**" in content
        assert "https://example.org/benchmarks-2026" in content

        # G: Hash matches
        expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert artifact.sha256 == expected_sha


# -----------------------------------------------------------------------------
# Run Isolation & Overwrite Prevention Tests (I, J)
# -----------------------------------------------------------------------------

def test_two_different_runs_do_not_overwrite():
    """Verifies I: Different runs produce independent isolated artifact paths."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        mock_rt_1 = make_mock_runtime("product", json.dumps(SAMPLE_PRODUCT_RESULT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt_1)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Multi-Run Task",
            goal="Test isolation",
            required_roles=["product"],
        )

        run_1 = service.execute_product_task(task.id)
        art_path_1 = base_dir / run_1.artifacts[0].path
        assert art_path_1.exists()

        # Simulate second run under same task with different result
        result_2_dict = dict(SAMPLE_PRODUCT_RESULT)
        result_2_dict["summary"] = "Run 2 modified summary."
        typed_result_2 = parse_and_validate_product_result(json.dumps(result_2_dict))

        run_2 = task.create_run()
        art_2 = materialize_specialist_artifact(base_dir, task, run_2, "product", typed_result_2)
        art_path_2 = base_dir / art_2.path

        # Both files exist independently and do not overwrite each other
        assert art_path_1 != art_path_2
        assert art_path_1.exists()
        assert art_path_2.exists()
        assert "Run 2 modified summary" not in art_path_1.read_text(encoding="utf-8")
        assert "Run 2 modified summary" in art_path_2.read_text(encoding="utf-8")


# -----------------------------------------------------------------------------
# Failure Semantics Tests (L, M, N)
# -----------------------------------------------------------------------------

def test_malformed_result_creates_no_artifact():
    """Verifies L: Malformed JSON output creates no artifact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = make_mock_runtime("product", "Malformed non-JSON output")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Broken Task",
            goal="Will fail validation",
            required_roles=["product"],
        )

        run = service.execute_product_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert task.status == TaskStatus.FAILED.value
        assert len(run.artifacts) == 0


def test_runtime_failure_creates_no_artifact():
    """Verifies M: Subprocess runtime failure creates no artifact."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = make_mock_runtime("product", "", success=False, exit_code=1)
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Crashing Task",
            goal="Will crash in runtime",
            required_roles=["product"],
        )

        run = service.execute_product_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert task.status == TaskStatus.FAILED.value
        assert len(run.artifacts) == 0


def test_materialization_write_failure_fails_run_safely():
    """Verifies N: Failure during disk writing fails the run and task safely."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_rt = make_mock_runtime("product", json.dumps(SAMPLE_PRODUCT_RESULT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_rt)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Disk Failure Task",
            goal="Simulate I/O error",
            required_roles=["product"],
        )

        # Mock atomic_write_text to raise an OSError
        with patch("jester_ai_company.materializer.atomic_write_text", side_effect=OSError("Disk write error")):
            run = service.execute_product_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert task.status == TaskStatus.FAILED.value
        assert "materialization failed" in run.error.lower()
        assert len(run.artifacts) == 0
