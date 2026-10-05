# JesterAICompany Architecture

This document defines the core architecture, execution model, authority boundaries, and operational invariants of **JesterAICompany**.

---

## 1. System Overview

**JesterAICompany** is an engineered AI-company runtime and orchestration system. It coordinates specialized AI employee roles through deterministic application logic to interpret goals, research, specify, design, implement, and independently verify software changes.

- **What it is:** A structured multi-agent runtime where probabilistic LLMs perform bounded reasoning within deterministic software guardrails.
- **What it is NOT:** It is **not** Jester itself (the target software product), nor is it an unconstrained group chat or autonomous AGI.
- **Repository Boundaries:** Jester (target product) and JesterBridge (separate integration concept) are distinct repositories and currently out of scope. Direct Jester integration has **not** yet been performed.

---

## 2. Company Hierarchy & Authority Boundaries

```
                    Human Owner / Founder
                    (Final Authority)
                           │
                           ▼
                       CEO Agent
          (Planner, Decomposer, Reporter)
                           │
         ┌─────────┬───────┼─────────┬─────────┬─────────┐
         ▼         ▼       ▼         ▼         ▼         ▼
      Product  Research    UX    Marketing  Developer   QA
```

### Hierarchy Rules & Role Responsibilities

1. **Human Owner / Founder:**
   - Retains ultimate authority over company objectives, strategic decisions, and high-impact repository mutation.
   - Must explicitly authorize code application (`RealRepoApplyGrant`).
   - Human approvals are never synthesized, mocked, or fabricated by agents.

2. **CEO Agent:**
   - Translates human objectives into structured company plans.
   - Decomposes work into typed, validated Directed Acyclic Graphs (`DAGProposal`).
   - Assigns eligible specialist roles and synthesizes progress reports.
   - **Critical Boundary:** The CEO does **NOT** possess unrestricted execution authority. The CEO cannot bypass DAG validation, issue execution grants arbitrarily, skip QA, declare QA pass, self-approve repository apply, or bypass human gates.

3. **Specialist AI Employees (6 Roles):**
   - **Research:** Read-only investigator. Conducts external web/repository grounding, identifies facts, provides source URLs/paths and citations. Cannot modify code or redefine product scope.
   - **Product:** Defines requirements, IN/OUT scope boundaries, user stories, deliverables, and acceptance criteria (`PRD`). Cannot write code or design visual UI.
   - **UX:** Defines user journeys, interaction patterns, screen states, ergonomics, and edge cases (`UX_SPEC`). Cannot alter product scope or write code.
   - **Marketing:** Evaluates positioning, messaging, target audiences, and communication channels. Independent deliverable not consumed by Developer.
   - **Developer:** Technical implementation planner and bounded code modifier. Modifies code **strictly** inside isolated disposable Git worktrees under an explicit `ExecutionGrant`. Has zero direct write access to the primary repository and zero shell authority (`run_command` is denied). Outputs canonical `CODE_PATCH` artifacts.
   - **QA:** Independent quality and verification specialist. Read-only inspector (`QA_REPORT`) and isolated test runner (`QA_EXECUTION_REPORT`). Evaluates `CODE_PATCH` artifacts against requirements in fresh worktrees using application-owned `pytest` execution. Enforces deterministic verdict constraints. Cannot mutate the main repository or approve apply.

---

## 3. Core Architectural Principle: Semantic vs. Deterministic

The foundational invariant of the system is the strict separation between probabilistic reasoning and deterministic authority:

