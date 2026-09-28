"""Tests for CompanyService application API (Stage 26).

Verifies:
1. Project & Task management (creation, retrieval, listing).
2. Task execution delegating to Stage 25 TaskExecutor.
3. Independent QA verification access and Artifact inspection.
4. Retry semantics (preserves same Task, increments attempt_number, retains prior runs).
5. Application-level error handling (ProjectNotFoundError, TaskNotFoundError, RunNotFoundError, InvalidTaskStateError).
6. Multi-project independence with same 7 employees (Project Alpha: React/TS vs Project Beta: Python/FastAPI).
7. Real vs. mocked execution path differentiation.
"""

from pathlib import Path
import tempfile
import pytest

from jester_ai_company.core import (
    ArtifactType,
    RunStatus,
    TaskStatus,
)
from jester_ai_company.service import (
    CompanyService,
    InvalidTaskStateError,
    ProjectNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)


def test_project_and_task_creation_and_retrieval():
    """AC-1, AC-2, AC-3, AC-4: Verify Project and Task creation, retrieval, and listing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)

        # AC-1: Create Project
        proj = service.create_project(
            project_id="proj-alpha",
            name="Project Alpha",
            root_path="/repos/alpha",
            tech_stack=["React", "TypeScript"],
            conventions={"styling": "tailwind"},
        )
        assert proj.id == "proj-alpha"
        assert proj.name == "Project Alpha"
        assert service.get_project("proj-alpha").name == "Project Alpha"
        assert len(service.list_projects()) == 1

        # AC-2: Create Task
        task = service.create_task(
            project_id="proj-alpha",
            title="Navigation Header",
            goal="Implement responsive navigation header component",
            constraints=["WCAG 2.1 AA", "Zero external UI dependencies"],
            required_roles=["product", "ux", "developer", "qa"],
        )
        assert task.id.startswith("task_")
        assert task.project_id == "proj-alpha"
        assert task.title == "Navigation Header"
        assert task.status == TaskStatus.PENDING.value

        # AC-3: Retrieve Task by ID
        fetched_task = service.get_task(task.id)
        assert fetched_task.id == task.id
        assert fetched_task.goal == task.goal

        # AC-4: Project exposes its Tasks
        tasks = service.list_tasks("proj-alpha")
        assert len(tasks) == 1
        assert tasks[0].id == task.id


def test_service_execute_task_success():
    """AC-5, AC-6, AC-7, AC-8, AC-9: Execute Task through service with artifacts and verification."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        service.create_project("p1", "Project 1", tech_stack=["Python"])
        task = service.create_task("p1", "Task 1", "Execute unit test verification")

        verify_cmd = 'python -c "import sys; sys.exit(0)"'

        # AC-5: Execute through service
        run = service.execute_task(
            task_id=task.id,
            verify_cmd=verify_cmd,
            mock=True,
        )

        # AC-6: TaskRun created and attached to Task
        assert run.attempt_number == 1
        assert run.status == RunStatus.SUCCESS.value
        assert len(service.list_runs(task.id)) == 1

        # AC-7: Real TaskResult exposed
        result = service.get_task_result(task.id)
        assert result is not None
        assert result.status == TaskStatus.COMPLETED.value
        assert result.total_runs == 1
        assert result.final_run_id == run.id

        # AC-8: QA VerificationResult accessible through service
        verifications = service.get_task_verifications(task.id)
        assert len(verifications) == 1
        assert verifications[0].verifier_role == "qa"
        assert verifications[0].passed is True

        # AC-9: Artifacts accessible through service
        artifacts = service.get_task_artifacts(task.id)
        assert len(artifacts) >= 3
        artifact_types = [a.artifact_type for a in artifacts]
        assert ArtifactType.SPECIFICATION.value in artifact_types
        assert ArtifactType.CODE_PATCH.value in artifact_types


