"""Deterministic unit tests for Product Task Execution (STEP 6B).

Verifies:
A. valid PENDING Product task executes
B. correct agent="product" is used
C. execution prompt contains Task ID/title/goal
D. constraints are included
E. expected_output is included
F. valid raw JSON parses
G. fenced JSON parses
H. structured result validation works
I. successful run becomes COMPLETED (RunStatus.SUCCESS)
J. successful Task becomes COMPLETED (TaskStatus.COMPLETED)
K. Task.result contains validated result
L. malformed JSON creates controlled failed run
M. runtime failure creates controlled failed run
N. empty stdout creates controlled failed run
O. wrong schema fails
P. invalid deliverable shape fails
Q. non-Product task is rejected before runtime
R. multi-role task is rejected
S. already-completed task is rejected
T. no other specialist executes
U. no retry occurs
V. no Artifact is invented unless existing domain behavior explicitly requires it
"""

import json
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

from jester_ai_company.core import RunStatus, TaskStatus
from jester_ai_company.product_result import (
    ProductDeliverable,
    ProductResultError,
    ProductResultParseError,
    ProductResultValidationError,
    ProductTaskResult,
    build_product_execution_prompt,
    extract_product_json_text,
    parse_and_validate_product_result,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService, InvalidTaskStateError, TaskNotFoundError


def make_mock_runtime(
    stdout: str = "",
    stderr: str = "",
    success: bool = True,
    exit_code: int = 0,
    timed_out: bool = False,
    duration_ms: float = 250.0,
) -> MagicMock:
    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.return_value = AgentExecutionResult(
        agent="product",
        success=success,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        timed_out=timed_out,
        command=["agy", "--agent", "product", "-p", "..."],
    )
    return runtime


VALID_PRODUCT_RESULT_DICT = {
    "schema_version": "1.0",
    "status": "completed",
    "summary": "Completed comprehensive onboarding PRD and user stories with testable acceptance criteria.",
    "deliverables": [
        {
            "name": "Onboarding PRD",
            "content": "# Jester Onboarding PRD\n\n## Overview\nStreamline first-time user experience.",
        },
        {
            "name": "User Stories & Acceptance Criteria",
            "content": "### Story 1: Fast activation\nGiven a new user, When they complete step 1, Then activation is triggered.",
        },
    ],
    "risks": [
        "Users may drop off if API keys are requested too early.",
    ],
    "open_questions": [
        "Will third-party oauth be available in Phase 1?",
    ],
}


# -----------------------------------------------------------------------------
# Parser & Validation Contract Tests (F, G, H, O, P)
# -----------------------------------------------------------------------------

def test_extract_and_parse_valid_raw_json():
    """Verifies F & H: Valid raw JSON parses into ProductTaskResult."""
    raw = json.dumps(VALID_PRODUCT_RESULT_DICT, indent=2)
    result = parse_and_validate_product_result(raw)

    assert result.schema_version == "1.0"
    assert result.status == "completed"
    assert "comprehensive onboarding PRD" in result.summary
    assert len(result.deliverables) == 2
    assert result.deliverables[0].name == "Onboarding PRD"
    assert len(result.risks) == 1
    assert len(result.open_questions) == 1


def test_extract_and_parse_fenced_markdown_json():
    """Verifies G: Fenced ```json ... ``` parses successfully."""
    fenced = f"Here is the product result:\n```json\n{json.dumps(VALID_PRODUCT_RESULT_DICT)}\n```\nDone."
    result = parse_and_validate_product_result(fenced)
    assert result.status == "completed"
    assert len(result.deliverables) == 2


def test_parse_malformed_json_fails():
    """Verifies L: Malformed JSON raises ProductResultParseError."""
    malformed = '{"schema_version": "1.0", broken json...'
    with pytest.raises(ProductResultParseError) as exc_info:
        parse_and_validate_product_result(malformed)
    assert "Malformed JSON" in str(exc_info.value)


def test_empty_or_non_string_fails():
    """Verifies N: Empty or whitespace-only model output fails."""
    with pytest.raises(ProductResultParseError):
        parse_and_validate_product_result("")

    with pytest.raises(ProductResultParseError):
        parse_and_validate_product_result("   \n\t  ")


def test_invalid_schema_version_fails():
    """Verifies O: Wrong schema_version raises ProductResultValidationError."""
    bad_data = dict(VALID_PRODUCT_RESULT_DICT)
    bad_data["schema_version"] = "2.0"
    with pytest.raises(ProductResultValidationError) as exc_info:
        parse_and_validate_product_result(json.dumps(bad_data))
    assert "Invalid schema_version '2.0'" in str(exc_info.value)


def test_invalid_status_fails():
    """Verifies O: Unknown status raises ProductResultValidationError."""
    bad_data = dict(VALID_PRODUCT_RESULT_DICT)
    bad_data["status"] = "in_progress"
    with pytest.raises(ProductResultValidationError) as exc_info:
        parse_and_validate_product_result(json.dumps(bad_data))
    assert "Invalid status 'in_progress'" in str(exc_info.value)


def test_invalid_deliverable_shape_fails():
    """Verifies P: Invalid deliverable structure fails."""
    # Deliverables not a list
    bad_data_1 = dict(VALID_PRODUCT_RESULT_DICT)
    bad_data_1["deliverables"] = "just a string"
    with pytest.raises(ProductResultValidationError) as exc_info:
        parse_and_validate_product_result(json.dumps(bad_data_1))
    assert "Field 'deliverables' must be a list" in str(exc_info.value)

    # Deliverable item missing content
    bad_data_2 = dict(VALID_PRODUCT_RESULT_DICT)
    bad_data_2["deliverables"] = [{"name": "Only Name", "content": "  "}]
    with pytest.raises(ProductResultValidationError) as exc_info:
        parse_and_validate_product_result(json.dumps(bad_data_2))
    assert "must have a non-empty 'content'" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Execution Prompt Builder Tests (C, D, E)
# -----------------------------------------------------------------------------

def test_build_product_execution_prompt():
    """Verifies C, D, E: Prompt includes Task ID, title, goal, constraints, expected_output."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proj = service.ensure_default_project()
        task = service.create_task(
            project_id=proj.id,
            title="Design Onboarding Flow",
            goal="Define lean activation path",
            constraints=["No UI mockups", "Zero backend code changes"],
            required_roles=["product"],
            expected_output=["Onboarding PRD", "Acceptance Matrix"],
        )

        prompt = build_product_execution_prompt(task)

        assert f"Task ID: {task.id}" in prompt
        assert "Title: Design Onboarding Flow" in prompt
        assert "Goal: Define lean activation path" in prompt
        assert "No UI mockups" in prompt
        assert "Zero backend code changes" in prompt
        assert "Onboarding PRD" in prompt
        assert "Acceptance Matrix" in prompt
        assert "STRUCTURED PRODUCT EXECUTION MODE" in prompt
        assert "schema_version" in prompt


# -----------------------------------------------------------------------------
# Service Execution Lifecycle Tests (A, B, I, J, K, L, M, N, Q, R, S, T, U, V)
# -----------------------------------------------------------------------------

def test_execute_product_task_success():
    """Verifies A, B, I, J, K, T, U, V: Successful execution lifecycle."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(stdout=json.dumps(VALID_PRODUCT_RESULT_DICT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Onboarding Scoping",
            goal="Scope onboarding requirements",
            constraints=["Constraint A"],
            required_roles=["product"],
            expected_output=["PRD v1"],
        )
        assert task.status == TaskStatus.PENDING.value
        assert len(task.runs) == 0

        # Execute
        run = service.execute_product_task(task.id)

        # B & T: Agent is strictly product, executed once
        mock_runtime.execute.assert_called_once()
        assert mock_runtime.execute.call_args.kwargs["agent"] == "product"

        # I: Run status is SUCCESS
        assert run.status == RunStatus.SUCCESS.value
        assert run.attempt_number == 1
        assert run.completed_at is not None

        # J: Task status is COMPLETED
        assert task.status == TaskStatus.COMPLETED.value

        # K: Task.result is populated with summary and structured details
        assert task.result is not None
        assert task.result.status == TaskStatus.COMPLETED.value
        assert task.result.summary == VALID_PRODUCT_RESULT_DICT["summary"]
        assert task.result.details["schema_version"] == "1.0"
        assert len(task.result.details["deliverables"]) == 2

        # U: No retries; exactly 1 run exists
        assert len(task.runs) == 1
        assert task.runs[0].id == run.id

        # V: Exactly one durable artifact registered
        assert len(run.artifacts) == 1
        assert run.artifacts[0].name == "product_report.md"
        assert run.artifacts[0].producer_role == "product"
        assert run.artifacts[0].sha256 is not None



