# JesterAICompany

Repository for the JesterAICompany project.

## 1. Company Identity

- **Name:** Jester AI Company
- **Purpose:** A team of AI employees that collaborate to perform real work and report results to the human owner.

---

## 2. Core Operating Principles

1. **Practical over complex:** Favor simple, workable solutions over convoluted architectures.
2. **Small change → run → test → verify:** Execute all work in small, measurable increments with immediate verification.
3. **Do not move to the next stage until the current stage works:** Strict stage gating; never skip ahead.
4. **Do not build functionality before it is needed:** Zero speculative design or premature optimization (YAGNI).
5. **Evidence before opinion where applicable:** Rely on verified test results, inspection data, and factual evidence over assumptions.
6. **Human remains the final decision maker:** The human owner retains ultimate authority and approves all major milestones and strategic directions.
7. **DONE means actually executed and verified:** A task is only complete when it has been executed, tested, and validated in practice.

---

## 3. Initial Company Hierarchy

```
       YOU (Human Owner / Final Decision Maker)
                          ↓
                      CEO Agent
                          ↓
                Specialist Employees
```

- **YOU:** The human owner providing vision, goals, priorities, and final decisions.
- **CEO Agent:** The central coordinator translating human goals into executable tasks, delegating to specialists, and reporting verified progress.
- **Specialist Employees:** Domain-focused AI roles executing specific tasks under the CEO's coordination.

---

## 4. Initial Employee Roles (High-Level Definitions)

*Note: These roles are organizational definitions only. No agents are implemented at this stage.*

- **CEO:** Coordinates company operations, breaks down high-level objectives into actionable plans, delegates work to specialist employees, tracks status, and reports verified results to the human owner.
- **Product:** Defines requirements, scopes features, prioritizes user value, maintains product direction, and ensures work aligns with business objectives.
- **Research:** Conducts deep-dive investigations into technologies, tools, algorithms, and market data, delivering findings backed by concrete evidence.
- **UX:** Designs user flows, interaction patterns, interface structures, and usability guidelines to ensure seamless user experiences.
- **Marketing:** Crafts product messaging, value propositions, documentation clarity, external communications, and positioning strategy.
- **Developer:** Writes, refactors, and tests clean, maintainable, and robust code adhering to project standards and operating principles.
- **QA:** Designs test cases, verifies acceptance criteria, executes rigorous testing against real outputs, and guarantees that "DONE" criteria are genuinely met.

---

## 5. Company Boundaries

To maintain clean separation of concerns and operational safety, boundaries are strictly defined:

- **Jester:** The actual underlying software product.
- **JesterAICompany:** The AI employee and company infrastructure (this repository). Manages organizational structure, agent definitions, workflows, and collaboration.
- **JesterBridge:** A separate repository that serves as the bridge/interface between AI systems and product environments. It is strictly out of scope and **NOT** touched during current phases.

---

## 6. Build Phases

The company is constructed through a staged, verified approach:

- **STEP 1 = New Project** *(Verified)*: Verify clean environment, repository setup, and baseline files.
- **STEP 2 = Company Foundation** *(Current)*: Establish identity, principles, hierarchy, high-level role definitions, boundaries, and backlog.
- **STEP 3 = CEO Agent** *(Next)*: Create the initial CEO Agent following the foundation guidelines.
- **STEP 4 = CEO Test**: Run and verify the CEO Agent's operational behavior and reporting.
- **Later Stages**: Specialist employee roles, workflows, and bridge integrations will be introduced only after preceding stages are fully verified.

---

## 7. Future Roadmap & Backlog

Ideas and systems that are intentionally deferred and not implemented in early phases are tracked in [BACKLOG.md](BACKLOG.md).
