# Jester AI Company — Visual Design Direction
**Document Version:** `v1.0 — Design Foundation`  
**Stage:** `STAGE 27-C — VISUAL DIRECTION`  
**Status:** Approved Reference Specification  
**Target:** Owner / Founder Control Experience  

---

## 1. The Core Visual Concept: "The Living Studio"

### 1.1 The Core Metaphor
Jester AI Company is not an admin console, not a developer IDE, not a dark terminal, and not a chatbot conversation. It is a **Living Digital Studio / Contemporary Architecture Atelier**.

When the Founder/Owner opens the interface, the immediate emotional impression must be:
> **"I have an actual company working for me. My team is right here, competent, focused, and alive."**

It evokes the feeling of walking into a sunlit, high-ceilinged modern design and engineering studio:
- Warm light streaming onto natural timber and matte stone desks.
- Soft, crisp paper, notebooks, and precision pens alongside high-end displays.
- A team of experienced professionals who know their craft, moving with calm, purposeful efficiency.
- A distinctive **warm carrot-orange** thread connecting goals, people, and work.

### 1.2 Why This Fits Jester AI Company
1. **Reusability & Permanence:** The employees are not disposable ephemeral scripts; they are company assets who stay with the company across projects. A physical, human-feeling studio visual metaphor reinforces their permanent role.
2. **De-escalation of AI Anxiety:** Sterile, glowing black-and-neon "cyberpunk" interfaces make AI feel alien, opaque, unpredictable, and intimidating. A warm, daylight, tactile design language makes autonomous work transparent, understandable, and deeply reassuring.
3. **Hierarchy Clarity:** The physical studio space visually separates the **Owner** (the founder who walks into the studio to review outcomes and set goals), the **CEO** (the studio director orchestrating the floor), and the **Specialist Employees** (craftspeople at their designated work areas).
4. **Subtle Personality vs. Cartoonish Gimmicks:** In a real top-tier studio, employees don't dress up in clown suits or spout catchphrases; they have authentic personal style, subtle workplace banter, mutual professional respect, and quiet pride in their deliverables.

---

## 2. Color Direction & Palette Architecture

The color system is anchored in **warm daylight neutrals**, accented by **energetic carrot-orange**, with restrained, dignified semantic states.

```
┌────────────────────────────────────────────────────────────────────────┐
│                              PALETTE MAP                               │
│                                                                        │
│   Canvas: Warm Linen        Surface: Studio Card     Accent: Carrot    │
│   #FBFBF9                   #FFFFFF / #F6F5F2        #F95924 (Primary) │
│                                                                        │
│   Text Main: Charcoal       Text Secondary: Slate    Muted: Sandstone  │
│   #18191B                   #5A5D64                  #93969F           │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Primary & Accent Colors
- **Carrot Orange (Primary Active Brand Accent):**  
  `[DESIGN PROPOSAL]` **`#F95924`** (HSL: `15°, 95%, 56%`)  
  *Alternative subtle variant:* `#F06535`  
  *Why this value:* It is a vibrant, natural terracotta-carrot orange with enough warmth and depth to avoid looking like a construction hazard or a generic flat orange. It feels organic, creative, and active.
- **Carrot Tint / Glow Wash:**  
  `rgba(249, 89, 36, 0.08)` to `rgba(249, 89, 36, 0.14)` — Used for active employee focus halos, connection line pulses, and active task badges.
- **Deep Terracotta (Interactive Hover / Focus):**  
  `#D94313` — Used for button hover states, active tab underscores, and highlighted links.

### 2.2 Surface & Canvas Neutrals (The Daylight System)
- **Canvas Base (Workspace Floor):**  
  `#FBFBF9` (Linen White) — A warm, non-glare, natural off-white with a tiny touch of amber/yellow warmth. Never pure `#FFFFFF` across the whole screen.
- **Surface Elevation 1 (Cards, Studio Pods, Side Shelves):**  
  `#FFFFFF` (Pure White) — Placed over `#FBFBF9` with subtle warm borders, creating soft, natural depth.
- **Surface Elevation 2 (Elevated Drawers, Modals, Detail Panels):**  
  `#FFFFFF` with soft ambient shadow.
- **Surface Inset (Code viewer, Evidence drawer, Inset Logs):**  
  `#F4F3EF` (Warm Sand Inset) — For technical details, code excerpts, and artifact readouts.

