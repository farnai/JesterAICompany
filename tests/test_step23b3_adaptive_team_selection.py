"""Tests for STEP 23B.3: CEO Adaptive Team Selection & Execution Efficiency.

Deterministic test suite covering:
1. Simple backend bug -> minimal engineering team (Developer-only).
2. Research-only task -> Research without Developer/UX.
3. Marketing-only task -> Marketing.
4. Simple UI change -> UX/Developer without unnecessary Product/Research.
5. Complex new feature -> appropriate multi-specialist team.
6. Georgian-language objectives (all major task categories).
7. Empty acceptance criteria handling.
8. Uncertainty resolved by STEP 23B.2 investigation context.
9. Genuine adaptive escalation without duplicate work and bounded attempts.
10. Unsupported roles and invalid dependencies rejected before execution.
11. Engineering QA remains mandatory for code mutations.
12. Founder Approval and Execution Grants remain unchanged and cannot be bypassed.
13. Existing CompanyRun persistence and resume behavior with team selection.
14. Target repository invariant: No unauthorized repository mutations.
"""

import json
from pathlib import Path
import tempfile
import pytest

from jester_ai_company.ceo_contract import (
    ComplexityLevel,
    RiskLevel,
    RoleRequirement,
    TaskCategory,
    TeamSelectionResult,
    UncertaintyLevel,
    build_ceo_team_selection_prompt,
    evaluate_team_selection_heuristically,
    parse_and_validate_ceo_plan,
    parse_and_validate_team_selection,
    CEODecisionSecurityError,
    CEODecisionValidationError,
    PlanValidationError,
)
from jester_ai_company.dag import (
    DAGValidationError,
    validate_dag_structure,
)
from jester_ai_company.orchestrator import (
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    TeamEscalationRecord,
    UnsupportedRoleError,
    WorkItemState,
)
from jester_ai_company.service import CompanyService


@pytest.fixture
def temp_service() -> CompanyService:
    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    runs_dir = tmp_path / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return CompanyService(
        repo_root=tmp_path,
        output_dir=str(runs_dir),
    )


# -----------------------------------------------------------------------------
# 1. Simple backend bug -> minimal engineering team (Developer-only)
# -----------------------------------------------------------------------------

def test_requirement_1_simple_backend_bug_minimal_engineering_team():
    obj = CompanyObjective(
        id="obj_bug_001",
        title="Fix registration password validation 500 error",
        description="Fix server crash on invalid password length in backend/app/routers/auth.py",
        constraints=["Preserve existing auth tests"],
        acceptance_criteria=["Password validation returns 422 instead of 500 error"],
    )

    team_res = evaluate_team_selection_heuristically(obj)

    assert team_res.task_category == TaskCategory.BUG_FIX.value
    assert team_res.selected_roles == ["developer"]
    assert team_res.allow_direct_developer is True
    assert team_res.complexity in (ComplexityLevel.LOW.value, ComplexityLevel.MEDIUM.value)
    assert team_res.uncertainty == UncertaintyLevel.LOW.value

    # Verify omitted roles have rationale
    assert "product" in team_res.omitted_roles_rationale
    assert "ux" in team_res.omitted_roles_rationale
    assert "research" in team_res.omitted_roles_rationale
    assert "qa" in team_res.omitted_roles_rationale

    # Verify avoidable delegation warnings
    assert len(team_res.avoidable_delegation_warnings) > 0
    assert "Saved 4 unnecessary specialist invocations" in team_res.avoidable_delegation_warnings[0]

    # Verify minimal DAG is valid
    plan = CEOOrchestrationPlan(
        plan_id="plan_dev_only",
        objective_id=obj.id,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="wi_dev",
                role="developer",
                objective="Fix password validation",
                depends_on=[],
                expected_outputs=["code_patch.diff"],
            )
        ],
        task_category=team_res.task_category,
        allow_direct_developer=team_res.allow_direct_developer,
    )
    validate_dag_structure(plan)


# -----------------------------------------------------------------------------
# 2. Research-only task -> Research without Developer/UX
# -----------------------------------------------------------------------------

