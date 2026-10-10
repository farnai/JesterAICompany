"""Deterministic tests for STEP 23B.7-A: Agent Instruction / Runtime Contract Alignment.

Validates the real instruction files for:
- CEO (.agents/agents/ceo/agent.md)
- QA (.agents/agents/qa/agent.md)
- Developer (.agents/agents/developer/agent.md)

Verifies:
1. Frontmatter metadata validity.
2. Removal of obsolete CEO legacy fan-in constraints and alignment with adaptive DAG logic.
3. Documentation and valid Python parsing of CEO evaluation and team-selection modes.
4. QA dual/triple mode coverage:
   - Mode A: Ordinary QA Advisory / Planning (STEP 23B.1)
   - Mode B: Engineering QA Inspection (STEP 14A)
   - Mode C: Engineering QA Verdict Proposal (STEP 14B)
5. Parsing and validation of representative QA output examples with actual runtime parsers.
6. Developer dual mode coverage:
   - Mode A: Read-Only Developer Planning (STEP 13A)
   - Mode B: Bounded Developer Mutation (STEP 13B-2)
7. Parsing and validation of representative Developer output examples with actual runtime parsers.
8. Preservation of security and human approval boundaries across all three agent instructions.
"""

from pathlib import Path
import re
from typing import Any, Dict, List, Tuple
import pytest
import yaml