```
┌────────────────────────────────────────────────────────────────────────┐
│                      DETERMINISTIC PYTHON CONTROL                      │
│                                                                        │
│  - Task Eligibility & Role Registry                                    │
│  - CompanyRun Lifecycle State Machine                                  │
│  - DAG Proposal Structural Validation & Cycle Detection                │
│  - Context Assembly with Security Delimiters                           │
│  - Preflight Integrity (SHA-256 byte-for-byte check, size limits)      │
│  - ExecutionGrant Issuance & File Path Confinement                     │
│  - Synchronous PreToolUse Policy Hook Interception                     │
│  - Isolated Git Worktree Lifecycle Management                          │
│  - Application-Owned Verification Execution (pytest, shell=False)      │
│  - Deterministic Verdict Enforcement (test fail -> PASS forbidden)     │
│  - External Repository Lock Acquisition & Crash Recovery               │
│  - Human-Approved RealRepoApply & Non-Destructive Rollback             │
│                                                                        │
│         │ Prompt Construction              ▲ Validated Data            │
│         ▼ (with untrusted delimiters)     │ (parsed JSON contracts)   │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   PROBABILISTIC SPECIALIST LLM                   │  │
│  │                                                                  │  │
│  │   - Specialist reasoning within structured role boundaries       │  │
│  │   - Analysis of supplied contextual evidence                     │  │
│  │   - Structured JSON output adhering to versioned schemas         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

**Agents reason. Application code controls authority and state transitions.**

---

## 4. CompanyRun & Orchestration Lifecycle

Company operations execute under an orchestrated `CompanyRun` state machine:

### States
- `CREATED`: Run initialized with a human objective.
- `PLAN_READY`: CEO has produced a structurally validated DAG proposal.
- `RUNNING`: Execution of DAG nodes or engineering pipeline is underway.
- `READY_FOR_HUMAN_APPLY`: Code changes have passed independent QA verification and await human review.
- `APPLYING`: Human has issued a `RealRepoApplyGrant`; transactional apply is in progress.
- `COMPLETED`: Run finished successfully (either non-code deliverables completed or approved patch applied).
- `FAILED`: Unrecoverable execution failure.
- `BLOCKED`: Required prerequisite, human approval, or verification is missing/blocked.

### Workflow Distinctions

#### A. Non-Code Workflow
```
CREATED → PLAN_READY → RUNNING → COMPLETED
```
Executes research, product specifications, UX guidelines, or marketing deliverables. When all DAG nodes complete, the run transitions directly to `COMPLETED`.

#### B. Engineering Workflow
```
CREATED → PLAN_READY → RUNNING
                          │
                          ▼
            Product + UX Fan-In Prerequisites
                          │
                          ▼
             Developer Planning (Read-Only)
                          │
                          ▼
                   ExecutionGrant
                          │
                          ▼
             Isolated Worktree Mutation
                          │
                          ▼
                  CODE_PATCH Artifact
                          │
                          ▼
                   Independent QA
                    ┌─────┴─────┐
                 FAIL          PASS
                    │            │
               Bounded Repair    │
              (Max 2 iterations) │
                    │            │
                    └───────────►│
                                 ▼
                       READY_FOR_HUMAN_APPLY
                                 🔒 (Autonomous Execution STOPS)
                                 │
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

---

## 5. Engineering Pipeline & Mutation Boundaries

Engineering workflows follow strict containment protocols:

1. **Prerequisite Fan-In:** Developer planning requires verified `PRD` (Product) and `UX_SPEC` (UX) artifacts. Direct jumps to code modification without specifications are forbidden.
2. **Read-Only Planning:** Developer planning proposes files and commands as inert data. Zero code is modified.
3. **ExecutionGrant:** Explicit authorization binding approved file paths (`approved_files_to_modify`, `approved_files_to_create`), size budgets, and the exact `base_commit_hash`.
4. **Isolated Worktree:** Mutation occurs exclusively in `.runs/worktrees/<grant_id>`, checked out at `base_commit_hash`. The primary repository is untouched.
5. **Synchronous Policy Hooks:** PreToolUse hooks intercept tool calls. Writes to unapproved paths and all `run_command` invocations are blocked synchronously.
6. **Application-Owned Verification:** Verification commands (e.g. `pytest`) are deterministically translated and executed by Python subprocesses (`shell=False`, sanitized environment, no secrets).
7. **Canonical `CODE_PATCH`:** Git diff is captured against `base_commit_hash`, including approved untracked files. Stored atomically as `developer_changes.patch` with companion cryptographic metadata.

---

## 6. Independent QA & Controlled Repair Loop

1. **Independent QA Inspection (Read-Only):** QA Agent inspects `CODE_PATCH` against product requirements and UX flows. Emits structured findings and severity ratings (`QA_REPORT`).
2. **Isolated QA Execution:** In a fresh worktree, Python applies the patch (`git apply`), validates the resulting diff, and executes authorized verification tests (`pytest`).
3. **Deterministic Verdicts:**
   - Unexecutable or missing tests → PASS is forbidden (`BLOCKED`).
   - Test failure → PASS is forbidden (`FAIL`).
   - All tests pass with verified coverage → `PASS` permitted.