def test_requirement_2_research_only_task():
    obj = CompanyObjective(
        id="obj_res_001",
        title="Research competitor pricing models for people discovery platforms",
        description="Analyze market trends, competitor pricing tiers, and summarize findings",
        constraints=[],
        acceptance_criteria=["Market research summary report delivered"],
    )

    team_res = evaluate_team_selection_heuristically(obj)

    assert team_res.task_category == TaskCategory.RESEARCH.value
    assert team_res.selected_roles == ["research"]
    assert team_res.allow_direct_developer is False
    assert "developer" in team_res.omitted_roles_rationale
    assert "ux" in team_res.omitted_roles_rationale
    assert "product" in team_res.omitted_roles_rationale


# -----------------------------------------------------------------------------
# 3. Marketing-only task -> Marketing
# -----------------------------------------------------------------------------

def test_requirement_3_marketing_only_task():
    obj = CompanyObjective(
        id="obj_mkt_001",
        title="Draft marketing announcement and blog post for v1.0 release",
        description="Craft compelling messaging and social media campaign copy",
        constraints=[],
        acceptance_criteria=["Blog post draft delivered"],
    )

    team_res = evaluate_team_selection_heuristically(obj)

    assert team_res.task_category == TaskCategory.MARKETING.value
    assert team_res.selected_roles == ["marketing"]
    assert team_res.allow_direct_developer is False
    assert "developer" in team_res.omitted_roles_rationale
    assert "qa" in team_res.omitted_roles_rationale


# -----------------------------------------------------------------------------
# 4. Simple UI change -> UX/Developer without unnecessary Product/Research
# -----------------------------------------------------------------------------

def test_requirement_4_simple_ui_change_no_unnecessary_product_research():
    obj = CompanyObjective(
        id="obj_ui_001",
        title="Adjust button styling, padding and primary brand color",
        description="Update visual CSS tokens and adjust component layout for buttons",
        constraints=[],
        acceptance_criteria=["Button padding matches 12px specification"],
    )

    team_res = evaluate_team_selection_heuristically(obj)

    assert team_res.task_category == TaskCategory.UI_UX_CHANGE.value
    assert "ux" in team_res.selected_roles
    assert "developer" in team_res.selected_roles
    assert "product" in team_res.omitted_roles_rationale
    assert "research" in team_res.omitted_roles_rationale


# -----------------------------------------------------------------------------
# 5. Complex new feature -> appropriate multi-specialist team
# -----------------------------------------------------------------------------

def test_requirement_5_complex_new_feature_appropriate_multi_specialist_team():
    obj = CompanyObjective(
        id="obj_feat_001",
        title="Implement complex feature: multi-tenant billing with Stripe integration",
        description="Build multi-tenant subscription tiers, payment webhooks, and customer portal",
        constraints=[],
        acceptance_criteria=["Stripe webhooks verified", "Billing settings UI operational"],
    )

    team_res = evaluate_team_selection_heuristically(obj)

    assert team_res.task_category == TaskCategory.LARGE_FEATURE.value
    assert team_res.complexity == ComplexityLevel.HIGH.value
    assert "product" in team_res.selected_roles
    assert "ux" in team_res.selected_roles
    assert "developer" in team_res.selected_roles


# -----------------------------------------------------------------------------
# 6. Georgian-language objectives (all major task categories)
# -----------------------------------------------------------------------------

