"""Jester AI Company package.

Provides company introspection, agent inventory, and operational state inspection.
"""

from .core import (
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
from .execution import TaskExecutor
from .registry import RECOGNIZED_AGENTS, get_agent_inventory
from .service import (
    CompanyService,
    CompanyServiceError,
    ExecutionError,
    InvalidTaskStateError,
    ProjectNotFoundError,
    RunNotFoundError,
    TaskNotFoundError,
)

from .status import (
    DEFAULT_COMPANY_NAME,
    DEFAULT_PURPOSE,
    DEFAULT_LIFECYCLE_STAGE,
    DEFAULT_HEALTH_STATUS,
    IMPLEMENTED_CAPABILITIES,
    format_status_console,
    get_company_status,
    get_pipeline_telemetry,
)

from .control_center import ControlCenterHandler, create_server, run_control_center
from .runtime import (
    AgentExecutionResult,
    AntigravityRuntime,
    AntigravityRuntimeError,
    InvalidAgentError,
)
from .proposal import (
    CEOActionProposal,
    ProposalError,
    ProposalParseError,
    ProposalValidationError,
    build_task_proposal_prompt,
    extract_json_text,
    parse_and_validate_proposal,
)

__version__ = "0.1.0"

__all__ = [
    "Approval",
    "ApprovalStatus",
    "Artifact",
    "ArtifactType",
    "Company",
    "Employee",
    "Project",
    "RunStatus",
    "Task",
    "TaskResult",
    "TaskRun",
    "TaskStatus",
    "VerificationResult",
    "create_default_company",
    "TaskExecutor",
    "CompanyService",
    "CompanyServiceError",
    "ProjectNotFoundError",
    "TaskNotFoundError",
    "RunNotFoundError",
    "InvalidTaskStateError",
    "ExecutionError",
    "ControlCenterHandler",
    "create_server",
    "run_control_center",
    "RECOGNIZED_AGENTS",
    "get_agent_inventory",
    "DEFAULT_COMPANY_NAME",
    "DEFAULT_PURPOSE",
    "DEFAULT_LIFECYCLE_STAGE",
    "DEFAULT_HEALTH_STATUS",
    "IMPLEMENTED_CAPABILITIES",
    "format_status_console",
    "get_company_status",
    "get_pipeline_telemetry",
    "AgentExecutionResult",
    "AntigravityRuntime",
    "AntigravityRuntimeError",
    "InvalidAgentError",
    "CEOActionProposal",
    "ProposalError",
    "ProposalParseError",
    "ProposalValidationError",
    "build_task_proposal_prompt",
    "extract_json_text",
    "parse_and_validate_proposal",
    "__version__",
]

