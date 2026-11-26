# დეფექტების რეესტრი (DEFECT REGISTER)

**აუდიტის ფაზა:** Phase K — დეფექტების, რისკების, ჰიპოთეზებისა და გაუმჯობესებების სრული რეესტრი  
**კლასიფიკაციის წესი:** მკაფიოდ გამიჯნულია (1) **დადასტურებული დეფექტები (Confirmed Defects)**, (2) **ძლიერად დასაბუთებული რისკები (Strongly Supported Risks)**, (3) **დაუდასტურებელი ჰიპოთეზები (Unverified Hypotheses)** და (4) **გაუმჯობესების შესაძლებლობები (Improvement Opportunities)**.

### შემაჯამებელი სტატისტიკა (დადასტურებული დეფექტები)
- **P0 — კრიტიკული (უსაფრთხოება / მმართველობა / მონაცემთა მთლიანობა):** 6 დეფექტი (`DEF-001` – `DEF-006`)
- **P1 — მაღალი (ბირთვის კრაშები / ორკესტრაცია / QA ხვრელები / ჩიხები):** 11 დეფექტი (`DEF-007` – `DEF-017`)
- **P2 — საშუალო (კონტექსტი / რესტარტი / პროექტ-აგნოსტიკურობა / ტესტ-სუიტი):** 10 დეფექტი (`DEF-018` – `DEF-027`)
- **P3 — დაბალი (ჰიგიენა / დოკუმენტაცია / მკვდარი კოდი):** 4 დეფექტი (`DEF-028` – `DEF-031`)

---

## ნაწილი 1 — დადასტურებული დეფექტები (Confirmed Defects)

### P0 — კრიტიკული დეფექტები

#### `DEF-001` — ავთენტიფიკაციის გარეშე RCE Control Center-ის `verify_cmd`-ისა და Wildcard CORS-ის მეშვეობით
- **Affected Component(s):** `jester_ai_company/control_center.py` (ხაზები 295, 328, 729–795), `jester_ai_company/execution.py` (ხაზი 285)
- **Severity:** **P0**
- **Evidence:** `AUDIT-SEC-01` (იზოლირებულ `ControlCenterServer`-ზე `POST /api/tasks/{id}/execute`-მა `verify_cmd`-ით შექმნა ფაილი `rce_proof_marker.txt` შიგთავსით `RCE_CONFIRMED` და დააბრუნა `Access-Control-Allow-Origin: *`).
- **Reproduction Steps:** გაუშვით `ControlCenterServer`, შექმენით task (`POST /api/tasks`), გაგზავნეთ `POST /api/tasks/{id}/execute` ბოდით `{"mock": true, "verify_cmd": "python -c \"...\""}`.
- **Expected Behavior:** HTTP API-ს არასოდეს უნდა შეეძლოს თვითნებური shell ბრძანებების (`shell=True`) შესრულება; ყველა მუტაციის endpoint უნდა იყოს ავთენტიფიცირებული და მკაცრი origin-ით შეზღუდული.
- **Actual Behavior:** ნებისმიერი ლოკალური პროცესი ან ნებისმიერი გახსნილი ვებ-გვერდი ბრაუზერში (CORS `*` გამო) ასრულებს თვითნებურ OS ბრძანებებს დამფუძნებლის უფლებებით.
- **Root Cause:** Legacy `TaskExecutor.verify_cmd` მიბმულია Control Center-ზე ავთენტიფიკაციის, origin allowlist-ის და ბრძანების allowlist-ის გარეშე.
- **Impact:** სრული ლოკალური მანქანის კომპრომეტაცია (RCE).
- **Proposed Correction:** წაშალეთ/აკრძალეთ თვითნებური `verify_cmd` HTTP API-დან (გამოიყენეთ მხოლოდ ტიპიზებული `VerificationAction` allowlist `shell=False`-ით), შეზღუდეთ CORS მხოლოდ `http://127.0.0.1:<port>`/`http://localhost:<port>`-ზე და დაამატეთ per-session Bearer/CSRF ტოკენი.
- **Dependencies:** არ აქვს (Stage 0 პირველი პრიორიტეტი).
- **Verification / Regression Test:** `AUDIT-SEC-01` → უნდა დააბრუნოს `401/403` ტოკენის გარეშე და `400` თვითნებურ `verify_cmd`-ზე; CORS header არ უნდა იყოს `*`.
- **Confidence Level:** High (100% ექსპერიმენტულად დადასტურებული) | **Verification Status:** **Confirmed (Live HTTP Repro)**

#### `DEF-002` — Path Traversal სტატიკური ფაილების სერვერში (`/assets/`, `/portraits/`)
- **Affected Component(s):** `jester_ai_company/control_center.py` (ხაზები 357–382)
- **Severity:** **P0**
- **Evidence:** `AUDIT-SEC-03` (`GET /assets/../../package.json` raw HTTP მოთხოვნამ დააბრუნა `HTTP 200` და `frontend/package.json`-ის სრული შიგთავსი).
- **Reproduction Steps:** გაგზავნეთ raw HTTP `GET /assets/../../package.json` `ControlCenterServer`-ზე (`http.client.HTTPConnection`).
- **Expected Behavior:** HTTP `403` ან `404` ყველა გზაზე, რომელიც `resolve()`-ის შემდეგ სცდება `FRONTEND_DIST_DIR`-ს.
- **Actual Behavior:** `FRONTEND_DIST_DIR / path.lstrip("/")` ამოწმებს მხოლოდ `is_file()`-ს `is_relative_to()`-ს გარეშე და აბრუნებს დისკზე არსებულ ნებისმიერ ფაილს.
- **Root Cause:** path confinement შემოწმების არარსებობა `_handle_static_file`-ში.
- **Impact:** ლოკალური ფაილური სისტემის ნებისმიერი ფაილის წაკითხვა (მათ შორის `.env`, SSH/Git კონფიგები, წყარო-კოდი).
- **Proposed Correction:** დაამატეთ `resolved = (FRONTEND_DIST_DIR / rel).resolve(); if not resolved.is_relative_to(FRONTEND_DIST_DIR.resolve()): return 403`.
- **Dependencies:** Stage 0.
- **Verification / Regression Test:** raw HTTP ტესტი `/assets/../../package.json`, `/assets/../../../../Windows/win.ini`, URL-encoded `%2e%2e`.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live HTTP Repro)**

