"""Deterministic integration tests for STEP 23B.7-G.1: Verified Project Context Delivery Fix.

Validates that Product and UX agents deterministically receive authentic, verified,
and bounded project documentation through the existing Python orchestration system
without expanding specialist permissions and without creating new CompanyRuns.

Scenarios tested:
- Scenario A: Product receives actual documentation excerpts in its execution prompt.
- Scenario B: UX receives actual design excerpts and verified Product artifact.
- Scenario C: Product -> UX artifact integrity remains strictly enforced.
- Scenario D: Project A cannot accidentally receive knowledge from Project B.
- Scenario E: Missing mandatory documentation results in a controlled validation failure.
- Scenario F: Large documentation is bounded without falsely claiming complete coverage.
- Scenario G: Invalid source paths, traversal attempts, and unauthorized locations are rejected.
- Scenario H: Existing agents without documentation requirements remain compatible.
- Scenario I: Structured JSON parsing continues to work.
- Scenario J: System does not require an additional Research LLM invocation to transmit documentation.
"""

import hashlib
import json
from pathlib import Path
import tempfile
from typing import Tuple
from unittest.mock import MagicMock
import pytest

from jester_ai_company.core import (
    Artifact,
    ArtifactInputRef,
    ArtifactType,
    ArtifactVerificationError,
    RunStatus,
    Task,
    TaskStatus,
)
from jester_ai_company.context import (
    ContextEnvelope,
    format_project_knowledge_prompt_block,
)
from jester_ai_company.knowledge import (
    FreshnessStatus,
    KnowledgeError,
    KnowledgeLoadPolicy,
    KnowledgeNotFoundError,
    KnowledgePolicyViolationError,
    ProjectContextExcerpt,
    ProjectKnowledgeCatalog,
    ProjectKnowledgeManifest,
    ProjectKnowledgeSource,
    RoleKnowledgePolicy,
    SourceAuthority,
    TruthScope,
)
from jester_ai_company.product_result import (
    ProductDeliverable,
    ProductTaskResult,
    build_product_execution_prompt,
    parse_and_validate_product_result,
)
from jester_ai_company.project import (
    PolicyViolationError,
    Project,
    RepositoryPolicy,
    RepositoryRef,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import (
    CompanyService,
    InvalidTaskStateError,
    TaskNotFoundError,
)
from jester_ai_company.ux_result import (
    UXFlow,
    UXScreenState,
    UXTaskResult,
    build_ux_execution_prompt,
    parse_and_validate_ux_result,
)


from jester_ai_company.worktree import run_git


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def temp_jester_repo():
    """Create an isolated temporary repository mimicking Jester's documentation and tokens."""
    with tempfile.TemporaryDirectory(prefix="jester_test_repo_") as tmp:
        repo_path = Path(tmp).resolve()
        (repo_path / "docs").mkdir(parents=True, exist_ok=True)
        (repo_path / "frontend" / "src" / "ui" / "tokens").mkdir(parents=True, exist_ok=True)
        (repo_path / "frontend" / "src" / "modules" / "auth").mkdir(parents=True, exist_ok=True)

        # 1. Product foundation
        prod_doc = (
            "# JESTER — Product Foundation\n\n"
            "**Authority Level:** Level 2\n"
            "**Status:** LOCKED PRODUCT DECISION\n\n"
            "JESTER is a People Discovery and Relationship Intelligence platform.\n"
            "It is engineered to help human beings understand themselves and other people.\n"
            "Core registration behavior preserves Georgian-first localization.\n"
        )
        (repo_path / "docs" / "JESTER_PRODUCT_FOUNDATION.md").write_text(prod_doc, encoding="utf-8")

        # 2. Design exploration
        design_doc = (
            "# JESTER — Design Exploration & UI/UX Proposals\n\n"
            "**Authority Level:** Level 6 (Proposals & Explorations)\n"
            "**Status:** WORKING EXPLORATION\n\n"
            "## 1. Aesthetic Direction: Editorial Digital Luxury [PROPOSAL]\n"
            "Crisp typography and intentional whitespace.\n\n"
            "## 2. Color Exploration\n"
            "Section 2.1 Baseline Token Palette [PROPOSAL]\n"
            "accent: #6366f1 (Electric Royal Indigo)\n"
            "Section 2.2 Warm Terracotta & Monochromatic Alternatives [EXPLORATION]\n"
        )
        (repo_path / "docs" / "JESTER_DESIGN_EXPLORATION.md").write_text(design_doc, encoding="utf-8")

        # 3. Strategic marketing foundation
        mkt_doc = (
            "# JESTER — Strategic Marketing Foundation\n\n"
            "**Status:** Authoritative Strategic Guide\n"
            "They show the match. JESTER explains the connection.\n"
            "The insight becomes the invitation.\n"
        )
        (repo_path / "docs" / "JESTER_STRATEGIC_MARKETING_FOUNDATION.md").write_text(mkt_doc, encoding="utf-8")

        # 4. Color tokens
        token_code = (
            'export const colors = {\n'
            '  background: "#f8fafc",\n'
            '  surface: "#ffffff",\n'
            '  accent: "#6366f1",\n'
            '  orangePrimary: "#ea580c",\n'
            '} as const;\n'
        )
        (repo_path / "frontend" / "src" / "ui" / "tokens" / "colors.ts").write_text(token_code, encoding="utf-8")

        # 5. Registration component
        reg_code = (
            'import React from "react";\n'
            'export const RegisterPage: React.FC = () => {\n'
            '  return <div className="register-container">რეგისტრაცია (Registration)</div>;\n'
            '};\n'
        )
        (repo_path / "frontend" / "src" / "modules" / "auth" / "RegisterPage.tsx").write_text(reg_code, encoding="utf-8")

        # Initialize Git repository
        run_git(["init", "-b", "main"], cwd=repo_path)
        run_git(["config", "user.name", "Test Committer"], cwd=repo_path)
        run_git(["config", "user.email", "committer@example.com"], cwd=repo_path)
        run_git(["add", "."], cwd=repo_path)
        run_git(["commit", "-m", "Initial commit"], cwd=repo_path)

        yield repo_path


@pytest.fixture
def temp_project_b_repo():
    """Create an isolated second repository (Project B)."""
    with tempfile.TemporaryDirectory(prefix="project_b_repo_") as tmp:
        repo_path = Path(tmp).resolve()
        (repo_path / "docs").mkdir(parents=True, exist_ok=True)
        (repo_path / "docs" / "PROJECT_B_SPEC.md").write_text(
            "# PROJECT B SECRET SPEC\nConfidential information for Project B only.\n",
            encoding="utf-8",
        )
        run_git(["init", "-b", "main"], cwd=repo_path)
        run_git(["config", "user.name", "Test Committer"], cwd=repo_path)
        run_git(["config", "user.email", "committer@example.com"], cwd=repo_path)
        run_git(["add", "."], cwd=repo_path)
        run_git(["commit", "-m", "Initial commit"], cwd=repo_path)

        yield repo_path


def make_mock_runtime(agent_response_stdout: str = "") -> MagicMock:
    """Mock AntigravityRuntime capturing execution prompt and arguments."""
    runtime = MagicMock(spec=AntigravityRuntime)
    runtime.execute.return_value = AgentExecutionResult(
        agent="product",
        success=True,
        exit_code=0,
        stdout=agent_response_stdout,
        stderr="",
        timed_out=False,
        duration_ms=50.0,
    )
    return runtime


def build_service_with_jester(temp_jester_repo: Path, mock_runtime: MagicMock) -> Tuple[CompanyService, Project, ProjectKnowledgeManifest]:
    """Set up CompanyService with Jester project and registered knowledge manifest."""
    service = CompanyService(output_dir=str(temp_jester_repo / "output"), runtime=mock_runtime)

    repo_ref = RepositoryRef(
        repository_id="repo_jester",
        root_path=str(temp_jester_repo),
        target_branch="main",
        expected_remote="git@github.com:farnai/Jester.git",
        allow_untracked=True,
    )
    repo_policy = RepositoryPolicy(
        read_allowed=("docs/**", "frontend/**", "backend/**", "*.md"),
        mutation_allowed=(),
        denied=(".git/**", ".env*", "*.secret"),
    )
    project = Project(
        project_id="prj_jester",
        name="Jester Platform",
        description="Relationship Intelligence Platform",
        repository=repo_ref,
        policy=repo_policy,
    )
    service.project_registry.register_project(project)
    service.create_project(
        project_id="prj_jester",
        name="Jester Platform",
        root_path=str(temp_jester_repo),
    )

    manifest = ProjectKnowledgeManifest(
        project_id="prj_jester",
        repository_id="repo_jester",
        sources=(
            ProjectKnowledgeSource(
                source_id="jester_product_foundation",
                relative_path="docs/JESTER_PRODUCT_FOUNDATION.md",
                domain="product",
                authority=SourceAuthority.AUTHORITATIVE,
                truth_scope=TruthScope.SPECIFICATION,
                load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
                description="Canonical Product Foundation",
            ),
            ProjectKnowledgeSource(
                source_id="jester_design_exploration",
                relative_path="docs/JESTER_DESIGN_EXPLORATION.md",
                domain="ux",
                authority=SourceAuthority.EXPLORATORY,
                truth_scope=TruthScope.SPECIFICATION,
                load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
                description="Design proposals and exploratory UI options",
            ),
            ProjectKnowledgeSource(
                source_id="jester_strategic_marketing",
                relative_path="docs/JESTER_STRATEGIC_MARKETING_FOUNDATION.md",
                domain="marketing",
                authority=SourceAuthority.AUTHORITATIVE,
                truth_scope=TruthScope.SPECIFICATION,
                load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
                description="Strategic marketing guide",
            ),
            ProjectKnowledgeSource(
                source_id="jester_ui_tokens",
                relative_path="frontend/src/ui/tokens/colors.ts",
                domain="frontend",
                authority=SourceAuthority.AUTHORITATIVE,
                truth_scope=TruthScope.IMPLEMENTATION,
                load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
                description="Color tokens implementation",
            ),
            ProjectKnowledgeSource(
                source_id="jester_register_component",
                relative_path="frontend/src/modules/auth/RegisterPage.tsx",
                domain="frontend",
                authority=SourceAuthority.AUTHORITATIVE,
                truth_scope=TruthScope.IMPLEMENTATION,
                load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
                description="Existing registration page component",
            ),
        ),
    )
    service.knowledge_registry.register_manifest(manifest)
    prod_emp = service.company.get_employee("product")
    if prod_emp:
        prod_emp.tools = []
    return service, project, manifest


# ==============================================================================
# Tests
# ==============================================================================

def test_scenario_a_product_receives_actual_documentation_excerpts(temp_jester_repo: Path):
    """Scenario A: Product receives actual documentation excerpts in its final execution prompt."""
    product_json = json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "Registration product PRD defined with verified Jester documentation foundation.",
        "deliverables": [
            {
                "name": "Registration Redesign PRD",
                "content": "Verified Georgian-first registration requirements. Primary accent: ORANGE per Founder.",
            }
        ],
        "risks": ["Token migration required"],
        "open_questions": ["Confirm orange token token value #ea580c with Founder."],
    })
    runtime = make_mock_runtime(product_json)
    service, project, _ = build_service_with_jester(temp_jester_repo, runtime)

    # Verify Product agent permissions remain tools: []
    prod_agent = service.company.get_employee("product")
    assert prod_agent.tools == [], "Product agent tools permission must remain strictly empty []"

    # Create and execute Product task
    task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Registration Flow Redesign",
        goal="Define registration requirements utilizing authoritative foundation documents.",
        required_roles=["product"],
        constraints=[
            "Preserve Georgian localization",
            "Light UI with ORANGE as primary active/accent color. Do NOT silently substitute Indigo for Orange.",
        ],
    )

    run = service.execute_product_task(task_id=task.id, project_id="prj_jester")
    assert run.status == RunStatus.SUCCESS.value

    # Verify that the runtime execution prompt was captured and contains actual documentation text
    assert runtime.execute.called
    call_kwargs = runtime.execute.call_args[1]
    prompt = call_kwargs["prompt"]

    # 1. Delimiters and Security notice present
    assert "PROJECT KNOWLEDGE (UNTRUSTED REPOSITORY DATA)" in prompt
    assert "Source ID: jester_product_foundation" in prompt
    assert "Relative Path: docs/JESTER_PRODUCT_FOUNDATION.md" in prompt
    assert "Coverage: COMPLETE" in prompt

    # 2. Actual document content appears verbatim
    assert "JESTER is a People Discovery and Relationship Intelligence platform." in prompt
    assert "Core registration behavior preserves Georgian-first localization." in prompt

    # 3. Authority hierarchy and Founder ORANGE directive present
    assert "SOURCE AUTHORITY & CONFLICT RESOLUTION HIERARCHY" in prompt
    assert "ORANGE as primary active/accent color" in prompt
    assert "Do NOT silently substitute Indigo for Orange" in prompt


