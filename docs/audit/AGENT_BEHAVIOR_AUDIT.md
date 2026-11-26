# აგენტების ქცევისა და ინტელექტის აუდიტი (AGENT BEHAVIOR AUDIT)

**აუდიტის ფაზა:** Phase C — შვიდივე აგენტის ინდივიდუალური შეფასება  
**შემოწმებული წყაროები:** `.agents/agents/*/agent.md`, `jester_ai_company/{ceo_contract,research_result,product_result,ux_result,marketing_result,developer_result,developer_mutation,qa_result,qa_execution,repair,service,engineering_pipeline,policy_hook,runtime}.py`

---

## 1. შემაჯამებელი მატრიცა: რეალური შესრულება vs აღწერა

აუდიტის ერთ-ერთი უმთავრესი მოთხოვნაა მკაფიო გამიჯვნა ექვს სტადიას შორის:
**შეთავაზებული (Proposed) → მცდელობა (Attempted) → შესრულებული (Executed) → ვერიფიცირებული (Verified) → დამტკიცებული (Approved) → გამოქვეყნებული (Released).**

| აგენტი | რეალურად ასრულებს სამუშაოს თუ მხოლოდ აღწერს? | ინსტრუმენტების ხელმისაწვდომობა / საიმედოობა | კონტრაქტის შესაბამისობა (`agent.md` ↔ Python) | საერთო შეფასება |
| :--- | :--- | :--- | :--- | :--- |
| **1. CEO** | **ნაწილობრივ / უმეტესად გვერდის ავლით** — `is_production=False`-ში შეფასებასა და გუნდის შერჩევას საერთოდ არ ასრულებს; მხოლოდ DAG JSON-ს აგენერირებს | `agy --agent ceo --dangerously-skip-permissions`; არ გააჩნია tool-ის პოლიტიკის hook | **გაფუჭებულია** (`audit`, `FEATURE`, `GENERAL` იწვევს ვალიდაციის კრაშს) | **არასაიმედო** |
| **2. Product** | **ასრულებს სპეციფიკაციას** (ქმნის მდგრად PRD არტეფაქტს), თუმცა დოკუმენტის ხარისხი და კონტექსტი იზღუდება 28k ჩამოჭრით | `agy --agent product --dangerously-skip-permissions`; ფაქტობრივად არ გააჩნია write-დაცვის hook | **ნაწილობრივი შეუსაბამობა** (`agent.md` Markdown vs JSON `deliverables`) | **საშუალო (საჭიროებს გასწორებას)** |
| **3. Research** | **ასრულებს კვლევას** (ქმნის სტრუქტურირებულ `schema 1.1` ანგარიშს), თუმცა `service.py` **უგულებელყოფს მისთვის აწყობილ `ContextEnvelope`-ს და `role_knowledge`-ს!** | `agy --agent research --dangerously-skip-permissions`; არ გააჩნია read-only hook (რეალურად აქვს write/shell წვდომა!) | **ნაწილობრივი შეუსაბამობა** (`agent.md` Markdown vs JSON `sources`/`findings.claim`) | **საშუალო-დაბალი** |
| **4. UX** | **ასრულებს UX სპეციფიკაციას**, მაგრამ ვიზუალური პროტოტიპირების რეჟიმში დაბინძურებულია Jester-ის მყარი ქართული შაბლონებით და აგდებს 3-არტეფაქტის კრაშს / UI deadlock-ს | `agy --agent ux --dangerously-skip-permissions`; არ გააჩნია read-only hook | **გაფუჭებულია** (`agent.md` კრძალავს დამატებით ველებს, `ux_result.py` მოითხოვს `concepts`-ს) | **პრობლემური** |
| **5. Marketing** | **ასრულებს მარკეტინგის დოკუმენტს**, მაგრამ `service.py` **აგდებს მის `ContextEnvelope`-ს და `role_knowledge`-ს** | `agy --agent marketing --dangerously-skip-permissions`; არ გააჩნია read-only hook | **ნაწილობრივი შეუსაბამობა** (`agent.md` Markdown vs JSON `target_audiences`/`channels_or_tactics`) | **საშუალო-დაბალი** |
| **6. Developer** | **რეალურად ცვლის კოდს** იზოლირებულ worktree-ში და აწარმოებს `CODE_PATCH`-ს (დადასტურებულია); მაგრამ Repair Planning ეშვება `repo_root`-ში hook-ის გარეშე, `developer_mutation.py`-ში არის `UnboundLocalError`, და `hook_policy.py` გაუმართავია | Worktree mutation-ს აქვს `hook_policy.py`, მაგრამ კვოტას არ ამოწმებს, მეორე ჩაწერას ბლოკავს და `write_file`/`edit_file`-ს არ ცნობს; Repair Planning-ს hook საერთოდ არ აქვს | **გაფუჭებულია** (`agent.md`-ში საერთოდ არ წერია Mode C / Repair Planning; `developer_result.py`-ს აკლია `verification_actions`) | **მაღალი რისკის ქვეშ** |
| **7. QA** | **ინსპექცია (14A) + იზოლირებული ტესტების გაშვება (14B) იმპლემენტირებულია**, მაგრამ **არასაიმედოა**: 14A აყალბებს `VERIFIED` კატეგორიებს, 14B უშვებს `PASS`-ს 0 ტესტზე, 14A ეშვება `JesterAICompany`-ში სამიზნე რეპოს ნაცვლად, ხოლო 14B timeout 30 წამზეა ჩაჭედილი | 14A: `agy --agent qa` (`repo_root`-ში!); 14B: აპლიკაციის მფლობელობაში არსებული `verification.py` worktree-ში (`timeout=30s`) | **გაფუჭებულია** (`audit` vs `read_only_audit`; Mode B ტრიგერის შეუსაბამობა) | **არასაიმედო (კრიტიკული ხვრელები)** |

