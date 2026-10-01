# Jester AI Company — Stage 27-D.1: Visual Explorations
**Document Version:** `v1.0 — Design Exploration`  
**Stage:** `STAGE 27-D.1 — VISUAL EXPLORATION`  
**Status:** Design Proposal & Evaluation  
**Reference Sources:** `docs/EMPLOYEE_EXPERIENCE_AND_PERSONALITY_BIBLE.md`, `docs/VISUAL_DIRECTION.md`, Stage 27-B UX Blueprint  

---

## Executive Overview

This document presents **three distinct visual design directions** for the core **"My Company"** experience of **Jester AI Company**.

All three directions share the exact same underlying company information, data integrity, operational depth, and UX architecture:
- **Same Hierarchy:** `FOUNDER / OWNER` (You) → `CEO` → `EMPLOYEES` (7 specialists).
- **Same Operational Reality:** `PROJECTS` → `TASKS` → `EXECUTIONS` → `QA VERIFICATION` → `APPROVALS` → `RESULTS`.
- **Same 3-Layer Information Model:**
  - **Level 1 (Human):** Living company overview, active colleagues, natural status.
  - **Level 2 (Operational):** Project contexts, task objectives, activity timeline, workplace dialogue.
  - **Level 3 (Evidence):** TaskRuns, stdout/stderr, test commands, exit codes, artifacts, QA reports.
- **Same Color Anchor:** Warm daylight linen (`#FBFBF9`), crisp white surfaces (`#FFFFFF`), deep charcoal ink (`#18191B`), and energetic Carrot Orange (`#F95924`).

What differs across the three directions is the **aesthetic interpretation, spatial metaphor, and emotional timbre**:
* **Direction A: Editorial Studio** — Architectural, refined, spacious, literary, dignified.
* **Direction B: Warm Modern Workplace** — Clean, approachable, functional, modular, high-contrast usability.
* **Direction C: Living Studio** — Ambient, human, energized, relational, dynamic, subtle micro-behaviors.

---

## Architectural Ground Rules & Disclaimers

1. **Hierarchy Invariant:** The Owner sits visually above the CEO; the CEO sits above the specialist workforce. The Owner is never portrayed as a generic employee or sidebar admin profile.
2. **Organization vs. Work:** Organizational hierarchy (who reports to whom) is never conflated with work hierarchy (which projects and tasks are currently in flight).
3. **Specialist Grouping:** Any functional grouping of specialists into pods (e.g. Strategy, Craft, Integrity) is strictly labeled `[DESIGN PROPOSAL]` and does not alter the fact that the CEO directly coordinates the entire workforce.
4. **Selective Presence:** Employees not involved in current work are rendered in quiet, available/idle states. Only genuinely active employees (e.g. Developer building, QA waiting/verifying) receive energized visual focus.
5. **Separation of Personality and Verification Truth:** Casual employee dialogue (e.g. Developer: *"Done."* / QA: *"No."*) is clearly distinguished from objective verification truth (`QA Verdict: FAIL`, `Exit Code: 1`, `Finding: Missing mobile breakpoint`).

---

# DIRECTION A — EDITORIAL STUDIO

### 1. Visual Concept & Metaphor
**"The Architectural Atelier"**  
Direction A models the company after a world-class architectural atelier or high-end industrial design bureau. It is spacious, dignified, and typographic, conveying deep competence, calm authority, and unhurried intellectual rigor. It treats the human owner as the **Founding Principal** who reviews master plans and works-in-progress.

### 2. Main Company Screen Layout
- **Atmosphere:** Expansive, open, gallery-grade whitespace with hairline warm borders (`1px solid rgba(24, 25, 27, 0.08)`).
- **Top Elevation:** A calm, editorial header displaying the studio name and current master status:  
  *"JESTER AI COMPANY — STUDIO REGISTER / 14:32 ATELIER TIME"*  
  Followed by a warm, serif greeting: *"Good afternoon, Founder. 1 active project under construction, 1 task awaiting verification."*
