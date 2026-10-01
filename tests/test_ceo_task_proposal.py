"""Unit and contract tests for CEO Structured Task Proposal (STEP 4).

Verifies:
A. valid raw JSON parses successfully
B. fenced JSON parses successfully
C. malformed JSON fails safely
D. unknown schema version fails
E. unknown action fails
F. unknown assigned agent fails
G. CEO cannot assign arbitrary agent names
H. missing required field fails
I. wrong field types fail
J. empty objective/title fails
K. action="respond" parses correctly
L. no Task is persisted
M. no TaskRun is created
N. no specialist executes
"""

import json
import os
from pathlib import Path
import tempfile
from unittest.mock import MagicMock
import pytest

from jester_ai_company.core import TaskStatus
from jester_ai_company.proposal import (
    CEOActionProposal,
    ProposalError,
    ProposalParseError,
    ProposalValidationError,
    REGISTERED_SPECIALIST_ROLES,
    SCHEMA_VERSION,
    build_task_proposal_prompt,
    extract_json_text,
    parse_and_validate_proposal,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime, InvalidAgentError
from jester_ai_company.service import CompanyService, ProjectNotFoundError


def make_mock_runtime(
    stdout: str = "",
    stderr: str = "",
    success: bool = True,
    exit_code: int = 0,
    timed_out: bool = False,
    duration_ms: float = 150.0,
) -> MagicMock:
    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.return_value = AgentExecutionResult(
        agent="ceo",
        success=success,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        timed_out=timed_out,
        command=["agy", "--agent", "ceo", "-p", "..."],
    )
    return runtime


VALID_PROPOSE_TASK_DICT = {
    "schema_version": "1.0",
    "action": "propose_task",
    "title": "Investigate Social Discovery Onboarding",
    "objective": "Analyze top 3 competing social apps to identify friction points.",
    "assigned_agent": "research",
    "constraints": ["No modifications to production code", "Deliver findings in markdown"],
    "expected_output": ["Competitor analysis document", "Actionable recommendations table"],
}

VALID_RESPOND_DICT = {
    "schema_version": "1.0",
    "action": "respond",
    "message": "Hello Founder, all operational units are running smoothly.",
}


# -----------------------------------------------------------------------------
# Parser & Extraction Tests
# -----------------------------------------------------------------------------

def test_extract_json_text_pure_raw():
    """Verification A: Valid raw JSON parses successfully."""
    raw = json.dumps(VALID_PROPOSE_TASK_DICT, indent=2)
    extracted = extract_json_text(raw)
    assert extracted == raw.strip()

    proposal = parse_and_validate_proposal(raw)
    assert proposal.schema_version == "1.0"
    assert proposal.action == "propose_task"
    assert proposal.title == VALID_PROPOSE_TASK_DICT["title"]
    assert proposal.assigned_agent == "research"
    assert len(proposal.constraints) == 2
    assert len(proposal.expected_output) == 2


def test_extract_json_text_fenced_markdown():
    """Verification B: Fenced JSON (```json ... ``` and ``` ... ```) parses successfully."""
    raw_fenced = f"Here is the machine proposal:\n```json\n{json.dumps(VALID_PROPOSE_TASK_DICT)}\n```\nStanding by."
    proposal = parse_and_validate_proposal(raw_fenced)
    assert proposal.action == "propose_task"
    assert proposal.title == VALID_PROPOSE_TASK_DICT["title"]

    raw_generic_fence = f"```\n{json.dumps(VALID_PROPOSE_TASK_DICT)}\n```"
    proposal2 = parse_and_validate_proposal(raw_generic_fence)
    assert proposal2.action == "propose_task"


def test_extract_json_text_whitespace_surrounding():
    """Verification A/B: JSON with leading and trailing whitespace parses successfully."""
    raw_ws = f"   \n\n  {json.dumps(VALID_PROPOSE_TASK_DICT)}   \n\n  "
    proposal = parse_and_validate_proposal(raw_ws)
    assert proposal.title == VALID_PROPOSE_TASK_DICT["title"]


def test_malformed_json_fails_safely():
    """Verification C: Malformed JSON fails safely with ProposalParseError without throwing unhandled exceptions."""
    malformed = '{"schema_version": "1.0", "action": "propose_task", "title": broken json...'
    with pytest.raises(ProposalParseError) as exc_info:
        parse_and_validate_proposal(malformed)
    assert "Malformed JSON" in str(exc_info.value)


def test_empty_or_non_string_output_fails_safely():
    """Verification C: Empty output fails safely."""
    with pytest.raises(ProposalParseError):
        parse_and_validate_proposal("")

    with pytest.raises(ProposalParseError):
        parse_and_validate_proposal("   ")


def test_non_object_json_fails():
    """Verification C: Valid JSON array instead of object fails validation."""
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal('["schema_version", "1.0"]')
    assert "must be a JSON object" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Schema & Type Validation Tests
# -----------------------------------------------------------------------------

def test_unknown_schema_version_fails():
    """Verification D: Unknown schema version fails with ProposalValidationError."""
    data = dict(VALID_PROPOSE_TASK_DICT)
    data["schema_version"] = "2.0"
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data))
    assert "Invalid schema_version '2.0'" in str(exc_info.value)


