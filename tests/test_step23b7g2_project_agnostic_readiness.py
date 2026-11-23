"""
tests/test_step23b7g2_project_agnostic_readiness.py

Deterministic integration test suite for STEP 23B.7-G.2:
Project-Agnostic Context Guard & Jester Registration Readiness.

Verifies:
1. Generic Product and UX prompt builders are strictly project-agnostic (no hardcoded Jester/Orange/Indigo).
2. Jester's ORANGE requirement comes exclusively from authorized Founder Objective / task constraints.
3. Separate fictional project (e.g. Project Emerald) retains independent branding with zero Jester leakage.
4. Mandatory documentation coverage for Jester registration:
   - Product receives credentials-only registration and onboarding transition rules.
   - UX receives design exploration, Mkhedruli typography, color tokens, and RegisterPage component.
5. Large documents are bounded deterministically without false claims of full coverage (PARTIAL vs COMPLETE).
6. Multi-anchor SECTION_EXCERPT delivers targeted critical sections within character budgets.
7. Product -> UX artifact handoff integrity remains strictly enforced.
8. Zero LLM or Research agent invocations for context transmission.
"""

import json
from pathlib import Path
import tempfile
from typing import Dict, List, Tuple
from unittest.mock import MagicMock

import pytest

from jester_ai_company.context import (
    CompanyObjective,
    ContextEnvelope,
    assemble_specialist_context,
)
from jester_ai_company.core import (
    Artifact,
    ArtifactInputRef,
    ArtifactType,
    ArtifactVerificationError,
    Company,
    Employee,
    Project as CoreProject,
    RunStatus,
    Task,
    TaskStatus,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.knowledge import (
    KnowledgeError,
    KnowledgeLoadPolicy,
    KnowledgeNotFoundError,
    ProjectContextExcerpt,
    ProjectKnowledgeCatalog,
    ProjectKnowledgeManifest,
    ProjectKnowledgeSource,
    RoleKnowledgePolicy,
    SourceAuthority,
    TruthScope,
    create_jester_registration_manifest,
    extract_markdown_section,
    format_project_knowledge_prompt_block,
)
from jester_ai_company.product_result import (
    ProductTaskResult,
    build_product_execution_prompt,
    parse_and_validate_product_result,
)
from jester_ai_company.project import (
    Project as RepositoryProject,
    RepositoryPolicy,
    RepositoryRef,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.ux_result import (
    UXTaskResult,
    build_ux_execution_prompt,
    parse_and_validate_ux_result,
)
from jester_ai_company.worktree import run_git


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def realistic_jester_repo():
    """Create a realistic temporary repository matching Jester's exact document structures."""
    with tempfile.TemporaryDirectory(prefix="jester_real_repo_") as tmp:
        repo_path = Path(tmp).resolve()
        (repo_path / "docs").mkdir(parents=True, exist_ok=True)
        (repo_path / "frontend" / "src" / "ui" / "tokens").mkdir(parents=True, exist_ok=True)
        (repo_path / "frontend" / "src" / "modules" / "auth").mkdir(parents=True, exist_ok=True)

        # 1. Full-length Product foundation containing sections 1 through 13
        # Padding section 1-4 with content to exceed 4,000 characters
        padding = "Jester interpersonal insight exploration and dynamic chemistry principles. " * 50
        prod_doc = f"""# JESTER — Product Foundation

**Document Type:** Canonical Product Foundation & Source of Truth
**Authority Level:** Level 2
**Status:** LOCKED PRODUCT DECISION

## 1. What JESTER Is

JESTER is a People Discovery and Relationship Intelligence platform.
{padding}

## 2. What JESTER Is NOT

Not a traditional astrology app. Not a swipe-card game.
{padding}

## 11. Authentication Boundary

JESTER strictly isolates authentication credentials from personal identity:

```text
┌──────────────────────────────────────┐       ┌──────────────────────────────────────┐
│       1. AUTHENTICATION              │       │         2. ONBOARDING                │
│    Route: /auth/register             │  ───► │    Route: /onboarding                │
│    • Email                           │       │    • Real Name & Display Name        │
│    • Password                        │       │    • Private Birth Data              │
│    • Confirm Password                │       │    • City, Interests, Photo          │
└──────────────────────────────────────┘       └──────────────────────────────────────┘
```

- **Credentials-Only Registration:**
  `/auth/register` accepts only `email`, `password`, and `confirm_password`. First name, last name, birth data, and location are never requested on the registration form.
- **Supabase Auth Authority:**
  Supabase Auth is the identity and session provider.
- **Abandonment Safety:**
  If a user abandons registration before completing Onboarding Step 1, zero personal identity or birth data exists in application tables.

## 12. Privacy & Security Invariants

1. Birth Data Isolation: private table via RLS.
2. Server-Only Astrology: clients receive only safe derived DTOs.

## 13. Georgian-First Requirement

JESTER is built and deployed **Georgian-first (`locale: "ka"`)**. English (`en`) is secondary.

- **Native Voice:** JESTER's signature witty copy is authored natively in Georgian.
- **Script Nuances:** Mkhedruli script has no native uppercase/lowercase distinction. Visual hierarchy relies on font weight contrast (700/800 Bold) and vertical line spacing (minimum line-height 1.55).
- **Horizontal Expansion:** Georgian words are on average 20% to 35% longer than English equivalents. UI containers and buttons must support generous horizontal breathing room.
"""
        (repo_path / "docs" / "JESTER_PRODUCT_FOUNDATION.md").write_text(prod_doc, encoding="utf-8")

        # 2. Design Exploration
        design_doc = """# JESTER — Design Exploration & UI/UX Proposals

**Document Type:** UI/UX Design Exploration & Component Proposals
**Authority Level:** Level 6 (Proposals & Explorations)
**Status:** WORKING EXPLORATION

## 1. Aesthetic Direction: "Editorial Digital Luxury" [PROPOSAL]

A visual synthesis combining editorial print with modern digital tools.

## 2. Color Exploration

### 2.1 Baseline Token Palette [PROPOSAL]
*(Currently reflected in prototype token files `frontend/src/ui/tokens/colors.ts`)*

```typescript
export const colors = {
  background: "#f8fafc",
  surface: "#ffffff",
  accent: "#6366f1", // Main CTAs, active indicators (Electric Royal Indigo)
  accentHover: "#4f46e5",
  highlight: "#9333ea",
};
```

### 2.2 Warm Terracotta & Monochromatic Alternatives [EXPLORATION]
- Terracotta & Warm Paper: testing warm off-whites (#faf8f5) and warm terracotta (#c2410c).

## 3. Typography & Georgian-First Rules

### 3.1 Mkhedruli Script Mechanics [APPROVED]
- **No Native Upper/Lower Case:** Visual hierarchy must rely on font weight (700/800 Bold) rather than uppercase transformations.
- **Vertical Line-Height (1.55+):** Minimum line-height is strictly 1.55.
- **Horizontal Expansion:** Georgian words are 20% to 35% longer than English. Buttons must provide generous horizontal padding.
"""
        (repo_path / "docs" / "JESTER_DESIGN_EXPLORATION.md").write_text(design_doc, encoding="utf-8")

        # 3. Strategic Marketing Foundation
        mkt_doc = """# JESTER — Strategic Marketing Foundation & Product Experience Blueprint

**Document Type:** Strategic Marketing Foundation
**Version:** 1.0.0
**Status:** Authoritative Strategic Guide

## 1. Executive Summary

JESTER is a next-generation platform for People Discovery and Relationship Intelligence.
Our core strategic axiom:
> "They show the match. JESTER explains the connection."
> THE INSIGHT BECOMES THE INVITATION.
"""
        (repo_path / "docs" / "JESTER_STRATEGIC_MARKETING_FOUNDATION.md").write_text(mkt_doc, encoding="utf-8")

        # 4. Color Tokens Implementation
        tokens_code = """export const colors = {
  background: "#f8fafc",
  surface: "#ffffff",
  surfaceSubtle: "#f1f5f9",
  textPrimary: "#0f172a",
  accent: "#6366f1",
  accentHover: "#4f46e5",
  highlight: "#9333ea",
} as const;

export type ColorToken = keyof typeof colors;
"""
        (repo_path / "frontend" / "src" / "ui" / "tokens" / "colors.ts").write_text(tokens_code, encoding="utf-8")

        # 5. Existing RegisterPage component
        register_code = """import React, { useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { useAuth } from "../../core/auth/useAuth";

export const RegisterPage: React.FC = () => {
  const navigate = useNavigate();
  const { user, onboardingCompleted, signUp } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const handleAccountSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.includes("@")) return;
    await signUp({ email, password });
    navigate("/onboarding", { replace: true });
  };

  return (
    <form onSubmit={handleAccountSubmit}>
      <input type="email" value={email} onChange={e => setEmail(e.target.value)} />
      <input type="password" value={password} onChange={e => setPassword(e.target.value)} />
      <input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} />
      <button type="submit">ახალი ანგარიშის შექმნა</button>
    </form>
  );
};
"""
        (repo_path / "frontend" / "src" / "modules" / "auth" / "RegisterPage.tsx").write_text(register_code, encoding="utf-8")

        # Initialize Git repository
        run_git(["init", "-b", "main"], cwd=repo_path)
        run_git(["config", "user.name", "JesterArchitect"], cwd=repo_path)
        run_git(["config", "user.email", "architect@jester.ge"], cwd=repo_path)
        run_git(["add", "."], cwd=repo_path)
        run_git(["commit", "-m", "Initial Jester canonical documentation and frontend"], cwd=repo_path)

        yield repo_path


def make_mock_runtime(agent_response_stdout: str = "") -> MagicMock:
    """Mock runtime capturing execution parameters without making external calls."""
    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.return_value = AgentExecutionResult(
        agent="specialist",
        success=True,
        exit_code=0,
        stdout=agent_response_stdout,
        stderr="",
        timed_out=False,
        duration_ms=25.0,
    )
    return runtime


def build_service_with_manifest(
    repo_path: Path,
    mock_runtime: MagicMock,
    project_id: str = "prj_jester",
    repository_id: str = "repo_jester",
) -> Tuple[CompanyService, RepositoryProject, ProjectKnowledgeManifest]:
    """Helper setting up service with registered repository and knowledge manifest."""
    service = CompanyService(output_dir=str(repo_path / "output"), runtime=mock_runtime)

    repo_ref = RepositoryRef(
        repository_id=repository_id,
        root_path=str(repo_path),
        target_branch="main",
        expected_remote="git@github.com:farnai/Jester.git",
        allow_untracked=True,
    )
    repo_policy = RepositoryPolicy(
        read_allowed=("docs/**", "frontend/**", "backend/**", "*.md"),
        mutation_allowed=(),
        denied=(".git/**", ".env*", "*.secret"),
    )
    project = RepositoryProject(
        project_id=project_id,
        name="Jester Platform",
        description="Relationship Intelligence Platform",
        repository=repo_ref,
        policy=repo_policy,
    )
    service.project_registry.register_project(project)
    service.create_project(
        project_id=project_id,
        name="Jester Platform",
        root_path=str(repo_path),
    )

    manifest = create_jester_registration_manifest(project_id=project_id, repository_id=repository_id)
    service.register_project_knowledge_manifest(manifest)

    prod_emp = service.company.get_employee("product")
    if prod_emp:
        prod_emp.tools = []

    return service, project, manifest


# ==============================================================================
# Tests: Issue A — Project-Agnostic Context Guard
# ==============================================================================

def test_generic_product_and_ux_prompt_builders_are_project_agnostic():
    """Verify that build_product_execution_prompt and build_ux_execution_prompt contain ZERO hardcoded Jester branding."""
    dummy_task = Task(
        id="task_generic",
        project_id="prj_generic",
        title="Generic Feature Specification",
        goal="Define requirements for an arbitrary software project.",
        constraints=["Preserve existing APIs", "Deliver within 2 weeks"],
        required_roles=["product"],
        expected_output=["PRD document"],
    )

    product_prompt = build_product_execution_prompt(dummy_task)
    ux_prompt = build_ux_execution_prompt(dummy_task)

    for p, role in [(product_prompt, "Product"), (ux_prompt, "UX")]:
        # 1. Must NOT contain hardcoded Jester project name
        assert "Jester" not in p, f"{role} prompt builder must not contain hardcoded 'Jester'"
        assert "jester" not in p.lower() or "jester" in dummy_task.id.lower(), f"{role} prompt builder must not contain 'jester'"

        # 2. Must NOT contain hardcoded ORANGE or Indigo
        assert "ORANGE" not in p, f"{role} prompt builder must not contain hardcoded 'ORANGE'"
        assert "#6366f1" not in p, f"{role} prompt builder must not contain hardcoded Indigo '#6366f1'"
        assert "Indigo" not in p, f"{role} prompt builder must not contain hardcoded 'Indigo'"

        # 3. Must contain generic Source Authority Hierarchy and Conflict Resolution Rules
        assert "SOURCE AUTHORITY & CONFLICT RESOLUTION HIERARCHY:" in p
        assert "1. Authorized Founder Objective and explicit constraints (HIGHEST PRIORITY)." in p
        assert "CONFLICT RESOLUTION RULES:" in p
        assert "Lower-authority sources CANNOT override higher-authority constraints or Founder directives." in p


def test_jester_orange_branding_delivered_strictly_from_task_context(realistic_jester_repo: Path):
    """Verify that Jester's ORANGE directive is delivered legitimately via task.constraints and enforced by the hierarchy."""
    runtime = make_mock_runtime(json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "Registration PRD adhering to Founder ORANGE directive.",
        "deliverables": [{"name": "PRD", "content": "Orange accent specified."}],
        "risks": [],
        "open_questions": [],
    }))
    service, _, _ = build_service_with_manifest(realistic_jester_repo, runtime)

    # Create task with Founder Orange constraint explicitly
    task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Jester Registration Flow Redesign",
        goal="Design registration flow adhering to canonical documents.",
        required_roles=["product"],
        constraints=[
            "Preserve Georgian localization",
            "Founder mandate: Light UI with ORANGE as primary active/accent color. Do NOT silently substitute Indigo for Orange.",
        ],
    )

    run = service.execute_product_task(task_id=task.id, project_id="prj_jester")
    assert run.status == RunStatus.SUCCESS.value

    call_kwargs = runtime.execute.call_args[1]
    prompt = call_kwargs["prompt"]

    # 1. Orange requirement is present in prompt via Constraints:
    assert "Founder mandate: Light UI with ORANGE as primary active/accent color." in prompt
    assert "Do NOT silently substitute Indigo for Orange." in prompt

    # 2. Source authority hierarchy reinforces that this constraint is top priority
    assert "SOURCE AUTHORITY & CONFLICT RESOLUTION HIERARCHY:" in prompt
    assert "1. Authorized Founder Objective and explicit constraints (HIGHEST PRIORITY)." in prompt