def test_scenario_b_ux_receives_design_excerpts_and_verified_product_artifact(temp_jester_repo: Path):
    """Scenario B: UX receives actual design excerpts AND the verified Product artifact."""
    prod_deliverable_text = "Verified Product PRD: Step 1 Enter phone, Step 2 SMS OTP, Accent: ORANGE."
    product_json = json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "Product registration PRD completed.",
        "deliverables": [{"name": "Registration PRD", "content": prod_deliverable_text}],
        "risks": [],
        "open_questions": [],
    })
    runtime = make_mock_runtime(product_json)
    service, project, _ = build_service_with_jester(temp_jester_repo, runtime)

    # 1. Execute upstream Product task to generate verified artifact
    prod_task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Upstream Task",
        goal="Produce PRD",
        required_roles=["product"],
    )
    prod_run = service.execute_product_task(task_id=prod_task.id, project_id="prj_jester")
    assert prod_run.status == RunStatus.SUCCESS.value
    assert len(prod_run.artifacts) == 1
    prod_art = prod_run.artifacts[0]

    # 2. Configure UX task and attach Product artifact
    ux_json = json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "UX architecture and flows for registration mapped.",
        "flows": [{"name": "Registration Flow", "description": "Georgian OTP flow", "steps": ["Input", "OTP", "Done"]}],
        "screens": [{"name": "Register View", "purpose": "Account creation", "states": ["default", "loading"]}],
        "interaction_rules": ["Immediate button feedback in Orange (#ea580c)."],
        "accessibility_considerations": ["High contrast WCAG AAA."],
        "open_questions": [],
    })
    runtime.execute.return_value = AgentExecutionResult(
        agent="ux",
        success=True,
        exit_code=0,
        stdout=ux_json,
        stderr="",
        timed_out=False,
        duration_ms=50.0,
    )

    ux_task = service.create_task(
        project_id="prj_jester",
        title="[UX] Registration Architecture",
        goal="Map screen states and flows adhering to Product requirements and design tokens.",
        required_roles=["ux"],
        constraints=[
            "Light UI with ORANGE as primary active/accent color. Do NOT silently substitute Indigo for Orange.",
        ],
    )
    service.attach_input_artifact(
        target_task_id=ux_task.id,
        source_artifact_id=prod_art.id,
        project_id="prj_jester",
    )

    ux_run = service.execute_ux_task(task_id=ux_task.id, project_id="prj_jester")
    assert ux_run.status == RunStatus.SUCCESS.value

    # Inspect UX prompt
    call_kwargs = runtime.execute.call_args[1]
    prompt = call_kwargs["prompt"]

    # 1. Upstream Product artifact is present in verified section
    assert "UPSTREAM VERIFIED ARTIFACT" in prompt
    assert prod_deliverable_text in prompt
    assert prod_art.sha256 in prompt

    # 2. Design excerpts are present
    assert "Source ID: jester_design_exploration" in prompt
    assert "Editorial Digital Luxury" in prompt
    assert "Section 2.1 Baseline Token Palette" in prompt
    assert "Source ID: jester_ui_tokens" in prompt
    assert 'export const colors = {' in prompt

    # 3. Registration component evidence is present
    assert "Source ID: jester_register_component" in prompt
    assert "RegisterPage: React.FC" in prompt

    # 4. Authority hierarchy is reinforced
    assert "SOURCE AUTHORITY & CONFLICT RESOLUTION HIERARCHY" in prompt
    assert "Do NOT silently substitute Indigo for Orange" in prompt


