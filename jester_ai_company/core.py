"""Universal Company Core Model for Jester AI Company.

Defines the clean, minimal, project-agnostic foundation that allows the AI
company's employees to operate across multiple independent projects.

Architecture Hierarchy:
    Company
      ├── Employees (Generic reusable roles: CEO, Product, Research, UX, Marketing, Developer, QA)
      └── Projects (Target contexts: Jester, AllCare, Client Projects, Internal...)
            └── Tasks (Concrete objectives with constraints and required roles)
                  ├── Runs (Execution attempts: 1..N)
                  ├── Verifications (Independent QA results)
                  ├── Approvals (Human decision gates)
                  ├── Artifacts (Durable deliverables vs ephemeral logs)
                  └── Result (Task-level completion outcome)
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from .registry import RECOGNIZED_AGENTS, get_agent_inventory


def _utc_now_iso() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class ArtifactType(str, Enum):
    """Classification of artifacts produced during work."""
    SPECIFICATION = "SPECIFICATION"
    CODE_PATCH = "CODE_PATCH"
    VERIFICATION_REPORT = "VERIFICATION_REPORT"
    RESEARCH_REPORT = "RESEARCH_REPORT"
    UX_MOCKUP = "UX_MOCKUP"
    MARKETING_BRIEF = "MARKETING_BRIEF"
    SUMMARY = "SUMMARY"
    LOG = "LOG"


class ApprovalStatus(str, Enum):
    """Human or automated approval decision state."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TaskStatus(str, Enum):
    """Lifecycle status of a Task."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class RunStatus(str, Enum):
    """Outcome status of an individual execution Run."""
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class Employee:
    """Represents a reusable AI specialist employee belonging to the Company."""
    id: str
    role: str
    title: str
    responsibilities: str
    tools: List[str] = field(default_factory=list)
    status: str = "ACTIVE"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Artifact:
    """Represents a concrete output produced during a task execution."""
    id: str
    name: str
    artifact_type: str
    path: str
    durable: bool = True
    created_at: str = field(default_factory=_utc_now_iso)
    sha256: Optional[str] = None
    run_id: Optional[str] = None
    producer_role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    """Represents an independent verification check performed by QA."""
    id: str
    verifier_role: str
    passed: bool
    summary: str
    details: Dict[str, Any] = field(default_factory=dict)
    executed_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChatMessage:
    """Represents a message in the company-wide communication thread between Owner and Employees."""
    id: str
    sender_role: str  # "owner", "ceo", "developer", "qa", etc.
    sender_name: str
    content: str
    timestamp: str = field(default_factory=_utc_now_iso)
    task_id: Optional[str] = None
    project_id: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Approval:
    """Represents a human or policy decision gate for a milestone or action."""
    id: str
    gate_name: str
    approver: str
    status: str = ApprovalStatus.PENDING.value
    notes: Optional[str] = None
    decided_at: Optional[str] = None

    def approve(self, notes: Optional[str] = None) -> None:
        self.status = ApprovalStatus.APPROVED.value
        self.notes = notes
        self.decided_at = _utc_now_iso()

    def reject(self, notes: Optional[str] = None) -> None:
        self.status = ApprovalStatus.REJECTED.value
        self.notes = notes
        self.decided_at = _utc_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskRun:
    """Represents one execution attempt of a Task."""
    id: str
    task_id: str
    attempt_number: int
    status: str = RunStatus.INITIALIZING.value
    created_at: str = field(default_factory=_utc_now_iso)
    completed_at: Optional[str] = None
    artifacts: List[Artifact] = field(default_factory=list)
    verifications: List[VerificationResult] = field(default_factory=list)
    error: Optional[str] = None

    def complete(self, status: str, error: Optional[str] = None) -> None:
        self.status = status
        self.error = error
        self.completed_at = _utc_now_iso()

    def add_artifact(
        self,
        name: str,
        artifact_type: str,
        path: str,
        durable: bool = True,
        sha256: Optional[str] = None,
        producer_role: Optional[str] = None,
    ) -> Artifact:
        art = Artifact(
            id=str(uuid.uuid4())[:8],
            name=name,
            artifact_type=artifact_type,
            path=path,
            durable=durable,
            sha256=sha256,
            run_id=self.id,
            producer_role=producer_role,
        )
        self.artifacts.append(art)
        return art

    def add_verification(self, verifier_role: str, passed: bool, summary: str, details: Optional[Dict[str, Any]] = None) -> VerificationResult:
        veri = VerificationResult(
            id=str(uuid.uuid4())[:8],
            verifier_role=verifier_role,
            passed=passed,
            summary=summary,
            details=details or {},
        )
        self.verifications.append(veri)
        return veri

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["artifacts"] = [a.to_dict() for a in self.artifacts]
        d["verifications"] = [v.to_dict() for v in self.verifications]
        return d


@dataclass
class TaskResult:
    """Represents the final outcome of an entire Task."""
    task_id: str
    status: str
    summary: str
    total_runs: int
    final_run_id: Optional[str] = None
    completed_at: str = field(default_factory=_utc_now_iso)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    """Represents a concrete objective assigned to the company within a project."""
    id: str
    project_id: str
    title: str
    goal: str
    constraints: List[str] = field(default_factory=list)
    required_roles: List[str] = field(default_factory=list)
    expected_output: List[str] = field(default_factory=list)
    status: str = TaskStatus.PENDING.value
    created_at: str = field(default_factory=_utc_now_iso)
    runs: List[TaskRun] = field(default_factory=list)
    approvals: List[Approval] = field(default_factory=list)
    result: Optional[TaskResult] = None

    def create_run(self) -> TaskRun:
        attempt = len(self.runs) + 1
        run_id = f"run_{self.id}_{attempt:02d}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        run = TaskRun(id=run_id, task_id=self.id, attempt_number=attempt)
        self.runs.append(run)
        self.status = TaskStatus.IN_PROGRESS.value
        return run

    def add_approval_gate(self, gate_name: str, approver: str = "Human Owner") -> Approval:
        app = Approval(id=str(uuid.uuid4())[:8], gate_name=gate_name, approver=approver)
        self.approvals.append(app)
        return app

    def complete(self, status: str, summary: str, details: Optional[Dict[str, Any]] = None) -> TaskResult:
        self.status = status
        latest_run = self.runs[-1] if self.runs else None
        res = TaskResult(
            task_id=self.id,
            status=status,
            summary=summary,
            total_runs=len(self.runs),
            final_run_id=latest_run.id if latest_run else None,
            details=details or {},
        )
        self.result = res
        return res


    def execute(
        self,
        project: Optional["Project"] = None,
        verify_cmd: Optional[str] = None,
        mock: bool = False,
        dry_run: bool = False,
        output_dir: str = ".runs",
        verbose: bool = False,
    ) -> "TaskRun":
        """Initiate real execution of this Task using Company Core TaskExecutor."""
        from .execution import TaskExecutor

        executor = TaskExecutor(output_dir=output_dir, verbose=verbose)
        return executor.execute_task(
            self,
            project=project,
            verify_cmd=verify_cmd,
            mock=mock,
            dry_run=dry_run,
        )

    def to_dict(self) -> Dict[str, Any]:

        d = asdict(self)
        d["runs"] = [r.to_dict() for r in self.runs]
        d["approvals"] = [a.to_dict() for a in self.approvals]
        d["result"] = self.result.to_dict() if self.result else None
        return d


@dataclass
class Project:
    """Represents an external or internal project context worked on by the Company."""
    id: str
    name: str
    root_path: str
    tech_stack: List[str] = field(default_factory=list)
    conventions: Dict[str, Any] = field(default_factory=dict)
    status: str = "ACTIVE"
    tasks: Dict[str, Task] = field(default_factory=dict)

    def create_task(
        self,
        task_id: str,
        title: str,
        goal: str,
        constraints: Optional[List[str]] = None,
        required_roles: Optional[List[str]] = None,
        expected_output: Optional[List[str]] = None,
    ) -> Task:
        task = Task(
            id=task_id,
            project_id=self.id,
            title=title,
            goal=goal,
            constraints=constraints or [],
            required_roles=required_roles or [],
            expected_output=expected_output or [],
        )
        self.tasks[task_id] = task
        return task


    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "name": self.name,
            "root_path": self.root_path,
            "tech_stack": self.tech_stack,
            "conventions": self.conventions,
            "status": self.status,
            "tasks": {k: t.to_dict() for k, t in self.tasks.items()},
        }
        return d


@dataclass
class Company:
    """Represents the AI organization itself.

    The Company owns reusable AI employees and works across multiple Projects.
    The Company does NOT belong to any single project.
    """
    id: str
    name: str
    purpose: str
    employees: Dict[str, Employee] = field(default_factory=dict)
    projects: Dict[str, Project] = field(default_factory=dict)
    messages: List[ChatMessage] = field(default_factory=list)

    def register_employee(self, employee: Employee) -> None:
        self.employees[employee.id] = employee

    def register_project(self, project: Project) -> None:
        self.projects[project.id] = project

    def get_employee(self, role_or_id: str) -> Optional[Employee]:
        return self.employees.get(role_or_id)

    def add_message(
        self,
        sender_role: str,
        sender_name: str,
        content: str,
        task_id: Optional[str] = None,
        project_id: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> ChatMessage:
        """Record a chat message in the company communication thread."""
        msg = ChatMessage(
            id=f"msg_{uuid.uuid4().hex[:8]}",
            sender_role=sender_role,
            sender_name=sender_name,
            content=content,
            task_id=task_id,
            project_id=project_id,
            meta=meta or {},
        )
        self.messages.append(msg)
        return msg

    def execute_task(
        self,
        task: Task,
        project: Optional[Project] = None,
        verify_cmd: Optional[str] = None,
        mock: bool = False,
        dry_run: bool = False,
        output_dir: str = ".runs",
        verbose: bool = False,
    ) -> TaskRun:
        """Execute a Task within its Project context using the Company's TaskExecutor."""
        from .execution import TaskExecutor

        executor = TaskExecutor(company=self, output_dir=output_dir, verbose=verbose)
        return executor.execute_task(
            task,
            project=project,
            verify_cmd=verify_cmd,
            mock=mock,
            dry_run=dry_run,
        )

    def to_dict(self) -> Dict[str, Any]:

        return {
            "id": self.id,
            "name": self.name,
            "purpose": self.purpose,
            "employees": {k: e.to_dict() for k, e in self.employees.items()},
            "projects": {k: p.to_dict() for k, p in self.projects.items()},
            "messages": [m.to_dict() for m in self.messages[-50:]],
        }


def create_default_company(repo_root: Optional[Path] = None) -> Company:
    """Factory creating the default Jester AI Company with its 7 standard reusable employees."""
    company = Company(
        id="jester-ai-company",
        name="Jester AI Company",
        purpose="A team of AI employees that collaborate to perform real work and report results to the human owner.",
    )

    # Populate the 7 standard recognized roles from the company blueprint
    root = repo_root or Path(__file__).resolve().parent.parent
    inventory = get_agent_inventory(root)

    for item in inventory:
        role_id = item["role"]
        emp = Employee(
            id=role_id,
            role=role_id,
            title=item.get("title", f"{role_id.capitalize()} Agent"),
            responsibilities=item.get("responsibilities", ""),
            tools=["view_file", "list_dir", "grep_search", "send_message"],
            status=item.get("status", "ACTIVE"),
        )
        if role_id == "ceo":
            emp.tools = ["invoke_subagent", "send_message", "manage_task"]
        company.register_employee(emp)

    # Seed the initial CEO greeting in Company Chat
    company.add_message(
        sender_role="ceo",
        sender_name="CEO Agent",
        content="Welcome to your company workspace, Founder. I'm ready to organize the team for your next mission. What are we building today?",
    )

    return company