- **Canvas Division:**
  - *Top Half (Full Width):* The **Architectural Company Map**.
  - *Bottom Half (65% / 35% Split):*
    - *Left (65%):* **Active Studio Commissions (Projects & Tasks)** with large, legible editorial numbers (`01`, `02`) and milestone bars.
    - *Right (35%):* **The Studio Log (Activity & Monologue)** in a clean, single-column vertical timeline.

### 3. Company Map (Direction A)
- **Composition:** `[DESIGN PROPOSAL]` A clean, horizontal blueprint diagram.
- **Top:** Founder desk, rendered as an unboxed, dignified title block with a gold hairline accent.
- **Descent:** A single vertical hairline leads directly down to the CEO card.
- **Specialist Spans:** Below the CEO, an elegant horizontal structural datum line connects all 7 specialists laid out in a balanced line or subtle 2-tier architectural grid:
  - *Top Row:* Product, Research, UX (Definition & Architecture).
  - *Bottom Row:* Marketing, Developer, QA (Delivery & Verification).
- **Connector Lines:** Hairline slate rules (`0.75px solid #D5D3CC`). Active collaboration draws a subtle terracotta highlight (`#F95924`).

### 4. Owner & CEO Treatment
- **Owner Treatment:** No enclosed card or box. The Owner is represented as the **Founding Inscription** at the head of the canvas, flanked by discrete studio controls: `[ + Commission New Mission ]` and `[ Archive ]`.
- **CEO Treatment:** An elongated, minimalist horizontal card. Features a quiet portrait silhouette, formal title: *"Chief Executive Officer — Operational Direction"*, and current operational focus: *"Overseeing Project #01: Restaurant Web Platform — Stage 2 Execution."*

### 5. Employee Cards & States
- **Card Aesthetics:** Minimalist rectangular planes with generous internal padding (20px), subtle hairline border, no drop shadows (pure flat elevation).
- **Avatars:** High-contrast editorial line drawings in black ink with a tiny wash of warm sand.
- **Idle State:** 50% opacity text, card background matches base linen canvas (`#FBFBF9`). Footnote reads: *"Available for commission."*
- **Active State:** The active card background turns crisp ivory-white (`#FFFFFF`), framed by a delicate 1px terracotta-orange border (`#F95924`). A tiny editorial numeral marks their active task: `● Active on Task 01.2`.
- **Waiting State (QA):** Sandstone card with an italicized footnote: *"Awaiting code deliverable from Developer."*

### 6. Current Work, Activity & Conversation
- **Current Work Section:** Rendered like an architectural project dossier. Features a large serif title (`"Restaurant Web Platform"`), progress ratio (`2/5 Deliverables Verified`), and prominent task rows.
- **Activity Representation:** Clean typographic log entries:
  - `14:15` — *CEO assigned Task 01.2 (Responsive Navigation) to Developer.*
  - `14:28` — *Developer authored `header.css` and executed build verification.*
- **Conversation Representation:** Minimalist blockquote style with thin vertical indicator bars matching the speaker's role color.
- **Thought Bubbles:** Rare, italicized bracketed side-notes:  
  *Developer [aside]:* `[ "Cache cleared. Checking media query triggers..." ]`

### 7. Deep Information & Level 3 Entry
- Clicking on any task or artifact smoothly expands an **Architectural Sheet (Full Drawer)** from the right (55% viewport width).
- In the drawer:
  - **Specification Tab:** Clean markdown document with serif headers.
  - **QA Verification Tab:** Crisp table with acceptance criteria, exit code badge (`CODE: 0`), and an inspectable monospace terminal excerpt.
  - **Founder Gate:** Subtle bottom bar: `[ Accept Deliverable ]` or `[ Reject with Revision Notes ]`.