4. **Controlled Repair Loop:**
   - Triggered on `FAIL` or repairable `BLOCKED`.
   - Developer produces `DEVELOPER_REPAIR_PLAN`.
   - **Mandatory Human Approval:** Each repair iteration requires explicit human founder approval (`founder_approval_id`). Approvals are never fabricated.
   - Fresh worktree created at `base_commit_hash` with previous patch pre-applied.
   - Cumulative patch `CODE_PATCH vN` generated.
   - Independent QA reinspection and re-execution.
   - **Hard Iteration Limit:** `MAX_REPAIR_ITERATIONS = 2`. If iteration 2 fails, execution halts in `REPAIR_LIMIT_REACHED`.

---

## 7. Transactional Real Repository Apply (`RealRepoApply`)

Applying code back to the human owner's primary working tree is a strictly isolated transaction:

1. **External Repository Lock:** Acquired outside target `.git` in `.runs/locks/apply_<hash>.lock`.
2. **Working Tree Cleanliness Precondition:** Target working tree must be 100% clean (`git status --porcelain` empty) before any operation.
3. **Crash Recovery Classification:**
   - `NOT_APPLIED`: Apply proceeds.
   - `EXACT_APPROVED_PATCH_PRESENT`: Idempotent success (no duplicate apply).
   - `PARTIAL_OR_UNKNOWN_STATE`: Fails closed immediately (`CrashRecoveryBlockError`).
4. **Transactional Application:** Prechecked (`git apply --check`), applied (`git apply`), and diff verified against `CODE_PATCH` byte-for-byte.
5. **Non-Destructive Rollback:** If diff mismatch occurs, rolled back via `git apply --reverse`. Destructive commands (`git reset --hard`, `git clean -fd`) are prohibited.
6. **Durable Report:** Materializes `REAL_REPO_APPLY_REPORT` (`real_repo_apply_report.md` + `.meta.json`).

---

## 8. Artifact System & Lineage

Specialists communicate through immutable, content-addressed deliverables:

- **Canonical Artifacts:**
  - `PRD`: Product Requirements Document (`product_report.md`)
  - `UX_SPEC`: UX Specifications (`ux_report.md`)
  - `DEVELOPER_PLAN`: Technical Implementation Plan (`developer_plan_report.md`)
  - `CODE_PATCH`: Canonical Unified Diff (`developer_changes.patch`)
  - `QA_REPORT`: Independent QA Inspection (`qa_report.md`)
  - `QA_EXECUTION_REPORT`: Isolated QA Verdict (`qa_execution_report.md`)
  - `DEVELOPER_QA_REPAIR_REPORT`: Repair Cycle Record (`developer_qa_repair_report.md`)
  - `REAL_REPO_APPLY_REPORT`: Primary Repository Application Audit (`real_repo_apply_report.md`)
- **Integrity:** Every artifact has a SHA-256 checksum calculated over UTF-8 disk bytes and verified upon readback.
- **Lineage:** Artifact metadata records `artifact_id`, `producer_role`, `run_id`, `upstream_artifact_ids`, `base_commit_hash`, and timestamps.
- **Untrusted Context Delimiters:** Upstream artifacts injected into prompts are strictly delimited as untrusted data to prevent prompt injection.

---

## 9. Crash Recovery, Resume & Idempotency

- **State Boundaries:** Service and pipeline state transitions are persisted with durable artifact references.
- **Verified Artifact Reuse:** Completed expensive operations (research, specs, plans, patches) are reused if SHA-256 and lineage remain valid.
- **Tamper Detection:** Stale, modified, or tampered artifacts fail closed on preflight integrity checks.
- **Duplicate Apply Guard:** Re-running apply on an already-applied grant is detected as `EXACT_APPROVED_PATCH_PRESENT` and succeeds idempotently without re-mutating files.

---

## 10. Security & Architecture Invariants

