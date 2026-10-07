"""STEP 20B — First Durable Authoritative Jester Company Run.

Executes a live, production-grade company run for TASK-0002 against the real
authoritative Jester repository using the STEP 20A DurableRunStorage boundary:
- Production durable storage rooted at .runs (IS_EPHEMERAL = FALSE)
- Fail-closed TargetRepositoryIdentityGuard
- Real CEO planning and dynamic specialist DAG execution
- Isolated developer worktree mutation & independent QA verification
- Bounded stopping at READY_FOR_HUMAN_APPLY (ZERO mutation on authoritative Jester)
- Complete process/service recreation test and cryptographic revalidation from disk
"""

import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
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
    inspect_repository_state,
    run_git,
    verify_target_repository_identity,
)
from jester_ai_company.knowledge import (
    KnowledgeLoadPolicy,
    ProjectKnowledgeCatalog,
    ProjectKnowledgeManifest,
    ProjectKnowledgeRegistry,
    ProjectKnowledgeSource,
    RoleKnowledgePolicy,
    SourceAuthority,
    TruthScope,
)
from jester_ai_company.context import (
    CompanyObjective,
    assemble_ceo_context,
    assemble_specialist_context,
)
from jester_ai_company.orchestrator import (
    CompanyRun,
    CompanyRunState,
    WorkItemState,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.runtime import AntigravityRuntime
from jester_ai_company.dag import (
    select_ready_work_items,
    validate_dag_structure,
)
from jester_ai_company.durable_storage import (
    DurableRunStorage,
    ProposalNotFoundError,
    ProposalIntegrityError,
)

REAL_JESTER_PATH = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester").resolve()
EXPECTED_JESTER_HEAD = "2173b2dd72c9802421963788e7dd0d0087af68af"
EXPECTED_JESTER_BRANCH = "main"
EXPECTED_JESTER_REMOTE = "git@github.com:farnai/Jester.git"
PROJECT_ID = "prj_jester"
REPOSITORY_ID = "repo_jester"
TASK_ID = "TASK-0002"

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("STEP_20B")


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
        raise RuntimeError(f"Target repository has tracked modifications: {stat_out}")

    code, all_stat, _ = run_git(["status", "--porcelain"], cwd=REAL_JESTER_PATH)
    untracked_lines = [line.strip() for line in all_stat.splitlines() if line.strip()]
    audit_file = ".jester/reports/audits/2026-10-06_project_overview.md"
    for line in untracked_lines:
        if line.startswith("??"):
            path = line.split(maxsplit=1)[1]
            if path.replace("\\", "/") != audit_file:
                raise RuntimeError(f"Unexpected untracked file found in target repo: '{path}'")

    code, wt_out, _ = run_git(["worktree", "list"], cwd=REAL_JESTER_PATH)
    wt_lines = [l for l in wt_out.strip().splitlines() if l.strip()]
    if len(wt_lines) != 1:
        raise RuntimeError(f"Dangling worktrees found on real Jester: {wt_out}")


def main() -> None:
    logger.info("==================================================")
    logger.info("STEP 20B: AUTHORITATIVE JESTER COMPANY RUN START")
    logger.info("==================================================")

    # 1. Preflight target repository verification
    verify_target_preflight()
    logger.info("Authoritative target repository guard: PASS")

    # 2. Production storage setup
    service = CompanyService.create_production(repo_root=REPO_ROOT, verbose=True)
    durable_root = service.durable_storage.storage_root
    logger.info("PRODUCTION_STORAGE_ROOT = %s", durable_root)
    logger.info("STORAGE_MODE = PRODUCTION_DURABLE")
    logger.info("IS_EPHEMERAL = FALSE")
    assert service.is_production is True
    assert not str(durable_root).lower().endswith("temp")

    # 3. Register real Jester Project
    repo_ref = RepositoryRef(
        repository_id=REPOSITORY_ID,
        root_path=str(REAL_JESTER_PATH),
        target_branch=EXPECTED_JESTER_BRANCH,
        expected_remote=EXPECTED_JESTER_REMOTE,
        allow_untracked=True,
    )
    repo_policy = RepositoryPolicy(
        read_allowed=(
            "docs/**",
            "backend/**",
            "frontend/**",
            "tests/**",
            "scripts/**",
            "*.md",
            "*.ini",
            "*.txt",
        ),
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

    sources = (
        ProjectKnowledgeSource(
            source_id="jester_doc_architecture",
            relative_path="docs/ARCHITECTURE.md",
            domain="architecture",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.SPECIFICATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Core architecture specification for Jester AI platform",
        ),
        ProjectKnowledgeSource(
            source_id="jester_doc_foundation",
            relative_path="docs/JESTER_PRODUCT_FOUNDATION.md",
            domain="product",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.SPECIFICATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="High-level product overview and objectives",
        ),
        ProjectKnowledgeSource(
            source_id="jester_doc_readme",
            relative_path="README.md",
            domain="product",
            authority=SourceAuthority.SUPPORTING,
            truth_scope=TruthScope.REFERENCE,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Repository README and capabilities",
        ),
        ProjectKnowledgeSource(
            source_id="jester_doc_agents",
            relative_path="AGENTS.md",
            domain="brand",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.BEHAVIOR,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Jester behavioral rules and engineering workflows",
        ),
        ProjectKnowledgeSource(
            source_id="jester_doc_api",
            relative_path="docs/API.md",
            domain="backend",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.SPECIFICATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Complete API router and endpoint contract specification",
        ),
        ProjectKnowledgeSource(
            source_id="jester_doc_interpretation_contract",
            relative_path="docs/JESTER_INTERPRETATION_CONTRACT.md",
            domain="product",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.SPECIFICATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Interpretation architecture and voice guidelines",
        ),
        ProjectKnowledgeSource(
            source_id="jester_backend_main",
            relative_path="backend/app/main.py",
            domain="backend",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.IMPLEMENTATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="FastAPI main application entrypoint",
        ),
        ProjectKnowledgeSource(
            source_id="jester_backend_config",
            relative_path="backend/app/config.py",
            domain="architecture",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.CONFIGURATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Runtime application settings and environment config",
        ),
        ProjectKnowledgeSource(
            source_id="jester_backend_canonical",
            relative_path="backend/app/core/canonical.py",
            domain="backend",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.IMPLEMENTATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Deterministic canonical pair identity and relationship pair seed core primitives",
        ),
        ProjectKnowledgeSource(
            source_id="jester_test_canonical",
            relative_path="tests/core/test_canonical.py",
            domain="backend",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.SPECIFICATION,
            load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            description="Unit tests for core canonical pair identity and seed behavior",
        ),
    )
    manifest = ProjectKnowledgeManifest(
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        sources=sources,
    )

    service.register_repository_project(project)
    service.register_project_knowledge_manifest(manifest)
    logger.info("Project and 10 Knowledge Sources registered successfully.")

    # 4. Human Objective formulation for TASK-0002
    obj_id = f"obj_jester_task0002_{uuid.uuid4().hex[:6]}"
    objective = CompanyObjective(
        id=obj_id,
        title="Add defensive self-pair validation to canonical_pair_seed",
        description=(
            "Add defensive self-pair validation to canonical_pair_seed in Jester by raising a ValueError "
            "when user_1 equals user_2 (preventing invalid relationship seeds for identical users), while "
            "preserving backward compatibility, symmetry, and determinism for distinct users, accompanied "
            "by unit tests in tests/core/test_canonical.py."
        ),
        constraints=[
            f"target repository is external jester ({REAL_JESTER_PATH})",
            "strictly preserve backward compatibility for distinct pairs",
            "canonical_pair_seed must raise ValueError with message 'Cannot pair a user with themselves' when u1 == u2",
            "preserve symmetry: canonical_pair_seed(A, vA, B, vB) == canonical_pair_seed(B, vB, A, vA)",
            "implement change in backend/app/core/canonical.py and tests in tests/core/test_canonical.py",
            "orchestrate focused engineering delivery using product, ux, and developer specialist roles",
        ],
        acceptance_criteria=[
            "canonical_pair_seed(u1, ver1, u1, ver2) raises ValueError with message containing 'Cannot pair a user with themselves'",
            "canonical_pair_seed behavior for distinct users remains 100% identical and symmetric",
            "unit tests in tests/core/test_canonical.py pass clean and verify both self-pair rejection and distinct pair symmetry",
        ],
        target_repository=str(REAL_JESTER_PATH),
        project_id=PROJECT_ID,
    )

    # 5. Create Company Run
    run = service.create_company_run(
        objective=objective,
        project_id=PROJECT_ID,
        repository_id=REPOSITORY_ID,
        target_branch=EXPECTED_JESTER_BRANCH,
        base_commit_hash=EXPECTED_JESTER_HEAD,
    )
    company_run_id = run.run_id
    logger.info("Created CompanyRun: %s", company_run_id)

    # 6. CEO Planning
    logger.info("Invoking CEO Agent for orchestration planning...")
    planned_run = service.plan_company_run(company_run_id)
    plan = planned_run.active_plan
    validate_dag_structure(plan)

    selected_agents = [w.role.lower() for w in plan.work_items]
    logger.info("CEO Plan formulated. Selected agents: %s", selected_agents)

    # 7. Start Company Run & Execute Specialist DAG
    logger.info("Starting CompanyRun execution...")
    service.start_company_run(company_run_id)

    max_specialist_turns = 10
    turns = 0
    while turns < max_specialist_turns:
        current_run = service.get_company_run(company_run_id)
        ready_items = select_ready_work_items(
            plan,
            completed_item_ids={
                wid for wid, st in current_run.work_item_states.items()
                if st == WorkItemState.COMPLETED.value
            },
            current_states=current_run.work_item_states,
        )
        if not ready_items:
            break
        if all(item.role.lower() == "developer" for item in ready_items):
            logger.info("Developer work item is now ready (Product/UX handoffs satisfied).")
            break

        service.execute_next_company_work(company_run_id)
        turns += 1

    # 8. Execute Developer & QA Pipeline
    logger.info("Executing Developer work item in isolated worktree mutation...")
    completed_run = service.execute_developer_company_work(company_run_id)
    proposal_id = completed_run.real_repo_apply_proposal_id

    assert completed_run.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value
    assert proposal_id is not None
    logger.info("CompanyRun reached state: READY_FOR_HUMAN_APPLY")
    logger.info("Generated Proposal ID: %s", proposal_id)

    # 9. Verify durable storage on disk
    run_manifest_file = durable_root / "company_runs" / company_run_id / "run_manifest.json"
    prop_dir = durable_root / "proposals" / proposal_id
    patch_file = prop_dir / "patch.diff"
    prop_manifest_file = prop_dir / "proposal.json"
    verification_file = prop_dir / "verification.json"
    provenance_file = prop_dir / "provenance.json"

    assert run_manifest_file.is_file(), f"Missing durable run manifest at {run_manifest_file}"
    assert patch_file.is_file(), f"Missing durable patch at {patch_file}"
    assert prop_manifest_file.is_file(), f"Missing durable proposal at {prop_manifest_file}"
    assert verification_file.is_file(), f"Missing durable verification at {verification_file}"
    assert provenance_file.is_file(), f"Missing durable provenance at {provenance_file}"
    logger.info("All durable run and proposal files verified on disk.")

    initial_patch_bytes = patch_file.read_bytes()
    stored_patch_sha = hashlib.sha256(initial_patch_bytes).hexdigest()
    logger.info("Stored Patch SHA-256: %s", stored_patch_sha)

    # ==============================================================================
    # 10. CRITICAL: PROCESS / SERVICE RECREATION TEST (Sections 7 & 8)
    # ==============================================================================
    logger.info("Releasing original in-memory CompanyService instance...")
    del service

    logger.info("Instantiating completely fresh CompanyService instance from disk...")
    recreated_service = CompanyService.create_production(repo_root=REPO_ROOT, verbose=True)

    # Recover proposal strictly from disk
    recovered_proposal = recreated_service.recover_real_repo_apply_proposal(
        proposal_id=proposal_id,
        verify_integrity=True,
        target_repo_root=REAL_JESTER_PATH,
    )
    assert recovered_proposal.proposal_id == proposal_id
    assert recovered_proposal.project_id == PROJECT_ID
    assert recovered_proposal.base_commit_hash == EXPECTED_JESTER_HEAD
    logger.info("RECOVERY_AFTER_SERVICE_RECREATION = PASS")

    # Load durable patch and recompute SHA-256
    recovered_patch_text = recreated_service.durable_storage.load_proposal_patch(proposal_id, verify_integrity=True)
    recomputed_patch_sha = hashlib.sha256(recovered_patch_text.encode("utf-8")).hexdigest()
    logger.info("Recomputed Patch SHA-256: %s", recomputed_patch_sha)
    assert recomputed_patch_sha == stored_patch_sha
    assert recomputed_patch_sha == recovered_proposal.code_patch_sha256
    logger.info("PATCH_DIGEST_MATCH = TRUE")

    # 11. Authoritative Jester zero-mutation proof
    verify_target_preflight()
    logger.info("Post-run Authoritative Jester zero-mutation check: PASS (100% clean, untouched)")

    # 12. Save Step 20B receipt
    receipt = {
        "status": "PASS",
        "company_run_id": company_run_id,
        "proposal_id": proposal_id,
        "selected_agents": selected_agents,
        "stored_patch_sha256": stored_patch_sha,
        "recomputed_patch_sha256": recomputed_patch_sha,
        "base_commit": EXPECTED_JESTER_HEAD,
        "target_repository": str(REAL_JESTER_PATH),
        "target_branch": EXPECTED_JESTER_BRANCH,
        "proposal_state": recovered_proposal.status,
    }
    receipt_path = durable_root / "step_20b_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    logger.info("Receipt written to: %s", receipt_path)
    logger.info("==================================================")
    logger.info("STEP 20B RUN COMPLETE: ALL CRITERIA SATISFIED")
    logger.info("==================================================")


if __name__ == "__main__":
    main()
