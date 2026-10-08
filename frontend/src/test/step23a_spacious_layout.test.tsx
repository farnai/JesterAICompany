/// <reference types="@testing-library/jest-dom" />
import '@testing-library/jest-dom'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { OperationalContextPanel } from '../components/OperationalContextPanel'
import { EmployeeWorkstation } from '../components/EmployeeWorkstation'
import { ObjectiveHeader } from '../components/ObjectiveHeader'
import type { CompanyRun, RepositoryProject, EmployeeSummary } from '../types/company'

const mockRun: CompanyRun = {
  run_id: 'crun_test_23a',
  project_id: 'prj_jester',
  state: 'READY_FOR_HUMAN_APPLY',
  selected_agents: ['developer', 'qa'],
  skipped_agents: ['product', 'ux', 'marketing'],
  selection_reasoning: 'Focus on developer implementation and independent QA certification.',
  objective: {
    id: 'obj_123',
    title: 'Defensive canonical pair validation with non-negative versioning',
    description: 'Reject negative version values in canonical_pair_seed while maintaining backward compatibility.',
    constraints: ['Strictly bounded to core/canonical', 'Preserve all non-negative behavior'],
    target_repository: 'C:/Users/fiord/OneDrive/Desktop/Jester',
    created_at: '2026-10-08T12:00:00Z',
  },
  proposal: {
    proposal_id: 'prop_test_23a',
    target_repository_root: 'C:/Users/fiord/OneDrive/Desktop/Jester',
    base_commit_hash: '005a53a4',
    code_patch_artifact_id: 'art_patch_1',
    expected_changed_files: ['backend/app/core/canonical.py', 'tests/core/test_canonical.py'],
    status: 'PROPOSED',
    created_at: '2026-10-08T12:05:00Z',
  } as any,
  events: [
    {
      event_type: 'OBJECTIVE_RECEIVED',
      timestamp: '2026-10-08T12:00:00Z',
      details: { message: 'Received objective' },
    },
    {
      event_type: 'SPECIALISTS_SELECTED',
      timestamp: '2026-10-08T12:01:00Z',
      role: 'CEO',
      details: { selected_agents: ['developer', 'qa'] },
    },
  ],
  qa_verdict: 'PASS',
  qa_summary: 'All unit and boundary criteria verified clean.',
  created_at: '2026-10-08T12:00:00Z',
}

const mockProject: RepositoryProject = {
  project_id: 'prj_jester',
  name: 'Jester — People Discovery & Relationship Intelligence Engine',
  repository: {
    repository_id: 'repo_jester',
    target_branch: 'main',
  } as any,
  verification: {
    is_valid: true,
    branch: 'main',
  } as any,
}

describe('STEP 23A: Spacious Layout & Collapsible Inspector', () => {
  it('1. Inspector Panel renders as a compact vertical rail when collapsed', () => {
    render(
      <OperationalContextPanel
        run={mockRun}
        isCollapsed={true}
      />
    )

    const panel = screen.getByTestId('operational-context-panel')
    expect(panel).toHaveClass('collapsed-rail')
    expect(screen.getByTestId('toggle-inspector-btn')).toBeInTheDocument()

    // Tab buttons are accessible in the collapsed rail
    expect(screen.getByTestId('tab-activity')).toBeInTheDocument()
    expect(screen.getByTestId('tab-artifacts')).toBeInTheDocument()
    expect(screen.getByTestId('tab-qa')).toBeInTheDocument()
    expect(screen.getByTestId('tab-diff')).toBeInTheDocument()
    expect(screen.getByTestId('tab-details')).toBeInTheDocument()
  })

  it('2. Clicking toggle button calls onToggleCollapse to expand the panel', () => {
    const toggleSpy = vi.fn()
    render(
      <OperationalContextPanel
        run={mockRun}
        isCollapsed={true}
        onToggleCollapse={toggleSpy}
      />
    )

    fireEvent.click(screen.getByTestId('toggle-inspector-btn'))
    expect(toggleSpy).toHaveBeenCalledTimes(1)
  })

  it('3. Clicking a tab in collapsed rail triggers toggle and switches tab', () => {
    const toggleSpy = vi.fn()
    render(
      <OperationalContextPanel
        run={mockRun}
        isCollapsed={true}
        onToggleCollapse={toggleSpy}
      />
    )

    // Click Diff in collapsed rail
    fireEvent.click(screen.getByTestId('tab-diff'))
    expect(toggleSpy).toHaveBeenCalledTimes(1)
  })

  it('4. Expanded Inspector renders full header, collapse control, and scrollable body', () => {
    const toggleSpy = vi.fn()
    render(
      <OperationalContextPanel
        run={mockRun}
        isCollapsed={false}
        onToggleCollapse={toggleSpy}
      />
    )

    const panel = screen.getByTestId('operational-context-panel')
    expect(panel).toHaveClass('expanded')
    expect(screen.getByText('Inspector')).toBeInTheDocument()
    expect(screen.getByTestId('toggle-inspector-btn')).toBeInTheDocument()

    // Activity timeline is visible in expanded mode
    expect(screen.getByTestId('activity-feed')).toBeInTheDocument()
    expect(screen.getByText('OBJECTIVE_RECEIVED')).toBeInTheDocument()

    // Clicking collapse calls toggle
    fireEvent.click(screen.getByTestId('toggle-inspector-btn'))
    expect(toggleSpy).toHaveBeenCalledTimes(1)
  })

  it('5. Active EmployeeWorkstation renders enhanced layout with specialist title', () => {
    render(
      <EmployeeWorkstation
        role="developer"
        name="Dato"
        title="Developer Specialist"
        status="Completed"
        isActiveWorkforce={true}
        anchorId="anchor-worker-developer"
        summary={{
          role: 'developer',
          status: 'Completed',
          summary: 'Implemented defensive validation in canonical_pair_seed.',
          artifact_refs: [
            {
              artifact_id: 'art_1',
              name: 'canonical_validation.patch',
              path: 'backend/app/core/canonical.py',
              sha256: 'abc12345',
              type: 'CODE_PATCH',
            },
          ],
        }}
      />
    )

    const station = screen.getByTestId('station-developer')
    expect(station).toHaveClass('active-floor-station')
    expect(screen.getByText('Dato')).toBeInTheDocument()
    expect(screen.getByText('Developer Specialist')).toBeInTheDocument()
    expect(screen.getByText('DEVELOPER')).toBeInTheDocument()
    expect(screen.getByText('Completed')).toBeInTheDocument()
    expect(screen.getByText('canonical_validation.patch')).toBeInTheDocument()
  })

  it('6. ObjectiveHeader renders prominent title and full constraints without cramped truncation', () => {
    render(
      <ObjectiveHeader
        run={mockRun}
        activeProject={mockProject}
      />
    )

    expect(screen.getByText('Defensive canonical pair validation with non-negative versioning')).toBeInTheDocument()
    expect(screen.getByText(/Strictly bounded to core\/canonical · Preserve all non-negative behavior/)).toBeInTheDocument()
    expect(screen.getByText('Approval')).toBeInTheDocument()
  })
})