def test_cross_project_isolation_independent_project_retains_own_branding(realistic_jester_repo: Path):
    """Verify that a separate fictional project (Project Emerald) receives its own branding with zero Jester/Orange leakage."""
    with tempfile.TemporaryDirectory(prefix="emerald_repo_") as tmp:
        emerald_path = Path(tmp).resolve()
        (emerald_path / "docs").mkdir(parents=True, exist_ok=True)
        (emerald_path / "docs" / "SPEC.md").write_text("# Project Emerald\n\nFintech system.", encoding="utf-8")
        run_git(["init", "-b", "main"], cwd=emerald_path)
        run_git(["config", "user.name", "EmeraldDev"], cwd=emerald_path)
        run_git(["config", "user.email", "dev@emerald.com"], cwd=emerald_path)
        run_git(["add", "."], cwd=emerald_path)
        run_git(["commit", "-m", "init emerald"], cwd=emerald_path)

        runtime = make_mock_runtime(json.dumps({
            "schema_version": "1.0",
            "status": "completed",
            "summary": "Emerald PRD completed.",
            "deliverables": [{"name": "PRD", "content": "Dark UI with emerald green accents."}],
            "risks": [],
            "open_questions": [],
        }))

        mock_runtime_obj = runtime
        service = CompanyService(output_dir=str(emerald_path / "output"), runtime=mock_runtime_obj)

        # Register Emerald project
        repo_ref = RepositoryRef(
            repository_id="repo_emerald",
            root_path=str(emerald_path),
            target_branch="main",
            expected_remote="git@github.com:farnai/Emerald.git",
            allow_untracked=True,
        )
        project = RepositoryProject(
            project_id="prj_emerald",
            name="Emerald Platform",
            description="Fintech System",
            repository=repo_ref,
            policy=RepositoryPolicy(read_allowed=("docs/**", "*.md"), mutation_allowed=()),
        )
        service.project_registry.register_project(project)
        service.create_project(project_id="prj_emerald", name="Emerald Platform", root_path=str(emerald_path))

        manifest = ProjectKnowledgeManifest(
            project_id="prj_emerald",
            repository_id="repo_emerald",
            sources=(
                ProjectKnowledgeSource(
                    source_id="emerald_spec",
                    relative_path="docs/SPEC.md",
                    domain="product",
                    authority=SourceAuthority.AUTHORITATIVE,
                    truth_scope=TruthScope.SPECIFICATION,
                    load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
                ),
            ),
        )
        service.register_project_knowledge_manifest(manifest)

        task = service.create_task(
            project_id="prj_emerald",
            title="[PRODUCT] Emerald Login Flow",
            goal="Define requirements for Emerald system.",
            required_roles=["product"],
            constraints=["Founder mandate: Dark UI with EMERALD (#10b981) as primary accent color."],
        )

        run = service.execute_product_task(task_id=task.id, project_id="prj_emerald")
        assert run.status == RunStatus.SUCCESS.value

        call_kwargs = mock_runtime_obj.execute.call_args[1]
        prompt = call_kwargs["prompt"]

        # 1. Contains Emerald's branding
        assert "Dark UI with EMERALD (#10b981)" in prompt
        assert "Source ID: emerald_spec" in prompt

        # 2. MUST NOT contain Jester or Orange or Indigo
        assert "JESTER" not in prompt
        assert "ORANGE" not in prompt
        assert "#6366f1" not in prompt
        assert "Indigo" not in prompt