### 2.3 Typography & Ink Tones
- **Ink Primary (Headings, Key Titles, Owner Name):**  
  `#18191B` (Soft Obsidian / Deep Charcoal) — Clean, high contrast, non-fatiguing.
- **Ink Secondary (Body descriptions, roles, timestamps):**  
  `#5A5D64` (Warm Studio Slate) — Crisp readability without visual heaviness.
- **Ink Muted (Borders, subtle labels, empty states):**  
  `#93969F` (Sandstone Gray).

### 2.4 Restrained Semantic Status Tones
Semantic colors must never scream or look like arcade video game banners. They are muted, elegant, and definitive:
- **Success / Passed / Completed:**  
  `#1B8755` (Forest Sage Green) with wash `rgba(27, 135, 85, 0.08)`
- **Warning / Reviewing / Attention Needed:**  
  `#D97706` (Amber Ochre) with wash `rgba(217, 119, 6, 0.08)`
- **Failed / Blocker / Verification Failed:**  
  `#D9383A` (Muted Studio Crimson) with wash `rgba(217, 56, 58, 0.08)`
- **Idle / Quiet / Neutral:**  
  `#7C8089` (Neutral Gray) with wash `rgba(124, 128, 137, 0.08)`

---

## 3. Typography Direction

The typography must feel **literary, architectural, and contemporary**. Avoid generic "AI SaaS" geometric sans that look like crypto dashboards.

### 3.1 Primary Font Family
- **Font Stack:**  
  `Plus Jakarta Sans`, `Inter`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `sans-serif`  
  *Alternative Editorial Proposition:* `[DESIGN PROPOSAL]` Combining a warm humanist sans (`Plus Jakarta Sans`) for interface controls with an elegant contemporary editorial serif (`Newsreader` or `Fraunces` or `Instrument Serif`) exclusively for the **Owner greeting and Company Name** (`"Jester AI Company"`).

### 3.2 Monospace Family (Technical & Artifact Layer)
- **Font Stack:**  
  `JetBrains Mono`, `SF Mono`, `Menlo`, `Consolas`, `monospace`  
  *Character:* Reserved strictly for Level 3 evidence: file paths, commit hashes, exit codes, and diff previews.

### 3.3 Type Scale & Rhythm
- **Display / Studio Greeting:** `28px / 34px` — Medium / Semi-bold (Soft charcoal)
- **Section Headers (Company Map, Active Projects):** `18px / 24px` — Semi-bold
- **Card Headings (Employee Name, Task Title):** `15px / 20px` — Semi-bold
- **Body Regular (Activity logs, descriptions):** `13.5px / 19px` — Regular
- **Micro Badges & Metadata:** `11.5px / 16px` — Medium, tracking `+0.02em`

---

## 4. Layout Philosophy: "Simple on the Surface, Deep Underneath"

The user interface uses a **3-Layer Depth Model**. The user never gets overwhelmed by technical plumbing on first glance, but every single fact, log, artifact, and verification result is reachable within two deliberate clicks.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        3-LAYER INFORMATION DEPTH                       │
├────────────────────────────────────────────────────────────────────────┤
│ LEVEL 1: HUMAN / LIVING EXPERIENCE                                     │
│ "What is my company doing right now?"                                  │
│ • Company Map & Employee presence                                      │
│ • Natural status: "Developer is implementing homepage navigation"      │
│ • Founder summary & active project overview                            │
├────────────────────────────────────────────────────────────────────────┤
│ LEVEL 2: OPERATIONAL WORK DETAIL                                       │
│ "How is this task progressing?"                                        │
│ • Project context, task objectives, assigned roles                     │
│ • Chronological workplace activity stream & collaboration dialogue     │
│ • Current run attempt, task status pills                               │
├────────────────────────────────────────────────────────────────────────┤
│ LEVEL 3: EVIDENCE & TECHNICAL INTEGRITY                                │
│ "Show me the proof that it actually works."                           │
│ • Full TaskRun execution manifest, start/completion timestamps         │
│ • Independent QA verification report, command exit code, stdout/stderr │
│ • Concrete artifacts viewer (markdown, specs, code patches, JSON)      │
│ • Human approval gate actions ("Approve" / "Request Changes")          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Company Map: The Organizational Masterpiece