### 8. Typography, Color & Motion (Direction A)
- **Typography:** Display serif (`Instrument Serif` / `Newsreader` / `Fraunces`) for titles and Owner greeting; sharp geometric sans (`Plus Jakarta Sans`) for metadata and controls; `JetBrains Mono` for Level 3 code.
- **Color Palette:** Warm linen canvas (`#FBFBF9`), crisp white cards (`#FFFFFF`), deep charcoal ink (`#18191B`), muted sandstone slate (`#787B84`), and surgical, sparing carrot orange (`#F95924`) reserved exclusively for active operational states.
- **Motion Concept:** Architectural, calm, linear fades (180ms ease-out). No bouncy springs; feels like sliding a vellum tracing paper sheet over a drafting table.

---

# DIRECTION B — WARM MODERN WORKPLACE

### 1. Visual Concept & Metaphor
**"The Modern Productivity Headquarters"**  
Direction B takes inspiration from the cleanest, most ergonomic modern productivity platforms (e.g. Linear, Notion, Apple design systems), but imbued with **warmth, daylight, and clear company hierarchy**. It is the most immediately usable, functional, and scannable direction, prioritizing rapid orientation, crisp status visibility, and effortless operational control.

### 2. Main Company Screen Layout
- **Atmosphere:** Clean, modular, comfortable, highly structured. Cards have distinct, soft-curved corners (12px), crisp contrast, and warm micro-shadows.
- **Top Elevation:** A clear, modern status bar:
  - *Left:* Founder identity badge (`"Founder & Owner"`) + Company name (`"Jester AI Company"`).
  - *Center:* Global Company Status pill (`● In Production — 1 Active Project, 1 Blocked Task, 0 Critical Failures`).
  - *Right:* Quick search and primary mission trigger `[ + New Task ]`.
- **Canvas Division:**
  - *Section 1 (Top):* **The Company Overview & Hierarchy Banner** (Compact Company Map).
  - *Section 2 (Middle):* **Active Projects & Tasks Board** (Tabbed / segmented view: Tasks in flight, Under QA, Completed).
  - *Section 3 (Bottom or Right Rail):* **Live Workplace Stream** (Unified activity, collaborative exchanges, artifact drops).

### 3. Company Map (Direction B)
- **Composition:** `[DESIGN PROPOSAL]` A compact, highly organized tree grid designed for instant scannability.
- **Top Center:** Founder card in an elevated warm-white pill with a subtle founder crown icon.
- **Connector:** A clean vertical connector line with downward directional arrowhead leads to the CEO Card.
- **Specialist Grid:** Directly beneath the CEO, 6 specialist cards arranged in a clean 2x3 or 6-column grid with clear role badges and real-time state chips.
- **Visual Connection:** Solid slate connector rules (`1.5px solid #E2E0D8`). Active links light up in bright carrot orange with an animated micro-dot.

### 4. Owner & CEO Treatment
- **Owner Treatment:** Framed in a dedicated, premium pill-card at the very top:
  - Icon: Distinctive Founder monogram.
  - Title: *"You (Company Founder & Owner)"*.
  - Subtitle: *"Ultimate Decision Authority & Mission Sponsor"*.
- **CEO Treatment:** Prominent leadership card:
  - Displays CEO avatar + Name + Status: *"Coordinating Sprint #1: Restaurant Web Platform"*.
  - Real-time action meter: *"Delegated 1 task to Developer; 1 task queued for QA"*.

### 5. Employee Cards & States
- **Card Aesthetics:** Rounded container (radius 12px), white background, crisp 1px neutral border (`#E5E3DC`), subtle soft ambient shadow (`0 2px 8px rgba(0,0,0,0.04)`).
- **Avatars:** Friendly, modern illustrated icons with soft warm backgrounds and role-colored accent rims.
- **State Pills:** Prominent status tags on each card:
  - `IDLE`: Soft gray pill (`#F0EFEA` / text `#7C8089`).
  - `ACTIVE`: Vibrant carrot orange pill with a pulsing status dot (`#F95924` / text `#FFFFFF`).
  - `WAITING`: Soft amber pill (`#FEF3C7` / text `#D97706`).
  - `VERIFYING`: Sage green pill (`#DCFCE7` / text `#166534`).