def test_requirement_6_georgian_language_objectives():
    # 1. Bug Fix
    obj_geo_bug = CompanyObjective(
        id="obj_geo_1",
        title="რეგისტრაცია - შეასწორე პაროლის ვალიდაცია",
        description="ავტორიზაციის შეცდომა 500 კოდით",
        acceptance_criteria=["შეცდომა გასწორებულია"],
    )
    res_bug = evaluate_team_selection_heuristically(obj_geo_bug)
    assert res_bug.task_category == TaskCategory.BUG_FIX.value
    assert res_bug.selected_roles == ["developer"]
    assert res_bug.allow_direct_developer is True

    # 2. Research
    obj_geo_res = CompanyObjective(
        id="obj_geo_2",
        title="იკვლიე AI ბაზრის ტენდენციები და ალტერნატივები",
        description="კონკურენტების ანალიზი",
        acceptance_criteria=["კვლევის ანგარიში მომზადებულია"],
    )
    res_res = evaluate_team_selection_heuristically(obj_geo_res)
    assert res_res.task_category == TaskCategory.RESEARCH.value
    assert res_res.selected_roles == ["research"]

    # 3. Marketing
    obj_geo_mkt = CompanyObjective(
        id="obj_geo_3",
        title="დაწერე მარკეტინგული პოსტი რელიზისთვის",
        description="ანონსი სოციალური მედიისთვის",
        acceptance_criteria=["პოსტი მზადაა"],
    )
    res_mkt = evaluate_team_selection_heuristically(obj_geo_mkt)
    assert res_mkt.task_category == TaskCategory.MARKETING.value
    assert res_mkt.selected_roles == ["marketing"]

    # 4. UI Change
    obj_geo_ui = CompanyObjective(
        id="obj_geo_4",
        title="ღილაკების სტილის და ფერის შეცვლა",
        description="ინტერფეისის დიზაინის მორგება",
        acceptance_criteria=["ახალი სტილი დამატებულია"],
    )
    res_ui = evaluate_team_selection_heuristically(obj_geo_ui)
    assert res_ui.task_category == TaskCategory.UI_UX_CHANGE.value
    assert "ux" in res_ui.selected_roles

    # 5. Large Feature
    obj_geo_feat = CompanyObjective(
        id="obj_geo_5",
        title="ახალი ფუნქციონალი: მრავალმომხმარებლიანი ბილინგი",
        description="სისტემის ინტეგრაცია გადახდებთან",
        acceptance_criteria=["ბილინგი მუშაობს"],
    )
    res_feat = evaluate_team_selection_heuristically(obj_geo_feat)
    assert res_feat.task_category == TaskCategory.LARGE_FEATURE.value
    assert "product" in res_feat.selected_roles
    assert "developer" in res_feat.selected_roles


# -----------------------------------------------------------------------------
# 7. Empty acceptance criteria handling
# -----------------------------------------------------------------------------

def test_requirement_7_empty_acceptance_criteria():
    obj = CompanyObjective(
        id="obj_empty_crit",
        title="Fix 500 error on user profile load",
        description="Server returns 500 when avatar is null",
        acceptance_criteria=[],
    )

    team_res = evaluate_team_selection_heuristically(obj)
    assert team_res.task_category == TaskCategory.BUG_FIX.value
    assert team_res.selected_roles == ["developer"]


# -----------------------------------------------------------------------------
# 8. Uncertainty resolved by STEP 23B.2 investigation context
# -----------------------------------------------------------------------------

def test_requirement_8_uncertainty_resolved_by_investigation():
    obj = CompanyObjective(
        id="obj_inv_001",
        title="Fix registration",
        description="Founder reported registration failure",
        acceptance_criteria=[],
    )
    findings = [
        "Inspected file: backend/app/routers/auth.py",
        "Found KeyError in password validation logic",
        "Test auth/test_registration.py reproduces 500 status",
    ]

    team_res = evaluate_team_selection_heuristically(obj, investigation_findings=findings)

    assert team_res.task_category == TaskCategory.BUG_FIX.value
    assert team_res.selected_roles == ["developer"]
    assert team_res.allow_direct_developer is True


# -----------------------------------------------------------------------------
# 9. Genuine adaptive escalation without duplicate work and bounded attempts
# -----------------------------------------------------------------------------

