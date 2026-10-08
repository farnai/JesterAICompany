"""Tests for STEP 23B.2: CEO Requirement Clarification & Autonomous Investigation.

Covers:
1. Decision Contract (CEODecisionResult validation, fail-closed security, serialization)
2. Heuristic Objective Evaluation (EXECUTE, INVESTIGATE, ASK_FOUNDER)
3. Georgian-language objectives ("რეგისტრაცია", "რეგისტრაცია გამისწორე jester ზე")
4. Empty acceptance criteria handling
5. Autonomous Read-Only Investigation with bounded budget & exhaustion
6. Durable waiting state persistence (WAITING_FOR_CLARIFICATION stored & loaded from disk)
7. Founder Clarification submission & resumption of existing CompanyRun
8. Preservation of context (no duplicate work, no restart of company run)
9. Safety invariants (No bypass of QA, Founder Approval, Execution Grants, RealRepoApply)
"""

import json
from pathlib import Path
import pytest

from jester_ai_company.orchestrator import (
    CompanyRunState,
    CompanyObjective,
)
from jester_ai_company.ceo_contract import (
    CEODecisionType,
    CEODecisionResult,
    parse_and_validate_ceo_decision,
    evaluate_objective_heuristically,
    CEODecisionSecurityError,
    CEODecisionValidationError,
)
import re
from typing import Optional, Dict
from jester_ai_company.service import CompanyService
from jester_ai_company.durable_storage import DurableRunStorage
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime


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
                    "work_item_id": "wi_research",
                    "role": "research",
                    "objective": "Research registration flow",
                    "depends_on": [],
                    "expected_outputs": ["research.md"],
                    "priority": 1,
                },
                {
                    "work_item_id": "wi_product",
                    "role": "product",
                    "objective": "Specify registration requirements",
                    "depends_on": ["wi_research"],
                    "expected_outputs": ["product.md"],
                    "priority": 2,
                },
                {
                    "work_item_id": "wi_marketing",
                    "role": "marketing",
                    "objective": "Document release notes",
                    "depends_on": ["wi_product"],
                    "expected_outputs": ["notes.md"],
                    "priority": 3,
                },
            ],
            "completion_criteria": ["Registration plan established"],
            "constraints": ["No unverified changes"],
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
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def mock_service(temp_dir: Path) -> CompanyService:
    repo_root = temp_dir / "repo"
    repo_root.mkdir()
    (repo_root / "README.md").write_text("# Jester Project\nPeople discovery platform.", encoding="utf-8")
    
    # Create fake backend auth router
    backend_app = repo_root / "backend" / "app" / "routers"
    backend_app.mkdir(parents=True)
    (backend_app / "auth.py").write_text(
        "# Authentication router\ndef register_user():\n    pass\n",
        encoding="utf-8",
    )
    
    output_dir = temp_dir / ".runs"
    
    service = CompanyService(
        repo_root=repo_root,
        output_dir=str(output_dir),
        runtime=MockCEORuntime(repo_root=repo_root),
    )
    return service


# ==============================================================================
# 1. Decision Contract Validation & Security
# ==============================================================================

def test_ceo_decision_contract_valid_json():
    """Verify valid JSON payload extracts into CEODecisionResult."""
    payload = {
        "decision": "EXECUTE",
        "reasoning_summary": "Requirements are unambiguous and fully specified.",
        "known_facts": ["Endpoint exists", "Test coverage available"],
        "assumptions": [],
        "missing_critical_information": [],
        "proposed_next_action": "Generate DAG plan",
        "clarification_question": None,
        "investigation_targets": [],
    }
    result = parse_and_validate_ceo_decision(json.dumps(payload))
    assert result.decision == CEODecisionType.EXECUTE
    assert result.reasoning_summary == "Requirements are unambiguous and fully specified."
    assert len(result.known_facts) == 2


def test_ceo_decision_contract_rejects_privileged_keys():
    """Verify security guardrail rejects privileged bypass fields."""
    payload = {
        "decision": "EXECUTE",
        "reasoning_summary": "All good.",
        "skip_qa": True,  # Privileged key forbidden
    }
    with pytest.raises(CEODecisionSecurityError, match="Prohibited authority key 'skip_qa'"):
        parse_and_validate_ceo_decision(json.dumps(payload))

    payload_grant = {
        "decision": "EXECUTE",
        "reasoning_summary": "All good.",
        "create_execution_grant": True,
    }
    with pytest.raises(CEODecisionSecurityError, match="Prohibited authority key"):
        parse_and_validate_ceo_decision(json.dumps(payload_grant))


def test_ceo_decision_contract_invalid_decision_type():
    """Verify unknown decision string is rejected."""
    payload = {
        "decision": "BYPASS_ALL",
        "reasoning_summary": "Invalid type",
    }
    with pytest.raises(CEODecisionValidationError, match="missing or invalid 'decision'"):
        parse_and_validate_ceo_decision(json.dumps(payload))