def test_execute_product_task_runtime_failure():
    """Verifies M: Antigravity runtime failure produces a controlled FAILED run and Task."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(success=False, exit_code=1, stderr="Process crashed")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Failing Task",
            goal="Will fail in runtime",
            required_roles=["product"],
        )

        run = service.execute_product_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert "exit code 1" in run.error
        assert task.status == TaskStatus.FAILED.value
        assert task.result is not None
        assert task.result.status == TaskStatus.FAILED.value
        assert len(task.runs) == 1


def test_execute_product_task_timeout():
    """Verifies M: Antigravity runtime timeout produces a controlled FAILED run."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(success=False, exit_code=-1, timed_out=True, duration_ms=60000)
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Timeout Task",
            goal="Will time out",
            required_roles=["product"],
        )

        run = service.execute_product_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert "timed out" in run.error.lower()
        assert task.status == TaskStatus.FAILED.value


def test_execute_product_task_empty_stdout():
    """Verifies N: Empty stdout produces a controlled FAILED run."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(stdout="   \n  ")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Empty Output Task",
            goal="Produces empty output",
            required_roles=["product"],
        )

        run = service.execute_product_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert "empty output" in run.error.lower()
        assert task.status == TaskStatus.FAILED.value


def test_execute_product_task_malformed_json():
    """Verifies L: Malformed JSON creates a controlled FAILED run without throwing unhandled exceptions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(stdout="Sorry, I cannot return JSON right now.")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Malformed Output Task",
            goal="Produces invalid JSON",
            required_roles=["product"],
        )

        run = service.execute_product_task(task.id)

        assert run.status == RunStatus.FAILED.value
        assert "validation failed" in run.error.lower()
        assert task.status == TaskStatus.FAILED.value