# ==============================================================================
# Tests: Issue B — Mandatory Documentation Content Coverage
# ==============================================================================

def test_full_document_truncation_omits_late_sections_and_marks_partial(realistic_jester_repo: Path):
    """Verify that loading a 19KB file as FULL_DOCUMENT with 4,000 max_chars omits late sections and marks Coverage: PARTIAL."""
    manifest = ProjectKnowledgeManifest(
        project_id="prj_jester",
        repository_id="repo_jester",
        sources=(
            ProjectKnowledgeSource(
                source_id="jester_full_foundation",
                relative_path="docs/JESTER_PRODUCT_FOUNDATION.md",
                domain="product",
                authority=SourceAuthority.AUTHORITATIVE,
                truth_scope=TruthScope.SPECIFICATION,
                load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
            ),
        ),
    )
    catalog = ProjectKnowledgeCatalog(
        manifest=manifest,
        repo_policy=RepositoryPolicy(read_allowed=("docs/**",)),
        repo_root=realistic_jester_repo,
    )

    src = manifest.get_source("jester_full_foundation")
    excerpt = catalog.load_excerpt(src, repository_revision="HEAD", max_chars=4000)

    # 1. Excerpt is accurately flagged as truncated
    assert excerpt.is_truncated is True
    assert excerpt.character_count <= 4100
    assert "... [content truncated due to budget limit]" in excerpt.content

    # 2. Formatted prompt block explicitly states Coverage: PARTIAL
    block = format_project_knowledge_prompt_block([excerpt])
    assert "Coverage: PARTIAL (Truncated by budget limit)" in block

    # 3. Critical Section 11 (Authentication Boundary) is OMITTED from the 4,000-char head
    assert "Credentials-Only Registration" not in excerpt.content
    assert "Route: /auth/register             │  ───► │    Route: /onboarding" not in excerpt.content