- **Context Footer:** Explicit task label: *"Working on: Task #12 — Nav Component"*.

### 6. Current Work, Activity & Conversation
- **Current Work Section:** Highly organized task cards showing:
  - Task title + ID (`#TSK-012`).
  - Assigned employee avatar group (CEO → Dev → QA).
  - Multi-segment progress bar: `Planning (Done) → Dev (Active) → QA (Waiting) → Approval (Pending)`.
- **Activity Representation:** Clean, modern timeline with distinct event icons (Assign, Commit, Build, Verify, Pass).
- **Conversation Representation:** Modern chat chips integrated directly into task cards:
  - *Developer:* `"Navigation responsive layout implemented. Unit tests passing."`
  - *QA:* `"Pulling branch for independent verification."`
- **Thought Bubbles:** Discrete tooltip-style micro-chips labeled `[ Dev Thought ]` that appear on hover or as transient status toast.

### 7. Deep Information & Level 3 Entry
- Clicking on a task card opens a **Level 3 Modular Inspector Modal** or right slide-over:
  - Tab 1: **Run History** (Attempt 1, Attempt 2, execution duration, exit codes).
  - Tab 2: **Artifacts Generated** (Downloadable / previewable files: `nav.html`, `styles.css`).
  - Tab 3: **QA Verification Report** (Acceptance checklist, automated test output, confirmation evidence).
  - Tab 4: **Owner Approval** (Prominent green `[ Approve Deliverable ]` vs red `[ Reject & Rerun ]`).

### 8. Typography, Color & Motion (Direction B)
- **Typography:** 100% contemporary humanist sans (`Plus Jakarta Sans` throughout). Bold, legible headings, high x-height for exceptional readability at 12px and 14px.
- **Color Palette:** Warm linen base (`#F8F7F4`), bright white cards (`#FFFFFF`), charcoal text (`#1A1C1E`), energetic carrot orange accent (`#F95924`), supported by clear semantic emerald (`#10B981`) and amber (`#F59E0B`).
- **Motion Concept:** Snappy, spring-based micro-interactions (120ms cubic-bezier transitions on hover, smooth 200ms pill badge state swaps).

---

# DIRECTION C — LIVING STUDIO

### 1. Visual Concept & Metaphor
**"The Living Collaborative Studio"**  
Direction C pushes the **"human company"** experience to its most vivid, engaging, and atmospheric expression—without ever crossing into childish cartoons or video games. It visually evokes a bustling, sun-drenched digital creative studio where you can literally observe the rhythm of work: tasks being handed off, quiet contemplation at idle desks, animated collaboration between Developer and QA, and visible lines of communication.

### 2. Main Company Screen Layout
- **Atmosphere:** Warm, tactile, relational, deeply alive. The canvas feels like a real digital atelier floor with natural zoning, soft ambient lighting, and rich visual textures.
- **Top Elevation:** The **Founder's Balcony**:
  - The Owner sits on an elevated visual tier overlooking the studio floor.
  - Greeting: *"Welcome back, Founder. The team is currently working on Restaurant Website."*
  - Live studio health indicator: *"Studio Pulse: Active & Calm • 2 employees collaborating • 0 blockers"*.
- **Canvas Division:**
  - *Primary Stage (Top 55%):* **The Living Studio Map** (Interactive, relational studio floor showing Owner, CEO, and Employees at their desks with dynamic collaboration threads).
  - *Active Worktable (Bottom 45%):* **The Collaboration Canvas**:
    - *Left:* The Active Task Board with live handoff animations.
    - *Center:* Live Workplace Dialogue Stream (with rare, organic thought bubbles).
    - *Right:* Tangible Deliverables / Artifact Shelf.

### 3. Company Map (Direction C)
- **Composition:** `[DESIGN PROPOSAL]` A spatial, desk-pod layout representing the studio floor:
  - **Upper Tier:** Founder's Private Suite / Desk overlooking the room.
  - **Center:** The CEO's Executive Planning Desk with open blueprints and task allocation pads.
  - **Surrounding Pods:**
    - *Craft Corner:* Developer & UX seated close together with shared design lines.
    - *Strategy Table:* Product, Research, Marketing reviewing requirements.
    - *The Quality Station:* QA seated at an independent, prominent verification desk with test monitors.
