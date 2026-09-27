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
from .registry import RECOGNIZED_AGENTS, get_agent_inventory
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
    "__version__",
]