def test_section_excerpt_delivers_complete_credentials_only_and_onboarding_rules(realistic_jester_repo: Path):
    """Verify that multi-anchor SECTION_EXCERPT delivers complete, untruncated credentials-only and onboarding transition rules."""
    manifest = create_jester_registration_manifest()
    catalog = ProjectKnowledgeCatalog(
        manifest=manifest,
        repo_policy=RepositoryPolicy(read_allowed=("docs/**", "frontend/**")),
        repo_root=realistic_jester_repo,
    )

    src = manifest.get_source("jester_product_foundation")
    excerpt = catalog.load_excerpt(src, repository_revision="HEAD", max_chars=4000)

    # 1. Excerpt is COMPLETE and not truncated
    assert excerpt.is_truncated is False
    assert excerpt.character_count < 4000

    # 2. Contains Section 11 (Authentication Boundary): credentials-only and onboarding transition
    assert "Credentials-Only Registration" in excerpt.content
    assert "`/auth/register` accepts only `email`, `password`, and `confirm_password`" in excerpt.content
    assert "First name, last name, birth data, and location are never requested on the registration form." in excerpt.content
    assert "Route: /auth/register             │  ───► │    Route: /onboarding" in excerpt.content
    assert "Abandonment Safety" in excerpt.content

    # 3. Contains Section 13 (Georgian-First Requirement)
    assert "Georgian-first (`locale: \"ka\"`)" in excerpt.content
    assert "Mkhedruli script has no native uppercase/lowercase distinction" in excerpt.content
    assert "minimum line-height 1.55" in excerpt.content

    # 4. Formatted prompt block displays Coverage: COMPLETE
    block = format_project_knowledge_prompt_block([excerpt])
    assert "Coverage: COMPLETE" in block