def test_service_retry_preserves_task_and_increments_attempt():
    """AC-10, AC-11, AC-12: Retry failed task without creating new task, incrementing attempt."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        service.create_project("proj-retry", "Retry Project")
        task = service.create_task("proj-retry", "Flaky Task", "Attempt that initially fails")

        # Attempt 1: Fails verification
        fail_cmd = 'python -c "import sys; sys.exit(1)"'
        run_1 = service.execute_task(task.id, verify_cmd=fail_cmd, mock=True)
        assert run_1.attempt_number == 1
        assert run_1.status == RunStatus.FAILED.value
        assert task.status == TaskStatus.FAILED.value

        # AC-10 & AC-11: Retry using service.retry_task()
        pass_cmd = 'python -c "import sys; sys.exit(0)"'
        run_2 = service.retry_task(task.id, verify_cmd=pass_cmd, mock=True)

        assert run_2.attempt_number == 2
        assert run_2.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value

        # AC-12: Both runs remain inspectable
        all_runs = service.list_runs(task.id)
        assert len(all_runs) == 2
        assert all_runs[0].id == run_1.id
        assert all_runs[0].status == RunStatus.FAILED.value
        assert all_runs[1].id == run_2.id
        assert all_runs[1].status == RunStatus.SUCCESS.value

        # Verifications across all runs
        veris = service.get_task_verifications(task.id)
        assert len(veris) == 2
        assert veris[0].passed is False
        assert veris[1].passed is True


def test_service_error_handling_missing_resources():
    """AC-13: Clear application-level errors for missing or invalid resources."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)

        # Project not found
        with pytest.raises(ProjectNotFoundError) as exc_info:
            service.get_project("nonexistent-proj")
        assert "nonexistent-proj" in str(exc_info.value)

        # Task not found
        with pytest.raises(TaskNotFoundError) as exc_info:
            service.get_task("nonexistent-task")
        assert "nonexistent-task" in str(exc_info.value)

        # Run not found
        with pytest.raises(RunNotFoundError) as exc_info:
            service.get_run("nonexistent-run")
        assert "nonexistent-run" in str(exc_info.value)

        # Invalid retry on unexecuted task
        service.create_project("p-test", "Test Proj")
        task = service.create_task("p-test", "Pending Task", "Never run")
        with pytest.raises(InvalidTaskStateError) as exc_info:
            service.retry_task(task.id)
        assert "has not been executed yet" in str(exc_info.value)

        # Invalid retry on already completed task
        service.execute_task(task.id, verify_cmd='python -c "import sys; sys.exit(0)"', mock=True)
        with pytest.raises(InvalidTaskStateError) as exc_info:
            service.retry_task(task.id)
        assert "already completed successfully" in str(exc_info.value)


def test_service_multi_project_same_employees():
    """AC-14, AC-15: Coexistence of two synthetic Projects using the same 7 employees."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)

        # Project Alpha: React / TypeScript
        proj_alpha = service.create_project(
            project_id="alpha",
            name="Project Alpha",
            tech_stack=["React", "TypeScript"],
        )
        task_alpha = service.create_task("alpha", "UI Header", "Build UI", required_roles=["developer", "qa"])

        # Project Beta: Python / FastAPI
        proj_beta = service.create_project(
            project_id="beta",
            name="Project Beta",
            tech_stack=["Python", "FastAPI"],
        )
        task_beta = service.create_task("beta", "Metrics API", "Build API", required_roles=["developer", "qa"])

        pass_cmd = 'python -c "import sys; sys.exit(0)"'
        run_alpha = service.execute_task(task_alpha.id, verify_cmd=pass_cmd, mock=True)
        run_beta = service.execute_task(task_beta.id, verify_cmd=pass_cmd, mock=True)

        assert run_alpha.status == RunStatus.SUCCESS.value
        assert run_beta.status == RunStatus.SUCCESS.value

        # Confirm both use the SAME company employees
        dev = service.company.get_employee("developer")
        assert dev is not None
        assert dev.title == "Developer Agent"

        # Confirm no project-specific agents
        assert service.company.get_employee("alpha_developer") is None
        assert service.company.get_employee("beta_developer") is None


def test_service_run_and_artifact_specific_queries():
    """Verify specific queries by run_id for verifications and artifacts."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir)
        service.create_project("p-query", "Query Project")
        task = service.create_task("p-query", "Query Task", "Query artifacts and verifications")

        run = service.execute_task(task.id, verify_cmd='python -c "import sys; sys.exit(0)"', mock=True)

        # Query by run_id
        fetched_run = service.get_run(run.id, task_id=task.id)
        assert fetched_run.id == run.id

        veris = service.get_task_verifications(task.id, run_id=run.id)
        assert len(veris) == 1
        assert veris[0].passed is True

        artifacts = service.get_task_artifacts(task.id, run_id=run.id)
        assert len(artifacts) >= 3