#### `DEF-003` — თვითნებური ფაილის წაკითხვა რეპოზიტორიაში `GET /api/artifacts/content` მეშვეობით
- **Affected Component(s):** `jester_ai_company/control_center.py` (ხაზები 488–501), `jester_ai_company/service.py` (ხაზები 961–986)
- **Severity:** **P0**
- **Evidence:** `AUDIT-SEC-02` (`GET /api/artifacts/content?path=../.env`-მა დააბრუნა `HTTP 200` და საიდუმლო `AUDIT_SECRET=SENTINEL_VALUE_9988`).
- **Reproduction Steps:** მოათავსეთ `.env` `repo_root`-ში, გაგზავნეთ `GET /api/artifacts/content?path=../.env`.
- **Expected Behavior:** დაშვებულია მხოლოდ `output_dir` (`.runs/`) შიგნით არსებული რეგისტრირებული არტეფაქტების წაკითხვა.
- **Actual Behavior:** `service.py:976` დამატებით უშვებს `target.relative_to(repo_resolved)`-ს, რაც ხსნის `.env`, `.git/config` და სრულ კოდბაზას.
- **Root Cause:** ზედმეტად ფართო fallback შემოწმება `repo_root`-ზე.
- **Impact:** საიდუმლოების და რეპოზიტორიის ფაილების გაჟონვა HTTP-ით.
- **Proposed Correction:** წაშალეთ `repo_resolved` fallback; შეზღუდეთ წაკითხვა მკაცრად `self.output_dir.resolve()`-ით და უარყავით protected path-ები (`.env`, `.git`, `*.key`, `*.pem`).
- **Dependencies:** Stage 0.
- **Verification / Regression Test:** `AUDIT-SEC-02` უნდა დააბრუნოს `HTTP 403/404`.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live HTTP Repro)**

#### `DEF-004` — სინთეზური / გაყალბებული დამფუძნებლის თანხმობები (`founder_grant_*`, `founder_repair_*`, `founder_ui_*`)
- **Affected Component(s):** `jester_ai_company/engineering_pipeline.py` (ხაზები 591, 870–873), `jester_ai_company/control_center.py` (ხაზი 916)
- **Severity:** **P0**
- **Evidence:** `AUDIT-SEC-05` (`synthetic_grant=True`, `synthetic_repair=True`); კოდის ინსპექცია: `engineering_pipeline.py:591` (`f"founder_grant_{run.run_id}"`), `870-873` (`f"founder_repair_1_{run.run_id}"`, `f"founder_repair_2_{run.run_id}"`), `control_center.py:916` (ავტომატური `founder_ui_{run_id}_{uuid}`).
- **Reproduction Steps:** გაუშვით `CompanyEngineeringPipeline` ან გაგზავნეთ `POST /api/company-runs/{id}/approve` ცარიელი ბოდით `{}`.
- **Expected Behavior:** ადამიანის თანხმობის ID არასოდეს არ უნდა გენერირდებოდეს ავტომატურად (`ARCHITECTURE.md:37,187`, `repair.py:18`).
- **Actual Behavior:** სისტემა თვითონ აყალბებს დამფუძნებლის თანხმობის ID-ებს ExecutionGrant-ისთვის, Repair Loop-ისთვის და UI Apply-ისთვის.
- **Root Cause:** ავტომატიზაციის დასაჩქარებლად გვერდი აუარეს ადამიანის კარიბჭის მოთხოვნებს.
- **Impact:** მმართველობის (Governance) და აუდიტის კვალის (audit trail) მთლიანობის სრული რღვევა.
- **Proposed Correction:** (1) `control_center.py:916`-ში აკრძალეთ ცარიელი `founder_approval_id` (HTTP 400); (2) მკაფიოდ განასხვავეთ სანდბოქსის/worktree-ის ავტომატური ნებართვა (`ExecutionScopeToken`) ადამიანის დამტკიცებისგან (`FounderApprovalRecord`) ან შეაჩერეთ run `WAITING_FOR_HUMAN`-ში დამფუძნებლის თანხმობის მისაღებად.
- **Dependencies:** Stage 0 & Stage 2.
- **Verification / Regression Test:** ტესტი, რომელიც უზრუნველყოფს, რომ არცერთი `founder_*` ID არ გენერირდება კოდში დამფუძნებლის ხელით შეყვანის გარეშე.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Static + Automated Audit)**

#### `DEF-005` — არაიზოლირებული Developer Repair Planning პირდაპირ `self.repo_root`-ში hook-ის გარეშე
- **Affected Component(s):** `jester_ai_company/service.py` (ხაზები 3827–3833)
- **Severity:** **P0**
- **Evidence:** `service.py:3827-3833` იძახებს `self.runtime.execute(agent="developer", ..., workspace_dir=self.repo_root)` — არა `target_repo`-ში, არა იზოლირებულ worktree-ში და `install_planning_policy_hook`-ის გარეშე, `--dangerously-skip-permissions`-ით.
- **Reproduction Steps:** გაუშვით Repair Loop იტერაცია 1 (`execute_developer_qa_repair_loop`) გარე სამიზნე რეპოზიტორიაზე.
- **Expected Behavior:** Repair Planning უნდა გაეშვას იზოლირებულ დისპოზაბელურ planning workspace-ში (სამიზნე რეპოს კოპიაზე) `install_planning_policy_hook`-ით.
- **Actual Behavior:** Developer აგენტი `--dangerously-skip-permissions`-ით ეშვება პირდაპირ კომპანიის ძრავის რეპოზიტორიაში (`JesterAICompany`) უსაფრთხოების ბარიერის გარეშე.
- **Root Cause:** STEP 15-ის იმპლემენტაციისას გამოტოვეს იზოლირებული planning workspace და target repo routing.
- **Impact:** აგენტს შეუძლია შეცვალოს თავად `JesterAICompany`-ის კოდი ან დაწეროს არასწორი repair plan, რადგან არასწორ რეპოზიტორიას კითხულობს.
- **Proposed Correction:** შექმენით იზოლირებული planning worktree `target_repo`-დან და დააყენეთ `install_planning_policy_hook` `try/finally` წაშლით.
- **Dependencies:** `DEF-006`.
- **Verification / Regression Test:** ინტეგრაციის ტესტი, რომელიც ამოწმებს, რომ repair planning იყენებს `target_repo`-ს worktree-ს და `planning_hook_audit.jsonl` იწერება.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Source Audit)**

