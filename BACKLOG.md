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

- **Implemented Foundation (Verified in STEP 13A, 13B-1 & 13B-2):**
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

- **Still Deferred:**
  - **Developer Verification Execution & Durable CODE_PATCH Artifact (Next: STEP 13B-3):** Application-owned conversion of typed `VerificationAction` to subprocess execution and durable materialization of `CODE_PATCH` artifact with cryptographic SHA-256 binding.
  - **Real Repository Patch Application (STEP 13C):** Applying verified `CODE_PATCH` back to the human owner's primary working tree after founder review.
  - **QA Agent & Automated Repair Loop:** Deferred until Developer mutation and verification are complete.
  - **Dependency Management:** Safe installation of project dependencies.
  - **Git Operations:** Automated commits or branch manipulation (Git remains strictly application-owned).

---

### C. QA Agent Structured Execution

- **Implemented Foundation:**
  - QA Agent role definition and neutral verification guidelines ([`.agents/agents/qa/agent.md`](.agents/agents/qa/agent.md)).
  - `VerificationResult` domain model in core architecture.

- **Still Deferred:**
  - **Typed QA Contract:** Structured JSON result contract for QA findings, acceptance criteria verdicts (`PASS` / `FAIL` / `BLOCKED`), and defect logs.
  - **Structured QA Execution:** Service-level `execute_qa_task` entry point and preflight validation.
  - **Developer ↔ QA Repair Loop:** Automated feedback cycle where QA failure reports feed back into Developer planning/implementation.
  - **Automated Test Harness Execution:** Supervised running of unit and integration test suites.

---

### D. Automated CEO Orchestration & Autonomous Autopilot

- **Implemented Foundation:**
  - CEO structured action proposals ([`CEOActionProposal`](jester_ai_company/proposal.py)) translating user goals into validated specialist tasks.
  - Company chat interface ([`company_chat`](jester_ai_company/service.py)).

- **Still Deferred:**
  - **Autonomous Chaining:** CEO autonomously spawning downstream tasks upon upstream completion.
  - **Dynamic Task Decomposition:** Automatically creating multi-specialist pipelines from high-level objectives.
  - **Automated Escalation Management:** Automatically resolving conflicts between Product and UX without human operator intervention.

---

### E. Permissions, Sandboxing & OS-Level Isolation

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

### F. Persistent Company Storage & Long-Term Memory

- **Implemented Foundation:**
  - In-memory service state (`CompanyService`) for projects, tasks, runs, and verifications.
  - Durable, disk-persisted artifacts stored in `.runs/<task_id>/<run_id>/artifacts/`.

- **Still Deferred:**
  - **Relational / Document Database:** SQLite, PostgreSQL, or file-backed database persisting company operational state across process restarts.
  - **Cross-Session Memory:** Agent recall of past project decisions, learnings, and historical context.
  - **Vector Storage & Semantic Retrieval:** Embeddings-based retrieval over past artifacts and repository knowledge.

---

### G. Decision Systems & Human Approval Gates

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