def test_scenario_c_product_to_ux_artifact_integrity_enforced(temp_jester_repo: Path):
    """Scenario C: Existing Product -> UX artifact integrity remains strictly enforced."""
    runtime = make_mock_runtime("{}")
    service, project, _ = build_service_with_jester(temp_jester_repo, runtime)

    # Create dummy artifact with non-matching hash
    fake_art = Artifact(
        id="art_corrupted",
        name="corrupted_art",
        artifact_type=ArtifactType.SPECIFICATION.value,
        path="artifacts/corrupted.json",
        sha256="0000000000000000000000000000000000000000000000000000000000000000",
        durable=True,
        producer_role="product",
    )

    ux_task = service.create_task(
        project_id="prj_jester",
        title="[UX] Task with Corrupted Input",
        goal="Design screen",
        required_roles=["ux"],
    )
    # Tamper input_artifacts list directly
    ux_task.input_artifacts.append(
        ArtifactInputRef(
            artifact_id=fake_art.id,
            run_id="run_prod",
            sha256=fake_art.sha256,
            producer_role="product",
        )
    )

    # Must fail closed with ArtifactVerificationError
    with pytest.raises(ArtifactVerificationError) as exc_info:
        service.execute_ux_task(task_id=ux_task.id, project_id="prj_jester")
    assert "could not be found" in str(exc_info.value)