1. Human is the final authority.
2. CEO proposes plans but does not possess unrestricted execution authority.
3. Deterministic application code owns state transitions.
4. Product + UX are required direct prerequisites for Developer engineering execution.
5. Developer mutation occurs exclusively in isolated worktrees.
6. `CODE_PATCH` is the canonical engineering deliverable.
7. QA independently verifies engineering work.
8. QA FAIL cannot reach the Human apply gate.
9. Repair loop is strictly bounded (maximum 2 iterations).
10. QA PASS reaches `READY_FOR_HUMAN_APPLY`; autonomous execution stops there.
11. Target repository remains unchanged before explicit Human approval.
12. Only explicit Human approval (`RealRepoApplyGrant`) authorizes `RealRepoApply`.
13. Duplicate apply fails closed or reports idempotent completion.
14. Tampered or stale artifacts fail closed.
15. Crash/resume reuses only verified durable state.
16. Jester software product remains unconnected (real connection deferred to STEP 19C).
17. JesterBridge remains untouched and out of scope.

---

## 11. Generic Project & Repository Foundation (STEP 19B)

STEP 19B introduces a typed, generic integration layer allowing JesterAICompany to operate against registered external software projects without hardcoding any specific repository or product into Core.

### 1. Domain Entities
- **`Project`**: Immutable entity binding a `project_id`, descriptive metadata, exactly one primary `RepositoryRef`, and an overarching `RepositoryPolicy`.
- **`RepositoryRef`**: Immutable configuration specifying `repository_id`, safe canonical filesystem `root_path`, configured `target_branch`, and optional `expected_remote`.
- **`RepositoryPolicy`**: Immutable security policy defining coarse maximum Project authority (`read_allowed`, `mutation_allowed`, `denied`).
  - **Precedence Rule:** `DENIED` strictly overrides `ALLOWED` (fail-closed).
  - **Path Traversal & Escape:** Strict path normalization blocks `..` traversals, absolute paths outside repo root, and symlink escapes.
- **`RepositoryStateFingerprint`**: Read-only, deterministic snapshot of observed runtime state (`head_commit_hash`, `branch_name`, `is_clean`, `state_sha256`). Inspection performs zero Git mutations.
- **`ProjectRegistry`**: Application/Human-owned registry for registering, resolving, and listing projects. Enforces unique project and repository IDs and validates repository health and branch conformity upon registration.

### 2. Dual Authority Model (Project Authority vs. Task Authority)

```
               Human / Application Authority
                            │
                            ▼
                     ProjectRegistry
                            │
                            ▼
                RepositoryPolicy (Project Authority)
                - Coarse maximum repository boundary
                - mutation_allowed, denied
                            │
                            ▼
                 ExecutionGrant (Task Authority)
                - Narrower, task-specific developer scope
                - approved_files_to_modify, approved_files_to_create
                            │
                            ▼
                Isolated Disposable Git Worktree
```
- **Invariant:** `ExecutionGrant` mutation scope **MUST** be a strict subset of `RepositoryPolicy.mutation_allowed` and must not intersect `RepositoryPolicy.denied`.
- Both layers must validate; any violation fails closed.

### 3. Provenance & Cross-Project Protection
- **Run Binding:** Project-backed `CompanyRun` instances carry immutable bindings: `project_id`, `repository_id`, `target_branch`, and `base_commit_hash`.
- **Task Inheritance:** Tasks inherit `project_id` from the run; CEO output cannot alter or redirect project identity.
- **RealRepoApply Boundary:** `RealRepoApplyProposal` and `RealRepoApplyGrant` are bound to `project_id` and `repository_id`.
- **Cross-Project Invariant:** A proposal, grant, or patch for Project A cannot authorize or mutate Project B under any circumstances (`CrossProjectMismatchError` fails closed with zero target mutation).

### 4. Current Stage Status
- **Generic Project / Repository Foundation:** Implemented, verified, and tested.
- **Control Center UI / API:** Deferred to later milestones.

---

## 12. Generic Project Knowledge Core & Read-Only Repository Integration (STEP 19C-B)

STEP 19C-B introduces the first generic, typed Project Knowledge layer in JesterAICompany and proves it against the real Jester repository (`C:\Users\fiord\.gemini\antigravity-ide\scratch\jester`) in strictly read-only mode.

### 1. Conceptual Triad: Project Knowledge vs. Run Artifacts vs. Company Memory