#### `DEF-006` — `PreToolUse` `hook_policy.py`-ის 4 ხარვეზი და read-only hook-ების არარსებობა არა-მუტაციურ აგენტებზე
- **Affected Component(s):** `jester_ai_company/policy_hook.py` (ხაზები 244–447), `jester_ai_company/runtime.py` (ხაზი 181), `jester_ai_company/service.py`
- **Severity:** **P0**
- **Evidence:** `AUDIT-SEC-06` (გენერირებული `hook_policy.py`-ის პირდაპირი გაშვება): (1) 10,000-ბაიტიანი ჩაწერა დაშვებული იქნა `max_bytes_written=10`-ზე (`decision=allow`); (2) ახლად შექმნილ ფაილზე მეორე ჩაწერა დაიბლოკა (`deny`), მიუხედავად იმისა, რომ `authorize_tool_mutation` უშვებს (`allowed=True`); (3) Windows `src\app.py` დაიბლოკა (`deny`); (4) `read_file`/`write_file` დაიბლოკა (`deny`). ასევე, CEO/Product/Research/UX/Marketing/QA 14A ეშვება `--dangerously-skip-permissions`-ით ყოველგვარი hook-ის გარეშე.
- **Reproduction Steps:** გაუშვით `AUDIT-SEC-06` (`install_execution_policy_hook` → `python .agents/hook_policy.py` სხვადასხვა `toolCall` JSON-ით).
- **Expected Behavior:** ერთიანი ლოგიკა, ბაიტების/ფაილების კვოტის რეალური კონტროლი, Windows გზების ნორმალიზაცია, `agy` 1.3.6 tool-ების (`read_file`, `write_file`, `edit_file`) მხარდაჭერა და read-only hook ყველა არა-მუტაციურ აგენტზე.
- **Actual Behavior:** 4 დადასტურებული ხარვეზი `hook_policy.py`-ში და 0 ტექნიკური დაცვა 6 არა-მუტაციურ აგენტზე.
- **Root Cause:** `hook_policy.py` ჩაკოპირებულია სტრინგად და განცალკევებულია `authorize_tool_mutation`-ისგან; tool-ების სახელები მოძველებულია.
- **Impact:** კვოტების გვერდის ავლა, ლეგიტიმური დეველოპერის ჩაწერების ცრუ ბლოკვა და არასანქცირებული ჩაწერის რისკი read-only აგენტებისგან.
- **Proposed Correction:** გადაიყვანეთ `hook_policy.py` საერთო Python ფუნქციაზე, დაამატეთ `read_file`/`write_file`/`edit_file` + Windows ნორმალიზაცია + რეალური byte/file მრიცხველი და ჩართეთ read-only hook ყველა არა-მუტაციურ აგენტზე; გადაამოწმეთ `agy --dangerously-skip-permissions` + `hooks.json` ურთიერთქმედება (`HYP-01`).
- **Dependencies:** Stage 0.
- **Verification / Regression Test:** `AUDIT-SEC-06` განახლებული მოლოდინებით + ცოცხალი `agy` hook პრობა.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Subprocess Repro)**

---

### P1 — მაღალი სიმძიმის დეფექტები

#### `DEF-007` — `UI_UX_CHANGE` ნაკადების დეტერმინისტული კრაში (`["ux", "developer"]`)
- **Affected Component(s):** `jester_ai_company/engineering_pipeline.py` (ხაზები 187–207), `jester_ai_company/ceo_contract.py` (ხაზი 1414), `jester_ai_company/dag.py` (ხაზები 199–210)
- **Severity:** **P1**
- **Evidence:** `AUDIT-BUG-01` (`EngineeringPreconditionError: Developer macro work item 'wi_dev_1' violates Product + UX Fan-In invariant: requires direct dependencies on BOTH Product and UX work items. Found depends_on: ['wi_ux_1'].`).
- **Reproduction Steps:** შექმენით UI/UX კოდური ამოცანა (გუნდი `["ux", "developer"]`), დაასრულეთ UX, შემდეგ გაუშვით Developer work item.
- **Expected Behavior:** `UI_UX_CHANGE` ნაკადში Developer უნდა იწყებოდეს UX არტეფაქტის საფუძველზე Product-ის გარეშე.
- **Actual Behavior:** ყოველი `UI_UX_CHANGE` გაშვება 100%-ით ვარდება `EngineeringPreconditionError`-ით.
- **Root Cause:** `requires_fan_in = (has_prod_in_plan or has_ux_in_plan) or not is_direct_allowed` აიძულებს ორივე Product+UX-ის არსებობას მაშინაც კი, როცა გეგმაში მხოლოდ UX არის.
- **Impact:** UI/UX ცვლილებების მთელი კლასი სრულად არამუშაა.
- **Proposed Correction:** შეცვალეთ fan-in პირობა, რათა `UI_UX_CHANGE`-ზე (`has_ux_in_plan and not has_prod_in_plan`) დაშვებული იყოს მხოლოდ UX upstream, როგორც `engineering_pipeline.py`-ში, ისე `execute_developer_planning_task`-ში.
- **Dependencies:** `DEF-008`.
- **Verification / Regression Test:** `AUDIT-BUG-01` უნდა გაიაროს Developer Planning-მდე კრაშის გარეშე.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-008` — 3-არტეფაქტიანი კრაში ვიზუალური UX პროტოტიპის გადაცემისას Developer Planning-ში
- **Affected Component(s):** `jester_ai_company/engineering_pipeline.py` (ხაზები 445–450), `jester_ai_company/service.py` (ხაზი 1983)
- **Severity:** **P1**
- **Evidence:** `AUDIT-BUG-02` (`HandoffPolicyError: Developer planning task '...' requires exactly 2 input artifacts (1 Product, 1 UX), found 3.`).
- **Reproduction Steps:** მიაბით Developer Planning task-ს `SPECIFICATION` + `UX_SPECIFICATION` + `UX_PROTOTYPE` და გამოიძახეთ `execute_developer_planning_task`.
- **Expected Behavior:** Developer Planning იღებს PRD + UX_SPEC + არასავალდებულო UX_PROTOTYPE/DESIGN_CONCEPT-ს.
- **Actual Behavior:** `service.py:1983` მკაცრად უარყოფს `len(input_artifacts) != 2`-ს.
- **Root Cause:** STEP 24-ში `engineering_pipeline.py`-ს დაემატა მე-3 არტეფაქტი, მაგრამ `service.py`-ს ვალიდატორი არ განახლდა.
- **Impact:** ვიზუალური პროტოტიპირების (STEP 24) შემდეგ კოდის იმპლემენტაცია შეუძლებელია.
- **Proposed Correction:** დაუშვით 1–3 არტეფაქტი ტიპების მიხედვით (`PRD` optional on `UI_UX_CHANGE`, `UX_SPEC`, optional `UX_PROTOTYPE`/`DESIGN_CONCEPT`).
- **Dependencies:** `DEF-007`.
- **Verification / Regression Test:** `AUDIT-BUG-02` უნდა დასრულდეს `HandoffPolicyError`-ის გარეშე.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-009` — ვიზუალური დიზაინის დამტკიცების მუდმივი ჩიხი (`WAITING_FOR_HUMAN` Deadlock)
- **Affected Component(s):** `jester_ai_company/service.py` (ხაზები 5772–5781), `jester_ai_company/control_center.py`, `frontend/src/api/client.ts`
- **Severity:** **P1**
- **Evidence:** `control_center.py`-ში და `client.ts`-ში 0 endpoint/მეთოდია `submit_founder_design_approval`/`reject_founder_design_concepts`-ზე; რეალური run `.runs/company_runs/crun_29fcdd4a` 2,384.5 წამის შემდეგ გაჭედილია `WAITING_FOR_HUMAN`-ში.
- **Reproduction Steps:** გაუშვით კოდური UX ვიზუალური კონცეპტების ამოცანა Control Center-იდან; სცადეთ დიზაინის დამტკიცება UI/API-დან.
- **Expected Behavior:** Control Center აჩვენებს კონცეპტებს და იძლევა დამტკიცების/უარყოფის HTTP endpoint-ებს, რომლებიც აგრძელებენ run-ს.
- **Actual Behavior:** Run სამუდამოდ იჭედება `WAITING_FOR_HUMAN`-ში.
- **Root Cause:** STEP 24 დასრულდა Python სერვისის დონეზე, HTTP/UI ინტეგრაციის გარეშე.
- **Impact:** დამფუძნებელი ვერ დაასრულებს ვერცერთ ვიზუალურ დიზაინ-ამოცანას Control Center-იდან.
- **Proposed Correction:** დაამატეთ `POST /api/company-runs/{id}/design-approval` და `/design-reject` ენდფოინთები (ავთენტიფიცირებული!) და UI კონტროლი.
- **Dependencies:** `DEF-001`, `DEF-008`.
- **Verification / Regression Test:** E2E Control Center ტესტი `WAITING_FOR_HUMAN` → design approval → resume → `READY_FOR_HUMAN_APPLY`.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Source + Real `.runs/` Evidence)**