def test_product_execution_receives_actual_jester_registration_foundation(realistic_jester_repo: Path):
    """Verify that Product execution prompt contains all required Jester registration foundation excerpts."""
    runtime = make_mock_runtime(json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "Registration PRD based on authentic Jester foundation documents.",
        "deliverables": [{"name": "Registration PRD", "content": "Credentials-only registration specification."}],
        "risks": [],
        "open_questions": [],
    }))
    service, _, _ = build_service_with_manifest(realistic_jester_repo, runtime)

    task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Jester Registration Redesign",
        goal="Specify registration requirements from authentic project foundation.",
        required_roles=["product"],
        constraints=["Preserve Georgian localization", "Light UI with ORANGE accent"],
        metadata={"mandatory_knowledge_sources": ["jester_product_foundation", "jester_strategic_marketing"]},
    )

    run = service.execute_product_task(task_id=task.id, project_id="prj_jester")
    assert run.status == RunStatus.SUCCESS.value

    call_kwargs = runtime.execute.call_args[1]
    prompt = call_kwargs["prompt"]

    # 1. Product foundation: Credentials-only registration & onboarding transition present
    assert "Source ID: jester_product_foundation" in prompt
    assert "Credentials-Only Registration:" in prompt
    assert "`/auth/register` accepts only `email`, `password`, and `confirm_password`" in prompt
    assert "Route: /auth/register             │  ───► │    Route: /onboarding" in prompt
    assert "Abandonment Safety" in prompt

    # 2. Strategic marketing axiom present
    assert "Source ID: jester_strategic_marketing" in prompt
    assert "They show the match. JESTER explains the connection." in prompt
    assert "THE INSIGHT BECOMES THE INVITATION." in prompt


