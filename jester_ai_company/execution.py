"""Execution engine connecting the Universal Company Core to real execution.

Bridges Company, Project, Task, and TaskRun models with CEO orchestration,
specialist delegation, and independent QA verification.

Flow:
    Project Context + Task
             ↓
     TaskRun (attempt N)
             ↓
     CEO Orchestration (native invoke_subagent delegation)
             ↓
     Selected Specialists Execution & Artifact Generation
             ↓
     Independent QA Verification (VerificationResult)
             ↓
     TaskResult Generation (or retry with attempt N+1 on failure)
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional
import uuid

from .core import (
    Artifact,
    ArtifactType,
    Company,
    Employee,
    Project,
    RunStatus,
    Task,
    TaskResult,
    TaskRun,
    TaskStatus,
    VerificationResult,
    create_default_company,
)
from .registry import get_agent_inventory


class TaskExecutor:
    """Executes a Task within a Project context using Company employees."""

    def __init__(
        self,
        company: Optional[Company] = None,
        output_dir: str = ".runs",
        verbose: bool = False,
        repo_root: Optional[Path] = None,
    ):
        self.repo_root = repo_root or Path(__file__).resolve().parent.parent
        self.company = company or create_default_company(self.repo_root)
        self.output_dir = Path(output_dir)
        self.verbose = verbose

    def _log(self, message: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"[{ts}] [TaskExecutor] {message}")

    def _debug(self, message: str) -> None:
        if self.verbose:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"[{ts}] [TaskExecutor:DEBUG] {message}")

    def build_project_context(self, task: Task, project: Project) -> Dict[str, Any]:
        """Synthesize project context payload for agent consumption."""
        return {
            "project_id": project.id,
            "project_name": project.name,
            "root_path": str(project.root_path),
            "tech_stack": project.tech_stack,
            "conventions": project.conventions,
            "task_id": task.id,
            "task_title": task.title,
            "task_goal": task.goal,
            "task_constraints": task.constraints,
            "required_roles": task.required_roles,
        }

    def execute_task(
        self,
        task: Task,
        project: Optional[Project] = None,
        verify_cmd: Optional[str] = None,
        mock: bool = False,
        dry_run: bool = False,
        max_fix_attempts: int = 2,
    ) -> TaskRun:
        """Execute a TaskRun for the given Task within its Project context.

        If verification fails, records the failed TaskRun on the Task.
        A subsequent call creates a new TaskRun with incremented attempt_number.
        """
        # Resolve project
        proj = project
        if proj is None:
            proj = self.company.projects.get(task.project_id)
        if proj is None:
            # Fallback self-hosting project
            proj = Project(
                id=task.project_id or "default-project",
                name="Default Project",
                root_path=str(self.repo_root),
                tech_stack=["Python"],
            )

        # 1. Create a new TaskRun on the Task (preserves attempt numbering)
        run = task.create_run()
        run.status = RunStatus.RUNNING.value

        self._log(
            f"Starting execution for Task '{task.id}' (Attempt #{run.attempt_number}) "
            f"in Project '{proj.name}' [{proj.id}]"
        )

        if dry_run:
            self._log(f"Dry-run mode: Simulating execution for Task {task.id}")
            run.complete(RunStatus.SUCCESS.value)
            task.complete(TaskStatus.COMPLETED.value, summary="Dry-run completed successfully.")
            return run

        # Set up run directory
        run_dir = self.output_dir / run.id
        run_dir.mkdir(parents=True, exist_ok=True)

        # 2. Persist project context artifact
        ctx = self.build_project_context(task, proj)
        ctx_file = run_dir / "00_context" / "project_context.json"
        ctx_file.parent.mkdir(parents=True, exist_ok=True)
        ctx_file.write_text(json.dumps(ctx, indent=2), encoding="utf-8")
        run.add_artifact(
            name="project_context.json",
            artifact_type=ArtifactType.SPECIFICATION.value,
            path=str(ctx_file.relative_to(run_dir)),
            durable=True,
        )

        # 3. CEO Orchestration & Execution
        orchestration_result = self._orchestrate_and_execute(task, proj, run, run_dir, mock=mock)

        # 4. QA Independent Verification
        default_verify = f'"{sys.executable}" tools/verify_company.py'
        actual_verify_cmd = verify_cmd if verify_cmd is not None else default_verify

        veri_result = self._run_qa_verification(actual_verify_cmd, run_dir)
        run.add_verification(
            verifier_role="qa",
            passed=veri_result.passed,
            summary=veri_result.summary,
            details=veri_result.details,
        )

        # 5. Determine Outcome & Handle Result
        if veri_result.passed:
            self._log(f"QA Verification PASSED for Task {task.id} (Run {run.id})")
            run.complete(RunStatus.SUCCESS.value)
            task.complete(
                status=TaskStatus.COMPLETED.value,
                summary=f"Task completed successfully on attempt #{run.attempt_number}.",
            )
        else:
            self._log(f"QA Verification FAILED for Task {task.id} (Run {run.id})")
            run.complete(
                status=RunStatus.FAILED.value,
                error=veri_result.summary,
            )
            task.status = TaskStatus.FAILED.value

        # 6. Write final run_manifest.json for telemetry compatibility
        self._write_manifest(task, proj, run, run_dir, actual_verify_cmd)

        return run

    def _orchestrate_and_execute(
        self,
        task: Task,
        project: Project,
        run: TaskRun,
        run_dir: Path,
        mock: bool = False,
    ) -> Dict[str, Any]:
        """Perform CEO orchestration and specialist execution."""
        if mock:
            self._debug("Mock mode: synthesizing orchestration and deliverables.")
            # 01_product
            spec_file = run_dir / "01_product" / "product_spec.md"
            spec_file.parent.mkdir(parents=True, exist_ok=True)
            spec_content = (
                f"# Product Specification for {project.name}\n\n"
                f"**Task ID:** {task.id}\n"
                f"**Goal:** {task.goal}\n"
                f"**Tech Stack:** {', '.join(project.tech_stack)}\n"
                f"**Constraints:** {', '.join(task.constraints)}\n"
            )
            spec_file.write_text(spec_content, encoding="utf-8")
            run.add_artifact("product_spec.md", ArtifactType.SPECIFICATION.value, str(spec_file.relative_to(run_dir)), durable=True)

            # 02_developer
            dev_file = run_dir / "02_developer" / "dev_summary.md"
            dev_file.parent.mkdir(parents=True, exist_ok=True)
            dev_content = (
                f"# Developer Implementation Summary\n\n"
                f"Implemented deliverables conforming to {project.name} conventions.\n"
                f"Target path: {project.root_path}\n"
            )
            dev_file.write_text(dev_content, encoding="utf-8")
            run.add_artifact("dev_summary.md", ArtifactType.CODE_PATCH.value, str(dev_file.relative_to(run_dir)), durable=True)

            return {
                "ceo_plan": "Mock CEO plan formulated",
                "specialists": ["product", "developer"],
                "conversation_id": f"mock-conv-{uuid.uuid4().hex[:8]}",
            }

        # Real Execution Mode: Invoke CEO via Antigravity with native invoke_subagent instruction
        prompt = (
            f"You are the CEO Agent of Jester AI Company.\n"
            f"TASK TO EXECUTE:\n"
            f"- Project: {project.name} (ID: {project.id})\n"
            f"- Tech Stack: {', '.join(project.tech_stack)}\n"
            f"- Root Path: {project.root_path}\n"
            f"- Task ID: {task.id}\n"
            f"- Goal: {task.goal}\n"
            f"- Constraints: {json.dumps(task.constraints)}\n\n"
            f"ORCHESTRATION INSTRUCTIONS:\n"
            f"1. Evaluate this project context and task objective.\n"
            f"2. Use your native invoke_subagent tool to orchestrate the required specialist employees "
            f"(e.g. product, research, developer, qa) to perform this task.\n"
            f"3. Return the subagent conversation ID and a concise summary of the executed work.\n"
        )

        cmd = [
            "agy",
            "--add-dir",
            str(self.repo_root),
            "--agent",
            "ceo",
            "--dangerously-skip-permissions",
            "-p",
            prompt,
        ]

        self._log(f"Executing CEO Agent via Antigravity for Task {task.id}...")
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            stdout = proc.stdout
            stderr = proc.stderr
        except Exception as exc:
            stdout = ""
            stderr = str(exc)

        # Record CEO log artifacts
        ceo_log_file = run_dir / "00_ceo" / "stdout.log"
        ceo_log_file.parent.mkdir(parents=True, exist_ok=True)
        ceo_log_file.write_text(stdout, encoding="utf-8")
        run.add_artifact("ceo_stdout.log", ArtifactType.LOG.value, str(ceo_log_file.relative_to(run_dir)), durable=False)

        plan_file = run_dir / "00_ceo" / "ceo_orchestration.md"
        plan_file.write_text(stdout or "CEO execution completed.", encoding="utf-8")
        run.add_artifact("ceo_orchestration.md", ArtifactType.SPECIFICATION.value, str(plan_file.relative_to(run_dir)), durable=True)

        return {
            "stdout": stdout,
            "stderr": stderr,
            "conversation_id": "real-ceo-invocation",
        }

    def _run_qa_verification(self, verify_cmd: str, run_dir: Path) -> VerificationResult:
        """Run independent QA verification command and return VerificationResult."""
        self._log(f"Running QA verification command: {verify_cmd}")
        start_time = datetime.now(timezone.utc)
        try:
            proc = subprocess.run(
                verify_cmd,
                shell=True,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except Exception as exc:
            exit_code = 1
            stdout = ""
            stderr = str(exc)

        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        passed = (exit_code == 0)

        # Save verification report artifact
        veri_dir = run_dir / "03_verification"
        veri_dir.mkdir(parents=True, exist_ok=True)

        veri_report = {
            "passed": passed,
            "command": verify_cmd,
            "exit_code": exit_code,
            "duration_seconds": duration,
            "stdout": stdout,
            "stderr": stderr,
            "timestamp": _utc_now_iso(),
        }

        report_file = veri_dir / "verification_report.json"
        report_file.write_text(json.dumps(veri_report, indent=2), encoding="utf-8")

        summary = (
            f"QA Verification PASSED (exit code 0 in {duration:.2f}s)"
            if passed
            else f"QA Verification FAILED with exit code {exit_code}: {stderr.strip() or stdout.strip() or 'Unknown error'}"
        )

        return VerificationResult(
            id=str(uuid.uuid4())[:8],
            verifier_role="qa",
            passed=passed,
            summary=summary,
            details=veri_report,
        )

    def _write_manifest(
        self,
        task: Task,
        project: Project,
        run: TaskRun,
        run_dir: Path,
        verify_cmd: str,
    ) -> None:
        """Write standard run_manifest.json to support pipeline telemetry inspection."""
        manifest = {
            "run_id": run.id,
            "task_id": task.id,
            "project_id": project.id,
            "project_name": project.name,
            "attempt_number": run.attempt_number,
            "created_at": run.created_at,
            "completed_at": run.completed_at,
            "status": run.status,
            "goal": task.goal,
            "options": {
                "verify_cmd": verify_cmd,
                "project_tech_stack": project.tech_stack,
            },
            "artifacts": [a.to_dict() for a in run.artifacts],
            "verifications": [v.to_dict() for v in run.verifications],
            "error": run.error,
        }
        manifest_path = run_dir / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
