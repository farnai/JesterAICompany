"""Integration test demonstrating the REAL execution path through CompanyService.

Proves end-to-end:
Service
  ↓
Task
  ↓
TaskExecutor
  ↓
CEO Agent (Antigravity agy session)
  ↓ native invoke_subagent
Research Subagent
  ↓
Independent QA Verification
  ↓
TaskResult
"""

from pathlib import Path
import tempfile
import pytest

from jester_ai_company.core import RunStatus, TaskStatus
from jester_ai_company.service import CompanyService


def test_real_service_execution_path():
    """Verify live real-agent execution path through CompanyService."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        service = CompanyService(output_dir=tmp_dir, verbose=True)

        project = service.create_project(
            project_id="proj-real-test",
            name="Project Real Test",
            tech_stack=["Python", "FastAPI"],
        )

        task = service.create_task(
            project_id="proj-real-test",
            title="Real Service Integration Check",
            goal="Inspect project context and use your native invoke_subagent tool to delegate to the research specialist to confirm all 7 active agent definitions exist.",
        )

        # Real execution (mock=False invokes real Antigravity CEO agent)
        run = service.execute_task(
            task_id=task.id,
            verify_cmd='python tools/verify_company.py',
            mock=False,
        )

        # 1. Run and Task outcome
        assert run.status == RunStatus.SUCCESS.value
        assert task.status == TaskStatus.COMPLETED.value
        assert task.result is not None
        assert task.result.status == TaskStatus.COMPLETED.value
        assert task.result.total_runs == 1

        # 2. Verification check
        veris = service.get_task_verifications(task.id)
        assert len(veris) == 1
        assert veris[0].verifier_role == "qa"
        assert veris[0].passed is True

        # 3. Artifacts check
        artifacts = service.get_task_artifacts(task.id)
        ceo_orchestrations = [a for a in artifacts if a.name == "ceo_orchestration.md"]
        assert len(ceo_orchestrations) == 1

        # Check content of CEO artifact on disk
        run_dir = Path(tmp_dir) / run.id
        ceo_file = run_dir / ceo_orchestrations[0].path
        assert ceo_file.is_file()
        content = ceo_file.read_text(encoding="utf-8")
        assert "Research" in content
        assert "subagent" in content.lower()
