"""Stage 0B + Stage 0B-polish Security, Authority Model, Concurrency, Tool Hook,
Execution Policy Coverage, Repair Isolation & Test Infrastructure Suite.

All tests in this file run 100% offline in isolated temporary directories / Git repositories.
They NEVER touch real Desktop/Jester, NEVER delete historical .runs/ data, and NEVER call live agy.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from jester_ai_company.authority import (
    AuthorityExpiredError,
    AuthorityLevel,
    AuthorityRegistry,
    AuthorityReplayError,
    AuthorityTypeMismatchError,
    ForgedApprovalError,
    FounderAuthenticationRequiredError,
    FounderDecision,
    FounderDecisionType,
    FounderSessionAuthenticator,
    PROVENANCE_UNVERIFIED_STRUCTURAL,
    PROVENANCE_VERIFIED_SESSION_BOUND,
    ProtectedOperationGrant,
    ProtectedOperationType,
    SandboxExecutionToken,
    ScopeExpansionForbiddenError,
    StaleRepositoryHeadError,
    create_authenticated_founder_decision,
    derive_protected_operation_grant,
    issue_sandbox_execution_token,
    verify_and_consume_protected_operation_grant,
    verify_and_consume_sandbox_token,
    verify_protected_operation_grant,
    verify_sandbox_token_for_worktree,
)
from jester_ai_company.core import Artifact, ArtifactType, RunStatus, TaskStatus
from jester_ai_company.execution_grant import ExecutionGrant
from jester_ai_company.orchestrator import CompanyObjective
from jester_ai_company.policy_hook import (
    install_execution_policy_hook,
    install_readonly_policy_hook,
)
from jester_ai_company.runtime import AgentExecutionResult, AntigravityRuntime
from jester_ai_company.service import CompanyService
from jester_ai_company.worktree import resolve_repo_head_commit, run_git


# ==============================================================================
# Helpers
# ==============================================================================

def _init_git_repo(repo_dir: Path, files: dict[str, str] | None = None) -> str:
    repo_dir.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "test@jester.local"],
        ["config", "user.name", "Stage0B Tester"],
    ):
        run_git(args, cwd=repo_dir)
    for rel, content in (files or {"app.py": "def add(a, b):\n    return a - b\n"}).items():
        fpath = repo_dir / rel
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content, encoding="utf-8")
    run_git(["add", "."], cwd=repo_dir)
    run_git(["commit", "-m", "initial commit"], cwd=repo_dir)
    return resolve_repo_head_commit(repo_dir)


def _run_hook_script(hook_py: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(hook_py)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"Hook script crashed: stderr={proc.stderr}"
    return json.loads(proc.stdout)


def _sample_sha(label: str = "sample") -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


# ==============================================================================
# 1. Authority Model (2A) & FounderDecision Cryptographic Provenance (0B-polish)
# ==============================================================================

class TestAuthorityModelStage0B:

    @pytest.mark.parametrize(
        "synthetic_id",
        [
            "founder_grant_crun_1234",
            "founder_repair_1_crun_1234",
            "founder_ui_9999",
            "auto_approved_1",
            "synthetic_123",
            "mock_founder_01",
        ],
    )
    def test_execution_grant_rejects_synthetic_founder_approval_ids(self, synthetic_id: str):
        with pytest.raises(ForgedApprovalError):
            ExecutionGrant(
                grant_id="grant_synth",
                task_id="task_1",
                plan_artifact_id="art_plan_1",
                plan_sha256=_sample_sha("plan"),
                base_commit_hash="a" * 40,
                approved_files_to_modify=("app.py",),
                founder_approval_id=synthetic_id,
            )

    def test_sandbox_execution_token_valid_on_execution_grant_without_founder_id(self):
        plan_sha = _sample_sha("plan")
        token = issue_sandbox_execution_token(
            run_id="crun_1",
            task_id="task_1",
            base_commit_hash="a" * 40,
            plan_artifact_id="art_plan_1",
            plan_sha256=plan_sha,
            approved_files_to_modify=("app.py",),
        )
        grant = ExecutionGrant(
            grant_id="grant_sbx_1",
            task_id="task_1",
            plan_artifact_id="art_plan_1",
            plan_sha256=plan_sha,
            base_commit_hash="a" * 40,
            approved_files_to_modify=("app.py",),
            sandbox_token=token,
        )
        assert grant.founder_approval_id == ""
        assert grant.sandbox_token_id == token.token_id
        assert grant.authority_level == AuthorityLevel.SANDBOX_EXECUTION.value

    def test_sandbox_token_cannot_target_real_repo_or_reuse_across_runs_or_workspaces(self, tmp_path: Path):
        real_repo = tmp_path / "real_repo"
        wt1 = tmp_path / "wt1"
        wt2 = tmp_path / "wt2"
        real_repo.mkdir()
        wt1.mkdir()
        wt2.mkdir()
        reg = AuthorityRegistry(tmp_path / "authority_registry.json")
        token = issue_sandbox_execution_token(
            run_id="crun_1",
            task_id="task_1",
            base_commit_hash="a" * 40,
            plan_artifact_id="art_1",
            plan_sha256=_sample_sha("plan"),
            approved_files_to_modify=("app.py",),
            worktree_path=str(wt1),
        )

        # Real repo root -> blocked
        with pytest.raises(ScopeExpansionForbiddenError):
            verify_sandbox_token_for_worktree(
                token, worktree_root=real_repo, real_repo_root=real_repo, requested_files=("app.py",)
            )

        # Wrong run_id -> blocked
        with pytest.raises(ScopeExpansionForbiddenError):
            verify_sandbox_token_for_worktree(
                token, worktree_root=wt1, real_repo_root=real_repo, run_id="crun_OTHER", requested_files=("app.py",)
            )

        # Wrong worktree -> blocked
        with pytest.raises(ScopeExpansionForbiddenError):
            verify_sandbox_token_for_worktree(
                token, worktree_root=wt2, real_repo_root=real_repo, run_id="crun_1", requested_files=("app.py",)
            )

        # Legitimate single-use consumption succeeds once...
        verify_and_consume_sandbox_token(
            token,
            worktree_root=wt1,
            real_repo_root=real_repo,
            registry=reg,
            requested_files=("app.py",),
            run_id="crun_1",
            task_id="task_1",
            plan_artifact_id="art_1",
        )
        # ...and replaying the same SandboxExecutionToken MUST fail!
        with pytest.raises(AuthorityReplayError):
            verify_and_consume_sandbox_token(
                token,
                worktree_root=wt1,
                real_repo_root=real_repo,
                registry=reg,
                requested_files=("app.py",),
                run_id="crun_1",
                task_id="task_1",
                plan_artifact_id="art_1",
            )

    def test_expired_sandbox_token_rejected(self):
        plan_sha = _sample_sha("plan")
        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        expired_token = SandboxExecutionToken(
            token_id="sbx_expired000001",
            run_id="crun_1",
            task_id="task_1",
            base_commit_hash="a" * 40,
            plan_artifact_id="art_1",
            plan_sha256=plan_sha,
            approved_files_to_modify=("app.py",),
            created_at=(datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(),
            expires_at=past,
        )
        with pytest.raises(AuthorityExpiredError):
            ExecutionGrant(
                grant_id="grant_exp",
                task_id="task_1",
                plan_artifact_id="art_1",
                plan_sha256=plan_sha,
                base_commit_hash="a" * 40,
                approved_files_to_modify=("app.py",),
                sandbox_token=expired_token,
            )

    def test_founder_decision_structural_strings_alone_do_not_prove_authentication(self, tmp_path: Path):
        """Well-formed actor, session ID, and SHA-256 MUST NOT authorize a protected operation."""
        auth = FounderSessionAuthenticator()
        prop_sha = _sample_sha("prop")

        # 1. Constructing a structurally valid FounderDecision without server authenticator
        unverified = create_authenticated_founder_decision(
            decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
            run_id="crun_1",
            subject_artifact_id="prop_1",
            subject_sha256=prop_sha,
            actor="Founder",
            auth_session_id="well_formed_fake_session_123456",
        )
        assert unverified.provenance_status == PROVENANCE_UNVERIFIED_STRUCTURAL
        assert not unverified.is_cryptographically_authenticated

        # 2. Attempting to derive ProtectedOperationGrant with unverified decision MUST fail closed
        with pytest.raises(FounderAuthenticationRequiredError):
            derive_protected_operation_grant(
                decision=unverified,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                proposal_id="prop_1",
                proposal_sha256=prop_sha,
                target_repository_root=str(tmp_path),
                target_branch="main",
                expected_head_hash="a" * 40,
                code_patch_artifact_id="art_patch_1",
                code_patch_sha256=_sample_sha("patch"),
                qa_execution_report_artifact_id="art_qa_1",
                qa_execution_report_sha256=_sample_sha("qa"),
                expected_changed_files=("app.py",),
                authenticator=auth,
            )

        # 3. Attempting to forge a 64-hex session_proof and claim VERIFIED_SESSION_BOUND MUST fail closed
        sid = auth.issue_session("Founder")
        forged_proof_decision = FounderDecision(
            decision_id="fdec_forgedproof01",
            decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL.value,
            run_id="crun_1",
            subject_artifact_id="prop_1",
            subject_sha256=prop_sha,
            actor="Founder",
            auth_session_id=sid,
            nonce="nonce_1234567890abcdef",
            session_proof="f" * 64,
            provenance_status=PROVENANCE_VERIFIED_SESSION_BOUND,
        )
        with pytest.raises(ForgedApprovalError):
            derive_protected_operation_grant(
                decision=forged_proof_decision,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                proposal_id="prop_1",
                proposal_sha256=prop_sha,
                target_repository_root=str(tmp_path),
                target_branch="main",
                expected_head_hash="a" * 40,
                code_patch_artifact_id="art_patch_1",
                code_patch_sha256=_sample_sha("patch"),
                qa_execution_report_artifact_id="art_qa_1",
                qa_execution_report_sha256=_sample_sha("qa"),
                expected_changed_files=("app.py",),
                authenticator=auth,
            )

        # 4. Revoked session MUST be rejected fail-closed even with previously signed proof
        signed = create_authenticated_founder_decision(
            decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
            run_id="crun_1",
            subject_artifact_id="prop_1",
            subject_sha256=prop_sha,
            actor="Founder",
            auth_session_id=sid,
            authenticator=auth,
        )
        assert signed.provenance_status == PROVENANCE_VERIFIED_SESSION_BOUND
        auth.revoke_session(sid)
        with pytest.raises(FounderAuthenticationRequiredError):
            auth.verify_decision(signed)

    def test_founder_decision_blocks_unauthenticated_and_system_actors(self):
        prop_sha = _sample_sha("prop")
        with pytest.raises(FounderAuthenticationRequiredError):
            create_authenticated_founder_decision(
                decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
                run_id="crun_1",
                subject_artifact_id="prop_1",
                subject_sha256=prop_sha,
                actor="system",
                auth_session_id="sess_1234567890abcdef",
            )
        with pytest.raises(FounderAuthenticationRequiredError):
            create_authenticated_founder_decision(
                decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
                run_id="crun_1",
                subject_artifact_id="prop_1",
                subject_sha256=prop_sha,
                actor="Founder",
                auth_session_id="short",
            )

    def test_privilege_escalation_sandbox_token_cannot_authorize_protected_operation(self, tmp_path: Path):
        auth = FounderSessionAuthenticator()
        token = issue_sandbox_execution_token(
            run_id="crun_1",
            task_id="task_1",
            base_commit_hash="a" * 40,
            plan_artifact_id="art_1",
            plan_sha256=_sample_sha("plan"),
            approved_files_to_modify=("app.py",),
        )
        with pytest.raises(AuthorityTypeMismatchError):
            derive_protected_operation_grant(
                decision=token,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                proposal_id="prop_1",
                proposal_sha256=_sample_sha("prop"),
                target_repository_root=str(tmp_path),
                target_branch="main",
                expected_head_hash="a" * 40,
                code_patch_artifact_id="art_patch_1",
                code_patch_sha256=_sample_sha("patch"),
                qa_execution_report_artifact_id="art_qa_1",
                qa_execution_report_sha256=_sample_sha("qa"),
                expected_changed_files=("app.py",),
                authenticator=auth,
            )
        with pytest.raises(AuthorityTypeMismatchError):
            verify_protected_operation_grant(
                token,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                target_repository_root=tmp_path,
                current_head_hash="a" * 40,
                requested_files=("app.py",),
                authenticator=auth,
            )

    def test_privilege_confusion_wrong_founder_decision_type_or_direct_execution_blocked(self, tmp_path: Path):
        auth = FounderSessionAuthenticator()
        sid = auth.issue_session("Founder")
        clarification = create_authenticated_founder_decision(
            decision_type=FounderDecisionType.CLARIFICATION,
            run_id="crun_1",
            subject_artifact_id="prop_1",
            subject_sha256=_sample_sha("prop"),
            actor="Founder",
            auth_session_id=sid,
            authenticator=auth,
        )
        with pytest.raises(AuthorityTypeMismatchError):
            derive_protected_operation_grant(
                decision=clarification,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                proposal_id="prop_1",
                proposal_sha256=_sample_sha("prop"),
                target_repository_root=str(tmp_path),
                target_branch="main",
                expected_head_hash="a" * 40,
                code_patch_artifact_id="art_patch_1",
                code_patch_sha256=_sample_sha("patch"),
                qa_execution_report_artifact_id="art_qa_1",
                qa_execution_report_sha256=_sample_sha("qa"),
                expected_changed_files=("app.py",),
                authenticator=auth,
            )
        approval = create_authenticated_founder_decision(
            decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
            run_id="crun_1",
            subject_artifact_id="prop_1",
            subject_sha256=_sample_sha("prop"),
            actor="Founder",
            auth_session_id=sid,
            authenticator=auth,
        )
        with pytest.raises(AuthorityTypeMismatchError):
            verify_protected_operation_grant(
                approval,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                target_repository_root=tmp_path,
                current_head_hash="a" * 40,
                requested_files=("app.py",),
                authenticator=auth,
            )

    def test_protected_grant_enforces_expiry_replay_stale_head_and_scope_expansion(self, tmp_path: Path):
        auth = FounderSessionAuthenticator()
        sid = auth.issue_session("Founder")
        prop_sha = _sample_sha("prop")
        decision = create_authenticated_founder_decision(
            decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
            run_id="crun_1",
            subject_artifact_id="prop_1",
            subject_sha256=prop_sha,
            actor="Founder",
            auth_session_id=sid,
            authenticator=auth,
        )
        grant = derive_protected_operation_grant(
            decision=decision,
            operation_type=ProtectedOperationType.REAL_REPO_APPLY,
            proposal_id="prop_1",
            proposal_sha256=prop_sha,
            target_repository_root=str(tmp_path),
            target_branch="main",
            expected_head_hash="a" * 40,
            code_patch_artifact_id="art_patch_1",
            code_patch_sha256=_sample_sha("patch"),
            qa_execution_report_artifact_id="art_qa_1",
            qa_execution_report_sha256=_sample_sha("qa"),
            expected_changed_files=("app.py",),
            authenticator=auth,
            ttl_seconds=60,
        )
        reg_file = tmp_path / "authority_registry.json"
        registry = AuthorityRegistry(reg_file)

        # Stale HEAD rejected
        with pytest.raises(StaleRepositoryHeadError):
            verify_protected_operation_grant(
                grant,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                target_repository_root=tmp_path,
                current_head_hash="b" * 40,
                requested_files=("app.py",),
                registry=registry,
                authenticator=auth,
            )

        # Scope expansion (extra file) rejected
        with pytest.raises(ScopeExpansionForbiddenError):
            verify_protected_operation_grant(
                grant,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                target_repository_root=tmp_path,
                current_head_hash="a" * 40,
                requested_files=("app.py", "evil.py"),
                registry=registry,
                authenticator=auth,
            )

        # Operation type expansion (GIT_PUSH vs REAL_REPO_APPLY) rejected
        with pytest.raises(ScopeExpansionForbiddenError):
            verify_protected_operation_grant(
                grant,
                operation_type=ProtectedOperationType.GIT_PUSH,
                target_repository_root=tmp_path,
                current_head_hash="a" * 40,
                requested_files=("app.py",),
                registry=registry,
                authenticator=auth,
            )

        # Expired grant rejected
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        with pytest.raises(AuthorityExpiredError):
            verify_protected_operation_grant(
                grant,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                target_repository_root=tmp_path,
                current_head_hash="a" * 40,
                requested_files=("app.py",),
                registry=registry,
                authenticator=auth,
                now=future,
            )

        # Atomic verify+consume once, then reload durable registry and verify replay blocked
        verify_and_consume_protected_operation_grant(
            grant,
            operation_type=ProtectedOperationType.REAL_REPO_APPLY,
            target_repository_root=tmp_path,
            current_head_hash="a" * 40,
            requested_files=("app.py",),
            registry=registry,
            authenticator=auth,
        )
        reloaded = AuthorityRegistry(reg_file)
        with pytest.raises(AuthorityReplayError):
            verify_protected_operation_grant(
                grant,
                operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                target_repository_root=tmp_path,
                current_head_hash="a" * 40,
                requested_files=("app.py",),
                registry=reloaded,
                authenticator=auth,
            )

    def test_authority_registry_thread_concurrency_atomic_single_consume(self, tmp_path: Path):
        """12 concurrent threads racing on the same ProtectedOperationGrant -> EXACTLY 1 succeeds."""
        auth = FounderSessionAuthenticator()
        sid = auth.issue_session("Founder")
        prop_sha = _sample_sha("prop_race")
        decision = create_authenticated_founder_decision(
            decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
            run_id="crun_race",
            subject_artifact_id="prop_race",
            subject_sha256=prop_sha,
            actor="Founder",
            auth_session_id=sid,
            authenticator=auth,
        )
        grant = derive_protected_operation_grant(
            decision=decision,
            operation_type=ProtectedOperationType.REAL_REPO_APPLY,
            proposal_id="prop_race",
            proposal_sha256=prop_sha,
            target_repository_root=str(tmp_path),
            target_branch="main",
            expected_head_hash="a" * 40,
            code_patch_artifact_id="art_patch",
            code_patch_sha256=_sample_sha("patch"),
            qa_execution_report_artifact_id="art_qa",
            qa_execution_report_sha256=_sample_sha("qa"),
            expected_changed_files=("app.py",),
            authenticator=auth,
        )
        reg_file = tmp_path / "race_registry.json"

        def worker(_idx: int) -> str:
            # Deliberately instantiate a separate AuthorityRegistry per thread on the same path
            reg = AuthorityRegistry(reg_file)
            try:
                verify_and_consume_protected_operation_grant(
                    grant,
                    operation_type=ProtectedOperationType.REAL_REPO_APPLY,
                    target_repository_root=tmp_path,
                    current_head_hash="a" * 40,
                    requested_files=("app.py",),
                    registry=reg,
                    authenticator=auth,
                )
                return "CONSUMED"
            except AuthorityReplayError:
                return "REPLAY_BLOCKED"

        with ThreadPoolExecutor(max_workers=12) as pool:
            outcomes = list(pool.map(worker, range(12)))

        assert outcomes.count("CONSUMED") == 1
        assert outcomes.count("REPLAY_BLOCKED") == 11
        persisted = json.loads(reg_file.read_text(encoding="utf-8"))
        assert grant.grant_id in persisted
        assert grant.founder_decision_id in persisted

    def test_authority_registry_cross_process_concurrency_atomic_single_consume(self, tmp_path: Path):
        """6 independent OS Python processes racing on the same registry file -> EXACTLY 1 succeeds."""
        reg_file = tmp_path / "mp_registry.json"
        worker_script = tmp_path / "mp_worker.py"
        repo_root = Path(__file__).resolve().parent.parent
        worker_script.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(repo_root)!r})\n"
            "from jester_ai_company.authority import AuthorityRegistry, AuthorityReplayError\n"
            "reg = AuthorityRegistry(Path(sys.argv[1]))\n"
            "try:\n"
            "    reg.consume_once(['pog_cross_proc_key', 'fdec_cross_proc_key'], {'worker': sys.argv[2]})\n"
            "    print('CONSUMED')\n"
            "except AuthorityReplayError:\n"
            "    print('REPLAY_BLOCKED')\n",
            encoding="utf-8",
        )
        procs = [
            subprocess.Popen(
                [sys.executable, str(worker_script), str(reg_file), str(i)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for i in range(6)
        ]
        results = []
        for p in procs:
            out, err = p.communicate(timeout=30)
            assert p.returncode == 0, f"Child process failed: stderr={err}"
            results.append(out.strip())

        assert results.count("CONSUMED") == 1
        assert results.count("REPLAY_BLOCKED") == 5
        persisted = json.loads(reg_file.read_text(encoding="utf-8"))
        assert "pog_cross_proc_key" in persisted
        assert "fdec_cross_proc_key" in persisted

    def test_service_end_to_end_protected_real_repo_apply_and_anti_replay(self, tmp_path: Path):
        target_repo = tmp_path / "target_repo"
        head = _init_git_repo(target_repo, {"greeter.py": "def greet():\n    return 'old'\n"})
        runs_dir = tmp_path / "runs"
        service = CompanyService(output_dir=str(runs_dir), repo_root=target_repo)
        service.create_project("proj_auth", "Auth Test Project")
        task = service.create_task("proj_auth", "Fix greeter", "Return new", required_roles=["developer"])
        run = task.create_run()
        run.status = RunStatus.SUCCESS.value

        patch_text = (
            "diff --git a/greeter.py b/greeter.py\n"
            "--- a/greeter.py\n"
            "+++ b/greeter.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def greet():\n"
            "-    return 'old'\n"
            "+    return 'new'\n"
        )
        patch_file = runs_dir / "patch_v1.diff"
        patch_file.parent.mkdir(parents=True, exist_ok=True)
        patch_file.write_text(patch_text, encoding="utf-8")
        patch_sha = hashlib.sha256(patch_file.read_bytes()).hexdigest()

        qa_rep_file = runs_dir / "qa_report.md"
        qa_rep_file.write_text("# QA Report\n", encoding="utf-8")
        qa_rep_sha = hashlib.sha256(qa_rep_file.read_bytes()).hexdigest()

        qa_exec_file = runs_dir / "qa_exec.md"
        qa_exec_file.write_text("# QA Exec PASS\n", encoding="utf-8")
        qa_exec_sha = hashlib.sha256(qa_exec_file.read_bytes()).hexdigest()

        patch_art = Artifact(
            id="art_patch_1",
            run_id=run.id,
            name="patch_v1.diff",
            path="patch_v1.diff",
            artifact_type=ArtifactType.CODE_PATCH.value,
            producer_role="developer",
            sha256=patch_sha,
            durable=True,
            metadata={
                "base_commit_hash": head,
                "changed_files": ["greeter.py"],
                "verification_outcomes": [{"status": "PASS", "passed": True, "exit_code": 0}],
                "patch_version": 1,
            },
        )
        qa_rep_art = Artifact(
            id="art_qarep_1",
            run_id=run.id,
            name="qa_report.md",
            path="qa_report.md",
            artifact_type=ArtifactType.QA_REPORT.value,
            producer_role="qa",
            sha256=qa_rep_sha,
            durable=True,
        )
        qa_exec_art = Artifact(
            id="art_qaexec_1",
            run_id=run.id,
            name="qa_exec.md",
            path="qa_exec.md",
            artifact_type=ArtifactType.QA_EXECUTION_REPORT.value,
            producer_role="qa",
            sha256=qa_exec_sha,
            durable=True,
            metadata={
                "verdict": "PASS",
                "code_patch_artifact_id": patch_art.id,
                "code_patch_sha256": patch_sha,
                "qa_report_artifact_id": qa_rep_art.id,
            },
        )
        run.artifacts.extend([patch_art, qa_rep_art, qa_exec_art])
        task.complete(status=TaskStatus.COMPLETED.value, summary="done")

        proposal = service.prepare_real_repo_apply(
            target_repo_root=target_repo,
            code_patch_artifact_id=patch_art.id,
            qa_execution_report_artifact_id=qa_exec_art.id,
        )

        # Unregistered session_id string MUST fail closed at record_founder_decision
        with pytest.raises(FounderAuthenticationRequiredError):
            service.record_founder_decision(
                decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
                run_id="crun_1",
                subject_artifact_id=proposal.proposal_id,
                subject_sha256=proposal.proposal_sha256,
                actor="Founder",
                auth_session_id="unregistered_but_long_session_id_1234",
            )

        # SandboxExecutionToken cannot be passed to approve or execute real repo apply
        sbx = issue_sandbox_execution_token(
            run_id="crun_1",
            task_id=task.id,
            base_commit_hash=head,
            plan_artifact_id="art_plan",
            plan_sha256=_sample_sha("plan"),
            approved_files_to_modify=("greeter.py",),
        )
        with pytest.raises(AuthorityTypeMismatchError):
            service.approve_real_repo_apply(proposal.proposal_id, sbx)  # type: ignore[arg-type]
        with pytest.raises(AuthorityTypeMismatchError):
            service.execute_real_repo_apply(sbx)
        with pytest.raises(AuthorityTypeMismatchError):
            service.execute_real_repo_apply(sbx.token_id)

        # Server-issued authenticated session -> FounderDecision -> ProtectedOperationGrant -> Execute once
        session_id = service.issue_founder_session(actor="Founder")
        decision = service.record_founder_decision(
            decision_type=FounderDecisionType.PROTECTED_OPERATION_APPROVAL,
            run_id="crun_1",
            subject_artifact_id=proposal.proposal_id,
            subject_sha256=proposal.proposal_sha256,
            actor="Founder",
            auth_session_id=session_id,
        )
        assert decision.is_cryptographically_authenticated

        # FounderDecision alone cannot execute
        with pytest.raises(AuthorityTypeMismatchError):
            service.execute_real_repo_apply(decision)

        pgrant = service.authorize_protected_operation(
            proposal_id=proposal.proposal_id,
            founder_decision=decision,
        )
        res = service.execute_real_repo_apply(pgrant)
        assert res.status == "APPLIED_SUCCESSFULLY"
        assert "return 'new'" in (target_repo / "greeter.py").read_text(encoding="utf-8")

        # Replay of consumed ProtectedOperationGrant MUST fail
        with pytest.raises(AuthorityReplayError):
            service.execute_protected_real_repo_apply(pgrant)

    def test_engineering_pipeline_contains_no_fabricated_founder_approvals(self):
        pipeline_src = (
            Path(__file__).resolve().parent.parent
            / "jester_ai_company"
            / "engineering_pipeline.py"
        ).read_text(encoding="utf-8")
        assert "founder_grant_" not in pipeline_src
        assert "founder_repair_" not in pipeline_src


# ==============================================================================
# 2. Agent Tool Security (2B): Verified agy v1.3.6 Schemas, Quotas, Repeated
#    Edits to Created Files, Confinement, Fail-Closed Hooks
# ==============================================================================

class TestPolicyHookStage0B:

    def _make_grant(self, mod=("src/app.py",), create=("src/new_helper.py",), max_bytes=200, max_files=2):
        return ExecutionGrant(
            grant_id="grant_hook_0b",
            task_id="task_hook",
            plan_artifact_id="art_plan",
            plan_sha256=_sample_sha("plan"),
            base_commit_hash="a" * 40,
            approved_files_to_modify=tuple(mod),
            approved_files_to_create=tuple(create),
            allow_test_modifications=False,
            max_files_changed=max_files,
            max_bytes_written=max_bytes,
            founder_approval_id="test_explicit_approval_0b",
        )

    def test_verified_agy_schemas_read_write_edit_and_repeated_edit_on_created_file(self, tmp_path: Path):
        ws = tmp_path / "ws"
        (ws / "src").mkdir(parents=True)
        (ws / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        grant = self._make_grant(max_bytes=500, max_files=2)
        install_execution_policy_hook(ws, grant)
        hook_py = ws / ".agents" / "hook_policy.py"

        assert _run_hook_script(hook_py, {"toolCall": {"name": "read_file", "args": {"Path": "src\\app.py"}}})["decision"] == "allow"
        assert _run_hook_script(
            hook_py,
            {"toolCall": {"name": "edit_file", "args": {"Path": "src/app.py", "Target": "x = 1", "Replacement": "x = 2"}}},
        )["decision"] == "allow"
        assert _run_hook_script(
            hook_py,
            {"toolCall": {"name": "write_file", "args": {"Path": "./src/new_helper.py", "Content": "def h():\n    return 1\n"}}},
        )["decision"] == "allow"

        (ws / "src" / "new_helper.py").write_text("def h():\n    return 1\n", encoding="utf-8")
        assert _run_hook_script(
            hook_py,
            {"toolCall": {"name": "edit_file", "args": {"Path": "src\\new_helper.py", "Target": "return 1", "Replacement": "return 2"}}},
        )["decision"] == "allow"

    def test_wrong_runtime_schemas_denied_fail_closed(self, tmp_path: Path):
        ws = tmp_path / "ws"
        (ws / "src").mkdir(parents=True)
        (ws / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        grant = self._make_grant()
        install_execution_policy_hook(ws, grant)
        hook_py = ws / ".agents" / "hook_policy.py"

        assert _run_hook_script(
            hook_py, {"toolCall": {"name": "write_file", "args": {"TargetFile": "src/app.py", "Content": "x = 2"}}}
        )["decision"] == "deny"
        assert _run_hook_script(
            hook_py, {"toolCall": {"name": "edit_file", "args": {"Path": "src/new_helper.py", "Target": "a", "Replacement": "b"}}}
        )["decision"] == "deny"
        assert _run_hook_script(hook_py, {"toolCall": {"name": "read_file", "args": {}}})["decision"] == "deny"
        for bad_tool in ("run_command", "invoke_subagent", "call_mcp_tool", "swarm", "delete_file", "bash"):
            assert _run_hook_script(
                hook_py, {"toolCall": {"name": bad_tool, "args": {"CommandLine": "whoami"}}}
            )["decision"] == "deny"

    def test_writes_outside_worktree_and_secret_reads_denied(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside.py"
        outside.write_text("secret\n", encoding="utf-8")
        (ws / ".env").write_text("API_KEY=secret\n", encoding="utf-8")

        grant = self._make_grant(mod=("app.py",), create=())
        install_execution_policy_hook(ws, grant)
        hook_py = ws / ".agents" / "hook_policy.py"

        for escape_path in ("../outside.py", "..\\outside.py", str(outside), "\\\\server\\share\\evil.py"):
            assert _run_hook_script(
                hook_py, {"toolCall": {"name": "write_file", "args": {"Path": escape_path, "Content": "x"}}}
            )["decision"] == "deny"
            assert _run_hook_script(
                hook_py, {"toolCall": {"name": "read_file", "args": {"Path": escape_path}}}
            )["decision"] == "deny"
        assert _run_hook_script(hook_py, {"toolCall": {"name": "read_file", "args": {"Path": ".env"}}})["decision"] == "deny"

    def test_cumulative_byte_quota_and_file_limit_enforced_persistently(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.py").write_text("a\n", encoding="utf-8")
        (ws / "b.py").write_text("b\n", encoding="utf-8")
        grant = ExecutionGrant(
            grant_id="grant_quota",
            task_id="task_q",
            plan_artifact_id="art_q",
            plan_sha256=_sample_sha("plan"),
            base_commit_hash="a" * 40,
            approved_files_to_modify=("a.py", "b.py"),
            max_files_changed=2,
            max_bytes_written=20,
            founder_approval_id="test_explicit_approval_q",
        )
        install_execution_policy_hook(ws, grant)
        hook_py = ws / ".agents" / "hook_policy.py"

        assert _run_hook_script(
            hook_py, {"toolCall": {"name": "write_file", "args": {"Path": "a.py", "Content": "123456789012"}}}
        )["decision"] == "allow"
        res = _run_hook_script(
            hook_py, {"toolCall": {"name": "write_file", "args": {"Path": "b.py", "Content": "1234567890"}}}
        )
        assert res["decision"] == "deny"
        assert "cumulative write size" in res["reason"].lower()

        cfg_file = ws / ".agents" / "policy_config.json"
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
        cfg["max_bytes_written"] = 1000
        cfg["max_files_changed"] = 1
        cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
        res2 = _run_hook_script(
            hook_py, {"toolCall": {"name": "write_file", "args": {"Path": "b.py", "Content": "ok"}}}
        )
        assert res2["decision"] == "deny"
        assert "distinct modified files" in res2["reason"].lower()

    def test_missing_or_corrupt_policy_config_fails_closed(self, tmp_path: Path):
        ws = tmp_path / "ws"
        ws.mkdir()
        grant = self._make_grant()
        install_execution_policy_hook(ws, grant)
        hook_py = ws / ".agents" / "hook_policy.py"
        cfg_file = ws / ".agents" / "policy_config.json"

        cfg_file.write_text("{corrupt json", encoding="utf-8")
        assert _run_hook_script(hook_py, {"toolCall": {"name": "read_file", "args": {"Path": "src/app.py"}}})["decision"] == "deny"

        cfg_file.unlink()
        assert _run_hook_script(hook_py, {"toolCall": {"name": "read_file", "args": {"Path": "src/app.py"}}})["decision"] == "deny"

    def test_readonly_and_planning_hooks_deny_mutations_and_shell(self, tmp_path: Path):
        ws = tmp_path / "ro_ws"
        ws.mkdir()
        (ws / "README.md").write_text("# Docs\n", encoding="utf-8")
        install_readonly_policy_hook(ws)
        hook_py = ws / ".agents" / "hook_policy.py"

        assert _run_hook_script(hook_py, {"toolCall": {"name": "read_file", "args": {"Path": "README.md"}}})["decision"] == "allow"
        for denied_call in (
            {"name": "write_file", "args": {"Path": "README.md", "Content": "x"}},
            {"name": "edit_file", "args": {"Path": "README.md", "Target": "Docs", "Replacement": "Hacked"}},
            {"name": "run_command", "args": {"CommandLine": "echo hi"}},
            {"name": "send_message", "args": {"Recipient": "ceo", "Message": "hi"}},
            {"name": "invoke_subagent", "args": {"TypeName": "developer"}},
        ):
            assert _run_hook_script(hook_py, {"toolCall": denied_call})["decision"] == "deny"


# ==============================================================================
# 3. Complete DEF-006 Execution Policy Coverage & Repair Planning Isolation (2C)
# ==============================================================================

class TestExecutionPolicyCoverageStage0BPolish:
    """Proves NO CompanyService agent entry point bypasses its required PreToolUse policy."""

    def test_all_ceo_and_qa_14a_entry_points_enforce_readonly_policy_hook(self, tmp_path: Path):
        company_repo = tmp_path / "JesterAICompany"
        _init_git_repo(company_repo, {"engine.py": "ENGINE = True\n"})
        runs_dir = tmp_path / "runs"
        real_runtime = AntigravityRuntime(repo_root=company_repo)
        service = CompanyService(
            output_dir=str(runs_dir),
            repo_root=company_repo,
            runtime=real_runtime,
            is_production=True,
        )
        service.create_project("proj_cov", "Policy Coverage")

        observed_calls: list[dict] = []

        def fake_execute(agent, prompt, timeout=None, workspace_dir=None, env=None):
            assert workspace_dir is not None, f"Agent '{agent}' executed without isolated workspace!"
            ws = Path(workspace_dir).resolve()
            assert ws != company_repo.resolve(), f"Agent '{agent}' executed directly inside company repo!"
            hooks_file = ws / ".agents" / "hooks.json"
            cfg_file = ws / ".agents" / "policy_config.json"
            assert hooks_file.is_file(), f"Agent '{agent}' missing PreToolUse hooks.json!"
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            observed_calls.append({"agent": agent, "ws": ws, "mode": cfg.get("mode")})

            if agent == "qa":
                out = '```json\n{"schema_version":"1.0","status":"READY_FOR_QA_EXECUTION","summary":"ok","requirements_coverage":[],"recommended_verification_actions":[]}\n```'
            elif "CEOActionProposal" in prompt or "task_title" in prompt or '"action"' in prompt:
                out = '```json\n{"schema_version":"1.0","action":"PROPOSE_TASK","summary":"ok","proposed_task":{"title":"T","goal":"G","required_roles":["research"]}}\n```'
            elif "work_items" in prompt:
                out = '```json\n{"schema_version":"1.0","version":1,"objective_id":"obj_cov","plan_summary":"ok","work_items":[{"work_item_id":"wi_1","title":"R","objective":"Investigate authentication","role":"research","depends_on":[]}]}\n```'
            elif "selected_roles" in prompt:
                out = '```json\n{"schema_version":"1.0","task_category":"RESEARCH_ONLY","complexity":"LOW","uncertainty":"LOW","risk":"LOW","selected_roles":["research"],"rationale":"ok"}\n```'
            elif "decision" in prompt and "INVESTIGATE" in prompt:
                out = '```json\n{"schema_version":"1.0","decision":"EXECUTE","rationale":"ok","clarifying_questions":[]}\n```'
            else:
                out = "CEO acknowledged."
            return AgentExecutionResult(
                agent=agent, command=["mock"], exit_code=0, stdout=out, stderr="", duration_ms=5.0, timed_out=False, success=True
            )

        with patch.object(real_runtime, "execute", side_effect=fake_execute):
            # 1. CEO Chat
            service.send_chat_message("Hello CEO", sender_role="owner")
            # 2. CEO Task Proposal
            try:
                service.propose_task("Build feature X")
            except Exception:
                pass
            # 3. CEO Initial Company Plan
            obj = CompanyObjective(id="obj_cov", title="Research auth", description="Investigate authentication")
            service.propose_initial_company_plan(obj)
            # 4. CEO Team Selection (is_production=True)
            crun = service.create_company_run(obj)
            service.select_company_team(crun)
            # 5. QA 14A Inspection (_execute_qa_specialist_task)
            qa_task = service.create_task("proj_cov", "QA Inspect", "Inspect patch", required_roles=["qa"])
            service._execute_qa_specialist_task(qa_task, prompt="Inspect patch", lineage_metadata={}, timeout=30.0)

        assert len(observed_calls) >= 5
        for call in observed_calls:
            assert call["mode"] == "strict_read_only"
            # Ephemeral read-only workspaces must be cleaned up after each execution
            assert not call["ws"].exists()

    def test_qa_14b_verification_installs_readonly_hook_after_verification_commands(self, tmp_path: Path):
        target_repo = tmp_path / "TargetApp"
        head = _init_git_repo(
            target_repo,
            {
                "calc.py": "def inc(x):\n    return x + 1\n",
                "tests/test_calc.py": "from calc import inc\ndef test_inc():\n    assert inc(1) == 2\n",
            },
        )
        runs_dir = tmp_path / "runs"
        real_runtime = AntigravityRuntime(repo_root=target_repo)
        service = CompanyService(output_dir=str(runs_dir), repo_root=target_repo, runtime=real_runtime)
        service.create_project("proj_qa14b", "QA 14B Policy")
        prod_f = runs_dir / "prod.md"
        prod_f.parent.mkdir(parents=True, exist_ok=True)
        prod_f.write_text("# Product\nREQ-1: inc(x) returns x+1\n", encoding="utf-8")
        plan_f = runs_dir / "plan.md"
        plan_f.write_text("# Plan\nUpdate calc.py\n", encoding="utf-8")
        patch_f = runs_dir / "patch.diff"
        patch_f.write_text(
            "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def inc(x):\n-    return x + 1\n+    return x + 1  # verified\n",
            encoding="utf-8",
        )
        qarep_f = runs_dir / "qarep.md"
        qarep_f.write_text("# QA Inspection\n", encoding="utf-8")

        prod_task = service.create_task("proj_qa14b", "Prod", "Prod", required_roles=["product"])
        prod_run = prod_task.create_run()
        prod_run.status = RunStatus.SUCCESS.value
        prod_art = Artifact(id="art_p", run_id=prod_run.id, name="prod.md", path="prod.md", artifact_type=ArtifactType.SPECIFICATION.value, producer_role="product", sha256=hashlib.sha256(prod_f.read_bytes()).hexdigest(), durable=True)
        prod_run.artifacts.append(prod_art)
        prod_task.complete(status=TaskStatus.COMPLETED.value, summary="prod done")

        base_task = service.create_task("proj_qa14b", "Base", "Base", required_roles=["developer"])
        service.attach_input_artifact(base_task.id, prod_art.id, project_id="proj_qa14b")
        base_run = base_task.create_run()
        base_run.status = RunStatus.SUCCESS.value
        plan_art = Artifact(id="art_d", run_id=base_run.id, name="plan.md", path="plan.md", artifact_type=ArtifactType.DEVELOPER_PLAN_REPORT.value, producer_role="developer", sha256=hashlib.sha256(plan_f.read_bytes()).hexdigest(), durable=True)
        patch_art = Artifact(
            id="art_c",
            run_id=base_run.id,
            name="patch.diff",
            path="patch.diff",
            artifact_type=ArtifactType.CODE_PATCH.value,
            producer_role="developer",
            sha256=hashlib.sha256(patch_f.read_bytes()).hexdigest(),
            durable=True,
            metadata={
                "base_commit_hash": head,
                "changed_files": ["calc.py"],
                "verification_outcomes": [{"status": "PASS", "passed": True, "exit_code": 0}],
                "plan_artifact_id": plan_art.id,
                "plan_sha256": plan_art.sha256,
            },
        )
        qarep_art = Artifact(
            id="art_q",
            run_id=base_run.id,
            name="qarep.md",
            path="qarep.md",
            artifact_type=ArtifactType.QA_REPORT.value,
            producer_role="qa",
            sha256=hashlib.sha256(qarep_f.read_bytes()).hexdigest(),
            durable=True,
            metadata={
                "code_patch_artifact_id": patch_art.id,
                "code_patch_sha256": patch_art.sha256,
                "product_artifact_id": prod_art.id,
                "developer_plan_artifact_id": plan_art.id,
                "base_commit_hash": head,
                "recommended_verification_actions": [{"action_type": "pytest", "target": "tests/test_calc.py", "purpose": "Verify inc"}],
            },
        )
        base_run.artifacts.extend([plan_art, patch_art, qarep_art])
        base_task.complete(status=TaskStatus.COMPLETED.value, summary="done")

        qa_task = service.create_task("proj_qa14b", "QA Verify", "Verify patch", required_roles=["qa"])
        for aid in (prod_art.id, plan_art.id, patch_art.id, qarep_art.id):
            service.attach_input_artifact(qa_task.id, aid, project_id="proj_qa14b")

        hook_verified = []

        def fake_qa_execute(agent, prompt, timeout=None, workspace_dir=None, env=None):
            ws = Path(workspace_dir).resolve()
            assert ws != target_repo.resolve()
            cfg = json.loads((ws / ".agents" / "policy_config.json").read_text(encoding="utf-8"))
            assert cfg["mode"] == "strict_read_only"
            assert (ws / ".agents" / "hooks.json").is_file()
            hook_verified.append(cfg["mode"])
            verdict_json = json.dumps({
                "schema_version": "1.0",
                "verdict": "PASS",
                "summary": "Verified cleanly",
                "requirements_evaluations": [{"requirement_id": "REQ-1", "status": "SATISFIED", "evidence": "pytest passed"}],
                "blocking_issues": [],
                "release_recommendation": "APPROVE",
            })
            return AgentExecutionResult(agent="qa", command=["mock"], exit_code=0, stdout=f"```json\n{verdict_json}\n```", stderr="", duration_ms=5.0, timed_out=False, success=True)

        with patch.object(real_runtime, "execute", side_effect=fake_qa_execute):
            qa_run = service.execute_qa_verification_task(qa_task.id, project_id="proj_qa14b", target_repo_root=target_repo)

        assert qa_run.status == RunStatus.SUCCESS.value
        assert hook_verified == ["strict_read_only"]

    def test_repair_planning_runs_in_isolated_target_worktree_not_company_repo_and_cleans_up_on_failure(self, tmp_path: Path):
        company_repo = tmp_path / "JesterAICompany"
        target_repo = tmp_path / "TargetApp"
        _init_git_repo(company_repo, {"engine.py": "ENGINE = True\n"})
        target_head = _init_git_repo(target_repo, {"math_lib.py": "def add(a, b):\n    return a - b\n"})
        runs_dir = tmp_path / "runs"

        captured_workspaces: list[Path] = []
        hook_modes: list[str] = []

        class FailingRepairPlannerRuntime(AntigravityRuntime):
            def execute(self, agent, prompt, timeout=None, workspace_dir=None, env=None):
                assert workspace_dir is not None
                ws = Path(workspace_dir).resolve()
                captured_workspaces.append(ws)
                cfg = json.loads((ws / ".agents" / "policy_config.json").read_text(encoding="utf-8"))
                hook_modes.append(cfg["mode"])
                assert ws != company_repo.resolve()
                assert ws != target_repo.resolve()
                assert (ws / "math_lib.py").is_file()
                assert not (ws / "engine.py").exists()
                return AgentExecutionResult(
                    agent=agent, command=["mock"], exit_code=0, stdout="INVALID NON-JSON RESPONSE", stderr="", duration_ms=5.0, timed_out=False, success=True
                )

        service = CompanyService(
            output_dir=str(runs_dir),
            repo_root=company_repo,
            runtime=FailingRepairPlannerRuntime(repo_root=company_repo),
        )
        service.create_project("proj_rep", "Repair Iso Project")
        task = service.create_task("proj_rep", "Fix add", "Fix add bug", required_roles=["developer"])
        run = task.create_run()
        run.status = RunStatus.SUCCESS.value

        plan_file = runs_dir / "plan.md"
        plan_file.parent.mkdir(parents=True, exist_ok=True)
        plan_file.write_text("# Plan\n", encoding="utf-8")
        patch_file = runs_dir / "patch.diff"
        patch_file.write_text("diff --git a/math_lib.py b/math_lib.py\n", encoding="utf-8")
        qarep_file = runs_dir / "qarep.md"
        qarep_file.write_text("# QA Rep\n", encoding="utf-8")
        qaexec_file = runs_dir / "qaexec.md"
        qaexec_file.write_text("# QA Exec FAIL\n", encoding="utf-8")

        plan_art = Artifact(id="art_plan_iso", run_id=run.id, name="plan.md", path="plan.md", artifact_type=ArtifactType.DEVELOPER_PLAN_REPORT.value, producer_role="developer", sha256=hashlib.sha256(plan_file.read_bytes()).hexdigest(), durable=True)
        patch_art = Artifact(id="art_patch_iso", run_id=run.id, name="patch.diff", path="patch.diff", artifact_type=ArtifactType.CODE_PATCH.value, producer_role="developer", sha256=hashlib.sha256(patch_file.read_bytes()).hexdigest(), durable=True, metadata={"base_commit_hash": target_head, "changed_files": ["math_lib.py"]})
        qarep_art = Artifact(id="art_qarep_iso", run_id=run.id, name="qarep.md", path="qarep.md", artifact_type=ArtifactType.QA_REPORT.value, producer_role="qa", sha256=hashlib.sha256(qarep_file.read_bytes()).hexdigest(), durable=True)
        qaexec_art = Artifact(id="art_qaexec_iso", run_id=run.id, name="qaexec.md", path="qaexec.md", artifact_type=ArtifactType.QA_EXECUTION_REPORT.value, producer_role="qa", sha256=hashlib.sha256(qaexec_file.read_bytes()).hexdigest(), durable=True, metadata={"verdict": "FAIL", "code_patch_artifact_id": patch_art.id, "qa_report_artifact_id": qarep_art.id, "developer_plan_artifact_id": plan_art.id, "base_commit_hash": target_head})
        run.artifacts.extend([plan_art, patch_art, qarep_art, qaexec_art])
        task.complete(status=TaskStatus.COMPLETED.value, summary="done")

        res = service.execute_developer_qa_repair_loop(
            task_id=task.id,
            project_id="proj_rep",
            target_repo_root=target_repo,
            sandbox_run_id="crun_iso_test",
        )
        assert res.status == "REPAIR_PLAN_FAILED"
        assert hook_modes == ["read_only_planning"]
        assert not captured_workspaces[0].exists()
        _, c_stat, _ = run_git(["status", "--porcelain"], cwd=company_repo)
        _, t_stat, _ = run_git(["status", "--porcelain"], cwd=target_repo)
        assert c_stat.strip() == ""
        assert t_stat.strip() == ""

    def test_readonly_specialist_with_real_runtime_uses_isolated_hooked_workspace_and_cleans_up(self, tmp_path: Path):
        company_repo = tmp_path / "JesterAICompany"
        _init_git_repo(company_repo, {"engine.py": "ENGINE = True\n"})
        runs_dir = tmp_path / "runs"

        real_runtime = AntigravityRuntime(repo_root=company_repo)
        service = CompanyService(output_dir=str(runs_dir), repo_root=company_repo, runtime=real_runtime)
        service.create_project("proj_ro", "RO Test")
        task = service.create_task("proj_ro", "Research check", "Check architecture", required_roles=["research"])

        seen_ws: list[Path] = []

        def fake_execute(agent, prompt, timeout=None, workspace_dir=None, env=None):
            ws = Path(workspace_dir).resolve()
            seen_ws.append(ws)
            assert ws != company_repo.resolve()
            assert (ws / ".agents" / "hooks.json").is_file()
            return AgentExecutionResult(
                agent=agent,
                command=["mock"],
                exit_code=0,
                stdout='```json\n{"schema_version":"1.0","status":"completed","summary":"ok","findings":["f1"],"recommendations":["r1"],"sources":[]}\n```',
                stderr="",
                duration_ms=10.0,
                timed_out=False,
                success=True,
            )

        with patch.object(real_runtime, "execute", side_effect=fake_execute):
            service.execute_research_task(task.id, project_id="proj_ro")

        assert len(seen_ws) == 1
        assert not seen_ws[0].exists()


# ==============================================================================
# 4. Test Infrastructure (2D): Offline Unit Tests Cannot Invoke Live agy
# ==============================================================================

class TestOfflineAgyGuardStage0B:

    def test_conftest_blocks_accidental_live_agy_popen(self):
        with pytest.raises(RuntimeError, match="attempted to spawn live 'agy' subprocess"):
            subprocess.Popen(["agy", "--version"])

    def test_conftest_blocks_accidental_live_agy_run(self):
        with pytest.raises(RuntimeError, match="attempted to run live 'agy' subprocess"):
            subprocess.run(["agy", "--version"], capture_output=True, text=True)
