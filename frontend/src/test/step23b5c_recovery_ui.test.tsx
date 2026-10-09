import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'
import { CompanyFloor } from '../components/CompanyFloor'
import type { CompanyRun } from '../types/company'

describe('STEP 23B.5-C Recovery UI in Control Center', () => {
  it('renders compact recovery status banner and founder action badge', () => {
    const mockRun: CompanyRun = {
      run_id: 'crun_recov123',
      state: 'RUNNING',
      project_id: 'proj_test',
      selected_agents: ['research'],
      skipped_agents: ['product', 'ux', 'marketing', 'developer', 'qa'],
      selection_reasoning: 'Minimal workforce',
      created_at: new Date().toISOString(),
      recovery_summary: {
        current_attempt: 2,
        max_retries: 1,
        failure_category: 'TRANSIENT_RUNTIME',
        recovery_decision: 'RETRY',
        preserved_artifacts: ['research_brief.md'],
        remaining_work: ['work_item_2'],
        founder_action_required: false,
        explanation: 'Transient runtime error detected. Scheduling bounded retry.',
      },
    }

    render(
      <CompanyFloor
        employees={[]}
        run={mockRun}
      />
    )

    const banner = screen.getByTestId('recovery-status-banner')
    expect(banner).toBeDefined()
    expect(banner.textContent).toContain('Attempt 2/2')
    expect(banner.textContent).toContain('TRANSIENT_RUNTIME')
    expect(banner.textContent).toContain('RETRY')
    expect(banner.textContent).toContain('Preserved Artifacts: 1')
    expect(banner.textContent).toContain('Remaining Work: 1')
  })

  it('renders founder action badge when founder intervention is required', () => {
    const mockRun: CompanyRun = {
      run_id: 'crun_founder_needed',
      state: 'WAITING_FOR_CLARIFICATION',
      project_id: 'proj_test',
      selected_agents: ['research'],
      skipped_agents: [],
      selection_reasoning: 'Clarification',
      created_at: new Date().toISOString(),
      clarification_request: {
        question: 'Please specify target database.',
      },
      recovery_summary: {
        current_attempt: 1,
        max_retries: 1,
        failure_category: 'AUTHENTICATION',
        recovery_decision: 'FAIL',
        preserved_artifacts: [],
        remaining_work: ['work_item_1'],
        founder_action_required: true,
        explanation: 'Authentication failed.',
      },
    }

    render(
      <CompanyFloor
        employees={[]}
        run={mockRun}
      />
    )

    const badge = screen.getByTestId('recovery-founder-action-badge')
    expect(badge).toBeDefined()
    expect(badge.textContent).toContain('Founder Action Required')
  })
})