#### `DEF-010` — QA Verification აბრუნებს `PASS`-ს 0 გაშვებული ტესტით (`recommended_verification_actions: []`)
- **Affected Component(s):** `jester_ai_company/qa_execution.py` (ხაზები 540, 546–583)
- **Severity:** **P1**
- **Evidence:** `AUDIT-BUG-03` (იზოლირებულ worktree-ში ბექენდ `app.py` პატჩზე ცარიელი `recommended_verification_actions`-ით `execute_qa_verification_task`-მა დააბრუნა `verdict=PASS`).
- **Reproduction Steps:** გადაეცით `execute_qa_verification_task`-ს `QA_REPORT`, რომლის `recommended_verification_actions` არის `[]`, და დააბრუნებინეთ QA აგენტს `PASS`.
- **Expected Behavior:** 0 გაშვებულ ტესტზე დეტერმინისტულმა override-მა უპირობოდ უნდა დააყენოს `BLOCKED`.
- **Actual Behavior:** `no_actions_executed = (len(verification_results) == 0 and len(action_audits) > 0)` არის `False` და ბექენდ ცვლილებაზე ბრუნდება `PASS`.
- **Root Cause:** ხაზი 550 არასწორად ამოწმებს `and len(action_audits) > 0`-ს.
- **Impact:** გაუტესტავი ან გაფუჭებული ბექენდ კოდი იღებს `QA PASS`-ს და გადის `RealRepoApply`-მდე.
- **Proposed Correction:** შეცვალეთ პირობა `if len(verification_results) == 0:` → ყოველთვის `BLOCKED` ნებისმიერ `CODE_PATCH`-ზე.
- **Dependencies:** არ აქვს.
- **Verification / Regression Test:** `AUDIT-BUG-03` უნდა დააბრუნოს `BLOCKED` (`deterministic_override_applied=True`).
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-011` — QA Inspection 14A პარსერი აყალბებს `VERIFIED` კატეგორიებს ტესტების გაშვებამდე
- **Affected Component(s):** `jester_ai_company/qa_result.py` (ხაზები 497–533)
- **Severity:** **P1**
- **Evidence:** `AUDIT-BUG-04` (სქემის შესაბამის 14A JSON-ზე, სადაც `category_verifications` არ არის, პარსერმა შექმნა `FUNCTIONAL_CORRECTNESS: ('VERIFIED', 'Functional test suites passed in test environment.')` და `DESIGN_SPECIFICATION_COMPLIANCE: ('VERIFIED', ...)`).
- **Reproduction Steps:** გამოიძახეთ `parse_and_validate_qa_result` მინიმალური 14A JSON-ით (`category_verifications`-ის გარეშე).
- **Expected Behavior:** სტატიკური ინსპექციის ეტაპზე გაუტესტავი კატეგორიები უნდა იყოს `NOT_VERIFIED` / `PENDING_EXECUTION`.
- **Actual Behavior:** კოდი იგონებს ყალბ მტკიცებულებას, თითქოს ტესტები უკვე წარმატებით გაეშვა.
- **Root Cause:** ავტომატური default fallback სინთეზური `VERIFIED` ჩანაწერებით.
- **Impact:** დამფუძნებელი და downstream კომპონენტები იღებენ ყალბ მტკიცებულებას ვერიფიკაციის შესახებ.
- **Proposed Correction:** წაშალეთ ყალბი `VERIFIED` default-ები; დააყენეთ `NOT_EXECUTED` სანამ 14B რეალურად არ გაეშვება.
- **Dependencies:** `DEF-010`.
- **Verification / Regression Test:** `AUDIT-BUG-04` უნდა აბრუნებდეს `NOT_EXECUTED` / `UNVERIFIED`.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-012` — CEO და QA `agent.md` პრომპტების შეუსაბამობა Python ვალიდატორებთან (`audit`, `FEATURE`, `GENERAL`)
- **Affected Component(s):** `.agents/agents/ceo/agent.md` (ხაზები 76, 137), `.agents/agents/qa/agent.md` (ხაზები 47, 88), `.agents/agents/developer/agent.md`, `.agents/agents/ux/agent.md` (ხაზები 58–70)
- **Severity:** **P1**
- **Evidence:** `AUDIT-BUG-09A` (`PlanValidationError: QA work item 'wi_qa_1' specifies unsupported capability 'audit'`); `AUDIT-BUG-09B` (`CEODecisionValidationError: Invalid task_category 'FEATURE'` / `'GENERAL'`).
- **Reproduction Steps:** გადაეცით `parse_and_validate_ceo_plan`-ს `"capability": "audit"`, ხოლო `parse_and_validate_team_selection`-ს `"task_category": "FEATURE"` ან `"GENERAL"`.
- **Expected Behavior:** აგენტის სისტემურ პრომპტში მითითებული ყველა enum მნიშვნელობა მიღებული უნდა იყოს პარსერის მიერ.
- **Actual Behavior:** თუ ცოცხალი CEO ან QA აგენტი ზუსტად მიჰყვება თავის `agent.md`-ს, სისტემა დეტერმინისტულად აგდებს ვალიდაციის შეცდომას.
- **Root Cause:** Python enum-ები შეიცვალა ეტაპების განმავლობაში `agent.md` ფაილების სინქრონიზაციის გარეშე.
- **Impact:** ცოცხალი მოდელის ხშირი ვალიდაციის ჩავარდნები (ისტორიაში 18x `Output validation exhausted` ჩავარდნა!).
- **Proposed Correction:** სინქრონიზაცია გაუკეთეთ 7-ვე `agent.md`-ს Python ვალიდატორებთან (მათ შორის დაამატეთ Developer Mode C და UX `concepts`) და დაამატეთ ავტომატური კონტრაქტ-ტესტი.
- **Dependencies:** არ აქვს.
- **Verification / Regression Test:** `AUDIT-BUG-09A`, `AUDIT-BUG-09B` + prompt-to-enum AST/regex ტესტი.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-013` — CEO LLM გვერდის ავლა ნაგულისხმევ რეჟიმში და მცდარი `source="MODEL"` ტელემეტრია
- **Affected Component(s):** `jester_ai_company/service.py` (ხაზები 4714–4889, 5005–5078), `jester_ai_company/control_center.py` (ხაზი 1149)
- **Severity:** **P1**
- **Evidence:** `AUDIT-BUG-12` (`ceo_runtime_calls=1` მხოლოდ DAG-ისთვის, 0 გამოძახება შეფასებაზე/გუნდის შერჩევაზე, მაგრამ `events_claim_MODEL=True`). ასევე `service.py:4816-4889` (`investigate_objective`) არ კითხულობს ფაილებს.
- **Reproduction Steps:** გაუშვით `plan_company_run` ნაგულისხმევი `CompanyService()`-ით (როგორც Control Center-ში) და დათვალეთ CEO runtime-ის გამოძახებები.
- **Expected Behavior:** ან რეალურად იძახება CEO LLM (`is_production=True` ან კონფიგურირებადი), ან ტელემეტრია პატიოსნად წერს `source="HEURISTIC"` და `model_invocation_count=0`.
- **Actual Behavior:** Control Center ყოველთვის იყენებს ჰევრისტიკებს და ცრუდ აფიქსირებს `source="MODEL"`.
- **Root Cause:** `fallback_activated=False` გამოყენებულია როგორც `source="MODEL"`-ის პროქსი მაშინაც, როცა მოდელი საერთოდ არ გამოძახებულა.
- **Impact:** დამფუძნებელს ჰგონია, რომ CEO LLM იღებს გადაწყვეტილებებს, რეალურად კი მარტივი keyword-ების სია მართავს კომპანიას.
- **Proposed Correction:** შემოიტანეთ ცალსახა `decision_source` (`"MODEL"` | `"HEURISTIC"` | `"FALLBACK"`), ჩართეთ `is_production=True` (ან კონფიგურირებადი flag) Control Center-ში და გახადეთ `investigate_objective` რეალური read-only ინსპექცია.
- **Dependencies:** `DEF-012`.
- **Verification / Regression Test:** `AUDIT-BUG-12` უნდა ადასტურებდეს ზუსტ `decision_source`-ს.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-014` — კოდის კრაშები: `UnboundLocalError` (`developer_mutation.py:169` და `service.py:5669/5684/5697`)
- **Affected Component(s):** `jester_ai_company/developer_mutation.py` (ხაზი 169), `jester_ai_company/service.py` (ხაზები 5669, 5684, 5697 vs 5734)
- **Severity:** **P1**
- **Evidence:** `AUDIT-BUG-05` (`UnboundLocalError: cannot access local variable 'json_str'`); კოდის ინსპექცია `service.py:5669, 5684, 5697` (`spec_dur` გამოყენებულია განსაზღვრამდე ხაზ 5734-ზე).
- **Reproduction Steps:** (1) გადაეცით `parse_and_validate_developer_mutation_result`-ს `'Modified {app.py}:\n```json\n{...}\n```'`; (2) შექმენით სპეციალისტის run დაკარგული ან დაზიანებული გამომავალი არტეფაქტით.
- **Expected Behavior:** დეველოპერის fenced JSON პარსირდება; დაზიანებულ არტეფაქტზე გამოიძახება `_handle_work_item_failure` ზუსტი `spec_dur`-ით.
- **Actual Behavior:** ორივე გზა აგდებს დაუმუშავებელ `UnboundLocalError`-ს.
- **Root Cause:** ლოკალური ცვლადების (`json_str = ""`, `spec_dur`) არაინიციალიზება პირობითი ბლოკების წინ.
- **Impact:** ცოცხალი აგენტის სტანდარტული პასუხი (ტექსტი + JSON) ან არტეფაქტის მთლიანობის შეცდომა აგდებს კრაშს.
- **Proposed Correction:** დაამატეთ `json_str: Optional[str] = None` `developer_mutation.py:156`-ში და გამოთვალეთ `spec_dur` `service.py:5655`-ზე (ყველა მარცხის ბილიკის წინ).
- **Dependencies:** არ აქვს.
- **Verification / Regression Test:** `AUDIT-BUG-05` + unit ტესტი missing/tampered output artifact-ზე.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live Repro + Source Audit)**

