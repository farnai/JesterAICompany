"""Stage 1 Verification Suite: QA Integrity, Verification Truthfulness & Core Crash Fixes.

Covers exact Stage 1 defects from REMEDIATION_PLAN_V2.md:
- DEF-010 (AUDIT-BUG-03): QA 14B 0 executed tests -> BLOCKED; ProtectedOperationGrant rejects 0-test QA reports.
- DEF-011 (AUDIT-BUG-04): QA 14A parser NEVER fabricates VERIFIED categories before 14B test execution.
- DEF-014 (AUDIT-BUG-05): UnboundLocalError fixes in developer_mutation.py (json_str) and service.py (spec_dur).
- DEF-017: QA 14A target_repo_root worktree routing + QA 14B configurable verification timeout (no hardcoded 30s).
- DEF-021 (AUDIT-ADV-01): Untrusted CEO JSON cannot self-authorize allow_direct_developer; no in-place selected_roles mutation.
- DEF-027: DeveloperTaskResult typed verification_actions + recovery.py generic timeout RETRY + strict AC boundary matching.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from jester_ai_company.authority import FounderDecisionType
from jester_ai_company.ceo_contract import (
    TaskCategory,
    TeamSelectionResult,
    parse_and_validate_ceo_plan,
)
from jester_ai_company.core import Artifact, ArtifactType, RunStatus, TaskStatus
from jester_ai_company.dag import DAGValidationError
from jester_ai_company.developer_mutation import parse_and_validate_developer_mutation_result
from jester_ai_company.developer_result import (
    DeveloperResultValidationError,
    parse_and_validate_developer_result,
)
from jester_ai_company.execution_grant import VerificationAction
from jester_ai_company.orchestrator import CompanyObjective, CompanyRunState
from jester_ai_company.qa_execution import (
    QAActionAuthorizationDecision,
    QAExecutionActionAudit,
    QAExecutionVerdictResult,
    QAFinalVerdict,
    enforce_deterministic_verdict_constraints,
)
from jester_ai_company.qa_result import QACategoryStatus, parse_and_validate_qa_result
from jester_ai_company.real_repo_apply import CandidateNotEligibleError, validate_candidate_eligibility
from jester_ai_company.recovery import (
    FailureCategory,
    RecoveryDecision,
    classify_specialist_failure,
    evaluate_acceptance_criteria,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService
from jester_ai_company.verification import VerificationExecutionResult
from jester_ai_company.worktree import resolve_repo_head_commit, run_git


def _init_git_repo(repo_dir: Path, files: dict[str, str]) -> str:
    repo_dir.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "stage1@jester.local"],
        ["config", "user.name", "Stage1 Tester"],
    ):
        run_git(args, cwd=repo_dir)
    for rel, content in files.items():
        fp = repo_dir / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "init"], cwd=repo_dir)
    return resolve_repo_head_commit(repo_dir)


# ==============================================================================
# DEF-010 (AUDIT-BUG-03): Zero Executed Tests MUST Always Be BLOCKED
# ==============================================================================

class TestDEF010ZeroTestPassBlocked:

    def test_audit_bug_03_zero_executed_actions_overrides_pass_to_blocked(self):
        agent_verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.PASS.value,
            summary="Looks fine visually",
            requirements_evaluations=[],
            executed_tests_summary="None executed",
            blocking_issues=[],
            release_recommendation="APPROVED_FOR_RELEASE",
        )
        out = enforce_deterministic_verdict_constraints(
            verdict_result=agent_verdict,
            action_audits=[],
            verification_results=[],
            changed_files=["app.py"],
        )
        assert out.verdict == QAFinalVerdict.BLOCKED.value
        assert out.deterministic_override_applied is True
        assert out.release_recommendation == "BLOCKED_ON_VERIFICATION_INFRASTRUCTURE"
        assert "0 tests" in (out.override_reason or "").lower()

    def test_real_executed_passing_action_preserves_pass(self):
        agent_verdict = QAExecutionVerdictResult(
            schema_version="1.0",
            verdict=QAFinalVerdict.PASS.value,
            summary="Tests passed",
            requirements_evaluations=[],
            executed_tests_summary="1 passed",
            blocking_issues=[],
            release_recommendation="APPROVED_FOR_RELEASE",
        )
        audits = [
            QAExecutionActionAudit(
                action_type="pytest",
                target="tests/test_app.py",
                purpose="verify app",
                decision=QAActionAuthorizationDecision.AUTHORIZED.value,
            )
        ]
        results = [
            VerificationExecutionResult(
                action=VerificationAction("pytest", "tests/test_app.py"),
                status="PASS",
                exit_code=0,
                stdout="1 passed",
                stderr="",
                duration_ms=25,
            )
        ]
        out = enforce_deterministic_verdict_constraints(
            verdict_result=agent_verdict,
            action_audits=audits,
            verification_results=results,
            changed_files=["app.py"],
        )
        assert out.verdict == QAFinalVerdict.PASS.value
        assert out.deterministic_override_applied is False

    def test_validate_candidate_eligibility_rejects_zero_executed_qa_report(self, tmp_path: Path):
        repo = tmp_path / "repo"
        head = _init_git_repo(repo, {"app.py": "x = 1\n"})
        patch_f = tmp_path / "patch.diff"
        patch_f.write_text("diff --git a/app.py b/app.py\n", encoding="utf-8")
        qa_f = tmp_path / "qa_exec.md"
        qa_f.write_text("# QA Exec\n", encoding="utf-8")

        patch_art = Artifact(
            id="art_p",
            run_id="r1",
            name="patch.diff",
            path="patch.diff",
            artifact_type=ArtifactType.CODE_PATCH.value,
            producer_role="developer",
            sha256=hashlib.sha256(patch_f.read_bytes()).hexdigest(),
            durable=True,
            metadata={
                "base_commit_hash": head,
                "changed_files": ["app.py"],
                "verification_outcomes": [{"status": "PASS"}],
            },
        )
        qa_art = Artifact(
            id="art_q",
            run_id="r1",
            name="qa_exec.md",
            path="qa_exec.md",
            artifact_type=ArtifactType.QA_EXECUTION_REPORT.value,
            producer_role="qa",
            sha256=hashlib.sha256(qa_f.read_bytes()).hexdigest(),
            durable=True,
            metadata={
                "verdict": "PASS",
                "code_patch_artifact_id": patch_art.id,
                "code_patch_sha256": patch_art.sha256,
                "verification_actions_executed": 0,
                "execution_outcomes": [],
            },
        )
        with pytest.raises(CandidateNotEligibleError, match="executed 0 verification actions"):
            validate_candidate_eligibility(patch_art, patch_f, qa_art, qa_f, repo)


# ==============================================================================
# DEF-011 (AUDIT-BUG-04): QA 14A Parser Never Fabricates VERIFIED Categories
# ==============================================================================

class TestDEF011NoFabricatedQACategories:

    def test_audit_bug_04_minimal_14a_json_defaults_to_not_executed_never_verified(self):
        raw = json.dumps({
            "schema_version": "1.0",
            "status": "READY_FOR_QA_EXECUTION",
            "summary": "Static inspection complete",
            "requirements_coverage": [
                {"requirement_id": "REQ-1", "status": "COVERED", "evidence": "Code present in diff"}
            ],
            "recommended_verification_actions": [
                {"action_type": "pytest", "target": "tests/test_app.py", "purpose": "Run tests"}
            ],
        })
        res = parse_and_validate_qa_result(raw)
        assert len(res.category_verifications) == 5
        for rec in res.category_verifications:
            assert rec.status == QACategoryStatus.NOT_EXECUTED.value
            assert rec.verified is False
        assert res.verified_categories == []


# ==============================================================================
# DEF-014 (AUDIT-BUG-05): UnboundLocalError Fixes (developer_mutation & service)
# ==============================================================================

class TestDEF014UnboundLocalErrorFixes:

    def test_audit_bug_05_developer_mutation_prose_with_braces_before_fenced_json(self):
        raw = (
            "Modified {app.py} successfully:\n"
            "```json\n"
            '{"schema_version":"1.0","status":"completed","summary":"Updated app.py","files_attempted":["app.py"],"files_completed":["app.py"],"blocked_actions":[],"unresolved_issues":[]}\n'
            "```\n"
        )
        res = parse_and_validate_developer_mutation_result(raw)
        assert res.status == "completed"
        assert res.files_completed == ["app.py"]

    def test_service_missing_output_artifact_does_not_crash_with_unbound_spec_dur(self, tmp_path: Path):
        repo = tmp_path / "repo"
        _init_git_repo(repo, {"README.md": "# Repo\n"})
        runs_dir = tmp_path / "runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=repo)
        obj = CompanyObjective(id="obj_s14", title="Research auth", description="Research auth flow")
        run = service.create_company_run(obj)

        mock_plan = json.dumps({
            "schema_version": "1.0",
            "version": 1,
            "objective_id": "obj_s14",
            "plan_summary": "Research only",
            "work_items": [
                {"work_item_id": "wi_res_1", "role": "research", "objective": "Research auth", "depends_on": []}
            ],
        })
        with patch.object(
            service.runtime,
            "execute",
            return_value=AgentExecutionResult(
                agent="ceo", command=["mock"], exit_code=0, stdout=f"```json\n{mock_plan}\n```", stderr="", duration_ms=5.0, success=True
            ),
        ):
            planned = service.plan_company_run(run.run_id)
            if planned.state == CompanyRunState.WAITING_FOR_CLARIFICATION.value:
                service.submit_founder_clarification(run.run_id, response="Backend auth only")
        service.start_company_run(run.run_id)

        # Simulate specialist producing a task_run whose artifact file was tampered on disk
        tampered_file = runs_dir / "tampered.md"
        tampered_file.parent.mkdir(parents=True, exist_ok=True)
        tampered_file.write_text("# Tampered content\n", encoding="utf-8")

        def fake_research_exec(task_id, project_id=None, **kwargs):
            t = service.get_task(task_id, project_id=project_id)
            tr = t.create_run()
            tr.artifacts.append(
                Artifact(
                    id="art_tampered_1",
                    run_id=tr.id,
                    name="tampered.md",
                    path="tampered.md",
                    artifact_type=ArtifactType.RESEARCH_REPORT.value,
                    producer_role="research",
                    sha256="a" * 64,  # Mismatched checksum triggers spec_dur failure path
                    durable=True,
                )
            )
            tr.complete(status=RunStatus.SUCCESS.value)
            t.complete(status=TaskStatus.COMPLETED.value, summary="done")
            return tr

        with patch.object(service, "execute_research_task", side_effect=fake_research_exec):
            # Must NOT raise UnboundLocalError('spec_dur')!
            updated = service.execute_next_company_work(run.run_id)
        assert updated is not None


# ==============================================================================
# DEF-017: QA 14A Target Repo Routing & QA 14B Configurable Verification Timeout
# ==============================================================================

class TestDEF017QARepoRoutingAndTimeout:

    def test_qa_14a_routes_to_isolated_target_repo_worktree_not_company_repo(self, tmp_path: Path):
        company_repo = tmp_path / "JesterAICompany"
        target_repo = tmp_path / "ExternalApp"
        _init_git_repo(company_repo, {"engine_only.py": "ENGINE = 1\n"})
        target_head = _init_git_repo(target_repo, {"external_app.py": "def f():\n    return 1\n"})
        runs_dir = tmp_path / "runs"

        real_rt = AntigravityRuntime(repo_root=company_repo)
        service = CompanyService(output_dir=str(runs_dir), repo_root=company_repo, runtime=real_rt)
        service.create_project("proj_17", "External Repo QA")

        prod_f = runs_dir / "prod.md"
        prod_f.parent.mkdir(parents=True, exist_ok=True)
        prod_f.write_text("# Spec\nREQ-1\n", encoding="utf-8")
        plan_f = runs_dir / "plan.md"
        plan_f.write_text("# Plan\n", encoding="utf-8")
        patch_f = runs_dir / "patch.diff"
        patch_f.write_text("diff --git a/external_app.py b/external_app.py\n", encoding="utf-8")

        prod_task = service.create_task("proj_17", "Prod", "Spec", required_roles=["product"])
        prod_run = prod_task.create_run()
        prod_art = Artifact(id="art_p17", run_id=prod_run.id, name="prod.md", path="prod.md", artifact_type=ArtifactType.SPECIFICATION.value, producer_role="product", sha256=hashlib.sha256(prod_f.read_bytes()).hexdigest(), durable=True)
        prod_run.artifacts.append(prod_art)
        prod_run.complete(RunStatus.SUCCESS.value)
        prod_task.complete(TaskStatus.COMPLETED.value, "done")

        plan_task = service.create_task("proj_17", "Plan", "Plan", required_roles=["developer"])
        service.attach_input_artifact(plan_task.id, prod_art.id, project_id="proj_17")
        plan_run = plan_task.create_run()
        plan_art = Artifact(id="art_d17", run_id=plan_run.id, name="plan.md", path="plan.md", artifact_type=ArtifactType.DEVELOPER_PLAN_REPORT.value, producer_role="developer", sha256=hashlib.sha256(plan_f.read_bytes()).hexdigest(), durable=True)
        patch_art = Artifact(id="art_c17", run_id=plan_run.id, name="patch.diff", path="patch.diff", artifact_type=ArtifactType.CODE_PATCH.value, producer_role="developer", sha256=hashlib.sha256(patch_f.read_bytes()).hexdigest(), durable=True, metadata={"base_commit_hash": target_head, "changed_files": ["external_app.py"], "plan_artifact_id": plan_art.id, "plan_sha256": plan_art.sha256, "verification_outcomes": [{"status": "PASS", "exit_code": 0}]})
        plan_run.artifacts.extend([plan_art, patch_art])
        plan_run.complete(RunStatus.SUCCESS.value)
        plan_task.complete(TaskStatus.COMPLETED.value, "done")

        qa_task = service.create_task("proj_17", "QA 14A", "Inspect", required_roles=["qa"])
        for aid in (prod_art.id, plan_art.id, patch_art.id):
            service.attach_input_artifact(qa_task.id, aid, project_id="proj_17")

        seen_ws: list[Path] = []

        def fake_qa(agent, prompt, timeout=None, workspace_dir=None, env=None):
            ws = Path(workspace_dir).resolve()
            seen_ws.append(ws)
            assert ws != company_repo.resolve()
            assert ws != target_repo.resolve()
            assert (ws / "external_app.py").is_file()
            assert not (ws / "engine_only.py").exists()
            assert (ws / ".agents" / "hooks.json").is_file()
            out = json.dumps({
                "schema_version": "1.0",
                "status": "READY_FOR_QA_EXECUTION",
                "summary": "Inspected external repo cleanly",
                "requirements_coverage": [{"requirement_id": "REQ-1", "status": "COVERED", "evidence": "ok"}],
                "recommended_verification_actions": [],
            })
            return AgentExecutionResult(agent="qa", command=["mock"], exit_code=0, stdout=f"```json\n{out}\n```", stderr="", duration_ms=5.0, success=True)

        with patch.object(real_rt, "execute", side_effect=fake_qa):
            qa_run = service.execute_qa_inspection_task(
                qa_task.id,
                project_id="proj_17",
                code_patch_artifact_id=patch_art.id,
                target_repo_root=target_repo,
            )
        assert qa_run.status == RunStatus.SUCCESS.value
        assert len(seen_ws) == 1
        assert not seen_ws[0].exists()

    def test_qa_14b_uses_configurable_verification_timeout_not_hardcoded_30s(self, tmp_path: Path):
        target_repo = tmp_path / "TargetApp"
        head = _init_git_repo(
            target_repo,
            {
                "calc.py": "def f():\n    return 1\n",
                "tests/test_calc.py": "from calc import f\ndef test_f():\n    assert f() == 1\n",
            },
        )
        runs_dir = tmp_path / "runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=target_repo)
        service.create_project("proj_t", "Timeout Test")

        prod_f = runs_dir / "prod.md"
        prod_f.parent.mkdir(parents=True, exist_ok=True)
        prod_f.write_text("# Spec\nREQ-1\n", encoding="utf-8")
        plan_f = runs_dir / "plan.md"
        plan_f.write_text("# Plan\n", encoding="utf-8")
        patch_f = runs_dir / "patch.diff"
        patch_f.write_text(
            "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 1  # ok\n",
            encoding="utf-8",
        )
        qarep_f = runs_dir / "qarep.md"
        qarep_f.write_text("# QA\n", encoding="utf-8")

        prod_task = service.create_task("proj_t", "Prod", "Spec", required_roles=["product"])
        prod_run = prod_task.create_run()
        prod_art = Artifact(id="art_pt", run_id=prod_run.id, name="prod.md", path="prod.md", artifact_type=ArtifactType.SPECIFICATION.value, producer_role="product", sha256=hashlib.sha256(prod_f.read_bytes()).hexdigest(), durable=True)
        prod_run.artifacts.append(prod_art)
        prod_run.complete(RunStatus.SUCCESS.value)
        prod_task.complete(TaskStatus.COMPLETED.value, "done")

        plan_task = service.create_task("proj_t", "Plan", "Plan", required_roles=["developer"])
        service.attach_input_artifact(plan_task.id, prod_art.id, project_id="proj_t")
        plan_run = plan_task.create_run()
        plan_art = Artifact(id="art_dt", run_id=plan_run.id, name="plan.md", path="plan.md", artifact_type=ArtifactType.DEVELOPER_PLAN_REPORT.value, producer_role="developer", sha256=hashlib.sha256(plan_f.read_bytes()).hexdigest(), durable=True)
        patch_art = Artifact(id="art_ct", run_id=plan_run.id, name="patch.diff", path="patch.diff", artifact_type=ArtifactType.CODE_PATCH.value, producer_role="developer", sha256=hashlib.sha256(patch_f.read_bytes()).hexdigest(), durable=True, metadata={"base_commit_hash": head, "changed_files": ["calc.py"], "plan_artifact_id": plan_art.id, "plan_sha256": plan_art.sha256, "verification_outcomes": [{"status": "PASS", "exit_code": 0}]})
        qarep_art = Artifact(id="art_qt", run_id=plan_run.id, name="qarep.md", path="qarep.md", artifact_type=ArtifactType.QA_REPORT.value, producer_role="qa", sha256=hashlib.sha256(qarep_f.read_bytes()).hexdigest(), durable=True, metadata={"code_patch_artifact_id": patch_art.id, "code_patch_sha256": patch_art.sha256, "product_artifact_id": prod_art.id, "developer_plan_artifact_id": plan_art.id, "base_commit_hash": head, "recommended_verification_actions": [{"action_type": "pytest", "target": "tests/test_calc.py", "purpose": "test"}]})
        plan_run.artifacts.extend([plan_art, patch_art, qarep_art])
        plan_run.complete(RunStatus.SUCCESS.value)
        plan_task.complete(TaskStatus.COMPLETED.value, "done")

        qa_task = service.create_task("proj_t", "QA 14B", "Verify", required_roles=["qa"])
        for aid in (prod_art.id, plan_art.id, patch_art.id, qarep_art.id):
            service.attach_input_artifact(qa_task.id, aid, project_id="proj_t")

        recorded_timeouts: list[float] = []

        def fake_exec_verif(action, worktree_path, timeout=30.0, sanitized_env=None):
            recorded_timeouts.append(timeout)
            return VerificationExecutionResult(action=action, status="PASS", exit_code=0, stdout="1 passed", stderr="", duration_ms=10)

        verdict_json = json.dumps({
            "schema_version": "1.0",
            "verdict": "PASS",
            "summary": "All passed",
            "requirements_evaluations": [{"requirement_id": "REQ-1", "status": "SATISFIED", "evidence": "ok"}],
            "blocking_issues": [],
            "release_recommendation": "APPROVE",
        })

        with patch("jester_ai_company.service.execute_verification_action", side_effect=fake_exec_verif), patch.object(
            service.runtime,
            "execute",
            return_value=AgentExecutionResult(agent="qa", command=["mock"], exit_code=0, stdout=f"```json\n{verdict_json}\n```", stderr="", duration_ms=5.0, success=True),
        ):
            qa_run = service.execute_qa_verification_task(
                qa_task.id,
                project_id="proj_t",
                target_repo_root=target_repo,
                verification_timeout=240.0,
            )

        assert qa_run.status == RunStatus.SUCCESS.value
        assert recorded_timeouts == [240.0]
        qa_exec_arts = [a for a in qa_run.artifacts if a.artifact_type == ArtifactType.QA_EXECUTION_REPORT.value]
        assert len(qa_exec_arts) == 1
        assert qa_exec_arts[0].metadata.get("verification_actions_executed") == 1


# ==============================================================================
# DEF-021 (AUDIT-ADV-01): CEO JSON Cannot Self-Authorize Direct Developer
# ==============================================================================

class TestDEF021CEOSelfAuthorizationBlocked:

    def test_audit_adv_01_untrusted_ceo_json_cannot_self_authorize_direct_developer(self):
        obj = CompanyObjective(id="obj_adv1", title="Build payment module", description="Add Stripe billing")
        untrusted_plan = json.dumps({
            "schema_version": "1.0",
            "version": 1,
            "objective_id": "obj_adv1",
            "allow_direct_developer": True,
            "task_category": "BUG_FIX",
            "work_items": [
                {"work_item_id": "wi_dev", "role": "developer", "objective": "Write payment code directly", "depends_on": []}
            ],
        })
        with pytest.raises(DAGValidationError):
            parse_and_validate_ceo_plan(untrusted_plan, obj, team_selection=None)

    def test_selected_roles_not_mutated_in_place(self):
        obj = CompanyObjective(id="obj_imm", title="Research & Marketing", description="Analyze market")
        ts = TeamSelectionResult(
            task_category=TaskCategory.RESEARCH.value,
            complexity="LOW",
            uncertainty="LOW",
            risk="LOW",
            required_capabilities=["research"],
            selected_roles=["research"],
            role_requirements={"research": "REQUIRED"},
            omitted_roles_rationale={},
            selection_reasoning="Research task",
            escalation_conditions=[],
            estimated_specialist_count=1,
            actual_specialist_count=1,
            allow_direct_developer=False,
            enforce_strict_roles=False,
        )
        plan_json = json.dumps({
            "schema_version": "1.0",
            "version": 1,
            "objective_id": "obj_imm",
            "work_items": [
                {"work_item_id": "wi_1", "role": "research", "objective": "Research", "depends_on": []},
                {"work_item_id": "wi_2", "role": "marketing", "objective": "Positioning", "depends_on": ["wi_1"]},
            ],
        })
        parse_and_validate_ceo_plan(plan_json, obj, team_selection=ts)
        # Caller's team_selection.selected_roles MUST NOT be mutated in place!
        assert ts.selected_roles == ["research"]


# ==============================================================================
# DEF-027: DeveloperTaskResult verification_actions & recovery.py Fixes
# ==============================================================================

class TestDEF027DeveloperVerificationActionsAndRecovery:

    def test_developer_result_parses_typed_verification_actions_and_rejects_injection(self):
        good_json = json.dumps({
            "schema_version": "1.0",
            "status": "completed",
            "summary": "Planned feature",
            "implementation_plan": ["Step 1"],
            "files_to_modify": [{"path": "app.py", "description": "Update"}],
            "verification_actions": [
                {"action_type": "pytest", "target": "tests/test_app.py"},
                {"action_type": "frontend_build", "target": "frontend"},
            ],
        })
        res = parse_and_validate_developer_result(good_json)
        assert len(res.verification_actions) == 2
        assert res.verification_actions[0].action_type == "pytest"
        assert res.to_dict()["verification_actions"][1] == {"action_type": "frontend_build", "target": "frontend"}

        bad_json = json.dumps({
            "schema_version": "1.0",
            "status": "completed",
            "summary": "Planned feature",
            "implementation_plan": ["Step 1"],
            "verification_actions": [
                {"action_type": "pytest", "target": "tests/test_app.py; rm -rf /"},
            ],
        })
        with pytest.raises(DeveloperResultValidationError):
            parse_and_validate_developer_result(bad_json)

    def test_recovery_generic_timeout_triggers_retry_while_exploration_triggers_replan(self):
        generic = classify_specialist_failure(
            role="research",
            work_item_id="wi_1",
            error_message="Subprocess timed out after 300s",
            timed_out=True,
            attempt_number=1,
            max_retries=1,
        )
        assert generic.failure_category == FailureCategory.TIMEOUT.value
        assert generic.recovery_decision == RecoveryDecision.RETRY.value
        assert generic.is_exploration_timeout is False

        exploration = classify_specialist_failure(
            role="research",
            work_item_id="wi_1",
            stdout="Executed 100 steps in excessive exploration loop",
            error_message="Subprocess timed out",
            timed_out=True,
            attempt_number=1,
            max_retries=1,
        )
        assert exploration.recovery_decision == RecoveryDecision.REPLAN.value
        assert exploration.is_exploration_timeout is True

    def test_evaluate_acceptance_criteria_blocks_substring_spoofing_and_empty_hash(self):
        # 'app.py' must NOT falsely match 'not_app.py' via naive substring!
        all_met, met, unmet = evaluate_acceptance_criteria(
            mandatory_criteria=["Must produce not_app.py"],
            satisfied_criteria=[],
            preserved_artifacts=[{"name": "app.py", "path": "app.py", "sha256": "abc123"}],
        )
        assert all_met is False
        assert unmet == ["Must produce not_app.py"]

        # Artifact with explicitly empty sha256 must NOT satisfy mandatory criterion!
        all_met2, _, unmet2 = evaluate_acceptance_criteria(
            mandatory_criteria=["Must produce report.md"],
            satisfied_criteria=[],
            preserved_artifacts=[{"name": "report.md", "path": "report.md", "sha256": ""}],
        )
        assert all_met2 is False
        assert unmet2 == ["Must produce report.md"]

        # Valid boundary filename match with non-empty sha256 succeeds
        all_met3, met3, unmet3 = evaluate_acceptance_criteria(
            mandatory_criteria=["Must produce report.md"],
            satisfied_criteria=[],
            preserved_artifacts=[{"name": "report.md", "path": "report.md", "sha256": "deadbeef"}],
        )
        assert all_met3 is True
        assert met3 == ["Must produce report.md"]
        assert unmet3 == []