def test_ux_execution_receives_design_exploration_tokens_and_current_code(realistic_jester_repo: Path):
    """Verify that UX execution prompt receives design exploration rules, color tokens, and RegisterPage code."""
    prod_deliverable_text = "PRD: Credentials-only registration (email, password, confirmPassword). Transition to /onboarding. Primary accent: ORANGE."
    prod_json = json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "Registration PRD adhering to Founder ORANGE directive.",
        "deliverables": [{"name": "PRD", "content": prod_deliverable_text}],
        "risks": [],
        "open_questions": [],
    })
    ux_json = json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "UX architecture for registration flow.",
        "flows": [
            {
                "name": "Registration Flow",
                "description": "Credentials-only registration navigating to onboarding.",
                "steps": ["User enters email", "User enters password", "Submit to Supabase"],
            }
        ],
        "screens": [
            {
                "name": "Register Page",
                "purpose": "Capture credentials with Georgian-first localization.",
                "states": ["initial", "validating", "submitting", "error"],
            }
        ],
        "interaction_rules": [
            "Orange active accent on primary buttons",
            "Mkhedruli typography with 1.55 line height",
        ],
        "accessibility_considerations": ["High contrast labels", "Mkhedruli screen reader support"],
    })

    def fake_execute(agent, prompt, timeout=300):
        out = prod_json if agent == "product" else ux_json
        return AgentExecutionResult(
            agent=agent,
            success=True,
            exit_code=0,
            stdout=out,
            stderr="",
            timed_out=False,
            duration_ms=25.0,
        )

    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.side_effect = fake_execute
    service, _, _ = build_service_with_manifest(realistic_jester_repo, runtime)

    # 1. Product run
    prod_task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Registration PRD",
        goal="Produce PRD",
        required_roles=["product"],
    )
    prod_run = service.execute_product_task(task_id=prod_task.id, project_id="prj_jester")
    prod_art = prod_run.artifacts[0]

    # 2. UX task consuming Product artifact
    ux_task = service.create_task(
        project_id="prj_jester",
        title="[UX] Registration Architecture",
        goal="Map screen states and tokens.",
        required_roles=["ux"],
        constraints=["Founder mandate: Light UI with ORANGE accent. Do not substitute Indigo."],
        metadata={"mandatory_knowledge_sources": [
            "jester_design_exploration",
            "jester_ui_tokens",
            "jester_register_component",
        ]},
    )
    service.attach_input_artifact(
        target_task_id=ux_task.id,
        source_artifact_id=prod_art.id,
        project_id="prj_jester",
    )

    ux_run = service.execute_ux_task(task_id=ux_task.id, project_id="prj_jester")
    assert ux_run.status == RunStatus.SUCCESS.value

    call_kwargs = runtime.execute.call_args[1]
    prompt = call_kwargs["prompt"]

    # Upstream Product artifact verified
    assert "UPSTREAM VERIFIED ARTIFACT" in prompt
    assert prod_deliverable_text in prompt
    assert prod_art.sha256 in prompt

    # Design exploration: color palette and typography rules
    assert "Source ID: jester_design_exploration" in prompt
    assert "Color Exploration" in prompt
    assert 'accent: "#6366f1"' in prompt
    assert "Mkhedruli Script Mechanics" in prompt
    assert "No Native Upper/Lower Case" in prompt

    # Code evidence: color tokens and current component
    assert "Source ID: jester_ui_tokens" in prompt
    assert "export const colors =" in prompt
    assert "Source ID: jester_register_component" in prompt
    assert "export const RegisterPage: React.FC" in prompt
    assert "handleAccountSubmit" in prompt


