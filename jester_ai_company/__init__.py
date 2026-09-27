"""Jester AI Company package.

Provides company introspection, agent inventory, and operational state inspection.
"""

from .registry import RECOGNIZED_AGENTS, get_agent_inventory
from .status import (
    DEFAULT_COMPANY_NAME,
    DEFAULT_PURPOSE,
    DEFAULT_LIFECYCLE_STAGE,
    DEFAULT_HEALTH_STATUS,
    IMPLEMENTED_CAPABILITIES,
    format_status_console,
    get_company_status,
)

__version__ = "0.1.0"

__all__ = [
    "RECOGNIZED_AGENTS",
    "get_agent_inventory",
    "DEFAULT_COMPANY_NAME",
    "DEFAULT_PURPOSE",
    "DEFAULT_LIFECYCLE_STAGE",
    "DEFAULT_HEALTH_STATUS",
    "IMPLEMENTED_CAPABILITIES",
    "format_status_console",
    "get_company_status",
    "__version__",
]