# ==============================================================================
# 2. Objective Evaluation Outcomes: EXECUTE, INVESTIGATE, ASK_FOUNDER
# ==============================================================================

def test_clear_objective_evaluates_to_execute():
    """A clear objective with title, goal, and acceptance criteria should EXECUTE."""
    obj = CompanyObjective(
        id="obj_clear",
        title="Add health check ping route",
        description="Add a GET /health/ping endpoint returning pong 200 OK.",
        acceptance_criteria=["GET /health/ping returns 200", "Include pytest"],
    )
    decision = evaluate_objective_heuristically(obj)
    assert decision.decision == CEODecisionType.EXECUTE
    assert "clear" in decision.reasoning_summary.lower()


def test_investigable_ambiguity_evaluates_to_investigate():
    """Technical ambiguity with code references but no criteria triggers INVESTIGATE."""
    obj = CompanyObjective(
        id="obj_investigable",
        title="Fix auth router validation bug",
        description="The backend app auth router is throwing unhandled ValueError on bad tokens.",
        acceptance_criteria=[],
    )
    decision = evaluate_objective_heuristically(obj)
    assert decision.decision == CEODecisionType.INVESTIGATE
    assert len(decision.investigation_targets) > 0
    assert "auth" in decision.investigation_targets[0].lower()


def test_critical_business_ambiguity_evaluates_to_ask_founder():
    """Critical business policy choice requires human judgment -> ASK_FOUNDER."""
    obj = CompanyObjective(
        id="obj_policy",
        title="Change pricing and authentication tiers",
        description="Choose between free open registration or requiring credit card authorization upfront.",
        acceptance_criteria=[],
    )
    decision = evaluate_objective_heuristically(obj)
    assert decision.decision == CEODecisionType.ASK_FOUNDER
    assert decision.clarification_question is not None
    assert len(decision.missing_critical_information) > 0


# ==============================================================================
# 3. Georgian-Language Objectives & Empty Criteria
# ==============================================================================

def test_georgian_language_objective_empty_criteria():
    """Georgian objective ('რეგისტრაცია') without criteria evaluates to INVESTIGATE first."""
    obj = CompanyObjective(
        id="obj_georgian_01",
        title="რეგისტრაცია",
        description="რეგისტრაცია გამისწორე jester ზე",
        acceptance_criteria=[],
    )
    decision = evaluate_objective_heuristically(obj)
    assert decision.decision == CEODecisionType.INVESTIGATE
    assert any("auth" in t or "backend" in t for t in decision.investigation_targets)
    assert "ქართულენოვანი" in decision.reasoning_summary or "georgian" in decision.reasoning_summary.lower()


# ==============================================================================
# 4. Investigation Budget Exhaustion Guard
# ==============================================================================

def test_investigation_budget_exhaustion_transitions_to_ask_founder():
    """When investigation budget is exhausted (count >= max), CEO must ASK_FOUNDER."""
    obj = CompanyObjective(
        id="obj_budget",
        title="რეგისტრაცია",
        description="რეგისტრაცია გამისწორე jester ზე",
        acceptance_criteria=[],
    )
    decision = evaluate_objective_heuristically(
        obj,
        investigation_findings=["Inspected backend/app/routers/auth.py", "Inspected tests/test_auth.py"],
        investigation_count=2,
        max_investigations=2,
    )
    assert decision.decision == CEODecisionType.ASK_FOUNDER
    assert "budget exhausted" in decision.reasoning_summary.lower()
    assert decision.clarification_question is not None


# ==============================================================================
# 5. Autonomous Read-Only Investigation via CompanyService
# ==============================================================================

def test_service_investigate_objective_is_read_only(mock_service: CompanyService):
    """Verify investigation gathers read-only findings without modifying repo files."""
    obj = CompanyObjective(
        id="obj_read_only",
        title="Fix auth router",
        description="Investigate backend/app/routers/auth.py",
        acceptance_criteria=[],
    )
    run = mock_service.create_company_run(obj)
    auth_file = mock_service.repo_root / "backend" / "app" / "routers" / "auth.py"
    original_mtime = auth_file.stat().st_mtime
    original_content = auth_file.read_text(encoding="utf-8")

    decision = CEODecisionResult(
        decision=CEODecisionType.INVESTIGATE,
        reasoning_summary="Need repo context",
        investigation_targets=["backend/app/routers/auth.py"],
    )

    findings = mock_service.investigate_objective(run.run_id, decision)
    assert len(findings) > 0
    assert "backend/app/routers/auth.py" in findings[0]

    # Verify target file was NOT mutated
    assert auth_file.stat().st_mtime == original_mtime
    assert auth_file.read_text(encoding="utf-8") == original_content

    updated_run = mock_service.get_company_run(run.run_id)
    assert updated_run.investigation_count == 1
    assert len(updated_run.investigation_findings) == 1


# ==============================================================================
# 6. Durable Waiting State & Persistence
# ==============================================================================