def test_scenario_d_project_isolation_cross_project_leakage_prevented(
    temp_jester_repo: Path,
    temp_project_b_repo: Path,
):
    """Scenario D: Project A cannot accidentally receive knowledge from Project B."""
    runtime = make_mock_runtime("{}")
    service, _, _ = build_service_with_jester(temp_jester_repo, runtime)

    # Register Project B
    repo_ref_b = RepositoryRef(
        repository_id="repo_b",
        root_path=str(temp_project_b_repo),
        target_branch="main",
        expected_remote="git@github.com:farnai/ProjectB.git",
        allow_untracked=True,
    )
    repo_policy_b = RepositoryPolicy(
        read_allowed=("docs/**", "*.md"),
        mutation_allowed=(),
    )
    project_b = Project(
        project_id="prj_b",
        name="Project B",
        description="Unrelated company project",
        repository=repo_ref_b,
        policy=repo_policy_b,
    )
    service.project_registry.register_project(project_b)

    manifest_b = ProjectKnowledgeManifest(
        project_id="prj_b",
        repository_id="repo_b",
        sources=(
            ProjectKnowledgeSource(
                source_id="project_b_spec",
                relative_path="docs/PROJECT_B_SPEC.md",
                domain="product",
                authority=SourceAuthority.AUTHORITATIVE,
                truth_scope=TruthScope.SPECIFICATION,
                load_policy=KnowledgeLoadPolicy.FULL_DOCUMENT,
                description="Project B confidential spec",
            ),
        ),
    )
    service.knowledge_registry.register_manifest(manifest_b)

    # Verify Project A catalog only contains Project A sources
    catalog_a = service.get_project_knowledge_catalog("prj_jester")
    assert catalog_a is not None
    assert catalog_a.get_source("project_b_spec") is None
    sources_a = catalog_a.list_sources()
    assert all("PROJECT_B" not in s.relative_path for s in sources_a)

    # Cross-project loading attempt inside Project A catalog fails closed
    with pytest.raises(KnowledgeNotFoundError):
        catalog_a.require_source("project_b_spec")

    with pytest.raises(PolicyViolationError):
        ProjectKnowledgeSource(
            source_id="leakage_attempt",
            relative_path=str(Path("..") / temp_project_b_repo.name / "docs" / "PROJECT_B_SPEC.md"),
            domain="product",
            authority=SourceAuthority.AUTHORITATIVE,
            truth_scope=TruthScope.SPECIFICATION,
        )


