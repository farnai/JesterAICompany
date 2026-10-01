"""Durable Artifact Materialization & Lineage (STEP 9).

Converts validated specialist outputs (ProductTaskResult, ResearchTaskResult)
into deterministic, durable Markdown files and registers canonical Artifact records
with SHA-256 integrity checksums and traceable lineage.
"""

import hashlib
from pathlib import Path
from typing import Any, List, Optional
import uuid

from .core import (
    Artifact,
    ArtifactInputRef,
    ArtifactType,
    ArtifactVerificationError,
    Task,
    TaskRun,
)
from .product_result import ProductTaskResult
from .research_result import ResearchTaskResult
from .ux_result import UXTaskResult
from .marketing_result import MarketingTaskResult
from .developer_result import DeveloperTaskResult


class MaterializationError(Exception):
    """Raised when artifact materialization fails."""
    pass


def compute_sha256(content: str) -> str:
    """Compute the SHA-256 hex digest over exact UTF-8 bytes."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def atomic_write_text(target_path: Path, content: str) -> None:
    """Atomically write UTF-8 text to disk using a temporary file in the same directory."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".tmp_{target_path.name}_{uuid.uuid4().hex[:8]}")
    try:
        temp_path.write_bytes(content.encode("utf-8"))
        temp_path.replace(target_path)
    except Exception as exc:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise MaterializationError(f"Failed to atomically write artifact '{target_path.name}': {exc}") from exc


def get_safe_run_artifacts_dir(base_output_dir: Path, task_id: str, run_id: str) -> Path:
    """Resolve a safe, isolated run artifacts directory, preventing traversal attacks."""
    if not task_id or ".." in task_id or "/" in task_id or "\\" in task_id:
        raise MaterializationError(f"Invalid task_id '{task_id}' for artifact storage.")
    if not run_id or ".." in run_id or "/" in run_id or "\\" in run_id:
        raise MaterializationError(f"Invalid run_id '{run_id}' for artifact storage.")

    base_resolved = base_output_dir.resolve()
    target_dir = (base_resolved / task_id / run_id / "artifacts").resolve()

    if not target_dir.is_relative_to(base_resolved):
        raise MaterializationError(
            f"Path traversal detected: target '{target_dir}' is outside output directory '{base_resolved}'."
        )

    return target_dir


def format_product_report(task: Task, result: ProductTaskResult) -> str:
    """Format validated ProductTaskResult and Task metadata into a deterministic Markdown report."""
    expected_output_items = (
        "\n".join(f"- {eo}" for eo in task.expected_output)
        if task.expected_output
        else "- None specified"
    )

    deliverables_sections: List[str] = []
    for d in result.deliverables:
        deliverables_sections.append(f"### {d.name}\n\n{d.content}")
    deliverables_content = (
        "\n\n".join(deliverables_sections)
        if deliverables_sections
        else "_No deliverables provided._"
    )

    risks_content = (
        "\n".join(f"- {r}" for r in result.risks)
        if result.risks
        else "- None identified"
    )

    open_questions_content = (
        "\n".join(f"- {oq}" for oq in result.open_questions)
        if result.open_questions
        else "- None identified"
    )

    return (
        f"# Product Report: {task.title}\n\n"
        f"- **Task ID:** `{task.id}`\n"
        f"- **Status:** `{result.status.upper()}`\n"
        f"- **Schema Version:** `{result.schema_version}`\n\n"
        f"## Executive Summary\n\n{result.summary}\n\n"
        f"## Goal\n\n{task.goal}\n\n"
        f"## Expected Output\n\n{expected_output_items}\n\n"
        f"## Deliverables\n\n{deliverables_content}\n\n"
        f"## Risks\n\n{risks_content}\n\n"
        f"## Open Questions\n\n{open_questions_content}\n"
    )