def test_unknown_action_fails():
    """Verification E: Unknown action fails with ProposalValidationError."""
    data = dict(VALID_PROPOSE_TASK_DICT)
    data["action"] = "delegate_and_run"
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data))
    assert "Invalid action 'delegate_and_run'" in str(exc_info.value)


def test_unknown_assigned_agent_fails():
    """Verification F & G: Unknown or arbitrary assigned agent fails validation."""
    data = dict(VALID_PROPOSE_TASK_DICT)
    data["assigned_agent"] = "database_specialist"  # Unregistered role
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data))
    assert "Unknown or unauthorized specialist 'database_specialist'" in str(exc_info.value)


def test_ceo_cannot_assign_to_ceo():
    """Verification G: CEO cannot assign work to 'ceo'."""
    data = dict(VALID_PROPOSE_TASK_DICT)
    data["assigned_agent"] = "ceo"
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data))
    assert "CEO cannot assign work to 'ceo'" in str(exc_info.value)


def test_all_registered_specialists_are_valid_targets():
    """Verification F: All 6 registered specialist roles are valid assignees."""
    for specialist in REGISTERED_SPECIALIST_ROLES:
        data = dict(VALID_PROPOSE_TASK_DICT)
        data["assigned_agent"] = specialist
        proposal = parse_and_validate_proposal(json.dumps(data))
        assert proposal.assigned_agent == specialist


def test_missing_required_fields_fail():
    """Verification H: Missing required fields fail validation."""
    required_keys = ["title", "objective", "assigned_agent", "constraints", "expected_output"]
    for key in required_keys:
        data = dict(VALID_PROPOSE_TASK_DICT)
        del data[key]
        with pytest.raises(ProposalValidationError) as exc_info:
            parse_and_validate_proposal(json.dumps(data))
        assert f"Missing required field for 'propose_task': '{key}'" in str(exc_info.value)


def test_wrong_field_types_fail():
    """Verification I: Wrong field types fail validation."""
    # constraints is not a list
    data1 = dict(VALID_PROPOSE_TASK_DICT)
    data1["constraints"] = "No dependencies"
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data1))
    assert "Field 'constraints' must be a list" in str(exc_info.value)

    # constraint item is not a string
    data2 = dict(VALID_PROPOSE_TASK_DICT)
    data2["constraints"] = [123, "valid string"]
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data2))
    assert "must be a string" in str(exc_info.value)

    # expected_output is not a list
    data3 = dict(VALID_PROPOSE_TASK_DICT)
    data3["expected_output"] = 42
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data3))
    assert "Field 'expected_output' must be a list" in str(exc_info.value)

    # assigned_agent is not a string
    data4 = dict(VALID_PROPOSE_TASK_DICT)
    data4["assigned_agent"] = ["developer"]
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data4))
    assert "Field 'assigned_agent' must be a string" in str(exc_info.value)


def test_empty_title_and_objective_fail():
    """Verification J: Empty or whitespace title/objective fails validation."""
    data_empty_title = dict(VALID_PROPOSE_TASK_DICT)
    data_empty_title["title"] = "   "
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data_empty_title))
    assert "Field 'title' must be a non-empty string" in str(exc_info.value)

    data_empty_obj = dict(VALID_PROPOSE_TASK_DICT)
    data_empty_obj["objective"] = ""
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps(data_empty_obj))
    assert "Field 'objective' must be a non-empty string" in str(exc_info.value)


