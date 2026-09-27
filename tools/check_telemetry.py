#!/usr/bin/env python3
"""Pipeline Telemetry Verification Tool.

Inspects company status output to verify that pipeline telemetry records
total_runs as a valid non-negative integer.

Adheres strictly to Jester AI Company core operating principles:
- Practical over complex
- Zero external dependencies
- Location-agnostic execution
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional

# Ensure repository root is resolvable
REPO_ROOT = Path(__file__).resolve().parent.parent


def get_repo_root(custom_path: Optional[Path] = None) -> Path:
    """Resolve repository root directory."""
    if custom_path is not None:
        return Path(custom_path).resolve()
    return Path(__file__).resolve().parent.parent


def check_telemetry(repo_root: Optional[Path] = None) -> int:
    """Check pipeline telemetry from status.py --json.

    Validates:
    - AC-1: Runs status.py --json and parses JSON.
    - AC-2: Validates total_runs is integer >= 0.
    - AC-3: Prints 'TELEMETRY OK: <total_runs> runs recorded' to stdout.
    - AC-4: Exits code 0 on success.

    Returns:
        0 on success, non-zero on error.
    """
    resolved_root = get_repo_root(repo_root)
    status_script = resolved_root / "status.py"

    if not status_script.is_file():
        print(f"Error: status.py not found at '{status_script}'", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(status_script), "--json"]
    try:
        result = subprocess.run(
            cmd,
            cwd=resolved_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        print(f"Error executing '{status_script}': {exc}", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(
            f"status.py --json failed with return code {result.returncode}:\n{result.stderr}",
            file=sys.stderr,
        )
        return result.returncode

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"Failed to parse JSON output: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("Invalid status JSON payload: expected a top-level dictionary.", file=sys.stderr)
        return 1

    pipeline_telemetry = payload.get("pipeline_telemetry")
    if not isinstance(pipeline_telemetry, dict):
        print("Missing or invalid 'pipeline_telemetry' section in JSON payload.", file=sys.stderr)
        return 1

    total_runs = pipeline_telemetry.get("total_runs")
    if not isinstance(total_runs, int) or isinstance(total_runs, bool) or total_runs < 0:
        print(
            f"Invalid 'total_runs' value: {total_runs!r}. Expected non-negative integer.",
            file=sys.stderr,
        )
        return 1

    # AC-3: Print expected confirmation with total runs recorded
    print(f"TELEMETRY OK: {total_runs} runs recorded")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for checking telemetry."""
    parser = argparse.ArgumentParser(
        description="Verify pipeline telemetry from status.py"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Path to repository root (defaults to parent of script directory)",
    )
    args = parser.parse_args(argv)
    return check_telemetry(repo_root=args.repo_root)


if __name__ == "__main__":
    sys.exit(main())