#### `DEF-015` — კონკურენტული `POST /api/company-runs` TOCTOU Race Condition და Thread-Safety-ს არარსებობა
- **Affected Component(s):** `jester_ai_company/control_center.py` (ხაზები 821–852), `jester_ai_company/service.py`
- **Severity:** **P1**
- **Evidence:** `AUDIT-SCEN-08` (5 ერთდროული `POST /api/company-runs` მოთხოვნიდან **5-ვემ დააბრუნა HTTP 201**!).
- **Reproduction Steps:** გაგზავნეთ 5 პარალელური `POST /api/company-runs` მოთხოვნა `ThreadPoolExecutor`-ით.
- **Expected Behavior:** მხოლოდ 1 run ბრუნდება `201`-ით; დანარჩენი 4 იღებს `409 Conflict`.
- **Actual Behavior:** ხუთივე გადის შემოწმებას, ქმნის 5 პარალელურ run-ს და იწვევს race condition-ებს საერთო `CompanyService`-ში.
- **Root Cause:** check-then-act (აქტიური worker-ის შემოწმება vs რეგისტრაცია) არ არის დაცული `threading.Lock`-ით.
- **Impact:** დუბლირებული აგენტების გაშვება, დაზიანებული მდგომარეობა და არაკონტროლირებადი LLM ხარჯი.
- **Proposed Correction:** შემოიღეთ `threading.RLock` `ControlCenter` run-შექმნისა და `CompanyService` მუტაციების გარშემო.
- **Dependencies:** არ აქვს.
- **Verification / Regression Test:** `AUDIT-SCEN-08` უნდა იღებდეს ზუსტად 1× `201` და 4× `409`.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Live HTTP Repro)**