The **Company Map** is the signature visual anchor of Jester AI Company. It is situated prominently on the primary overview screen, visually illustrating the relationship between the Founder, the CEO, and the specialist workforce.

### 5.1 The Visual Layout Approach
Instead of a rigid, corporate org-chart box tree, the Company Map is composed as an **Atelier Blueprint**:

```
                              ┌────────────────┐
                              │      YOU       │
                              │ FOUNDER / OWNER│  (Dignified top desk)
                              └───────┬────────┘
                                      │  (Golden/Orange thread of vision)
                                      ▼
                              ┌────────────────┐
                              │      CEO       │
                              │ Operational Dir│  (Central orchestrator)
                              └───────┬────────┘
                                      │
             ┌────────────────────────┼────────────────────────┐
             │                        │                        │
      [ STRATEGY POD ]         [ CRAFT POD ]            [ INTEGRITY POD ]
      ┌──────────────┐         ┌─────────────┐          ┌─────────────┐
      │  • Product   │         │ • Developer │          │    • QA     │
      │  • Research  │         │ • UX        │          │ (Verifier)  │
      │  • Marketing │         └─────────────┘          └─────────────┘
      └──────────────┘
```

`[DESIGN PROPOSAL]` **Functional Grouping ("The Three Pods"):**
To prevent a wide horizontal clutter of 7 identical cards, group the specialists into logical workplace clusters connected to the CEO:
1. **Strategy & Definition Pod:** Product, Research, Marketing
2. **Implementation & Experience Pod:** Developer, UX
3. **Quality & Verification Pod:** QA (standing as the independent quality gate)

### 5.2 Dynamic State of the Map
- When an employee is **IDLE / AVAILABLE**, their pod card is softly rendered in warm neutral tones (`#F6F5F2` surface, muted slate text).
- When a task is **ASSIGNED & ACTIVE**, a thin, elegant warm carrot-orange hairline animates from the CEO card into the active employee's card.
- The active employee's card gently lifts with a warm white surface, crisp charcoal title, and a subtle glowing carrot status dot (`● Working on Task #12`).
- When work transitions to **QA VERIFICATION**, the orange thread flows from Developer directly into QA's desk, signaling handoff.

---

## 6. Founder/Owner & Leadership Visual Treatments

### 6.1 The Founder / Owner (YOU)
The Owner is **not** an account dropdown in the corner of a navbar, nor a card in the employee grid. The Owner sits visibly at the summit of the company.

- **Visual Treatment:**  
  A distinguished top banner / studio headpiece:
  - Label: `COMPANY FOUNDER & OWNER` in tracking-spaced uppercase sandstone typography.
  - Presence: Warm greeting line: *"Good morning. Your company is currently active on 2 projects with 1 task awaiting verification."*
  - Control Touchpoints: Clean, minimalist action buttons: `[ + Direct New Mission ]` and `[ Company Settings ]`.
  - Visual Distinction: Framed in an elegant warm border with a discreet gold/terracotta founder crest.

### 6.2 The CEO Agent (Operational Leader)
The CEO is the operational bridge between the Owner's will and specialist execution.
- **Visual Treatment:**
  - Card style: Sits directly below the Owner, wider and more substantial than individual employee cards.
  - Avatar: Depicted as an experienced, composed operational director (approximately 42, understated navy blazer, calm posture, clean desk).
  - Status display: Shows what the CEO is currently orchestrating:  
    `"Orchestrating Task #4: 'Homepage Navigation' -> Delegated to Developer & QA"`
  - Quick action: `[ View CEO Execution Plan ]` which smoothly unfolds Level 2 operational details.

---

## 7. Employee Visual Language & Avatars

### 7.1 Avatar Art Direction
`[DESIGN PROPOSAL]` **Sophisticated Human Illustration / Contemporary Line & Wash:**
- Avoid 3D Pixar-style cartoon mascots (too childish).
- Avoid generic stock photos of corporate models (cold and fake).
- Avoid robotic cyberpunk wireframes (antithetical to the living company).
- **Direction:** Clean, modern, editorial line-art with soft watercolor/gouache tone fills. Each employee has an unmistakable, human silhouette, distinctive posture, and authentic workspace accessories:
  - **CEO:** Upright, thoughtful, navy knit or blazer, espresso cup, clean Moleskine.
  - **Product:** Expressive, energetic, glasses on head, colorful sticky notes, tablet with wireframes.
  - **Research:** Contemplative, cable-knit sweater, dual displays with dense documentation, mug of tea.
  - **UX:** Stylus in hand, aesthetic warm daylight, design swatches, minimal clean layout.
  - **Marketing:** Confident posture, contemporary linen shirt, audio podcast mic on desk, sharp notebook.
  - **Developer:** Slightly tired but focused, dark graphic tee or hoodie, mechanical keyboard, large ceramic coffee mug.
  - **QA:** Sharp, composed, observant, approximately 35, professional casual, dual screens showing terminal & diffs, pen ready for verification mark.

