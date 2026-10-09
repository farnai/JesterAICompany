"""Execution Observability & Performance Baseline (STEP 23B.4).

Provides lightweight, durable execution telemetry and performance baseline
comparison for CompanyRuns and specialist work items.

Core Architecture:
1. SpecialistExecutionMetrics: Fine-grained measurement for individual specialist executions.
2. RunExecutionTelemetry: Aggregated run-level telemetry (durations, calls, workforce).
3. PerformanceBaselineComparator: Deterministic comparison between historical runs.
4. Security & Data Minimization Invariants:
   - Zero sensitive prompts, credentials, or raw model dumps stored in telemetry.
   - Read-only telemetry: cannot alter permissions, execution grants, or state machines.
   - Monotonic clocks used for duration where available, durable ISO timestamps for recovery.
   - Missing provider metrics (e.g. tokens, cost) explicitly labeled as None / unavailable.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_to_epoch(iso_str: Optional[str]) -> Optional[float]:
    """Parse ISO 8601 string to unix epoch timestamp safely."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        # Handle 'Z' or offset
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.timestamp()
    except Exception:
        return None


def sanitize_telemetry_message(msg: Optional[str], max_len: int = 250) -> Optional[str]:
    """Sanitize error messages to avoid leaking credentials, prompts, or raw outputs."""
    if not msg or not isinstance(msg, str):
        return None
    cleaned = msg.strip()
    # Mask potential bearer tokens or secrets
    cleaned = re.sub(r"(?i)(bearer\s+[a-z0-9_\-\.]+)", "Bearer [REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(api[_\-]?key\s*[:=]\s*[a-z0-9_\-\.]+)", "api_key=[REDACTED]", cleaned)
    cleaned = re.sub(r"(?i)(password\s*[:=]\s*\S+)", "password=[REDACTED]", cleaned)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "..."
    return cleaned


# ==============================================================================
# Specialist Execution Telemetry
# ==============================================================================

