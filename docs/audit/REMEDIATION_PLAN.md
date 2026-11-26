# გამოსწორების ეტაპობრივი გეგმა (REMEDIATION PLAN)

**აუდიტის ფაზა:** Phase L — ძირეულ მიზეზებზე დაფუძნებული, დამოკიდებულებებით დალაგებული რემედიაციის გეგმა  
**მნიშვნელოვანი გაფრთხილება (STEP 9):** ეს გეგმა არის **შემოთავაზება დამფუძნებლის დასამტკიცებლად**. არცერთი ფაილი ჯერ არ შეცვლილა. იმპლემენტაცია დაიწყება მხოლოდ დამფუძნებლის ცალსახა თანხმობის შემდეგ.

---

## Stage 0 — უსაფრთხოების გადაუდებელი შეკავება (Emergency Security Containment)
- **მიზანი:** სრულად აღმოფხვრას P0 მოწყვლადობები (RCE, Path Traversal, Wildcard CORS, არაიზოლირებული Repair Planning, გაუმართავი `hook_policy.py`) და გადაამოწმოს `HYP-01`.
- **გამოსწორებული დეფექტები:** `DEF-001`, `DEF-002`, `DEF-003`, `DEF-005`, `DEF-006` + `HYP-01` ვერიფიკაცია.
- **შესაცვლელი ფაილები:**
  - `jester_ai_company/control_center.py`
  - `jester_ai_company/service.py` (`get_artifact_content`, `execute_developer_qa_repair_loop`)
  - `jester_ai_company/policy_hook.py`
  - `jester_ai_company/runtime.py`
  - `jester_ai_company/execution.py`