def test_missing_mandatory_source_in_task_metadata_fails_closed(realistic_jester_repo: Path):
    """Verify that if a task metadata specifies a missing mandatory source ID, execution fails closed."""
    runtime = make_mock_runtime("{}")
    service, _, _ = build_service_with_manifest(realistic_jester_repo, runtime)

    task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Task with Missing Mandatory Source",
        goal="Test failure",
        required_roles=["product"],
        metadata={"mandatory_knowledge_sources": ["non_existent_source_id"]},
    )

    with pytest.raises(KnowledgeNotFoundError) as exc_info:
        service.execute_product_task(task_id=task.id, project_id="prj_jester")
    assert "non_existent_source_id" in str(exc_info.value)


def test_zero_research_llm_invocation_for_jester_context_delivery(realistic_jester_repo: Path):
    """Verify that zero Research agents or LLMs are invoked simply to transmit Jester documentation."""
    runtime = make_mock_runtime(json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "Product registration PRD.",
        "deliverables": [{"name": "PRD", "content": "Done"}],
        "risks": [],
        "open_questions": [],
    }))
    service, _, _ = build_service_with_manifest(realistic_jester_repo, runtime)

    task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Registration Flow Redesign",
        goal="Define registration requirements.",
        required_roles=["product"],
    )

    run = service.execute_product_task(task_id=task.id, project_id="prj_jester")
    assert run.status == RunStatus.SUCCESS.value

    # Exactly 1 execution call occurred (the Product agent itself), ZERO research calls
    assert runtime.execute.call_count == 1
    call_kwargs = runtime.execute.call_args[1]
    assert call_kwargs["agent"] == "product"