```
┌────────────────────────────────────────────────────────────────────────┐
│                          AGENT CONTEXT                                 │
│                                                                        │
│   System / Role Contract                                               │
│ + Human Objective                                                      │
│ + Security Constraints                                                 │
│ + Relevant Project Knowledge (Configured, durable repository truth)   │
│ + Required Run Artifacts     (Produced during current CompanyRun)      │
│ + Future Company Memory      (Cross-run learned operational knowledge) │
│ + Execution Authority        (Task-specific grants where applicable)   │
└────────────────────────────────────────────────────────────────────────┘
```

- **Project Knowledge:** Durable, configured knowledge belonging to the target Project (e.g. system prompts, schemas, architecture specs, rules). It is reference DATA from an external repository.
- **Run Artifacts:** Transient, verified outputs created during the current `CompanyRun` (e.g., `ProductSpecification`, `UXSpecification`, `PatchProposal`).
- **Company Memory:** Future cross-run learned operational knowledge (deferred, NOT implemented in Core V1).
- **Invariant:** Project Knowledge and Run Artifacts remain structurally distinct within `ContextEnvelope` with zero lifecycle conflation.

### 2. Extensible Knowledge Domains & Truth Scopes

- **Extensible Domains:** Domains are normalized strings (`normalize_domain(slug)`) validated via `^[a-z0-9_\-\.]+$` rather than a closed enum. Any project can configure custom domains (e.g., `architecture`, `product`, `brand`, `backend`, `frontend`, `security`, `payments`, `compliance`) without modifying Core.
- **Source Authority:** Classifies trust and durability:
  - `AUTHORITATIVE`: Binding durable project truth.
  - `SUPPORTING`: Explanatory context; subordinate to authoritative.
  - `EXPLORATORY`: Roadmaps and non-final proposals.
  - `HISTORICAL`: Superseded records, archival benchmarks.
  - `GENERATED`: Ephemeral build caches, test dumps.
  - `DENIED`: Secrets, credentials, private configs (fails closed).
  - `IGNORE`: Noise, IDE configs.
- **Truth Scopes:** Distinguishes intended truth from observed truth to prevent false conflicts:
  - `SPECIFICATION`: Intended product/architectural requirements.
  - `IMPLEMENTATION`: Executable source code reflecting current reality.
  - `BEHAVIOR`: Persona guidelines and rhetorical directives.
  - `CONFIGURATION`: Environment defaults, ports, quotas.
  - `REFERENCE`: Background facts and benchmarks.

### 3. Separation of Source Metadata and Role Policy

- **`ProjectKnowledgeSource`:** Describes WHAT the knowledge is, WHERE it resides, its domain, authority, truth scope, and load policy (`FULL_DOCUMENT`, `SECTION_EXCERPT`, `METADATA_ONLY`). Sources do **not** intrinsically belong to any employee role.
- **`RoleKnowledgePolicy`:** Separately defines which primary/secondary domains and explicit source inclusions/exclusions an employee role consumes (e.g. Marketing vs. Developer).
- **`ProjectKnowledgeManifest`:** Immutable collection of sources bound to `project_id` and `repository_id`.

### 4. Freshness: Repository Drift vs. Source Drift

- **Revision Provenance:** Excerpts capture `repository_revision` and cryptographic `content_sha256`.
- **Drift Distinction:** If an unrelated file advances the repository HEAD commit, the catalog detects `repository_drift`, but because the selected source file's `content_sha256` remains identical, the excerpt remains valid and fresh.
- If the selected source file changes, disappears, or becomes denied, freshness fails closed.

### 5. Security & Trust Boundaries

- **Untrusted Data Delimiters:** Every Project Knowledge excerpt injected into an agent prompt is wrapped inside deterministic `UNTRUSTED REPOSITORY DATA` delimiters with explicit notices instructing the model never to obey instructions embedded within external repository text.
- **Deterministic Secret Denial:** Sources marked `DENIED` or matching `RepositoryPolicy.denied` fail closed before any content is read from disk.
- **Zero Real Repository Mutation:** All reading operates in place with zero worktree creation, zero patches, zero grants, and zero disk mutations. Real Jester remains 100% clean and identical to baseline commit `700fa1254855885a4c5a175f203b0e278e993288`.