> [!CAUTION]
> **სისტემური დარღვევა ყველა არა-მუტაციურ აგენტზე:** `AntigravityRuntime` (`runtime.py:181`) **ყველა** აგენტს — მათ შორის CEO, Product, Research, UX, Marketing და QA-ს — უშვებს დროშით `--dangerously-skip-permissions`, ხოლო `PreToolUse` read-only hook (`install_planning_policy_hook`) დაყენებულია **მხოლოდ** `execute_developer_planning_task`-ში! შესაბამისად, ყველა „read-only“ აგენტის უსაფრთხოება ეფუძნება მხოლოდ პრომპტში ჩაწერილ სიტყვიერ თხოვნას და არა ტექნიკურ იძულებას (enforcement).

---

## 2. შვიდივე აგენტის დეტალური ინდივიდუალური აუდიტი (15 კრიტერიუმი)

### 2.1 CEO Agent (`.agents/agents/ceo/agent.md`, `ceo_contract.py`, `dag.py`, `service.py`)

1. **System Prompt-ის სიცხადე:** ვრცელი, მაგრამ **შინაგანად წინააღმდეგობრივი** Python კოდთან (`qa_capability: "audit"` ხაზი 76, `task_category: "FEATURE" | "GENERAL"` ხაზი 137).
2. **როლის საზღვრები:** დეკლარირებულია როგორც კოორდინატორი და პლანერი, არა კოდის შემსრულებელი. რეალურად `service.py` ხშირად გვერდს უვლის მას (`is_production=False`).
3. **შემავალი მონაცემების ვალიდაცია:** `evaluate_company_objective` (`service.py:4714`) იყენებს სიტყვათა სიგრძისა და საკვანძო სიტყვების ჰევრისტიკას; მარტივად ცდება არასტანდარტულ ან არა-ინგლისურ (მაგ., ქართულ) ამოცანებზე.
4. **გამომავალი სტრუქტურა:** `parse_and_validate_ceo_plan` (`ceo_contract.py:300+`) მკაცრია (`schema_version: "1.0"`, `work_items`, `depends_on`), მაგრამ სწორედ ეს სიმკაცრე აგდებს კრაშს, თუ CEO დაიცავს საკუთარ `agent.md`-ს (`AUDIT-BUG-09A`, `AUDIT-BUG-09B`).
5. **ხელმისაწვდომი ინსტრუმენტები:** `core.py:514-518` უგულებელყოფს `agent.md`-ში მითითებულ ინსტრუმენტების სიას; რანტაიმში CEO-ს აქვს სრული `--dangerously-skip-permissions` წვდომა hook-ის გარეშე.
6. **ინსტრუმენტების გამოყენების საიმედოობა:** Legacy `TaskExecutor`-ში CEO იძახებს subagent-ებს უკონტროლოდ; Modern `CompanyRun`-ში CEO-ს საერთოდ არ ეძლევა tool-ებით დელეგირების უფლება.
7. **კონტექსტის დამუშავება:** `build_ceo_evaluation_prompt` (`ceo_contract.py:619`) და `build_ceo_team_selection_prompt` (`ceo_contract.py:1130`) იღებენ `project_knowledge` პარამეტრს და **სრულად აიგნორებენ მას!**
8. **გადაწყვეტილების უფლებამოსილება:** **სერიოზული ხვრელი (`AUDIT-ADV-01`):** თუ `team_selection` არ გადაეცა, CEO-ს არასანდო JSON-ს შეუძლია თვითავტორიზაცია (`"allow_direct_developer": true`, `"task_category": "BUG_FIX"`) და Product+UX fan-in-ის გვერდის ავლა!
9. **შეცდომების დამუშავება:** `PlanValidationError` აჩერებს run-ს, მაგრამ არ არსებობს ავტომატური retry CEO-ს სქემის შეცდომაზე Control Center-ის ფონურ ნაკადში.
10. **კოლაბორაციის ქცევა:** CEO არ ურთიერთობს სპეციალისტებთან შესრულების მიმდინარეობისას; არ ამოწმებს და არ არიგებს წინააღმდეგობრივ შედეგებს.
11. **ესკალაციის წესები:** `WAITING_FOR_CLARIFICATION` მუშაობს საწყის ეტაპზე (`AUDIT-SCEN-02`), მაგრამ `control_center.py:1072` არ აგრძელებს ფონურ worker-ს, თუ clarification მოხდა შუა შესრულებისას (`RUNNING`).
12. **დასრულების კრიტერიუმები:** CEO არ ამოწმებს საბოლოო მტკიცებულებებს; კომპანიის დასრულების სტატუსს აყენებს `CompanyService` და არა CEO.
13. **უსაფრთხოების შეზღუდვები:** სუსტი — `--dangerously-skip-permissions` + 0 hook + `allow_direct_developer` თვითავტორიზაციის შესაძლებლობა.
14. **ჰალუცინაციის რისკები:** მაღალი — რადგან `project_knowledge` იკარგება შეფასებისა და გუნდის შერჩევის პრომპტებში, ხოლო `investigate_objective` არ კითხულობს ფაილებს.
15. **არასრული/წინააღმდეგობრივი ინფორმაციისგან აღდგენა:** მუშაობს მხოლოდ ბუნდოვანი მოთხოვნის საწყის ბარიერზე (ჰევრისტიკული clarification); წინააღმდეგობრივი სპეციალისტის შედეგების გადაწყვეტა არ არის რეალიზებული.