def test_durable_waiting_state_persistence(mock_service: CompanyService):
    """Verify WAITING_FOR_CLARIFICATION state and fields persist durably to disk."""
    obj = CompanyObjective(
        id="obj_durable",
        title="Business policy ambiguity",
        description="Decide whether to charge subscription before or after trial",
        acceptance_criteria=[],
    )
    run = mock_service.create_company_run(obj)
    
    # Run planning: should transition to WAITING_FOR_CLARIFICATION
    mock_service.plan_company_run(run.run_id)
    persisted_run = mock_service.get_company_run(run.run_id)

    assert persisted_run.state == CompanyRunState.WAITING_FOR_CLARIFICATION
    assert persisted_run.clarification_request is not None
    assert "question" in persisted_run.clarification_request

    # Verify file on disk can be reloaded by a clean DurableRunStorage instance
    disk_storage = DurableRunStorage(storage_root=mock_service.output_dir)
    reloaded_run = disk_storage.load_company_run(run.run_id)
    assert reloaded_run is not None
    assert reloaded_run.state == CompanyRunState.WAITING_FOR_CLARIFICATION
    assert reloaded_run.clarification_request["question"] == persisted_run.clarification_request["question"]


# ==============================================================================
# 7. Founder Clarification & Seamless Resume
# ==============================================================================

def test_founder_response_and_resume_flow(mock_service: CompanyService):
    """Founder clarification resolves ambiguity and resumes the SAME CompanyRun."""
    obj = CompanyObjective(
        id="obj_resume",
        title="რეგისტრაცია",
        description="რეგისტრაცია გამისწორე jester ზე",
        acceptance_criteria=[],
    )
    run = mock_service.create_company_run(obj)
    
    # 1. First planning phase exhausts investigation or halts on ambiguity
    mock_service.plan_company_run(run.run_id)
    waiting_run = mock_service.get_company_run(run.run_id)
    assert waiting_run.state == CompanyRunState.WAITING_FOR_CLARIFICATION
    original_run_id = waiting_run.run_id

    # 2. Founder responds with clear requirement
    founder_input = "გაასწორე პაროლის მინიმალური სიგრძე 8 სიმბოლომდე backend/app/routers/auth.py-ში"
    resumed_run = mock_service.submit_founder_clarification(
        run_id=original_run_id,
        response=founder_input,
        author="Founder",
    )

    # 3. Same run is resumed (no duplicate run_id created)
    assert resumed_run.run_id == original_run_id
    assert len(resumed_run.founder_clarifications) == 1
    assert resumed_run.founder_clarifications[0]["response"] == founder_input
    assert resumed_run.clarification_request is None

    # 4. State advanced to PLAN_READY or PLANNING with active plan
    assert resumed_run.state in (CompanyRunState.PLAN_READY, CompanyRunState.PLANNING)
    assert resumed_run.active_plan is not None
    assert len(resumed_run.active_plan.work_items) > 0


# ==============================================================================
# 8. No Duplicate Work After Resume
# ==============================================================================

def test_no_duplicate_work_after_resume(mock_service: CompanyService):
    """Investigation findings and context are retained, not re-run or wiped."""
    obj = CompanyObjective(
        id="obj_retain",
        title="Investigate & Clarify",
        description="Check auth router and confirm policy",
        acceptance_criteria=[],
    )
    run = mock_service.create_company_run(obj)
    
    # Seed prior investigation findings
    run.investigation_count = 1
    run.investigation_findings = ["Found UserSchema in models/user.py"]
    mock_service.durable_storage.save_company_run(run)

    # Plan moves to clarification
    mock_service.plan_company_run(run.run_id)
    run = mock_service.get_company_run(run.run_id)
    assert run.state == CompanyRunState.WAITING_FOR_CLARIFICATION
    assert len(run.investigation_findings) >= 1

    # Clarify
    resumed = mock_service.submit_founder_clarification(
        run_id=run.run_id,
        response="Use email validation only",
    )
    # Findings are preserved
    assert "Found UserSchema in models/user.py" in resumed.investigation_findings


# ==============================================================================
# 9. Safety Invariants (No Bypass of QA or Approval)
# ==============================================================================

def test_safety_invariants_preserved(mock_service: CompanyService):
    """Clarification flow cannot bypass QA, Founder Approval, or RealRepoApply."""
    obj = CompanyObjective(
        id="obj_safety",
        title="Ambiguous objective",
        description="Something vague",
        acceptance_criteria=[],
    )
    run = mock_service.create_company_run(obj)
    mock_service.plan_company_run(run.run_id)
    waiting_run = mock_service.get_company_run(run.run_id)
    assert waiting_run.state == CompanyRunState.WAITING_FOR_CLARIFICATION

    # Attempting to directly approve or apply while waiting for clarification must fail
    with pytest.raises(Exception):
        mock_service.approve_company_run(run.run_id, approver="Founder")

    with pytest.raises(Exception):
        mock_service.apply_company_run(run.run_id)

    # Run cannot skip QA to reach READY_FOR_HUMAN_APPLY
    assert waiting_run.real_repo_apply_proposal_id is None
    assert waiting_run.real_repo_apply_grant_id is None
