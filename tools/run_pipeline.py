#!/usr/bin/env python3
"""
tools/run_pipeline.py - Jester AI Company Pipeline Runner MVP

Sequential pipeline runner for AI-driven development workflows.
Adheres strictly to the Jester AI Company core operating principles:
- Practical over complex
- Small change -> run -> test -> verify
- Do not move to the next stage until the current stage works
- Zero AI SDK imports / provider-agnostic
- Sequential execution with fail-fast gating
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional


class PipelineError(Exception):
    """Custom exception raised when a pipeline stage or gate fails."""
    def __init__(self, message: str, stage_id: str, exit_code: int = 1):
        super().__init__(message)
        self.stage_id = stage_id
        self.exit_code = exit_code


class PipelineRunner:
    def __init__(
        self,
        goal: str,
        verify_cmd: Optional[str] = None,
        dry_run: bool = False,
        mock: bool = False,
        output_dir: str = ".runs",
        verbose: bool = False,
    ):
        self.goal = goal.strip()
        self.verify_cmd = verify_cmd if verify_cmd is not None else "python tools/verify_company.py"
        self.dry_run = dry_run
        self.mock = mock
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
                "output_dir": str(self.output_dir),
                "verbose": self.verbose,
            },
            "goal": self.goal,
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

    def check_gate(self, stage_id: str, artifact_path: Path, description: str) -> None:
        """Fail-fast gate: Ensure artifact exists and is non-empty."""
        if not artifact_path.exists():
            raise PipelineError(f"Gate check failed for {stage_id}: Artifact {artifact_path} does not exist", stage_id)
        file_size = artifact_path.stat().st_size
        if file_size == 0:
            raise PipelineError(f"Gate check failed for {stage_id}: Artifact {artifact_path} is empty (0 bytes)", stage_id)
        self.debug(f"Gate passed for {stage_id}: {artifact_path.name} verified ({file_size} bytes).")

    def save_manifest(self) -> None:
        """Write run_manifest.json to run_dir."""
        if not self.dry_run:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = self.run_dir / "run_manifest.json"
            manifest_path.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")
            self.debug(f"Updated manifest at {manifest_path}")

    def execute(self) -> int:
        """Execute the sequential pipeline with fail-fast gating."""
        self.log(f"Starting pipeline run: {self.run_id}")
        self.log(f"Goal: {self.goal}")
        self.log(f"Mode: {'DRY-RUN' if self.dry_run else 'MOCK' if self.mock else 'LIVE'}")

        if self.dry_run:
            return self._execute_dry_run()

        try:
            self.manifest["status"] = "RUNNING"
            self.save_manifest()

            # Stage 00: Goal
            self._stage_00_goal()

            # Stage 01: Product
            self._stage_01_product()

            # Stage 02: Developer
            self._stage_02_developer()

            # Stage 03: Verification
            self._stage_03_verification()

            # Stage 04: Result
            self._stage_04_result()

            self.manifest["status"] = "SUCCESS"
            self.manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.save_manifest()
            self.log(f"Pipeline completed successfully. All artifacts written to: {self.run_dir}")
            return 0

        except PipelineError as e:
            self.log(f"ERROR: Pipeline halted at stage [{e.stage_id}]: {e}")
            self.manifest["status"] = "FAILED"
            self.manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.manifest["error"] = {
                "stage": e.stage_id,
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
                "message": str(e),
                "exit_code": 1,
            }
            self.save_manifest()
            return 1

    def _execute_dry_run(self) -> int:
        self.log("Dry run requested. Validating pipeline plan and parameters:")
        print(f"  Target Run Directory: {self.run_dir}")
        print("  Planned Stage Execution Plan:")
        print("    1. [00_goal] -> 00_goal/goal.txt")
        print("    2. [01_product] -> 01_product/product_spec.md, stdout.log, stderr.log")
        print("    3. [02_developer] -> 02_developer/dev_summary.md, stdout.log, stderr.log")
        print("    4. [03_verification] -> 03_verification/verification_report.json, stdout.log, stderr.log")
        print(f"       Verification Command: {self.verify_cmd}")
        print("    5. [04_result] -> 04_result/result_summary.md")
        print("    6. [manifest] -> run_manifest.json")
        print("  Fail-fast gating: Enabled (halts on non-zero exit code or empty output)")

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
            raise PipelineError("Goal content is empty", stage_id)

        artifact_rel = "00_goal/goal.txt"
        artifact_path = self.write_artifact(artifact_rel, self.goal + "\n")
        self.check_gate(stage_id, artifact_path, "Goal artifact")
        self._record_stage(stage_id, "Goal Ingestion", "COMPLETED", [artifact_rel])

    def _stage_01_product(self) -> None:
        stage_id = "01_product"
        self.log(f"--- Stage {stage_id}: Generating Product Specification ---")

        goal_path = self.run_dir / "00_goal/goal.txt"
        self.check_gate("00_goal", goal_path, "Prerequisite goal file")

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
            self.log(f"Executing Product stage command via agy...")
            proc = subprocess.run(cmd, cwd=self.repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            stdout_content = proc.stdout
            stderr_content = proc.stderr
            if proc.returncode != 0:
                self.write_artifact("01_product/stdout.log", stdout_content)
                self.write_artifact("01_product/stderr.log", stderr_content)
                raise PipelineError(f"Product stage failed with exit code {proc.returncode}:\n{stderr_content or stdout_content}", stage_id, exit_code=proc.returncode)
            content = proc.stdout

        spec_rel = "01_product/product_spec.md"
        spec_path = self.write_artifact(spec_rel, content)
        stdout_rel = "01_product/stdout.log"
        self.write_artifact(stdout_rel, stdout_content)
        stderr_rel = "01_product/stderr.log"
        self.write_artifact(stderr_rel, stderr_content)

        self.check_gate(stage_id, spec_path, "Product spec artifact")
        artifacts.extend([spec_rel, stdout_rel, stderr_rel])
        self._record_stage(stage_id, "Product Specification", "COMPLETED", artifacts)

    def _stage_02_developer(self) -> None:
        stage_id = "02_developer"
        self.log(f"--- Stage {stage_id}: Developer Implementation ---")

        spec_path = self.run_dir / "01_product/product_spec.md"
        self.check_gate("01_product", spec_path, "Prerequisite product spec")

        artifacts = []
        if self.mock:
            self.debug("Mock mode: synthesizing developer implementation.")
            content = (
                f"# Developer Implementation Summary\n\n"
                f"**Run ID:** `{self.run_id}`\n"
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
            self.log(f"Executing Developer stage command via agy...")
            proc = subprocess.run(cmd, cwd=self.repo_root, capture_output=True, text=True, encoding="utf-8", errors="replace")
            stdout_content = proc.stdout
            stderr_content = proc.stderr
            if proc.returncode != 0:
                self.write_artifact("02_developer/stdout.log", stdout_content)
                self.write_artifact("02_developer/stderr.log", stderr_content)
                raise PipelineError(f"Developer stage failed with exit code {proc.returncode}:\n{stderr_content or stdout_content}", stage_id, exit_code=proc.returncode)
            content = proc.stdout

        summary_rel = "02_developer/dev_summary.md"
        summary_path = self.write_artifact(summary_rel, content)
        stdout_rel = "02_developer/stdout.log"
        self.write_artifact(stdout_rel, stdout_content)
        stderr_rel = "02_developer/stderr.log"
        self.write_artifact(stderr_rel, stderr_content)

        self.check_gate(stage_id, summary_path, "Developer summary artifact")
        artifacts.extend([summary_rel, stdout_rel, stderr_rel])
        self._record_stage(stage_id, "Developer Implementation", "COMPLETED", artifacts)

    def _stage_03_verification(self) -> None:
        stage_id = "03_verification"
        self.log(f"--- Stage {stage_id}: Verification ---")

        dev_path = self.run_dir / "02_developer/dev_summary.md"
        self.check_gate("02_developer", dev_path, "Prerequisite developer summary")

        report: Dict[str, Any] = {
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": self.verify_cmd,
            "passed": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }

        self.log(f"Executing verification command: {self.verify_cmd}")
        start_time = datetime.now(timezone.utc)
        proc = subprocess.run(
            self.verify_cmd,
            cwd=self.repo_root,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        report["exit_code"] = proc.returncode
        report["stdout"] = proc.stdout
        report["stderr"] = proc.stderr
        report["duration_seconds"] = duration
        report["passed"] = (proc.returncode == 0)

        stdout_rel = "03_verification/stdout.log"
        self.write_artifact(stdout_rel, proc.stdout)
        stderr_rel = "03_verification/stderr.log"
        self.write_artifact(stderr_rel, proc.stderr)
        report_rel = "03_verification/verification_report.json"
        artifact_path = self.write_artifact(report_rel, json.dumps(report, indent=2))

        artifacts = [report_rel, stdout_rel, stderr_rel]

        if proc.returncode != 0:
            self._record_stage(stage_id, "Verification", "FAILED", artifacts, details=report)
            raise PipelineError(
                f"Verification command failed with exit code {proc.returncode}:\n{proc.stderr or proc.stdout}",
                stage_id,
                exit_code=proc.returncode,
            )

        self.check_gate(stage_id, artifact_path, "Verification report artifact")
        self._record_stage(stage_id, "Verification", "COMPLETED", artifacts, details=report)

    def _stage_04_result(self) -> None:
        stage_id = "04_result"
        self.log(f"--- Stage {stage_id}: Aggregating Result Summary ---")

        veri_path = self.run_dir / "03_verification/verification_report.json"
        self.check_gate("03_verification", veri_path, "Prerequisite verification report")

        content = (
            f"# Pipeline Run Result Summary\n\n"
            f"- **Run ID:** `{self.run_id}`\n"
            f"- **Status:** SUCCESS\n"
            f"- **Goal:** {self.goal}\n"
            f"- **Completed At:** {datetime.now(timezone.utc).isoformat()}\n\n"
            f"## Executed Stages\n"
            f"1. `00_goal`: Ingested goal and verified non-empty.\n"
            f"2. `01_product`: Generated approved product specification.\n"
            f"3. `02_developer`: Documented developer implementation.\n"
            f"4. `03_verification`: Executed verification checks (passed).\n"
            f"5. `04_result`: Synthesized run outcomes and manifest.\n\n"
            f"## Artifacts\n"
            f"All artifacts and `run_manifest.json` have been committed under `{self.run_dir}`.\n"
        )
        artifact_rel = "04_result/result_summary.md"
        artifact_path = self.write_artifact(artifact_rel, content)
        self.check_gate(stage_id, artifact_path, "Result summary artifact")
        self._record_stage(stage_id, "Result Summary", "COMPLETED", [artifact_rel])


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Jester AI Company sequential pipeline runner with fail-fast gating.",
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
        output_dir=args.output_dir,
        verbose=args.verbose,
    )
    return runner.execute()


if __name__ == "__main__":
    sys.exit(main())