#### `DEF-016` — Control Center-ში შუა-შესრულების Clarification Resume-ის გაჭედვა და Cancellation-ის არარსებობა
- **Affected Component(s):** `jester_ai_company/control_center.py` (ხაზი 1072), `jester_ai_company/orchestrator.py` (ხაზები 118–136)
- **Severity:** **P1**
- **Evidence:** `AUDIT-SCEN-11` (`CompanyRunState`-ში არ არსებობს `CANCELLED`); კოდის ინსპექცია: `control_center.py:1072` ამოწმებს მხოლოდ `if run.state == CompanyRunState.PLAN_READY.value:`, მაშინ როცა `service.py:5110-5122` შუა-შესრულების clarification-ის შემდეგ აბრუნებს `RUNNING`-ს.
- **Reproduction Steps:** გადაიყვანეთ run `RUNNING` → `WAITING_FOR_CLARIFICATION` → გაგზავნეთ `POST /api/company-runs/{id}/clarify`.
- **Expected Behavior:** ფონური worker აგრძელებს შესრულებას; ასევე არსებობს `POST /api/company-runs/{id}/cancel` (`CANCELLED` სტატუსი + `kill_process_tree`).
- **Actual Behavior:** Run რჩება `RUNNING`-ში worker-ის გარეშე სამუდამოდ; გაუქმება საერთოდ შეუძლებელია.
- **Root Cause:** Resume პირობა ითვალისწინებს მხოლოდ pre-execution clarification-ს; cancellation არ დაპროექტებულა.
- **Impact:** დამფუძნებელს არ შეუძლია გაჭედილი ან არასასურველი გაშვების შეჩერება.
- **Proposed Correction:** განაახლეთ resume პირობა (`PLAN_READY` ან `RUNNING`), დაამატეთ `CANCELLED` სტატუსი, `cancel_company_run` და აქტიური subprocess-ის შეწყვეტა.
- **Dependencies:** `DEF-015`.
- **Verification / Regression Test:** ტესტი mid-run clarify resume-ზე და `POST /cancel`-ზე.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Source + Automated Audit)**

#### `DEF-017` — QA 14A ეშვება არასწორ რეპოში (`self.repo_root`), ხოლო QA 14B-ს timeout ჩაჭედილია 30 წამზე
- **Affected Component(s):** `jester_ai_company/service.py` (ხაზები 2937, 2968, 3342)
- **Severity:** **P1**
- **Evidence:** `service.py:2937` უშვებს QA 14A აგენტს `workspace_dir=self.repo_root`-ში (კომპანიის ძრავა!) და ხაზი `2968` ამოწმებს `self.repo_root`-ის git სისუფთავეს `target_repo`-ს ნაცვლად; ხაზი `3342` მყარად გადასცემს `timeout=30.0`-ს `verification.py`-ს.
- **Reproduction Steps:** გაუშვით QA 14A/14B გარე რეპოზე (`Jester`), სადაც `frontend_build` 30 წამზე მეტხანს გრძელდება.
- **Expected Behavior:** 14A იზოლირებულად კითხულობს `target_repo`-ს; 14B იყენებს კონფიგურირებად timeout-ს (მაგ., 180–300s `frontend_build`-ისთვის).
- **Actual Behavior:** 14A ამოწმებს არასწორ რეპოზიტორიას; 14B ხშირად იჭრება 30-წამიან timeout-ზე.
- **Root Cause:** `target_repo_root` პარამეტრის და `timeout`-ის გაუტარებლობა.
- **Impact:** ცრუ QA დასკვნები გარე პროექტებზე და ბილდის ცრუ ჩავარდნები.
- **Proposed Correction:** გადაეცით `target_repo_root` 14A-ს (იზოლირებული read-only hook-ით) და დააკავშირეთ `timeout` 14B-ში.
- **Dependencies:** `DEF-006`.
- **Verification / Regression Test:** გარე-რეპო QA 14A/14B ტესტი `target_repo_root != self.repo_root`-ზე.
- **Confidence Level:** High | **Verification Status:** **Confirmed (Source Audit)**

---

### P2 — საშუალო სიმძიმის დეფექტები

#### `DEF-018` — `AntigravityRuntime` ჩუმად ჭრის პრომპტს 28,000 სიმბოლოზე (კარგავს ბოლოში მდებარე JSON სქემას)
- **Affected Component(s):** `jester_ai_company/runtime.py` (ხაზები 167–169)
- **Severity:** **P2** (მაღალკონტექსტიან ამოცანებზე P1 ეფექტით)
- **Evidence:** `AUDIT-BUG-11` (`Input len=29038, sent len=28000, tail_schema_lost=True`).
- **Root Cause:** Windows CLI არგუმენტების სიგრძის (~32KB) ლიმიტის გვერდის ავლა უხეში slice-ით `[:28000]`.
- **Proposed Correction:** გადაეცით პრომპტი `stdin`-ით ან დროებითი ფაილით (`agy` ფლაგების შემოწმებით), ან უარყავით fail-closed შეცდომით, არასოდეს ჩამოჭრათ ჩუმად სქემა.
- **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-019` — `ContextEnvelope` და `role_knowledge` იკარგება `research`, `marketing`, `qa` და CEO შეფასებისას; `max_sources=3` გვერდის ავლა
- **Affected Component(s):** `jester_ai_company/service.py` (ხაზები 5495–5505, 5576–5629), `jester_ai_company/ceo_contract.py` (ხაზები 619, 1130), `jester_ai_company/knowledge.py` (ხაზები 632–638)
- **Severity:** **P2**
- **Evidence:** პირდაპირი კოდის ინსპექცია: `execute_next_company_work` არ გადასცემს აწყობილ კონტექსტს 3 როლს; CEO prompt builder-ები იგნორირებენ `project_knowledge`-ს; ყველა 6 წყარო ხდება `mandatory`.
- **Proposed Correction:** გადაეცით `context_envelope` და `role_knowledge` ყველა 7 როლს და დაიცავით `max_sources` ლიმიტი.
- **Verification Status:** **Confirmed (Source Audit)**

#### `DEF-020` — `RealRepoApply` Crash Recovery-ის 3 დეფექტი: `Project.add_task`, `EXACT_APPROVED_PATCH_PRESENT`, Stale Lock Deadlock
- **Affected Component(s):** `jester_ai_company/service.py` (ხაზები 4434, 4469–4477), `jester_ai_company/real_repo_apply.py` (ხაზები 504–530)
- **Severity:** **P2**
- **Evidence:** `AUDIT-BUG-07` (`hasattr(Project, 'add_task') == False`), `AUDIT-BUG-08` (`TargetRepositoryDirtyError` იდემპოტენტური აღდგენის ნაცვლად), `AUDIT-SCEN-09B` (`ConcurrentApplyError` მკვდარ PID `999999`-ზე).
- **Proposed Correction:** გაასწორეთ `default_proj.tasks.append(patch_task)`, დაამუშავეთ `EXACT_APPROVED_PATCH_PRESENT` იდემპოტენტურად და დაამატეთ PID liveness / stale-lock recovery.
- **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-021` — CEO-ს არასანდო JSON-ს შეუძლია თვითავტორიზაცია (`allow_direct_developer: true`) და `selected_roles`-ის in-place მუტაცია
- **Affected Component(s):** `jester_ai_company/ceo_contract.py` (ხაზები 425–426, 480, 491), `jester_ai_company/dag.py` (ხაზი 193)
- **Severity:** **P2**
- **Evidence:** `AUDIT-ADV-01` (DAG ვალიდატორმა მიიღო direct developer მხოლოდ CEO-ს მიერ ჩაწერილი `"allow_direct_developer": true`-ს საფუძველზე).
- **Proposed Correction:** `allow_direct_developer` უნდა განისაზღვროს მხოლოდ აპლიკაციის პოლიტიკით / `team_selection`-ით და არა CEO-ს არასანდო გეგმიდან; შეწყვიტეთ `selected_roles`-ის in-place მუტაცია.
- **Verification Status:** **Confirmed (Live Repro)**