def test_requirement_9_genuine_escalation_without_duplicate_work(temp_service):
    obj = CompanyObjective(
        id="obj_esc_run",
        title="Fix registration on Jester",
        description="Resolve registration issue",
        acceptance_criteria=["Registration returns 201"],
    )
    run = temp_service.create_company_run(obj)
    # Set initial plan with developer
    plan = CEOOrchestrationPlan(
        plan_id="plan_init",
        objective_id=obj.id,
        work_items=[
            CEOPlannedWorkItem(
                work_item_id="wi_dev_1",
                role="developer",
                objective="Implement registration fix",
                depends_on=[],
                expected_outputs=["patch.diff"],
            )
        ],
        task_category=TaskCategory.BUG_FIX.value,
        allow_direct_developer=True,
    )
    run.set_plan(plan)
    run.team_selection = {
        "task_category": TaskCategory.BUG_FIX.value,
        "selected_roles": ["developer"],
        "actual_specialist_count": 1,
    }
    temp_service.save_company_run(run)

    # 1. First escalation: Developer discovers UX ambiguity
    run_esc1 = temp_service.escalate_company_team(
        run_id=run.run_id,
        triggered_by_role="developer",
        reason="Registration modal styling is ambiguous",
        requested_capability="ux_design",
        requested_role="ux",
    )
    assert run_esc1.escalation_count == 1
    assert len(run_esc1.team_escalations) == 1
    assert "ux" in run_esc1.team_selection["selected_roles"]
    assert any(w.role == "ux" for w in run_esc1.active_plan.work_items)
    assert run_esc1.team_escalations[0]["action_taken"] == "ADDED_SPECIALIST"

    # 2. Duplicate escalation attempt for UX: must NOT duplicate work items
    run_esc2 = temp_service.escalate_company_team(
        run_id=run.run_id,
        triggered_by_role="developer",
        reason="Repeated call for UX",
        requested_capability="ux_design",
        requested_role="ux",
    )
    assert run_esc2.escalation_count == 2
    assert run_esc2.team_escalations[1]["action_taken"] == "ALREADY_PRESENT_NO_DUPLICATE"
    # Ensure only 1 UX work item exists
    ux_items = [w for w in run_esc2.active_plan.work_items if w.role == "ux"]
    assert len(ux_items) == 1

    # 3. Third escalation attempt: Exceeds max_escalations (budget=2)
    run_esc3 = temp_service.escalate_company_team(
        run_id=run.run_id,
        triggered_by_role="developer",
        reason="Need research on competitors",
        requested_capability="market_research",
        requested_role="research",
    )
    assert run_esc3.escalation_count == 2  # Not incremented past limit
    assert run_esc3.team_escalations[-1]["action_taken"] == "REJECTED_BUDGET_EXCEEDED"
    assert not any(w.role == "research" for w in run_esc3.active_plan.work_items)


# -----------------------------------------------------------------------------
# 10. Unsupported roles and invalid dependencies rejected before execution
# -----------------------------------------------------------------------------

def test_requirement_10_unsupported_roles_dependencies_rejected_before_execution():
    # A. Unsupported role in RoleRequirement
    with pytest.raises(CEODecisionValidationError, match="not a recognized macro role"):
        RoleRequirement(
            role="growth_hacker",
            why_necessary="Marketing growth",
            expected_deliverable="Growth metrics",
        )

    # B. Unsupported role in TeamSelectionResult payload
    bad_team_payload = {
        "task_category": "BUG_FIX",
        "complexity": "LOW",
        "uncertainty": "LOW",
        "risk": "LOW",
        "required_capabilities": ["hacking"],
        "selected_roles": ["sales_rep"],
        "role_requirements": [
            {
                "role": "developer",
                "why_necessary": "dev",
                "expected_deliverable": "patch",
            }
        ],
        "omitted_roles_rationale": {},
        "selection_reasoning": "bad team",
        "escalation_conditions": [],
    }
    with pytest.raises(CEODecisionValidationError):
        parse_and_validate_team_selection(bad_team_payload)

    # C. CEO plan specifies role omitted in team selection
    obj = CompanyObjective(id="obj_c", title="Bug", description="Bug")
    team_sel = TeamSelectionResult(
        task_category=TaskCategory.BUG_FIX.value,
        complexity="LOW",
        uncertainty="LOW",
        risk="LOW",
        required_capabilities=["code"],
        selected_roles=["developer"],
        role_requirements=[
            RoleRequirement(role="developer", why_necessary="code", expected_deliverable="diff")
        ],
        omitted_roles_rationale={"product": "omitted"},
        selection_reasoning="minimal team",
        escalation_conditions=[],
        estimated_specialist_count=1,
        actual_specialist_count=1,
        enforce_strict_roles=True,
    )
    plan_with_omitted_role = {
        "schema_version": "1.0",
        "plan_id": "p_bad",
        "objective_id": obj.id,
        "version": 1,
        "work_items": [
            {
                "work_item_id": "wi_prod",
                "role": "product",
                "objective": "Spec",
                "depends_on": [],
                "expected_outputs": ["spec.md"],
            }
        ],
    }
    with pytest.raises(PlanValidationError, match="omitted in CEO team selection"):
        parse_and_validate_ceo_plan(json.dumps(plan_with_omitted_role), obj, team_selection=team_sel)