---

### 2.2 Product Agent (`.agents/agents/product/agent.md`, `product_result.py`, `service.py`)

1. **System Prompt-ის სიცხადე:** საშუალო — `agent.md` კარგად აღწერს პროდუქტის პასუხისმგებლობას, თუმცა ფორმატის ნაწილი ეწინააღმდეგება `product_result.py`-ის JSON მოთხოვნას (`deliverables`).
2. **როლის საზღვრები:** მკაფიოა — არ წერს კოდს, განსაზღვრავს პრობლემას, მოთხოვნებს, პრიორიტეტებსა და acceptance criteria-ს.
3. **შემავალი მონაცემების ვალიდაცია:** აპლიკაცია ამოწმებს წინამორბედი არტეფაქტების SHA-256 ჰეშს (`load_and_verify_input_artifact`), რაც კარგია.
4. **გამომავალი სტრუქტურა:** `parse_and_validate_product_result` მკაცრად ამოწმებს `schema_version: "1.0"`, `status`, `summary`, `deliverables`.
5. **ხელმისაწვდომი ინსტრუმენტები:** `agy --agent product --dangerously-skip-permissions` read-only hook-ის გარეშე.
6. **ინსტრუმენტების საიმედოობა:** საშუალო; არ არსებობს ტექნიკური ბარიერი, რომელიც Product აგენტს შეუშლის ხელს ფაილების შეცვლაში.
7. **კონტექსტის დამუშავება:** იღებს `ContextEnvelope`-ს და `role_knowledge`-ს, თუმცა `service.py:5495-5505` ყველა 6 წყაროს სვამს `mandatory_knowledge_sources`-ში (არღვევს `max_sources=3` ლიმიტს), რის გამოც პრომპტი შეიძლება გადასცდეს 28,000 სიმბოლოს და `runtime.py:167`-მა ჩამოჭრას ბოლოში მდებარე JSON სქემა!
8. **გადაწყვეტილების უფლებამოსილება:** არ აქვს კოდის ან გამოქვეყნების უფლება; მოთხოვნები გადაეცემა UX/Marketing/Developer-ს.
9. **შეცდომების დამუშავება:** ვალიდაციის ჩავარდნაზე `recovery.py` აკეთებს bounded compact retry-ს (`compact_prd=True`).
10. **კოლაბორაციის ქცევა:** სექვენციური (იღებს Research-ს, გადასცემს UX/Marketing/Developer-ს); `deliverables` არის თავისუფალი ტექსტი (`content` სტრინგი), არა სტრუქტურირებული მოთხოვნების მასივი ID-ებით (`REQ-001`), რაც ართულებს QA-სა და Developer-ის მიერ ავტომატურ ტრასირებას.
11. **ესკალაციის წესები:** შეუძლია ჩაწეროს `open_questions`, მაგრამ ორკესტრატორი ავტომატურად **არ აჩერებს** run-ს დამფუძნებლისთვის Product-ის `open_questions`-ზე.
12. **დასრულების კრიტერიუმები:** სქემის ვალიდაცია + არტეფაქტის (`product_report.md`) დისკზე მატერიალიზაცია და SHA-256 შემოწმება.
13. **უსაფრთხოების შეზღუდვები:** არტეფაქტის მონაცემები მოქცეულია trust boundary დელიმიტერებში, მაგრამ აკლია OS/PreToolUse read-only დაცვა.
14. **ჰალუცინაციის რისკები:** საშუალო-მაღალი — თუ წინამორბედი Research არ ტარდება და `project_knowledge` ჩამოიჭრება 28k ზღვარზე, Product იგონებს რეპოზიტორიის ფუნქციონალს.
15. **აღდგენა არასრული ინფორმაციისგან:** `compact_prd` retry ეხმარება timeout-ზე, მაგრამ ბიზნეს-გაურკვევლობას არ აბრუნებს დამფუძნებელთან.

