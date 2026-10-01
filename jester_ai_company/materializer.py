"""Durable Artifact Materialization & Lineage (STEP 9).

Converts validated specialist outputs (ProductTaskResult, ResearchTaskResult)
into deterministic, durable Markdown files and registers canonical Artifact records
with SHA-256 integrity checksums and traceable lineage.
"""

import hashlib
from pathlib import Path
from typing import Any, List, Optional
import uuid

from .core import Artifact, ArtifactType, Task, TaskRun
from .product_result import ProductTaskResult
from .research_result import ResearchTaskResult


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
        temp_path.write_text(content, encoding="utf-8")
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
