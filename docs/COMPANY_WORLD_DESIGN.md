# Jester AI Company — Stage 27-D.4: The Company World
**Document Version:** `v1.0 — Experience Specification`  
**Stage:** `STAGE 27-D.4 — THE COMPANY WORLD`  
**Status:** Approved Experience Design & Interactive Prototype  
**Target:** The Primary "My Company" Home Experience  
**Reference Source:** `docs/EMPLOYEE_EXPERIENCE_AND_PERSONALITY_BIBLE.md`, `docs/WORKFORCE_VISUAL_SYSTEM.md`  

---

## 1. Executive Summary: The Shift to "The Company World"

We have decisively left behind dashboard thinking (`Cards + Tables + Metrics Panels`). Jester AI Company is not an admin console or a control panel; it is a **living company that the Founder owns and runs**.

When the Founder opens the application, they step into:
> **THE COMPANY WORLD**  
> *"I own this company. These are my people. They are working for me. I can see what they are doing, how they collaborate, what they are producing, and how work flows to completion."*

---

## 2. Core Experience Architecture

### 2.1 The Two Hierarchies (Clear Separation)
A critical insight of this design is visually distinguishing the **Organizational Structure** from the **Work Network**:

```
      ORGANIZATIONAL HIERARCHY                              WORKFLOW NETWORK
┌───────────────────────────────────┐             ┌───────────────────────────────────┐
│         FOUNDER / OWNER           │             │      PROJECT: Restaurant Web      │
│                │                  │             │                 │                 │
│         CEO (Leadership)          │             │       TASK: Build Homepage        │
│                │                  │     VS      │                 │                 │
│      7 PERMANENT EMPLOYEES        │             │      DEVELOPER (Building)         │
│  (Dev, QA, Product, UX, Res, Mkt) │             │                 │                 │
│                                   │             │    ARTIFACT (homepage.html)       │
│   (Permanent company assets)      │             │                 │                 │
│                                   │             │        QA (Verifying)             │
│                                   │             │                 │                 │
│                                   │             │      RESULT (Verified Build)      │
└───────────────────────────────────┘             └───────────────────────────────────┘
```

The Company World visually anchors the **Organization** in the physical studio environment while the **Work Network** flows dynamically between active workstations as tasks are executed.

---

## 3. The Physical Environment: The Modern Studio Atelier

The office environment is rendered in clean, simplified vector styling. It provides authentic spatial context without turning into a video game or a realistic 3D simulator.

### 3.1 Studio Zones & Workstations
1. **The Founder’s Suite (Summit):**
   - Positioned at the top of the canvas.
   - Elegant architectural desk with subtle amber/gold accents, stationery, and a live company pulse indicator:  
     *“Mission Sponsor & Ultimate Authority • 1 Project Active • 2 Team Members in Flight”*
   - Includes the primary vision command: `[ + Direct New Mission ]`.
2. **The CEO Strategy Desk (Center-Upper):**
   - Executive planning table directly connected to the Founder.
   - Features open project blueprints, espresso cup, tablet, and active delegation conduits flowing to the team.
   - Real-time status: *“Coordinating Sprint #1: Delegated Homepage to Developer & QA.”*
3. **The Craft Station (Active Workstation — Lower Left):**
   - Developer’s desk: Dual monitors showing syntax lines, mechanical keyboard, dark ceramic coffee mug, and sticky notes.
   - Developer avatar is **active with a glowing Carrot Orange halo** (`#F95924`).
   - Contextual thought bubble: `💭 "One more breakpoint for 320px..."`
4. **The Quality Station (Active Workstation — Lower Right):**
   - QA’s independent testing bench: Test runner console, verification checklist clipboard, and diff analyzer.
   - QA avatar is **active with a Forest Green / Amber halo** (`#168050`).
   - Contextual thought bubble: `💭 "Let's see what broke this time."`
5. **The Strategy & Scoping Station (Quiet / Available — Left Wing):**
   - Product & Research desks: Moleskine notebooks, research documents, whiteboard with wireframe post-its, potted monstera plant.
   - Avatars are calm, sitting comfortably, ready for the next sprint.
6. **The Creative & Positioning Station (Quiet / Available — Right Wing):**
   - UX & Marketing desks: Swatch fans, design tablet with stylus, microphone, minimalist lighting.
   - Avatars are calm and observant.

---

## 4. The Characters: Distinctive Vector Portraits

Avatars are **strictly head-and-shoulders vector portraits**. No full-body cartoon people, no chibi, no kawaii, no anime, and no generic stock packs.

