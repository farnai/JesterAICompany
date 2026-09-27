#!/usr/bin/env python3
"""
tools/run_pipeline.py - Jester AI Company Pipeline Runner (Hardened)

Sequential pipeline runner for AI-driven development workflows with a
controlled Developer -> Verification feedback loop.

Adheres strictly to the Jester AI Company core operating principles:
- Practical over complex
- Small change -> run -> test -> verify
- Do not move to the next stage until the current stage works
- Zero AI SDK imports / provider-agnostic
- Sequential execution with fail-fast gating
- Independent verification gate with bounded Developer fix retry loop
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional


class FailureType:
    """Classifies pipeline failure types to ensure appropriate handling."""
    INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
    DEVELOPER_FAILURE = "DEVELOPER_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"


class PipelineError(Exception):
    """Custom exception raised when a pipeline stage or gate fails."""
    def __init__(
        self,
        message: str,
        stage_id: str,
        exit_code: int = 1,
        failure_type: str = FailureType.INFRASTRUCTURE_FAILURE,
    ):
        super().__init__(message)
        self.stage_id = stage_id
        self.exit_code = exit_code
        self.failure_type = failure_type


class PipelineRunner:
    def __init__(
        self,
        goal: str,
        verify_cmd: Optional[str] = None,
        dry_run: bool = False,
        mock: bool = False,
        max_fix_attempts: int = 2,
        output_dir: str = ".runs",
        verbose: bool = False,
    ):
        self.goal = goal.strip()
        self.verify_cmd = verify_cmd if verify_cmd is not None else "python tools/verify_company.py"
        self.dry_run = dry_run
        self.mock = mock
        self.max_fix_attempts = max(0, int(max_fix_attempts))
        self.output_dir = Path(output_dir)
        self.verbose = verbose
        self.repo_root = Path(__file__).resolve().parent.parent

        # Run identifier and directory structure
        self.timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_id = f"run_{self.timestamp_str}"
        self.run_dir = self.output_dir / self.run_id

        # Manifest tracking
        self.manifest: Dict[str, Any] = {
            "run_id": self.run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "INITIALIZING",
            "options": {
                "dry_run": self.dry_run,
                "mock": self.mock,
                "verify_cmd": self.verify_cmd,
                "max_fix_attempts": self.max_fix_attempts,
                "output_dir": str(self.output_dir),
                "verbose": self.verbose,
            },
            "goal": self.goal,
            "fix_attempts_executed": 0,
            "stages": [],
            "completed_at": None,
            "error": None,
        }

    def log(self, message: str) -> None:
        """Log message with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[{ts}] {message}")

    def debug(self, message: str) -> None:
        """Log debug/verbose message if verbose flag is set."""
        if self.verbose:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"[{ts}] [DEBUG] {message}")

    def write_artifact(self, relative_path: str, content: str) -> Path:
        """Write content to an artifact file inside run_dir."""
        full_path = self.run_dir / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        self.debug(f"Wrote {len(content)} characters to {full_path}")
        return full_path

    def check_gate(
        self,
        stage_id: str,
        artifact_path: Path,
        description: str,
        failure_type: str = FailureType.INFRASTRUCTURE_FAILURE,
    ) -> None:
        """Fail-fast gate: Ensure artifact exists and is non-empty."""
        if not artifact_path.exists():
            raise PipelineError(
                f"Gate check failed for {stage_id}: Artifact {artifact_path} does not exist ({description})",
                stage_id,
                failure_type=failure_type,
            )
        file_size = artifact_path.stat().st_size
        if file_size == 0:
            raise PipelineError(
                f"Gate check failed for {stage_id}: Artifact {artifact_path} is empty (0 bytes) ({description})",
                stage_id,
                failure_type=failure_type,
            )
        self.debug(f"Gate passed for {stage_id}: {artifact_path.name} verified ({file_size} bytes).")

    def save_manifest(self) -> None:
        """Write run_manifest.json to run_dir."""
        if not self.dry_run:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = self.run_dir / "run_manifest.json"
            manifest_path.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
            self.debug(f"Updated manifest at {manifest_path}")

    def execute(self) -> int:
        """Execute the pipeline with feedback loop and fail-fast gating."""
        self.log(f"Starting pipeline run: {self.run_id}")
        self.log(f"Goal: {self.goal}")
        self.log(f"Mode: {'DRY-RUN' if self.dry_run else 'MOCK' if self.mock else 'LIVE'}")
        self.log(f"Max Fix Attempts: {self.max_fix_attempts}")

        if self.dry_run:
            return self._execute_dry_run()

        try:
            self.manifest["status"] = "RUNNING"
            self.save_manifest()

            # Stage 00: Goal
            self._stage_00_goal()

            # Stage 01: Product
            self._stage_01_product()

            # Stage 02: Initial Developer Implementation (attempt 0)
            self._stage_02_developer()

            # Stage 03 & Fix Loop: Verification and Developer Feedback Loop
            current_attempt = 0
            while True:
                veri_report = self._run_verification(attempt=current_attempt)
                if veri_report["passed"]:
                    self.log(f"Verification passed on attempt {current_attempt}.")
                    break

                # Verification failed on this attempt
                self.log(
                    f"Verification FAILED on attempt {current_attempt} with exit code {veri_report['exit_code']}."
                )

                if current_attempt >= self.max_fix_attempts:
                    self.log(
                        f"Maximum fix attempts ({self.max_fix_attempts}) exhausted. Halting pipeline."
                    )
                    raise PipelineError(
                        f"Verification failed on attempt {current_attempt} with exit code {veri_report['exit_code']} (max fix attempts exhausted):\n{veri_report['stderr'] or veri_report['stdout']}",
                        stage_id=f"03_verification_attempt_{current_attempt}",
                        exit_code=veri_report["exit_code"],
                        failure_type=FailureType.VERIFICATION_FAILURE,
                    )

                # Advance to next fix attempt
                current_attempt += 1
                self.manifest["fix_attempts_executed"] = current_attempt
                self.save_manifest()

                self.log(
                    f"Entering Developer Fix loop: Attempt {current_attempt} of {self.max_fix_attempts}..."
                )
                self._stage_02_developer_fix(attempt=current_attempt, prev_veri_report=veri_report)

            # Stage 04: Result
            self._stage_04_result(total_fix_attempts=current_attempt)

            self.manifest["status"] = "SUCCESS"
            self.manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.save_manifest()
            self.log(f"Pipeline completed successfully. All artifacts written to: {self.run_dir}")
            return 0

        except PipelineError as e:
            self.log(f"ERROR: Pipeline halted at stage [{e.stage_id}] [{e.failure_type}]: {e}")
            self.manifest["status"] = "FAILED"
            self.manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.manifest["error"] = {
                "stage": e.stage_id,
                "failure_type": e.failure_type,
                "message": str(e),
                "exit_code": e.exit_code,
            }
            self.save_manifest()
            return e.exit_code
        except Exception as e:
            self.log(f"UNEXPECTED ERROR: {e}")
            self.manifest["status"] = "FAILED"
            self.manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.manifest["error"] = {
                "stage": "UNKNOWN",
                "failure_type": FailureType.INFRASTRUCTURE_FAILURE,
                "message": str(e),
                "exit_code": 1,
            }
            self.save_manifest()
            return 1

    def _execute_dry_run(self) -> int:
        self.log("Dry run requested. Validating pipeline plan and parameters:")
        print(f"  Target Run Directory: {self.run_dir}")
        print(f"  Max Fix Attempts: {self.max_fix_attempts}")
        print("  Planned Stage Execution Plan:")
        print("    1. [00_goal] -> 00_goal/goal.txt")
        print("    2. [01_product] -> 01_product/product_spec.md, stdout.log, stderr.log")
        print("    3. [02_developer] -> 02_developer/dev_summary.md, stdout.log, stderr.log (Initial Implementation - Attempt 0)")
        print(f"    4. [03_verification] -> Verification attempt 0. On failure, up to {self.max_fix_attempts} Developer fix cycles.")
        print(f"       Verification Command: {self.verify_cmd}")
        print("    5. [04_result] -> 04_result/result_summary.md")
        print("    6. [manifest] -> run_manifest.json")
        print("  Fail-fast gating: Enabled (halts on infrastructure failure or retry budget exhaustion)")

        if not self.goal:
            print("  ERROR: Goal is empty. Dry-run validation failed.", file=sys.stderr)
            return 1

        print("  Dry-run validation PASSED. No files created or modified.")
        return 0

    def _record_stage(
        self,
        stage_id: str,
        name: str,
        status: str,
        artifacts: List[str],
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        stage_record = {
            "stage_id": stage_id,
            "name": name,
            "status": status,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "artifacts": artifacts,
            "details": details or {},
        }
        self.manifest["stages"].append(stage_record)
        self.save_manifest()

    def _stage_00_goal(self) -> None:
        stage_id = "00_goal"
        self.log(f"--- Stage {stage_id}: Ingesting Goal ---")
        if not self.goal:
            raise PipelineError(
                "Goal content is empty",
                stage_id,
                failure_type=FailureType.INFRASTRUCTURE_FAILURE,
            )

        artifact_rel = "00_goal/goal.txt"
        artifact_path = self.write_artifact(artifact_rel, self.goal + "\n")
        self.check_gate(stage_id, artifact_path, "Goal artifact", FailureType.INFRASTRUCTURE_FAILURE)
        self._record_stage(stage_id, "Goal Ingestion", "COMPLETED", [artifact_rel])

    def _stage_01_product(self) -> None:
        stage_id = "01_product"
        self.log(f"--- Stage {stage_id}: Generating Product Specification ---")

        goal_path = self.run_dir / "00_goal/goal.txt"
        self.check_gate(stage_id, goal_path, "Prerequisite goal file", FailureType.INFRASTRUCTURE_FAILURE)

        artifacts = []
        if self.mock:
            self.debug("Mock mode: synthesizing product specification.")
            content = (
                f"# Product Specification\n\n"
                f"**Run ID:** `{self.run_id}`\n"
                f"**Status:** Approved for Implementation\n\n"
                f"## Objective\n"
                f"{self.goal}\n\n"
                f"## Scope & Boundaries\n"
                f"- Work strictly within the JesterAICompany repository boundaries.\n"
                f"- Strictly no modifications to Jester or JesterBridge.\n"
                f"- Use Python 3 standard library only; zero AI SDK imports.\n\n"
                f"## Acceptance Criteria\n"
                f"1. Command line interface options must match specification.\n"
                f"2. Run directory and artifact structure generated under `.runs/<run_id>/`.\n"
                f"3. Sequential execution with strict fail-fast gating on empty output or non-zero exit codes.\n"
                f"4. Generation of valid `run_manifest.json` tracking stage progression.\n"
            )
            stdout_content = "[MOCK] Product agent executed successfully. Specification formulated.\n"
            stderr_content = ""
        else:
            prompt = (
                f"Define the minimum product requirements, scope (IN/OUT), and acceptance criteria for: {self.goal}. "
                f"Output using standard Product format."
            )
            cmd = ["agy", "--add-dir", str(self.repo_root), "--agent", "product", "--dangerously-skip-permissions", "-p", prompt]
            self.log("Executing Product stage command via agy...")
            try:
                proc = subprocess.run(cmd, cwd=self.repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            except Exception as e:
                raise PipelineError(f"Failed to execute Product agent command: {e}", stage_id, failure_type=FailureType.INFRASTRUCTURE_FAILURE)

            stdout_content = proc.stdout
            stderr_content = proc.stderr
            if proc.returncode != 0:
                self.write_artifact("01_product/stdout.log", stdout_content)
                self.write_artifact("01_product/stderr.log", stderr_content)
                raise PipelineError(
                    f"Product stage failed with exit code {proc.returncode}:\n{stderr_content or stdout_content}",
                    stage_id,
                    exit_code=proc.returncode,
                    failure_type=FailureType.INFRASTRUCTURE_FAILURE,
                )
            content = proc.stdout

        spec_rel = "01_product/product_spec.md"
        spec_path = self.write_artifact(spec_rel, content)
        stdout_rel = "01_product/stdout.log"
        self.write_artifact(stdout_rel, stdout_content)
        stderr_rel = "01_product/stderr.log"
        self.write_artifact(stderr_rel, stderr_content)

        self.check_gate(stage_id, spec_path, "Product spec artifact", FailureType.INFRASTRUCTURE_FAILURE)
        artifacts.extend([spec_rel, stdout_rel, stderr_rel])
        self._record_stage(stage_id, "Product Specification", "COMPLETED", artifacts)

    def _stage_02_developer(self) -> None:
        stage_id = "02_developer"
        self.log(f"--- Stage {stage_id}: Developer Implementation (Attempt 0) ---")

        spec_path = self.run_dir / "01_product/product_spec.md"
        self.check_gate(stage_id, spec_path, "Prerequisite product spec", FailureType.INFRASTRUCTURE_FAILURE)

        artifacts = []
        if self.mock:
            self.debug("Mock mode: synthesizing developer implementation.")
            content = (
                f"# Developer Implementation Summary\n\n"
                f"**Run ID:** `{self.run_id}`\n"
                f"**Attempt:** 0\n"
                f"**Execution Timestamp:** {datetime.now(timezone.utc).isoformat()}\n\n"
                f"## Plan of Record\n"
                f"Implemented pipeline execution engine satisfying product specifications:\n"
                f"- Implemented `tools/run_pipeline.py` with standard library CLI parser.\n"
                f"- Enforced stage gating checks before and after artifact production.\n"
                f"- Recorded stage artifacts and telemetry into run manifest.\n\n"
                f"## Boundaries & Integrity\n"
                f"- Zero third-party dependencies utilized.\n"
                f"- Repositories Jester and JesterBridge untouched.\n"
            )
            stdout_content = "[MOCK] Developer agent executed successfully. Implementation documented.\n"
            stderr_content = ""
        else:
            product_spec_text = spec_path.read_text(encoding="utf-8")
            prompt = (
                f"Implement the requested changes according to this product specification:\n{product_spec_text}\n"
                f"Report in standard Developer format."
            )
            cmd = ["agy", "--add-dir", str(self.repo_root), "--agent", "developer", "--dangerously-skip-permissions", "-p", prompt]
            self.log("Executing Developer stage command via agy...")
            try:
                proc = subprocess.run(cmd, cwd=self.repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            except Exception as e:
                raise PipelineError(f"Failed to execute Developer agent command: {e}", stage_id, failure_type=FailureType.DEVELOPER_FAILURE)

            stdout_content = proc.stdout
            stderr_content = proc.stderr
            if proc.returncode != 0:
                self.write_artifact("02_developer/stdout.log", stdout_content)
                self.write_artifact("02_developer/stderr.log", stderr_content)
                raise PipelineError(
                    f"Developer stage failed with exit code {proc.returncode}:\n{stderr_content or stdout_content}",
                    stage_id,
                    exit_code=proc.returncode,
                    failure_type=FailureType.DEVELOPER_FAILURE,
                )
            content = proc.stdout

        summary_rel = "02_developer/dev_summary.md"
        summary_path = self.write_artifact(summary_rel, content)
        stdout_rel = "02_developer/stdout.log"
        self.write_artifact(stdout_rel, stdout_content)
        stderr_rel = "02_developer/stderr.log"
        self.write_artifact(stderr_rel, stderr_content)

        self.check_gate(stage_id, summary_path, "Developer summary artifact", FailureType.DEVELOPER_FAILURE)
        artifacts.extend([summary_rel, stdout_rel, stderr_rel])
        self._record_stage(
            stage_id,
            "Developer Implementation",
            "COMPLETED",
            artifacts,
            details={"attempt": 0, "fix_attempt": False},
        )

    def _run_verification(self, attempt: int) -> Dict[str, Any]:
        """Execute verification command for a given attempt and record results."""
        stage_id = f"03_verification_attempt_{attempt}"
        self.log(f"--- Stage 03_verification: Verification (Attempt {attempt}) ---")

        # Verify prerequisite developer summary exists
        if attempt == 0:
            dev_path = self.run_dir / "02_developer/dev_summary.md"
        else:
            dev_path = self.run_dir / f"02_developer_fix_{attempt}/dev_summary.md"

        self.check_gate(
            stage_id,
            dev_path,
            f"Prerequisite developer summary for attempt {attempt}",
            FailureType.INFRASTRUCTURE_FAILURE,
        )

        report: Dict[str, Any] = {
            "run_id": self.run_id,
            "attempt": attempt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": self.verify_cmd,
            "passed": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "duration_seconds": 0.0,
        }

        self.log(f"Executing verification command: {self.verify_cmd}")
        start_time = datetime.now(timezone.utc)
        try:
            proc = subprocess.run(
                self.verify_cmd,
                cwd=self.repo_root,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            raise PipelineError(
                f"Failed to execute verification command: {e}",
                stage_id,
                failure_type=FailureType.INFRASTRUCTURE_FAILURE,
            )

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        report["exit_code"] = proc.returncode
        report["stdout"] = proc.stdout
        report["stderr"] = proc.stderr
        report["duration_seconds"] = duration
        report["passed"] = (proc.returncode == 0)

        # Write attempt-specific verification artifacts
        attempt_stdout_rel = f"03_verification/attempt_{attempt}/stdout.log"
        self.write_artifact(attempt_stdout_rel, proc.stdout)
        attempt_stderr_rel = f"03_verification/attempt_{attempt}/stderr.log"
        self.write_artifact(attempt_stderr_rel, proc.stderr)
        attempt_report_rel = f"03_verification/attempt_{attempt}/verification_report.json"
        artifact_path = self.write_artifact(attempt_report_rel, json.dumps(report, indent=2))

        # Mirror to canonical paths for downstream reference
        self.write_artifact("03_verification/stdout.log", proc.stdout)
        self.write_artifact("03_verification/stderr.log", proc.stderr)
        self.write_artifact("03_verification/verification_report.json", json.dumps(report, indent=2))

        artifacts = [attempt_report_rel, attempt_stdout_rel, attempt_stderr_rel]

        if not report["passed"]:
            fix_requested = (attempt < self.max_fix_attempts)
            report_details = dict(report)
            report_details["fix_requested"] = fix_requested
            self._record_stage(
                stage_id,
                f"Verification (Attempt {attempt})",
                "FAILED",
                artifacts,
                details=report_details,
            )
            return report

        self.check_gate(stage_id, artifact_path, "Verification report artifact", FailureType.INFRASTRUCTURE_FAILURE)
        report_details = dict(report)
        report_details["fix_requested"] = False
        self._record_stage(
            stage_id,
            f"Verification (Attempt {attempt})",
            "COMPLETED",
            artifacts,
            details=report_details,
        )
        return report

    def _stage_02_developer_fix(self, attempt: int, prev_veri_report: Dict[str, Any]) -> None:
        """Execute Developer fix stage providing full context of previous verification failure."""
        stage_id = f"02_developer_fix_{attempt}"
        self.log(f"--- Stage {stage_id}: Developer Fix (Attempt {attempt} of {self.max_fix_attempts}) ---")

        spec_path = self.run_dir / "01_product/product_spec.md"
        self.check_gate(stage_id, spec_path, "Prerequisite product spec", FailureType.INFRASTRUCTURE_FAILURE)
        product_spec_text = spec_path.read_text(encoding="utf-8")

        # Load previous developer summary
        if attempt == 1:
            prev_dev_path = self.run_dir / "02_developer/dev_summary.md"
        else:
            prev_dev_path = self.run_dir / f"02_developer_fix_{attempt - 1}/dev_summary.md"
        self.check_gate(stage_id, prev_dev_path, "Previous developer summary", FailureType.INFRASTRUCTURE_FAILURE)
        prev_dev_summary = prev_dev_path.read_text(encoding="utf-8")

        # Compose structured failure context for Developer
        failure_context = (
            f"# Verification Failure Context for Developer Fix (Attempt {attempt})\n\n"
            f"## 1. Failure Summary\n"
            f"- Stage: `03_verification`\n"
            f"- Attempt: {prev_veri_report.get('attempt', 0)}\n"
            f"- Exit Code: {prev_veri_report.get('exit_code')}\n"
            f"- Command: `{prev_veri_report.get('command')}`\n\n"
            f"## 2. Verification Standard Output\n"
            f"```text\n{prev_veri_report.get('stdout', '')}\n```\n\n"
            f"## 3. Verification Standard Error\n"
            f"```text\n{prev_veri_report.get('stderr', '')}\n```\n\n"
            f"## 4. Expected Behavior (Product Specification)\n"
            f"{product_spec_text}\n\n"
            f"## 5. Current Implementation (Previous Developer Summary)\n"
            f"{prev_dev_summary}\n\n"
            f"## 6. Attempt Lifecycle\n"
            f"- Current Fix Attempt: {attempt}\n"
            f"- Max Allowed Fix Attempts: {self.max_fix_attempts}\n"
        )
        context_rel = f"02_developer_fix_{attempt}/failure_context.md"
        self.write_artifact(context_rel, failure_context)

        artifacts = [context_rel]
        if self.mock:
            self.debug(f"Mock mode: synthesizing developer fix for attempt {attempt}.")
            content = (
                f"# Developer Fix Implementation Summary (Attempt {attempt})\n\n"
                f"**Run ID:** `{self.run_id}`\n"
                f"**Fix Attempt:** {attempt} of {self.max_fix_attempts}\n"
                f"**Execution Timestamp:** {datetime.now(timezone.utc).isoformat()}\n\n"
                f"## Failure Diagnosis & Action\n"
                f"Addressed failure from previous verification attempt {prev_veri_report.get('attempt')}:\n"
                f"- Inspected failure context in `{context_rel}`.\n"
                f"- Applied required code and configuration corrections.\n"
                f"- Preserved repository boundaries.\n"
            )
            stdout_content = f"[MOCK] Developer fix attempt {attempt} executed successfully.\n"
            stderr_content = ""
        else:
            prompt = (
                f"You are tasked with fixing an implementation that failed verification.\n"
                f"Carefully review the failure details, verification output, product specification, and previous implementation:\n\n"
                f"{failure_context}\n\n"
                f"Please implement the necessary fixes to resolve the verification failure and satisfy all product requirements.\n"
                f"Run tests and verify your changes.\n"
                f"Report in standard Developer format."
            )
            cmd = ["agy", "--add-dir", str(self.repo_root), "--agent", "developer", "--dangerously-skip-permissions", "-p", prompt]
            self.log(f"Executing Developer fix command via agy (attempt {attempt})...")
            try:
                proc = subprocess.run(cmd, cwd=self.repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            except Exception as e:
                raise PipelineError(f"Failed to execute Developer fix agent command: {e}", stage_id, failure_type=FailureType.DEVELOPER_FAILURE)

            stdout_content = proc.stdout
            stderr_content = proc.stderr
            if proc.returncode != 0:
                self.write_artifact(f"02_developer_fix_{attempt}/stdout.log", stdout_content)
                self.write_artifact(f"02_developer_fix_{attempt}/stderr.log", stderr_content)
                raise PipelineError(
                    f"Developer fix stage {stage_id} failed with exit code {proc.returncode}:\n{stderr_content or stdout_content}",
                    stage_id,
                    exit_code=proc.returncode,
                    failure_type=FailureType.DEVELOPER_FAILURE,
                )
            content = proc.stdout

        summary_rel = f"02_developer_fix_{attempt}/dev_summary.md"
        summary_path = self.write_artifact(summary_rel, content)
        stdout_rel = f"02_developer_fix_{attempt}/stdout.log"
        self.write_artifact(stdout_rel, stdout_content)
        stderr_rel = f"02_developer_fix_{attempt}/stderr.log"
        self.write_artifact(stderr_rel, stderr_content)

        self.check_gate(stage_id, summary_path, "Developer fix summary artifact", FailureType.DEVELOPER_FAILURE)
        artifacts.extend([summary_rel, stdout_rel, stderr_rel])
        self._record_stage(
            stage_id,
            f"Developer Fix (Attempt {attempt})",
            "COMPLETED",
            artifacts,
            details={
                "attempt": attempt,
                "fix_requested": True,
                "resolved_previous_attempt": prev_veri_report.get("attempt"),
            },
        )

    def _stage_04_result(self, total_fix_attempts: int) -> None:
        stage_id = "04_result"
        self.log(f"--- Stage {stage_id}: Aggregating Result Summary ---")

        veri_path = self.run_dir / "03_verification/verification_report.json"
        self.check_gate(stage_id, veri_path, "Prerequisite verification report", FailureType.INFRASTRUCTURE_FAILURE)

        content = (
            f"# Pipeline Run Result Summary\n\n"
            f"- **Run ID:** `{self.run_id}`\n"
            f"- **Status:** SUCCESS\n"
            f"- **Goal:** {self.goal}\n"
            f"- **Fix Attempts Executed:** {total_fix_attempts} (max allowed: {self.max_fix_attempts})\n"
            f"- **Completed At:** {datetime.now(timezone.utc).isoformat()}\n\n"
            f"## Executed Stages\n"
            f"1. `00_goal`: Ingested goal and verified non-empty.\n"
            f"2. `01_product`: Generated approved product specification.\n"
            f"3. `02_developer`: Implemented code changes (attempt 0).\n"
            f"4. `03_verification`: Executed verification with feedback loop ({total_fix_attempts} fix cycles).\n"
            f"5. `04_result`: Synthesized run outcomes and manifest.\n\n"
            f"## Artifacts\n"
            f"All artifacts and `run_manifest.json` have been committed under `{self.run_dir}`.\n"
        )
        artifact_rel = "04_result/result_summary.md"
        artifact_path = self.write_artifact(artifact_rel, content)
        self.check_gate(stage_id, artifact_path, "Result summary artifact", FailureType.INFRASTRUCTURE_FAILURE)
        self._record_stage(stage_id, "Result Summary", "COMPLETED", [artifact_rel])


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Jester AI Company sequential pipeline runner with feedback loop and fail-fast gating.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    goal_group = parser.add_mutually_exclusive_group(required=True)
    goal_group.add_argument(
        "--goal",
        type=str,
        help="Direct goal string describing the pipeline objective.",
    )
    goal_group.add_argument(
        "--goal-file",
        type=str,
        help="Path to a text file containing the pipeline objective.",
    )
    parser.add_argument(
        "--verify-cmd",
        type=str,
        default="python tools/verify_company.py",
        help="Verification command to execute in stage 03 (default: python tools/verify_company.py).",
    )
    parser.add_argument(
        "--max-fix-attempts",
        type=int,
        default=2,
        help="Maximum number of Developer fix attempts after verification failure (default: 2).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate pipeline execution and print stage plan without writing artifacts.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run offline mock pipeline generating mock stage artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".runs",
        help="Base directory for run outputs (default: .runs).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output logging.",
    )
    return parser.parse_args(args)


def main(cli_args: Optional[List[str]] = None) -> int:
    args = parse_args(cli_args)

    if args.goal_file:
        goal_path = Path(args.goal_file)
        if not goal_path.exists():
            print(f"Error: Goal file not found: {args.goal_file}", file=sys.stderr)
            return 1
        goal = goal_path.read_text(encoding="utf-8").strip()
    else:
        goal = args.goal.strip()

    if not goal:
        print("Error: Provided goal is empty.", file=sys.stderr)
        return 1

    runner = PipelineRunner(
        goal=goal,
        verify_cmd=args.verify_cmd,
        dry_run=args.dry_run,
        mock=args.mock,
        max_fix_attempts=args.max_fix_attempts,
        output_dir=args.output_dir,
        verbose=args.verbose,
    )
    return runner.execute()


if __name__ == "__main__":
    sys.exit(main())
