"""STEP 19D — First Real Jester Company Run.

Production-like end-to-end dry run proving that JesterAICompany can operate
as a software company against the REAL Jester repository:

HUMAN OBJECTIVE
        ↓
REAL PROJECT (prj_jester, repo_jester)
        ↓
PROJECT KNOWLEDGE (Role-differentiated, cryptographic hashes)
        ↓
CEO (Antigravity agy runtime)
        ↓
COMPANY PLAN (Validated DAG with Developer Fan-In)
        ↓
DAG ORCHESTRATION (Product -> UX -> Developer)
        ↓
SPECIALIST AGENTS (Verified durable artifacts)
        ↓
ARTIFACT HANDOFF (Strict provenance, SHA-256)
        ↓
DEVELOPER (Bounded isolated worktree mutation)
        ↓
QA (Independent verification in fresh disposable worktree)
        ↓
VERIFIED CHANGE (Validated CODE_PATCH + QA PASS)
        ↓
REAL REPO APPLY BOUNDARY (READY_FOR_HUMAN_APPLY — STOP)

CRITICAL INVARIANT:
Zero mutation on the real Jester repository.
Real Jester HEAD commit untouched (2173b2dd72c9802421963788e7dd0d0087af68af).
Real Jester working tree remains 100% clean.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List
import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactType,
    RunStatus,
    TaskStatus,
)
from jester_ai_company.project import (
    Project,
    ProjectRegistry,
    RepositoryPolicy,
    RepositoryRef,
    inspect_repository_state,
    run_git,
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
    format_project_knowledge_prompt_block,
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


REAL_JESTER_PATH = Path(r"C:\Users\fiord\OneDrive\Desktop\Jester").resolve()
EXPECTED_JESTER_HEAD = "2173b2dd72c9802421963788e7dd0d0087af68af"
EXPECTED_JESTER_BRANCH = "main"
EXPECTED_JESTER_REMOTE = "git@github.com:farnai/Jester.git"


@pytest.fixture(scope="module")
def real_jester_preflight():
    """Verify that real Jester is on expected baseline before and after tests."""
    assert REAL_JESTER_PATH.exists(), f"Real Jester not found at {REAL_JESTER_PATH}"

    # 1. Branch check
    code, branch_out, _ = run_git(["branch", "--show-current"], cwd=REAL_JESTER_PATH)
    assert code == 0
    assert branch_out.strip() == EXPECTED_JESTER_BRANCH, f"Branch mismatch: {branch_out.strip()}"

    # 2. HEAD commit check
    code, head_out, _ = run_git(["rev-parse", "HEAD"], cwd=REAL_JESTER_PATH)
    assert code == 0
    actual_head = head_out.strip()
    assert actual_head == EXPECTED_JESTER_HEAD, f"Jester HEAD mismatch: {actual_head} != {EXPECTED_JESTER_HEAD}"

    # 3. Clean tracked working tree check
    code, stat_tracked, _ = run_git(["status", "--porcelain", "--untracked-files=no"], cwd=REAL_JESTER_PATH)
    assert code == 0
    assert stat_tracked.strip() == "", f"Real Jester has tracked modifications: {stat_tracked}"

    code, initial_stat, _ = run_git(["status", "--porcelain"], cwd=REAL_JESTER_PATH)

    # 4. Worktree check
    code, wt_out, _ = run_git(["worktree", "list"], cwd=REAL_JESTER_PATH)
    assert code == 0
    lines = [line for line in wt_out.strip().splitlines() if line.strip()]
    assert len(lines) == 1, f"Unexpected extra Git worktrees on real Jester: {wt_out}"

    yield actual_head

    # POST-RUN ZERO MUTATION GUARANTEE
    code, post_stat, _ = run_git(["status", "--porcelain"], cwd=REAL_JESTER_PATH)
    assert code == 0
    assert post_stat.strip() == initial_stat.strip(), "Real Jester was mutated during testing!"

    code, post_head, _ = run_git(["rev-parse", "HEAD"], cwd=REAL_JESTER_PATH)
    assert code == 0
    assert post_head.strip() == EXPECTED_JESTER_HEAD, "Real Jester HEAD moved during testing!"

    code, post_wt, _ = run_git(["worktree", "list"], cwd=REAL_JESTER_PATH)
    assert code == 0
    lines_after = [line for line in post_wt.strip().splitlines() if line.strip()]
    assert len(lines_after) == 1, f"Dangling worktrees remain on real Jester: {post_wt}"


@pytest.fixture
def jester_live_setup(real_jester_preflight, tmp_path):
    """Set up live CompanyService with registered Real Jester Project and Knowledge."""
    service = CompanyService(output_dir=str(tmp_path / "runs"), verbose=True)

    project_id = "prj_jester"
    repository_id = "repo_jester"

    repo_ref = RepositoryRef(
        repository_id=repository_id,
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
    project = Project(
        project_id=project_id,
        name="Jester — People Discovery & Relationship Intelligence Engine",
        description="High-performance People Discovery and Relationship Intelligence platform",
        repository=repo_ref,
        policy=repo_policy,
    )

    # Attach certified 10-source context-safe Jester Knowledge Manifest
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
        project_id=project_id,
        repository_id=repository_id,
        sources=sources,
    )

    service.register_repository_project(project)
    service.register_project_knowledge_manifest(manifest)

    return service, project, manifest


def test_real_jester_step19d_preflight_and_registration(jester_live_setup, real_jester_preflight):
    """Targeted cheap validation of STEP 19D preflight, registration, and run identity binding."""
    service, project, manifest = jester_live_setup

    # 1. Real repository fingerprint verification
    fingerprint = inspect_repository_state(project.repository)
    assert fingerprint.repository_id == "repo_jester"
    assert fingerprint.head_commit == EXPECTED_JESTER_HEAD
    assert fingerprint.branch == EXPECTED_JESTER_BRANCH
    assert fingerprint.is_clean is True

    # 2. Knowledge catalog verification
    catalog = service.get_project_knowledge_catalog("prj_jester")
    assert catalog is not None
    assert len(manifest.sources) == 10

    # 3. Role-differentiation verification
    ceo_policy = RoleKnowledgePolicy(role="ceo", primary_domains=("product", "architecture"), max_sources=2)
    dev_policy = RoleKnowledgePolicy(role="developer", primary_domains=("backend", "architecture"), max_sources=2)
    ceo_sources = catalog.select_sources_for_role(ceo_policy)
    dev_sources = catalog.select_sources_for_role(dev_policy)
    assert {s.source_id for s in ceo_sources} != {s.source_id for s in dev_sources}

    # 4. Human Objective & Company Run Creation with fail-closed TargetRepositoryVerification
    objective = CompanyObjective(
        id="obj_jester_canonical_self_pair_defense_001",
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
        project_id="prj_jester",
    )

    run = service.create_company_run(
        objective=objective,
        project_id="prj_jester",
        repository_id="repo_jester",
        target_branch=EXPECTED_JESTER_BRANCH,
        base_commit_hash=fingerprint.head_commit,
    )
    assert run.state == CompanyRunState.CREATED.value
    assert run.project_id == "prj_jester"
    assert run.repository_id == "repo_jester"
    assert run.base_commit_hash == EXPECTED_JESTER_HEAD
    assert run.target_repository_verification is not None
    assert run.target_repository_verification["project_id"] == "prj_jester"
    assert run.target_repository_verification["repository_head"] == EXPECTED_JESTER_HEAD
    assert run.target_repository_verification["branch"] == EXPECTED_JESTER_BRANCH
    assert run.target_repository_verification["is_valid"] is True


def test_first_real_jester_company_run_end_to_end(jester_live_setup, real_jester_preflight):
    """Execute the first complete production-like dry run of JesterAICompany on real Jester."""
    service, project, manifest = jester_live_setup

    # ==============================================================================
    # PHASE 0 & 3: PRE-FLIGHT & PROJECT REGISTRATION VERIFICATION
    # ==============================================================================
    fingerprint = inspect_repository_state(project.repository)
    assert fingerprint.repository_id == "repo_jester"
    assert fingerprint.head_commit == EXPECTED_JESTER_HEAD
    assert fingerprint.branch == EXPECTED_JESTER_BRANCH
    assert fingerprint.is_clean is True

    catalog = service.get_project_knowledge_catalog("prj_jester")
    assert catalog is not None
    assert len(manifest.sources) == 10

    # Role-differentiation verification
    ceo_policy = RoleKnowledgePolicy(role="ceo", primary_domains=("product", "architecture"), max_sources=2)
    dev_policy = RoleKnowledgePolicy(role="developer", primary_domains=("backend", "architecture"), max_sources=2)
    ceo_sources = catalog.select_sources_for_role(ceo_policy)
    dev_sources = catalog.select_sources_for_role(dev_policy)
    assert {s.source_id for s in ceo_sources} != {s.source_id for s in dev_sources}

    # ==============================================================================
    # PHASE 2 & 4: HUMAN OBJECTIVE & REAL COMPANY RUN CREATION
    # ==============================================================================
    objective = CompanyObjective(
        id="obj_jester_canonical_self_pair_defense_001",
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
        project_id="prj_jester",
    )

    run = service.create_company_run(
        objective=objective,
        project_id="prj_jester",
        repository_id="repo_jester",
        target_branch=EXPECTED_JESTER_BRANCH,
        base_commit_hash=fingerprint.head_commit,
    )
    assert run.state == CompanyRunState.CREATED.value
    assert run.project_id == "prj_jester"
    assert run.repository_id == "repo_jester"
    assert run.base_commit_hash == EXPECTED_JESTER_HEAD
    assert run.target_repository_verification is not None
    assert run.target_repository_verification["project_id"] == "prj_jester"
    assert run.target_repository_verification["repository_head"] == EXPECTED_JESTER_HEAD
    assert run.target_repository_verification["branch"] == EXPECTED_JESTER_BRANCH
    assert run.target_repository_verification["is_valid"] is True

    # ==============================================================================
    # PHASE 5 & 6: REAL CEO PLANNING & QUALITY GATE
    # ==============================================================================
    planned_run = service.plan_company_run(run.run_id)
    assert planned_run.state == CompanyRunState.PLAN_READY.value
    assert planned_run.active_plan is not None
    assert planned_run.ceo_invocation_count == 1

    plan = planned_run.active_plan
    validate_dag_structure(plan)

    # Prove Developer Fan-In invariant
    dev_items = [w for w in plan.work_items if w.role.lower() == "developer"]
    assert len(dev_items) >= 1, "CEO plan must include at least one Developer work item."
    for dev_w in dev_items:
        dep_roles = {
            next(w.role.lower() for w in plan.work_items if w.work_item_id == dep_id)
            for dep_id in dev_w.depends_on
        }
        assert "product" in dep_roles, "Developer must depend on Product (Fan-In invariant)."
        assert "ux" in dep_roles, "Developer must depend on UX (Fan-In invariant)."

    # ==============================================================================
    # PHASE 7, 8, 9: EXECUTE REAL SPECIALIST DAG & ARTIFACT HANDOFFS
    # ==============================================================================
    running_run = service.start_company_run(run.run_id)
    assert running_run.state == CompanyRunState.RUNNING.value

    # Dynamically execute specialist DAG nodes until Developer is ready
    max_specialist_turns = 10
    turns = 0
    while turns < max_specialist_turns:
        current_run = service.get_company_run(run.run_id)
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
        # If all ready items are developer, we are ready for Developer Fan-In execution
        if all(item.role.lower() == "developer" for item in ready_items):
            break

        service.execute_next_company_work(run.run_id)
        turns += 1

    updated_run = service.get_company_run(run.run_id)
    # Ensure Product and UX prerequisites for Developer Fan-In are both completed
    prod_items = [w for w in plan.work_items if w.role.lower() == "product"]
    ux_items = [w for w in plan.work_items if w.role.lower() == "ux"]
    assert all(updated_run.work_item_states[w.work_item_id] == WorkItemState.COMPLETED.value for w in prod_items)
    assert all(updated_run.work_item_states[w.work_item_id] == WorkItemState.COMPLETED.value for w in ux_items)

    # Verify produced specialist artifacts exist on disk and have matching cryptographic hashes
    for summary in updated_run.employee_summaries:
        assert len(summary.artifact_refs) >= 1
        for ref in summary.artifact_refs:
            art_file = Path(service.output_dir) / ref["path"]
            assert art_file.is_file()
            actual_sha = hashlib.sha256(art_file.read_bytes()).hexdigest()
            assert actual_sha == ref["sha256"]

    # ==============================================================================
    # PHASE 10, 11, 12, 13, 14: DEVELOPER PIPELINE, QA, AND APPLY PREPARATION
    # ==============================================================================
    completed_run = service.execute_developer_company_work(run.run_id)

    # Invariant: Autonomous company execution STOPS at READY_FOR_HUMAN_APPLY
    assert completed_run.state == CompanyRunState.READY_FOR_HUMAN_APPLY.value
    assert completed_run.real_repo_apply_proposal_id is not None
    assert completed_run.code_patch_artifact_id is not None
    assert completed_run.qa_execution_report_artifact_id is not None

    # Verify Developer and QA summaries
    dev_summary = next(s for s in completed_run.employee_summaries if s.role == "developer")
    qa_summary = next(s for s in completed_run.employee_summaries if s.role == "qa")
    assert dev_summary.status == "COMPLETED"
    assert qa_summary.status == "COMPLETED"

    # Verify CODE_PATCH artifact exists on disk
    patch_ref = dev_summary.artifact_refs[0]
    patch_file = Path(service.output_dir) / patch_ref["path"]
    assert patch_file.is_file()
    patch_bytes = patch_file.read_bytes()
    assert hashlib.sha256(patch_bytes).hexdigest() == patch_ref["sha256"]
    patch_text = patch_bytes.decode("utf-8")
    assert "diff --git" in patch_text or "--- " in patch_text

    # Verify QA_EXECUTION_REPORT artifact exists on disk with verdict PASS
    qa_ref = qa_summary.artifact_refs[0]
    qa_file = Path(service.output_dir) / qa_ref["path"]
    assert qa_file.is_file()
    qa_content = qa_file.read_text(encoding="utf-8")
    assert "PASS" in qa_content

    # Verify RealRepoApplyProposal
    proposal = service.get_real_repo_apply_proposal(completed_run.real_repo_apply_proposal_id)
    assert proposal is not None
    assert Path(proposal.target_repo_root).resolve() == REAL_JESTER_PATH.resolve()
    assert proposal.base_commit_hash == EXPECTED_JESTER_HEAD
    assert proposal.status == "READY_FOR_APPROVAL"

    # ==============================================================================
    # PHASE 15 & 16: HUMAN AUTHORITY BOUNDARY & REAL JESTER ZERO-MUTATION CHECK
    # ==============================================================================
    # Crucial proof: Jester was NOT mutated because human authority was not granted
    code, stat_out, _ = run_git(["status", "--porcelain", "--untracked-files=no"], cwd=REAL_JESTER_PATH)
    assert code == 0
    assert stat_out.strip() == "", f"Violation: Real Jester working tree has tracked modifications: {stat_out}"

    code, head_out, _ = run_git(["rev-parse", "HEAD"], cwd=REAL_JESTER_PATH)
    assert code == 0
    assert head_out.strip() == EXPECTED_JESTER_HEAD, "Violation: Real Jester HEAD commit changed!"

    code, wt_out, _ = run_git(["worktree", "list"], cwd=REAL_JESTER_PATH)
    assert code == 0
    lines = [line for line in wt_out.strip().splitlines() if line.strip()]
    assert len(lines) == 1, f"Violation: Stray Git worktrees found on real Jester: {wt_out}"
