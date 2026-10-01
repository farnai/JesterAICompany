import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CompanyFlowCanvas } from '../components/CompanyFlowCanvas'
import type { Task, VerificationResult } from '../types/company'

describe('STEP 4: React Flow Canvas Integration', () => {
  it('renders React Flow canvas container', () => {
    const mockTask: Task = {
      id: 'task_1',
      project_id: 'proj_1',
      title: 'Build Restaurant Platform',
      goal: 'Deliver clean UI',
      status: 'IN_PROGRESS',
    }

    render(
      <CompanyFlowCanvas
        activeTask={mockTask}
        runs={[]}
        verifications={[]}
      />
    )

    expect(screen.getByTestId('flow-canvas-container')).toBeInTheDocument()
  })

  it('renders custom nodes including Founder, CEO, Task, Worker, Deliverable, and QA', () => {
    const mockTask: Task = {
      id: 'task_1',
      project_id: 'proj_1',
      title: 'Build Restaurant Platform',
      goal: 'Deliver clean UI',
      status: 'IN_PROGRESS',
    }

    const mockVerifications: VerificationResult[] = [
      {
        id: 'v_1',
        verifier_role: 'qa_engineer',
        passed: true,
        summary: 'All 12 acceptance tests passed',
      },
    ]

    render(
      <CompanyFlowCanvas
        activeTask={mockTask}
        runs={[]}
        verifications={mockVerifications}
        onSelectNode={vi.fn()}
      />
    )

    expect(screen.getByTestId('flow-node-founder')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-ceo')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-task')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-worker')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-deliverable')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-qa')).toBeInTheDocument()
    expect(screen.getByTestId('flow-node-result')).toBeInTheDocument()
  })

  it('adapts QA node to failed state when verification fails', () => {
    const mockFailedVerifications: VerificationResult[] = [
      {
        id: 'v_fail',
        verifier_role: 'qa_engineer',
        passed: false,
        summary: 'Lint and test assertion failed',
      },
    ]

    render(
      <CompanyFlowCanvas
        activeTask={null}
        runs={[]}
        verifications={mockFailedVerifications}
      />
    )

    const qaNode = screen.getByTestId('flow-node-qa')
    expect(qaNode).toHaveClass('failed')
    expect(screen.getByText(/REMEDIATION NEEDED/i)).toBeInTheDocument()
  })
})
