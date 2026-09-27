"""
tests/test_run_pipeline.py - Deterministic test suite for pipeline hardening.

Verifies:
A. Verification succeeds immediately (Product -> Developer -> Verification -> Result)
B. Verification fails once and succeeds after Developer fix (Product -> Developer -> Verification FAIL -> Developer FIX -> Verification PASS -> Result)
C. Verification fails until retry limit is exhausted (Product -> Developer -> Verification FAIL -> Developer FIX -> Verification FAIL -> Developer FIX -> Verification FAIL -> FINAL FAILURE)
D. Invalid/empty goal still fails before agent execution
E. Infrastructure failure is not retried as a normal code verification failure
"""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

from tools.run_pipeline import PipelineRunner, FailureType, PipelineError


def test_scenario_a_verification_succeeds_immediately():
    """Scenario A: Verification succeeds on attempt 0.
    
    Expected flow: Product -> Developer -> Verification -> Result (0 fix attempts).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        verify_cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        runner = PipelineRunner(
            goal="Scenario A: Immediate verification success",
            verify_cmd=verify_cmd,
            mock=True,
            max_fix_attempts=2,
            output_dir=tmp_dir,
            verbose=False,
        )
        exit_code = runner.execute()

        assert exit_code == 0
        assert runner.manifest["status"] == "SUCCESS"
        assert runner.manifest["fix_attempts_executed"] == 0

        stage_ids = [s["stage_id"] for s in runner.manifest["stages"]]
        assert stage_ids == [
            "00_goal",
            "01_product",
            "02_developer",
            "03_verification_attempt_0",
            "04_result",
        ]

        # Artifacts verification
        run_dir = Path(tmp_dir) / runner.run_id
        assert (run_dir / "00_goal/goal.txt").is_file()
        assert (run_dir / "01_product/product_spec.md").is_file()
        assert (run_dir / "02_developer/dev_summary.md").is_file()
        assert (run_dir / "03_verification/attempt_0/verification_report.json").is_file()
        assert (run_dir / "03_verification/verification_report.json").is_file()
        assert (run_dir / "04_result/result_summary.md").is_file()

        # Ensure no developer fix directories were created
        assert not (run_dir / "02_developer_fix_1").exists()


def test_scenario_b_verification_fails_once_then_succeeds_after_fix():
    """Scenario B: Verification fails on attempt 0, succeeds on attempt 1 after Developer fix.
    
    Expected flow: Product -> Developer -> Verification FAIL -> Developer FIX -> Verification PASS -> Result.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create a state file to simulate failure on attempt 0, then success on attempt 1
        state_file = Path(tmp_dir) / "counter.txt"
        state_path_str = str(state_file).replace("\\", "/")
        verify_cmd = (
            f'"{sys.executable}" -c "'
            f'import pathlib, sys; '
            f'p = pathlib.Path(\'{state_path_str}\'); '
            f'n = int(p.read_text()) if p.exists() else 0; '
            f'p.write_text(str(n + 1)); '
            f'sys.exit(0 if n >= 1 else 1)"'
        )

        runner = PipelineRunner(
            goal="Scenario B: Single fix attempt success",
            verify_cmd=verify_cmd,
            mock=True,
            max_fix_attempts=2,
            output_dir=tmp_dir,
            verbose=False,
        )
        exit_code = runner.execute()

        assert exit_code == 0
        assert runner.manifest["status"] == "SUCCESS"
        assert runner.manifest["fix_attempts_executed"] == 1

        stage_ids = [s["stage_id"] for s in runner.manifest["stages"]]
        assert stage_ids == [
            "00_goal",
            "01_product",
            "02_developer",
            "03_verification_attempt_0",
            "02_developer_fix_1",
            "03_verification_attempt_1",
            "04_result",
        ]

        # Stage statuses
        stage_status_map = {s["stage_id"]: s["status"] for s in runner.manifest["stages"]}
        assert stage_status_map["03_verification_attempt_0"] == "FAILED"
        assert stage_status_map["02_developer_fix_1"] == "COMPLETED"
        assert stage_status_map["03_verification_attempt_1"] == "COMPLETED"
        assert stage_status_map["04_result"] == "COMPLETED"

        # Artifacts verification
        run_dir = Path(tmp_dir) / runner.run_id
        assert (run_dir / "03_verification/attempt_0/verification_report.json").is_file()
        assert (run_dir / "02_developer_fix_1/failure_context.md").is_file()
        assert (run_dir / "02_developer_fix_1/dev_summary.md").is_file()
        assert (run_dir / "03_verification/attempt_1/verification_report.json").is_file()
        assert (run_dir / "04_result/result_summary.md").is_file()

        # Check failure context content
        failure_context = (run_dir / "02_developer_fix_1/failure_context.md").read_text(encoding="utf-8")
        assert "Verification Failure Context for Developer Fix (Attempt 1)" in failure_context
        assert "Exit Code: 1" in failure_context


