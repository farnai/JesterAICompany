# JesterAICompany

An engineered AI-company runtime and orchestration system in which specialized AI employees perform bounded, professional work under deterministic application control. The Human Founder remains the ultimate decision maker and final authority.

---

## 1. What It Is

**JesterAICompany** is an AI company runtime and multi-agent execution framework. Instead of treating large language models (LLMs) as open-ended, free-form chatbots or speculative autonomous agents, JesterAICompany structures them as specialized AI employee roles operating within rigorous professional boundaries and coordinated through deterministic application logic.

- **Company Identity:**
  - **Name:** Jester AI Company
  - **Role:** AI company execution system & runtime infrastructure
- **Crucial Boundary Clarification:**
  - JesterAICompany is **NOT** Jester itself. Jester is a separate target software product.
  - JesterBridge is a separate repository / integration concept and is currently out of scope.
  - **Direct Jester integration has NOT yet been performed.**

For a comprehensive technical specification of system internals, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## 2. Company Hierarchy

The company structure enforces strict separation of responsibilities between human governance, executive planning, and specialist execution:

```
                     Human Owner / Founder
                     (Ultimate Authority)
                               │
                               ▼
                           CEO Agent
              (Planner, Decomposer, Reporter)
                               │
         ┌─────────┬───────────┼───────────┬─────────┬─────────┐
         ▼         ▼           ▼           ▼         ▼         ▼
      Product  Research       UX       Marketing Developer    QA
```

### CEO Responsibilities & Authority Boundaries
- **Core Responsibilities:**
  - Interpret high-level Human objectives.
  - Propose structured company plans and work decomposition.
  - Formulate typed, validated Directed Acyclic Graphs (`DAGProposal`).
  - Coordinate specialist assignments and synthesize progress reports.
- **Strict Limitation of Authority:**
  - The CEO **DOES NOT** possess unrestricted execution authority.
  - The CEO cannot issue execution authority arbitrarily.
  - The CEO cannot skip QA verification or declare QA PASS.
  - The CEO cannot approve its own repository application.
  - The CEO cannot synthesize human approval or bypass the `READY_FOR_HUMAN_APPLY` gate.

---

## 3. Employee Roles

JesterAICompany recognizes seven distinct employee roles defined in `.agents/agents/<role>/agent.md`:

| Role | Domain Discipline | Operational Responsibilities & Boundaries |
| :--- | :--- | :--- |
| **CEO** | Executive Planning | Interprets human intent; produces structured DAG work decompositions; coordinates specialists; reports status. Has zero direct code or spec authoring authority. |
| **Product** | Requirements & Scope | Authors Product Requirements Documents (`PRD`); defines problem statements, user personas, IN/OUT scope boundaries, and acceptance criteria. Cannot write code or design UI. |
| **Research** | Grounding & Evidence | Gathers factual technical benchmarks, external evidence, and repository data. Read-only tools (`search_web`, `view_file`, `grep_search`). Provides verifiable source citations. Cannot alter product scope or write code. |
| **UX** | Interaction & Flow | Authors UX specifications (`UX_SPEC`); defines user journeys, screen states, ergonomics, interaction patterns, and edge cases. Cannot alter product scope or write code. |
| **Marketing** | Positioning & Comms | Authors marketing briefs; defines positioning, target audience messaging, value propositions, and communication strategies. Independent deliverable not consumed by Developer. |
| **Developer** | Implementation & Patching | Formulates implementation plans (`DEVELOPER_PLAN`); executes bounded code mutations strictly inside isolated disposable Git worktrees under an explicit `ExecutionGrant`. Has zero shell authority (`run_command` denied) and zero direct primary repository write access. Outputs canonical `CODE_PATCH` unified diffs. |
| **QA** | Quality & Verification | Independent inspection of `CODE_PATCH` against specs (`QA_REPORT`); executes test suites in fresh worktrees (`QA_EXECUTION_REPORT`). Application enforces deterministic verdict rules. Cannot mutate the main repository or approve apply. |

---

## 4. Core Architectural Principle: Semantic vs. Deterministic

The foundational invariant of the system is the strict separation between probabilistic reasoning and deterministic authority:

```
LLM semantic intelligence
        ↓
typed structured proposal / result
        ↓
deterministic validation
        ↓
deterministic orchestration
        ↓
controlled execution
```

- **Agents reason:** Probabilistic LLMs analyze context, evaluate trade-offs, and return structured JSON proposals adhering to versioned schemas.
- **Application code controls authority:** Deterministic Python software owns state machines, lifecycle transitions, DAG structural validation, execution grant issuance, worktree lifecycles, diff audits, verification execution, and repository locking.

---

## 5. CompanyRun Lifecycle

All company operations execute under an explicit, state-gated `CompanyRun` state machine:

```
CREATED → PLAN_READY → RUNNING
```

From the `RUNNING` state, execution diverges deterministically based on workflow type:

### A. Non-Code Workflow
```
RUNNING → COMPLETED
```
Executes non-code DAG nodes (Research, Product, UX, Marketing). When all nodes terminate successfully, the run reaches `COMPLETED`.

### B. Engineering Workflow
```
RUNNING → Developer Pipeline → QA Execution → READY_FOR_HUMAN_APPLY
                                                       │
                                                 (Human Review)
                                                       │
                                              RealRepoApplyGrant
                                                       │
                                                       ▼
                                                   APPLYING
                                                       │
                                                 RealRepoApply
                                                       │
                                                       ▼
                                                   COMPLETED
```

### Failure & Blocked States
- **`BLOCKED`:** Occurs when an essential prerequisite (e.g. human approval, unexecutable verification action, or missing artifact) is absent.
- **`FAILED`:** Occurs upon unrecoverable error, hard limit exhaustion, or validation violation.

---

## 6. Engineering Pipeline

The engineering workflow enforces multi-stage containment to ensure safe, verifiable code generation:

```
Product + UX Fan-In
        ↓
Developer Planning (Read-Only)
        ↓
ExecutionGrant
        ↓
Isolated Git Worktree
        ↓
CODE_PATCH
        ↓
QA Verification
   ┌────┴────┐
 FAIL      PASS
   │         │
repair       ▼
(max 2)  READY_FOR_HUMAN_APPLY
   │         🔒 (Autonomous Execution STOPS)
   └────────►│
             ▼
        Human Review
             │
     RealRepoApplyGrant
             │
             ▼
          APPLYING
             │
       RealRepoApply
             │
             ▼
         COMPLETED
```

1. **Prerequisite Fan-In:** Developer planning strictly requires verified `PRD` (Product) and `UX_SPEC` (UX) artifacts.
2. **Read-Only Planning:** Developer planning proposes files and commands as inert data; zero code is modified.
3. **ExecutionGrant:** Binds authority to approved file paths, quotas, and exact `base_commit_hash`.
4. **Worktree Isolation:** Mutation occurs in `.runs/worktrees/<grant_id>`. The primary repository is untouched.
5. **Synchronous Policy Hooks:** PreToolUse hook intercepts tool calls; unapproved writes and all `run_command` invocations are blocked synchronously.
6. **Application Verification:** Test actions (`pytest`) are executed by application infrastructure in sanitized environments.
7. **Canonical `CODE_PATCH`:** Git diff captured against base commit and stored atomically with cryptographic metadata.
8. **Target Repository Immutability:** The target repository remains completely unchanged until explicit Human approval.

---

## 7. Human Authority Model

The human owner remains the final authority for all high-impact actions:

- **CEO Cannot:**
  - Issue execution grants arbitrarily.
  - Skip QA or declare QA PASS.
  - Approve its own repository changes.
  - Synthesize human approval.
  - Bypass `READY_FOR_HUMAN_APPLY`.
- **Developer Cannot:**
  - Directly mutate the target repository before approval.
  - Self-approve code application.
- **QA Cannot:**
  - Apply patches to the target repository.
- **Human Exclusivity:**
  - Only explicit human approval (`RealRepoApplyGrant`) can authorize mutating the primary working tree.

---

## 8. Artifact Model

Employees exchange typed, content-addressed artifacts on disk rather than relying on uncontrolled conversational memory:

- **Canonical Artifacts:**
  - `PRD`: Product Requirements Document (`product_report.md`)
  - `UX_SPEC`: UX Specifications (`ux_report.md`)
  - `DEVELOPER_PLAN`: Technical Implementation Plan (`developer_plan_report.md`)
  - `CODE_PATCH`: Unified Diff (`developer_changes.patch`)
  - `QA_REPORT`: QA Inspection Findings (`qa_report.md`)
  - `QA_EXECUTION_REPORT`: Isolated Verification Verdict (`qa_execution_report.md`)
  - `REAL_REPO_APPLY_REPORT`: Real Repository Application Audit (`real_repo_apply_report.md`)
- **Integrity & Lineage:**
  - Every artifact has a SHA-256 digest computed over its UTF-8 disk bytes and verified upon readback.
  - Accompanying `.meta.json` records producer role, run ID, upstream dependencies, and base commit hash.
  - Upstream artifacts injected into prompts are wrapped in explicit security delimiters to prevent prompt injection.

---

## 9. Crash / Resume & Idempotency

- **Durable State Boundaries:** State transitions are committed to disk alongside materialized artifact references.
- **Verified Artifact Reuse:** Expensive completed operations (specs, plans, patches) are safely reused if cryptographic hashes match.
- **Fail-Closed on Tampering:** Stale, modified, or corrupted artifacts fail closed immediately during preflight checks.
- **Duplicate Apply Rejection:** Re-applying an approved grant is recognized as `EXACT_APPROVED_PATCH_PRESENT` and resolves idempotently without duplicating mutations.

---

## 10. Repository Boundaries & Project Foundation

- **Jester:** The target software product being developed. Completely separate project.
- **JesterAICompany:** The AI company runtime and orchestration infrastructure (this repository).
- **JesterBridge:** Separate repository and integration concept, currently out of scope.
- **Generic Project Foundation (STEP 19B):** Introduced a generic `Project`, `RepositoryRef`, `RepositoryPolicy`, `RepositoryStateFingerprint`, and `ProjectRegistry` foundation.
  - Project authority (`RepositoryPolicy`) defines coarse maximum repository boundaries; task authority (`ExecutionGrant`) defines narrower task mutations.
  - Cross-project protection guarantees zero cross-project contamination or unauthorized apply.
- **Generic Project Knowledge Layer (STEP 19C-B):** Introduced durable Project Knowledge ingestion, extensible domain normalization, source authority classification, role-specific policies (`RoleKnowledgePolicy`), and untrusted data prompt isolation.
- **Real Jester Read-Only Integration:** Validated directly against the authoritative real Jester repository (`C:\Users\fiord\OneDrive\Desktop\Jester` at `2173b2dd72c9802421963788e7dd0d0087af68af`) with zero mutations, zero worktrees, and fail-closed secret denial.

---

## 11. Verification Status

*(Snapshot as of STEP 19C-B)*
- **Generic Project Knowledge Suite:** Verified clean (26 passed, 0 failed).
- **Real Jester Read-Only Live Proof:** Verified clean (9 passed, 0 failed, 0 mutations).
- **Generic Project / Repository Foundation:** Verified clean (13 passed, 0 failed).
- **Focused Engineering Pipeline Suite:** Verified clean (54 passed, 0 failed).
- **Core Orchestration Engine & Services:** Verified clean (669 passed, 0 failed, 2 skipped).
- **Full Regression Status:** 100% green.
- **External Provider Status:** Deterministic tests are completely decoupled from external LLM quota availability; external 429 quota exhaustion is classified explicitly without false positives.

---

## 12. Development Principles

1. **Practical over complex:** Favor lean, workable implementations over convoluted abstractions.
2. **Small change → run → test → verify:** Advance strictly in small, measurable increments with empirical verification.
3. **Do not move ahead before current stage works:** Never advance to the next capability milestone until the current stage passes all verification gates.
4. **No premature functionality (YAGNI):** Zero speculative architecture. Build capabilities only when explicitly required.
5. **Evidence before opinion:** Base all assessments on verifiable artifacts, execution logs, and automated tests.
6. **Human final authority:** The human owner retains ultimate strategic, product, and operational authority.
7. **DONE means executed and verified:** Work is complete only when executed, parsed, validated, materialized, and tested.