def test_action_respond_parses_correctly():
    """Verification K: action='respond' parses correctly and enforces message field."""
    proposal = parse_and_validate_proposal(json.dumps(VALID_RESPOND_DICT))
    assert proposal.schema_version == "1.0"
    assert proposal.action == "respond"
    assert proposal.message == VALID_RESPOND_DICT["message"]
    assert proposal.title is None
    assert proposal.assigned_agent is None

    # Missing message fails
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps({"schema_version": "1.0", "action": "respond"}))
    assert "Missing required field for 'respond': 'message'" in str(exc_info.value)

    # Empty message fails
    with pytest.raises(ProposalValidationError) as exc_info:
        parse_and_validate_proposal(json.dumps({"schema_version": "1.0", "action": "respond", "message": "   "}))
    assert "Field 'message' must be a non-empty string" in str(exc_info.value)


def test_proposal_to_dict():
    """Verify proposal serialization matches dictionary format."""
    prop1 = parse_and_validate_proposal(json.dumps(VALID_PROPOSE_TASK_DICT))
    d1 = prop1.to_dict()
    assert d1 == VALID_PROPOSE_TASK_DICT

    prop2 = parse_and_validate_proposal(json.dumps(VALID_RESPOND_DICT))
    d2 = prop2.to_dict()
    assert d2 == VALID_RESPOND_DICT


# -----------------------------------------------------------------------------
# CompanyService.propose_task and Non-Persistence Verifications (L, M, N)
# -----------------------------------------------------------------------------

def test_company_service_propose_task_no_persistence():
    """Verification L, M, N: propose_task creates NO Task, NO TaskRun, NO Artifacts, and invokes NO specialist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(stdout=json.dumps(VALID_PROPOSE_TASK_DICT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)

        project = service.ensure_default_project()
        initial_tasks_count = len(project.tasks)
        initial_runs_count = sum(len(t.runs) for t in project.tasks.values())

        founder_request = "We need an in-depth investigation of onboarding benchmarks."
        proposal = service.propose_task(founder_request)

        # 1. Proposal is valid
        assert isinstance(proposal, CEOActionProposal)
        assert proposal.action == "propose_task"
        assert proposal.assigned_agent == "research"

        # 2. Verification L: No Task is persisted
        after_tasks_count = len(project.tasks)
        assert after_tasks_count == initial_tasks_count, "Verification L: Tasks before must equal Tasks after"

        # 3. Verification M: No TaskRun is created
        after_runs_count = sum(len(t.runs) for t in project.tasks.values())
        assert after_runs_count == initial_runs_count, "Verification M: TaskRuns before must equal TaskRuns after"

        # 4. Verification N: No specialist executes; only CEO was called
        mock_runtime.execute.assert_called_once()
        called_agent = mock_runtime.execute.call_args.kwargs["agent"]
        assert called_agent == "ceo", "Verification N: Specialist must NOT execute; only CEO is invoked"


def test_company_service_propose_task_runtime_failure():
    """Verify propose_task raises ProposalError if runtime execution fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(success=False, exit_code=1, stderr="Subprocess error")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)

        with pytest.raises(ProposalError) as exc_info:
            service.propose_task("Evaluate market opportunities")
        assert "CEO runtime execution failed" in str(exc_info.value)


def test_company_service_propose_task_empty_request_rejected():
    """Verify propose_task rejects empty string."""
    service = CompanyService(runtime=make_mock_runtime(stdout="{}"))
    with pytest.raises(ValueError):
        service.propose_task("   ")


# -----------------------------------------------------------------------------
# STEP 6A Ingestion: Validated CEO Proposal -> Registered Task (A through O)
# -----------------------------------------------------------------------------

