"""Tests for connecting Universal Company Core to Real Execution (Stage 25).

Verifies:
1. Project -> Task -> TaskRun execution flow.
2. Independent QA verification recording (VerificationResult).
3. Attempt numbering and multi-run retry (attempt 1 FAIL -> attempt 2 PASS).
4. TaskResult reflects actual consolidated outcome.
5. Two synthetic Project contexts (Alpha: React/TS, Beta: Python/FastAPI) using the same 7 employees.
6. Real artifacts associated with TaskRun (durable deliverables vs ephemeral logs).
"""

import json
from pathlib import Path
import tempfile
import pytest

from jester_ai_company.core import (
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
from jester_ai_company.execution import TaskExecutor


def test_project_task_execution_lifecycle_success():
    """Verify standard execution lifecycle from Project/Task to TaskRun and TaskResult."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        company = create_default_company()
        project = Project(
            id="proj-alpha",
            name="Project Alpha",
            root_path="/repos/alpha",
            tech_stack=["React", "TypeScript"],
            conventions={"linter": "eslint"},
        )
        company.register_project(project)

        task = project.create_task(
            task_id="task-alpha-001",
            title="Create Header Component",
            goal="Build accessible navigation header with breadcrumbs",
            constraints=["WCAG 2.1 AA compliant", "Pure CSS modules"],
            required_roles=["product", "ux", "developer", "qa"],
        )

        assert task.status == TaskStatus.PENDING.value
        assert len(task.runs) == 0

        executor = TaskExecutor(company=company, output_dir=tmp_dir)

        # Successful verification command (exit 0)
        verify_cmd = 'python -c "import sys; sys.exit(0)"'
        run = executor.execute_task(task, project=project, verify_cmd=verify_cmd, mock=True)

        # TaskRun assertions
        assert run.attempt_number == 1
        assert run.status == RunStatus.SUCCESS.value
        assert len(task.runs) == 1
        assert task.status == TaskStatus.COMPLETED.value

        # Artifacts assertions
        artifact_types = [a.artifact_type for a in run.artifacts]
        assert ArtifactType.SPECIFICATION.value in artifact_types
        assert ArtifactType.CODE_PATCH.value in artifact_types

        # VerificationResult assertions
        assert len(run.verifications) == 1
        assert run.verifications[0].verifier_role == "qa"
        assert run.verifications[0].passed is True

        # TaskResult assertions
        assert task.result is not None
        assert task.result.status == TaskStatus.COMPLETED.value
        assert task.result.total_runs == 1
        assert task.result.final_run_id == run.id

        # Verify disk artifacts and manifest
        run_dir = Path(tmp_dir) / run.id
        assert (run_dir / "00_context/project_context.json").is_file()
        assert (run_dir / "01_product/product_spec.md").is_file()
        assert (run_dir / "02_developer/dev_summary.md").is_file()
        assert (run_dir / "03_verification/verification_report.json").is_file()
        assert (run_dir / "run_manifest.json").is_file()

        # Check project context inside artifact
        ctx_data = json.loads((run_dir / "00_context/project_context.json").read_text(encoding="utf-8"))
        assert ctx_data["project_name"] == "Project Alpha"
        assert ctx_data["tech_stack"] == ["React", "TypeScript"]


def test_task_multi_run_retry_recovery():
    """Verify that a failed TaskRun is followed by a second TaskRun for the SAME Task with incremented attempt_number."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        company = create_default_company()
        project = Project(
            id="proj-beta",
            name="Project Beta",
            root_path="/repos/beta",
            tech_stack=["Python", "FastAPI"],
        )
        company.register_project(project)

        task = project.create_task(
            task_id="task-beta-002",
            title="Create Health API Endpoint",
            goal="Add /api/health endpoint returning operational status",
            required_roles=["developer", "qa"],
        )

        executor = TaskExecutor(company=company, output_dir=tmp_dir)

        # Run 1: Fails verification (exit 1)
        fail_cmd = 'python -c "import sys; sys.exit(1)"'
        run_1 = executor.execute_task(task, project=project, verify_cmd=fail_cmd, mock=True)

        assert run_1.attempt_number == 1
        assert run_1.status == RunStatus.FAILED.value
        assert task.status == TaskStatus.FAILED.value
        assert len(task.runs) == 1
        assert run_1.verifications[0].passed is False

        # Run 2: Retry for the SAME Task succeeds (exit 0)
        pass_cmd = 'python -c "import sys; sys.exit(0)"'
        run_2 = executor.execute_task(task, project=project, verify_cmd=pass_cmd, mock=True)

        assert run_2.attempt_number == 2
        assert run_2.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value
        assert len(task.runs) == 2
        assert run_2.verifications[0].passed is True

        # Verify parent Task remains intact and links both runs
        assert task.runs[0].id == run_1.id
        assert task.runs[1].id == run_2.id
        assert task.result is not None
        assert task.result.total_runs == 2
        assert task.result.final_run_id == run_2.id


def test_two_synthetic_projects_same_employees():
    """Demonstrate that ONE Company and the SAME 7 employees execute across TWO different Project contexts."""
    company = create_default_company()

    # Project Alpha (React/TypeScript)
    proj_alpha = Project(
        id="alpha",
        name="Project Alpha",
        root_path="/repos/alpha",
        tech_stack=["React", "TypeScript"],
    )
    company.register_project(proj_alpha)

    # Project Beta (Python/FastAPI)
    proj_beta = Project(
        id="beta",
        name="Project Beta",
        root_path="/repos/beta",
        tech_stack=["Python", "FastAPI"],
    )
    company.register_project(proj_beta)

    task_alpha = proj_alpha.create_task("t-alpha", "UI Task", "Build frontend UI", required_roles=["developer", "qa"])
    task_beta = proj_beta.create_task("t-beta", "Backend Task", "Build API route", required_roles=["developer", "qa"])

    with tempfile.TemporaryDirectory() as tmp_dir:
        executor = TaskExecutor(company=company, output_dir=tmp_dir)

        run_alpha = executor.execute_task(task_alpha, proj_alpha, verify_cmd='python -c "import sys; sys.exit(0)"', mock=True)
        run_beta = executor.execute_task(task_beta, proj_beta, verify_cmd='python -c "import sys; sys.exit(0)"', mock=True)

        assert run_alpha.status == RunStatus.SUCCESS.value
        assert run_beta.status == RunStatus.SUCCESS.value

        # Verify that both tasks used the SAME company developer employee
        dev = company.get_employee("developer")
        assert dev is not None
        assert dev.role == "developer"
        assert dev.title == "Developer Agent"

        # Verify NO project-specific agents exist
        assert company.get_employee("alpha_developer") is None
        assert company.get_employee("beta_developer") is None
        assert company.get_employee("jester_developer") is None
        assert company.get_employee("allcare_developer") is None


def test_task_direct_execute_method():
    """Verify that calling task.execute() directly triggers TaskExecutor."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        project = Project(id="proj-direct", name="Direct Project", root_path="/repos/direct")
        task = project.create_task("t-dir", "Direct Execution", "Execute directly from Task object")

        run = task.execute(
            project=project,
            verify_cmd='python -c "import sys; sys.exit(0)"',
            mock=True,
            output_dir=tmp_dir,
        )

        assert run.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value
        assert task.result is not None
        assert task.result.total_runs == 1
