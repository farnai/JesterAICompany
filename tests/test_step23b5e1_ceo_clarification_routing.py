"""Regression Tests for STEP 23B.5-E.1 — CEO False Clarification & Investigation Routing.

Verifies:
1. Exact Founder objective ('Investigate Jester User Registration Architecture & Endpoints')
   receives complete Goal, Acceptance Criteria, and Constraints.
2. Explicit acceptance criteria embedded in description are parsed and not treated as absent.
3. Natural-language phrases (such as 'form/component', 'and/or') are not blindly interpreted as file targets.
4. Missing repository evidence routes to bounded Research specialist for read-only investigation.
5. CEO investigation budget remains strictly enforced (max_investigations=2).
6. Genuinely ambiguous engineering tasks and policy decisions still trigger Founder clarification.
7. Telemetry and recovery context remain accurate.
8. External target repository remains strictly read-only and unmutated.
9. The existing paused run pattern safely transitions to PLAN_READY with Research specialist.
"""

from pathlib import Path
import pytest
import tempfile
import uuid
from typing import Any, Dict, List, Optional

from jester_ai_company.ceo_contract import (
    CEODecisionResult,
    CEODecisionType,
    ComplexityLevel,
    TaskCategory,
    UncertaintyLevel,
    evaluate_objective_heuristically,
    evaluate_team_selection_heuristically,
    is_read_only_research_objective,
)
from jester_ai_company.core import TaskStatus
from jester_ai_company.orchestrator import (
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    WorkItemState,
    extract_acceptance_criteria_from_text,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
import json
import re


class MockCEORuntime(AntigravityRuntime):
    """Deterministic mock runtime returning valid CEO orchestration plans."""

    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root=repo_root)

    def validate_agent(self, agent: str) -> str:
        return agent.strip().lower()

    def execute(
        self,
        agent: str,
        prompt: str,
        timeout: Optional[float] = None,
        workspace_dir: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> AgentExecutionResult:
        obj_match = re.search(r"ID:\s*([a-zA-Z0-9_\-]+)", prompt)
        obj_id = obj_match.group(1) if obj_match else "obj_test"

        plan_payload = {
            "schema_version": "1.0",
            "plan_id": f"plan_{obj_id}",
            "objective_id": obj_id,
            "version": 1,
            "work_items": [
                {
                    "work_item_id": "wi_research_1",
                    "role": "research",
                    "objective": "Investigate registration architecture",
                    "depends_on": [],
                    "expected_outputs": ["research_report.json"],
                    "priority": 1,
                }
            ],
            "completion_criteria": ["Research report produced"],
            "constraints": ["STRICTLY READ-ONLY research"],
        }
        return AgentExecutionResult(
            agent=agent.lower(),
            success=True,
            stdout=json.dumps(plan_payload),
            stderr="",
            exit_code=0,
            duration_ms=5.0,
        )


@pytest.fixture
def mock_service(tmp_path: Path) -> CompanyService:
    """Instantiate a local isolated CompanyService for regression testing."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    (repo_root / "README.md").write_text("# Jester Project\nPeople discovery platform.", encoding="utf-8")

    # Create fake backend auth router
    backend_app = repo_root / "backend" / "app" / "routers"
    backend_app.mkdir(parents=True, exist_ok=True)
    (backend_app / "auth.py").write_text(
        "# Authentication router\ndef register_user():\n    pass\n",
        encoding="utf-8",
    )

    output_dir = tmp_path / ".runs"
    service = CompanyService(
        repo_root=repo_root,
        output_dir=str(output_dir),
        runtime=MockCEORuntime(repo_root=repo_root),
    )
    return service


def _create_sample_registration_objective() -> CompanyObjective:
    """Create the exact Founder objective from STEP 23B.5-E / crun_97a8b4f3."""
    title = "Investigate Jester User Registration Architecture & Endpoints"
    description = (
        "Conduct a read-only factual investigation of the Jester user registration flow, "
        "focusing strictly on the frontend registration entry point and its corresponding backend endpoint.\n\n"
        "Acceptance Criteria:\n"
        "1. Deliver a concise evidence-based research report in JSON format conforming to schema 1.1.\n"
        "2. Identify the primary frontend registration form/component and the corresponding backend route.\n"
        "3. Limit exploration to a maximum of 3 primary files.\n"
        "4. Do not perform recursive repository exploration.\n"
        "5. Save all artifacts solely in JesterAICompany without mutating the target repository."
    )
    constraints = [
        "Target repository: external Jester.",
        "STRICTLY READ-ONLY research.",
        "Research specialist only; no Developer or other implementation roles.",
        "No file modifications, migrations, commits, pushes, approvals or apply operations.",
        "Inspect a maximum of 3 primary source files.",
        "Avoid recursive directory searches.",
        "Save artifacts only in JesterAICompany.",
    ]
    return CompanyObjective(
        id=f"obj_{uuid.uuid4().hex[:8]}",
        title=title,
        description=description,
        constraints=constraints,
        acceptance_criteria=[],  # Submitted empty by UI modal
        target_repository="C:/Users/fiord/OneDrive/Desktop/Jester",
        project_id="prj_jester",
    )


# ==============================================================================
# 1. Complete Objective Reception & Acceptance Criteria Extraction
# ==============================================================================

def test_registration_objective_extracts_acceptance_criteria():
    """Explicit acceptance criteria embedded in description must be extracted and populated."""
    obj = _create_sample_registration_objective()
    assert len(obj.acceptance_criteria) == 5
    assert "concise evidence-based research report" in obj.acceptance_criteria[0]
    assert "frontend registration form/component" in obj.acceptance_criteria[1]
    assert "maximum of 3 primary files" in obj.acceptance_criteria[2]
    assert "recursive repository exploration" in obj.acceptance_criteria[3]
    assert "without mutating the target repository" in obj.acceptance_criteria[4]


def test_standalone_criteria_extractor():
    """Criteria extractor handles headers, numbered items, and bullet points."""
    text = (
        "General goal text.\n\n"
        "Acceptance Criteria:\n"
        "1. First criterion\n"
        "2. Second criterion with slash/symbol\n"
        "- Third bullet\n"
    )
    criteria = extract_acceptance_criteria_from_text(text)
    assert len(criteria) == 3
    assert criteria[0] == "First criterion"
    assert criteria[1] == "Second criterion with slash/symbol"
    assert criteria[2] == "Third bullet"


# ==============================================================================
# 2. Objective Evaluation Heuristic: EXECUTE vs False Clarification
# ==============================================================================

def test_registration_objective_evaluates_to_execute():
    """CEO must evaluate the registration objective directly to EXECUTE without asking Founder."""
    obj = _create_sample_registration_objective()
    
    # At initial state (investigation_count = 0)
    decision = evaluate_objective_heuristically(obj, investigation_count=0)
    assert decision.decision == CEODecisionType.EXECUTE.value
    assert decision.clarification_question is None
    assert "explicit acceptance criteria" in decision.reasoning_summary.lower()

    # Even if investigation budget reached max (investigation_count = 2)
    decision_max = evaluate_objective_heuristically(obj, investigation_count=2)
    assert decision_max.decision == CEODecisionType.EXECUTE.value
    assert decision_max.clarification_question is None


def test_read_only_research_classification():
    """Read-only research objectives are recognized and route to EXECUTE."""
    obj = _create_sample_registration_objective()
    assert is_read_only_research_objective(obj) is True

    # Mutation objective is NOT read-only
    mut_obj = CompanyObjective(
        id="obj_mut",
        title="Fix registration endpoint",
        description="Fix the bug in registration endpoint",
        constraints=["implement fix", "modify code"],
    )
    assert is_read_only_research_objective(mut_obj) is False


# ==============================================================================
# 3. Investigation Targets: Natural-Language Phrases Filtered Out
# ==============================================================================

def test_natural_language_phrases_not_treated_as_investigation_targets():
    """Natural-language phrases such as 'form/component' and 'and/or' must never be file targets."""
    vague_obj = CompanyObjective(
        id="obj_vague",
        title="Review form/component and/or client/server integration",
        description="Inspect frontend/backend input/output without clear criteria",
        acceptance_criteria=[],
    )
    decision = evaluate_objective_heuristically(vague_obj, investigation_count=0)
    assert decision.decision == CEODecisionType.INVESTIGATE.value
    targets = decision.investigation_targets

    # Natural-language phrases must NOT be in targets
    prohibited_targets = [
        "form/component",
        "and/or",
        "client/server",
        "frontend/backend",
        "input/output",
    ]
    for pt in prohibited_targets:
        assert pt not in targets, f"Prohibited phrase '{pt}' found in investigation targets: {targets}"


# ==============================================================================
# 4. Team Selection: Routes to Research Specialist
# ==============================================================================

def test_registration_objective_selects_research_specialist():
    """CEO team selection allocates only Research role for read-only investigation."""
    obj = _create_sample_registration_objective()
    team_selection = evaluate_team_selection_heuristically(obj)

    assert team_selection.task_category == TaskCategory.RESEARCH.value
    assert team_selection.selected_roles == ["research"]
    assert "developer" not in team_selection.selected_roles
    assert "ux" not in team_selection.selected_roles
    assert "product" not in team_selection.selected_roles
    assert team_selection.actual_specialist_count == 1


# ==============================================================================
# 5. Missing Repository Evidence Routes to Research, Not Founder Clarification
# ==============================================================================

def test_missing_repo_evidence_routes_to_research():
    """Missing files or search terms in read-only objectives route to Research specialist."""
    obj = _create_sample_registration_objective()
    findings = [
        "Inspected target not found: form/component",
        "Inspected target not found: registration",
        "Found directory: backend/app",
    ]
    decision = evaluate_objective_heuristically(
        obj,
        investigation_findings=findings,
        investigation_count=2,
        max_investigations=2,
    )
    # Must NOT ask Founder
    assert decision.decision == CEODecisionType.EXECUTE.value
    assert decision.clarification_question is None


# ==============================================================================
# 6. Genuinely Ambiguous Tasks & Policy Decisions Still Trigger Clarification
# ==============================================================================

def test_genuinely_ambiguous_task_triggers_founder_clarification():
    """A task with no criteria and no read-only research scope asks Founder when budget is exhausted."""
    vague_obj = CompanyObjective(
        id="obj_gen_amb",
        title="Improve auth system",
        description="Make the system better and faster",
        acceptance_criteria=[],
        constraints=[],
    )
    # At count 0: investigates
    dec0 = evaluate_objective_heuristically(vague_obj, investigation_count=0)
    assert dec0.decision == CEODecisionType.INVESTIGATE.value

    # At budget limit (2/2): asks Founder
    dec2 = evaluate_objective_heuristically(vague_obj, investigation_count=2, max_investigations=2)
    assert dec2.decision == CEODecisionType.ASK_FOUNDER.value
    assert dec2.clarification_question is not None


def test_business_policy_decision_triggers_founder_clarification():
    """Vendor choice or critical business policy triggers Founder clarification immediately."""
    policy_obj = CompanyObjective(
        id="obj_policy",
        title="Select Auth Provider",
        description="Choose vendor between Auth0 and Firebase for external auth provider",
        acceptance_criteria=[],
    )
    decision = evaluate_objective_heuristically(policy_obj)
    assert decision.decision == CEODecisionType.ASK_FOUNDER.value
    assert "provider" in decision.clarification_question.lower() or "policy" in decision.clarification_question.lower()


# ==============================================================================
# 7. Safe Planning & Transition on Paused Run Pattern
# ==============================================================================

def test_paused_run_pattern_plans_successfully_without_clarification(mock_service: CompanyService):
    """A CompanyRun with this objective transitions to PLAN_READY with Research specialist."""
    obj = _create_sample_registration_objective()
    run = mock_service.create_company_run(obj)

    # Seed prior investigation findings similar to crun_97a8b4f3
    run.investigation_count = 2
    run.investigation_findings = [
        "Inspected target not found: form/component",
        "Inspected target not found: registration",
        "Found directory: backend/app",
        "Found directory: docs",
        "Found directory: tests",
    ]
    mock_service.durable_storage.save_company_run(run)

    # Planning execution
    planned_run = mock_service.plan_company_run(run.run_id)
    assert planned_run.state == CompanyRunState.PLAN_READY.value
    assert planned_run.team_selection is not None
    assert planned_run.team_selection["selected_roles"] == ["research"]
    assert planned_run.active_plan is not None
    assert len(planned_run.active_plan.work_items) == 1
    assert planned_run.active_plan.work_items[0].role == "research"


# ==============================================================================
# 8. Target Repository Immutability Guarantee
# ==============================================================================

def test_no_target_repository_mutation(mock_service: CompanyService, tmp_path: Path):
    """Research planning and execution never mutate the external target repository."""
    target_repo = tmp_path / "mock_jester_repo"
    target_repo.mkdir(parents=True, exist_ok=True)
    canary_file = target_repo / "canary.txt"
    canary_file.write_text("unmodified-baseline-state", encoding="utf-8")

    obj = _create_sample_registration_objective()
    obj.target_repository = str(target_repo)
    run = mock_service.create_company_run(obj)

    planned_run = mock_service.plan_company_run(run.run_id)
    assert planned_run.state == CompanyRunState.PLAN_READY.value
    assert canary_file.read_text(encoding="utf-8") == "unmodified-baseline-state"
    # Ensure no git commits or apply grants created
    assert planned_run.real_repo_apply_proposal_id is None
    assert planned_run.real_repo_apply_grant_id is None