def format_research_report(task: Task, result: ResearchTaskResult) -> str:
    """Format validated ResearchTaskResult schema 1.1 into a deterministic Markdown report with visible provenance."""
    findings_sections: List[str] = []
    for idx, f in enumerate(result.findings, start=1):
        sources_str = ", ".join(f"`{sid}`" for sid in f.source_ids) if f.source_ids else "_None (Inference / Unverified)_"
        findings_sections.append(
            f"### Finding {idx}: {f.claim}\n\n"
            f"- **Evidence Status:** `{f.evidence_status}`\n"
            f"- **Certainty:** `{f.certainty}`\n"
            f"- **Sources:** {sources_str}\n"
            f"- **Supporting Evidence:** {f.evidence}"
        )
    findings_content = (
        "\n\n".join(findings_sections)
        if findings_sections
        else "_No findings recorded._"
    )

    sources_sections: List[str] = []
    for s in result.sources:
        accessed_str = s.accessed_at if s.accessed_at else "Offline / Not Recorded"
        sources_sections.append(
            f"- **`[{s.source_id}]` {s.title}**\n"
            f"  - **Reference:** `{s.reference}`\n"
            f"  - **Source Type:** `{s.source_type}`\n"
            f"  - **Accessed:** `{accessed_str}`"
        )
    sources_content = (
        "\n".join(sources_sections)
        if sources_sections
        else "_No sources cited._"
    )

    uncertainties_content = (
        "\n".join(f"- {u}" for u in result.uncertainties)
        if result.uncertainties
        else "- None identified"
    )

    open_questions_content = (
        "\n".join(f"- {oq}" for oq in result.open_questions)
        if result.open_questions
        else "- None identified"
    )

    return (
        f"# Research Report: {task.title}\n\n"
        f"- **Task ID:** `{task.id}`\n"
        f"- **Status:** `{result.status.upper()}`\n"
        f"- **Schema Version:** `{result.schema_version}`\n\n"
        f"## Executive Summary\n\n{result.summary}\n\n"
        f"## Goal\n\n{task.goal}\n\n"
        f"## Findings\n\n{findings_content}\n\n"
        f"## Sources & Evidence Provenance\n\n{sources_content}\n\n"
        f"## Uncertainties\n\n{uncertainties_content}\n\n"
        f"## Open Questions\n\n{open_questions_content}\n"
    )


def format_ux_report(task: Task, result: UXTaskResult) -> str:
    """Format validated UXTaskResult into a deterministic Markdown report."""
    flows_sections: List[str] = []
    for idx, flow in enumerate(result.flows, start=1):
        steps_str = "\n".join(f"{s_idx}. {step}" for s_idx, step in enumerate(flow.steps, start=1))
        flows_sections.append(
            f"### Flow {idx}: {flow.name}\n\n"
            f"{flow.description}\n\n"
            f"**Steps:**\n{steps_str if steps_str else '_No steps specified._'}"
        )
    flows_content = "\n\n".join(flows_sections) if flows_sections else "_No user flows defined._"

    screens_sections: List[str] = []
    for idx, screen in enumerate(result.screens, start=1):
        states_str = ", ".join(f"`{st}`" for st in screen.states)
        screens_sections.append(
            f"### Screen {idx}: {screen.name}\n\n"
            f"- **Purpose:** {screen.purpose}\n"
            f"- **States:** {states_str if states_str else '_Default only_'}"
        )
    screens_content = "\n\n".join(screens_sections) if screens_sections else "_No screens defined._"

    interaction_rules_content = (
        "\n".join(f"- {ir}" for ir in result.interaction_rules)
        if result.interaction_rules
        else "- None specified"
    )

    accessibility_content = (
        "\n".join(f"- {ac}" for ac in result.accessibility_considerations)
        if result.accessibility_considerations
        else "- Standard guidelines apply"
    )

    open_questions_content = (
        "\n".join(f"- {oq}" for oq in result.open_questions)
        if result.open_questions
        else "- None identified"
    )

    return (
        f"# UX Report: {task.title}\n\n"
        f"- **Task ID:** `{task.id}`\n"
        f"- **Status:** `{result.status.upper()}`\n"
        f"- **Schema Version:** `{result.schema_version}`\n\n"
        f"## Executive Summary\n\n{result.summary}\n\n"
        f"## Goal\n\n{task.goal}\n\n"
        f"## User Flows\n\n{flows_content}\n\n"
        f"## Screen & State Architecture\n\n{screens_content}\n\n"
        f"## Interaction Rules\n\n{interaction_rules_content}\n\n"
        f"## Accessibility Considerations\n\n{accessibility_content}\n\n"
        f"## Open Questions\n\n{open_questions_content}\n"
    )