---

### 2.3 Research Agent (`.agents/agents/research/agent.md`, `research_result.py`, `service.py`)

1. **System Prompt-ის სიცხადე:** მაღალი ხარისხის ეპისტემური წესები (`verified_source`, `inferred`, `certainty`), მაგრამ ეწინააღმდეგება JSON `schema 1.1` სავალდებულო ფორმატს.
2. **როლის საზღვრები:** მკაფიოდ read-only კვლევა; არ წერს PRD-ს ან კოდს.
3. **შემავალი მონაცემების ვალიდაცია:** `execute_next_company_work` (`service.py:5576-5629`) აწყობს `ContextEnvelope`-ს და `role_knowledge`-ს, **და შემდეგ არ გადასცემს მათ `execute_research_task`-ს!** (დადასტურებული კონტექსტის დაკარგვის დეფექტი).
4. **გამომავალი სტრუქტურა:** ყველაზე მკაცრი სქემა (`schema_version: "1.1"`, `sources` with `source_id`, `findings` with `claim`/`evidence`/`evidence_status`/`source_ids`/`certainty`).
5. **ხელმისაწვდომი ინსტრუმენტები:** `agy --agent research --dangerously-skip-permissions` — არ გააჩნია read-only PreToolUse hook!
6. **ინსტრუმენტების საიმედოობა:** ისტორიულ ლოგებში (`crun_a8d46db1`, `test_step23b5b`) ხშირია 300-წამიანი timeout-ები დიდ რეპოზიტორიებზე.
7. **კონტექსტის დამუშავება:** **დაზიანებულია** — აწყობილი `ContextEnvelope` და პროექტის ცოდნა იკარგება გადაცემისას (`service.py:5576-5629`).
8. **გადაწყვეტილების უფლებამოსილება:** მხოლოდ ანალიტიკური; არ შეუძლია მუტაცია ან დამტკიცება.
9. **შეცდომების დამუშავება:** იყენებს `recovery.py`-ს (401 auth შეცდომაზე დაუყოვნებლივ აჩერებს retry-ს — დადასტურებულია `AUDIT-SCEN-05`-ში).
10. **კოლაბორაციის ქცევა:** აწვდის `RESEARCH_REPORT`-ს Product-ს; სხვა აგენტებთან პირდაპირ არ კომუნიკირებს.
11. **ესკალაციის წესები:** `open_questions` იწერება ანგარიშში, მაგრამ ავტომატურ ესკალაციას არ იწვევს.
12. **დასრულების კრიტერიუმები:** `schema 1.1` ვალიდაცია + `research_report.md` მატერიალიზაცია.
13. **უსაფრთხოების შეზღუდვები:** არ გააჩნია ტექნიკური read-only hook; `workspace_dir` ზოგჯერ მიუთითებს რეალურ სამიზნე რეპოზე.
14. **ჰალუცინაციის რისკები:** დაბალი-საშუალო (`evidence_status` ვალიდაცია კარგია, მაგრამ ვალიდატორი არ ამოწმებს, რეალურად არსებობს თუ არა მითითებული `reference` ფაილი დისკზე).
15. **აღდგენა არასრული ინფორმაციისგან:** კარგად გამოხატავს გაურკვევლობას `uncertainties`/`open_questions`-ში, მაგრამ ვერ იღებს წინასწარ შეგროვებულ `role_knowledge`-ს.

---

### 2.4 UX Agent (`.agents/agents/ux/agent.md`, `ux_result.py`, `prototype_renderer.py`, `design_recovery.py`)

