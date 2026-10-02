# Future Capabilities & Backlog

This backlog tracks architectural capabilities, integrations, and enhancements that are **intentionally NOT implemented yet** or are **genuinely deferred**.

In accordance with our core operating principles (*"Practical over complex"*, *"Do not build functionality before it is needed"*, and *"Strict stage gating"*), capabilities are introduced only after preceding workflow primitives are executed and verified.

---

## 1. Status of Core Capabilities

### A. Structured Agent Communication & Workflow Primitives

- **Implemented Foundation (Verified through STEP 13A):**
  - Typed task definitions (`Task`) and execution attempts (`TaskRun`).
  - Immutable input references ([`ArtifactInputRef`](jester_ai_company/core.py)).
  - Cryptographically verified, content-addressed artifact handoffs (`load_and_verify_input_artifact`).
  - Strict handoff policy enforcement ([`ALLOWED_HANDOFF_EDGES`](jester_ai_company/core.py#L131)).
  - Three proven workflow data primitives:
    - **Sequential Handoff:** `Research → Product → UX`
    - **Fan-Out:** `Product → (UX + Marketing)`
    - **Fan-In:** `(Product + UX) → Developer Planning`
  - Strict input size limits (100KB per artifact / 150KB combined).
  - Explicit trust boundary delimiters for untrusted upstream artifact data.

- **Still Deferred:**
  - **Automatic Orchestration:** Automatic specialist chaining without explicit service invocation.
  - **Generalized Graph Scheduling:** Dynamic directed acyclic graph (DAG) scheduling and automated dependency resolution.
  - **Inter-Agent Direct Messaging:** Ad-hoc or conversational peer-to-peer agent messaging.
  - **Execution Retries & Rollback:** Automated retry strategies, exponential backoff, or failure rollback mechanics.
  - **Persistent Workflow State:** Preserving active workflow run states across process restarts.

---

### B. Developer Implementation & Repository Mutation (STEP 13B Roadmap)

- **Implemented Foundation (Verified in STEP 13A, 13B-1, 13B-2 & 13B-3):**
  - Developer Agent activated in **READ-ONLY PLANNING MODE** (STEP 13A).
  - Typed planning contract ([`DeveloperTaskResult`](jester_ai_company/developer_result.py)) with proposed files, dependencies, commands, risks, and verification strategies.
  - Proposed commands and file paths treated strictly as inert data.
  - Pre- and post-execution working-tree integrity assertions (`git status --porcelain`).
  - **Immutable ExecutionGrant Foundation (STEP 13B-1):** Binds execution authority to explicit `founder_approval_id`, durable Developer Plan artifact ID, plan SHA-256, and exact `base_commit_hash`.
  - **Isolated Git Worktree Lifecycle (STEP 13B-1):** Deterministic detached worktree manager operating in `.runs/worktrees/<grant_id>` from approved commit base; automatic cleanup on success or exception.
  - **Deterministic Diff Capture (STEP 13B-1):** Application-owned unified diff capture including untracked files without LLM involvement.
  - **Main Repository Immutability (STEP 13B-1):** Proven invariant that dirty main working tree changes are not leaked into isolated worktree and main repository is 100% untouched.
  - **Security Primitives (STEP 13B-1):** Path confinement engine rejecting traversal/escapes, protected-path policies (`.git`, `.agents`, `.env*`, etc.), test modification gating, and environment variable sanitization.
  - **Bounded Developer Mutation (STEP 13B-2):** Real Developer agent mutation inside isolated disposable worktree bounded strictly by `ExecutionGrant`; synchronous `PreToolUse` hook denies unauthorized writes and `run_command` calls before tool execution; independent diff validation enforces zero deletions, approved file limits, and byte budgets; worktree discarded after execution; zero real-repository changes.
  - **Verification Execution & CODE_PATCH Artifact (STEP 13B-3):** Application-owned typed verification (`pytest`), fail-closed validation, canonical patch capture (including approved new files), durable `CODE_PATCH` artifact materialization (`developer_changes.patch` + companion `.meta.json`), readback SHA-256 byte-for-byte check, full audit lineage retention, and worktree destruction in `finally:` block.

- **Still Deferred:**
  - **Dependency Management:** Safe installation of project dependencies.
  - **Git Operations:** Automated commits or branch manipulation (Git remains strictly application-owned).

---

### C. QA Agent Structured Execution & Repair Loop (STEP 14 & STEP 15 Roadmap)

- **Implemented Foundation (Verified in STEP 14A, STEP 14B & STEP 15):**
  - **Independent QA Inspection (STEP 14A):** Real QA Agent execution (`agy --agent qa`) inspecting verified `CODE_PATCH` and upstream Product/UX/Developer specifications.
  - **Strict Typed QA Contract ([`QAInspectionResult`](jester_ai_company/qa_result.py)):** Schema version 1.0, inspection-oriented verdicts (`READY_FOR_QA_EXECUTION`, `NEEDS_DEVELOPER_ATTENTION`, `BLOCKED`).
  - **Structured Findings:** Severity-rated defects (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO`) citing requirement references, affected files, diff evidence, and recommendations.
  - **Requirements Coverage:** Deterministic mapping of product/UX requirements against implementation evidence (`COVERED`, `PARTIAL`, `NOT_COVERED`, `NOT_VERIFIABLE`).
  - **QA Test Planning:** Structured test case specifications (`QATestCase`) with objectives, preconditions, targets, and expected results.
  - **Recommended Verification Actions:** Proposals for future execution (`QARecommendedAction`) strictly without execution authority (proposal != permission).
  - **Durable QA Artifact Materialization:** `QA_REPORT` (`qa_report.md` + `.meta.json`) with cryptographic SHA-256 integrity and complete lineage chain back to Product, UX, Plan, Grant, Patch, Base Commit, and Verifications.
  - **Isolated QA Execution (STEP 14B):** Fresh disposable Git worktree created from exact `base_commit_hash`; application-owned patch applicability preflight (`git apply --check`) and apply (`git apply`) with `shell=False`; applied diff validation against `CODE_PATCH` authority.
  - **Safe Typed Verification Action Authorization (STEP 14B):** Rigorous whitelist enforcement (`pytest` only), metacharacter rejection, path traversal rejection, protected path policy, physical file target existence verification, and budget limits.
  - **Deterministic Verdict Constraints (STEP 14B):** Enforced strictly by the application layer:
    - If required verification is unavailable/unexecutable -> PASS is forbidden -> normally `BLOCKED`.
    - If required verification executes and fails -> PASS is forbidden -> `FAIL`.
    - If required actions execute and pass with no blockers -> `PASS` permitted.
    - QA Agent interprets evidence but cannot override these deterministic verdict constraints.
  - **Read-Only QA Agent Release Verdict (STEP 14B):** QA Agent evaluates executed evidence and issues structured final release verdict (`PASS`, `FAIL`, `BLOCKED`).
  - **Durable QA Execution Artifact Materialization (STEP 14B):** `QA_EXECUTION_REPORT` (`qa_execution_report.md` + `.meta.json`) with SHA-256 cryptographic verification and complete end-to-end lineage.
  - **Guaranteed Worktree Cleanup & Repo Immutability (STEP 14B):** Worktree destroyed on all exit paths in `finally:` block; main repository remains 100% untouched.
  - **Developer ↔ QA Controlled Repair Loop (STEP 15):**
    - Application-owned repair loop between Developer and QA when independent QA execution returns `FAIL` or repairable `BLOCKED`.
    - **Clarification 1 (Handoff Edge != Agent Authority):** `ALLOWED_HANDOFF_EDGES` contains `("qa", "developer")` and `("developer", "developer")` strictly governing artifact consumption compatibility; agents have zero runtime invocation authority; QA cannot invoke Developer, Developer cannot invoke QA or itself; `CompanyService` remains the sole transition owner.
    - **Clarification 2 (Human Approval Mandatory):** Zero synthetic/fabricated founder approvals. Every repair iteration strictly requires its own legitimate founder approval (`founder_approval_id`); missing or reused approval halts immediately in `REPAIR_GRANT_REJECTED`.
    - **Typed DeveloperRepairTask & Strict DeveloperRepairPlan:** Schema version 1.0 ([`DeveloperRepairPlan`](jester_ai_company/repair.py)), strict root-cause analysis, defect-to-requirement mapping, file deletion strictly forbidden, requirement conflict gating.
    - **Fresh Worktree Reconstruction & Patch Pre-application:** Fresh worktree created at original `base_commit_hash` with previous `CODE_PATCH` pre-applied (`apply_code_patch_to_worktree`).
    - **Cumulative CODE_PATCH vN Generation:** Captured directly against `base_commit_hash` representing total cumulative delta; includes complete version lineage (`patch_version`, `previous_code_patch_artifact_id`, `previous_code_patch_sha256`, `repair_id`, `repair_iteration`).
    - **Independent QA Reinspection & Re-execution:** Every candidate patch undergoes independent QA reinspection (STEP 14A) and re-execution (STEP 14B) in disposable worktree.
    - **Hard Iteration Limit:** `MAX_REPAIR_ITERATIONS = 2` strictly enforced with no 3rd attempt.
    - **Durable Repair Artifacts:** `DEVELOPER_REPAIR_PLAN_REPORT` (`developer_repair_plan_v{N}.md`) and `DEVELOPER_QA_REPAIR_REPORT` (`developer_qa_repair_report.md` + `.meta.json`).
    - **Zero Real Repository Mutation:** All repairs execute inside isolated disposable worktrees; main repository remains 100% untouched.

---

### D. Human-Approved Transactional Real Repository Apply (STEP 16 Roadmap)

- **Implemented Foundation (Verified in STEP 16):**
  - **External Concurrency Lock Outside Target `.git`:** Lock acquired as `.runs/locks/apply_<hash>.lock` in JesterAICompany runtime state, leaving target `.git` untouched.
  - **Simplified Local Repository Identity:** Canonical absolute root path + exact `HEAD` commit hash + clean status (no root commit authorization primitive).
  - **Deterministic Crash Recovery Classification:** `NOT_APPLIED`, `EXACT_APPROVED_PATCH_PRESENT`, `PARTIAL_OR_UNKNOWN_STATE`.
  - **Fail-Closed Crash State Blocking:** Any unfinalized grant in unresolved or unknown state permanently blocks subsequent apply via `CrashRecoveryBlockError`.
  - **Clean Working Tree Precondition:** Target working tree must be 100% clean (`git status --porcelain` empty) before any apply operation and before any rollback operation.
  - **Exact Reverse Patch Rollback:** Non-destructive rollback via `git apply --reverse`; zero `git reset --hard` or `git clean -fd`.
  - **Zero Real Repository Pytest/Application Tests (V1):** Real repository never executes test suites or arbitrary code in V1.
  - **Exact Diff Equivalence as Final Commit Point:** Applied patch diff against real repository working tree must match approved `CODE_PATCH` byte-for-byte; any divergence triggers immediate reverse rollback.
  - **Mandatory Explicit Human Approval:** Valid, distinct human founder approval (`founder_approval_id`) strictly required; zero agent synthesis.
  - **Zero-Mutation Prepare & Approve:** `prepare_real_repo_apply` and `approve_real_repo_apply` perform zero repository writes and zero working tree modifications.
  - **Single Mutation Boundary:** `execute_real_repo_apply` is the sole entry point permitted to mutate the target working tree.
  - **Zero Agent Runtime Invocation:** No `agy` invocation during real repository apply; process is strictly application-owned.
  - **Durable `REAL_REPO_APPLY_REPORT` Artifact:** Cryptographic SHA-256 integrity and complete lineage chain.

- **Still Deferred (Updated Roadmap Order):**
  - **Automatic CEO Orchestration (STEP 17):** Autonomous end-to-end task chaining across specialists.
  - **Full End-to-End Company Proof (STEP 18):** Complete organizational validation.

---

### E. Automated CEO Orchestration & Autonomous Autopilot (STEP 17 Roadmap)

- **Implemented Foundation:**
  - CEO structured action proposals ([`CEOActionProposal`](jester_ai_company/proposal.py)) translating user goals into validated specialist tasks.
  - Company chat interface ([`company_chat`](jester_ai_company/service.py)).

- **Still Deferred:**
  - **Autonomous Chaining:** CEO autonomously spawning downstream tasks upon upstream completion.
  - **Dynamic Task Decomposition:** Automatically creating multi-specialist pipelines from high-level objectives.
  - **Automated Escalation Management:** Automatically resolving conflicts between Product and UX without human operator intervention.

---

### F. Permissions, Sandboxing & OS-Level Isolation

- **Implemented Foundation (Verified in STEP 13B-1):**
  - Path traversal protection ensuring all artifact reads and writes are strictly confined under the configured output directory.
  - Deterministic workspace confinement verifying all approved modification/creation paths resolve strictly inside the worktree root.
  - Explicit protected-path policy rejecting modifications to `.git`, `.agents`, `.env*`, credential files, and company control files.
  - Default denial of test file modifications (`allow_test_modifications=False`).
  - Subprocess environment sanitization stripping secret tokens and keys (`*_KEY`, `*_TOKEN`, `*_SECRET`, `AWS_*`, `GITHUB_*`).
  - Isolated detached Git worktree execution boundary.

- **Still Deferred:**
  - **OS-Level Process Sandboxing:** Containerized or kernel jail isolation preventing raw OS syscalls or direct network access.
  - **Tool-Level Capability Gating:** Dynamic policy-driven gating of agy CLI tools.

---

### G. Persistent Company Storage & Long-Term Memory

- **Implemented Foundation:**
  - In-memory service state (`CompanyService`) for projects, tasks, runs, and verifications.
  - Durable, disk-persisted artifacts stored in `.runs/<task_id>/<run_id>/artifacts/`.

- **Still Deferred:**
  - **Relational / Document Database:** SQLite, PostgreSQL, or file-backed database persisting company operational state across process restarts.
  - **Cross-Session Memory:** Agent recall of past project decisions, learnings, and historical context.
  - **Vector Storage & Semantic Retrieval:** Embeddings-based retrieval over past artifacts and repository knowledge.

---

### H. Decision Systems & Human Approval Gates

- **Implemented Foundation:**
  - `Approval` entity in core domain model with `PENDING`, `APPROVED`, and `REJECTED` states.
  - Human review of CEO proposals and explicit manual trigger of specialist tasks.

- **Still Deferred:**
  - **Interactive Checkpoints:** Halting automated workflows pending explicit human sign-off via UI/CLI.
  - **Consensus Matrices:** Formal multi-agent voting or decision matrices for conflicting specialist recommendations.

---

## 2. Archived / Removed Roadmap Directions

The following items from earlier conceptual notes have been removed from the active JesterAICompany roadmap:

### JesterBridge Integration (Archived)
- **Previous Concept:** Technical inspection, MVP development, and runtime integration with `JesterBridge` (an external bridge connecting AI systems to product environments).
- **Current Architectural Status:** **REMOVED FROM ROADMAP.**
- **Rationale:** `JesterBridge` is a separate experimental repository. JesterAICompany is an independent, self-contained multi-agent company execution engine. It does not depend on, interact with, or include `JesterBridge`.