def test_scenario_e_missing_mandatory_documentation_fails_closed(temp_jester_repo: Path):
    """Scenario E: Missing mandatory documentation results in a controlled validation failure."""
    runtime = make_mock_runtime("{}")
    service, project, _ = build_service_with_jester(temp_jester_repo, runtime)

    task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Task Requiring Missing Doc",
        goal="Requirements",
        required_roles=["product"],
    )

    # 1. Mandatory source not configured in manifest
    with pytest.raises(KnowledgeNotFoundError) as exc_info:
        service.execute_product_task(
            task_id=task.id,
            project_id="prj_jester",
            mandatory_source_ids=["non_existent_mandatory_doc"],
        )
    assert "Mandatory knowledge source 'non_existent_mandatory_doc' not found" in str(exc_info.value)

    # 2. Mandatory source configured in manifest, but file missing on disk
    catalog = service.get_project_knowledge_catalog("prj_jester")
    assert catalog is not None
    missing_file_src = ProjectKnowledgeSource(
        source_id="missing_on_disk_source",
        relative_path="docs/NON_EXISTENT_FILE.md",
        domain="product",
        authority=SourceAuthority.AUTHORITATIVE,
        truth_scope=TruthScope.SPECIFICATION,
    )
    policy_with_missing = RoleKnowledgePolicy(
        role="product",
        mandatory_source_ids=("missing_on_disk_source",),
    )
    # Register in manifest
    updated_sources = list(catalog.manifest.sources) + [missing_file_src]
    catalog.manifest = ProjectKnowledgeManifest(
        project_id=catalog.manifest.project_id,
        repository_id=catalog.manifest.repository_id,
        sources=tuple(updated_sources),
    )
    with pytest.raises(KnowledgeNotFoundError) as exc_info2:
        catalog.select_sources_for_role(policy_with_missing)
    assert "does not exist at" in str(exc_info2.value)


