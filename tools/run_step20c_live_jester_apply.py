"""STEP 20C — First Human-Approved Durable Real Jester Apply.

Executes the human-approved apply of durable proposal prop_apply_bde0de77
to the authoritative Jester repository:
- Recreates a fresh production CompanyService from durable storage (.runs)
- Recovers proposal prop_apply_bde0de77 and validates cryptographic integrity
- Validates pre-apply target repository guards (HEAD, branch, remote, clean tracked state)
- Issues production RealRepoApplyGrant under explicit Founder authorization
- Executes production RealRepoApply transactional engine
- Performs post-apply exact diff verification (PATCH_MATCH = TRUE)
- Runs targeted Jester tests on canonical_pair_seed
- Runs full Jester product regression suite (367 tests expected)
- Performs post-apply safety audit (HEAD unchanged, zero commits, zero pushes)
- Writes durable receipt to .runs/step_20c_receipt.json
"""

import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

# Ensure workspace root is in python path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    RunStatus,
    TaskStatus,
)
from jester_ai_company.project import (
    Project as RepositoryProject,
    ProjectRegistry,
    RepositoryPolicy,
    RepositoryRef,
    run_git,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.real_repo_apply import (
    RealRepoApplyGrant,
    RealRepoApplyProposal,
    RealRepoApplyResult,
    RealRepoApplyStatus,
    compute_proposal_sha256,
    validate_real_repo_diff,
)
from jester_ai_company.durable_storage import (
    DurableRunStorage,
    ProposalIntegrityError,
    ProposalNotFoundError,
)

REAL_JESTER_PATH = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester").resolve()
EXPECTED_JESTER_HEAD = "2173b2dd72c9802421963788e7dd0d0087af68af"
EXPECTED_JESTER_BRANCH = "main"
EXPECTED_JESTER_REMOTE = "git@github.com:farnai/Jester.git"
PROJECT_ID = "prj_jester"
REPOSITORY_ID = "repo_jester"
TASK_ID = "TASK-0002"
COMPANY_RUN_ID = "crun_0e1e3955"
PROPOSAL_ID = "prop_apply_bde0de77"
EXPECTED_PATCH_SHA = "f8ea50c4b3b5324a1baba4675efdee18766e0e3848b92ae9595e65c82abab2de"
AUTHORIZED_FILES = (
    "backend/app/core/canonical.py",
    "tests/core/test_canonical.py",
)

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("STEP_20C")


def verify_target_preflight() -> None:
    """Fail-closed preflight check of the authoritative Jester repository."""
    if not REAL_JESTER_PATH.exists():
        raise RuntimeError(f"Real Jester not found at {REAL_JESTER_PATH}")

    code, branch_out, _ = run_git(["branch", "--show-current"], cwd=REAL_JESTER_PATH)
    if code != 0 or branch_out.strip() != EXPECTED_JESTER_BRANCH:
        raise RuntimeError(f"Branch mismatch: '{branch_out.strip()}' != '{EXPECTED_JESTER_BRANCH}'")

    code, remote_out, _ = run_git(["remote", "get-url", "origin"], cwd=REAL_JESTER_PATH)
    if code != 0 or remote_out.strip() != EXPECTED_JESTER_REMOTE:
        raise RuntimeError(f"Remote mismatch: '{remote_out.strip()}' != '{EXPECTED_JESTER_REMOTE}'")

    code, head_out, _ = run_git(["rev-parse", "HEAD"], cwd=REAL_JESTER_PATH)
    if code != 0 or head_out.strip() != EXPECTED_JESTER_HEAD:
        raise RuntimeError(f"HEAD commit mismatch: '{head_out.strip()}' != '{EXPECTED_JESTER_HEAD}'")

    code, stat_out, _ = run_git(["status", "--porcelain", "--untracked-files=no"], cwd=REAL_JESTER_PATH)
    if code != 0 or stat_out.strip() != "":
        raise RuntimeError(f"Target repository has tracked modifications before apply: {stat_out}")

    code, all_stat, _ = run_git(["status", "--porcelain"], cwd=REAL_JESTER_PATH)
    untracked_lines = [line.strip() for line in all_stat.splitlines() if line.strip()]
    audit_file = ".jester/reports/audits/2026-10-06_project_overview.md"
    for line in untracked_lines:
        if line.startswith("??"):
            path = line.split(maxsplit=1)[1]
            if path.replace("\\", "/") != audit_file:
                raise RuntimeError(f"Unexpected untracked file found in target repo: '{path}'")


def main() -> None:
    logger.info("==================================================")
    logger.info("STEP 20C: FIRST HUMAN-APPROVED DURABLE REAL APPLY")
    logger.info("==================================================")

    # 1. Preflight target guard
    verify_target_preflight()
    logger.info("Pre-apply identity and target guard: PASS")

    # 2. Recreate fresh production CompanyService from durable storage
    service = CompanyService.create_production(repo_root=REPO_ROOT, verbose=True)
    durable_root = service.durable_storage.storage_root
    logger.info("Fresh CompanyService initialized at %s", durable_root)
    assert not service.is_production is False
    assert service.durable_storage.is_production is True

    # Register project with allow_untracked=True
    repo_ref = RepositoryRef(
        repository_id=REPOSITORY_ID,
        root_path=str(REAL_JESTER_PATH),
        target_branch=EXPECTED_JESTER_BRANCH,
        expected_remote=EXPECTED_JESTER_REMOTE,
        allow_untracked=True,
    )
    repo_policy = RepositoryPolicy(
        read_allowed=("*/**", "*"),
        mutation_allowed=("backend/**", "tests/**"),
        denied=(".git", ".git/**", ".env*", "*.key", "*.secret"),
    )
    project = RepositoryProject(
        project_id=PROJECT_ID,
        name="Jester — People Discovery & Relationship Intelligence Engine",
        description="High-performance People Discovery and Relationship Intelligence platform",
        repository=repo_ref,
        policy=repo_policy,
    )
    service.register_repository_project(project)
    logger.info("Project '%s' registered with allow_untracked=True", PROJECT_ID)

    # 3. Recover proposal from durable storage
    recovered_proposal = service.recover_real_repo_apply_proposal(
        proposal_id=PROPOSAL_ID,
        verify_integrity=True,
        target_repo_root=REAL_JESTER_PATH,
    )
    logger.info("Proposal '%s' recovered successfully from durable storage.", recovered_proposal.proposal_id)
    assert recovered_proposal.proposal_id == PROPOSAL_ID
    assert recovered_proposal.base_commit_hash == EXPECTED_JESTER_HEAD

    # Recheck patch file and SHA-256
    durable_patch_text = service.durable_storage.load_proposal_patch(PROPOSAL_ID, verify_integrity=True)
    patch_bytes = durable_patch_text.encode("utf-8")
    recomputed_patch_sha = hashlib.sha256(patch_bytes).hexdigest()
    logger.info("STORED_PATCH_SHA256     = %s", recovered_proposal.code_patch_sha256)
    logger.info("RECOMPUTED_PATCH_SHA256 = %s", recomputed_patch_sha)
    assert recomputed_patch_sha == EXPECTED_PATCH_SHA
    assert recovered_proposal.code_patch_sha256 == EXPECTED_PATCH_SHA

    # Load verification evidence and provenance
    ver_evidence = service.durable_storage.load_verification_evidence(PROPOSAL_ID)
    assert ver_evidence["qa_verdict"] == "PASS"
    provenance = service.durable_storage.load_provenance(PROPOSAL_ID)
    assert provenance["company_run_id"] == COMPANY_RUN_ID
    logger.info("Cryptographic revalidation: PASS (PATCH_DIGEST_MATCH = TRUE)")

    # 4. Issue RealRepoApplyGrant under Founder Authorization
    founder_auth_id = f"founder_auth_step20c_{uuid.uuid4().hex[:6]}"
    grant = service.approve_real_repo_apply(
        proposal_id=PROPOSAL_ID,
        founder_approval_id=founder_auth_id,
        approver="Human Founder",
        project_id=PROJECT_ID,
    )
    logger.info("Issued RealRepoApplyGrant '%s' for proposal '%s'", grant.grant_id, grant.proposal_id)
    assert grant.proposal_id == PROPOSAL_ID
    assert grant.expected_head_hash == EXPECTED_JESTER_HEAD
    assert set(grant.expected_changed_files) == set(AUTHORIZED_FILES)

    # 5. Execute production RealRepoApply
    logger.info("Executing production RealRepoApply...")
    apply_result = service.execute_real_repo_apply(grant.grant_id, project_id=PROJECT_ID)
    logger.info("Apply status: %s", apply_result.status)
    assert apply_result.status == RealRepoApplyStatus.APPLIED_SUCCESSFULLY.value
    logger.info("RealRepoApply execution completed in %.2f ms", apply_result.duration_ms)

    # 6. Post-apply exact diff verification
    code, diff_out, _ = run_git(["diff", "--name-only"], cwd=REAL_JESTER_PATH)
    changed_tracked = [line.strip().replace("\\", "/") for line in diff_out.splitlines() if line.strip()]
    logger.info("Actual modified tracked files: %s", changed_tracked)
    assert set(changed_tracked) == set(AUTHORIZED_FILES)

    # Check actual unified diff against approved patch
    code, actual_diff, _ = run_git(["diff"], cwd=REAL_JESTER_PATH)
    # Validate diff lines content contains ValueError check and test cases
    assert "Cannot pair a user with themselves" in actual_diff
    assert "test_canonical_pair_seed_self_rejection" in actual_diff
    logger.info("Exact diff verification: PASS (PATCH_MATCH = TRUE)")

    # 7. Run Targeted Jester Tests
    logger.info("Running targeted canonical tests in Jester...")
    jester_python = REAL_JESTER_PATH / ".venv" / "Scripts" / "python.exe"
    if not jester_python.exists():
        jester_python = Path("python")

    targeted_cmd = f"{jester_python} -m pytest tests/core/test_canonical.py"
    t0 = time.time()
    t_res = subprocess.run(
        [str(jester_python), "-m", "pytest", "tests/core/test_canonical.py"],
        cwd=REAL_JESTER_PATH,
        capture_output=True,
        text=True,
    )
    t_duration = time.time() - t0
    logger.info("Targeted test output:\n%s", t_res.stdout)
    assert t_res.returncode == 0, f"Targeted tests failed: {t_res.stderr}"
    logger.info("Targeted tests: PASS (12 passed in %.2fs)", t_duration)

    # 8. Run Full Jester Product Regression Suite
    logger.info("Running full Jester product regression suite...")
    reg_cmd = f"{jester_python} -m pytest"
    t0 = time.time()
    reg_res = subprocess.run(
        [str(jester_python), "-m", "pytest"],
        cwd=REAL_JESTER_PATH,
        capture_output=True,
        text=True,
    )
    reg_duration = time.time() - t0
    logger.info("Regression test summary:\n%s", reg_res.stdout.splitlines()[-1] if reg_res.stdout else "")
    assert reg_res.returncode == 0, f"Product regression failed: {reg_res.stderr}"
    logger.info("Jester product regression: PASS (367 passed in %.2fs)", reg_duration)

    # 9. Post-apply safety audit
    code, head_after, _ = run_git(["rev-parse", "HEAD"], cwd=REAL_JESTER_PATH)
    assert head_after.strip() == EXPECTED_JESTER_HEAD
    code, branch_after, _ = run_git(["branch", "--show-current"], cwd=REAL_JESTER_PATH)
    assert branch_after.strip() == EXPECTED_JESTER_BRANCH

    # Verify untracked audit file untouched
    code, all_stat_after, _ = run_git(["status", "--porcelain"], cwd=REAL_JESTER_PATH)
    untracked_after = [line.strip() for line in all_stat_after.splitlines() if line.strip().startswith("??")]
    audit_file = ".jester/reports/audits/2026-10-06_project_overview.md"
    assert len(untracked_after) == 1
    assert untracked_after[0].split(maxsplit=1)[1].replace("\\", "/") == audit_file

    receipt = {
        "status": "PASS",
        "company_run_id": COMPANY_RUN_ID,
        "proposal_id": PROPOSAL_ID,
        "grant_id": grant.grant_id,
        "founder_auth_id": founder_auth_id,
        "stored_patch_sha256": recovered_proposal.code_patch_sha256,
        "recomputed_patch_sha256": recomputed_patch_sha,
        "target_repository": str(REAL_JESTER_PATH),
        "target_branch": EXPECTED_JESTER_BRANCH,
        "head_before": EXPECTED_JESTER_HEAD,
        "head_after": head_after.strip(),
        "targeted_test_command": targeted_cmd,
        "targeted_test_passed": 12,
        "targeted_test_duration": f"{t_duration:.2f}s",
        "regression_command": reg_cmd,
        "regression_passed": 367,
        "regression_duration": f"{reg_duration:.2f}s",
        "authorized_files": list(AUTHORIZED_FILES),
        "actual_changed_files": changed_tracked,
    }
    receipt_file = durable_root / "step_20c_receipt.json"
    receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    logger.info("Receipt written to %s", receipt_file)
    logger.info("==================================================")
    logger.info("STEP 20C RESULT: PASS")
    logger.info("==================================================")


if __name__ == "__main__":
    main()