1. **System Prompt-ის სიცხადე:** **კონფლიქტურია:** `ux/agent.md:58-70` აშკარად კრძალავს დამატებით ველებს, მაშინ როცა `ux_result.py:383-419` ვიზუალურ რეჟიმში მოითხოვს `concepts` და `recommended_concept_id`-ს.
2. **როლის საზღვრები:** დიზაინის სპეციფიკაცია და ვიზუალური კონცეპტები. **მძიმე არქიტექტურული დაბინძურება:** `ux_result.py:407-419` ნებისმიერ UX ამოცანაში, რომელშიც გვხვდება სიტყვები `"concept"`, `"prototype"`, `"visual"` ან `"redesign"`, ავტომატურად ტენის **Jester Social Astrology**-ის, `#FF7A2F`-ის, `jester_logo.svg`-ისა და 100% ქართული ტექსტის ინსტრუქციებს!
3. **შემავალი მონაცემების ვალიდაცია:** იღებს PRD-ს (თუ არსებობს); `UI_UX_CHANGE`-ზე შეუძლია იმუშაოს PRD-ის გარეშე, მაგრამ შემდეგ დეველოპერის ეტაპი კრაშავს (`AUDIT-BUG-01`).
4. **გამომავალი სტრუქტურა:** `ux_result.py` მხარს უჭერს ორ რეჟიმს (სტანდარტული `flows`+`screens` და ვიზუალური `concepts`), რაც ქმნის `UX_SPECIFICATION` + `UX_PROTOTYPE` არტეფაქტებს.
5. **ხელმისაწვდომი ინსტრუმენტები:** `agy --agent ux --dangerously-skip-permissions` read-only hook-ის გარეშე; HTML პრევიუს რენდერინგი (`prototype_renderer.py`) აპლიკაციის მხარესაა და აქვს XSS/CSP ფილტრაცია (დადებითი მხარე).
6. **ინსტრუმენტების საიმედოობა:** საშუალო; `prototype_renderer.py:28,183-204` მყარად ეყრდნობა `C:\Users\fiord\OneDrive\Desktop\Jester`-ს და რეგისტრაციის შაბლონს.
7. **კონტექსტის დამუშავება:** იღებს `ContextEnvelope`-ს, მაგრამ ვიზუალური პროტოტიპის არტეფაქტი (`UX_PROTOTYPE`) იწვევს **გარანტირებულ კრაშს** Developer Planning-ში (`AUDIT-BUG-02` — 3 არტეფაქტის უარყოფა!).
8. **გადაწყვეტილების უფლებამოსილება:** ვიზუალურ კონცეპტებზე დიზაინის დამტკიცება ეკუთვნის დამფუძნებელს (`design_approval.py`), მაგრამ **Control Center-ში არ არსებობს არცერთი HTTP endpoint ან UI ღილაკი დიზაინის დასამტკიცებლად** — შედეგად, run სამუდამოდ იჭედება `WAITING_FOR_HUMAN` სტატუსში (რაც დადასტურდა რეალურ ლოგშიც: `crun_29fcdd4a` 2,384.5 წამის შემდეგ კვლავ `WAITING_FOR_HUMAN`-შია!).
9. **შეცდომების დამუშავება:** `design_recovery.py:264-475` და `service.py:6245-6253` მყარად არის მიბმული ერთ კონკრეტულ ისტორიულ run-ზე (`crun_29fcdd4a`, `/auth/register`) და არ არის ზოგადი აღდგენის მექანიზმი.
10. **კოლაბორაციის ქცევა:** აწვდის `UX_SPECIFICATION`-ს Developer-სა და Marketing-ს; კონტრაქტის წყვეტა Developer-თან ორივე ახალ ნაკადზე (`UI_UX_CHANGE` და ვიზუალური კონცეპტები).
11. **ესკალაციის წესები:** `WAITING_FOR_HUMAN` კარიბჭე არქიტექტურულად ჩაკეტილია Control Center-იდან.
12. **დასრულების კრიტერიუმები:** სქემის ვალიდაცია + `ux_report.md` (და პრევიუ HTML-ები).
13. **უსაფრთხოების შეზღუდვები:** `prototype_renderer.py`-ის უსაფრთხოების ფილტრები (`test_step24_4_2_renderer_security.py`) გადის ტესტებს; აგენტის პროცესს კვლავ აკლია read-only hook.
14. **ჰალუცინაციის რისკები:** მაღალი არა-Jester პროექტებზე — სისტემა თვითონ აიძულებს UX აგენტს დააგენერიროს Jester-ის ასტროლოგიის ბრენდირება.
15. **აღდგენა არასრული ინფორმაციისგან:** სუსტი, რადგან `design_recovery` მყარად კოდირებულია ერთ ისტორიულ მაგალითზე.

---

### 2.5 Marketing Agent (`.agents/agents/marketing/agent.md`, `marketing_result.py`, `service.py`)