- **იმპლემენტაციის სტრატეგია:**
  1. გათიშეთ თვითნებური `verify_cmd` HTTP API-დან (`control_center.py:729-795`); დატოვეთ მხოლოდ ტიპიზებული `VerificationAction` (`shell=False`).
  2. შეცვალეთ `Access-Control-Allow-Origin: *` მკაცრი ლოკალური origin allowlist-ით და დაამატეთ per-session Bearer ტოკენი ყველა მუტაციურ ენდფოინთზე.
  3. დაამატეთ `is_relative_to(FRONTEND_DIST_DIR.resolve())` შემოწმება `/assets/` და `/portraits/`-ში (`DEF-002`); შეზღუდეთ `get_artifact_content` მხოლოდ `self.output_dir.resolve()`-ით და აკრძალეთ `.env`/`.git` (`DEF-003`).
  4. გადაიტანეთ Developer Repair Planning იზოლირებულ planning worktree-ში `target_repo`-დან `install_planning_policy_hook`-ით (`DEF-005`).
  5. გააერთიანეთ `hook_policy.py` და `authorize_tool_mutation` ერთ ლოგიკაში: დაამატეთ `read_file`/`write_file`/`edit_file`, Windows `\` ნორმალიზაცია, 2nd-write support, `max_bytes_written` / `max_files_changed` აღრიცხვა; დააყენეთ read-only hook ყველა არა-მუტაციურ აგენტზე (`DEF-006`).
  6. ჩაატარეთ 1 იზოლირებული ცოცხალი პრობა `agy.exe` 1.3.6-ზე იმის დასადგენად, მუშაობს თუ არა `PreToolUse` hook `--dangerously-skip-permissions`-თან ერთად (`HYP-01`). თუ არ მუშაობს — შეცვალეთ გაშვების რეჟიმი `--mode`/`--sandbox`/სანქცირებულ ფლაგებზე.
- **რისკები და მიტიგაცია:** Frontend-მა უნდა გაგზავნოს session ტოკენი (მივაწოდოთ Bootstrap endpoint/cookie-ით იგივე ლოკალური origin-იდან); არ დაირღვეს არსებული Vitest ტესტები.
- **ვერიფიკაციის ტესტები:** `AUDIT-SEC-01`, `AUDIT-SEC-02`, `AUDIT-SEC-03`, `AUDIT-SEC-06` ყველა უნდა გადავიდეს **PASS**-ზე.
- **მიღების კრიტერიუმები:** 0 P0 უსაფრთხოების მოწყვლადობა; 100% read-only hook დაფარვა არა-მუტაციურ აგენტებზე.
- **სირთულის შეფასება:** საშუალო–მაღალი (2–3 დღე).

---

## Stage 1 — მმართველობა (Governance), QA მთლიანობა და კოდის კრაშების აღმოფხვრა
- **მიზანი:** აღმოფხვრას ყალბი თანხმობები, QA-ს 0-ტესტიანი `PASS` ხვრელი, 14A ყალბი `VERIFIED` სტატუსები და დეტერმინისტული კრაშები.
- **გამოსწორებული დეფექტები:** `DEF-004`, `DEF-010`, `DEF-011`, `DEF-014`, `DEF-017`, `DEF-021`, `DEF-027`.
- **შესაცვლელი ფაილები:**
  - `jester_ai_company/engineering_pipeline.py`
  - `jester_ai_company/qa_execution.py`
  - `jester_ai_company/qa_result.py`
  - `jester_ai_company/developer_mutation.py`
  - `jester_ai_company/developer_result.py`
  - `jester_ai_company/service.py` (`spec_dur`, QA 14A `target_repo_root`, QA 14B `timeout`)
  - `jester_ai_company/ceo_contract.py` & `dag.py` (`allow_direct_developer` თვითავტორიზაციის აკრძალვა)
  - `jester_ai_company/control_center.py` (`/approve` სავალდებულო `founder_approval_id`)
- **იმპლემენტაციის სტრატეგია:**
  1. წაშალეთ სინთეზური `founder_grant_*`, `founder_repair_*`, `founder_ui_*` ID-ები; შემოიღეთ მკაფიო გამიჯვნა: sandbox worktree იყენებს სისტემურ `SandboxExecutionToken`-ს (არა `founder_approval_id`-ს!), ხოლო რეალური რეპოს Apply და (საჭიროების შემთხვევაში) Repair Escalation მოითხოვს ავთენტურ ადამიანის თანხმობას.
  2. `qa_execution.py:550`: გახადეთ `len(verification_results) == 0` ყოველთვის `BLOCKED` ნებისმიერ `CODE_PATCH`-ზე.
  3. `qa_result.py:497-533`: წაშალეთ სინთეზური `VERIFIED` default-ები (ჩაანაცვლეთ `NOT_EXECUTED`-ით).
  4. გაასწორეთ `json_str = None` (`developer_mutation.py:156`), `spec_dur` (`service.py:5655`), QA 14A `target_repo_root` და QA 14B კონფიგურირებადი `timeout` (180–300s).
  5. აკრძალეთ CEO-ს JSON-იდან `allow_direct_developer`-ის თვითავტორიზაცია `team_selection`-ის გარეშე; დაამატეთ `verification_actions` `DeveloperTaskResult`-ში.
- **დამოკიდებულებები:** Stage 0.
- **ვერიფიკაციის ტესტები:** `AUDIT-SEC-05`, `AUDIT-BUG-03`, `AUDIT-BUG-04`, `AUDIT-BUG-05`, `AUDIT-ADV-01` → **PASS**.
- **სირთულის შეფასება:** საშუალო (2 დღე).

---

## Stage 2 — ორკესტრაციის მთლიანობა, UX/Dev კონტრაქტები და მდგომარეობის მანქანა
- **მიზანი:** გაასწოროს გატეხილი სამუშაო ნაკადები (`UI_UX_CHANGE`, ვიზუალური კონცეპტები, Design Approval, Mid-run Clarify, Cancellation, Concurrency Lock, RealRepoApply Recovery).
- **გამოსწორებული დეფექტები:** `DEF-007`, `DEF-008`, `DEF-009`, `DEF-015`, `DEF-016`, `DEF-020`, `DEF-025`, `DEF-026`.
- **შესაცვლელი ფაილები:**
  - `jester_ai_company/engineering_pipeline.py`
  - `jester_ai_company/service.py`
  - `jester_ai_company/orchestrator.py`
  - `jester_ai_company/real_repo_apply.py`
  - `jester_ai_company/worktree.py`
  - `jester_ai_company/control_center.py`
  - `frontend/src/api/client.ts` & `frontend/src/hooks/useCompanyState.ts`
- **იმპლემენტაციის სტრატეგია:**
  1. გახსენით `UI_UX_CHANGE` (`["ux", "developer"]`) და 3-არტეფაქტიანი (`PRD + UX_SPEC + UX_PROTOTYPE`) გზები `engineering_pipeline.py`-სა და `execute_developer_planning_task`-ში.
  2. დაამატეთ Control Center-ში `/design-approval`, `/design-reject` და `/cancel` ენდფოინთები + `CompanyRunState.CANCELLED` + აქტიური subprocess-ის შეწყვეტა.
  3. გაასწორეთ `control_center.py:1072` resume (`PLAN_READY` და `RUNNING`) და დაამატეთ `threading.RLock` TOCTOU race-ის მოსასპობად.
  4. გაასწორეთ `RealRepoApply`: `default_proj.tasks.append(...)`, `EXACT_APPROVED_PATCH_PRESENT` იდემპოტენტური აღდგენა და `RealRepoApplyLock` stale-PID შემოწმება.
  5. გაასწორეთ Windows `worktree remove` retry + `client.ts` timeout (60–120s სინქრონულ ჩატ/clarify-ზე) + მოაშორეთ `mock=true` `useCompanyState.ts:274`-დან.
- **დამოკიდებულებები:** Stage 0, Stage 1.
- **ვერიფიკაციის ტესტები:** `AUDIT-BUG-01`, `AUDIT-BUG-02`, `AUDIT-BUG-07`, `AUDIT-BUG-08`, `AUDIT-SCEN-08`, `AUDIT-SCEN-09B`, `AUDIT-SCEN-11` → **PASS**.
- **სირთულის შეფასება:** მაღალი (3–4 დღე).

---

## Stage 3 — აგენტების პრომპტ-სქემების სინქრონიზაცია, CEO რეალური რეჟიმი და კონტექსტის გადაცემა
- **მიზანი:** აღმოფხვრას აგენტის ინსტრუქციებსა და პარსერებს შორის წინააღმდეგობები, ჩართოს რეალური CEO გადაწყვეტილებები პატიოსანი ტელემეტრიით და აღადგინოს დაკარგული კონტექსტი.
- **გამოსწორებული დეფექტები:** `DEF-012`, `DEF-013`, `DEF-018`, `DEF-019`, `DEF-022`.
- **შესაცვლელი ფაილები:**
  - `.agents/agents/{ceo,product,research,ux,marketing,developer,qa}/agent.md`
  - `jester_ai_company/runtime.py` (28k ჩამოჭრის ჩანაცვლება stdin/file გადაცემით)
  - `jester_ai_company/service.py`, `ceo_contract.py`, `knowledge.py`, `engineering_pipeline.py` (ხაზი 1024), `telemetry.py`
- **იმპლემენტაციის სტრატეგია:**
  1. გაასწორეთ ყველა `agent.md` (`read_only_audit`, სწორი `TaskCategory`, Developer Mode C, UX `concepts`, JSON სქემები).
  2. `runtime.py`: შეწყვიტეთ პრომპტის ჩუმი ჩამოჭრა 28,000 სიმბოლოზე; გამოიყენეთ stdin ან დროებითი prompt ფაილი (ან fail-closed შეცდომა).
  3. გადაეცით `ContextEnvelope` და `role_knowledge` `research`, `marketing`, `qa` და CEO შეფასების/გუნდის შერჩევის პრომპტებს; აღადგინეთ `max_sources` ლიმიტი.
  4. გაასწორეთ `decision_source` (`MODEL` vs `HEURISTIC`), ჩართეთ კონფიგურირებადი `is_production=True` Control Center-ში და გაასწორეთ `qa_exec_art.task_id` + რეალური wall-clock ტელემეტრია.
- **დამოკიდებულებები:** Stage 1.
- **ვერიფიკაციის ტესტები:** `AUDIT-BUG-09A`, `AUDIT-BUG-09B`, `AUDIT-BUG-10`, `AUDIT-BUG-11`, `AUDIT-BUG-12` → **PASS**.
- **სირთულის შეფასება:** საშუალო (2–3 დღე).

---

## Stage 4 — პროექტ-აგნოსტიკურობა და ტესტ-ინფრასტრუქტურის სტაბილიზაცია
- **მიზანი:** გაათავისუფლოს ბირთვი Jester-ის მყარი ტექსტებისგან და მოიყვანოს მთლიანი Python + Frontend ტესტ-სუიტი 100% მწვანე, სწრაფ, დეტერმინისტულ ბაზისზე.
- **გამოსწორებული დეფექტები:** `DEF-023`, `DEF-024`, `DEF-028`, `DEF-029`, `DEF-030`, `DEF-031`.
- **შესაცვლელი ფაილები:**
  - `pyproject.toml` (ახალი)
  - `jester_ai_company/{ux_result,prototype_renderer,design_recovery,service,project,control_center,developer_mutation,durable_storage,status}.py`
  - `tools/verify_company.py`, `README.md`, `docs/ARCHITECTURE.md`, `BACKLOG.md`
  - `tests/test_runtime_adapter.py`, `tests/test_company_orchestration_engine.py`, `tests/test_jester_live_*.py`, `tests/test_target_repository_guard.py`, `tests/test_step23b5b_runtime_reliability.py`, `tests/test_step24_4_3_artifact_recovery.py`
- **იმპლემენტაციის სტრატეგია:**
  1. გადაიტანეთ Jester-ის ბრენდირება/გზები/ბრენჩი გარე პროექტის კონფიგურაციაში (`projects.json`), წაშალეთ hardcoded `crun_29fcdd4a` / ქართული `/auth/register` / `#FF7A2F` ძრავის ბირთვიდან.
  2. დაამატეთ `pyproject.toml` (`testpaths = ["tests"]`, `markers = ["live: requires live agy CLI or external repo"]`).
  3. გაასწორეთ `test_runtime_adapter.py` (`subprocess.Popen` mock!), გამიჯნეთ `@pytest.mark.live` ტესტები და გამოიყენეთ იზოლირებული fixture git რეპოები unit ტესტებში.
  4. იმპლემენტაცია გაუკეთეთ `durable_storage.garbage_collect`-ს და სტარტაპზე ობოლი `RUNNING` run-ების reconciliation-ს (`INTERRUPTED`/`FAILED`).
  5. განაახლეთ `verify_company.py` (7-ვე აგენტი), `status.py` (`company_runs`) და დოკუმენტაცია.