from jester_ai_company.ceo_contract import (
    CEODecisionResult,
    TeamSelectionResult,
    parse_and_validate_ceo_decision,
    parse_and_validate_team_selection,
)
from jester_ai_company.developer_mutation import (
    DeveloperMutationResult,
    parse_and_validate_developer_mutation_result,
)
from jester_ai_company.developer_result import (
    DeveloperTaskResult,
    parse_and_validate_developer_result,
)
from jester_ai_company.execution_grant import VerificationAction
from jester_ai_company.verification import (
    VerificationExecutionResult,
    VerificationStatus,
)
from jester_ai_company.qa_execution import (
    QAActionAuthorizationDecision,
    QAExecutionActionAudit,
    QAExecutionVerdictResult,
    QAFinalVerdict,
    parse_and_validate_qa_verdict,
)
from jester_ai_company.qa_result import (
    QAInspectionResult,
    QAInspectionStatus,
    parse_and_validate_qa_planning_result,
    parse_and_validate_qa_result,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / ".agents" / "agents"


def _load_agent_md(role: str) -> Tuple[Dict[str, Any], str]:
    """Load agent.md and return (frontmatter_dict, markdown_body)."""
    file_path = AGENTS_DIR / role / "agent.md"
    assert file_path.exists(), f"Agent instruction file missing at: {file_path}"
    content = file_path.read_text(encoding="utf-8")

    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", content, re.DOTALL)
    assert match is not None, f"YAML frontmatter not found in {file_path}"

    frontmatter = yaml.safe_load(match.group(1))
    body = match.group(2)
    return frontmatter, body


def _extract_all_json_blocks(markdown_text: str) -> List[str]:
    """Extract all json code blocks from markdown."""
    pattern = re.compile(r"```json\r?\n(.*?)\r?\n```", re.DOTALL)
    return pattern.findall(markdown_text)


# ==============================================================================
# 1. Frontmatter Validation
# ==============================================================================

@pytest.mark.parametrize("role,expected_tools", [
    ("ceo", ["invoke_subagent"]),
    ("developer", ["view_file", "write_to_file", "replace_file_content", "run_command", "send_message"]),
    ("qa", ["view_file", "send_message"]),
])
def test_agent_frontmatter(role: str, expected_tools: List[str]):
    frontmatter, _ = _load_agent_md(role)
    assert frontmatter.get("name") == role
    assert bool(frontmatter.get("displayName"))
    assert bool(frontmatter.get("description"))
    assert frontmatter.get("subagent") is True
    assert frontmatter.get("tools") == expected_tools


# ==============================================================================
# 2. CEO Instruction & Contract Validation
# ==============================================================================

def test_ceo_instruction_adaptive_dag_contract():
    _, body = _load_agent_md("ceo")

    # Invariant 1: Obsolete legacy fan-in requirement must be removed
    assert "MUST directly depend on BOTH a product and a ux" not in body, (
        "Obsolete mandatory Developer -> (Product, UX) fan-in constraint still present in CEO instructions"
    )

    # Invariant 2: Adaptive team selection & Direct Developer execution must be documented
    assert "Adaptive Developer Fan-In rule" in body
    assert "Direct Developer selection is authorized" in body
    assert "Minimum sufficient workforce principle" in body

    # Invariant 3: Authority boundaries preserved
    assert "Data only" in body
    assert "do not invoke subagents, write files, run commands, issue grants, apply patches" in body

    # Invariant 4: QA role boundaries documented
    assert "Engineering QA certification is strictly application-owned inside code pipelines" in body
    assert "test_strategy" in body and "test_matrix" in body


def test_ceo_instruction_json_schemas_parse_with_runtime_parsers():
    _, body = _load_agent_md("ceo")
    json_blocks = _extract_all_json_blocks(body)
    assert len(json_blocks) >= 2, f"Expected at least 2 JSON examples in CEO instruction, found {len(json_blocks)}"

    # Block 1: Autonomous Objective Evaluation
    eval_json = json_blocks[0]
    decision_result = parse_and_validate_ceo_decision(eval_json)
    assert isinstance(decision_result, CEODecisionResult)
    assert decision_result.decision in {"EXECUTE", "INVESTIGATE", "ASK_FOUNDER"}
    assert decision_result.reasoning_summary

    # Block 2: Adaptive Team Selection
    team_json = json_blocks[1]
    team_result = parse_and_validate_team_selection(team_json)
    assert isinstance(team_result, TeamSelectionResult)
    assert team_result.task_category == "BUG_FIX"
    assert "developer" in team_result.selected_roles
    assert team_result.allow_direct_developer is True


# ==============================================================================
# 3. QA Instruction & Three-Mode Contract Validation
# ==============================================================================

def test_qa_instruction_three_modes_and_boundaries():
    _, body = _load_agent_md("qa")

    # Invariant 1: All 3 execution modes must be documented
    assert "Mode A" in body and "QA Advisory" in body
    assert "Mode B" in body and "QA Inspection Mode" in body
    assert "Mode C" in body and "QA Verdict Proposal Mode" in body

    # Invariant 2: Authority boundaries
    assert "MAY propose PASS" in body
    assert "proposed verdict is NOT the final release authority" in body
    assert "Deterministic Python validation" in body
    assert "QA has zero executable authority" in body

    # Invariant 3: Frontend change relevance check
    assert "Frontend code changes strictly require relevant frontend verification" in body

    # Invariant 4: Allowlisted verification actions
    assert "pytest" in body
    assert "frontend_build" in body


def test_qa_instruction_json_schemas_parse_with_runtime_parsers():
    _, body = _load_agent_md("qa")
    json_blocks = _extract_all_json_blocks(body)
    assert len(json_blocks) >= 2, f"Expected at least 2 JSON examples in QA instruction, found {len(json_blocks)}"

    # Block 1: QA Inspection / Advisory Schema (used by Mode A and Mode B)
    inspection_json = json_blocks[0]
    plan_result = parse_and_validate_qa_planning_result(inspection_json)
    assert isinstance(plan_result, QAInspectionResult)
    assert plan_result.status == QAInspectionStatus.READY_FOR_QA_EXECUTION.value
    assert len(plan_result.requirements_coverage) > 0

    insp_result = parse_and_validate_qa_result(inspection_json)
    assert isinstance(insp_result, QAInspectionResult)
    assert insp_result.status == QAInspectionStatus.READY_FOR_QA_EXECUTION.value

    # Block 2: QA Verdict Proposal Schema (Mode C)
    verdict_json = json_blocks[1]

    # Test with passing subprocess verification evidence
    action_audit = QAExecutionActionAudit(
        action_type="pytest",
        target="tests/test_feature.py",
        purpose="Verify feature behavior",
        decision=QAActionAuthorizationDecision.AUTHORIZED.value,
    )
    verif_result = VerificationExecutionResult(
        action=VerificationAction(
            action_type="pytest",
            target="tests/test_feature.py",
        ),
        status=VerificationStatus.PASS.value,
        exit_code=0,
        stdout="1 passed",
        stderr="",
        duration_ms=500,
    )

    verdict_outcome = parse_and_validate_qa_verdict(
        raw_output=verdict_json,
        action_audits=[action_audit],
        verification_results=[verif_result],
        changed_files=["tests/test_feature.py"],
        code_patch_text="",
    )
    assert isinstance(verdict_outcome, QAExecutionVerdictResult)
    assert verdict_outcome.verdict == QAFinalVerdict.PASS.value
    assert verdict_outcome.deterministic_override_applied is False


def test_qa_deterministic_override_rejection_of_unverified_pass():
    """Verify that Python validation overrides an agent's proposed PASS if tests failed."""
    _, body = _load_agent_md("qa")
    json_blocks = _extract_all_json_blocks(body)
    verdict_json = json_blocks[1]

    action_audit = QAExecutionActionAudit(
        action_type="pytest",
        target="tests/test_feature.py",
        purpose="Verify feature behavior",
        decision=QAActionAuthorizationDecision.AUTHORIZED.value,
    )
    # Verification failed (exit code 1)
    failing_verif_result = VerificationExecutionResult(
        action=VerificationAction(
            action_type="pytest",
            target="tests/test_feature.py",
        ),
        status=VerificationStatus.FAIL.value,
        exit_code=1,
        stdout="1 failed",
        stderr="AssertionError",
        duration_ms=500,
    )

    verdict_outcome = parse_and_validate_qa_verdict(
        raw_output=verdict_json,
        action_audits=[action_audit],
        verification_results=[failing_verif_result],
        changed_files=["tests/test_feature.py"],
        code_patch_text="",
    )
    # Agent proposed PASS, but deterministic runtime MUST override to FAIL
    assert verdict_outcome.verdict == QAFinalVerdict.FAIL.value
    assert verdict_outcome.deterministic_override_applied is True
    assert "failed" in verdict_outcome.override_reason.lower()


# ==============================================================================
# 4. Developer Instruction & Two-Mode Contract Validation
# ==============================================================================

def test_developer_instruction_two_modes_and_boundaries():
    _, body = _load_agent_md("developer")

    # Invariant 1: Two distinct execution modes
    assert "Mode A — Structured Developer Planning Mode (STEP 13A)" in body
    assert "Mode B — Bounded Developer Mutation Mode (STEP 13B-2)" in body

    # Invariant 2: Planning mode is read-only
    assert "READ-ONLY PLANNING" in body
    assert "inspect through permitted read tools only (`view_file`)" in body

    # Invariant 3: Mutation mode safety rules
    assert "isolated, disposable Git worktree under an immutable `ExecutionGrant`" in body
    assert "YOU MUST ONLY MODIFY files explicitly listed under `APPROVED FILES TO MODIFY`" in body
    assert "YOU MUST ONLY CREATE files explicitly listed under `APPROVED FILES TO CREATE`" in body
    assert "DO NOT call `run_command` or execute shell commands" in body
    assert "PreToolUse security hook" in body
    assert "Zero self-approval" in body


def test_developer_instruction_json_schemas_parse_with_runtime_parsers():
    _, body = _load_agent_md("developer")
    json_blocks = _extract_all_json_blocks(body)
    assert len(json_blocks) >= 2, f"Expected at least 2 JSON examples in Developer instruction, found {len(json_blocks)}"

    # Block 1: Structured Planning Mode (STEP 13A)
    planning_json = json_blocks[0]
    planning_result = parse_and_validate_developer_result(planning_json)
    assert isinstance(planning_result, DeveloperTaskResult)
    assert planning_result.status == "completed"
    assert len(planning_result.implementation_plan) > 0
    assert len(planning_result.files_to_modify) > 0
    assert len(planning_result.files_to_create) > 0

    # Block 2: Bounded Mutation Mode (STEP 13B-2)
    mutation_json = json_blocks[1]
    mutation_result = parse_and_validate_developer_mutation_result(mutation_json)
    assert isinstance(mutation_result, DeveloperMutationResult)
    assert mutation_result.status == "completed"
    assert len(mutation_result.files_attempted) > 0
    assert len(mutation_result.files_completed) > 0
