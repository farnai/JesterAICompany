# ტესტების შესრულების ანგარიში (TEST EXECUTION REPORT)

**აუდიტის ფაზები:** Phase H (სცენარული ვალიდაცია 1–12) და Phase I (ინვარიანტული / ადვერსარიული ტესტირება)  
**თარიღი:** 2026-11-23 | **გარემო:** Windows, Python `3.13.7`, Node.js/Vitest, `agy.exe` `1.3.6`, კომიტი `b3b31b6`  
**არადესტრუქციულობის დადასტურება:** ყველა აუდიტის ტესტი გაეშვა იზოლირებულ `tempfile.TemporaryDirectory()` გარემოში. საბოლოო შემოწმებით (`git status --porcelain`) როგორც `JesterAICompany`, ისე `Desktop/Jester` დარჩა 100% უცვლელი.

> [!IMPORTANT]
> **გამჭვირვალობის წესი:** ქვემოთ თითოეულ ტესტზე მკაფიოდ მითითებულია შესრულების მეთოდი: **Baseline Executed (Automated)**, **Live Local HTTP / Subprocess**, **Simulated (Mock Runtime)**, **Real-Model Observed**, ან **Blocked / Not Executed**. არცერთი შედეგი არ არის გაყალბებული ან გამოგონილი.

---

## 1. Baseline ტესტ-სუიტების შედეგები

| სუიტი | ბრძანება | შედეგი | ხანგრძლივობა | შენიშვნა |
| :--- | :--- | :--- | :---: | :--- |
| **Frontend (Vitest)** | `npm --prefix frontend test` | **PASS** — 13 ფაილი, **74/74 passed** | 4.22s | სტაბილური, სწრაფი |
| **Python (Bare `pytest`)** | `pytest -q --tb=short` | **ERROR (8 collection errors)** | <2s | `pyproject.toml`-ის არარსებობა (`ModuleNotFoundError`) + აგროვებს `scratch/test_*.py`-ს (`DEF-030`) |
| **Python (Full `tests/`)** | `python -m pytest tests/ -q --tb=short` | **FAIL** — **901 passed, 16 failed, 10 errors, 2 skipped** | **632.68s (10m 32s)** | რეალური ცოცხალი `agy` გამოძახებები გაჟონა 5 unit ტესტიდან + 15 ტესტი მიბმულია Desktop Jester-ზე (`DEF-024`) |

### Baseline Python-ის 16 ჩავარდნისა და 10 შეცდომის ძირეული მიზეზების განაწილება

| კატეგორია | რაოდენობა | კონკრეტული ტესტები | ძირეული მიზეზი |
| :--- | :---: | :--- | :--- |
| **Desktop `Jester` რეპოზე მყარი მიბმა** | **10 Errors + 5 Fails** | `test_jester_live_knowledge.py` (8E+1F), `test_jester_live_run.py` (2E), `test_step23b5b::test_target_jester_repository_untouched`, `test_step24_4_3::test_10_canonical_jester_unchanged`, `test_target_repository_guard.py` (2F) | ტესტები ითხოვენ Desktop `Jester`-ზე ძველ კომიტებს (`2173b2dd...`, `cb7135ca...`), ბრენჩ `main`-ს და 2 შეცვლილ ფაილს; რეალურად რეპო სუფთაა ბრენჩზე `codex/home-geometric-humanism` (`e394ecc`) |
| **გატეხილი Mock (`subprocess.run` vs `Popen`) — გაჟონა Live `agy`-ზე!** | **5 Fails** | `test_runtime_adapter.py`: `test_execution_success_captures_stdout`, `test_execution_failure_captures_stderr`, `test_execution_timeout_handled`, `test_executable_not_found_handled`, `test_product_agent_runtime_parity` | ტესტები აყალბებენ `subprocess.run`-ს, მაგრამ `runtime.py` იყენებს `subprocess.Popen`-ს → 5-ვე ტესტმა რეალურად გამოიძახა **ცოცხალი `agy` + Gemini 4 Neon**! (ასევე დაფიქსირდა Windows `kill_process_tree` გაფრთხილება PID 38172-ზე) |
| **ორკესტრაციის კონტრაქტის რეგრესიები** | **4 Fails** | `test_company_orchestration_engine.py`: `test_requirement_m_af_developer_node_fails_closed`, `test_requirement_n_unknown_role_rejected`, `test_requirement_t_artifact_verification_failure_fails_closed`, `test_requirement_ab_ac_specialist_failure_blocks_dependents` | STEP 23B.5-C recovery-ის ცვლილებებმა შეცვალა exception/state კონტრაქტი (`RUNNING` დაბრუნდა `FAILED`-ის ნაცვლად) და დაემატა `spec_dur` ბაგი |
| **Windows Worktree File-Lock კრაში** | **1 Fail** | `test_qa_execution.py::test_live_qa_agent_failing_proof` | `PermissionError: [WinError 32]` + `git worktree remove: Permission denied` |
| **Timeout Error Message რეგრესია** | **1 Fail** | `test_step23b5b_runtime_reliability.py::test_durable_failed_state_and_telemetry_attribution` | მოელოდა `"timed out"`, მიიღო `'Timeout retry budget exhausted.'` (ასევე გაგრძელდა 2×300 წამი = 10 წუთი!) |