- **დამოკიდებულებები:** Stages 0–3.
- **ვერიფიკაციის ტესტები:** `pytest` (default offline suite) 100% PASS <60 წამში; `npm --prefix frontend test` 100% PASS.
- **სირთულის შეფასება:** საშუალო (2–3 დღე).

---

## Stage 5 — კონტროლირებული ცოცხალი End-to-End 7-აგენტიანი ვალიდაცია (Real-Model Proof)
- **მიზანი:** Stages 0–4 დასრულების შემდეგ იზოლირებულ კლონზე (არა პროდაქშენზე!) ჩატარდეს რეალური ცოცხალი `agy` 7-აგენტიანი ტესტი (Scenarios 1, 2, 3, 4, 7, 9, 10, 11) და დადასტურდეს რეალური ოპერაციული მზაობა.
- **დამოკიდებულებები:** Stages 0–4 სრულად დასრულებული.
- **მიღების კრიტერიუმები:** რეალური ცოცხალი `agy` run ასრულებს ამოცანას, გადის რეალურ ტესტებს worktree-ში, აჩერებს `READY_FOR_HUMAN_APPLY`-ზე, დამფუძნებლის ხელით დამტკიცების შემდეგ სუფთად ადებს პატჩს იზოლირებულ სამიზნე რეპოში და 0 ფალსიფიკაცია/კრაში ფიქსირდება.
- **სირთულის შეფასება:** დაბალი–საშუალო (1 დღე).