def format_marketing_report(task: Task, result: MarketingTaskResult) -> str:
    """Format validated MarketingTaskResult into a deterministic Markdown report."""
    audiences_sections: List[str] = []
    for idx, aud in enumerate(result.target_audiences, start=1):
        pain_points_str = "\n".join(f"- {pt}" for pt in aud.pain_points) if aud.pain_points else "- None identified"
        audiences_sections.append(
            f"### Audience {idx}: {aud.name}\n\n"
            f"{aud.description}\n\n"
            f"**Pain Points & Needs:**\n{pain_points_str}"
        )
    audiences_content = "\n\n".join(audiences_sections) if audiences_sections else "_No target audiences defined._"

    messages_sections: List[str] = []
    for km in result.key_messages:
        messages_sections.append(f"- **{km.audience}:** {km.core_message}")
    messages_content = "\n".join(messages_sections) if messages_sections else "_No key messages defined._"

    tactics_sections: List[str] = []
    for idx, ct in enumerate(result.channels_or_tactics, start=1):
        tactics_sections.append(
            f"### Channel {idx}: {ct.channel}\n\n"
            f"**Tactic:** {ct.tactic}"
        )
    tactics_content = "\n\n".join(tactics_sections) if tactics_sections else "_No channels/tactics defined._"

    assumptions_content = (
        "\n".join(f"- {a}" for a in result.assumptions)
        if result.assumptions
        else "- None identified"
    )

    open_questions_content = (
        "\n".join(f"- {oq}" for oq in result.open_questions)
        if result.open_questions
        else "- None identified"
    )

    return (
        f"# Marketing Report: {task.title}\n\n"
        f"- **Task ID:** `{task.id}`\n"
        f"- **Status:** `{result.status.upper()}`\n"
        f"- **Schema Version:** `{result.schema_version}`\n\n"
        f"## Executive Summary\n\n{result.summary}\n\n"
        f"## Goal\n\n{task.goal}\n\n"
        f"## Core Positioning\n\n{result.positioning}\n\n"
        f"## Target Audiences\n\n{audiences_content}\n\n"
        f"## Key Messages\n\n{messages_content}\n\n"
        f"## Channels & Tactics\n\n{tactics_content}\n\n"
        f"## Assumptions & Uncertainties\n\n{assumptions_content}\n\n"
        f"## Open Questions\n\n{open_questions_content}\n"
    )


def format_developer_plan_report(task: Task, result: DeveloperTaskResult) -> str:
    """Format validated DeveloperTaskResult into a deterministic Markdown plan report."""
    plan_sections: List[str] = []
    for idx, step in enumerate(result.implementation_plan, start=1):
        plan_sections.append(f"{idx}. {step}")
    plan_content = "\n".join(plan_sections) if plan_sections else "_No implementation steps specified._"

    mod_sections: List[str] = []
    for f in result.files_to_modify:
        desc_str = f": {f.description}" if f.description else ""
        mod_sections.append(f"- `{f.path}`{desc_str}")
    mod_content = "\n".join(mod_sections) if mod_sections else "- None proposed"

    create_sections: List[str] = []
    for f in result.files_to_create:
        desc_str = f": {f.description}" if f.description else ""
        create_sections.append(f"- `{f.path}`{desc_str}")
    create_content = "\n".join(create_sections) if create_sections else "- None proposed"

    deps_content = (
        "\n".join(f"- `{dep}`" for dep in result.dependencies)
        if result.dependencies
        else "- None required"
    )

    cmd_sections: List[str] = []
    for c in result.commands_to_run:
        purpose_str = f" — _{c.purpose}_" if c.purpose else ""
        cmd_sections.append(f"- `{c.command}`{purpose_str}")
    cmd_content = "\n".join(cmd_sections) if cmd_sections else "- None proposed"

    ver_content = (
        "\n".join(f"- {vp}" for vp in result.verification_plan)
        if result.verification_plan
        else "- Standard test verification"
    )

    risks_content = (
        "\n".join(f"- {r}" for r in result.risks)
        if result.risks
        else "- None identified"
    )

    assumptions_content = (
        "\n".join(f"- {a}" for a in result.assumptions)
        if result.assumptions
        else "- None identified"
    )

    open_questions_content = (
        "\n".join(f"- {oq}" for oq in result.open_questions)
        if result.open_questions
        else "- None identified"
    )

    return (
        f"# Developer Plan Report: {task.title}\n\n"
        f"- **Task ID:** `{task.id}`\n"
        f"- **Status:** `{result.status.upper()}`\n"
        f"- **Schema Version:** `{result.schema_version}`\n\n"
        f"## Executive Technical Summary\n\n{result.summary}\n\n"
        f"## Goal\n\n{task.goal}\n\n"
        f"## Implementation Plan\n\n{plan_content}\n\n"
        f"## Proposed File Modifications (Planning Only)\n\n{mod_content}\n\n"
        f"## Proposed Files to Create (Planning Only)\n\n{create_content}\n\n"
        f"## Dependencies\n\n{deps_content}\n\n"
        f"## Proposed Commands to Run (Planning Only - Not Executed)\n\n{cmd_content}\n\n"
        f"## Verification Plan\n\n{ver_content}\n\n"
        f"## Technical Risks\n\n{risks_content}\n\n"
        f"## Technical Assumptions\n\n{assumptions_content}\n\n"
        f"## Open Questions & Conflicts\n\n{open_questions_content}\n"
    )