### 7.2 Employee Card Components
Each employee card features:
1. **Header:** Illustrated avatar thumbnail + Employee Title (`"Developer Agent"`) + Role handle (`"@developer"`).
2. **Current State Indicator:**  
   - `[ IDLE ]` (Sandstone pill)
   - `[ ASSIGNED ]` (Soft amber pill)
   - `[ ACTIVE: Building ]` (Carrot orange pill with micro pulse)
   - `[ REVIEWING ]` (Blue/slate pill)
3. **Domain Responsibility Snippet:** One concise line highlighting their craft.
4. **Current Context Footnote:** Displays the exact task and project they are currently touching (or *"Available for next sprint"* when idle).

---

## 8. State Visual Language: The Living Rhythms

The company transitions through real operational states. The UI reflects these transitions with dignity, calm, and clarity:

| State | Visual Treatment | Employee Motion / Cue | Color Tone |
| :--- | :--- | :--- | :--- |
| **Idle / Available** | Crisp, calm, daylight white. Clean desks. | Employees shown in relaxed posture, reading, observing. | Warm Linen `#FBFBF9` & Sandstone |
| **New Mission Ingestion** | Carrot highlight on Owner -> CEO line. | CEO desk illuminates with glowing brief. | Carrot Orange `#F95924` |
| **Planning & Scoping** | Subtle connector lines active between CEO & Product. | Product card active; checklist items previewing. | Warm Amber `#D97706` |
| **Active Building** | Developer card elevated with subtle warm glow. | Typing / active code indicator; file count ticker. | Active Carrot `#F95924` |
| **Handoff to Verification** | Animated orange pulse travels from Developer to QA. | Developer enters `[ Waiting on QA ]`; QA becomes active. | Transition Orange -> Sage |
| **QA Verification Active** | QA desk elevated; test checklist ticking. | QA reviewing artifacts and verification command logs. | Forest Sage `#1B8755` |
| **Verification Failed** | **Calm, respectful remediation state.** No flashing red sirens. | QA card notes: *"Verification did not pass: 1 defect found"*. Developer card activates: *"Investigating line 42"*. | Soft Studio Crimson `#D9383A` |
| **Passed & Verified** | Soft, satisfying green seal appears on task card. | QA notes: *"All criteria verified"*. CEO marks task complete. | Forest Sage `#1B8755` |
| **Needs Owner Approval** | Clean floating banner at Owner level: *"Ready for Founder Sign-off"*. | CEO waiting with pen; two clean buttons: `[ Approve ]` / `[ Review ]`. | Terracotta / Gold `#D97706` |

---

## 9. Live-Work Visual Language: Activity, Dialogue & Thoughts

### 9.1 Activity Stream (Level 1/2)
The activity stream is not a chaotic chat feed; it is an **Architectural Work Log**:
- Clean, vertical timeline on the right side or beneath active projects.
- Each entry has an authentic timestamp, employee avatar badge, and clear plain-English summary:  
  `14:22 — CEO assigned "Navigation Header" to Developer (Project: Jester AI Company)`  
  `14:25 — Developer committed 2 files; executed local build (Exit Code: 0)`  
  `14:26 — QA initiated independent verification check...`

### 9.2 Workplace Conversation Chips
When employees converse during work, it appears as **compact, understated dialogue chips** directly tied to the task card:
```
┌────────────────────────────────────────────────────────┐
│ 💬 WORKPLACE DIALOGUE                                  │
│                                                        │
│ [CEO]: "Navigation first. Mobile break at 768px."      │
│ [Developer]: "On it. Keeping it strictly Vanilla CSS." │
│ [QA]: "I'll test the touch targets once pushed."       │
└────────────────────────────────────────────────────────┘
```
- No chat bubbles with giant avatars. Just tight, elegant typographic cards with subtle left borders matching the employee's role color.

