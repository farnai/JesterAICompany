# JesterAICompany Capabilities & Backlog

This document tracks the implementation status of architectural capabilities in **JesterAICompany**, distinguishing completed capabilities, partially completed systems, deferred roadmap items, and obsolete directions.

In accordance with our core operating principles (*"Practical over complex"*, *"Do not build functionality before it is needed"*, and *"Strict stage gating"*), capabilities are introduced only after preceding workflow primitives are executed and verified.

---

## 1. Completed & Implemented Capabilities

### A. Structured Agent Communication & Canonical Artifact Materialization
- **Status:** `COMPLETED` (Verified through STEP 17B-4)
- **Implemented Scope:**
  - Typed task definitions (`Task`) and execution attempts (`TaskRun`).
  - Immutable input references ([`ArtifactInputRef`](jester_ai_company/core.py)).
  - Cryptographically verified, content-addressed artifact handoffs (`load_and_verify_input_artifact`) with SHA-256 byte-for-byte readback assertions.
  - Strict handoff policy enforcement ([`ALLOWED_HANDOFF_EDGES`](jester_ai_company/core.py)).
  - Three proven workflow data primitives: Sequential Handoff (`Research → Product → UX`), Fan-Out (`Product → UX + Marketing`), and Fan-In (`(Product + UX) → Developer Planning`).
  - Strict input size limits (100KB per artifact / 150KB combined).
  - Explicit trust boundary delimiters enclosing untrusted upstream artifact data in prompts.
  - Canonical materialized deliverables: `PRD` (`product_report.md`), `UX_SPEC` (`ux_report.md`), `DEVELOPER_PLAN` (`developer_plan_report.md`), `CODE_PATCH` (`developer_changes.patch`), `QA_REPORT` (`qa_report.md`), `QA_EXECUTION_REPORT` (`qa_execution_report.md`), `DEVELOPER_QA_REPAIR_REPORT` (`developer_qa_repair_report.md`), and `REAL_REPO_APPLY_REPORT` (`real_repo_apply_report.md`).

### B. Developer Implementation & Isolated Mutation
- **Status:** `COMPLETED` (Verified in STEP 13A, 13B-1, 13B-2, 13B-3)
- **Implemented Scope:**
  - Developer Agent activated in **READ-ONLY PLANNING MODE** (STEP 13A).
  - Typed planning contract ([`DeveloperTaskResult`](jester_ai_company/developer_result.py)) with proposed files, dependencies, commands, risks, and verification strategies.
  - Proposed commands and file paths treated strictly as inert data.
  - Working-tree immutability assertions (`git status --porcelain`).
  - **Immutable ExecutionGrant Foundation:** Binds execution authority to explicit `founder_approval_id`, durable Developer Plan artifact ID, plan SHA-256, approved modify/create file lists, byte quotas, and exact `base_commit_hash`.
  - **Isolated Git Worktree Lifecycle:** Deterministic detached worktree manager operating in `.runs/worktrees/<grant_id>` from approved commit base; automatic cleanup in `finally:` blocks.
  - **Synchronous Policy Hooks:** PreToolUse hook denies unauthorized writes and blocks `run_command` (zero shell authority).
  - **Application-Owned Verification:** Deterministic translation of typed verification actions (e.g. `pytest`), executed in sanitized environments without network or shell access.
  - **Canonical CODE_PATCH Materialization:** Unified diff captured against base commit, including approved new untracked files; atomic disk writes and SHA-256 verification.

