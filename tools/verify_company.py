"""
Company Integrity Verification Tool
Validates repository structure, agent definitions, baseline documentation,
and system boundaries.
"""

import os
import sys
from pathlib import Path


def verify_company() -> bool:
    repo_root = Path(__file__).resolve().parent.parent
    all_passed = True

    print("=== Jester AI Company Integrity Verification ===\n")

    # 1. Verify existence of agent definition files
    agent_files = [
        Path(".agents/agents/ceo/agent.md"),
        Path(".agents/agents/product/agent.md"),
        Path(".agents/agents/developer/agent.md"),
    ]

    print("1. Checking Agent Definitions:")
    for rel_path in agent_files:
        full_path = repo_root / rel_path
        if full_path.is_file():
            print(f"  [PASS] {rel_path.as_posix()} exists")
        else:
            print(f"  [FAIL] {rel_path.as_posix()} missing or not a file")
            all_passed = False

    print()

    # 2. Verify existence of baseline documentation
    doc_files = [
        Path("README.md"),
        Path("BACKLOG.md"),
    ]

    print("2. Checking Baseline Documentation:")
    for rel_path in doc_files:
        full_path = repo_root / rel_path
        if full_path.is_file():
            print(f"  [PASS] {rel_path.as_posix()} exists")
        else:
            print(f"  [FAIL] {rel_path.as_posix()} missing or not a file")
            all_passed = False

    print()

    # 3. Verify absence of external product repositories in repo root
    boundary_dirs = [
        "Jester",
        "JesterBridge",
    ]

    print("3. Checking System Boundaries (absence in root):")
    for dir_name in boundary_dirs:
        dir_path = repo_root / dir_name
        if not dir_path.exists():
            print(f"  [PASS] {dir_name} is absent (clean boundary)")
        else:
            print(f"  [FAIL] {dir_name} found in repo root (boundary violation)")
            all_passed = False

    print()

    if all_passed:
        print("Integrity Result: ALL CHECKS PASSED")
    else:
        print("Integrity Result: ONE OR MORE CHECKS FAILED")

    return all_passed


def main() -> int:
    success = verify_company()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