1. **System Prompt-ის სიცხადე:** კარგად აღწერს პოზიციონირებას და არსებითად ითხოვს ფაქტებზე დაყრდნობას, მაგრამ არ ასახავს `marketing_result.py`-ის ზუსტ JSON სქემას.
2. **როლის საზღვრები:** მკაფიოდ არა-ტექნიკური პოზიციონირება და მესიჯინგი; არ ეხება კოდს.
3. **შემავალი მონაცემების ვალიდაცია:** `execute_next_company_work` (`service.py:5576-5629`) **აგდებს `ContextEnvelope`-ს და `role_knowledge`-ს** `execute_marketing_task`-ის გამოძახებისას!
4. **გამომავალი სტრუქტურა:** `parse_and_validate_marketing_result` მკაცრად ამოწმებს `positioning`, `target_audiences`, `key_messages`, `channels_or_tactics`, `deliverables`.
5. **ხელმისაწვდომი ინსტრუმენტები:** `agy --agent marketing --dangerously-skip-permissions` read-only hook-ის გარეშე.
6. **ინსტრუმენტების საიმედოობა:** არ საჭიროებს ინსტრუმენტებს, თუმცა რანტაიმში მათზე სრული წვდომა აქვს.
7. **კონტექსტის დამუშავება:** იღებს upstream არტეფაქტებს (PRD/UX), მაგრამ კარგავს `project_knowledge`-სა და `ContextEnvelope`-ს.
8. **გადაწყვეტილების უფლებამოსილება:** მხოლოდ საკონსულტაციო/დოკუმენტური; ნულოვანი მუტაციის უფლება.
9. **შეცდომების დამუშავება:** სტანდარტული `recovery.py` retry ვალიდაციის ჩავარდნაზე.
10. **კოლაბორაციის ქცევა:** კარგად მუშაობს არაკოდურ ფან-აუთ/ფან-ინ ჯაჭვში (`AUDIT-SCEN-03` PASSED სიმულირებულ ტესტში).
11. **ესკალაციის წესები:** `open_questions` არ იწვევს დამფუძნებელთან პაუზას.
12. **დასრულების კრიტერიუმები:** JSON ვალიდაცია + `marketing_report.md` მატერიალიზაცია.
13. **უსაფრთხოების შეზღუდვები:** აკლია ტექნიკური read-only hook.
14. **ჰალუცინაციის რისკები:** საშუალო-მაღალი — `role_knowledge`-ის დაკარგვის გამო შეიძლება დაუშვას არაზუსტი პროდუქტის მტკიცებები.
15. **აღდგენა არასრული ინფორმაციისგან:** აღრიცხავს `assumptions`-ს, რაც კარგი პრაქტიკაა, მაგრამ ვერ მოითხოვს დაზუსტებას.

---

### 2.6 Developer Agent (`.agents/agents/developer/agent.md`, `developer_result.py`, `developer_mutation.py`, `repair.py`, `engineering_pipeline.py`, `policy_hook.py`)

1. **System Prompt-ის სიცხადე:** არასრული — აღწერს Planning (Mode A) და Mutation (Mode B), მაგრამ **სრულად ტოვებს Mode C-ს (Repair Planning, STEP 15)**.
2. **როლის საზღვრები:** დაგეგმილია მკაცრი გამიჯვნა: Planning (read-only) → ExecutionGrant → Isolated Worktree Mutation → `CODE_PATCH` → Verification. რეალურად, **Repair Planning (`service.py:3827-3833`) არღვევს ამ საზღვარს**: ეშვება პირდაპირ `self.repo_root`-ში (არა `target_repo`-ში, არა worktree-ში) და **hook-ის გარეშე!**
3. **შემავალი მონაცემების ვალიდაცია:** ძალიან მკაცრი, ზოგჯერ ზედმეტად ხისტი (`len != 2` აგდებს კრაშს ვიზუალურ პროტოტიპზე — `AUDIT-BUG-02`; `engineering_pipeline.py:190` აგდებს კრაშს `UI_UX_CHANGE`-ზე — `AUDIT-BUG-01`).
4. **გამომავალი სტრუქტურა:**
   - `developer_result.py`-ს **არ გააჩნია `verification_actions` ველი**, მაშინ როცა `engineering_pipeline.py:527` კითხულობს `plan_details.get("verification_actions", [])` (ყოველთვის ცარიელია!).
   - **`developer_mutation.py:169` კრაშავს `UnboundLocalError: json_str`-ით**, თუ დეველოპერის პასუხში ფიგურული ფრჩხილებიანი ტექსტი უძღვის წინ fenced JSON-ს (დადასტურებულია `AUDIT-BUG-05`-ში!).
   - `developer_mutation.py:195` მყარად ახსენებს `"allowed.txt"`-ს.
5. **ხელმისაწვდომი ინსტრუმენტები:** Worktree mutation-ისას უყენდება `install_execution_policy_hook`, თუმცა **`AUDIT-SEC-06`-მა დაადასტურა 4 კრიტიკული ხარვეზი `hook_policy.py`-ში**:
   - `max_bytes_written` და `max_files_changed` საერთოდ არ მოწმდება (10 KB ჩაწერა დაშვებული იქნა 10-ბაიტიან ლიმიტზე!).
   - ახლად შექმნილი ფაილის მეორეჯერ რედაქტირება **იბლოკება** `hook_policy.py`-ით (მიუხედავად იმისა, რომ `authorize_tool_mutation` უშვებს მას!).
   - Windows backslash (`src\app.py`) არ ნორმალიზდება და იბლოკება.
   - `agy` 1.3.6-ის თანამედროვე tool-ების სახელები (`read_file`, `write_file`, `edit_file`) უპირობოდ იბლოკება (მხოლოდ ძველი `view_file`/`write_to_file`/`replace_file_content` არის ცნობილი).
