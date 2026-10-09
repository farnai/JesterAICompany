"""Regression & Unit Tests for STEP 23B.4 — Execution Observability & Performance Baseline.

Verifies:
1. Successful execution metrics recording (durations, calls, roles, latencies).
2. Failed and blocked executions retain partial metrics.
3. Process restart and durable recovery preserves telemetry.
4. Legacy runs without telemetry deserialize safely and derive fallbacks.
5. No duplicate metrics on repeated polling.
6. Missing provider token usage explicitly represented as None / unavailable.
7. Correct wall-clock calculations (positive numbers, accurate diffs).
8. Specialist timing and model-call attribution to respective roles.
9. Escalation metrics tracked accurately.
10. Security and data minimization (no leaked keys/prompts, sanitized errors).
11. Existing QA and Founder Approval invariants preserved (read-only telemetry).
12. Control Center API endpoints for metrics and baseline comparison.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
import time
import uuid

from jester_ai_company.core import Artifact, ArtifactType, Company, Project, Task, TaskRun, RunStatus, TaskStatus
from jester_ai_company.orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    WorkItemState,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.durable_storage import DurableRunStorage
from jester_ai_company.telemetry import (
    SpecialistExecutionMetrics,
    RunExecutionTelemetry,
    compare_company_runs,
    sanitize_telemetry_message,
)
from jester_ai_company.control_center import enrich_company_run_data


class MockObservabilityRuntime(AntigravityRuntime):
    """Deterministic mock runtime for observability regression testing."""

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
        agent_norm = agent.lower()
        if agent_norm == "ceo":
            import re
            obj_match = re.search(r"\bID:\s*(\S+)", prompt)
            obj_id = obj_match.group(1).strip() if obj_match else "obj_test_1"

            if "defect" in prompt.lower() or "registration" in prompt.lower() or "bug" in prompt.lower():
                payload = {
                    "schema_version": "1.0",
                    "plan_id": f"plan_{uuid.uuid4().hex[:6]}",
                    "objective_id": obj_id,
                    "version": 1,
                    "work_items": [
                        {
                            "work_item_id": "wi_dev_1",
                            "role": "developer",
                            "objective": "Fix defect",
                            "depends_on": [],
                            "expected_outputs": ["patch.diff"],
                            "priority": 1,
                        }
                    ],
                    "completion_criteria": ["Registration returns 201"],
                    "constraints": [],
                    "allow_direct_developer": True,
                }
            else:
                payload = {
                    "schema_version": "1.0",
                    "plan_id": f"plan_{uuid.uuid4().hex[:6]}",
                    "objective_id": obj_id,
                    "version": 1,
                    "work_items": [
                        {
                            "work_item_id": "wi_res_1",
                            "role": "research",
                            "objective": "Research market dynamics",
                            "depends_on": [],
                            "expected_outputs": ["research_brief.md"],
                            "priority": 1,
                        }
                    ],
                    "completion_criteria": ["Market research summary generated"],
                    "constraints": [],
                }
            stdout = json.dumps(payload)
        else:
            stdout = "{}"

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
def test_env(tmp_path: Path):
    """Create isolated test environment with temporary runs directory and mock runtime."""
    runs_dir = tmp_path / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    storage = DurableRunStorage(storage_root=runs_dir, is_production=False)
    runtime = MockObservabilityRuntime(repo_root=tmp_path)
    service = CompanyService(
        output_dir=str(runs_dir),
        repo_root=tmp_path,
        runtime=runtime,
        durable_storage=storage,
    )
    return {
        "service": service,
        "storage": storage,
        "runs_dir": runs_dir,
        "tmp_path": tmp_path,
        "runtime": runtime,
    }


# ==============================================================================
# 1. Successful execution metrics
# ==============================================================================

def test_01_successful_execution_metrics(test_env):
    """Verify that a successful run and specialist execution records complete metrics."""
    service = test_env["service"]
    obj = CompanyObjective(
        id="obj_test_1",
        title="Conduct research on market requirements",
        description="Analyze market dynamics and research competitor alternatives",
        target_repository=str(test_env["tmp_path"]),
        acceptance_criteria=["Market research summary generated"],
    )
    run = service.create_company_run(obj)

    assert run.execution_telemetry is not None
    telemetry = RunExecutionTelemetry.from_dict(run.execution_telemetry)
    assert telemetry.run_id == run.run_id
    assert telemetry.status == CompanyRunState.CREATED.value
    assert telemetry.started_at is not None

    # Plan run
    service.plan_company_run(run.run_id)
    run = service.get_company_run(run.run_id)
    assert run.execution_telemetry is not None
    t_after_plan = RunExecutionTelemetry.from_dict(run.execution_telemetry)
    assert "research" in t_after_plan.planned_specialists
    assert t_after_plan.specialist_count_planned >= 1
    # CEO planning specialist metric was recorded
    assert any(m.role == "ceo" and m.phase == "planning" for m in t_after_plan.specialist_metrics)


# ==============================================================================
# 2. Failed and blocked executions
# ==============================================================================

def test_02_failed_and_blocked_executions_retain_partial_metrics(test_env):
    """Verify that failed and blocked executions retain partial metrics."""
    service = test_env["service"]
    obj = CompanyObjective(
        id="obj_fail_1",
        title="Execute failing task",
        description="Simulate execution pipeline failure and inspect telemetry",
        target_repository=str(test_env["tmp_path"]),
    )
    run = service.create_company_run(obj)

    # Transition to FAILED directly
    run.transition_to(CompanyRunState.FAILED, error="Simulated pipeline failure")
    service.save_company_run(run)

    reloaded = service.get_company_run(run.run_id)
    assert reloaded.state == CompanyRunState.FAILED.value
    assert reloaded.execution_telemetry is not None
    t_data = reloaded.execution_telemetry
    assert t_data["status"] == CompanyRunState.FAILED.value
    assert t_data["completed_at"] is not None
    assert t_data["duration_seconds"] is not None
    assert t_data["duration_seconds"] >= 0.0


# ==============================================================================
# 3. Process restart and durable recovery
# ==============================================================================

def test_03_process_restart_and_durable_recovery(test_env):
    """Verify telemetry survives a complete process restart and reloads from disk."""
    service = test_env["service"]
    runs_dir = test_env["runs_dir"]
    tmp_path = test_env["tmp_path"]

    obj = CompanyObjective(
        id="obj_restart_1",
        title="Durable restart verification",
        description="Validate state and telemetry durability across process restarts",
        target_repository=str(tmp_path),
    )
    run = service.create_company_run(obj)

    # Populate telemetry with measured data
    t_obj = RunExecutionTelemetry.from_dict(run.execution_telemetry)
    m = t_obj.record_specialist_start(
        execution_id="exec_test_m1",
        role="developer",
        phase="mutation",
    )
    t_obj.record_specialist_completion(
        execution_id=m.execution_id,
        status="SUCCESS",
        duration_seconds=5.25,
        model_latency_seconds=4.80,
        model_invocation_count=2,
    )
    t_obj.mark_completed(status="COMPLETED", duration_seconds=12.5)
    run.execution_telemetry = t_obj.to_dict()
    service.save_company_run(run)

    # Simulate fresh service instance restart
    new_storage = DurableRunStorage(storage_root=runs_dir, is_production=False)
    new_service = CompanyService(
        output_dir=str(runs_dir),
        repo_root=tmp_path,
        durable_storage=new_storage,
    )

    loaded_run = new_service.get_company_run(run.run_id)
    assert loaded_run.execution_telemetry is not None
    loaded_t = RunExecutionTelemetry.from_dict(loaded_run.execution_telemetry)
    assert loaded_t.duration_seconds == 12.5
    assert loaded_t.total_model_invocations == 2
    assert loaded_t.total_model_latency_seconds == 4.80
    assert len(loaded_t.specialist_metrics) == 1
    assert loaded_t.specialist_metrics[0].role == "developer"
    assert loaded_t.specialist_metrics[0].duration_seconds == 5.25


# ==============================================================================
# 4. Legacy runs without telemetry
# ==============================================================================

def test_04_legacy_runs_without_telemetry(test_env):
    """Verify that runs serialized before Step 23B.4 still deserialize and produce safe fallbacks."""
    service = test_env["service"]
    legacy_json = {
        "run_id": "crun_legacy_101",
        "objective": {
            "id": "obj_leg_1",
            "title": "Legacy objective",
            "description": "Legacy objective created before telemetry schema",
            "target_repository": str(test_env["tmp_path"]),
            "constraints": [],
        },
        "state": "COMPLETED",
        "created_at": "2026-10-08T10:00:00+00:00",
        "completed_at": "2026-10-08T10:00:30+00:00",
        "ceo_invocation_count": 1,
        "specialist_invocation_count": 2,
    }

    run = CompanyRun.from_dict(legacy_json)
    assert run.execution_telemetry is None
    service.save_company_run(run)

    # Service get_company_run_metrics derives fallback without errors
    metrics = service.get_company_run_metrics(run.run_id)
    assert metrics is not None
    assert metrics["run_id"] == "crun_legacy_101"
    assert metrics["status"] == "COMPLETED"
    assert metrics["duration_seconds"] == 30.0
    assert metrics["total_model_invocations"] == 3
    assert metrics["cost_status"] == "UNAVAILABLE"


# ==============================================================================
# 5. No duplicate metrics on polling
# ==============================================================================

def test_05_no_duplicate_metrics_on_polling(test_env):
    """Verify that repeated polling does not duplicate events or inflate counters."""
    service = test_env["service"]
    obj = CompanyObjective(
        id="obj_poll_1",
        title="Check polling idempotency",
        description="Ensure repeated telemetry polling remains side-effect free",
        target_repository=str(test_env["tmp_path"]),
    )
    run = service.create_company_run(obj)

    # Poll multiple times
    for _ in range(5):
        m1 = service.get_company_run_metrics(run.run_id)
        r1 = service.get_company_run(run.run_id)
        assert len(r1.events) == 1  # Only RUN_CREATED
        assert m1["total_model_invocations"] == 0

    assert len(run.events) == 1


# ==============================================================================
# 6. Missing provider token usage
# ==============================================================================

def test_06_missing_provider_token_usage_explicitly_labeled(test_env):
    """Verify that unavailable provider tokens are explicitly None / UNAVAILABLE, never zero or fabricated."""
    telemetry = RunExecutionTelemetry(run_id="crun_test_tokens")
    telemetry.record_specialist_start("exec_1", role="developer")
    telemetry.record_specialist_completion("exec_1", status="SUCCESS", duration_seconds=2.0)

    d = telemetry.to_dict()
    assert d["input_tokens"] is None
    assert d["output_tokens"] is None
    assert d["total_tokens"] is None
    assert d["estimated_cost_usd"] is None
    assert d["cost_status"] == "UNAVAILABLE"
    assert "input_tokens" in d["unavailable_fields"]
    assert "estimated_cost_usd" in d["unavailable_fields"]


# ==============================================================================
# 7. Correct wall-clock calculations
# ==============================================================================

def test_07_correct_wall_clock_calculations():
    """Verify that wall clock durations are calculated with accurate positive seconds."""
    telemetry = RunExecutionTelemetry(
        run_id="crun_wallclock",
        started_at="2026-10-09T10:00:00+00:00",
    )
    # Simulate completion 45.2 seconds later
    telemetry.mark_completed(
        status="COMPLETED",
        completed_at="2026-10-09T10:00:45.200000+00:00",
    )

    assert telemetry.duration_seconds is not None
    assert abs(telemetry.duration_seconds - 45.2) < 0.05
    assert telemetry.status == "COMPLETED"


# ==============================================================================
# 8. Specialist timing and model-call attribution
# ==============================================================================

def test_08_specialist_timing_and_model_call_attribution():
    """Verify attribution of duration, model latency, and invocations to specific roles."""
    telemetry = RunExecutionTelemetry(run_id="crun_roles")

    # Developer execution
    m_dev = telemetry.record_specialist_start("exec_dev", role="developer", phase="mutation")
    telemetry.record_specialist_completion(
        m_dev.execution_id,
        status="SUCCESS",
        duration_seconds=10.5,
        model_latency_seconds=9.8,
        model_invocation_count=2,
    )

    # QA execution
    m_qa = telemetry.record_specialist_start("exec_qa", role="qa", phase="verification")
    telemetry.record_specialist_completion(
        m_qa.execution_id,
        status="SUCCESS",
        duration_seconds=3.2,
        model_latency_seconds=3.0,
        model_invocation_count=1,
    )

    telemetry.recompute_aggregates()

    assert telemetry.total_model_invocations == 3
    assert abs(telemetry.total_model_latency_seconds - 12.8) < 0.01
    assert telemetry.specialist_count_executed == 2
    assert "developer" in telemetry.executed_specialists
    assert "qa" in telemetry.executed_specialists

    # Bottleneck correctly identifies developer
    assert telemetry.bottleneck_stage is not None
    assert telemetry.bottleneck_stage["role"] == "developer"
    assert telemetry.bottleneck_stage["duration_seconds"] == 10.5


# ==============================================================================
# 9. Escalation metrics
# ==============================================================================

def test_09_escalation_metrics_tracking(test_env):
    """Verify that team escalations are tracked in telemetry."""
    service = test_env["service"]
    obj = CompanyObjective(
        id="obj_esc_1",
        title="Fix registration endpoint defect",
        description="Fix broken password hashing and validation error",
        acceptance_criteria=["Registration returns 201"],
        target_repository=str(test_env["tmp_path"]),
    )
    run = service.create_company_run(obj)
    service.plan_company_run(run.run_id)

    # Perform escalation
    service.escalate_company_team(
        run_id=run.run_id,
        triggered_by_role="developer",
        reason="Visual styling requires UX specialist review",
        requested_capability="ux_styling",
        requested_role="ux",
    )

    updated_run = service.get_company_run(run.run_id)
    assert updated_run.escalation_count == 1
    assert updated_run.execution_telemetry is not None
    t_data = updated_run.execution_telemetry
    assert t_data["team_escalation_count"] == 1
    assert "ux" in t_data["planned_specialists"]


# ==============================================================================
# 10. Security and data minimization
# ==============================================================================

def test_10_security_and_data_minimization():
    """Verify credentials and long raw texts are sanitized from telemetry."""
    dirty_msg = "Failed with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 and api_key=sk-secret-123456"
    sanitized = sanitize_telemetry_message(dirty_msg)

    assert "eyJhbG" not in sanitized
    assert "sk-secret" not in sanitized
    assert "Bearer [REDACTED]" in sanitized
    assert "api_key=[REDACTED]" in sanitized

    # Long message truncation
    long_msg = "Error: " + ("x" * 500)
    truncated = sanitize_telemetry_message(long_msg, max_len=100)
    assert len(truncated) <= 104
    assert truncated.endswith("...")


# ==============================================================================
# 11. Existing QA and Founder Approval invariants
# ==============================================================================

def test_11_existing_qa_and_founder_approval_invariants_preserved(test_env):
    """Verify telemetry cannot modify state or bypass Founder Approval boundaries."""
    service = test_env["service"]
    obj = CompanyObjective(
        id="obj_sec_1",
        title="Check approval invariants",
        description="Verify read-only telemetry cannot modify invariants",
        target_repository=str(test_env["tmp_path"]),
    )
    run = service.create_company_run(obj)

    # Reading metrics has zero side effects
    metrics = service.get_company_run_metrics(run.run_id)
    assert metrics["status"] == CompanyRunState.CREATED.value

    # Run state remains strictly CREATED
    run_after = service.get_company_run(run.run_id)
    assert run_after.state == CompanyRunState.CREATED.value
    assert run_after.real_repo_apply_grant_id is None


# ==============================================================================
# 12. Control Center rendering and baseline comparison
# ==============================================================================

def test_12_control_center_enrichment_and_baseline_comparison(test_env):
    """Verify enrich_company_run_data includes telemetry and compare_company_runs produces deterministic diff."""
    service = test_env["service"]

    # Run 1: baseline (multi-specialist)
    obj1 = CompanyObjective(
        id="obj_b1",
        title="Baseline Run",
        description="Base run for baseline comparison test",
        target_repository=str(test_env["tmp_path"]),
    )
    run1 = service.create_company_run(obj1)
    t1 = RunExecutionTelemetry.from_dict(run1.execution_telemetry)
    t1.mark_completed(status="COMPLETED", duration_seconds=20.0)
    t1.total_model_invocations = 5
    t1.total_model_latency_seconds = 18.0
    t1.specialist_count_planned = 4
    t1.specialist_count_executed = 4
    run1.execution_telemetry = t1.to_dict()
    service.save_company_run(run1)

    # Run 2: candidate (lean team)
    obj2 = CompanyObjective(
        id="obj_b2",
        title="Candidate Run",
        description="Candidate run with lean team for comparison",
        target_repository=str(test_env["tmp_path"]),
    )
    run2 = service.create_company_run(obj2)
    t2 = RunExecutionTelemetry.from_dict(run2.execution_telemetry)
    t2.mark_completed(status="COMPLETED", duration_seconds=8.0)
    t2.total_model_invocations = 2
    t2.total_model_latency_seconds = 7.2
    t2.specialist_count_planned = 1
    t2.specialist_count_executed = 1
    run2.execution_telemetry = t2.to_dict()
    service.save_company_run(run2)

    # Check enrichment
    enriched = enrich_company_run_data(run2, service)
    assert "execution_telemetry" in enriched
    assert enriched["execution_telemetry"]["duration_seconds"] == 8.0

    # Deterministic comparison
    comparison = service.compare_company_runs(run1.run_id, run2.run_id)
    assert comparison["wall_clock"]["delta_seconds"] == -12.0
    assert comparison["wall_clock"]["percentage_change"] == -60.0
    assert comparison["model_invocations"]["delta_count"] == -3
    assert comparison["workforce"]["candidate_planned"] == 1
    assert comparison["tokens_and_cost"]["status"] == "UNAVAILABLE"
    assert "Model calls reduced by 3" in comparison["summary"]
    assert "Wall-clock execution faster by 12.00s" in comparison["summary"]