### 9.3 Thought Bubbles (Rare & Contextual)
`[CRITICAL PRINCIPLE]` Internal thoughts must be **rare, transient, and situational**.
- They only appear when an employee hits a notable milestone, friction point, or classic workplace realization.
- **Appearance:** A soft, semi-transparent cloud pill with a tiny tail:  
  *Developer while reviewing QA defect:* `💭 "ქეში გექნება გასაწმენდი... wait, let me check the container log."`  
  *QA while inspecting edge case:* `💭 "Passed on desktop, but let's test a 320px viewport."`
- They automatically fade after 6 seconds or can be toggled off entirely.

---

## 10. Deep-Information Visual Language: Level 3 Evidence

When the Owner clicks into any task, run, or artifact, the interface slides open a **Precision Evidence Drawer** without losing the visual context of the company studio.

### 10.1 Artifact Presentation
Artifacts are tangible work outputs. They are treated with the dignity of real design and engineering deliverables:
- **Specification Artifact (`product_spec.md`):** Rendered in clean editorial markdown with formatted requirement tables and explicit IN/OUT scope boxes.
- **Code Patch Artifact (`dev_summary.md`, patch files):** Displayed in a warm sandstone inset code frame (`#F4F3EF`), syntax-highlighted, with clear `+` / `-` diff indicators and files-touched badges.
- **Visual Artifacts (Mockups, HTML Previews):** Interactive sandboxed iframe preview with a viewport switcher (Desktop / Tablet / Mobile).

### 10.2 Independent QA Verification Card
Visually separates **employee conversational claims** from **objective system truth**:
```
┌────────────────────────────────────────────────────────────────────────┐
│ 🛡️ INDEPENDENT QA VERIFICATION REPORT                                  │
├────────────────────────────────────────────────────────────────────────┤
│ Status:  [ ✓ VERIFIED PASS ]        Verifier:  QA Agent (@qa)          │
│ Command: python tools/verify_company.py                                │
│ Exit:    0 (Success)                Duration:  0.42s                   │
├────────────────────────────────────────────────────────────────────────┤
│ ACCEPTANCE CRITERIA RESULTS:                                           │
│  [✓] Integrity check passes without syntax errors                     │
│  [✓] Zero external network calls executed                              │
│  [✓] Company boundaries preserved                                      │
├────────────────────────────────────────────────────────────────────────┤
│ EVIDENCE LOGS:  [ > Toggle Raw stdout/stderr (14 lines) ]              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Surfaces, Borders, Shadows & Spacing (Design Tokens)

### 11.1 Border System
- **Subtle Surface Border:** `1px solid rgba(24, 25, 27, 0.07)` — Crisp, tactile, light gray-slate outline.
- **Active / Focused Border:** `1.5px solid #F95924` (Carrot Orange).
- **Subtle Pod Divider:** `1px dashed rgba(24, 25, 27, 0.1)`.

### 11.2 Shadow System (Warm Studio Ambient)
Harsh drop shadows are banned. Shadows are warm, widely diffused, and soft:
- **Card Ambient (Resting):** `0 2px 10px -2px rgba(24, 25, 27, 0.04), 0 1px 3px rgba(24, 25, 27, 0.02)`
- **Card Hover / Active Lift:** `0 12px 28px -6px rgba(249, 89, 36, 0.08), 0 4px 12px -2px rgba(24, 25, 27, 0.04)`
- **Modal / Elevated Drawer:** `0 24px 48px -12px rgba(24, 25, 27, 0.12), 0 8px 16px -4px rgba(24, 25, 27, 0.04)`

### 11.3 Radius & Spacing Grid
- **Rhythm:** Based on an 8pt geometric grid (`4px`, `8px`, `12px`, `16px`, `24px`, `32px`, `48px`).
- **Border Radius:**
  - Micro tags / pills: `6px`
  - Small buttons / controls: `8px`
  - Employee cards / task panels: `14px`
  - Studio containers / primary drawers: `20px`

---

## 12. Motion Principles: The Rhythm of Real Work

Motion in Jester AI Company is **purposeful, physical, and restrained**. It communicates real state transitions rather than showing off CSS animations.