#### `DEF-022` — `engineering_pipeline.py:1024` (`qa_exec_art.task_id`) ჩუმად ყლაპავს Developer/QA ტელემეტრიას; ყალბი ფიქსირებული latencies
- **Affected Component(s):** `jester_ai_company/engineering_pipeline.py` (ხაზები 1024–1034), `jester_ai_company/service.py`, `jester_ai_company/telemetry.py`
- **Severity:** **P2**
- **Evidence:** `AUDIT-BUG-10` (`hasattr(Artifact, 'task_id') == False`), `except Exception: pass`; ფიქსირებული `0.05s`/`0.15s`/`0.1s` ხანგრძლივობები რეალური 9–23 წუთიანი გაშვებების ფონზე.
- **Proposed Correction:** გამოიყენეთ რეალური `task.id` და `time.perf_counter()` გაზომვები; ამოიღეთ ჩუმი `except Exception: pass`.
- **Verification Status:** **Confirmed (Live Repro + Source Audit)**

#### `DEF-023` — პროექტ-აგნოსტიკურობის დარღვევა: Jester-ის, ქართული `/auth/register`-ის და Desktop გზების hardcode ბირთვში
- **Affected Component(s):** `jester_ai_company/ux_result.py:407-419`, `prototype_renderer.py:28,183-204`, `service.py:6245-6253`, `design_recovery.py:264-475`, `project.py:412-438`, `control_center.py:80-86`, `developer_mutation.py:195`
- **Severity:** **P2**
- **Evidence:** პირდაპირი კოდის ინსპექცია (Jester Social Astrology, `#FF7A2F`, `jester_logo.svg`, `crun_29fcdd4a`, `C:\Users\fiord\OneDrive\Desktop\Jester` ბრენჩით `main`).
- **Proposed Correction:** გადაიტანეთ პროდუქტ-სპეციფიკური კონფიგურაცია პროექტის მანიფესტში (`project_config.json` / `ProjectRegistry`), გაათავისუფლეთ ძრავის ბირთვი Jester-ის მყარი ტექსტებისგან.
- **Verification Status:** **Confirmed (Source Audit)**

#### `DEF-024` — გატეხილი Baseline Python ტესტ-სუიტი (16 FAILED, 10 ERRORS) და ცოცხალ `agy`-ზე გაჟონილი Mock ტესტები
- **Affected Component(s):** `tests/test_runtime_adapter.py` (5 fail), `tests/test_company_orchestration_engine.py` (4 fail), `tests/test_jester_live_knowledge.py` (8 error + 1 fail), `tests/test_jester_live_run.py` (2 error), `tests/test_qa_execution.py` (1 fail WinError 32), `tests/test_step23b5b_runtime_reliability.py` (2 fail), `tests/test_step24_4_3_artifact_recovery.py` (1 fail), `tests/test_target_repository_guard.py` (2 fail)
- **Severity:** **P2**
- **Evidence:** `task-39` (`python -m pytest tests/ -q --tb=short` → `16 failed, 901 passed, 2 skipped, 10 errors in 632.68s`). `test_runtime_adapter.py` აყალბებს `subprocess.run`-ს მაშინ, როცა `runtime.py` იყენებს `subprocess.Popen`-ს → 5 unit ტესტი რეალურად უშვებს ცოცხალ `agy` პროცესებს!
- **Proposed Correction:** დაამატეთ `pyproject.toml` (`pythonpath = ["."]`, `testpaths = ["tests"]`, `@pytest.mark.live` მარკერი), განაახლეთ `test_runtime_adapter.py` `subprocess.Popen`-ზე, მოაშორეთ Desktop Jester-ის მყარი კომიტის ჰეშები unit ტესტებიდან.
- **Verification Status:** **Confirmed (Full Baseline Pytest Execution)**

#### `DEF-025` — Windows-ზე `git worktree remove` და `kill_process_tree` გაუმართაობა
- **Affected Component(s):** `jester_ai_company/worktree.py:407`, `jester_ai_company/runtime.py:65`
- **Severity:** **P2**
- **Evidence:** `task-39` ლოგები: `PermissionError: [WinError 32]` worktree-ს წაშლისას (`test_live_qa_agent_failing_proof`) და `WARNING runtime.py:65 Failed to terminate process tree for PID 38172`.
- **Proposed Correction:** დაამატეთ retry/backoff და `taskkill /F /T /PID` საიმედო დამუშავება + worktree-ს ობოლი დირექტორიების პერიოდული prune.
- **Verification Status:** **Confirmed (Observed in Baseline Run)**

#### `DEF-026` — ორი შეუთავსებელი ორკესტრაციის ძრავა + Frontend 10-წამიანი timeout და hardcoded `mock=true`
- **Affected Component(s):** `jester_ai_company/execution.py`, `frontend/src/api/client.ts:32`, `frontend/src/hooks/useCompanyState.ts:274`
- **Severity:** **P2**
- **Evidence:** `client.ts:32` (`10000` ms timeout ბლოკავს ცოცხალ `/api/chat` და `/clarify`-ს), `useCompanyState.ts:274` (`mock: true`), Legacy `TaskExecutor` თანაარსებობს `CompanyRun`-თან.
- **Proposed Correction:** გაზარდეთ/გამიჯნეთ timeout-ები ასინქრონული და სინქრონული მოთხოვნებისთვის, მოაშორეთ `mock=true` UI-ს რემედიაციიდან და გადაიყვანეთ Legacy `TaskExecutor` deprecated/disabled რეჟიმში.
- **Verification Status:** **Confirmed (Source Audit)**

