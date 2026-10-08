import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { FounderClarificationCard } from '../components/FounderClarificationCard'
import { CompanyFloor } from '../components/CompanyFloor'
import type { CompanyRun, Employee } from '../types/company'

const mockEmployees: Employee[] = [
  {
    id: 'ceo',
    name: 'CEO',
    role: 'ceo',
    title: 'Chief Executive Officer',
    responsibilities: 'Company direction',
    tools: [],
    status: 'ACTIVE',
  },
  {
    id: 'backend_developer',
    name: 'Backend Dev',
    role: 'backend_developer',
    title: 'Backend Developer',
    responsibilities: 'Backend implementation',
    tools: [],
    status: 'STANDBY',
  },
]

describe('STEP 23B.2 Clarification UI Components', () => {
  it('renders FounderClarificationCard with question, reason, and context', () => {
    const mockRun: CompanyRun = {
      run_id: 'crun_test_1',
      state: 'WAITING_FOR_CLARIFICATION',
      project_id: 'prj_jester',
      created_at: new Date().toISOString(),
      selected_agents: [],
      skipped_agents: [],
      selection_reasoning: 'Paused for Founder clarification.',
      investigation_count: 1,
      max_investigations: 2,
      investigation_findings: ['Found auth routes in backend/app/routers/auth.py.'],
      clarification_request: {
        question: 'Should registration require email verification or permit instant login?',
        reason: 'Auth policy decisions cannot be assumed autonomously.',
        known_facts: ['Existing auth routers use OAuth2/JWT.'],
        assumptions: ['Email verification might require third-party SMTP setup.'],
      },
    }

    render(<FounderClarificationCard run={mockRun} />)

    expect(screen.getByTestId('founder-clarification-card')).toBeInTheDocument()
    expect(screen.getByTestId('clarification-question')).toHaveTextContent(
      'Should registration require email verification or permit instant login?'
    )
    expect(screen.getByTestId('clarification-reason')).toHaveTextContent(
      'Auth policy decisions cannot be assumed autonomously.'
    )
    expect(screen.getByText(/Found auth routes in backend\/app\/routers\/auth.py/)).toBeInTheDocument()
    expect(screen.getByText(/Investigation count: 1 \/ 2/)).toBeInTheDocument()
  })

  it('renders Georgian language question and handles Founder submission', async () => {
    const mockRun: CompanyRun = {
      run_id: 'crun_georgian_1',
      state: 'WAITING_FOR_CLARIFICATION',
      project_id: 'prj_jester',
      created_at: new Date().toISOString(),
      selected_agents: [],
      skipped_agents: [],
      selection_reasoning: 'გაურკვეველი მოთხოვნა',
      investigation_count: 2,
      max_investigations: 2,
      clarification_request: {
        question: 'რეგისტრაციის რა დეტალებია გასასწორებელი?',
        reason: 'კრიტიკული ბიზნეს ლოგიკა საჭიროებს დამფუძნებლის გადაწყვეტილებას.',
        known_facts: ['სისტემა იყენებს JWT ტოკენებს'],
      },
    }

    const onSubmit = vi.fn().mockResolvedValue(undefined)

    render(<FounderClarificationCard run={mockRun} onSubmitClarification={onSubmit} />)

    expect(screen.getByTestId('clarification-question')).toHaveTextContent(
      'რეგისტრაციის რა დეტალებია გასასწორებელი?'
    )
    expect(screen.getByTestId('clarification-reason')).toHaveTextContent(
      'კრიტიკული ბიზნეს ლოგიკა საჭიროებს დამფუძნებლის გადაწყვეტილებას.'
    )

    const input = screen.getByTestId('clarification-input')
    const submitBtn = screen.getByTestId('clarification-submit-btn')

    // Initial state: empty input means disabled or no-op
    expect(submitBtn).toBeDisabled()

    // Type Founder response in Georgian
    fireEvent.change(input, {
      target: { value: 'გაასწორე პაროლის ვალიდაცია მინიმუმ 8 სიმბოლოზე' },
    })

    expect(submitBtn).not.toBeDisabled()
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith('გაასწორე პაროლის ვალიდაცია მინიმუმ 8 სიმბოლოზე')
    })
  })

  it('renders clarification card in CompanyFloor when run is WAITING_FOR_CLARIFICATION', () => {
    const mockRun: CompanyRun = {
      run_id: 'crun_floor_test',
      state: 'WAITING_FOR_CLARIFICATION',
      project_id: 'prj_jester',
      created_at: new Date().toISOString(),
      selected_agents: ['ceo'],
      skipped_agents: [],
      selection_reasoning: 'Awaiting guidance.',
      clarification_request: {
        question: 'Confirm database migration strategy.',
        reason: 'Schema changes require Founder approval.',
      },
    }

    render(
      <CompanyFloor
        run={mockRun}
        employees={mockEmployees}
        projectName="Jester"
      />
    )

    expect(screen.getByTestId('founder-clarification-card')).toBeInTheDocument()
    expect(screen.getByTestId('clarification-question')).toHaveTextContent(
      'Confirm database migration strategy.'
    )
  })

  it('does NOT render clarification card in CompanyFloor when run is RUNNING without request', () => {
    const mockRun: CompanyRun = {
      run_id: 'crun_running_test',
      state: 'RUNNING',
      project_id: 'prj_jester',
      created_at: new Date().toISOString(),
      selected_agents: ['ceo', 'backend_developer'],
      skipped_agents: [],
      selection_reasoning: 'Executing sprint.',
    }

    render(
      <CompanyFloor
        run={mockRun}
        employees={mockEmployees}
        projectName="Jester"
      />
    )

    expect(screen.queryByTestId('founder-clarification-card')).toBeNull()
  })
})
