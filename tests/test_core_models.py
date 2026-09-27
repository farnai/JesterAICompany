"""Tests for the Universal Company Core Model (Stage 24).

Validates:
1. Company, Employee, Project, Task, TaskRun, Artifact, VerificationResult, Approval, and TaskResult models.
2. Project-agnostic reusability across multiple independent projects (e.g. Jester vs. AllCare).
3. Multiple runs per task, independent verification, and human approval gates.
"""

from pathlib import Path
import pytest

from jester_ai_company.core import (
    Approval,
    ApprovalStatus,
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


def test_default_company_creation():
    """Verify Company initialization with its 7 reusable employee roles."""
    company = create_default_company()

    assert company.id == "jester-ai-company"
    assert company.name == "Jester AI Company"
    assert len(company.employees) == 7

    # Ensure all 7 generic roles exist
    for role in ["ceo", "product", "research", "ux", "marketing", "developer", "qa"]:
        emp = company.get_employee(role)
        assert emp is not None, f"Employee role '{role}' missing"
        assert emp.role == role
        assert emp.status == "ACTIVE"

    # CEO has native orchestration tools
    ceo = company.get_employee("ceo")
    assert "invoke_subagent" in ceo.tools


def test_project_agnostic_reusability():
    """Validate that the SAME AI company operates across multiple independent projects.

    Project A: Jester (React + TypeScript)
    Project B: AllCare (Next.js + Payload CMS)
    No 'JesterDeveloper' or 'AllCareDeveloper' exists!
    """
    company = create_default_company()

    # Register Project A: Jester
    jester_proj = Project(
        id="jester",
        name="Jester Desktop App",
        root_path="c:/repos/jester",
        tech_stack=["React", "TypeScript", "TailwindCSS"],
        conventions={"component_style": "functional", "state_management": "zustand"},
    )
    company.register_project(jester_proj)

    # Register Project B: AllCare
    allcare_proj = Project(
        id="allcare",
        name="AllCare Patient Portal",
        root_path="c:/repos/allcare",
        tech_stack=["Next.js", "Payload CMS", "PostgreSQL"],
        conventions={"auth_provider": "next-auth", "api_style": "rest"},
    )
    company.register_project(allcare_proj)

    assert len(company.projects) == 2
    assert "jester" in company.projects
    assert "allcare" in company.projects

    # Jester task
    jester_task = jester_proj.create_task(
        task_id="task-jester-01",
        title="Add Dark Mode Toggle",
        goal="Implement accessible dark mode toggle button in Settings panel",
        constraints=["Zero external component libraries", "WCAG AA contrast compliant"],
        required_roles=["product", "ux", "developer", "qa"],
    )

    # AllCare task
    allcare_task = allcare_proj.create_task(
        task_id="task-allcare-01",
        title="Create Appointment Booking Endpoint",
        goal="Develop secure patient appointment booking API route with HIPAA logging",
        constraints=["Audit log all PII access", "Validate slot availability with row locks"],
        required_roles=["research", "product", "developer", "qa"],
    )

    # Confirm both tasks use the SAME company developer employee
    developer = company.get_employee("developer")
    assert developer is not None
    assert developer.role == "developer"
    assert developer.title == "Developer Agent"

    # Verify no project-specific agents are required or defined
    assert company.get_employee("jester_developer") is None
    assert company.get_employee("allcare_developer") is None
    assert company.get_employee("jester_ceo") is None
    assert company.get_employee("allcare_ceo") is None


def test_task_multi_run_and_failure_recovery_model():
    """Verify that a Task can track multiple Runs (Run 1 FAIL -> Run 2 PASS), artifacts, and approvals."""
    project = Project(
        id="jester",
        name="Jester",
        root_path="/path/to/jester",
        tech_stack=["React", "TypeScript"],
    )

    task = project.create_task(
        task_id="task-ui-02",
        title="Implement Telemetry Banner",
        goal="Display pipeline run telemetry on main dashboard",
        required_roles=["developer", "qa"],
    )

    assert task.status == TaskStatus.PENDING.value
    assert len(task.runs) == 0

    # Run 1: Fails verification
    run_1 = task.create_run()
    assert task.status == TaskStatus.IN_PROGRESS.value
    assert run_1.attempt_number == 1
    assert run_1.status == RunStatus.INITIALIZING.value

    run_1.add_artifact("patch.diff", ArtifactType.CODE_PATCH.value, "02_developer/patch.diff")
    run_1.add_verification("qa", passed=False, summary="AC-3 violated: Output string format mismatch")
    run_1.complete(status=RunStatus.FAILED.value, error="Verification failed on attempt 1")

    assert run_1.status == RunStatus.FAILED.value
    assert len(run_1.verifications) == 1
    assert run_1.verifications[0].passed is False

    # Run 2: Fix attempt succeeds
    run_2 = task.create_run()
    assert run_2.attempt_number == 2
    assert len(task.runs) == 2

    run_2.add_artifact("patch_v2.diff", ArtifactType.CODE_PATCH.value, "02_developer/patch_v2.diff")
    run_2.add_verification("qa", passed=True, summary="All ACs verified: PASS")
    run_2.complete(status=RunStatus.SUCCESS.value)

    assert run_2.status == RunStatus.SUCCESS.value
    assert run_2.verifications[0].passed is True

    # Human Owner Approval Gate
    approval = task.add_approval_gate(gate_name="RELEASE_GATE", approver="Human Owner")
    assert approval.status == ApprovalStatus.PENDING.value
    approval.approve(notes="Approved for merge into main")
    assert approval.status == ApprovalStatus.APPROVED.value

    # Complete Task
    task_result = task.complete(status=TaskStatus.COMPLETED.value, summary="Implemented and verified in run 2")
    assert task.status == TaskStatus.COMPLETED.value
    assert task_result.total_runs == 2
    assert task_result.status == TaskStatus.COMPLETED.value
    assert task_result.final_run_id == run_2.id


def test_serialization_to_dict():
    """Verify full dictionary serialization for JSON compliance without loss of data."""
    company = create_default_company()
    proj = Project(id="demo", name="Demo App", root_path="/demo", tech_stack=["Python"])
    company.register_project(proj)
    task = proj.create_task("t1", "Test Task", "Do something")
    run = task.create_run()
    run.add_artifact("spec.md", ArtifactType.SPECIFICATION.value, "spec.md")
    run.add_verification("qa", True, "Passed")
    run.complete("SUCCESS")
    task.complete("COMPLETED", "Done")

    c_dict = company.to_dict()
    assert c_dict["id"] == "jester-ai-company"
    assert "demo" in c_dict["projects"]
    assert "t1" in c_dict["projects"]["demo"]["tasks"]
    assert len(c_dict["projects"]["demo"]["tasks"]["t1"]["runs"]) == 1
    assert c_dict["projects"]["demo"]["tasks"]["t1"]["result"]["status"] == "COMPLETED"
