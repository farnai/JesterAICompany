#!/usr/bin/env python3
"""Convenience script in repository root for Jester AI Company Status inspection.

Provides quick CLI access:
    python status.py
    python status.py --json
    python status.py --help

Adheres strictly to Jester AI Company core operating principles:
- Practical over complex
- Zero external dependencies
- Pure stdout JSON contract when --json is provided
- Location-agnostic execution
"""

from pathlib import Path
import sys
from typing import List, Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jester_ai_company.cli import main as cli_main
from jester_ai_company.registry import RECOGNIZED_AGENTS, get_agent_inventory
from jester_ai_company.status import (
    DEFAULT_COMPANY_NAME,
    DEFAULT_HEALTH_STATUS,
    DEFAULT_LIFECYCLE_STAGE,
    DEFAULT_PURPOSE,
    IMPLEMENTED_CAPABILITIES,
    VERSION,
    format_status_console,
    get_company_status,
    get_pipeline_telemetry,
    get_repo_root,
)

__all__ = [
    "RECOGNIZED_AGENTS",
    "get_agent_inventory",
    "DEFAULT_COMPANY_NAME",
    "DEFAULT_HEALTH_STATUS",
    "DEFAULT_LIFECYCLE_STAGE",
    "DEFAULT_PURPOSE",
    "IMPLEMENTED_CAPABILITIES",
    "VERSION",
    "format_status_console",
    "get_company_status",
    "get_pipeline_telemetry",
    "get_repo_root",
    "main",
]


def main(argv: Optional[List[str]] = None) -> int:
    """Execute status command with arguments."""
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