def test_accept_task_proposal_deterministic_success():
    """Verifies A through K: Valid proposal maps deterministically into registered Task."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(stdout="not called")
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)
        project = service.ensure_default_project()
        initial_tasks_count = len(project.tasks)

        proposal = CEOActionProposal(
            schema_version="1.0",
            action="propose_task",
            title="Define Onboarding Product Requirements",
            objective="Catalog user activation friction and define functional onboarding scope.",
            assigned_agent="product",
            constraints=["Zero code changes", "Lean delivery"],
            expected_output=["Onboarding PRD", "Acceptance Criteria Matrix"],
        )

        task = service.accept_task_proposal(proposal=proposal, project_id=project.id)

        # A. exactly one Task created
        assert len(project.tasks) == initial_tasks_count + 1
        assert task.id in project.tasks

        # B. title maps correctly
        assert task.title == proposal.title

        # C. goal maps correctly
        assert task.goal == proposal.objective

        # D. constraints map correctly
        assert task.constraints == proposal.constraints

        # E. required_roles == [assigned_agent]
        assert task.required_roles == [proposal.assigned_agent]

        # F. correct project_id is used
        assert task.project_id == project.id

        # G. initial status is PENDING
        assert task.status == TaskStatus.PENDING.value

        # Expected output stored
        assert task.expected_output == proposal.expected_output

        # H. no TaskRun is created
        assert len(task.runs) == 0
        assert len(service.list_runs(task.id)) == 0

        # I. no Artifact is created
        assert len(service.get_task_artifacts(task.id)) == 0

        # J & K. no AntigravityRuntime call occurs, no specialist executes
        mock_runtime.execute.assert_not_called()


def test_accept_task_proposal_rejects_respond_action():
    """Verification L: action='respond' is rejected without creating a Task."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        project = service.ensure_default_project()
        initial_count = len(project.tasks)

        proposal = CEOActionProposal(
            schema_version="1.0",
            action="respond",
            message="Hello Founder, everything looks good.",
        )

        with pytest.raises(ValueError) as exc_info:
            service.accept_task_proposal(proposal, project_id=project.id)

        assert "Only proposals with action 'propose_task'" in str(exc_info.value)
        assert len(project.tasks) == initial_count


def test_accept_task_proposal_rejects_unknown_project():
    """Verification M: Unknown project_id is rejected with ProjectNotFoundError."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        proposal = CEOActionProposal(
            schema_version="1.0",
            action="propose_task",
            title="Valid Title",
            objective="Valid Objective",
            assigned_agent="developer",
            constraints=[],
            expected_output=[],
        )

        with pytest.raises(ProjectNotFoundError):
            service.accept_task_proposal(proposal, project_id="non_existent_project")


def test_accept_task_proposal_rejects_stale_or_invalid_specialist():
    """Verification N: Stale/manual proposal assigning 'ceo' or unknown role is rejected."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        project = service.ensure_default_project()

        # Cannot assign to ceo
        bad_prop_ceo = CEOActionProposal(
            schema_version="1.0",
            action="propose_task",
            title="Self-assigned task",
            objective="Do CEO work",
            assigned_agent="ceo",
        )
        with pytest.raises(InvalidAgentError) as exc_info:
            service.accept_task_proposal(bad_prop_ceo, project_id=project.id)
        assert "not one of registered specialists" in str(exc_info.value)

        # Cannot assign to arbitrary string
        bad_prop_unknown = CEOActionProposal(
            schema_version="1.0",
            action="propose_task",
            title="Random task",
            objective="Random work",
            assigned_agent="super_agent",
        )
        with pytest.raises(InvalidAgentError):
            service.accept_task_proposal(bad_prop_unknown, project_id=project.id)


def test_accept_task_proposal_duplicate_acceptance_behavior():
    """Verification 9: Document that accepting the same proposal twice creates two distinct registered tasks."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        project = service.ensure_default_project()

        proposal = CEOActionProposal(
            schema_version="1.0",
            action="propose_task",
            title="Duplicate Test Task",
            objective="Test duplicate ingestion",
            assigned_agent="qa",
        )

        task_1 = service.accept_task_proposal(proposal, project_id=project.id)
        task_2 = service.accept_task_proposal(proposal, project_id=project.id)

        assert task_1.id != task_2.id
        assert task_1.title == task_2.title
        assert len(project.tasks) == 2


def test_existing_ceo_proposal_generation_remains_unchanged():
    """Verification O: propose_task generation remains strictly unchanged."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        mock_runtime = make_mock_runtime(stdout=json.dumps(VALID_PROPOSE_TASK_DICT))
        service = CompanyService(output_dir=tmp_dir, runtime=mock_runtime)

        proposal = service.propose_task("Research competitors")
        assert proposal.action == "propose_task"
        assert proposal.assigned_agent == "research"

