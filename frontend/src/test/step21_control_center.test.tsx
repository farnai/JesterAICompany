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
})