def materialize_specialist_artifact(
    base_output_dir: Path,
    task: Task,
    run: TaskRun,
    agent_name: str,
    typed_result: Any,
) -> Artifact:
    """Format and atomically write a durable specialist artifact, registering it with TaskRun."""
    target_dir = get_safe_run_artifacts_dir(base_output_dir, task.id, run.id)

    if agent_name == "product":
        filename = "product_report.md"
        artifact_type = ArtifactType.SPECIFICATION.value
        content = format_product_report(task, typed_result)
    elif agent_name == "research":
        filename = "research_report.md"
        artifact_type = ArtifactType.RESEARCH_REPORT.value
        content = format_research_report(task, typed_result)
    elif agent_name == "ux":
        filename = "ux_report.md"
        artifact_type = ArtifactType.UX_SPECIFICATION.value
        content = format_ux_report(task, typed_result)
    elif agent_name == "marketing":
        filename = "marketing_report.md"
        artifact_type = ArtifactType.MARKETING_REPORT.value
        content = format_marketing_report(task, typed_result)
    elif agent_name == "developer":
        filename = "developer_plan_report.md"
        artifact_type = ArtifactType.DEVELOPER_PLAN_REPORT.value
        content = format_developer_plan_report(task, typed_result)
    else:
        raise MaterializationError(f"Unsupported agent for artifact materialization: '{agent_name}'.")

    target_file = target_dir / filename
    sha256_hash = compute_sha256(content)

    # Perform atomic write to disk
    atomic_write_text(target_file, content)

    # Calculate relative storage path from base_output_dir
    try:
        rel_path = str(target_file.relative_to(base_output_dir.resolve()))
    except ValueError:
        rel_path = str(target_file)

    # Attach canonical Artifact record to producing TaskRun
    artifact = run.add_artifact(
        name=filename,
        artifact_type=artifact_type,
        path=rel_path,
        durable=True,
        sha256=sha256_hash,
        producer_role=agent_name,
    )

    return artifact


MAX_INPUT_ARTIFACT_SIZE_BYTES: int = 100_000
MAX_COMBINED_INPUT_ARTIFACT_SIZE_BYTES: int = 150_000


def load_and_verify_input_artifact(
    base_output_dir: Path,
    artifact: Artifact,
    expected_ref: ArtifactInputRef,
    max_bytes: int = MAX_INPUT_ARTIFACT_SIZE_BYTES,
) -> str:
    """Safely resolve, verify, and load an input artifact from disk (STEP 10).

    Enforces:
    1. Safe canonical path resolution under base_output_dir (no directory traversal).
    2. File existence.
    3. Maximum input size (non-truncating fail-safe).
    4. Exact UTF-8 decoding.
    5. Exact SHA-256 match against Artifact.sha256.
    6. Exact SHA-256 match against ArtifactInputRef.sha256.
    """
    if not artifact.path or ".." in artifact.path:
        raise ArtifactVerificationError(
            f"Invalid artifact path '{artifact.path}': Directory traversal not allowed."
        )

    base_resolved = base_output_dir.resolve()
    target_path = (base_resolved / artifact.path).resolve()

    if not target_path.is_relative_to(base_resolved):
        raise ArtifactVerificationError(
            f"Path traversal detected: Artifact path '{target_path}' escapes root '{base_resolved}'."
        )

    if not target_path.is_file():
        raise ArtifactVerificationError(
            f"Artifact file not found at expected path: '{target_path}'."
        )

    raw_bytes = target_path.read_bytes()
    if len(raw_bytes) > max_bytes:
        raise ArtifactVerificationError(
            f"Artifact '{artifact.id}' size ({len(raw_bytes)} bytes) exceeds maximum allowed size ({max_bytes} bytes)."
        )

    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactVerificationError(
            f"Artifact '{artifact.id}' at '{target_path}' is not valid UTF-8: {exc}"
        ) from exc

    computed_sha = hashlib.sha256(raw_bytes).hexdigest()
    if computed_sha != artifact.sha256:
        raise ArtifactVerificationError(
            f"Artifact '{artifact.id}' SHA-256 integrity mismatch: computed '{computed_sha}' != recorded '{artifact.sha256}'."
        )

    if computed_sha != expected_ref.sha256:
        raise ArtifactVerificationError(
            f"ArtifactInputRef '{expected_ref.artifact_id}' SHA-256 mismatch: computed '{computed_sha}' != expected '{expected_ref.sha256}'."
        )

    return content

