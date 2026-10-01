/// <reference types="@testing-library/jest-dom" />
import '@testing-library/jest-dom'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { WorkstationGrid } from '../components/WorkstationGrid'
import { CompanyFlowCanvas } from '../components/CompanyFlowCanvas'
import type { Employee, Task, TaskRun, VerificationResult } from '../types/company'

describe('STAGE 27-E.2.2: Company World Visual Experience', () => {
  const mockRoster: Employee[] = [
    {
      id: 'developer',
      role: 'developer',
      name: 'Developer Specialist',
      title: 'Senior Developer Agent',
      responsibilities: 'Autonomous clean code implementation',
      status: 'ACTIVE',
      tools: ['view_file', 'edit_file'],
    },
    {
      id: 'ux',
      role: 'ux',
      name: 'UX Designer Specialist',
      title: 'Interface Architect',
      responsibilities: 'User journey and interface structures',
      status: 'ACTIVE',
      tools: ['view_file'],
    },
    {
      id: 'qa',
      role: 'qa',
      name: 'QA Auditor Specialist',
      title: 'QA Engineer Agent',
      responsibilities: 'Rigorous acceptance criteria verification',
      status: 'ACTIVE',
      tools: ['run_test'],
    },
    {
      id: 'research',
      role: 'research',
      name: 'Research Specialist',
      title: 'Deep-dive Investigator',
      responsibilities: 'Evidence and technical discovery',
      status: 'ACTIVE',
      tools: ['search'],
    },
  ]

  it('1. Renders real employees from company roster without hardcoding', () => {
    render(
      <WorkstationGrid
        employees={mockRoster}
        onSelectEmployee={vi.fn()}
      />
    )

    expect(screen.getByTestId('station-developer')).toBeInTheDocument()
    expect(screen.getByTestId('station-ux')).toBeInTheDocument()
    expect(screen.getByTestId('station-qa')).toBeInTheDocument()
    expect(screen.getByTestId('station-research')).toBeInTheDocument()
    expect(screen.getByText('Developer Specialist')).toBeInTheDocument()
    expect(screen.getByText('UX Designer Specialist')).toBeInTheDocument()
  })

  it('2. Idle employees are not falsely shown as active', () => {
    // When no task is allocated, employees must be IDLE (available), not active
    render(
      <WorkstationGrid
        employees={mockRoster}
        activeTask={null}
        onSelectEmployee={vi.fn()}
      />
    )

    const devStation = screen.getByTestId('station-developer')
    const uxStation = screen.getByTestId('station-ux')

    // Must have quiet station and idle styling
    expect(devStation).toHaveClass('quiet-station')
    expect(devStation).toHaveClass('state-idle')
    expect(devStation).not.toHaveClass('active-worker')

    expect(uxStation).toHaveClass('quiet-station')
    expect(uxStation).toHaveClass('state-idle')

    // Must show AVAILABLE badge, not falsely claiming ACTIVE work
    const availableBadges = screen.getAllByText('AVAILABLE')
    expect(availableBadges.length).toBe(4)
  })

  it('3. Active employees genuinely involved in work reflect real state', () => {
    const activeTask: Task = {
      id: 'task_active_01',
      project_id: 'proj_01',
      title: 'Build Secure Auth Flow',
      goal: 'Implement JWT tokens',
      status: 'IN_PROGRESS',
      assigned_to: 'developer',
      required_roles: ['developer'],
      constraints: [],
      runs: [],
      created_at: '2026-09-29T10:00:00Z',
      updated_at: '2026-09-29T10:05:00Z',
    }

    render(
      <WorkstationGrid
        employees={mockRoster}
        activeTask={activeTask}
        onSelectEmployee={vi.fn()}
      />
    )

    const devStation = screen.getByTestId('station-developer')
    const uxStation = screen.getByTestId('station-ux')

    // Assigned developer is actively emphasized
    expect(devStation).toHaveClass('state-active')
    expect(devStation).toHaveClass('active-worker')
    expect(devStation.querySelector('.badge-active')).toBeInTheDocument()
    expect(screen.getByText(/Actively executing work on mission/i)).toBeInTheDocument()

    // Unassigned UX specialist remains quiet and available
    expect(uxStation).toHaveClass('quiet-station')
    expect(uxStation).toHaveClass('state-idle')
    expect(uxStation).not.toHaveClass('active-worker')
  })

  it('4. Task state is rendered from real data in React Flow', () => {
    const activeTask: Task = {
      id: 'task_real_42',
      project_id: 'proj_01',
      title: 'Migrate Core Database Schema',
      goal: 'PostgreSQL partitioned tables',
      status: 'IN_PROGRESS',
      assigned_to: 'developer',
      required_roles: ['developer'],
      constraints: [],
      runs: [],
      created_at: '2026-09-29T10:00:00Z',
      updated_at: '2026-09-29T10:05:00Z',
    }

    render(
      <CompanyFlowCanvas
        activeTask={activeTask}
        runs={[]}
        verifications={[]}
      />
    )

    const taskNode = screen.getByTestId('flow-node-task')
    expect(taskNode).toBeInTheDocument()
    expect(screen.getByText('Migrate Core Database Schema')).toBeInTheDocument()
    expect(screen.getByText('IN_PROGRESS')).toBeInTheDocument()
  })

  it('5. QA state is rendered from real verification data (PASSED vs FAILED)', () => {
    const passedVeri: VerificationResult[] = [
      {
        id: 'v_pass',
        verifier_role: 'qa',
        passed: true,
        summary: 'All 18 unit and boundary tests passed cleanly',
        executed_at: '2026-09-29T10:10:00Z',
      },
    ]

    const { unmount } = render(
      <CompanyFlowCanvas
        activeTask={null}
        runs={[]}
        verifications={passedVeri}
      />
    )

    const qaNode = screen.getByTestId('flow-node-qa')
    expect(qaNode).toHaveClass('verified')
    expect(screen.getByText('CRITERIA PASSED')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-result')).toHaveClass('verified')
    expect(screen.getByText('Deliverable Shipped')).toBeInTheDocument()

    unmount()

    // Test with Failed verification
    const failedVeri: VerificationResult[] = [
      {
        id: 'v_fail',
        verifier_role: 'qa',
        passed: false,
        summary: 'Exit code 2: missing dependency in verification step',
        executed_at: '2026-09-29T10:15:00Z',
      },
    ]

    render(
      <CompanyFlowCanvas
        activeTask={null}
        runs={[]}
        verifications={failedVeri}
      />
    )

    const failedQaNode = screen.getByTestId('flow-node-qa')
    expect(failedQaNode).toHaveClass('failed')
    expect(screen.getByText('REMEDIATION NEEDED')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-result')).toHaveClass('failed')
    expect(screen.getByText('Verification Issue')).toBeInTheDocument()
  })

  it('6. Result state is rendered from real data', () => {
    const mockRun: TaskRun = {
      id: 'run_99',
      task_id: 'task_01',
      attempt_number: 2,
      status: 'SUCCESS',
      started_at: '2026-09-29T10:00:00Z',
      finished_at: '2026-09-29T10:02:00Z',
      verifications: [],
      artifacts: [
        {
          id: 'art_1',
          name: 'dist_bundle.js',
          artifact_type: 'BUNDLE',
          path: 'dist/bundle.js',
          durable: true,
          created_at: '2026-09-29T10:02:00Z',
        },
      ],
    }

    render(
      <CompanyFlowCanvas
        activeTask={null}
        runs={[mockRun]}
        verifications={[{ id: 'v1', verifier_role: 'qa', passed: true, summary: 'OK', executed_at: '2026-09-29T10:03:00Z' }]}
      />
    )

    expect(screen.getByText('Run #2 Artifacts')).toBeInTheDocument()
    expect(screen.getByText('Validated Production Ready')).toBeInTheDocument()
  })

  it('7. React Flow dynamically adapts nodes to multi-specialist task subsets', () => {
    // Multi-specialist task: UX and Developer
    const designDevTask: Task = {
      id: 'task_design_dev',
      project_id: 'proj_01',
      title: 'Design and Build Onboarding Flow',
      goal: 'Interactive tutorial',
      status: 'IN_PROGRESS',
      required_roles: ['ux', 'developer'],
      constraints: [],
      runs: [],
      created_at: '2026-09-29T10:00:00Z',
      updated_at: '2026-09-29T10:05:00Z',
    }

    render(
      <CompanyFlowCanvas
        activeTask={designDevTask}
        runs={[]}
        verifications={[]}
      />
    )

    // Must render both specialists in the flow
    expect(screen.getByText('Ux Specialist')).toBeInTheDocument()
    expect(screen.getByText('Developer Specialist')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-founder')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-ceo')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-task')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-deliverable')).toBeInTheDocument()
  })

  it('8. No fake or hardcoded employee/task state is introduced on standby', () => {
    // When no active task exists, canvas truthfully indicates Standby
    render(
      <CompanyFlowCanvas
        activeTask={null}
        runs={[]}
        verifications={[]}
      />
    )

    expect(screen.getByText('No Active Task')).toBeInTheDocument()
    expect(screen.getByText('All systems standing by')).toBeInTheDocument()
    expect(screen.getByText('Pending Execution')).toBeInTheDocument()
  })
})