def test_scenario_f_large_documentation_bounded_without_false_complete_claims(temp_jester_repo: Path):
    """Scenario F: Large documentation is bounded without falsely claiming complete source coverage."""
    # Create large doc (10,000 characters)
    large_text = "# Large Specifications\n" + ("Section content line.\n" * 400)
    (temp_jester_repo / "docs" / "LARGE_SPEC.md").write_text(large_text, encoding="utf-8")

    runtime = make_mock_runtime("{}")
    service, _, _ = build_service_with_jester(temp_jester_repo, runtime)
    catalog = service.get_project_knowledge_catalog("prj_jester")
    assert catalog is not None

    large_src = ProjectKnowledgeSource(
        source_id="jester_large_spec",
        relative_path="docs/LARGE_SPEC.md",
        domain="architecture",
        authority=SourceAuthority.AUTHORITATIVE,
        truth_scope=TruthScope.SPECIFICATION,
    )

    # Load excerpt with small character budget (1500 chars)
    excerpt = catalog.load_excerpt(large_src, repository_revision="HEAD", max_chars=1500)

    # 1. Must be bounded
    assert excerpt.character_count <= 1600
    assert "... [content truncated due to budget limit]" in excerpt.content

    # 2. Must record truncation status
    assert excerpt.is_truncated is True

    # 3. Formatted prompt block must display PARTIAL coverage, NOT COMPLETE
    formatted = excerpt.format_for_prompt()
    assert "Coverage: PARTIAL (Truncated by budget limit)" in formatted
    assert "Coverage: COMPLETE" not in formatted


def test_scenario_g_invalid_source_paths_traversal_and_unauthorized_rejected(temp_jester_repo: Path):
    """Scenario G: Invalid source paths, traversal attempts, and unauthorized locations are rejected."""
    runtime = make_mock_runtime("{}")
    service, _, _ = build_service_with_jester(temp_jester_repo, runtime)
    catalog = service.get_project_knowledge_catalog("prj_jester")
    assert catalog is not None

    # 1. Path traversal attempt
    with pytest.raises((PolicyViolationError, KnowledgeError)):
        ProjectKnowledgeSource(
            source_id="traversal_test",
            relative_path="../../etc/passwd",
            domain="product",
            authority=SourceAuthority.AUTHORITATIVE,
        )

    # 2. Denied file pattern (.env)
    (temp_jester_repo / ".env").write_text("SECRET_KEY=12345\n", encoding="utf-8")
    denied_src = ProjectKnowledgeSource(
        source_id="denied_env_test",
        relative_path=".env",
        domain="security",
        authority=SourceAuthority.DENIED,
        safe_for_context=False,
    )
    with pytest.raises(KnowledgePolicyViolationError) as exc_info:
        catalog.load_excerpt(denied_src, repository_revision="HEAD")
    assert "DENIED" in str(exc_info.value)


