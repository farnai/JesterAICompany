"""Durable Artifact Materialization & Lineage (STEP 9).

Converts validated specialist outputs (ProductTaskResult, ResearchTaskResult)
into deterministic, durable Markdown files and registers canonical Artifact records
with SHA-256 integrity checksums and traceable lineage.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
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


def format_qa_report(task: Task, typed_result: Any) -> str:
    """Render a validated QAInspectionResult into a clean, human-readable Markdown report (STEP 14A)."""
    coverage_rows = []
    for rc in getattr(typed_result, "requirements_coverage", []):
        coverage_rows.append(
            f"| `{rc.requirement_id}` | **{rc.status}** | {rc.evidence or 'N/A'} | {rc.notes or ''} |"
        )
    coverage_table = (
        "| Requirement ID | Coverage Status | Evidence | Notes |\n"
        "| :--- | :--- | :--- | :--- |\n"
        + "\n".join(coverage_rows)
        if coverage_rows
        else "_No individual requirements mapped._"
    )

    findings_sections = []
    for f in getattr(typed_result, "findings", []):
        aff_str = ", ".join(f.affected_files) if f.affected_files else "None"
        findings_sections.append(
            f"### {f.id} [{f.severity}] — {f.category}\n"
            f"- **Description:** {f.description}\n"
            f"- **Requirement Reference:** {f.requirement_reference or 'N/A'}\n"
            f"- **Affected Files:** {aff_str}\n"
            f"- **Evidence:** {f.evidence or 'N/A'}\n"
            f"- **Recommended Action:** {f.recommended_action or 'N/A'}\n"
        )
    findings_content = "\n".join(findings_sections) if findings_sections else "_No defects or findings reported._"

    test_cases_sections = []
    for tc in getattr(typed_result, "test_cases", []):
        test_cases_sections.append(
            f"### {tc.id}: {tc.objective}\n"
            f"- **Type:** {tc.type} | **Priority:** {tc.priority}\n"
            f"- **Target:** `{tc.target}`\n"
            f"- **Preconditions:** {tc.preconditions or 'None'}\n"
            f"- **Expected Result:** {tc.expected_result}\n"
        )
    test_cases_content = "\n".join(test_cases_sections) if test_cases_sections else "_No test cases defined._"

    rec_actions = []
    for ra in getattr(typed_result, "recommended_verification_actions", []):
        rec_actions.append(f"- **{ra.action_type}** `{ra.target}`: {ra.purpose}")
    rec_actions_content = "\n".join(rec_actions) if rec_actions else "_None_"

    risks = getattr(typed_result, "risks", [])
    risks_content = "\n".join(f"- {r}" for r in risks) if risks else "_None identified._"

    reg = getattr(typed_result, "regression_areas", [])
    reg_content = "\n".join(f"- {r}" for r in reg) if reg else "_None identified._"

    unres = getattr(typed_result, "unresolved_questions", [])
    unres_content = "\n".join(f"- {q}" for q in unres) if unres else "_None._"

    return (
        f"# QA Inspection Report: {task.title}\n\n"
        f"- **Task ID:** `{task.id}`\n"
        f"- **Status:** **{typed_result.status}**\n"
        f"- **Schema Version:** `{typed_result.schema_version}`\n\n"
        f"## Executive Summary\n\n{typed_result.summary}\n\n"
        f"## Requirements Coverage\n\n{coverage_table}\n\n"
        f"## Structured Findings\n\n{findings_content}\n\n"
        f"## QA Test Case Specifications\n\n{test_cases_content}\n\n"
        f"## Recommended Verification Actions\n\n{rec_actions_content}\n\n"
        f"## Risks & Regression Areas\n\n"
        f"### Risks\n{risks_content}\n\n"
        f"### Regression Areas\n{reg_content}\n\n"
        f"## Unresolved Questions\n\n{unres_content}\n"
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
    elif agent_name == "qa":
        filename = "qa_report.md"
        artifact_type = ArtifactType.QA_REPORT.value
        content = format_qa_report(task, typed_result)
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


def materialize_code_patch_artifact(
    base_output_dir: Path,
    task: Task,
    run: TaskRun,
    patch_text: str,
    grant: Any,
    changed_files: List[str],
    verifications: Optional[List[Any]] = None,
    filename: str = "developer_changes.patch",
) -> Artifact:
    """Materialize a durable, cryptographically verified CODE_PATCH artifact with full lineage (STEP 13B-3).

    Enforces:
    1. Rejects binary patches or null bytes.
    2. Atomic write of patch text to run artifacts directory.
    3. Exact SHA-256 calculation and post-write verification.
    4. Complete provenance lineage attached in Artifact metadata:
       - founder_approval_id
       - execution_grant_id
       - plan_artifact_id
       - plan_sha256
       - base_commit_hash
       - changed_files
       - verification_actions
       - verification_outcomes
       - created_at
    5. Registration on TaskRun as durable ArtifactType.CODE_PATCH.
    """
    if "\x00" in patch_text or "Binary files" in patch_text:
        raise MaterializationError("Binary changes are not supported in CODE_PATCH V1.")

    if not patch_text or not patch_text.strip():
        raise MaterializationError("Cannot materialize empty CODE_PATCH artifact.")

    target_dir = get_safe_run_artifacts_dir(base_output_dir, task.id, run.id)
    target_file = target_dir / filename

    # Compute expected SHA-256
    sha256_hash = compute_sha256(patch_text)

    # Perform atomic write to disk
    atomic_write_text(target_file, patch_text)

    # Read back and verify exact hash match
    readback_bytes = target_file.read_bytes()
    recomputed_sha = hashlib.sha256(readback_bytes).hexdigest()
    if recomputed_sha != sha256_hash:
        raise MaterializationError(
            f"Artifact SHA-256 verification failed: computed '{sha256_hash}' != readback '{recomputed_sha}'."
        )

    # Calculate relative storage path from base_output_dir
    try:
        rel_path = str(target_file.relative_to(base_output_dir.resolve()))
    except ValueError:
        rel_path = str(target_file)

    veri_actions = []
    if hasattr(grant, "verification_actions") and grant.verification_actions:
        for va in grant.verification_actions:
            veri_actions.append(va.to_dict() if hasattr(va, "to_dict") else dict(va))

    veri_outcomes = []
    if verifications:
        for v in verifications:
            if hasattr(v, "to_dict"):
                veri_outcomes.append(v.to_dict())
            elif isinstance(v, dict):
                veri_outcomes.append(v)

    metadata: Dict[str, Any] = {
        "founder_approval_id": getattr(grant, "founder_approval_id", ""),
        "execution_grant_id": getattr(grant, "grant_id", ""),
        "plan_artifact_id": getattr(grant, "plan_artifact_id", ""),
        "plan_sha256": getattr(grant, "plan_sha256", ""),
        "base_commit_hash": getattr(grant, "base_commit_hash", ""),
        "changed_files": list(changed_files),
        "verification_actions": veri_actions,
        "verification_outcomes": veri_outcomes,
        "task_id": task.id,
        "run_id": run.id,
        "producer_role": "developer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Also persist companion metadata JSON file for convenience and auditability
    meta_file = target_dir / (filename + ".meta.json")
    atomic_write_text(meta_file, json.dumps(metadata, indent=2))

    artifact = run.add_artifact(
        name=filename,
        artifact_type=ArtifactType.CODE_PATCH.value,
        path=rel_path,
        durable=True,
        sha256=sha256_hash,
        producer_role="developer",
        metadata=metadata,
    )

    return artifact


def materialize_qa_report_artifact(
    base_output_dir: Path,
    task: Task,
    run: TaskRun,
    typed_result: Any,
    lineage_metadata: Dict[str, Any],
    filename: str = "qa_report.md",
) -> Artifact:
    """Materialize a durable, cryptographically verified QA_REPORT artifact with complete upstream lineage (STEP 14A).

    Enforces:
    1. Renders typed result via format_qa_report.
    2. Atomic write of markdown report to run artifacts directory.
    3. Exact SHA-256 calculation and post-write verification.
    4. Attaches complete provenance lineage:
       - product_artifact_id, product_sha256
       - ux_artifact_id, ux_sha256 (optional)
       - developer_plan_artifact_id, developer_plan_sha256
       - execution_grant_id
       - code_patch_artifact_id, code_patch_sha256
       - base_commit_hash
       - verification_evidence
       - qa_task_id, qa_run_id
       - producer_role="qa"
    5. Also persists companion .meta.json file.
    6. Registration on TaskRun as durable ArtifactType.QA_REPORT.
    """
    target_dir = get_safe_run_artifacts_dir(base_output_dir, task.id, run.id)
    target_file = target_dir / filename

    content = format_qa_report(task, typed_result)
    sha256_hash = compute_sha256(content)

    # Perform atomic write to disk
    atomic_write_text(target_file, content)

    # Read back and verify exact hash match
    readback_bytes = target_file.read_bytes()
    recomputed_sha = hashlib.sha256(readback_bytes).hexdigest()
    if recomputed_sha != sha256_hash:
        raise MaterializationError(
            f"Artifact SHA-256 verification failed: computed '{sha256_hash}' != readback '{recomputed_sha}'."
        )

    try:
        rel_path = str(target_file.relative_to(base_output_dir.resolve()))
    except ValueError:
        rel_path = str(target_file)

    meta: Dict[str, Any] = dict(lineage_metadata)
    meta.update({
        "qa_task_id": task.id,
        "qa_run_id": run.id,
        "producer_role": "qa",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": getattr(typed_result, "status", ""),
        "schema_version": getattr(typed_result, "schema_version", "1.0"),
    })

    # Persist companion .meta.json file
    meta_file = target_dir / (filename + ".meta.json")
    atomic_write_text(meta_file, json.dumps(meta, indent=2))

    artifact = run.add_artifact(
        name=filename,
        artifact_type=ArtifactType.QA_REPORT.value,
        path=rel_path,
        durable=True,
        sha256=sha256_hash,
        producer_role="qa",
        metadata=meta,
    )

    return artifact


def format_qa_execution_report(
    task: Task,
    typed_verdict: Any,
    execution_evidence: List[Dict[str, Any]],
) -> str:
    """Render a validated QAExecutionVerdictResult into a clean, human-readable Markdown report (STEP 14B)."""
    req_rows = []
    for re_item in getattr(typed_verdict, "requirements_evaluations", []):
        req_id = getattr(re_item, "requirement_id", "") if hasattr(re_item, "requirement_id") else re_item.get("requirement_id", "")
        status = getattr(re_item, "status", "") if hasattr(re_item, "status") else re_item.get("status", "")
        ev = getattr(re_item, "evidence", "") if hasattr(re_item, "evidence") else re_item.get("evidence", "")
        notes = getattr(re_item, "notes", "") if hasattr(re_item, "notes") else re_item.get("notes", "")
        req_rows.append(f"| `{req_id}` | **{status}** | {ev or 'N/A'} | {notes or ''} |")

    req_table = (
        "| Requirement ID | Execution Evaluation | Evidence | Notes |\n"
        "| :--- | :--- | :--- | :--- |\n"
        + "\n".join(req_rows)
        if req_rows
        else "_No individual requirements evaluated._"
    )

    exec_sections = []
    for idx, ee in enumerate(execution_evidence, start=1):
        act = ee.get("action", {})
        act_str = f"{act.get('action_type', 'pytest')} `{act.get('target', '')}`"
        st = ee.get("status", "UNKNOWN")
        ec = ee.get("exit_code", -1)
        dur = ee.get("duration_ms", 0)
        stdout_snip = (ee.get("stdout") or "").strip()
        stderr_snip = (ee.get("stderr") or "").strip()
        logs = []
        if stdout_snip:
            logs.append(f"```text\n{stdout_snip[:1000]}\n```")
        if stderr_snip:
            logs.append(f"```text\n{stderr_snip[:1000]}\n```")
        log_content = "\n".join(logs) if logs else "_No logs_"

        exec_sections.append(
            f"### Action {idx}: {act_str}\n"
            f"- **Status:** `{st}` (exit code {ec})\n"
            f"- **Duration:** {dur}ms\n"
            f"**Output:**\n{log_content}"
        )
    exec_content = "\n\n".join(exec_sections) if exec_sections else "_No verification actions executed._"

    blocking = getattr(typed_verdict, "blocking_issues", [])
    blocking_content = "\n".join(f"- {b}" for b in blocking) if blocking else "_None (clean run)_"

    override_note = ""
    if getattr(typed_verdict, "deterministic_override_applied", False):
        override_note = f"\n> [!WARNING]\n> **Deterministic Safety Override Applied:** {getattr(typed_verdict, 'override_reason', '')}\n"

    verdict_val = getattr(typed_verdict, "verdict", "UNKNOWN")
    rec_val = getattr(typed_verdict, "release_recommendation", "N/A")
    summary_val = getattr(typed_verdict, "summary", "")

    return (
        f"# QA Execution Report: {task.title}\n\n"
        f"- **Task ID:** `{task.id}`\n"
        f"- **Final Verdict:** **{verdict_val}**\n"
        f"- **Release Recommendation:** `{rec_val}`\n"
        f"- **Schema Version:** `{getattr(typed_verdict, 'schema_version', '1.0')}`\n"
        f"{override_note}\n"
        f"## Executive Summary\n\n{summary_val}\n\n"
        f"## Requirements Execution Evaluation\n\n{req_table}\n\n"
        f"## Executed Test Verification Evidence\n\n{exec_content}\n\n"
        f"## Blocking Issues & Defects\n\n{blocking_content}\n"
    )


def materialize_qa_execution_report_artifact(
    base_output_dir: Path,
    task: Task,
    run: TaskRun,
    typed_verdict: Any,
    lineage_metadata: Dict[str, Any],
    execution_evidence: Optional[List[Dict[str, Any]]] = None,
    filename: str = "qa_execution_report.md",
) -> Artifact:
    """Materialize a durable, cryptographically verified QA_EXECUTION_REPORT artifact with complete provenance (STEP 14B).

    Enforces:
    1. Formats report via format_qa_execution_report.
    2. Atomically writes report to safe run artifacts directory.
    3. Recomputes SHA-256 on readback and validates integrity.
    4. Attaches complete provenance lineage:
       - product, ux, developer_plan, execution_grant, code_patch, qa_report
       - base_commit_hash, worktree_diff_sha256, test execution outcomes
       - final verdict and release recommendation
    5. Persists companion .meta.json file.
    6. Registers durable ArtifactType.QA_EXECUTION_REPORT on TaskRun.
    """
    target_dir = get_safe_run_artifacts_dir(base_output_dir, task.id, run.id)
    target_file = target_dir / filename

    content = format_qa_execution_report(
        task=task,
        typed_verdict=typed_verdict,
        execution_evidence=execution_evidence or [],
    )
    sha256_hash = compute_sha256(content)

    # Perform atomic write to disk
    atomic_write_text(target_file, content)

    # Read back and verify exact hash match
    readback_bytes = target_file.read_bytes()
    recomputed_sha = hashlib.sha256(readback_bytes).hexdigest()
    if recomputed_sha != sha256_hash:
        raise MaterializationError(
            f"Artifact SHA-256 verification failed: computed '{sha256_hash}' != readback '{recomputed_sha}'."
        )

    try:
        rel_path = str(target_file.relative_to(base_output_dir.resolve()))
    except ValueError:
        rel_path = str(target_file)

    meta: Dict[str, Any] = dict(lineage_metadata)
    meta.update({
        "qa_task_id": task.id,
        "qa_run_id": run.id,
        "producer_role": "qa",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verdict": getattr(typed_verdict, "verdict", ""),
        "release_recommendation": getattr(typed_verdict, "release_recommendation", ""),
        "schema_version": getattr(typed_verdict, "schema_version", "1.0"),
        "deterministic_override_applied": getattr(typed_verdict, "deterministic_override_applied", False),
        "override_reason": getattr(typed_verdict, "override_reason", None),
        "execution_outcomes": execution_evidence or [],
    })

    # Persist companion .meta.json file
    meta_file = target_dir / (filename + ".meta.json")
    atomic_write_text(meta_file, json.dumps(meta, indent=2))

    artifact = run.add_artifact(
        name=filename,
        artifact_type=ArtifactType.QA_EXECUTION_REPORT.value,
        path=rel_path,
        durable=True,
        sha256=sha256_hash,
        producer_role="qa",
        metadata=meta,
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

