#!/usr/bin/env python3
"""CLI entrypoint to execute a Task within a Project context using Universal Company Core.

Usage:
    python tools/run_core_task.py --goal "Build feature X"
    python tools/run_core_task.py --project-name "Project Alpha" --tech-stack React TypeScript --goal "Add header component"
    python tools/run_core_task.py --goal "Test run" --mock
"""

import argparse
from pathlib import Path
import sys
from typing import List, Optional
import uuid

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jester_ai_company.core import Project, Task, create_default_company
from jester_ai_company.execution import TaskExecutor


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute a Task in a Project context using Jester AI Company Core.",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default="project-alpha",
        help="Unique identifier for the target project (default: project-alpha).",
    )
    parser.add_argument(
        "--project-name",
        type=str,
        default="Project Alpha",
        help="Display name for the target project (default: Project Alpha).",
    )
    parser.add_argument(
        "--tech-stack",
        nargs="+",
        default=["React", "TypeScript"],
        help="Technology stack of the target project (default: React TypeScript).",
    )
    parser.add_argument(
        "--task-id",
        type=str,
        default=None,
        help="Unique identifier for the Task (default: auto-generated).",
    )
    parser.add_argument(
        "--task-title",
        type=str,
        default="Company Core Task",
        help="Human-readable title for the Task.",
    )
    parser.add_argument(
        "--goal",
        type=str,
        required=True,
        help="Goal description for the Task.",
    )
    parser.add_argument(
        "--constraints",
        nargs="*",
        default=[],
        help="List of operational or technical constraints.",
    )
    parser.add_argument(
        "--verify-cmd",
        type=str,
        default=f'"{sys.executable}" tools/verify_company.py',
        help="Independent QA verification command (default: python tools/verify_company.py).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Execute in mock mode without invoking real LLM subagent processes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without modifying artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".runs",
        help="Output directory for run artifacts and manifests (default: .runs).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    return parser.parse_args(args)


def main(cli_args: Optional[List[str]] = None) -> int:
    args = parse_args(cli_args)

    company = create_default_company(REPO_ROOT)

    project = Project(
        id=args.project_id,
        name=args.project_name,
        root_path=str(REPO_ROOT),
        tech_stack=args.tech_stack,
    )
    company.register_project(project)

    task_id = args.task_id or f"task_{uuid.uuid4().hex[:8]}"
    task = project.create_task(
        task_id=task_id,
        title=args.task_title,
        goal=args.goal,
        constraints=args.constraints,
    )

    executor = TaskExecutor(
        company=company,
        output_dir=args.output_dir,
        verbose=args.verbose,
        repo_root=REPO_ROOT,
    )

    run = executor.execute_task(
        task,
        project=project,
        verify_cmd=args.verify_cmd,
        mock=args.mock,
        dry_run=args.dry_run,
    )

    print("\n" + "=" * 80)
    print("TASK EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Project         : {project.name} ({project.id})")
    print(f"Tech Stack      : {', '.join(project.tech_stack)}")
    print(f"Task ID         : {task.id}")
    print(f"Run ID          : {run.id}")
    print(f"Attempt Number  : {run.attempt_number}")
    print(f"Run Status      : {run.status}")
    print(f"Task Status     : {task.status}")
    if run.verifications:
        veri = run.verifications[-1]
        status_str = "PASS" if veri.passed else "FAIL"
        print(f"QA Verification : {status_str} ({veri.summary})")
    print(f"Artifacts Count : {len(run.artifacts)}")
    print("=" * 80)

    return 0 if run.status == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
