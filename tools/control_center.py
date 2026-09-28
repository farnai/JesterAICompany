#!/usr/bin/env python3
"""Jester AI Company Control Center CLI Entrypoint (Stage 27).

Launches the human-facing Owner/Admin dashboard and HTTP service.

Usage:
    python tools/control_center.py
    python tools/control_center.py --port 8500 --host 127.0.0.1
    python tools/control_center.py --open
"""

import argparse
from pathlib import Path
import sys

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jester_ai_company.control_center import run_control_center
from jester_ai_company.service import CompanyService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Jester AI Company Control Center: Owner/Admin operations and observability dashboard."
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind the Control Center server to (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8500,
        help="Port to listen on (default: 8500).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=".runs",
        help="Path to pipeline runs directory (default: .runs).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Automatically open the Control Center in the default web browser upon launch.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = CompanyService(output_dir=args.output_dir, repo_root=REPO_ROOT)
    run_control_center(host=args.host, port=args.port, service=service, open_browser=args.open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