- **Collaboration Threads:** Glowing warm carrot-orange threads (`#F95924`) physically travel between desks when collaboration is active (e.g. CEO delegating to Dev; Dev sending build to QA).

### 4. Owner & CEO Treatment
- **Owner Treatment:** Designed as the **Founder's Desk**:
  - Warm timber and cream border with a gold seal: `FOUNDER & CHIEF SPONSOR`.
  - Prominent mission statement displayed: *"Mission: Build and launch the premier online brand for Jester AI."*
- **CEO Treatment:** Designed as the **Studio Director**:
  - Depicted at an open planning table.
  - Status bubble: *"Delegated navigation to Developer. Reviewing QA acceptance criteria."*
  - Shows real-time coordination links pulsing toward active specialists.

### 5. Employee Cards & States
- **Card Aesthetics:** Rich, illustrated desk cards with characterful workspace props (coffee mugs, multiple screens, sketch pads, test diffs).
- **Avatars:** Hand-crafted, expressive editorial portraits capturing individual personality:
  - *Developer:* Leaning forward into terminal, coffee mug nearby, slightly tired but deeply engaged expression.
  - *QA:* Calm, focused, analytical gaze, independent station with green/red verification stamp pads.
  - *CEO:* Upright, organized, calm executive presence.
- **Active State:** The card glows with a soft, breathing warm amber/orange aura (`box-shadow: 0 8px 24px rgba(249, 89, 36, 0.12)`). A mini status ticker displays: `● Developer: Writing CSS media queries (line 124)...`
- **Idle State:** Desk lights are softly dimmed. Employee is depicted reading documentation, sipping tea, or reviewing past runs. Status tag: `○ Idle at Desk — Ready`.
- **Relationship Cues:** When Developer and QA collaborate, a dual-card bracket links them with a shared status: `[ Developer ↔ QA Active Handoff ]`.

### 6. Current Work, Activity & Conversation
- **Current Work Section:** Rendered as an actual **Studio Worktable**:
  - Active task is styled as an open blueprint file folder.
  - Shows real-time collaborator avatars actively pinned to the file.
- **Activity Representation:** Narrative, human-readable timeline entries:
  - *"CEO assigned Homepage Navigation to Developer (12 mins ago)"*
  - *"Developer committed patch: 'fix mobile burger toggle' (3 mins ago)"*
  - *"QA picked up build for independent verification check (Just now)"*
- **Conversation Representation:** Living speech snippets anchored between employee desks:
  - *Developer:* `"I pushed the mobile breakpoint fix. Should be good now."`
  - *QA:* `"Pulling it onto the test container. Let's see."`
- **Thought Bubbles (Rare & Contextual):**
  - Developer desk: `💭 "ქეში გექნება გასაწმენდი... wait, let me check the container log."`
  - Fades away softly after 6 seconds. Never clutters the UI.

### 7. Deep Information & Level 3 Entry
- Clicking on the blueprint folder or artifact shelf opens the **Studio Evidence Vault**:
  - Visually styled as a high-density, warm paper binder or technical drawer.
  - Shows tangible file artifacts with live interactive previews (HTML rendering in a mini iframe).
  - Shows the official **QA Seal of Verification**:
    - If passed: Deep green wax-style digital seal with date, time, and exit code 0.
    - If failed: Calm crimson inspection tag citing the exact defect file and line number.
  - Includes Founder Sign-off Stamp: `[ Founder Seal of Approval ]` / `[ Send Back with Guidance ]`.

