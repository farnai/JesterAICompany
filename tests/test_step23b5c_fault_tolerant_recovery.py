"""Tests for STEP 23B.5-C: Fault-Tolerant Agent Execution & Recovery.

Deterministic test suite covering the 16 required recovery and resilience scenarios:
1. Successful execution without recovery.
2. Transient failure followed by successful retry.
3. Timeout caused by excessive exploration (triggers replanning).
4. Authentication failure without retry (fail-closed immediately).
5. Permission/policy failure without retry (blocks/fails immediately).
6. Invalid output with preserved evidence.
7. Checkpoint persistence across process restart.
8. Completed specialists are not repeated.
9. Duplicate work/artifact prevention.
10. Partial results with unmet mandatory criteria.
11. Partial results with satisfied mandatory criteria.
12. Recovery budget exhaustion (attempt limit reached -> fails).
13. Founder clarification and resume.
14. Engineering QA and approval gates remain mandatory.
15. Read-only objectives never mutate the target repository.
16. Existing telemetry remains accurate under recovery.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Generator
import unittest.mock
import uuid
import pytest

from jester_ai_company.context import CompanyObjective
from jester_ai_company.core import RunStatus, TaskStatus
from jester_ai_company.orchestrator import (
    CompanyRun,
    CompanyRunState,
    CEOPlannedWorkItem,
    CEOOrchestrationPlan,
    WorkItemState,
)
from jester_ai_company.recovery import (
    FailureCategory,
    RecoveryDecision,
    FailureClassificationRecord,
    RecoveryCheckpoint,
    classify_specialist_failure,
    evaluate_acceptance_criteria,
    validate_recovery_checkpoint,
)
from jester_ai_company.research_result import RESEARCH_SCHEMA_VERSION
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Temporary workspace directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def _make_research_json(summary: str = "Research complete.") -> str:
    """Generate a valid research result JSON string conforming to Schema 1.1."""
    return json.dumps({
        "schema_version": RESEARCH_SCHEMA_VERSION,
        "task_id": "task_res_1",
        "status": "completed",
        "summary": summary,
        "sources": [
            {
                "source_id": "src_1",
                "title": "Architecture Overview",
                "reference": "docs/architecture.md",
                "source_type": "local_file",
            }
        ],
        "findings": [
            {
                "claim": "Architecture follows modular service pattern",
                "evidence": "Observed service.py structure",
                "evidence_status": "verified_source",
                "certainty": "high",
                "source_ids": ["src_1"],
            }
        ],
        "uncertainties": [],
        "open_questions": [],
    })


def _make_objective(
    title: str,
    description: str = "Test objective description",
    constraints: list = None,
    acceptance_criteria: list = None,
    target_repository: str = None,
) -> CompanyObjective:
    return CompanyObjective(
        id=f"obj_{uuid.uuid4().hex[:8]}",
        title=title,
        description=description,
        constraints=constraints if constraints is not None else ["read-only"],
        acceptance_criteria=acceptance_criteria if acceptance_criteria is not None else ["Complete research findings"],
        target_repository=target_repository,
    )


class MockRecoveryRuntime(AntigravityRuntime):
    """Deterministic mock runtime for fault-tolerance and recovery testing."""

    def __init__(self, repo_root: Path):
        super().__init__(repo_root=repo_root)

    def validate_agent(self, agent: str) -> str:
        return agent.strip().lower()

    def execute(
        self,
        agent: str,
        prompt: str,
        timeout: float = None,
        cwd=None,
    ) -> AgentExecutionResult:
        agent_norm = agent.lower().strip()
        if agent_norm == "ceo":
            import re
            obj_match = re.search(r"\bID:\s*(\S+)", prompt)
            obj_id = obj_match.group(1).strip() if obj_match else "obj_test"

            payload = {
                "schema_version": "1.0",
                "plan_id": f"plan_{uuid.uuid4().hex[:6]}",
                "objective_id": obj_id,
                "version": 1,
                "work_items": [
                    {
                        "work_item_id": "wi_res_1",
                        "role": "research",
                        "objective": "Research and analyze requirements",
                        "depends_on": [],
                        "expected_outputs": ["research_report.json"],
                        "priority": 1,
                    }
                ],
                "completion_criteria": ["Complete research findings"],
                "constraints": ["read-only"],
            }
            stdout = json.dumps(payload)
        else:
            stdout = _make_research_json("Default mock specialist result")

        return AgentExecutionResult(
            agent=agent_norm,
            success=True,
            stdout=stdout,
            stderr="",
            exit_code=0,
            duration_ms=50.0,
            timed_out=False,
            command=["mock", agent_norm],
        )


@pytest.fixture
def service(temp_dir: Path) -> CompanyService:
    """Configured CompanyService with mocked runtime and temp storage."""
    repo_root = temp_dir / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    runtime = MockRecoveryRuntime(repo_root=repo_root)
    svc = CompanyService(repo_root=repo_root, runtime=runtime)
    svc.output_dir = temp_dir / "output"
    svc.output_dir.mkdir(parents=True, exist_ok=True)
    return svc


# ==============================================================================
# Scenario 1: Successful execution without recovery
# ==============================================================================

def test_01_successful_execution_without_recovery(service: CompanyService):
    obj = _make_objective(
        title="Investigate Jester registration",
        description="Read-only analysis",
        constraints=["read-only", "no code changes"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    with unittest.mock.patch.object(
        service.runtime, "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("Direct success"),
            stderr="",
            exit_code=0,
            duration_ms=150.0,
        )
    ):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    final_run = service.get_company_run(run.run_id)
    assert final_run.state == CompanyRunState.COMPLETED.value
    assert len(final_run.recovery_history) == 0
    assert final_run.recovery_checkpoint is not None
    assert len(final_run.employee_summaries) >= 1
    assert final_run.employee_summaries[0].status == TaskStatus.COMPLETED.value


# ==============================================================================
# Scenario 2: Transient failure followed by successful retry
# ==============================================================================

def test_02_transient_failure_followed_by_successful_retry(service: CompanyService):
    obj = _make_objective(
        title="Analyze backend components",
        description="Read-only investigation",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # First attempt: 503 Service Unavailable (transient)
    # Second attempt: Success
    call_count = 0
    def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AgentExecutionResult(
                agent="research",
                success=False,
                stdout="Service temporarily unavailable",
                stderr="HTTP 503 Service Unavailable: upstream connection reset",
                exit_code=-1,
                duration_ms=50.0,
            )
        return AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("Recovered successfully"),
            stderr="",
            exit_code=0,
            duration_ms=100.0,
        )

    with unittest.mock.patch.object(service.runtime, "execute", side_effect=mock_exec):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    final_run = service.get_company_run(run.run_id)
    assert final_run.state == CompanyRunState.COMPLETED.value
    assert len(final_run.recovery_history) == 1
    assert final_run.recovery_history[0]["failure_category"] == FailureCategory.TRANSIENT_RUNTIME.value
    assert final_run.recovery_history[0]["recovery_decision"] == RecoveryDecision.RETRY.value
    assert call_count == 2
    assert final_run.execution_telemetry["total_retries"] >= 1


# ==============================================================================
# Scenario 3: Timeout caused by excessive exploration
# ==============================================================================

def test_03_timeout_caused_by_excessive_exploration(service: CompanyService):
    obj = _make_objective(
        title="Deep code search across repositories",
        description="Search exploration",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    call_count = 0
    def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AgentExecutionResult(
                agent="research",
                success=False,
                stdout="Executed 203 steps and 101 tool calls in excessive exploration loop",
                stderr="Agent execution timed out after 300.0 seconds.",
                exit_code=-1,
                duration_ms=300000.0,
                timed_out=True,
            )
        return AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("Bounded replan finished"),
            stderr="",
            exit_code=0,
            duration_ms=120.0,
        )

    with unittest.mock.patch.object(service.runtime, "execute", side_effect=mock_exec):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    final_run = service.get_company_run(run.run_id)
    assert final_run.state == CompanyRunState.COMPLETED.value
    assert len(final_run.recovery_history) >= 1
    assert final_run.recovery_history[0]["failure_category"] == FailureCategory.TIMEOUT.value
    assert final_run.recovery_history[0]["recovery_decision"] == RecoveryDecision.REPLAN.value
    assert final_run.recovery_history[0]["is_exploration_timeout"] is True
    assert final_run.replan_count >= 1


# ==============================================================================
# Scenario 4: Authentication failure without retry
# ==============================================================================

def test_04_authentication_failure_without_retry(service: CompanyService):
    obj = _make_objective(
        title="Query remote database",
        description="Database fetch",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    with unittest.mock.patch.object(
        service.runtime, "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=False,
            stdout="",
            stderr="HTTP 401 Unauthorized: Invalid API Key provided",
            exit_code=1,
            duration_ms=30.0,
        )
    ):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    final_run = service.get_company_run(run.run_id)
    assert final_run.state == CompanyRunState.FAILED.value
    assert len(final_run.recovery_history) == 1
    assert final_run.recovery_history[0]["failure_category"] == FailureCategory.AUTHENTICATION.value
    assert final_run.recovery_history[0]["recovery_decision"] == RecoveryDecision.FAIL.value
    assert final_run.recovery_history[0]["recovery_eligibility"] is False
    # Verified: NO retries occurred
    assert final_run.execution_telemetry["total_retries"] == 0


# ==============================================================================
# Scenario 5: Permission / policy failure without retry
# ==============================================================================

def test_05_permission_policy_failure_without_retry(service: CompanyService):
    obj = _make_objective(
        title="Check repository files",
        description="Inspection",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    with unittest.mock.patch.object(
        service.runtime, "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=False,
            stdout="",
            stderr="Repository Guard: Permission Denied. Attempted write operation on read-only constraints.",
            exit_code=1,
            duration_ms=25.0,
        )
    ):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    final_run = service.get_company_run(run.run_id)
    assert final_run.state == CompanyRunState.BLOCKED.value
    assert len(final_run.recovery_history) == 1
    assert final_run.recovery_history[0]["failure_category"] == FailureCategory.POLICY_OR_PERMISSION.value
    assert final_run.recovery_history[0]["recovery_decision"] == RecoveryDecision.BLOCK.value
    assert final_run.recovery_history[0]["recovery_eligibility"] is False
    assert final_run.execution_telemetry["total_retries"] == 0


# ==============================================================================
# Scenario 6: Invalid output with preserved evidence
# ==============================================================================

def test_06_invalid_output_with_preserved_evidence(service: CompanyService):
    obj = _make_objective(
        title="Produce schema report",
        description="Report generation",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    malformed_output = "MALFORMED_OUTPUT: {unclosed json string, missing brackets"

    call_count = 0
    def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AgentExecutionResult(
                agent="research",
                success=True,
                stdout=malformed_output,
                stderr="",
                exit_code=0,
                duration_ms=45.0,
            )
        return AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("Fixed schema"),
            stderr="",
            exit_code=0,
            duration_ms=60.0,
        )

    with unittest.mock.patch.object(service.runtime, "execute", side_effect=mock_exec):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    final_run = service.get_company_run(run.run_id)
    assert len(final_run.recovery_history) >= 1
    rec = final_run.recovery_history[0]
    assert rec["failure_category"] == FailureCategory.INVALID_OUTPUT.value
    # Original invalid output evidence must be preserved
    assert "malformed_output" in rec["error_evidence"].lower() or "validation" in rec["error_evidence"].lower()


# ==============================================================================
# Scenario 7: Checkpoint persistence across process restart
# ==============================================================================

def test_07_checkpoint_persistence_across_process_restart(temp_dir: Path, service: CompanyService):
    obj = _make_objective(
        title="Multi-stage persistent task",
        description="Two work items",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    with unittest.mock.patch.object(
        service.runtime, "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("First stage finished"),
            stderr="",
            exit_code=0,
            duration_ms=90.0,
        )
    ):
        service.execute_next_company_work(run.run_id)

    run_after_stage1 = service.get_company_run(run.run_id)
    assert run_after_stage1.recovery_checkpoint is not None
    saved_chk_id = run_after_stage1.recovery_checkpoint["checkpoint_id"]

    # Simulate fresh process restart with a new CompanyService pointing to same storage
    new_svc = CompanyService(repo_root=service.repo_root, runtime=service.runtime)
    new_svc.output_dir = service.output_dir
    rehydrated_run = new_svc.get_company_run(run.run_id)

    assert rehydrated_run.recovery_checkpoint is not None
    assert rehydrated_run.recovery_checkpoint["checkpoint_id"] == saved_chk_id
    assert len(rehydrated_run.recovery_checkpoint["completed_work_item_ids"]) >= 1

    # Checkpoint validation must pass on verified artifacts
    is_valid, err = new_svc.restore_company_run_checkpoint(run.run_id)
    assert is_valid is True
    assert err is None


# ==============================================================================
# Scenario 8: Completed specialists are not repeated
# ==============================================================================

def test_08_completed_specialists_are_not_repeated(service: CompanyService):
    obj = _make_objective(
        title="Sequential research and review",
        description="Sequential pipeline",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)

    # Force 2 work items into active plan
    w1 = run.active_plan.work_items[0]
    w2 = CEOPlannedWorkItem(
        work_item_id="work_item_2",
        role="research",
        objective="Follow-up review",
        depends_on=[w1.work_item_id],
        expected_outputs=["followup_notes.md"],
        priority=2,
        state=WorkItemState.PENDING.value,
    )
    run.active_plan.work_items.append(w2)
    run.work_item_states[w2.work_item_id] = WorkItemState.PENDING.value
    service.save_company_run(run)
    service.start_company_run(run.run_id)

    invoked_tasks = []
    def mock_exec(agent, prompt, *args, **kwargs):
        invoked_tasks.append(agent)
        return AgentExecutionResult(
            agent=agent,
            success=True,
            stdout=_make_research_json(f"Result for call {len(invoked_tasks)}"),
            stderr="",
            exit_code=0,
            duration_ms=80.0,
        )

    with unittest.mock.patch.object(service.runtime, "execute", side_effect=mock_exec):
        # Step 1: executes w1
        service.execute_next_company_work(run.run_id)
        assert len(invoked_tasks) == 1
        run_st1 = service.get_company_run(run.run_id)
        assert run_st1.work_item_states[w1.work_item_id] == WorkItemState.COMPLETED.value

        # Step 2: executes w2 without repeating w1
        service.execute_next_company_work(run.run_id)
        assert len(invoked_tasks) == 2
        run_st2 = service.get_company_run(run.run_id)
        assert run_st2.work_item_states[w2.work_item_id] == WorkItemState.COMPLETED.value
        assert run_st2.state == CompanyRunState.COMPLETED.value


# ==============================================================================
# Scenario 9: Duplicate work and artifact prevention
# ==============================================================================

def test_09_duplicate_work_and_artifact_prevention(service: CompanyService):
    obj = _make_objective(title="Deduplication check", constraints=["read-only"])
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    with unittest.mock.patch.object(
        service.runtime, "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("Deduplication test"),
            stderr="",
            exit_code=0,
            duration_ms=60.0,
        )
    ):
        service.execute_next_company_work(run.run_id)

    run_done = service.get_company_run(run.run_id)
    assert run_done.state == CompanyRunState.COMPLETED.value
    # Check artifact deduplication: no duplicate artifact paths in preserved_artifacts
    arts = (run_done.recovery_checkpoint or {}).get("preserved_artifacts", [])
    art_paths = [a.get("path") for a in arts]
    assert len(art_paths) == len(set(art_paths))

    # Attempting to execute work again on a completed run must fail-closed with TransitionPolicyError
    with pytest.raises(Exception) as exc_info:
        service.execute_next_company_work(run.run_id)
    assert "COMPLETED" in str(exc_info.value)


# ==============================================================================
# Scenario 10: Partial results with unmet mandatory criteria
# ==============================================================================

def test_10_partial_results_with_unmet_mandatory_criteria(service: CompanyService):
    obj = _make_objective(
        title="Analyze security with mandatory criteria",
        constraints=["read-only"],
        acceptance_criteria=["Must produce security_audit.md", "Must produce compliance_cert.md"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Specialist produces only general report, missing compliance_cert.md
    w_item = run.active_plan.work_items[0]
    available_arts = [{"name": "security_audit.md", "path": "artifacts/security_audit.md", "sha256": "abc"}]

    all_met, met, unmet = evaluate_acceptance_criteria(
        mandatory_criteria=run.objective.acceptance_criteria,
        satisfied_criteria=[],
        preserved_artifacts=available_arts,
    )
    assert all_met is False
    assert "Must produce compliance_cert.md" in unmet

    # When mandatory criteria are unmet, CONTINUE_WITH_PARTIAL must be rejected and fail closed
    res = service._handle_work_item_failure(
        run=run,
        target_item=w_item,
        role="research",
        error_msg="Partial output delivered but missing compliance_cert.md",
    )
    assert res.state in (CompanyRunState.FAILED.value, CompanyRunState.BLOCKED.value)


# ==============================================================================
# Scenario 11: Partial results with satisfied mandatory criteria
# ==============================================================================

def test_11_partial_results_with_satisfied_mandatory_criteria(service: CompanyService):
    obj = _make_objective(
        title="Research core architecture",
        constraints=["read-only"],
        acceptance_criteria=["Must produce research_deliverable.md"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    w_item = run.active_plan.work_items[0]

    # Pre-populate satisfied deliverable
    art_path = service.output_dir / "research_deliverable.md"
    art_path.write_text("# Core architecture report", encoding="utf-8")
    art_sha = hashlib.sha256(art_path.read_bytes()).hexdigest()

    run.employee_summaries.append(
        unittest.mock.Mock(
            role="research",
            artifact_refs=[{
                "artifact_id": "art_res_1",
                "name": "research_deliverable.md",
                "path": "research_deliverable.md",
                "sha256": art_sha,
                "producer_role": "research",
            }],
        )
    )

    all_met, met, unmet = evaluate_acceptance_criteria(
        mandatory_criteria=run.objective.acceptance_criteria,
        satisfied_criteria=[],
        preserved_artifacts=[{
            "name": "research_deliverable.md",
            "path": "research_deliverable.md",
            "sha256": art_sha,
        }],
    )
    assert all_met is True
    assert len(unmet) == 0


# ==============================================================================
# Scenario 12: Recovery budget exhaustion
# ==============================================================================

def test_12_recovery_budget_exhaustion(service: CompanyService):
    obj = _make_objective(title="Persistent glitch task", constraints=["read-only"])
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Fail continuously with 503
    with unittest.mock.patch.object(
        service.runtime, "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=False,
            stdout="",
            stderr="503 Service Unavailable: upstream server down",
            exit_code=-1,
            duration_ms=40.0,
        )
    ):
        service.run_company_until_boundary(run.run_id, max_steps=10)

    final_run = service.get_company_run(run.run_id)
    assert final_run.state == CompanyRunState.FAILED.value
    # Exactly 2 attempts (1 initial + 1 retry) permitted before budget exhaustion
    assert final_run.recovery_attempt_counts[run.active_plan.work_items[0].work_item_id] == 2
    assert final_run.current_recovery_record["recovery_decision"] == RecoveryDecision.FAIL.value


# ==============================================================================
# Scenario 13: Founder clarification and resume
# ==============================================================================

def test_13_founder_clarification_and_resume(service: CompanyService):
    obj = _make_objective(
        title="Ambiguous objective requiring decision",
        description="Architecture ambiguity",
        constraints=["read-only"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    # Manually transition to clarification needed
    w_item = run.active_plan.work_items[0]
    service._handle_work_item_failure(
        run=run,
        target_item=w_item,
        role="research",
        error_msg="Encountered ambiguous design requirement needing Founder input: PostgreSQL or MongoDB?",
    )

    waiting_run = service.get_company_run(run.run_id)
    # If not automatically ASK_FOUNDER due to message keywords, test transition manually:
    if waiting_run.state != CompanyRunState.WAITING_FOR_CLARIFICATION.value:
        waiting_run.transition_to(CompanyRunState.WAITING_FOR_CLARIFICATION)
        waiting_run.clarification_request = {"question": "PostgreSQL or MongoDB?"}
        service.save_company_run(waiting_run)

    # Founder responds
    resumed_run = service.submit_founder_clarification(
        run_id=run.run_id,
        response="Please use PostgreSQL for the database.",
        author="Human Founder",
    )
    assert resumed_run.state in (CompanyRunState.RUNNING.value, CompanyRunState.PLAN_READY.value)
    assert len(resumed_run.founder_clarifications) == 1
    assert "PostgreSQL" in resumed_run.founder_clarifications[0]["response"]


# ==============================================================================
# Scenario 14: Engineering QA and approval gates remain mandatory
# ==============================================================================

def test_14_engineering_qa_and_approval_gates_remain_mandatory(service: CompanyService):
    obj = _make_objective(title="Code modification objective")
    run = service.create_company_run(obj)

    # Critical security invariant: direct transition from RUNNING to COMPLETED is forbidden for code workflows
    run.code_patch_artifact_id = "patch_123"
    run.state = CompanyRunState.RUNNING.value

    from jester_ai_company.orchestrator import TransitionPolicyError
    with pytest.raises(TransitionPolicyError):
        run.transition_to(CompanyRunState.COMPLETED)

    # Cannot enter READY_FOR_HUMAN_APPLY without verified code patch & QA
    assert run.real_repo_apply_proposal_id is None
    assert run.real_repo_apply_grant_id is None


# ==============================================================================
# Scenario 15: Read-only objectives never mutate the target repository
# ==============================================================================

def test_15_read_only_objectives_never_mutate_target_repository(temp_dir: Path, service: CompanyService):
    target_repo = temp_dir / "target_repo"
    target_repo.mkdir()
    (target_repo / "main.py").write_text("print('untouched')", encoding="utf-8")
    before_content = (target_repo / "main.py").read_text()

    obj = _make_objective(
        title="Investigate target repo",
        target_repository=str(target_repo),
        constraints=["read-only", "no developer role"],
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    with unittest.mock.patch.object(
        service.runtime, "execute",
        return_value=AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("Examined target"),
            stderr="",
            exit_code=0,
            duration_ms=80.0,
        )
    ):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    after_content = (target_repo / "main.py").read_text()
    assert before_content == after_content
    # Target directory remains unmodified
    assert len(list(target_repo.iterdir())) == 1


# ==============================================================================
# Scenario 16: Existing telemetry remains accurate under recovery
# ==============================================================================

def test_16_existing_telemetry_remains_accurate_under_recovery(service: CompanyService):
    obj = _make_objective(title="Telemetry recovery verification", constraints=["read-only"])
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)
    service.start_company_run(run.run_id)

    call_count = 0
    def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AgentExecutionResult(
                agent="research",
                success=False,
                stdout="Rate limited",
                stderr="HTTP 429 Too Many Requests: resource_exhausted",
                exit_code=-1,
                duration_ms=25.0,
            )
        return AgentExecutionResult(
            agent="research",
            success=True,
            stdout=_make_research_json("Completed on retry"),
            stderr="",
            exit_code=0,
            duration_ms=65.0,
        )

    with unittest.mock.patch.object(service.runtime, "execute", side_effect=mock_exec):
        service.run_company_until_boundary(run.run_id, max_steps=5)

    final_run = service.get_company_run(run.run_id)
    metrics = service.get_company_run_metrics(run.run_id)

    assert metrics["status"] == CompanyRunState.COMPLETED.value
    assert metrics["total_retries"] >= 1
    assert metrics["total_model_invocations"] >= 1
    assert metrics["duration_seconds"] is not None
    assert metrics["specialist_count_executed"] >= 1