6. **ინსტრუმენტების საიმედოობა:** Windows-ზე `git worktree remove` პერიოდულად ვარდება `PermissionError: [WinError 32]`-ით (დადასტურდა `task-39`-ში `test_live_qa_agent_failing_proof`-ზე).
7. **კონტექსტის დამუშავება:** იღებს PRD+UX-ს, მაგრამ 28,000 სიმბოლოს ჩამოჭრა (`runtime.py:167`) განსაკუთრებით სახიფათოა Developer-ისთვის, რომელსაც დიდი upstream დოკუმენტები გადაეცემა.
8. **გადაწყვეტილების უფლებამოსილება:** `ExecutionGrant` და `repair_approvals` სინთეზურად გენერირდება `engineering_pipeline.py:591,870-873`-ში დამფუძნებლის თანხმობის გარეშე (`AUDIT-SEC-05`).
9. **შეცდომების დამუშავება:** აქვს 2-იტერაციიანი Repair Loop (`repair.py`), რაც არქიტექტურულად კარგია, მაგრამ Repair Planning-ის იზოლაციის არქონა და სინთეზური approval-ები არღვევს მის უსაფრთხოებას.
10. **კოლაბორაციის ქცევა:** კარგი არტეფაქტ-ლინეაჟი (`CODE_PATCH` ატარებს `plan_sha256`-ს და `base_commit_hash`-ს), თუმცა `engineering_pipeline.py:1024`-ში `qa_exec_art.task_id` იწვევს `AttributeError`-ს, რომელიც ჩუმად ყლაპავს Developer/QA ტელემეტრიას (`AUDIT-BUG-10`).
11. **ესკალაციის წესები:** `requirement_conflict_detected` სქემაშია (`repair.py`), მაგრამ `developer/agent.md`-ში საერთოდ არ არის აღწერილი.
12. **დასრულების კრიტერიუმები:** რეალური `git diff` worktree-ში + აპლიკაციის მიერ გაშვებული `verification.py` + `CODE_PATCH` მატერიალიზაცია. ეს არის სისტემის ერთ-ერთი ყველაზე ძლიერი ნაწილი, რადგან დეველოპერი **ვერ** გააყალბებს კოდის ცვლილებას მხოლოდ ტექსტით.
13. **უსაფრთხოების შეზღუდვები:** `ExecutionGrant` და `worktree` კარგი საფუძველია, მაგრამ Repair Planning-ში hook-ის არარსებობა და `hook_policy.py`-ის ხვრელები არსებითად ასუსტებს მას.
14. **ჰალუცინაციის რისკები:** დაბალი კოდის ცვლილების ფაქტზე (მოწმდება `git diff`-ით), მაღალი ფაილების გზებზე Planning-ის ეტაპზე, თუ კონტექსტი ჩამოიჭრა ან Repair Planning არასწორ რეპოში (`self.repo_root`) გაეშვა.
15. **აღდგენა არასრული ინფორმაციისგან:** შეზღუდულია 2 repair იტერაციით; `UI_UX_CHANGE` და ვიზუალური კონცეპტების შემთხვევაში ვერც კი იწყებს მუშაობას.

---

### 2.7 QA Agent (`.agents/agents/qa/agent.md`, `qa_result.py`, `qa_execution.py`, `service.py`)

1. **System Prompt-ის სიცხადე:** **წინააღმდეგობრივია:** `qa/agent.md:47` იყენებს `"audit"`-ს (`orchestrator.py` მოითხოვს `"read_only_audit"`), ხოლო `qa/agent.md:88` Mode B ტრიგერის ტექსტი არ ემთხვევა `qa_result.py:592`-ს.
2. **როლის საზღვრები:** ორფაზიანი მოდელი (14A სტატიკური ინსპექცია + 14B იზოლირებული ტესტების გაშვება) არქიტექტურულად სწორია, მაგრამ იმპლემენტაციაში სერიოზული ხვრელებია.
3. **შემავალი მონაცემების ვალიდაცია:** **ძლიერი მხარე** — `execute_qa_verification_task` (`service.py:3153-3265`) მკაცრად ამოწმებს PRD, UX, Developer Plan, CODE_PATCH და QA_REPORT ლინეაჟსა და SHA-256 ჰეშებს (დადასტურდა ჩვენი ტესტირების დროს). თუმცა non-code QA-ზე `execute_next_company_work` (`service.py:5576-5629`) აგდებს `ContextEnvelope`-სა და `role_knowledge`-ს!
4. **გამომავალი სტრუქტურა:** **კრიტიკული ფალსიფიკაციის დეფექტი (`AUDIT-BUG-04`):** `qa_result.py:497-533` STEP 14A-ში (როცა არცერთი ტესტი ჯერ არ გაშვებულა!) ავტომატურად აგენერირებს `FUNCTIONAL_CORRECTNESS = VERIFIED ("Functional test suites passed in test environment.")` და `DESIGN_SPECIFICATION_COMPLIANCE = VERIFIED`!
5. **ხელმისაწვდომი ინსტრუმენტები:**
   - **14A Inspection (`service.py:2937,2968`):** შეცდომით ეშვება `self.repo_root`-ში (`JesterAICompany`) და ამოწმებს `self.repo_root`-ის სისუფთავეს, **სამიზნე რეპოზიტორიის (`target_repo`) ნაცვლად!**
   - **14B Execution (`service.py:3342`):** აპლიკაცია უშვებს ტესტებს ახალ worktree-ში, მაგრამ მყარად აწესებს `timeout=30.0` წამს — რაც არასაკმარისია `frontend_build` (`npm run build`) ან დიდი `pytest` სუიტისთვის!