### C. Independent QA Inspection & Isolated Test Execution
- **Status:** `COMPLETED` (Verified in STEP 14A, 14B)
- **Implemented Scope:**
  - **Independent QA Inspection (Read-Only):** Real QA Agent (`agy --agent qa`) inspecting `CODE_PATCH` against product requirements and UX specifications. Structured findings with severity ratings (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`) and requirements coverage mapping.
  - **Isolated QA Execution:** Fresh disposable Git worktree created from exact `base_commit_hash`. Application-owned patch apply (`git apply`) and diff validation.
  - **Deterministic Verdict Constraints:** Application-enforced verdict logic (missing/unexecutable tests forbid PASS -> `BLOCKED`; test failures forbid PASS -> `FAIL`; clean test pass permits `PASS`).

### D. Developer ↔ QA Controlled Repair Loop
- **Status:** `COMPLETED` (Verified in STEP 15)
- **Implemented Scope:**
  - Automated application-owned repair loop between Developer and QA when independent QA execution issues `FAIL` or repairable `BLOCKED`.
  - **Clarification 1 (Handoff Edge != Agent Authority):** Handoff edges govern artifact compatibility only; agents have zero runtime invocation authority.
  - **Clarification 2 (Human Approval Mandatory):** Zero synthetic/fabricated approvals. Every repair iteration strictly requires its own distinct founder approval (`founder_approval_id`).
  - Fresh worktree reconstruction from `base_commit_hash` with previous patch pre-applied.
  - Cumulative `CODE_PATCH vN` generation with complete version lineage metadata.
  - Independent QA reinspection (STEP 14A) and re-execution (STEP 14B) on each repair candidate.
  - Hard limit of 2 repair iterations strictly enforced.

### E. Human-Approved Transactional Real Repository Apply (`RealRepoApply`)
- **Status:** `COMPLETED` (Verified in STEP 16)
- **Implemented Scope:**
  - External repository lock acquired outside target `.git` in `.runs/locks/apply_<hash>.lock`.
  - Clean working tree precondition (`git status --porcelain` empty) before apply and rollback.
  - Deterministic crash recovery classification (`NOT_APPLIED`, `EXACT_APPROVED_PATCH_PRESENT`, `PARTIAL_OR_UNKNOWN_STATE`).
  - Non-destructive rollback via `git apply --reverse` upon post-apply diff divergence.
  - Exact diff equivalence check against approved `CODE_PATCH` bytes before finalization.
  - Zero agent runtime invocation during apply; process is strictly application-owned.
  - Durable `REAL_REPO_APPLY_REPORT` artifact with cryptographic audit trail.

### F. Dynamic DAG Decomposition & Multi-Specialist Chaining
- **Status:** `COMPLETED` (Verified in STEP 17A, 17B-1 through 17B-4)
- **Implemented Scope:**
  - CEO structured planning contract ([`DAGProposal`](jester_ai_company/dag.py)).
  - Deterministic DAG validation: structural integrity, cycle detection, valid role assignment, prerequisite enforcement.
  - Multi-specialist task chaining across all seven roles via `CompanyRun`.
  - Engineering pipeline integration (`CompanyEngineeringPipeline`): connects Product + UX fan-in → Developer planning → ExecutionGrant → isolated worktree mutation → CODE_PATCH → QA execution → repair loop → `READY_FOR_HUMAN_APPLY` → `RealRepoApply` → `COMPLETED`.

---

## 2. Partially Completed Capabilities

### A. Human Approval System
- **Status:** `PARTIALLY_COMPLETED`
- **Implemented:**
  - Strict human authorization gates for high-impact mutations: `RealRepoApplyGrant` required for real repository application, `founder_approval_id` required for execution grants and repair iterations.
  - Fail-closed behavior on missing, stale, or reused approvals.
- **Still Deferred:**
  - Generalized human approval workflow across arbitrary non-code tasks.
  - Interactive web UI / CLI portal for live approval review and one-click dispatch.

### B. Permissions & Access Control
- **Status:** `PARTIALLY_COMPLETED`
- **Implemented:**
  - Strict execution boundaries: isolated Git worktrees, PreToolUse hook interception denying unauthorized writes, unconditional denial of `run_command`, environment variable sanitization stripping sensitive tokens.
- **Still Deferred:**
  - Full operating system kernel sandboxing (e.g. Linux namespaces, seccomp, Docker/cgroups containers).
  - Role-based multi-user authorization model (RBAC).

### C. Crash Recovery & Idempotency
- **Status:** `PARTIALLY_COMPLETED`
- **Implemented:**
  - Durable state transitions and artifact referencing in `.runs/`.
  - Transactional apply state classification (`NOT_APPLIED`, `EXACT_APPROVED_PATCH_PRESENT`, `PARTIAL_OR_UNKNOWN_STATE`).
  - Preflight SHA-256 integrity verification failing closed on modified artifacts.
- **Still Deferred:**
  - Relational database persistence (e.g. SQLite / PostgreSQL) storing full company memory across process restarts. Active `CompanyService` state currently initializes in-memory per service instance.

---

## 3. Deferred / Future Capabilities

### A. Persistent Long-Term Memory & Vector DB
- **Status:** `DEFERRED` (In accordance with YAGNI)
- **Scope:**
  - Cross-session memory recalling past organizational decisions and learnings.
  - Vector embeddings and semantic search over historical project deliverables.

### B. OS-Level Process Sandboxing
- **Status:** `DEFERRED`
- **Scope:**
  - Hardware- or kernel-enforced sandboxing restricting raw OS syscalls, network socket creation, and filesystem access beyond worktree roots.

### C. Full End-to-End Enterprise Evaluation (STEP 18)
- **Status:** `DEFERRED` (Scheduled for STEP 18)
- **Scope:**
  - Holistic organizational validation across long-horizon objectives.
  - End-to-end multi-agent evaluation under real-world project scenarios.

### D. Interactive Control Center UI
- **Status:** `DEFERRED`
- **Scope:**
  - Production graphical interface for monitoring company runs, reviewing artifacts, and granting human approvals.

---

## 4. Obsolete / Archived Roadmap Directions

### JesterBridge Integration
- **Status:** `OBSOLETE / ARCHIVED`
- **Rationale:** `JesterBridge` was an external exploratory integration concept that is out of scope and disconnected. JesterAICompany operates as an independent, self-contained multi-agent company execution engine. Direct integration with the target product (Jester) is a separate future concern and has not yet been performed.