def test_execute_product_task_rejects_non_pending_task():
    """Verifies S: Already completed or running task is rejected before execution."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Already Completed Task",
            goal="Already done",
            required_roles=["product"],
        )
        task.status = TaskStatus.COMPLETED.value

        with pytest.raises(InvalidTaskStateError) as exc_info:
            service.execute_product_task(task.id)
        assert "expected 'PENDING'" in str(exc_info.value)


def test_execute_product_task_rejects_non_product_role():
    """Verifies Q: Non-product task is rejected before runtime."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime()
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Developer Task",
            goal="Write code",
            required_roles=["developer"],
        )

        with pytest.raises(ValueError) as exc_info:
            service.execute_product_task(task.id)
        assert "expected exactly ['product']" in str(exc_info.value)
        mock_runtime.execute.assert_not_called()


def test_execute_product_task_rejects_multi_role_task():
    """Verifies R: Multi-role task is rejected before runtime."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime()
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="Multi Role Task",
            goal="Product and UX",
            required_roles=["product", "ux"],
        )

        with pytest.raises(ValueError) as exc_info:
            service.execute_product_task(task.id)
        assert "expected exactly ['product']" in str(exc_info.value)
        mock_runtime.execute.assert_not_called()


def test_execute_product_task_rejects_empty_roles():
    """Verifies Q: Task with empty required_roles is rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proj = service.ensure_default_project()

        task = service.create_task(
            project_id=proj.id,
            title="No Role Task",
            goal="Unassigned",
            required_roles=[],
        )

        with pytest.raises(ValueError) as exc_info:
            service.execute_product_task(task.id)
        assert "no required roles" in str(exc_info.value).lower()