6. **ინსტრუმენტების საიმედოობა:** Windows-ზე worktree-ს წაშლა ვარდება `PermissionError`-ით (`test_live_qa_agent_failing_proof`); 30-წამიანი timeout ხშირად აგდებს ცრუ ჩავარდნებს.
7. **კონტექსტის დამუშავება:** იღებს სრულ პატჩს და upstream დოკუმენტებს, მაგრამ ექვემდებარება 28k ჩამოჭრას (`runtime.py:167`).
8. **გადაწყვეტილების უფლებამოსილება:** **კრიტიკული ვერიფიკაციის გვერდის ავლა (`AUDIT-BUG-03`):** თუ QA Inspection 14A დააბრუნებს `recommended_verification_actions: []`, `qa_execution.py:550` (`no_actions_executed = (0 == 0 and 0 > 0) == False`) **უშვებს `QA PASS` ვერდიქტს 0 გაშვებული ტესტით** (დადასტურდა ექსპერიმენტულად!).
9. **შეცდომების დამუშავება:** თუ ტესტი გაეშვა და ჩავარდა (`exit_code != 0`), დეტერმინისტული override სწორად აძალებს `FAIL`-ს. სუსტი წერტილი სწორედ 0-ტესტიანი შემთხვევაა.
10. **კოლაბორაციის ქცევა:** `QA_EXECUTION_REPORT` გადაეცემა Repair Loop-სა და `RealRepoApplyProposal`-ს; კონტრაქტი მკაცრია, მაგრამ ცარიელი ტესტების ხვრელით დაზიანებული.
11. **ესკალაციის წესები:** `BLOCKED` ვერდიქტი მკაფიოდ განსაზღვრულია, თუმცა `recommended_verification_actions: []`-ზე არ ირთვება.
12. **დასრულების კრიტერიუმები:** **არღვევს Verified vs Proposed საზღვარს** — 14A აყალბებს `VERIFIED` სტატუსს, ხოლო 14B აბრუნებს `PASS`-ს გაშვებული ტესტების გარეშე.
13. **უსაფრთხოების შეზღუდვები:** 14A-ს არ აქვს read-only hook; 14B იყენებს აპლიკაციის სანქცირებულ `VerificationAction`-ს (`shell=False`, sanitized env), რაც ძლიერი მხარეა.
14. **ჰალუცინაციის რისკები:** მაღალი 14A-ში (ეშვება არასწორ რეპოში `JesterAICompany`, და პარსერი აყალბებს `VERIFIED` მტკიცებულებებს).
15. **აღდგენა არასრული ინფორმაციისგან:** თუ QA 14A ვერ პოულობს ტესტებს და აბრუნებს ცარიელ სიას, სისტემა ჩავარდნის/დაბლოკვის ნაცვლად აძლევს მწვანე შუქს (`PASS`)!

---

## 3. სამუშაოს სტატუსების გამიჯვნის აუდიტი (Proposed vs Verified vs Approved)

| გადასვლა | სწორად არის თუ არა გამიჯნული კოდში? | კონკრეტული დარღვევა |
| :--- | :---: | :--- |
| **Proposed → Attempted** | **ნაწილობრივ** | `CompanyRun` აფიქსირებს attempt-ებს, მაგრამ Legacy `TaskExecutor` `mock=True`-ით (`useCompanyState.ts:274`) მონიშნავს task-ს `COMPLETED`-ად რეალური აგენტის გაშვების გარეშე |
| **Attempted → Executed** | **კარგად (კოდურ ნაწილში)** | `CODE_PATCH` მოითხოვს რეალურ `git diff`-ს worktree-ში; მაგრამ non-code აგენტებისთვის ნებისმიერი ვალიდური JSON ითვლება `Executed`-ად ფაქტობრივი შემოწმების გარეშე |
| **Executed → Verified** | **დარღვეულია** | `qa_result.py:497-533` აყალბებს `VERIFIED`-ს 14A-ში; `qa_execution.py:550` უშვებს `PASS`-ს 0 ტესტით (`AUDIT-BUG-03`) |
| **Verified → Approved** | **დარღვეულია** | `engineering_pipeline.py:591,870-873` აყალბებს `founder_grant_*` და `founder_repair_*`-ს; `control_center.py:916` ავტომატურად აგენერირებს `founder_approval_id`-ს თუ ბოდიში არ არის |
| **Approved → Released** | **დაცულია (მაგრამ ხარვეზიანი აღდგენით)** | `RealRepoApply` ითხოვს `RealRepoApplyGrant`-ს, ბლოკავს replay-ს (`AUDIT-ADV-02` PASSED), მაგრამ crash recovery (`EXACT_APPROVED_PATCH_PRESENT`, `Project.add_task`, stale lock) გაფუჭებულია |