---

## 2. დამოუკიდებელი აუდიტის ვალიდაციის ცხრილი (Scenarios 1–12 + Security & Adversarial)

აუდიტის სკრიპტები: `audit_validation.py` და `audit_validation_part2.py` (შენახულია საუბრის `scratch/` დირექტორიაში).

| Test ID | სცენარი / ინვარიანტი | გარემო | შესრულების მეთოდი | მოსალოდნელი შედეგი | რეალური შედეგი | სტატუსი | მტკიცებულება / ლოგი |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **AUDIT-SEC-01** | სცენარი 7/უსაფრთხოება: RCE `POST /api/tasks/{id}/execute` `verify_cmd`-ით + CORS `*` | Isolated `ControlCenterServer` (`127.0.0.1:0`) | **Live Local HTTP** | უარყოფილი (Auth/Allowlist), არანაირი CORS `*` | `rce_proof_marker.txt` შეიქმნა (`RCE_CONFIRMED`), `CORS=*`, QA `PASSED` | **FAIL** (`DEF-001`) | `audit_validation_results.json` |
| **AUDIT-SEC-02** | უსაფრთხოება: `/api/artifacts/content?path=../.env` | Isolated `ControlCenterServer` | **Live Local HTTP** | HTTP 403/404 `.runs/`-ის გარეთ | **HTTP 200**, დაბრუნდა `AUDIT_SECRET=SENTINEL_VALUE_9988` | **FAIL** (`DEF-003`) | `audit_validation_results.json` |
| **AUDIT-SEC-03** | უსაფრთხოება: `/assets/../../package.json` Path Traversal | Isolated `ControlCenterServer` | **Live Raw HTTP** (`http.client`) | HTTP 403/404 `frontend/dist`-ის გარეთ | **HTTP 200**, დაბრუნდა `frontend/package.json` | **FAIL** (`DEF-002`) | `audit_validation_results.json` |
| **AUDIT-SEC-05** | სცენარი 7: სინთეზური `founder_grant_*` და `founder_repair_*` | Workspace კოდი | **Static Code Verification** | 0 ფაბრიკირებული approval ID | `synthetic_grant=True`, `synthetic_repair=True` (`engineering_pipeline.py:591,870`) | **FAIL** (`DEF-004`) | `audit_validation_results.json` |
| **AUDIT-SEC-06** | უსაფრთხოება: `hook_policy.py` კვოტა, 2nd-write, Windows `\`, `agy` 1.3.6 tools | Isolated temp workspace | **Live Subprocess** (`hook_policy.py`) | ბლოკავს 10KB-ს 10B ლიმიტზე; ემთხვევა `authorize_tool_mutation`-ს | 10KB=`allow`, 2nd-write=`deny` (in-mem=`True`), win-sep=`deny`, `read_file`=`deny` | **FAIL** (`DEF-006`) | `audit_validation_results.json` |
| **AUDIT-BUG-01** | სცენარი 1 (UI/UX): `UI_UX_CHANGE` (`["ux", "developer"]`) ნაკადი | Isolated git repo | **Simulated** (Mock Runtime + Real Pipeline) | Developer იწყება UX სპეცით | **კრაში:** `EngineeringPreconditionError` (`engineering_pipeline.py:207`) | **FAIL** (`DEF-007`) | `audit_validation_part2_results.json` |
| **AUDIT-BUG-02** | სცენარი 3 (Visual UX): 3 არტეფაქტი (`PRD`+`UX`+`UX_PROTOTYPE`) Developer Planning-ში | Isolated `CompanyService` | **Direct Python Call** | იღებს არასავალდებულო მე-3 პროტოტიპს | **კრაში:** `HandoffPolicyError: requires exactly 2 input artifacts, found 3` | **FAIL** (`DEF-008`) | `audit_validation_part2_results.json` |
| **AUDIT-BUG-03** | სცენარი 10 (False Completion): QA Verification ცარიელი `recommended_verification_actions`-ით | Isolated worktree + git diff | **Simulated** (Real `git apply` + Mock QA Eval) | დეტერმინისტული `BLOCKED` (0 ტესტი) | დააბრუნა **`verdict=PASS`** 0 გაშვებული ტესტით! | **FAIL** (`DEF-010`) | `audit_validation_part2_results.json` |
| **AUDIT-BUG-04** | სცენარი 10: QA Inspection 14A ფალსიფიცირებული `VERIFIED` კატეგორიები | In-memory parser | **Direct Python Call** | `NOT_EXECUTED` / `UNVERIFIED` | გააყალბა `FUNCTIONAL_CORRECTNESS = VERIFIED` ტესტების გაშვებამდე | **FAIL** (`DEF-011`) | `audit_validation_results.json` |
| **AUDIT-BUG-05** | სცენარი 12 (Parser/Tool): `developer_mutation.py` ტექსტზე `{...}` + fenced JSON | In-memory parser | **Direct Python Call** | სუფთა JSON პარსირება | **კრაში:** `UnboundLocalError: cannot access local variable 'json_str'` | **FAIL** (`DEF-014`) | `audit_validation_results.json` |
| **AUDIT-BUG-06** | სცენარი 6/უსაფრთხოება: გაყალბებული upstream არტეფაქტის SHA-256 შემოწმება | Isolated `CompanyService` | **Simulated** (Tamper on disk) | უარყოფა SHA-256 შეუთავსებლობით | დაიბლოკა `ContextAssemblyError: SHA-256 integrity mismatch` (შენიშვნა: `spec_dur` ბაგი ეხება output არტეფაქტის მარცხს ხაზ 5669/5684/5697-ზე) | **PASS** (Upstream Check) | `audit_validation_part2_results.json` |
| **AUDIT-BUG-07** | სცენარი 9 (Restart): `Project.add_task` არსებობა რესტარტის apply გზაზე | Core model | **Direct Inspection** | `Project.add_task` არსებობს | `hasattr(Project, 'add_task') == False` → `AttributeError` რესტარტზე | **FAIL** (`DEF-020`) | `audit_validation_part2_results.json` |
| **AUDIT-BUG-08** | სცენარი 9 (Crash Recovery): `EXACT_APPROVED_PATCH_PRESENT` იდემპოტენტობა | Isolated `RealRepoApply` | **Live Local Git Apply** | იდემპოტენტური წარმატება (`README:223`) | აგდებს `TargetRepositoryDirtyError`-ს | **FAIL** (`DEF-020`) | `audit_validation_part2_results.json` |
| **AUDIT-BUG-09A** | კონტრაქტი: CEO prompt `capability: "audit"` vs `orchestrator.py` | Parser | **Direct Python Call** | მიღებულია | უარყოფილია `PlanValidationError` (`read_only_audit` მოითხოვება) | **FAIL** (`DEF-012`) | `audit_validation_results.json` |
| **AUDIT-BUG-09B** | კონტრაქტი: CEO prompt `task_category: "FEATURE"/"GENERAL"` vs `ceo_contract.py` | Parser | **Direct Python Call** | მიღებულია | ორივე უარყოფილია `CEODecisionValidationError`-ით | **FAIL** (`DEF-012`) | `audit_validation_results.json` |
| **AUDIT-BUG-10** | ტელემეტრია: `engineering_pipeline.py:1024` `qa_exec_art.task_id` | Core model | **Direct Inspection** | ვალიდური ატრიბუტი | `hasattr(Artifact, 'task_id') == False` → ჩაყლაპულია `except: pass`-ით | **FAIL** (`DEF-022`) | `audit_validation_results.json` |
| **AUDIT-BUG-11** | სცენარი 6 (Context Loss): 29,038-სიმბოლოიანი პრომპტი `AntigravityRuntime`-ში | Isolated `AntigravityRuntime` | **Direct `build_command`** | არანაირი ჩუმი ჩამოჭრა | ჩამოიჭრა `28000`-ზე; ბოლოში მყოფი სქემის მარკერი დაიკარგა (`tail_schema_lost=True`) | **FAIL** (`DEF-018`) | `audit_validation_results.json` |
| **AUDIT-BUG-12** | CEO ორკესტრაცია: ნაგულისხმევი `is_production=False` + ტელემეტრია | Isolated `CompanyService` | **Simulated** (SpyRuntime) | CEO LLM გამოძახება ან `source=HEURISTIC` | 0 CEO LLM გამოძახება შეფასება/გუნდზე, თუმცა ლოგში წერია `MODEL` | **FAIL** (`DEF-013`) | `audit_validation_part2_results.json` |
| **AUDIT-ADV-01** | ადვერსარიული: CEO JSON თვითავტორიზაცია `allow_direct_developer: true` | DAG ვალიდატორი | **Direct Python Call** | უარყოფა `team_selection`-ის გარეშე | DAG ვალიდატორმა დაუშვა direct developer Product+UX-ის გვერდის ავლით | **FAIL** (`DEF-021`) | `audit_validation_results.json` |
| **AUDIT-ADV-02** | ადვერსარიული: გამოყენებული `RealRepoApplyGrant`-ის replay | Isolated `RealRepoApply` | **Live Local Git Apply** | უარყოფა `GrantReplayedError`-ით | უარყოფილია: `GrantReplayedError: has already been consumed` | **PASS** | `audit_validation_part2_results.json` |
| **AUDIT-SCEN-02** | სცენარი 2: ბუნდოვანი მოთხოვნა („Make it better“) | Isolated `CompanyService` | **Simulated** (SpyRuntime) | პაუზა `WAITING_FOR_CLARIFICATION` | გადავიდა `WAITING_FOR_CLARIFICATION`-ში (0 LLM გამოძახებით, ჰევრისტიკით) | **PASS** (Heuristic) | `audit_validation_results.json` |
| **AUDIT-SCEN-03** | სცენარი 3: მრავალ-აგენტიანი არაკოდური DAG (Research→Product→UX→Marketing) | Isolated `CompanyService` | **Simulated** (Valid Schema Mocks) | 4-ვე ელემენტი `COMPLETED` რიგითობით | `COMPLETED`, 4/4 work items `COMPLETED`, 0 შეცდომა | **PASS** (Simulated) | stdout log (Part 3) |
| **AUDIT-SCEN-05** | სცენარი 5: აგენტის Auth/401 ჩავარდნა | Isolated `CompanyService` | **Simulated** (401 Runtime) | დაუყოვნებლივი `FAILED`, 0 retry | `FAILED` 1 ცდაზე (`total_calls=2`: 1 CEO + 1 Research), retry დაიბლოკა | **PASS** (Simulated) | `audit_validation_results.json` |
| **AUDIT-SCEN-08** | სცენარი 8: 5 კონკურენტული `POST /api/company-runs` | Isolated `ControlCenterServer` | **Live Local HTTP** (5 threads) | მაქს. 1× `201`, 4× `409` | **5/5 დააბრუნა HTTP `201`** (TOCTOU race condition) | **FAIL** (`DEF-015`) | `audit_validation_results.json` |
| **AUDIT-SCEN-09B** | სცენარი 9: მკვდარი PID `999999` stale lock ფაილი `RealRepoApplyLock`-ში | Isolated tempdir | **Live Local Lock Test** | stale lock-ის აღმოჩენა და აღდგენა | **მუდმივი ჩიხი:** `ConcurrentApplyError: already locked by PID 999999` | **FAIL** (`DEF-020`) | stdout log |
| **AUDIT-SCEN-11** | სცენარი 11: გაშვების გაუქმება / შეწყვეტა (`CANCELLED`) | `CompanyRunState` & API | **Inspection** | `CANCELLED` სტატუსი და `/cancel` API | არ არსებობს არც სტატუსი, არც endpoint | **FAIL** (`DEF-016`) | `audit_validation_results.json` |
| **AUDIT-SCEN-01/04 (Live Model)** | სცენარი 1 & 4: ცოცხალი End-to-End 7-აგენტიანი კოდის ცვლილება + Repair Loop რეალურ `agy` მოდელზე | Real `agy` v1.3.6 (Gemini 4 Neon) | **Blocked / Not Executed** (დამატებით ნანახია `task-39`-ის ცოცხალი `agy` პასუხები და ისტორიული `.runs/` ლოგები) | სრული E2E კოდის ცვლილება | არ გაეშვა აუდიტის ფარგლებში `DEF-004`/`DEF-005`/`DEF-006`/`DEF-007`/`DEF-010` ბლოკერებისა და Desktop `Jester`-ის ბრენჩის შეუთავსებლობის გამო; `test_service_real_execution.py` გავიდა `task-39`-ში, ხოლო ისტორიული `.runs/` აჩვენებს 9–23 წთ ხანგრძლივობას და 28.9% FAILED წილს | **BLOCKED** | `task-39.log`, `.runs/company_runs/` |

---

## 3. ტესტირების საბოლოო შეფასება

- **სიმულირებული არაკოდური ნაკადი, SHA-256 ლინეაჟის შემოწმება, Grant Replay დაცვა (`AUDIT-ADV-02`), 401 Auth Fail-Closed (`AUDIT-SCEN-05`) და Frontend Vitest (74/74) რეალურად მუშაობს.**
- **თუმცა რეალური პროდაქშენ გამოყენება დაბლოკილია** 6 დადასტურებული P0 უსაფრთხოების/მმართველობის ხარვეზით და 11 დადასტურებული P1 ორკესტრაციული/QA/კონტრაქტული დეფექტით.