# -----------------------------------------------------------------------------
# 11. Engineering QA remains mandatory for code mutations
# -----------------------------------------------------------------------------

def test_requirement_11_engineering_qa_remains_mandatory_for_code_mutations():
    # Attempting to insert skip_qa or bypass QA in TeamSelectionResult raises CEODecisionSecurityError
    privileged_payload = {
        "task_category": "BUG_FIX",
        "complexity": "LOW",
        "uncertainty": "LOW",
        "risk": "LOW",
        "skip_qa": True,
        "selected_roles": ["developer"],
        "role_requirements": [
            {
                "role": "developer",
                "why_necessary": "code",
                "expected_deliverable": "patch",
            }
        ],
        "omitted_roles_rationale": {},
        "selection_reasoning": "bypass qa test",
        "escalation_conditions": [],
    }
    with pytest.raises(CEODecisionSecurityError, match="Unauthorized privileged key 'skip_qa'"):
        parse_and_validate_team_selection(privileged_payload)


# -----------------------------------------------------------------------------
# 12. Founder Approval and Execution Grants remain unchanged
# -----------------------------------------------------------------------------

def test_requirement_12_founder_approval_and_execution_grants_unchanged():
    # Attempting to grant permissions via CEO team selection raises security error
    privileged_payload = {
        "task_category": "BUG_FIX",
        "complexity": "LOW",
        "uncertainty": "LOW",
        "risk": "LOW",
        "execution_grant": "auto_grant",
        "selected_roles": ["developer"],
        "role_requirements": [
            {
                "role": "developer",
                "why_necessary": "code",
                "expected_deliverable": "patch",
            }
        ],
        "omitted_roles_rationale": {},
        "selection_reasoning": "bypass grant test",
        "escalation_conditions": [],
    }
    with pytest.raises(CEODecisionSecurityError, match="Unauthorized privileged key 'execution_grant'"):
        parse_and_validate_team_selection(privileged_payload)


# -----------------------------------------------------------------------------
# 13. Existing CompanyRun persistence and resume behavior
# -----------------------------------------------------------------------------

def test_requirement_13_company_run_persistence_and_resume_behavior():
    obj = CompanyObjective(id="obj_persist", title="Test Persist", description="Persistence check")
    run = CompanyRun(
        run_id="crun_persist_123",
        objective=obj,
        state=CompanyRunState.RUNNING.value,
        team_selection={
            "task_category": TaskCategory.BUG_FIX.value,
            "selected_roles": ["developer"],
            "complexity": "LOW",
            "actual_specialist_count": 1,
        },
        team_escalations=[
            {
                "escalation_id": "tesc_001",
                "run_id": "crun_persist_123",
                "triggered_by_role": "developer",
                "reason": "Missing UX specification",
                "requested_capability": "ux_design",
                "added_roles": ["ux"],
                "action_taken": "ADDED_SPECIALIST",
                "created_at": "2026-10-09T00:00:00Z",
            }
        ],
        escalation_count=1,
        max_escalations=2,
    )

    d = run.to_dict()
    restored = CompanyRun.from_dict(d)

    assert restored.run_id == run.run_id
    assert restored.team_selection["task_category"] == TaskCategory.BUG_FIX.value
    assert len(restored.team_escalations) == 1
    assert restored.team_escalations[0]["added_roles"] == ["ux"]
    assert restored.escalation_count == 1
    assert restored.max_escalations == 2


# -----------------------------------------------------------------------------
# 14. Target repository invariant: No unauthorized repository mutations
# -----------------------------------------------------------------------------

def test_requirement_14_no_unauthorized_jester_repository_mutations(temp_service):
    obj = CompanyObjective(
        id="obj_clean_repo",
        title="Fix registration",
        description="Verify repo untouched",
        acceptance_criteria=["No file writes"],
    )
    # Ensure temporary workspace has no git mutations
    initial_files = list(temp_service.repo_root.rglob("*"))

    team_res = evaluate_team_selection_heuristically(obj, repo_root=temp_service.repo_root)
    assert team_res is not None

    after_files = list(temp_service.repo_root.rglob("*"))
    assert initial_files == after_files