@dataclass
class SpecialistExecutionMetrics:
    """Fine-grained execution telemetry for an individual specialist or task."""
    execution_id: str
    role: str
    phase: str  # e.g. "planning", "investigation", "execution", "qa_verification", "repair"
    started_at: str
    work_item_id: Optional[str] = None
    task_id: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str = "RUNNING"  # "RUNNING", "SUCCESS", "FAILED", "BLOCKED"
    model_identifier: Optional[str] = None  # None if unavailable
    model_invocation_count: int = 1
    model_latency_seconds: Optional[float] = None
    tool_invocation_count: Optional[int] = None  # None if provider does not expose
    tool_execution_duration_seconds: Optional[float] = None  # None if provider does not expose
    input_tokens: Optional[int] = None  # None if unavailable
    output_tokens: Optional[int] = None  # None if unavailable
    total_tokens: Optional[int] = None  # None if unavailable
    error_count: int = 0
    retry_count: int = 0
    error_message: Optional[str] = None
    is_measured: bool = True

    def mark_completed(
        self,
        status: str,
        duration_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
        model_latency_seconds: Optional[float] = None,
        retry_count: int = 0,
        model_invocation_count: Optional[int] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Mark specialist execution as finished and record final measurements."""
        if completed_at:
            self.completed_at = completed_at
        elif not self.completed_at:
            self.completed_at = _utc_now_iso()
        self.status = status.strip().upper()
        if duration_seconds is not None:
            self.duration_seconds = max(0.0, round(float(duration_seconds), 3))
        elif self.duration_seconds is None and self.started_at:
            start_epoch = _parse_iso_to_epoch(self.started_at)
            end_epoch = _parse_iso_to_epoch(self.completed_at)
            if start_epoch and end_epoch and end_epoch >= start_epoch:
                self.duration_seconds = round(end_epoch - start_epoch, 3)

        if error_message:
            self.error_message = sanitize_telemetry_message(error_message)
            self.error_count += 1

        if model_latency_seconds is not None:
            self.model_latency_seconds = max(0.0, round(float(model_latency_seconds), 3))

        if retry_count > 0:
            self.retry_count = retry_count

        if model_invocation_count is not None:
            self.model_invocation_count = max(0, model_invocation_count)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize specialist telemetry to dictionary."""
        return {
            "execution_id": self.execution_id,
            "work_item_id": self.work_item_id,
            "task_id": self.task_id,
            "role": self.role,
            "phase": self.phase,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "model_identifier": self.model_identifier,
            "model_invocation_count": self.model_invocation_count,
            "model_latency_seconds": self.model_latency_seconds,
            "tool_invocation_count": self.tool_invocation_count,
            "tool_execution_duration_seconds": self.tool_execution_duration_seconds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "error_count": self.error_count,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "is_measured": self.is_measured,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecialistExecutionMetrics":
        """Deserialize specialist telemetry with fail-closed safety."""
        if not isinstance(data, dict):
            raise ValueError("Expected dictionary for SpecialistExecutionMetrics.")
        return cls(
            execution_id=str(data.get("execution_id", "")).strip(),
            work_item_id=data.get("work_item_id"),
            task_id=data.get("task_id"),
            role=str(data.get("role", "unknown")).strip().lower(),
            phase=str(data.get("phase", "execution")).strip().lower(),
            started_at=str(data.get("started_at", _utc_now_iso())),
            completed_at=data.get("completed_at"),
            duration_seconds=float(data["duration_seconds"]) if data.get("duration_seconds") is not None else None,
            status=str(data.get("status", "SUCCESS")).strip().upper(),
            model_identifier=data.get("model_identifier"),
            model_invocation_count=int(data.get("model_invocation_count", 1)),
            model_latency_seconds=float(data["model_latency_seconds"]) if data.get("model_latency_seconds") is not None else None,
            tool_invocation_count=int(data["tool_invocation_count"]) if data.get("tool_invocation_count") is not None else None,
            tool_execution_duration_seconds=float(data["tool_execution_duration_seconds"]) if data.get("tool_execution_duration_seconds") is not None else None,
            input_tokens=int(data["input_tokens"]) if data.get("input_tokens") is not None else None,
            output_tokens=int(data["output_tokens"]) if data.get("output_tokens") is not None else None,
            total_tokens=int(data["total_tokens"]) if data.get("total_tokens") is not None else None,
            error_count=int(data.get("error_count", 0)),
            retry_count=int(data.get("retry_count", 0)),
            error_message=sanitize_telemetry_message(data.get("error_message")),
            is_measured=bool(data.get("is_measured", True)),
        )


# ==============================================================================
# Run Execution Telemetry
# ==============================================================================

@dataclass
class RunExecutionTelemetry:
    """Aggregated execution telemetry for a CompanyRun."""
    run_id: str
    started_at: str = field(default_factory=_utc_now_iso)
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    status: str = "RUNNING"
    specialist_metrics: List[SpecialistExecutionMetrics] = field(default_factory=list)
    total_model_invocations: int = 0
    total_model_latency_seconds: float = 0.0
    total_tool_invocations: Optional[int] = None
    total_tool_duration_seconds: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_usd: Optional[float] = None  # None = unavailable
    cost_status: str = "UNAVAILABLE"  # "MEASURED", "ESTIMATED", "UNAVAILABLE"
    total_errors: int = 0
    total_retries: int = 0
    planned_specialists: List[str] = field(default_factory=list)
    executed_specialists: List[str] = field(default_factory=list)
    specialist_count_planned: int = 0
    specialist_count_executed: int = 0
    team_escalation_count: int = 0
    bottleneck_stage: Optional[Dict[str, Any]] = None
    measured_fields: List[str] = field(default_factory=lambda: [
        "started_at", "completed_at", "duration_seconds", "status",
        "total_model_invocations", "total_model_latency_seconds",
        "total_errors", "total_retries", "planned_specialists",
        "executed_specialists", "specialist_count_planned",
        "specialist_count_executed", "team_escalation_count",
    ])
    unavailable_fields: List[str] = field(default_factory=lambda: [
        "input_tokens", "output_tokens", "total_tokens",
        "total_tool_invocations", "total_tool_duration_seconds",
        "estimated_cost_usd",
    ])

    def record_specialist_start(
        self,
        execution_id: str,
        role: str,
        phase: str = "execution",
        work_item_id: Optional[str] = None,
        task_id: Optional[str] = None,
        model_identifier: Optional[str] = None,
    ) -> SpecialistExecutionMetrics:
        """Start tracking a specialist execution and append to record."""
        metric = SpecialistExecutionMetrics(
            execution_id=execution_id,
            role=role.strip().lower(),
            phase=phase.strip().lower(),
            started_at=_utc_now_iso(),
            work_item_id=work_item_id,
            task_id=task_id,
            model_identifier=model_identifier,
        )
        self.specialist_metrics.append(metric)
        self.recompute_aggregates()
        return metric

    def record_specialist_completion(
        self,
        execution_id: str,
        status: str,
        duration_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
        model_latency_seconds: Optional[float] = None,
        retry_count: int = 0,
        model_invocation_count: Optional[int] = None,
    ) -> Optional[SpecialistExecutionMetrics]:
        """Complete an in-flight specialist metric and update run-level aggregates."""
        for m in self.specialist_metrics:
            if m.execution_id == execution_id:
                m.mark_completed(
                    status=status,
                    duration_seconds=duration_seconds,
                    error_message=error_message,
                    model_latency_seconds=model_latency_seconds,
                    retry_count=retry_count,
                    model_invocation_count=model_invocation_count,
                )
                self.recompute_aggregates()
                return m
        return None

    def mark_completed(
        self,
        status: str,
        duration_seconds: Optional[float] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Mark the overall CompanyRun as completed and seal wall-clock metrics."""
        if completed_at:
            self.completed_at = completed_at
        elif not self.completed_at:
            self.completed_at = _utc_now_iso()
        self.status = status.strip().upper()
        if duration_seconds is not None:
            self.duration_seconds = max(0.0, round(float(duration_seconds), 3))
        elif self.duration_seconds is None and self.started_at:
            start_epoch = _parse_iso_to_epoch(self.started_at)
            end_epoch = _parse_iso_to_epoch(self.completed_at)
            if start_epoch and end_epoch and end_epoch >= start_epoch:
                self.duration_seconds = round(end_epoch - start_epoch, 3)
        self.recompute_aggregates()

    def recompute_aggregates(self) -> None:
        """Deterministically recalculate totals, workforce sets, and bottleneck stage."""
        total_invocations = 0
        total_latency = 0.0
        total_errs = 0
        total_rets = 0
        executed_roles: List[str] = []

        bottleneck_metric: Optional[SpecialistExecutionMetrics] = None
        max_duration = -1.0

        for m in self.specialist_metrics:
            total_invocations += m.model_invocation_count
            if m.model_latency_seconds is not None:
                total_latency += m.model_latency_seconds
            total_errs += m.error_count
            total_rets += m.retry_count

            if m.role not in executed_roles and m.status in ("SUCCESS", "RUNNING", "FAILED"):
                executed_roles.append(m.role)

            if m.duration_seconds is not None and m.duration_seconds > max_duration:
                max_duration = m.duration_seconds
                bottleneck_metric = m

        self.total_model_invocations = total_invocations
        self.total_model_latency_seconds = round(total_latency, 3)
        self.total_errors = total_errs
        self.total_retries = total_rets
        self.executed_specialists = executed_roles
        self.specialist_count_executed = len(executed_roles)

        if bottleneck_metric and bottleneck_metric.duration_seconds is not None:
            self.bottleneck_stage = {
                "role": bottleneck_metric.role,
                "phase": bottleneck_metric.phase,
                "work_item_id": bottleneck_metric.work_item_id,
                "duration_seconds": bottleneck_metric.duration_seconds,
                "reason": (
                    f"Specialist '{bottleneck_metric.role}' ({bottleneck_metric.phase}) "
                    f"had highest measured duration ({bottleneck_metric.duration_seconds:.2f}s)"
                ),
            }
        else:
            self.bottleneck_stage = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize run telemetry to dictionary."""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "specialist_metrics": [m.to_dict() for m in self.specialist_metrics],
            "total_model_invocations": self.total_model_invocations,
            "total_model_latency_seconds": self.total_model_latency_seconds,
            "total_tool_invocations": self.total_tool_invocations,
            "total_tool_duration_seconds": self.total_tool_duration_seconds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "cost_status": self.cost_status,
            "total_errors": self.total_errors,
            "total_retries": self.total_retries,
            "planned_specialists": list(self.planned_specialists),
            "executed_specialists": list(self.executed_specialists),
            "specialist_count_planned": self.specialist_count_planned,
            "specialist_count_executed": self.specialist_count_executed,
            "team_escalation_count": self.team_escalation_count,
            "bottleneck_stage": dict(self.bottleneck_stage) if self.bottleneck_stage else None,
            "measured_fields": list(self.measured_fields),
            "unavailable_fields": list(self.unavailable_fields),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunExecutionTelemetry":
        """Deserialize run telemetry with fail-closed schema resilience."""
        if not isinstance(data, dict):
            raise ValueError("Expected dictionary for RunExecutionTelemetry.")

        raw_specialists = data.get("specialist_metrics", [])
        specialists = [
            SpecialistExecutionMetrics.from_dict(m)
            for m in raw_specialists
            if isinstance(m, dict)
        ]

        return cls(
            run_id=str(data.get("run_id", "")).strip(),
            started_at=str(data.get("started_at", _utc_now_iso())),
            completed_at=data.get("completed_at"),
            duration_seconds=float(data["duration_seconds"]) if data.get("duration_seconds") is not None else None,
            status=str(data.get("status", "RUNNING")),
            specialist_metrics=specialists,
            total_model_invocations=int(data.get("total_model_invocations", 0)),
            total_model_latency_seconds=float(data.get("total_model_latency_seconds", 0.0)),
            total_tool_invocations=int(data["total_tool_invocations"]) if data.get("total_tool_invocations") is not None else None,
            total_tool_duration_seconds=float(data["total_tool_duration_seconds"]) if data.get("total_tool_duration_seconds") is not None else None,
            input_tokens=int(data["input_tokens"]) if data.get("input_tokens") is not None else None,
            output_tokens=int(data["output_tokens"]) if data.get("output_tokens") is not None else None,
            total_tokens=int(data["total_tokens"]) if data.get("total_tokens") is not None else None,
            estimated_cost_usd=float(data["estimated_cost_usd"]) if data.get("estimated_cost_usd") is not None else None,
            cost_status=str(data.get("cost_status", "UNAVAILABLE")),
            total_errors=int(data.get("total_errors", 0)),
            total_retries=int(data.get("total_retries", 0)),
            planned_specialists=[str(p) for p in data.get("planned_specialists", [])],
            executed_specialists=[str(e) for e in data.get("executed_specialists", [])],
            specialist_count_planned=int(data.get("specialist_count_planned", 0)),
            specialist_count_executed=int(data.get("specialist_count_executed", 0)),
            team_escalation_count=int(data.get("team_escalation_count", 0)),
            bottleneck_stage=dict(data["bottleneck_stage"]) if isinstance(data.get("bottleneck_stage"), dict) else None,
            measured_fields=list(data.get("measured_fields", [])),
            unavailable_fields=list(data.get("unavailable_fields", [])),
        )


# ==============================================================================
# Performance Baseline Comparator
# ==============================================================================

def compare_company_runs(
    baseline_run_dict: Dict[str, Any],
    candidate_run_dict: Dict[str, Any],
) -> Dict[str, Any]:
    """Deterministically compare two CompanyRuns using actual persisted metrics.

    Never claims cost savings without verified token/pricing measurements.
    Explicitly labels missing measurements as 'unavailable'.
    """
    base_t_data = baseline_run_dict.get("execution_telemetry") or {}
    cand_t_data = candidate_run_dict.get("execution_telemetry") or {}

    base_id = baseline_run_dict.get("run_id", "baseline")
    cand_id = candidate_run_dict.get("run_id", "candidate")

    # 1. Durations
    base_dur = base_t_data.get("duration_seconds")
    cand_dur = cand_t_data.get("duration_seconds")
    dur_delta = None
    dur_pct_change = None
    if base_dur is not None and cand_dur is not None and base_dur > 0:
        dur_delta = round(cand_dur - base_dur, 3)
        dur_pct_change = round(((cand_dur - base_dur) / base_dur) * 100.0, 1)

    # 2. Model Invocations
    base_inv = base_t_data.get("total_model_invocations", 0)
    cand_inv = cand_t_data.get("total_model_invocations", 0)
    inv_delta = cand_inv - base_inv

    # 3. Model Latency
    base_lat = base_t_data.get("total_model_latency_seconds", 0.0)
    cand_lat = cand_t_data.get("total_model_latency_seconds", 0.0)
    lat_delta = round(cand_lat - base_lat, 3)

    # 4. Specialist Counts
    base_planned_cnt = base_t_data.get("specialist_count_planned", 0)
    cand_planned_cnt = cand_t_data.get("specialist_count_planned", 0)
    base_exec_cnt = base_t_data.get("specialist_count_executed", 0)
    cand_exec_cnt = cand_t_data.get("specialist_count_executed", 0)

    # 5. Tokens & Cost (Strictly Unavailable if not exposed)
    token_comparison: Dict[str, Any] = {
        "status": "UNAVAILABLE",
        "reason": "Token usage and provider pricing are not exposed by the current runtime",
        "baseline_tokens": base_t_data.get("total_tokens"),
        "candidate_tokens": cand_t_data.get("total_tokens"),
        "token_delta": None,
        "cost_savings_claimed": False,
        "estimated_cost_usd": None,
    }

    # 6. Retries and Errors
    base_err = base_t_data.get("total_errors", 0)
    cand_err = cand_t_data.get("total_errors", 0)
    base_ret = base_t_data.get("total_retries", 0)
    cand_ret = cand_t_data.get("total_retries", 0)

    # 7. Efficiency Assessment Summary
    efficiency_summary = []
    if inv_delta < 0:
        efficiency_summary.append(f"Model calls reduced by {abs(inv_delta)} ({base_inv} -> {cand_inv}).")
    elif inv_delta > 0:
        efficiency_summary.append(f"Model calls increased by {inv_delta} ({base_inv} -> {cand_inv}).")
    else:
        efficiency_summary.append(f"Model calls remained identical ({cand_inv}).")

    if dur_delta is not None:
        if dur_delta < 0:
            efficiency_summary.append(f"Wall-clock execution faster by {abs(dur_delta):.2f}s ({dur_pct_change}%).")
        elif dur_delta > 0:
            efficiency_summary.append(f"Wall-clock execution slower by {dur_delta:.2f}s (+{dur_pct_change}%).")

    if cand_planned_cnt < base_planned_cnt:
        efficiency_summary.append(
            f"Planned team leaner by {base_planned_cnt - cand_planned_cnt} specialists "
            f"({base_planned_cnt} -> {cand_planned_cnt})."
        )

    return {
        "baseline_run_id": base_id,
        "candidate_run_id": cand_id,
        "compared_at": _utc_now_iso(),
        "wall_clock": {
            "baseline_seconds": base_dur,
            "candidate_seconds": cand_dur,
            "delta_seconds": dur_delta,
            "percentage_change": dur_pct_change,
        },
        "model_invocations": {
            "baseline_count": base_inv,
            "candidate_count": cand_inv,
            "delta_count": inv_delta,
        },
        "model_latency": {
            "baseline_seconds": base_lat,
            "candidate_seconds": cand_lat,
            "delta_seconds": lat_delta,
        },
        "workforce": {
            "baseline_planned": base_planned_cnt,
            "candidate_planned": cand_planned_cnt,
            "baseline_executed": base_exec_cnt,
            "candidate_executed": cand_exec_cnt,
            "baseline_roles": base_t_data.get("executed_specialists", []),
            "candidate_roles": cand_t_data.get("executed_specialists", []),
        },
        "reliability": {
            "baseline_errors": base_err,
            "candidate_errors": cand_err,
            "baseline_retries": base_ret,
            "candidate_retries": cand_ret,
        },
        "tokens_and_cost": token_comparison,
        "summary": " ".join(efficiency_summary),
    }
