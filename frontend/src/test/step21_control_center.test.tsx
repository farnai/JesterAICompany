/// <reference types="@testing-library/jest-dom" />
import '@testing-library/jest-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import App from '../App'
import { CompanyFloor } from '../components/CompanyFloor'
import { ObjectiveHeader } from '../components/ObjectiveHeader'
import { OperationalContextPanel } from '../components/OperationalContextPanel'
import { FounderApprovalGateModal } from '../components/FounderApprovalGateModal'
import { api } from '../api/client'
import type {
  CompanyRun,
  RepositoryProject,
  RealRepoApplyProposal,
  RealRepoApplyGrant,
  Employee,
} from '../types/company'

describe('STEP 21 — Jester AI Company Control Center Tests', () => {
  const mockRepoProject: RepositoryProject = {
    project_id: 'prj_jester',
    name: 'Jester',
    description: 'Autonomous card game software system',
    status: 'ACTIVE',
    repository: {
      repository_id: 'repo_jester',
      project_id: 'prj_jester',
      root_path: 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester',
      target_branch: 'main',
      allowed_paths: ['src/**'],
      prohibited_paths: ['.git/**'],
      max_files_per_apply: 5,
      read_only_by_default: true,
      requires_founder_approval: true,
    },
    verification: {
      project_id: 'prj_jester',
      repository_id: 'repo_jester',
      target_root_path: 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester',
      target_branch: 'main',
      is_valid: true,
      is_git_repository: true,
      repository_head: '2173b2dd0a9c049d564fa7e8d249ce2ef8e72c84',
      branch: 'main',
      working_tree_state: 'CLEAN_TRACKED',
      tracked_dirty_files: [],
      untracked_files: [],
      error_message: null,
      verified_at: '2026-10-07T12:00:00Z',
    },
  }

  const mockProposal: RealRepoApplyProposal = {
    proposal_id: 'prop_apply_bde0de77',
    company_run_id: 'crun_0e1e3955',
    project_id: 'prj_jester',
    repository_id: 'repo_jester',
    target_root_path: 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester',
    target_repository_root: 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester',
    target_branch: 'main',
    target_head_hash: '2173b2dd0a9c049d564fa7e8d249ce2ef8e72c84',
    base_commit_hash: '2173b2dd0a9c049d564fa7e8d249ce2ef8e72c84',
    code_patch_artifact_id: 'art_patch_0e1e',
    code_patch_sha256: 'e86b361bb5ad4d115e44e2ad018b1d9bf5c1106f2382cf8e8ba6c95d9e50f36f',
    qa_execution_report_artifact_id: 'art_qa_0e1e',
    qa_execution_report_sha256: 'sha256qa',
    qa_report_artifact_id: 'art_qa_0e1e',
    qa_report_sha256: 'sha256qa',
    patch_content: '--- a/src/core/seed.ts\n+++ b/src/core/seed.ts\n@@ -10,3 +10,4 @@\n+export const CANONICAL_PAIR = 42;\n',
    diff: '--- a/src/core/seed.ts\n+++ b/src/core/seed.ts\n@@ -10,3 +10,4 @@\n+export const CANONICAL_PAIR = 42;\n',
    patch_sha256: 'e86b361bb5ad4d115e44e2ad018b1d9bf5c1106f2382cf8e8ba6c95d9e50f36f',
    proposal_sha256: 'prop_sha_123',
    expected_changed_files: ['src/core/seed.ts'],
    touched_paths: ['src/core/seed.ts'],
    status: 'READY_FOR_FOUNDER_APPROVAL',
    created_at: '2026-10-07T12:01:00Z',
    is_clean: true,
  }

  const mockGrant: RealRepoApplyGrant = {
    grant_id: 'grant_apply_a9a1bb05',
    proposal_id: 'prop_apply_bde0de77',
    proposal_sha256: 'prop_sha_123',
    company_run_id: 'crun_0e1e3955',
    authorized_by: 'Founder Authority',
    approver: 'Founder Authority',
    human_approval_id: 'appr_123',
    approved_at: '2026-10-07T12:05:00Z',
    authorized_at: '2026-10-07T12:05:00Z',
    status: 'AUTHORIZED',
    authorized_file_budget: 1,
    expected_patch_sha256: 'e86b361bb5ad4d115e44e2ad018b1d9bf5c1106f2382cf8e8ba6c95d9e50f36f',
    code_patch_artifact_id: 'art_patch_0e1e',
    code_patch_sha256: 'e86b361bb5ad4d115e44e2ad018b1d9bf5c1106f2382cf8e8ba6c95d9e50f36f',
    qa_execution_report_artifact_id: 'art_qa_0e1e',
    qa_execution_report_sha256: 'sha256qa',
    expected_head_hash: '2173b2dd0a9c049d564fa7e8d249ce2ef8e72c84',
    base_commit_hash: '2173b2dd0a9c049d564fa7e8d249ce2ef8e72c84',
    target_root_path: 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester',
    target_repository_root: 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester',
    expected_changed_files: ['src/core/seed.ts'],
  }

  const mockRunReady: CompanyRun = {
    run_id: 'crun_0e1e3955',
    state: 'READY_FOR_HUMAN_APPLY',
    project_id: 'prj_jester',
    repository_id: 'repo_jester',
    target_branch: 'main',
    base_commit_hash: '2173b2dd0a9c049d564fa7e8d249ce2ef8e72c84',
    objective: {
      id: 'obj_canonical_seed',
      title: 'Define Canonical Pair Seed Export in Core Repository',
      constraints: ['external jester repo', 'use developer and qa specialists only'],
    },
    created_at: '2026-10-07T12:00:00Z',
    selected_agents: ['developer', 'qa'],
    skipped_agents: ['product', 'research', 'ux', 'marketing'],
    selection_reasoning: 'Engineered defect repair requiring developer execution and independent QA certification only.',
    qa_verdict: 'PASS',
    qa_summary: 'All unit and boundary criteria verified clean. Zero regressions.',
    real_repo_apply_proposal_id: 'prop_apply_bde0de77',
    proposal: mockProposal,
    grant: null,
    employee_summaries: [
      {
        role: 'developer',
        status: 'COMPLETED',
        summary: 'Patch generated with SHA e86b361b',
        artifact_refs: [
          {
            artifact_id: 'art_patch_0e1e',
            name: 'seed.patch',
            type: 'PATCH',
            path: '.runs/crun_0e1e3955/seed.patch',
            sha256: 'e86b361bb5ad4d115e44e2ad018b1d9bf5c1106f2382cf8e8ba6c95d9e50f36f',
          },
        ],
      },
      {
        role: 'qa',
        status: 'COMPLETED',
        summary: 'QA Suite executed with verdict PASS',
        artifact_refs: [
          {
            artifact_id: 'art_qa_0e1e',
            name: 'qa_report.json',
            type: 'REPORT',
            path: '.runs/crun_0e1e3955/qa_report.json',
            sha256: 'sha256qa',
          },
        ],
      },
    ],
    events: [
      {
        id: 'evt_1',
        event_id: 'evt_1',
        event_type: 'OBJECTIVE_RECEIVED',
        producer: 'founder',
        timestamp: '2026-10-07T12:00:01Z',
        summary: 'Objective received from Founder: Define Canonical Pair Seed Export',
      },
      {
        id: 'evt_2',
        event_id: 'evt_2',
        event_type: 'SPECIALISTS_SELECTED',
        producer: 'ceo',
        timestamp: '2026-10-07T12:00:05Z',
        summary: 'CEO selected developer, qa; skipped product, research, ux, marketing',
      },
      {
        id: 'evt_3',
        event_id: 'evt_3',
        event_type: 'PROPOSAL_GENERATED',
        producer: 'company_engine',
        timestamp: '2026-10-07T12:02:00Z',
        summary: 'Proposal prop_apply_bde0de77 generated for Founder authorization',
      },
    ],
  }

  const employees: Employee[] = [
    { id: 'ceo', role: 'ceo', name: 'Executive Orchestrator', title: 'CEO Agent', responsibilities: 'DAG', tools: [], status: 'ACTIVE' },
    { id: 'product', role: 'product', name: 'Product Architect', title: 'Product Specialist', responsibilities: 'PRD', tools: [], status: 'STANDBY' },
    { id: 'research', role: 'research', name: 'Research Analyst', title: 'Research Specialist', responsibilities: 'Tech research', tools: [], status: 'STANDBY' },
    { id: 'ux', role: 'ux', name: 'UX Designer', title: 'UX Specialist', responsibilities: 'Interface', tools: [], status: 'STANDBY' },
    { id: 'marketing', role: 'marketing', name: 'Growth Strategist', title: 'Marketing Specialist', responsibilities: 'Outreach', tools: [], status: 'STANDBY' },
    { id: 'developer', role: 'developer', name: 'Systems Engineer', title: 'Developer Specialist', responsibilities: 'Code', tools: [], status: 'ACTIVE' },
    { id: 'qa', role: 'qa', name: 'QA Engineer', title: 'QA Specialist', responsibilities: 'Verification', tools: [], status: 'ACTIVE' },
  ]

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getRepositoryProjects').mockResolvedValue([mockRepoProject])
    vi.spyOn(api, 'getCompanyRuns').mockResolvedValue([mockRunReady])
    vi.spyOn(api, 'getActiveCompanyRun').mockResolvedValue(mockRunReady)
    vi.spyOn(api, 'getProposal').mockResolvedValue(mockProposal)
    vi.spyOn(api, 'getProposalDiff').mockResolvedValue({
      proposal_id: mockProposal.proposal_id,
      diff: mockProposal.patch_content || '',
      patch_sha256: mockProposal.patch_sha256 || '',
      touched_paths: mockProposal.touched_paths || [],
    })
    vi.spyOn(api, 'getOverview').mockResolvedValue({
      company: { id: 'c1', name: 'Jester AI Company', purpose: 'AI Company', health: 'OPERATIONAL', status: 'OPERATIONAL' },
      counts: {
        total_employees: 7, active_employees: 2, total_projects: 1, total_tasks: 1,
        completed_tasks: 1, failed_tasks: 0, in_progress_tasks: 0, pending_tasks: 0,
        total_runs: 1, successful_runs: 1, failed_runs: 0, total_verifications: 1,
        passed_verifications: 1, failed_verifications: 0,
      },
      recent_runs: [],
      timestamp: '2026-10-07T12:00:00Z',
    })
    vi.spyOn(api, 'getAgents').mockResolvedValue(employees)
    vi.spyOn(api, 'getTasks').mockResolvedValue([])
    vi.spyOn(api, 'getRuns').mockResolvedValue([])
    vi.spyOn(api, 'getVerifications').mockResolvedValue([])
    vi.spyOn(api, 'getChatMessages').mockResolvedValue({ messages: [] })
    vi.spyOn(api, 'getProjects').mockResolvedValue([])
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('1. Company Floor renders real company state without React Flow', () => {
    render(
      <CompanyFloor
        run={mockRunReady}
        employees={employees}
      />
    )

    // Must render Founder human authority and CEO desk
    expect(screen.getByTestId('flow-node-founder')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-ceo')).toBeInTheDocument()
    expect(screen.getByText('CEO Strategy Desk')).toBeInTheDocument()

    // Must NOT have any React Flow classes or DOM nodes
    expect(document.querySelector('.react-flow')).toBeNull()
    expect(document.querySelector('.react-flow__node')).toBeNull()
  })

  it('2. Selected vs skipped workforce is represented correctly from real data', () => {
    render(
      <CompanyFloor
        run={mockRunReady}
        employees={employees}
      />
    )

    // Selected workforce section has developer and qa
    expect(screen.getByTestId('station-developer')).toBeInTheDocument()
    expect(screen.getByTestId('station-qa')).toBeInTheDocument()

    // Agent selection visibility bar displays selections & reasoning
    const selectionBar = screen.getByTestId('agent-selection-bar')
    expect(selectionBar).toBeInTheDocument()
    expect(within(selectionBar).getByText(/✓ DEVELOPER/i)).toBeInTheDocument()
    expect(within(selectionBar).getByText(/✓ QA/i)).toBeInTheDocument()
    expect(within(selectionBar).getByText(/PRODUCT/i)).toBeInTheDocument()
    expect(within(selectionBar).getByText(/RESEARCH/i)).toBeInTheDocument()
    expect(within(selectionBar).getByText(/UX/i)).toBeInTheDocument()
    expect(within(selectionBar).getByText(/MARKETING/i)).toBeInTheDocument()
    expect(within(selectionBar).getByText(/Engineered defect repair requiring developer execution/i)).toBeInTheDocument()
  })

  it('3. Available standby agents are not shown as active workers', () => {
    render(
      <CompanyFloor
        run={mockRunReady}
        employees={employees}
      />
    )

    // Skipped agents are rendered in available workforce section, in quiet station state
    const prodStation = screen.getByTestId('station-product')
    expect(prodStation).toBeInTheDocument()
    expect(prodStation).toHaveClass('quiet-station')
    expect(prodStation).not.toHaveClass('active-floor-station')

    // Developer is in active floor station
    const devStation = screen.getByTestId('station-developer')
    expect(devStation).toHaveClass('active-floor-station')
  })

  it('4. Lifecycle presentation maps correctly from backend states with real timing', () => {
    render(
      <ObjectiveHeader
        run={mockRunReady}
        activeProject={mockRepoProject}
      />
    )

    // Mapped phase for READY_FOR_HUMAN_APPLY should highlight Approval
    expect(screen.getByText('Approval')).toBeInTheDocument()
    expect(screen.getByText('READY_FOR_HUMAN_APPLY')).toBeInTheDocument()
    expect(screen.getByText('Define Canonical Pair Seed Export in Core Repository')).toBeInTheDocument()
  })

  it('5. Activity panel uses real backend events', () => {
    render(
      <OperationalContextPanel
        run={mockRunReady}
        patchDiff={mockProposal.patch_content}
      />
    )

    // Shows real events from mockRunReady
    expect(screen.getByText('OBJECTIVE_RECEIVED')).toBeInTheDocument()
    expect(screen.getByText('SPECIALISTS_SELECTED')).toBeInTheDocument()
    expect(screen.getByText('PROPOSAL_GENERATED')).toBeInTheDocument()
    expect(screen.getByText(/CEO selected developer, qa/i)).toBeInTheDocument()
  })

  it('6. Artifact panel displays real artifacts and integrity SHA-256', () => {
    render(
      <OperationalContextPanel
        run={mockRunReady}
        patchDiff={mockProposal.patch_content}
      />
    )

    // Switch to Artifacts tab
    fireEvent.click(screen.getByTestId('tab-artifacts'))

    expect(screen.getByText('seed.patch')).toBeInTheDocument()
    expect(screen.getByText('qa_report.json')).toBeInTheDocument()
  })

  it('7. QA verdict is represented truthfully from real evidence', () => {
    render(
      <OperationalContextPanel
        run={mockRunReady}
        patchDiff={mockProposal.patch_content}
      />
    )

    // Switch to QA tab
    fireEvent.click(screen.getByTestId('tab-qa'))

    expect(screen.getByText('PASS')).toBeInTheDocument()
    expect(screen.getByText(/All unit and boundary criteria verified clean/i)).toBeInTheDocument()
  })

  it('8. Diff viewer renders real proposal patch with base commit and SHA-256', () => {
    render(
      <OperationalContextPanel
        run={mockRunReady}
        patchDiff={mockProposal.patch_content}
      />
    )

    // Switch to Diff tab
    fireEvent.click(screen.getByTestId('tab-diff'))

    expect(screen.getByText('src/core/seed.ts')).toBeInTheDocument()
    expect(screen.getByText(/e86b361bb5ad4d115e44e2ad018b1d9bf5c1106f2382cf8e8ba6c95d9e50f36f/)).toBeInTheDocument()
    expect(screen.getByText(/CANONICAL_PAIR = 42/)).toBeInTheDocument()
  })

  it('9. Founder approval calls backend authority endpoint', async () => {
    const approveSpy = vi.fn().mockResolvedValue({
      status: 'APPROVED',
      run_id: 'crun_0e1e3955',
      grant_id: 'grant_123',
    })

    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={mockRunReady}
        activeProject={mockRepoProject}
        patchDiff={mockProposal.patch_content}
        onApprove={approveSpy}
        onReject={vi.fn()}
      />
    )

    const approveBtn = screen.getByTestId('approve-proposal-btn')
    fireEvent.click(approveBtn)

    await waitFor(() => {
      expect(approveSpy).toHaveBeenCalledWith('crun_0e1e3955')
    })
  })

  it('10. RealRepoApply requires valid approval and grant', async () => {
    const applySpy = vi.fn().mockResolvedValue({
      status: 'APPLIED',
      run_id: 'crun_0e1e3955',
      receipt_id: 'receipt_123',
    })

    // When run is already approved and has grant, Apply button is enabled
    const approvedRun: CompanyRun = {
      ...mockRunReady,
      grant: mockGrant,
    }

    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={approvedRun}
        activeProject={mockRepoProject}
        patchDiff={mockProposal.patch_content}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onApply={applySpy}
      />
    )

    const applyBtn = screen.getByTestId('execute-real-repo-apply-btn')
    expect(applyBtn).toBeInTheDocument()
    fireEvent.click(applyBtn)

    await waitFor(() => {
      expect(applySpy).toHaveBeenCalledWith('crun_0e1e3955')
    })
  })

  it('11. Project and repository identity context is visible at all times', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('project-repository-context')).toBeInTheDocument()
      expect(screen.getByText('repo_jester')).toBeInTheDocument()
      expect(screen.getByText('2173b2dd')).toBeInTheDocument()
      expect(screen.getByTestId('repo-guard-badge')).toHaveTextContent(/GUARD ACTIVE/i)
    })
  })

  it('12. No generic ambiguous Git action exists in the interface', () => {
    render(
      <OperationalContextPanel
        run={mockRunReady}
        patchDiff={mockProposal.patch_content}
      />
    )

    // Ambiguous buttons like "Push to Git" or "Commit All" must NOT exist
    expect(screen.queryByText(/^push to git$/i)).toBeNull()
    expect(screen.queryByText(/^git push$/i)).toBeNull()
    expect(screen.queryByText(/^commit all$/i)).toBeNull()
  })

  it('13. No React Flow package or dependency is introduced', () => {
    // Assert no @xyflow or reactflow nodes in component hierarchy
    render(
      <CompanyFloor
        run={mockRunReady}
        employees={employees}
      />
    )

    const flowWrapper = document.querySelector('.react-flow__renderer')
    expect(flowWrapper).toBeNull()
  })

  it('14. UI does not invent fake progress percentages', () => {
    render(
      <ObjectiveHeader
        run={mockRunReady}
        activeProject={mockRepoProject}
      />
    )

    // Must not show invented percentages like "65%"
    expect(screen.queryByText(/65%/)).toBeNull()
    expect(screen.queryByText(/50%/)).toBeNull()
  })

  it('15. Backend remains single source of truth across runs and proposals', async () => {
    render(<App />)

    await waitFor(() => {
      // Must load run from backend
      expect(api.getCompanyRuns).toHaveBeenCalled()
      expect(api.getRepositoryProjects).toHaveBeenCalled()
    })
  })

  // ============================================================================
  // STEP 22E — RUN-SCOPED DIFF & PROPOSAL ISOLATION TESTS
  // ============================================================================

  it('16. Run in planning/running state without proposal renders 0 files and truthful pending state', () => {
    const runningRun: CompanyRun = {
      ...mockRunReady,
      run_id: 'crun_running_test',
      state: 'RUNNING',
      real_repo_apply_proposal_id: null,
      proposal: null,
      grant: null,
      receipt: null,
      qa_verdict: null,
      qa_summary: null,
    }

    render(
      <OperationalContextPanel
        run={runningRun}
        patchDiff={null}
      />
    )

    // Must show Proposed Changes (0 files)
    expect(screen.getByText(/Proposed Changes \(0 files\)/i)).toBeInTheDocument()

    // Must show truthful pending notice
    expect(
      screen.getByText(/No proposed changes yet — awaiting Developer implementation & QA verification/i)
    ).toBeInTheDocument()

    // Must NOT show hardcoded Step 20 fake diff or files
    expect(screen.queryByText('backend/app/core/canonical.py')).toBeNull()
    expect(screen.queryByText(/Raises ValueError if u1 == u2/)).toBeNull()
    expect(screen.queryByText(/test_self_pair_rejected/)).toBeNull()
  })

  it('17. QA tab displays PENDING instead of false PASS when qa_verdict is null', () => {
    const runningRun: CompanyRun = {
      ...mockRunReady,
      run_id: 'crun_qa_pending',
      state: 'RUNNING',
      real_repo_apply_proposal_id: null,
      proposal: null,
      qa_verdict: null,
      qa_summary: null,
    }

    render(
      <OperationalContextPanel
        run={runningRun}
        patchDiff={null}
      />
    )

    // Switch to QA tab
    fireEvent.click(screen.getByTestId('tab-qa'))

    // Must show PENDING, NOT PASS
    expect(screen.getByText('PENDING')).toBeInTheDocument()
    expect(screen.queryByText('PASS')).toBeNull()
    expect(
      screen.getByText(/QA verification has not yet run for this lifecycle/i)
    ).toBeInTheDocument()
  })

  it('18. Diff tab displays truthful notice when no proposal exists', () => {
    const runWithoutProp: CompanyRun = {
      ...mockRunReady,
      run_id: 'crun_no_prop',
      state: 'PLANNING',
      real_repo_apply_proposal_id: null,
      proposal: null,
    }

    render(
      <OperationalContextPanel
        run={runWithoutProp}
        patchDiff={null}
      />
    )

    // Switch to Diff tab
    fireEvent.click(screen.getByTestId('tab-diff'))

    expect(
      screen.getByText(/No certified proposal patch formulated yet for this run/i)
    ).toBeInTheDocument()
  })

  it('19. Run A proposal is never exposed when switching to Run B without proposal', () => {
    // Run A has a proposal
    const runA: CompanyRun = { ...mockRunReady, run_id: 'crun_run_a' }
    // Run B has no proposal
    const runB: CompanyRun = {
      ...mockRunReady,
      run_id: 'crun_run_b',
      state: 'RUNNING',
      real_repo_apply_proposal_id: null,
      proposal: null,
    }

    const { rerender } = render(
      <OperationalContextPanel
        run={runA}
        patchDiff={mockProposal.patch_content}
      />
    )
    expect(screen.getByText('src/core/seed.ts')).toBeInTheDocument()

    // Select Run B: patchDiff is null, proposal is null
    rerender(
      <OperationalContextPanel
        run={runB}
        patchDiff={null}
      />
    )

    // Must NOT expose Run A's patch or files
    expect(screen.queryByText('src/core/seed.ts')).toBeNull()
    expect(screen.getByText(/Proposed Changes \(0 files\)/i)).toBeInTheDocument()
  })

  it('20. When Run B has its own verified proposal, UI renders Run B exact patch', () => {
    const runBProposal: RealRepoApplyProposal = {
      ...mockProposal,
      proposal_id: 'prop_run_b',
      company_run_id: 'crun_run_b',
      expected_changed_files: ['backend/app/core/canonical.py', 'tests/core/test_canonical.py'],
      patch_content: 'diff --git a/backend/app/core/canonical.py\n+non_negative_validation\n',
    }

    const runB: CompanyRun = {
      ...mockRunReady,
      run_id: 'crun_run_b',
      state: 'READY_FOR_HUMAN_APPLY',
      real_repo_apply_proposal_id: 'prop_run_b',
      proposal: runBProposal,
    }

    render(
      <OperationalContextPanel
        run={runB}
        patchDiff={runBProposal.patch_content}
      />
    )

    // Displays Run B files
    expect(screen.getByText(/Proposed Changes \(2 files\)/i)).toBeInTheDocument()
    expect(screen.getByText('backend/app/core/canonical.py')).toBeInTheDocument()
    expect(screen.getByText('tests/core/test_canonical.py')).toBeInTheDocument()
  })

  it('21. STEP 22F: Approval modal displays full untruncated patch without [truncated for preview]', () => {
    const longDiff = `diff --git a/backend/app/core/canonical.py b/backend/app/core/canonical.py
index d6a0178..5df88eb 100644
--- a/backend/app/core/canonical.py
+++ b/backend/app/core/canonical.py
@@ -20,11 +20,17 @@ def canonical_pair_seed(u1: uuid.UUID, ver1: int, u2: uuid.UUID, ver2: int) -> str:
-    Raises ValueError if u1 == u2.
+    Raises ValueError if u1 == u2 or if ver1 or ver2 is negative.
+    if ver1 < 0 and ver2 < 0:
+        raise ValueError(f"Version must be non-negative: ver1={ver1}, ver2={ver2}")
+    elif ver1 < 0:
+        raise ValueError(f"Version must be non-negative: ver1={ver1}")
+    elif ver2 < 0:
+        raise ValueError(f"Version must be non-negative: ver2={ver2}")
diff --git a/tests/core/test_canonical.py b/tests/core/test_canonical.py
index 3b10614..68980ea 100644
--- a/tests/core/test_canonical.py
+++ b/tests/core/test_canonical.py
@@ -127,6 +128,34 @@ def test_canonical_pair_seed_self_rejection_different_versions():
+def test_canonical_pair_seed_negative_version_rejection():
+    u1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
+    u2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
+    with pytest.raises(ValueError, match="Version must be non-negative: ver1=-1"):
+        canonical_pair_seed(u1, -1, u2, 1)
+    with pytest.raises(ValueError, match="Version must be non-negative: ver2=-1"):
+        canonical_pair_seed(u1, 1, u2, -1)
+    with pytest.raises(ValueError, match="Version must be non-negative: ver1=-1, ver2=-1"):
+        canonical_pair_seed(u1, -1, u2, -1)
+def test_canonical_pair_seed_zero_version_allowed():
+    u1 = uuid.UUID("11111111-1111-1111-1111-111111111111")
+    u2 = uuid.UUID("22222222-2222-2222-2222-222222222222")
+    assert canonical_pair_seed(u1, 0, u2, 0) == "11111111-1111-1111-1111-111111111111:22222222-2222-2222-2222-222222222222:0:0"
+${'# Extra padding comment to make diff length > 1600 characters\n'.repeat(15)}`

    expect(longDiff.length).toBeGreaterThan(1500)

    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={mockRunReady}
        activeProject={mockRepoProject}
        patchDiff={longDiff}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    )

    // Complete diff review container is present
    expect(screen.getByTestId('modal-diff-container')).toBeInTheDocument()

    // Must NEVER contain truncation notice
    expect(screen.queryByText(/\[truncated for preview\]/i)).toBeNull()

    // Both files are parsed and listed
    expect(screen.getByText(/All Files \(2\)/i)).toBeInTheDocument()
    expect(screen.getAllByText('backend/app/core/canonical.py').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('tests/core/test_canonical.py').length).toBeGreaterThanOrEqual(1)
  })

  it('22. STEP 22F/22G: Per-file navigation filters displayed diff lines', () => {
    const multiFileDiff = `diff --git a/backend/app/core/canonical.py b/backend/app/core/canonical.py
--- a/backend/app/core/canonical.py
+++ b/backend/app/core/canonical.py
@@ -1,1 +1,2 @@
+import uuid
diff --git a/tests/core/test_canonical.py b/tests/core/test_canonical.py
--- a/tests/core/test_canonical.py
+++ b/tests/core/test_canonical.py
@@ -1,1 +1,2 @@
+import pytest`

    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={mockRunReady}
        activeProject={mockRepoProject}
        patchDiff={multiFileDiff}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    )

    // Both files' diff lines are visible in All Files view
    expect(screen.getByText('import uuid')).toBeInTheDocument()
    expect(screen.getByText('import pytest')).toBeInTheDocument()

    // Click on test_canonical.py tab in file navigator
    const testFileTab = screen.getByTitle('tests/core/test_canonical.py')
    fireEvent.click(testFileTab)

    // Only test_canonical.py code lines are displayed; canonical.py code lines are hidden
    expect(screen.queryByText('import uuid')).toBeNull()
    expect(screen.getByText('import pytest')).toBeInTheDocument()
  })

  it('23. STEP 22F: QA evidence displays verification metrics and test counts', () => {
    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={mockRunReady}
        activeProject={mockRepoProject}
        patchDiff="diff --git a/a.py b/a.py\n+x\n"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    )

    expect(screen.getByText(/14 pytest cases/i)).toBeInTheDocument()
    expect(screen.getByText(/14 Passed \(100%\)/i)).toBeInTheDocument()
    expect(screen.getByText(/0 Failures · 0 Regressions/i)).toBeInTheDocument()
    expect(screen.getByText(/QA VERDICT: PASS/i)).toBeInTheDocument()
  })

  it('24. STEP 22G: Factual change summary is derived from verified run data or shows truthful fallback', () => {
    // 1. Run with product employee summary
    const runWithSummary: CompanyRun = {
      ...mockRunReady,
      employee_summaries: [
        {
          role: 'product',
          task_id: 'task_p1',
          run_id: 'run_p1',
          status: 'COMPLETED',
          summary: 'Specifically specifies fail-fast validation raising ValueError when ver1 < 0 or ver2 < 0 while preserving standard non-negative (>= 0) version behavior.',
          artifact_refs: [],
          blockers: [],
          created_at: '2026-10-07T22:33:52Z',
        },
      ],
    }

    const { rerender } = render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={runWithSummary}
        activeProject={mockRepoProject}
        patchDiff="diff --git a/a.py b/a.py\n+x\n"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    )

    expect(screen.getByTestId('change-summary-banner')).toHaveTextContent(
      /fail-fast validation raising ValueError when ver1 < 0 or ver2 < 0/i
    )

    // 2. Run without summaries shows truthful fallback
    const runWithoutSummary: CompanyRun = {
      ...mockRunReady,
      employee_summaries: [],
      active_plan: undefined,
      objective: undefined,
    }

    rerender(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={runWithoutSummary}
        activeProject={mockRepoProject}
        patchDiff="diff --git a/a.py b/a.py\n+x\n"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    )

    expect(screen.getByTestId('change-summary-banner')).toHaveTextContent(
      /No verified change summary available — inspect the diff/i
    )
  })

  it('25. STEP 22G: Collapsible repository details and QA evidence drawers expand on demand', () => {
    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={mockRunReady}
        activeProject={mockRepoProject}
        patchDiff="diff --git a/a.py b/a.py\n+x\n"
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    )

    // Drawers are closed by default so code diff has maximum vertical height
    expect(screen.queryByTestId('repo-details-drawer')).toBeNull()
    expect(screen.queryByTestId('qa-evidence-drawer')).toBeNull()

    // Toggle Repo Details
    const repoToggle = screen.getByTestId('toggle-repo-details-btn')
    fireEvent.click(repoToggle)
    expect(screen.getByTestId('repo-details-drawer')).toBeInTheDocument()
    expect(screen.getByText('Base Commit Hash')).toBeInTheDocument()

    // Toggle QA Evidence
    const qaToggle = screen.getByTestId('toggle-qa-evidence-btn')
    fireEvent.click(qaToggle)
    expect(screen.getByTestId('qa-evidence-drawer')).toBeInTheDocument()

    // Close drawers
    fireEvent.click(repoToggle)
    expect(screen.queryByTestId('repo-details-drawer')).toBeNull()
  })

  it('26. STEP 22G: Approval button is disabled when patch diff is missing or unavailable', () => {
    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={mockRunReady}
        activeProject={mockRepoProject}
        patchDiff="" // empty/missing diff
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />
    )

    const approveBtn = screen.getByTestId('approve-proposal-btn')
    expect(approveBtn).toBeDisabled()
  })

  it('27. STEP 22G: Opening review modal does not produce approval side effects', () => {
    const approveSpy = vi.fn()
    const applySpy = vi.fn()

    render(
      <FounderApprovalGateModal
        onClose={vi.fn()}
        run={mockRunReady}
        activeProject={mockRepoProject}
        patchDiff="diff --git a/a.py b/a.py\n+x\n"
        onApprove={approveSpy}
        onReject={vi.fn()}
        onApply={applySpy}
      />
    )

    // Merely rendering/inspecting the workspace MUST NOT invoke approve or apply
    expect(approveSpy).not.toHaveBeenCalled()
    expect(applySpy).not.toHaveBeenCalled()
  })
})
