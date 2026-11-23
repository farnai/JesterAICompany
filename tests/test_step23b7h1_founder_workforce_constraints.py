"""Step 23B.7-H.1: Founder Workforce Constraints & CEO Fallback Fix Unit Tests.

Verifies deterministic enforcement of Founder-required specialist roles,
CEO planning contract, fallback heuristics, DAG validation, and telemetry.
"""

import json
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import unittest
from unittest.mock import MagicMock, patch

from jester_ai_company.orchestrator import (
    CompanyObjective,
    CompanyRun,
    CompanyRunState,
    CEOOrchestrationPlan,
    CEOPlannedWorkItem,
    DAGValidationError,
    PlanValidationError,
    extract_acceptance_criteria_from_text,
    extract_required_roles_from_constraints,
)
from jester_ai_company.dag import validate_dag_structure
from jester_ai_company.ceo_contract import (
    CEODecisionValidationError,
    TaskCategory,
    TeamSelectionResult,
    build_ceo_planning_prompt,
    build_ceo_team_selection_prompt,
    evaluate_team_selection_heuristically,
    parse_and_validate_ceo_plan,
    parse_and_validate_team_selection,
)
from jester_ai_company.service import CompanyService
from jester_ai_company.runtime import AgentExecutionResult


class TestStep23B7H1FounderWorkforceConstraints(unittest.TestCase):
    """Deterministic verification of Founder workforce constraints and fallback behavior."""

    def test_a_complex_ui_redesign_with_founder_required_roles(self):
        """Test A: Complex UI redesign explicitly requiring Product and UX.

        Expected: Both roles included; valid dependencies.
        """
        obj = CompanyObjective(
            id="obj_ui_redesign_01",
            title="Registration Page Visual Redesign",
            description="Complete redesign of registration interface with light theme and orange accent.",
            constraints=[
                "Required specialist roles: product, ux, developer",
                "Light modern visual styling",
            ],
            acceptance_criteria=["Verified PRD", "Verified UX Spec", "Verified Frontend Implementation"],
        )

        self.assertEqual(obj.required_roles, ["product", "ux", "developer"])

        # Test heuristic formulation
        team_sel = evaluate_team_selection_heuristically(obj)
        self.assertIn("product", team_sel.selected_roles)
        self.assertIn("ux", team_sel.selected_roles)
        self.assertIn("developer", team_sel.selected_roles)
        self.assertEqual(team_sel.task_category, TaskCategory.LARGE_FEATURE.value)
        self.assertFalse(team_sel.allow_direct_developer)

        # Build plan with valid dependencies: Product -> UX -> Developer
        plan_dict = {
            "schema_version": "1.0",
            "plan_id": "plan_ui_redesign_01",
            "objective_id": obj.id,
            "version": 1,
            "task_category": "LARGE_FEATURE",
            "allow_direct_developer": False,
            "work_items": [
                {
                    "work_item_id": "wi_prod",
                    "role": "product",
                    "objective": "Author PRD for registration redesign",
                    "depends_on": [],
                    "expected_outputs": ["Product PRD"],
                },
                {
                    "work_item_id": "wi_ux",
                    "role": "ux",
                    "objective": "Author UX specifications for registration redesign",
                    "depends_on": ["wi_prod"],
                    "expected_outputs": ["UX Spec"],
                },
                {
                    "work_item_id": "wi_dev",
                    "role": "developer",
                    "objective": "Implement RegisterPage.tsx redesign",
                    "depends_on": ["wi_prod", "wi_ux"],
                    "expected_outputs": ["frontend/src/modules/auth/RegisterPage.tsx"],
                },
            ],
            "completion_criteria": ["PRD ready", "UX ready", "Code ready"],
            "constraints": ["Zero backend changes"],
        }

        parsed_plan = parse_and_validate_ceo_plan(json.dumps(plan_dict), obj, team_selection=team_sel)
        self.assertEqual(len(parsed_plan.work_items), 3)
        self.assertFalse(parsed_plan.allow_direct_developer)

    def test_b_same_objective_with_misleading_bug_fix_keywords(self):
        """Test B: Objective with misleading BUG_FIX keywords ('error', 'patch', 'repair').

        Expected: Founder-required roles remain included; does not downgrade to BUG_FIX.
        """
        obj = CompanyObjective(
            id="obj_ui_misleading_02",
            title="LIVE Jester Registration Redesign",
            description="Redesign page with error states presentation, code_patch deliverable, and QA repair loop.",
            constraints=[
                "Required specialist roles: product, ux, developer",
                "Light modern visual styling with orange accents",
            ],
            acceptance_criteria=["Handle error states", "Produce code_patch", "Pass repair loop"],
        )

        self.assertEqual(obj.required_roles, ["product", "ux", "developer"])

        # In crun_95911c2e, 'error states', 'code_patch', 'repair loop' triggered BUG_FIX.
        # Now, Rule 0 guarantees Founder-required roles are honored!
        team_sel = evaluate_team_selection_heuristically(obj)
        self.assertEqual(team_sel.task_category, TaskCategory.LARGE_FEATURE.value)
        self.assertEqual(team_sel.selected_roles, ["product", "ux", "developer"])
        self.assertFalse(team_sel.allow_direct_developer)

    def test_c_normal_small_bug_fix_without_founder_required_roles(self):
        """Test C: Normal small bug fix without Founder-required roles.

        Expected: Direct Developer remains available; minimum sufficient team selected.
        """
        obj = CompanyObjective(
            id="obj_bug_03",
            title="Fix 500 Internal Server Error in /api/v1/users endpoint",
            description="The users endpoint crashes with a 500 error when querying with an invalid UUID parameter.",
            constraints=["Zero database changes"],
            acceptance_criteria=["Endpoint returns 400 Bad Request instead of 500", "Unit tests added"],
        )

        self.assertIsNone(obj.required_roles)

        team_sel = evaluate_team_selection_heuristically(obj)
        self.assertEqual(team_sel.task_category, TaskCategory.BUG_FIX.value)
        self.assertEqual(team_sel.selected_roles, ["developer"])
        self.assertTrue(team_sel.allow_direct_developer)

        plan_dict = {
            "schema_version": "1.0",
            "plan_id": "plan_bug_03",
            "objective_id": obj.id,
            "version": 1,
            "task_category": "BUG_FIX",
            "allow_direct_developer": True,
            "work_items": [
                {
                    "work_item_id": "wi_dev_fix",
                    "role": "developer",
                    "objective": "Fix 500 error in users endpoint",
                    "depends_on": [],
                    "expected_outputs": ["Fix patch"],
                }
            ],
            "completion_criteria": ["Bug fixed"],
            "constraints": ["No db changes"],
        }

        parsed_plan = parse_and_validate_ceo_plan(json.dumps(plan_dict), obj, team_selection=team_sel)
        self.assertEqual(len(parsed_plan.work_items), 1)
        self.assertTrue(parsed_plan.allow_direct_developer)

    def test_d_ceo_model_times_out_fallback_honors_founder_constraints(self):
        """Test D: CEO model times out; fallback honors structured Founder constraints.

        Expected: Fallback records timeout in telemetry; selected roles honor Founder constraints.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            mock_runtime = MagicMock()
            # Simulate CEO CLI timing out after 60s
            mock_runtime.execute.return_value = AgentExecutionResult(
                agent="ceo",
                success=False,
                stdout="",
                stderr="Agent execution timed out after 60.0 seconds.",
                exit_code=-1,
                duration_ms=60000.0,
                timed_out=True,
                command=["agy", "-p", "..."],
            )

            service = CompanyService(
                output_dir=str(tmp_path / ".runs"),
                repo_root=tmp_path,
                runtime=mock_runtime,
                is_production=True,
            )

            obj = CompanyObjective(
                id="obj_timeout_04",
                title="Registration Flow Overhaul",
                description="Overhaul credentials flow with error states and validation repair.",
                required_roles=["product", "ux", "developer"],
                constraints=["Zero backend mutation"],
            )

            run = service.create_company_run(objective=obj)
            team_sel = service.select_company_team(run=run)

            # Verification:
            self.assertTrue(team_sel.fallback_activated)
            self.assertIn("timed out", team_sel.fallback_reason.lower())
            self.assertEqual(team_sel.selected_roles, ["product", "ux", "developer"])
            self.assertEqual(team_sel.task_category, TaskCategory.LARGE_FEATURE.value)

            # Check that fallback is recorded in run telemetry
            self.assertEqual(run.execution_telemetry.get("team_selection_source"), "HEURISTIC_FALLBACK")
            self.assertIn("timed out", run.execution_telemetry.get("fallback_reason", "").lower())

            # Check event was emitted
            fallback_events = [
                e for e in run.events
                if (e.event_type if hasattr(e, "event_type") else e.get("event_type")) == "CEO_TEAM_SELECTION_FALLBACK_ACTIVATED"
            ]
            self.assertEqual(len(fallback_events), 1)

    def test_e_ceo_model_returns_plan_missing_required_roles_rejected(self):
        """Test E: CEO model returns a plan missing required roles.

        Expected: Plan rejected; PlanValidationError or DAGValidationError raised.
        """
        obj = CompanyObjective(
            id="obj_missing_role_05",
            title="New User Onboarding Redesign",
            description="Redesign onboarding steps.",
            required_roles=["product", "ux", "developer"],
        )

        # Plan only contains developer
        plan_dict = {
            "schema_version": "1.0",
            "plan_id": "plan_missing_05",
            "objective_id": obj.id,
            "version": 1,
            "task_category": "LARGE_FEATURE",
            "work_items": [
                {
                    "work_item_id": "wi_dev_only",
                    "role": "developer",
                    "objective": "Implement onboarding without product/ux",
                    "depends_on": [],
                    "expected_outputs": ["Patch"],
                }
            ],
            "completion_criteria": ["Done"],
            "constraints": [],
        }

        with self.assertRaises(DAGValidationError) as ctx:
            parse_and_validate_ceo_plan(json.dumps(plan_dict), obj)
        self.assertIn("missing required roles", str(ctx.exception).lower())

    def test_f_incompatible_required_role_dependencies_rejected(self):
        """Test F: Incompatible required-role dependencies (e.g. UX does not depend on Product, or cycle).

        Expected: Explicit validation failure (DAGValidationError).
        """
        obj = CompanyObjective(
            id="obj_incompatible_06",
            title="Feature Redesign",
            description="Redesign feature.",
            required_roles=["product", "ux", "developer"],
        )

        # Case 1: UX does not depend on Product
        bad_dep_plan = {
            "schema_version": "1.0",
            "plan_id": "plan_bad_dep_06",
            "objective_id": obj.id,
            "version": 1,
            "task_category": "LARGE_FEATURE",
            "work_items": [
                {
                    "work_item_id": "wi_prod",
                    "role": "product",
                    "objective": "Product PRD",
                    "depends_on": [],
                    "expected_outputs": ["PRD"],
                },
                {
                    "work_item_id": "wi_ux",
                    "role": "ux",
                    "objective": "UX Spec independent of product",
                    "depends_on": [],  # Violates Product -> UX dependency
                    "expected_outputs": ["UX Spec"],
                },
                {
                    "work_item_id": "wi_dev",
                    "role": "developer",
                    "objective": "Dev implementation",
                    "depends_on": ["wi_prod", "wi_ux"],
                    "expected_outputs": ["Code"],
                },
            ],
            "completion_criteria": ["Done"],
            "constraints": [],
        }

        with self.assertRaises(DAGValidationError) as ctx:
            parse_and_validate_ceo_plan(json.dumps(bad_dep_plan), obj)
        self.assertIn("must depend on product", str(ctx.exception).lower())

        # Case 2: Cycle among required roles
        cycle_plan = {
            "schema_version": "1.0",
            "plan_id": "plan_cycle_06",
            "objective_id": obj.id,
            "version": 1,
            "task_category": "LARGE_FEATURE",
            "work_items": [
                {
                    "work_item_id": "wi_prod",
                    "role": "product",
                    "objective": "Product PRD",
                    "depends_on": ["wi_dev"],  # Cycle!
                    "expected_outputs": ["PRD"],
                },
                {
                    "work_item_id": "wi_ux",
                    "role": "ux",
                    "objective": "UX Spec",
                    "depends_on": ["wi_prod"],
                    "expected_outputs": ["UX Spec"],
                },
                {
                    "work_item_id": "wi_dev",
                    "role": "developer",
                    "objective": "Dev implementation",
                    "depends_on": ["wi_prod", "wi_ux"],
                    "expected_outputs": ["Code"],
                },
            ],
            "completion_criteria": ["Done"],
            "constraints": [],
        }

        with self.assertRaises(DAGValidationError) as ctx:
            parse_and_validate_ceo_plan(json.dumps(cycle_plan), obj)
        self.assertIn("cycle detected", str(ctx.exception).lower())

    def test_g_existing_persisted_company_runs_backward_compatibility(self):
        """Test G: Existing persisted CompanyRuns without required-role metadata.

        Expected: Clean deserialization and compatibility; required_roles is None.
        """
        persisted_data = {
            "id": "obj_legacy_07",
            "title": "Legacy Objective",
            "description": "Old objective serialized before required_roles field existed.",
            "constraints": ["Legacy constraint 1"],
            "acceptance_criteria": ["Legacy criteria 1"],
            "target_repository": "C:/repos/test",
            "project_id": "prj_legacy",
            "created_at": "2026-09-01T12:00:00Z",
            "created_by": "HUMAN",
        }

        obj = CompanyObjective.from_dict(persisted_data)
        self.assertIsNone(obj.required_roles)
        serialized = obj.to_dict()
        self.assertIsNone(serialized["required_roles"])

        # TeamSelectionResult backward compatibility
        legacy_team_data = {
            "task_category": "BUG_FIX",
            "complexity": "LOW",
            "uncertainty": "LOW",
            "risk": "LOW",
            "required_capabilities": ["code_patch"],
            "selected_roles": ["developer"],
            "role_requirements": [
                {
                    "role": "developer",
                    "why_necessary": "Code patch",
                    "expected_deliverable": "Patch",
                    "required_upstream_inputs": [],
                    "is_essential": True,
                }
            ],
            "omitted_roles_rationale": {"product": "Not needed"},
            "selection_reasoning": "Minimal fix",
            "escalation_conditions": [],
            "estimated_specialist_count": 1,
            "actual_specialist_count": 1,
            "avoidable_delegation_warnings": [],
            "allow_direct_developer": True,
            "enforce_strict_roles": False,
        }

        ts = TeamSelectionResult.from_dict(legacy_team_data)
        self.assertFalse(ts.fallback_activated)
        self.assertIsNone(ts.fallback_reason)

    def test_h_different_target_project_with_different_required_roles(self):
        """Test H: Different target project with different required roles (e.g. Research-only).

        Expected: No Jester-specific assumptions or rules leak into that project.
        """
        non_jester_obj = CompanyObjective(
            id="obj_alpha_08",
            title="Bio-Informatics Target Genome Analysis",
            description="Deep literature and genetic variant analysis for novel compound.",
            constraints=["Required specialist roles: research"],
            acceptance_criteria=["Comprehensive research synthesis"],
            target_repository="C:/repos/BioInformatics",
            project_id="prj_alpha",
        )

        self.assertEqual(non_jester_obj.required_roles, ["research"])

        team_sel = evaluate_team_selection_heuristically(non_jester_obj)
        self.assertEqual(team_sel.selected_roles, ["research"])
        self.assertEqual(team_sel.task_category, TaskCategory.RESEARCH.value)
        self.assertFalse(team_sel.allow_direct_developer)

    def test_i_product_ux_developer_artifact_and_dag_contracts_compatible(self):
        """Test I: Product -> UX -> Developer artifact and DAG contracts remain compatible.

        Expected: DAG dependencies match handoff architecture.
        """
        obj = CompanyObjective(
            id="obj_full_pipeline_09",
            title="Full feature development",
            description="End to end product development.",
            required_roles=["product", "ux", "developer"],
        )

        prompt = build_ceo_planning_prompt(obj)
        self.assertIn("FOUNDER MANDATED WORKFORCE INVARIANT", prompt)
        self.assertIn("product", prompt.lower())
        self.assertIn("ux", prompt.lower())
        self.assertIn("developer", prompt.lower())
        self.assertIn("Product -> UX -> Developer", prompt)


if __name__ == "__main__":
    unittest.main()