1. **The Pulse of Life (Idle Breathing):**  
   Active employee cards have a subtle, slow 4-second ambient opacity shift (`0.96` to `1.0`) on their active badge. No violent bouncing or shaking.
2. **The Flow of Delegation:**  
   When the CEO delegates a task, a gentle terracotta-orange light sweep (`300ms`, `cubic-bezier(0.16, 1, 0.3, 1)`) travels along the connector line into the target specialist's card.
3. **The Drawer Glide (Level 3 Deep Dive):**  
   Clicking a task or artifact glides the evidence drawer in from the right edge with a weighted, physical feel (`240ms`, spring ease). The background studio softly dims to 80% warm opacity.
4. **Zero Confetti / Zero Gamification:**  
   When a task completes, there is no confetti shower, no arcade fanfare, and no fireworks. A crisp green verification seal settles into place with a subtle 150ms check animation. It feels like an architect stamping an approved blueprint.

---

## 13. Screen Walkthroughs: Visual Descriptions

### Screen 1: The Studio Master Dashboard (Resting / Normal Day)
- **Top:** Warm linen background. At the very top, the Founder crest and greeting: *"Jester AI Company — Studio Overview"*. Next to it, high-level metrics cards (7 Employees Active • 1 Project Registered • 5 Runs Recorded • All Checks Passing).
- **Upper Canvas (Company Map):** Clean hierarchy. Founder at top; connector line descending to CEO Agent. Below CEO, the Three Pods: Strategy, Craft, Integrity. Developer card shows a soft orange outline with badge: `● In Progress: Homepage Navigation`. QA card shows: `Waiting for artifact`.
- **Lower Canvas (The Worktable):** Divided into two columns:
  - *Left (60%):* Active Tasks and Project cards. Shows Task #4 with a visual progress bar (Product Scoping [Done] -> Developer Implementation [Active] -> QA Verification [Queued]).
  - *Right (40%):* Live Activity Feed with recent workplace moments and dialogue chips.

### Screen 2: The Task Deep Dive & Artifact Inspection
- The user clicks on Task #4 (`"Implement Homepage Navigation"`).
- The right half of the screen smoothly expands into the **Evidence Workspace**:
  - Top tab switcher: `[ Overview ]` `[ Specification ]` `[ Developer Patch ]` `[ QA Verification ]`.
  - Under `QA Verification`, the user sees the real test command, the exit code 0, and the verbatim test output.
  - At the bottom, the human approval gate card:  
    `"Task #4 is verified by QA and ready for Founder Acceptance"` with two primary buttons: `[ Approve & Merge ]` and `[ Request Iteration ]`.

---

## 14. Explicit DOs and DON'Ts

| Category | MANDATED (DO) | PROHIBITED (DON'T) |
| :--- | :--- | :--- |
| **Color Scheme** | Warm daylight linen, crisp white surfaces, soft charcoal text, carrot-orange accent. | Dark theme by default, neon purple, cyan cyberpunk glows, cold blue admin consoles. |
| **Tone** | Professional, competent, authentic, subtle dry wit, calm. | Slapstick jokes, meme overload, AI chatbot roleplay, condescending banter. |
| **Hierarchy** | Founder/Owner sitting clearly above CEO; CEO sitting above workforce. | Founder looking like an admin profile icon in a bottom sidebar. |
| **Employee Activity** | Only currently active employees illuminated; idle employees quiet and calm. | All 7 employees chattering simultaneously or pretending to work on tasks they aren't part of. |
| **QA Representation** | Serious, independent verification seal backed by real exit codes and logs. | Vague green checks with no inspectable proof or treating QA as a funny obstacle. |
| **Depth** | Three clean layers (Human -> Operational -> Technical Evidence). | Dumping raw terminal traces on the home screen or hiding technical details behind 5 menus. |
| **Motion** | Gentle, purposeful 150–300ms transitions, subtle connector pulses. | Confetti, bouncy cartoon animations, flashing error screens, arcade sounds. |

---

## 15. Next Steps & Handoff

This document stands as the definitive visual foundation for **Stage 27-C**.  
- In **Stage 27-D**, the HTML/CSS templates in the Control Center will be systematically refactored to manifest this daylight studio palette, typography scale, Company Map layout, and 3-layer information depth without modifying any backend logic or `CompanyService` contracts.

---
*End of Visual Design Direction Specification — Jester AI Company*