#### `DEF-027` — `developer_result.py`-ს აკლია `verification_actions`, ხოლო `recovery.py` შეიცავს მიუღწევად retry-ს და სუსტ AC შემფასებელს
- **Affected Component(s):** `jester_ai_company/developer_result.py`, `jester_ai_company/engineering_pipeline.py:527`, `jester_ai_company/recovery.py:290, 604-636`
- **Severity:** **P2**
- **Evidence:** `engineering_pipeline.py:527` კითხულობს `plan_details.get("verification_actions", [])` (არ არსებობს `DeveloperTaskResult`-ში); `recovery.py:290` `attempt_number == 1` კონფლიქტშია `max_retries=1`-თან; `evaluate_acceptance_criteria` ამოწმებს მხოლოდ ფაილის სახელის substring-ს.
- **Proposed Correction:** დაამატეთ ტიპიზებული `verification_actions` `DeveloperTaskResult`-ში და გაასწორეთ `recovery.py`-ს retry/AC ლოგიკა.
- **Verification Status:** **Confirmed (Source Audit)**

---

### P3 — დაბალი სიმძიმის დეფექტები

- **`DEF-028` — ცარიელი `garbage_collect` (`durable_storage.py:506-530`) და ობოლი `.runs/` ფაილები:** `.runs/` უკვე 1,979 ფაილია (10.53 MB), 25 run გაჭედილია `RUNNING`-ში, 25 — `CREATED`-ში. **Status: Confirmed.**
- **`DEF-029` — მოძველებული დოკუმენტაცია და სკრიპტები:** `README.md`, `docs/ARCHITECTURE.md`, `BACKLOG.md` ეწინააღმდეგება რეალობას; `tools/verify_company.py` ამოწმებს მხოლოდ 4 აგენტს 7-ის ნაცვლად; `status.py` კითხულობს მხოლოდ ძველ `.runs/run_*`-ს და ვერ ხედავს `company_runs`-ს; `core.py:514-518` იგნორირებს `agent.md`-ის tool სიებს. **Status: Confirmed.**
- **`DEF-030` — `pyproject.toml` / `pytest.ini`-ის არარსებობა:** შიშველი `pytest` ბრძანება ვარდება 8 `ModuleNotFoundError`-ით და აგროვებს `scratch/test_*.py`-ს. **Status: Confirmed.**
- **`DEF-031` — დუბლიკატი და ჩრდილოვანი რეპოზიტორიები სამუშაო გარემოში:** `Desktop\JesterAICompany` (1 კომიტით ჩამორჩენილი) და `scratch\jester` (მიუთითებს `JesterAI.git`-ზე და არა `Jester.git`-ზე) ქმნის ოპერაციული შეცდომის რისკს. **Status: Confirmed.**

---

## ნაწილი 2 — ძლიერად დასაბუთებული რისკები (Strongly Supported Risks)

1. **`RISK-01` — მონოლითური `service.py` (6,517 ხაზი):** ერთი კლასი (`CompanyService`) აერთიანებს ორკესტრაციას, 7 აგენტის გაშვებას, არტეფაქტების შენახვას, recovery-ს, design approval-სა და real repo apply-ს. ამან პირდაპირ გამოიწვია `spec_dur` `UnboundLocalError`, `Project.add_task` რეგრესია და 4 ჩავარდნილი ტესტი `test_company_orchestration_engine.py`-ში.
2. **`RISK-02` — ხარჯებისა და კვოტების უკონტროლობა:** ტოკენების აღრიცხვის, run-ბიუჯეტისა და მოდელის fallback-ის არარსებობის გამო 1 რთული run (9–23 წუთი, მრავალი retry + repair) შეუზღუდავად ხარჯავს API კვოტას და 429 შეცდომაზე უბრალოდ იშლება.
3. **`RISK-03` — სექვენციური DAG შესრულება:** მიუხედავად იმისა, რომ DAG უშვებს პარალელურ ფან-აუთს (მაგ., UX + Marketing), `execute_next_company_work` ასრულებს მხოლოდ 1 ელემენტს ჯერზე, რაც ზრდის საერთო ლატენტობას.

---

## ნაწილი 3 — დაუდასტურებელი ჰიპოთეზები (Unverified Hypotheses)

1. **`HYP-01` — `agy.exe --dangerously-skip-permissions` vs `.agents/hooks.json`:** არ არის ექსპერიმენტულად გაზომილი, ასრულებს თუ არა `agy` CLI v1.3.6 `PreToolUse` hook-ს მაშინ, როცა გადაცემულია `--dangerously-skip-permissions`, თუ ეს დროშა hook-საც თიშავს. **სავალდებულო შესამოწმებელია Stage 0-ში!**
2. **`HYP-02` — ცოცხალი End-to-End 7-აგენტიანი რეალური კოდის ციკლი `Jester`-ზე მიმდინარე კომიტზე:** აუდიტში შეგნებულად არ გაეშვა მუტაციური ცოცხალი run `Desktop/Jester`-ზე (არა-დესტრუქციული წესის გამო + target branch mismatch `codex/home-geometric-humanism` vs `main`). რეალური 7-აგენტიანი LLM ხარისხი (hallucination rate, patch compile rate) სრულად უნდა შეფასდეს Stage 1–3 გასწორებების შემდეგ იზოლირებულ კლონზე.

---

## ნაწილი 4 — გაუმჯობესების შესაძლებლობები (Improvement Opportunities)

1. **`IMP-01`:** გადაიყვანეთ `product_result.py`-ის მოთხოვნები სტრუქტურირებულ მასივზე (`[{"id": "REQ-001", "text": "...", "acceptance_criteria": [...]}]`), რათა Developer და QA ავტომატურად ატრასირებდნენ თითოეულ მოთხოვნას.
2. **`IMP-02`:** შეცვალეთ JSON ფაილების ნაკრები `.runs/`-ში მსუბუქი SQLite მდგომარეობის საცავით (მხოლოდ მას შემდეგ, რაც P0/P1 გამოსწორდება) — აგვარებს lock-ებს, რესტარტის reconciliation-სა და სტატუსის კონსისტენტურობას.
3. **`IMP-03`:** დაამატეთ `agy` სესიის ტოკენების/ხარჯის ტელემეტრია და run-ის ბიუჯეტის ზღვარი.
4. **`IMP-04`:** გააერთიანეთ `cli.py` და `status.py` თანამედროვე `CompanyRun` საცავთან.