def test_scenario_h_existing_agents_without_documentation_remain_compatible(temp_jester_repo: Path):
    """Scenario H: Existing agents without documentation requirements remain compatible."""
    task = Task(
        id="t_generic",
        project_id="prj_jester",
        title="Standard Task",
        goal="Simple task without knowledge",
        required_roles=["product"],
        constraints=["Fast delivery"],
        expected_output=["Spec"],
    )

    # Build prompt without knowledge
    prompt = build_product_execution_prompt(task)
    assert "PROJECT KNOWLEDGE (UNTRUSTED REPOSITORY DATA)" not in prompt
    assert "Task ID: t_generic" in prompt
    assert "REQUIRED JSON OUTPUT STRUCTURE" in prompt

    ux_prompt = build_ux_execution_prompt(task)
    assert "PROJECT KNOWLEDGE (UNTRUSTED REPOSITORY DATA)" not in ux_prompt
    assert "Task ID: t_generic" in ux_prompt


def test_scenario_i_structured_json_parsing_continues_to_work():
    """Scenario I: Structured JSON parsing continues to work seamlessly."""
    raw_prod_output = (
        "Here is the product specification:\n```json\n{\n"
        '  "schema_version": "1.0",\n'
        '  "status": "completed",\n'
        '  "summary": "Registration redesign completed.",\n'
        '  "deliverables": [{"name": "Deliverable 1", "content": "Content 1"}],\n'
        '  "risks": ["Risk 1"],\n'
        '  "open_questions": []\n'
        "}\n```"
    )
    parsed_prod = parse_and_validate_product_result(raw_prod_output)
    assert parsed_prod.status == "completed"
    assert len(parsed_prod.deliverables) == 1
    assert parsed_prod.deliverables[0].name == "Deliverable 1"

    raw_ux_output = (
        "```json\n{\n"
        '  "schema_version": "1.0",\n'
        '  "status": "completed",\n'
        '  "summary": "UX screens mapped.",\n'
        '  "flows": [{"name": "Flow 1", "description": "Desc 1", "steps": ["Step 1"]}],\n'
        '  "screens": [{"name": "Screen 1", "purpose": "Purpose 1", "states": ["default"]}],\n'
        '  "interaction_rules": ["Rule 1"],\n'
        '  "accessibility_considerations": ["A11y 1"],\n'
        '  "open_questions": []\n'
        "}\n```"
    )
    parsed_ux = parse_and_validate_ux_result(raw_ux_output)
    assert parsed_ux.status == "completed"
    assert len(parsed_ux.flows) == 1
    assert parsed_ux.flows[0].name == "Flow 1"


def test_scenario_j_zero_research_llm_invocation_for_doc_delivery(temp_jester_repo: Path):
    """Scenario J: The system does not require an additional Research LLM invocation simply to transmit documentation."""
    product_json = json.dumps({
        "schema_version": "1.0",
        "status": "completed",
        "summary": "Direct product execution.",
        "deliverables": [{"name": "PRD", "content": "Direct PRD"}],
        "risks": [],
        "open_questions": [],
    })
    runtime = make_mock_runtime(product_json)
    service, project, _ = build_service_with_jester(temp_jester_repo, runtime)

    task = service.create_task(
        project_id="prj_jester",
        title="[PRODUCT] Direct Task",
        goal="Produce PRD",
        required_roles=["product"],
    )

    # Execute Product task
    service.execute_product_task(task_id=task.id, project_id="prj_jester")

    # Assert runtime was executed exactly ONCE (for the product agent itself, NEVER for a research agent)
    assert runtime.execute.call_count == 1
    executed_agent = runtime.execute.call_args[1]["agent"]
    assert executed_agent == "product"

    # Verify no tasks assigned to 'research' were created or executed
    for t in service.company.projects["prj_jester"].tasks.values():
        assert "research" not in t.required_roles