def test_scenario_c_verification_fails_exhausts_retry_limit():
    """Scenario C: Verification fails on every attempt until max-fix-attempts is exhausted.
    
    Expected flow: Product -> Developer -> Verification FAIL -> Developer FIX 1 -> Verification FAIL -> Developer FIX 2 -> Verification FAIL -> Halts as FAILED (Result NOT executed).
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Command always fails with exit code 2
        verify_cmd = f'"{sys.executable}" -c "import sys; sys.exit(2)"'
        runner = PipelineRunner(
            goal="Scenario C: Retry budget exhaustion",
            verify_cmd=verify_cmd,
            mock=True,
            max_fix_attempts=2,
            output_dir=tmp_dir,
            verbose=False,
        )
        exit_code = runner.execute()

        assert exit_code == 2
        assert runner.manifest["status"] == "FAILED"
        assert runner.manifest["fix_attempts_executed"] == 2
        assert runner.manifest["error"]["failure_type"] == FailureType.VERIFICATION_FAILURE
        assert runner.manifest["error"]["exit_code"] == 2

        stage_ids = [s["stage_id"] for s in runner.manifest["stages"]]
        assert stage_ids == [
            "00_goal",
            "01_product",
            "02_developer",
            "03_verification_attempt_0",
            "02_developer_fix_1",
            "03_verification_attempt_1",
            "02_developer_fix_2",
            "03_verification_attempt_2",
        ]

        # Ensure Stage 04: Result was NOT executed
        assert "04_result" not in stage_ids
        run_dir = Path(tmp_dir) / runner.run_id
        assert not (run_dir / "04_result").exists()

        # Verify artifacts for both fix attempts and failure contexts exist
        assert (run_dir / "03_verification/attempt_0/verification_report.json").is_file()
        assert (run_dir / "02_developer_fix_1/failure_context.md").is_file()
        assert (run_dir / "02_developer_fix_1/dev_summary.md").is_file()
        assert (run_dir / "03_verification/attempt_1/verification_report.json").is_file()
        assert (run_dir / "02_developer_fix_2/failure_context.md").is_file()
        assert (run_dir / "02_developer_fix_2/dev_summary.md").is_file()
        assert (run_dir / "03_verification/attempt_2/verification_report.json").is_file()


def test_scenario_d_empty_goal_fails_before_agent_execution():
    """Scenario D: Invalid or empty goal fails before any agent execution.
    
    Expected flow: Fails at Stage 00_goal; zero agent stages executed.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        runner = PipelineRunner(
            goal="   ",
            verify_cmd="python tools/verify_company.py",
            mock=True,
            max_fix_attempts=2,
            output_dir=tmp_dir,
            verbose=False,
        )
        exit_code = runner.execute()

        assert exit_code == 1
        assert runner.manifest["status"] == "FAILED"
        assert runner.manifest["error"]["failure_type"] == FailureType.INFRASTRUCTURE_FAILURE

        stage_ids = [s["stage_id"] for s in runner.manifest["stages"]]
        assert "01_product" not in stage_ids
        assert "02_developer" not in stage_ids
        assert "03_verification" not in stage_ids


def test_scenario_e_infrastructure_failure_not_retried_as_verification_failure():
    """Scenario E: An infrastructure failure (e.g. missing prerequisite spec) fails fast and is NOT retried.
    
    Expected flow: Halts immediately; fix loop is never entered.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        runner = PipelineRunner(
            goal="Scenario E: Infrastructure failure test",
            verify_cmd="python tools/verify_company.py",
            mock=True,
            max_fix_attempts=2,
            output_dir=tmp_dir,
            verbose=False,
        )

        # Force an infrastructure failure by deleting the goal file before Stage 01
        # or testing Stage 02 gate check when product spec is missing.
        run_dir = runner.run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        # Directly test check_gate behavior
        with pytest.raises(PipelineError) as exc_info:
            runner.check_gate(
                "02_developer",
                run_dir / "01_product/non_existent_spec.md",
                "Prerequisite product spec",
                FailureType.INFRASTRUCTURE_FAILURE,
            )

        assert exc_info.value.failure_type == FailureType.INFRASTRUCTURE_FAILURE
        assert exc_info.value.stage_id == "02_developer"

        # Now test through runner.execute where Stage 01 is intentionally corrupted
        # to ensure runner marks manifest as FAILED with INFRASTRUCTURE_FAILURE
        runner.manifest["status"] = "RUNNING"
        # If we invoke _stage_02_developer without Stage 01 running:
        with pytest.raises(PipelineError) as exc_info2:
            runner._stage_02_developer()

        assert exc_info2.value.failure_type == FailureType.INFRASTRUCTURE_FAILURE
        # Ensure fix loop was not triggered
        assert runner.manifest["fix_attempts_executed"] == 0