```
┌──────────────┬───────────────────────────────┬───────────────────────────────┬──────────────────────────────┐
│ Character    │ Physical Persona              │ Styling & Distinctive Props   │ Personality Cue & Speech     │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Founder (You)│ Distinguished modern founder, │ Tailored charcoal overshirt,  │ "Build a responsive booking  │
│              │ composed visionary authority  │ subtle amber founder lapel    │ experience for our clients." │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ CEO          │ Mid-40s male, neat dark hair  │ Navy blazer over white tee,   │ "Let's start with homepage.  │
│              │ with silver temple streaks    │ espresso cup, Moleskine pad   │ Focus on mobile first."      │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Developer    │ Late 20s male, slightly       │ Charcoal hoodie, headset      │ "Got it. Working on the      │
│              │ tousled dark hair, tired eyes │ around neck, matte mug        │ responsive structure."       │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ QA           │ ~35 female, sharp dark bob,   │ Deep teal blazer, light shirt,│ "I'll verify mobile once the │
│              │ independent skeptical gaze    │ verification clipboard        │ first version is ready."     │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Product      │ Early 30s female, tortoise    │ Dark moss mockneck, wireframe │ "Requirements locked. Scope  │
│              │ acetate glasses, alert gaze   │ notebook, sticky notes        │ boundaries defined."         │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Research     │ Mid-30s, textured hair,       │ Warm ochre knit sweater,      │ "Benchmark analysis complete │
│              │ round thin wireframe glasses  │ dual documentation displays   │ across 5 competitor flows."  │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ UX           │ Late 20s female, sleek bob,   │ Terracotta linen top, gold    │ "Eliminating navigation      │
│              │ discerning artistic gaze      │ hoop earring, design stylus   │ friction on touch devices."  │
├──────────────┼───────────────────────────────┼───────────────────────────────┼──────────────────────────────┤
│ Marketing    │ Early 30s male, swept hair,   │ Crisp white collared shirt,   │ "Positioning clean value     │
│              │ confident forward smile       │ desk podcast microphone       │ without corporate jargon."   │
└──────────────┴───────────────────────────────┴───────────────────────────────┴──────────────────────────────┘
```

---

## 5. The Live Work Network & Conduits

Connecting the people is the **Infographic Workflow Conduit Layer**:

1. **CEO Delegation Conduit:**  
   An animated orange hairline routes from the CEO Strategy Table $\rightarrow$ The Active Task Card (*"Build Responsive Homepage"*).
2. **Task-to-Developer Conduit:**  
   Routes directly into Developer’s keyboard. Pulse packets indicate active authoring.
3. **Artifact Materialization:**  
   As Developer completes code, a floating artifact node materializes between Developer and QA:  
   `[ 💻 homepage.html & nav.css — Patch #1 ]`.
4. **Handoff to QA Conduit:**  
   Carrot-orange path carries the artifact directly to QA’s testing bench.
5. **Verification & Result Gate:**  
   QA runs independent verification. Upon passing, a crisp Forest Green conduit routes into the **Verified Result Node** presented to the Founder for final acceptance.

---

## 6. Contextual Conversation & Thought Bubbles

Workplace communication is integrated directly into the environment:
- **Speech Chips:** Compact dialogue bubbles anchored between workstations. They display how colleagues actually communicate during execution:
  - CEO: *"Let's start with the homepage. Focus on mobile first."*
  - Developer: *"Got it. Working on the responsive structure."*
  - QA: *"I'll verify mobile once the first version is ready."*
- **Rare Thought Bubbles:** Contextual, transient internal monologue:
  - Developer: `💭 "One more breakpoint for 320px..."`
  - QA: `💭 "Let's see what broke this time."`
  - They fade naturally and never clutter the screen.

---

## 7. Deep Information (Level 3 Access)

The Company World is **Level 1 (The Human Experience)**. Deeper operational facts remain instantly accessible:
- Clicking any active task, artifact, or QA badge smoothly glides open the **Level 3 Evidence Vault**:
  - Exact execution duration (`0.64s`).
  - Terminal exit codes (`Exit Code: 0 (SUCCESS)`).
  - Raw stdout/stderr test runner logs.
  - Code diff viewer (`header.html` patch).
  - Founder Acceptance Gate: `[ ✓ Approve & Merge Deliverable ]` and `[ Request Changes ]`.

---

## 8. Interactive Prototype Summary

The interactive exploration is implemented in:  
👉 **[docs/explorations/company_world.html](file:///c:/Users/fiord/.gemini/antigravity-ide/scratch/JesterAICompany/docs/explorations/company_world.html)**

### Key Interactive Touchpoints:
1. **Interactive Office Floor Plan:** Hover over any desk or workstation to reveal subtle workstation details (monitors, coffee, notebooks).
2. **Employee Selection & Dossier:** Click any employee avatar to open their dedicated Employee Dossier (personality, role, active focus, colleague banter).
3. **Task & Deliverable Inspection:** Click the floating Task Card or Deliverable Node to open the Level 3 Evidence Vault.
4. **Interactive QA Verification Simulation:** Trigger the live remediation cycle (QA Defect $\rightarrow$ Return Conduit $\rightarrow$ Dev Fix $\rightarrow$ Verified Pass).

---
*End of The Company World Design Specification — Jester AI Company*