### 8. Typography, Color & Motion (Direction C)
- **Typography:** Warm editorial sans (`Plus Jakarta Sans`) paired with expressive serif section headers (`Fraunces` / `Newsreader`) and crisp monospace (`JetBrains Mono`) for logs.
- **Color Palette:** Warmest of all three: Rich Linen floor (`#FAF8F5`), Warm Cream cards (`#FFFFFF` & `#F5F2EB`), Deep Espresso Charcoal text (`#191716`), Vibrant Terracotta Carrot accent (`#F95924`), and soft ambient warm glow overlays.
- **Motion Concept:** The most alive and organic motion:
  - Subtle breathing idle pulse on active desks (4s sinusoidal cycle).
  - Fluid animated light sweep along delegation threads.
  - Smooth page-flip transitions when inspecting artifacts.

---

# COMPREHENSIVE COMPARISON TABLE

| Dimension | Direction A: Editorial Studio | Direction B: Warm Modern Workplace | Direction C: Living Studio |
| :--- | :--- | :--- | :--- |
| **Visual Metaphor** | Architectural Atelier & Bureau | Modern Ergonomic Tech Studio | Living Collaborative Studio Floor |
| **Primary Feeling** | Refined, literary, quiet authority | Crisp, ultra-efficient, friendly | Human, alive, deeply engaging |
| **Personality Level** | Restrained & subtle (Dry, dignified) | Clear & professional (Modern team) | Expressive & visible (Authentic workplace) |
| **Usability & Scannability** | High (Spacious editorial hierarchy) | Maximum (Dense, modular, intuitive) | High (Spatial, intuitive, visual) |
| **Premium Aesthetic Feel** | Maximum (High-end architectural firm) | High (Modern polished SaaS tier) | High (Bespoke crafted atelier) |
| **"Living Company" Impression**| Subtle (Blueprints & silent craft) | Moderate (Status pills & task flows) | Maximum (Desks, threads, live pulse) |
| **Information Depth (L3)** | Architectural sheet drawer | Structured modal / side-inspector | Tangible physical binder / vault |
| **Best Suited For** | Founders who value quiet elegance | Founders who prioritize high-speed work | Founders who want to watch their company live |

---

## Detailed Strengths, Trade-Offs & Hybrid Opportunities

### Direction A: Editorial Studio
- **Superpower:** Extremely sophisticated, high-status, and unhurried. Makes the company feel like a premier design firm rather than software tooling.
- **Potential Risk:** High whitespace may feel too sparse on small screens or for users expecting dense dashboard metrics.
- **Key Element to Borrow:** The dignified, unboxed Founder inscription at the top and the beautiful editorial typography pairing.

### Direction B: Warm Modern Workplace
- **Superpower:** Flawless usability, instantaneous comprehension, and zero learning curve. Every state, task, and run is immediately obvious.
- **Potential Risk:** Can risk feeling slightly conventional or closer to modern productivity tools (like Linear/Notion) if the warm carrot accent and human personality are dialed down too much.
- **Key Element to Borrow:** The ultra-clean task progress bar (`Planning → Dev → QA → Approval`) and the crisp status badge pills.

### Direction C: Living Studio
- **Superpower:** Delivers 100% on the core emotional promise: *"I have an actual company working for me and I love watching them work."* High emotional connection.
- **Potential Risk:** If not carefully restrained, visual desk props could distract from raw data density if the user is in a hurry.
- **Key Element to Borrow:** The spatial Company Map with animated collaboration threads between Developer and QA, and the tangible artifact preview shelf.

---

## `[DESIGN PROPOSAL]` The Recommended Hybrid Synthesis

If the Product Owner wishes to combine the best elements of all three directions without compromise:
1. **The Header & Founder Presence from Direction A:** Dignified, architectural Founder title block that establishes unmistakable ownership.
2. **The Spatial Company Map & Collaboration Threads from Direction C:** An alive, visual studio floor where active collaboration between CEO, Developer, and QA glows with subtle warm carrot threads.
3. **The Worktable & Task Usability from Direction B:** Crisp, modular, high-contrast task cards with unambiguous multi-stage progress bars and instant access to Level 3 verification evidence.

---
*End of Stage 27-D.1 Visual Exploration Specification — Jester AI Company*
