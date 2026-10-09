import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
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
    name: 'Developer',
    role: 'developer',
    title: 'Senior Developer',
    responsibilities: 'Code implementation',
    tools: [],
    status: 'ACTIVE',
  },
]

describe('STEP 23B.4 Execution Observability UI Components', () => {
  it('renders Execution Metrics card with total elapsed time, model calls, and workforce counts', () => {
    const mockRun: CompanyRun = {
      run_id: 'crun_obs_1',
      state: 'COMPLETED',
      project_id: 'prj_jester',
      created_at: new Date(Date.now() - 15000).toISOString(),
      completed_at: new Date().toISOString(),
      selected_agents: ['developer', 'qa'],
      skipped_agents: ['product', 'research', 'ux', 'marketing'],
      selection_reasoning: 'Direct developer bug fix with engineering QA verification.',
      ceo_invocation_count: 1,
      specialist_invocation_count: 2,
      execution_telemetry: {
        run_id: 'crun_obs_1',
        started_at: new Date(Date.now() - 15000).toISOString(),
        completed_at: new Date().toISOString(),
        duration_seconds: 14.82,
        status: 'COMPLETED',
        total_model_invocations: 3,
        total_model_latency_seconds: 12.45,
        total_tokens: null,
        input_tokens: null,
        output_tokens: null,
        estimated_cost_usd: null,
        cost_status: 'UNAVAILABLE',
        total_errors: 0,
        total_retries: 1,
        planned_specialists: ['developer', 'qa'],
        executed_specialists: ['developer', 'qa'],
        specialist_count_planned: 2,
        specialist_count_executed: 2,
        team_escalation_count: 0,
        bottleneck_stage: {
          role: 'developer',
          phase: 'mutation',
          work_item_id: 'wi_dev_1',
          duration_seconds: 9.35,
          reason: "Specialist 'developer' had highest measured duration (9.35s)",
        },
        specialist_metrics: [
          {
            execution_id: 'exec_ceo_1',
            role: 'ceo',
            phase: 'planning',
            started_at: new Date(Date.now() - 15000).toISOString(),
            completed_at: new Date(Date.now() - 14000).toISOString(),
            duration_seconds: 1.05,
            status: 'SUCCESS',
            model_invocation_count: 1,
            error_count: 0,
            retry_count: 0,
            is_measured: true,
          },
          {
            execution_id: 'exec_dev_1',
            role: 'developer',
            phase: 'mutation',
            started_at: new Date(Date.now() - 14000).toISOString(),
            completed_at: new Date(Date.now() - 4650).toISOString(),
            duration_seconds: 9.35,
            status: 'SUCCESS',
            model_invocation_count: 1,
            error_count: 0,
            retry_count: 1,
            is_measured: true,
          },
        ],
        measured_fields: ['duration_seconds', 'total_model_invocations'],
        unavailable_fields: ['total_tokens', 'estimated_cost_usd'],
      },
    }

    render(<CompanyFloor employees={mockEmployees} run={mockRun} />)

    expect(screen.getByTestId('execution-metrics-section')).toBeInTheDocument()
    expect(screen.getByTestId('metric-total-duration')).toHaveTextContent('14.82s')
    expect(screen.getByTestId('metric-model-calls')).toHaveTextContent('3')
    expect(screen.getByTestId('metric-token-usage')).toHaveTextContent('Unavailable')
    expect(screen.getByTestId('metric-workforce-count')).toHaveTextContent('2 / 2')
    expect(screen.getByTestId('metric-bottleneck-banner')).toHaveTextContent(/Bottleneck Stage:\s*developer/i)
  })

  it('handles runs with missing or legacy telemetry gracefully', () => {
    const legacyRun: CompanyRun = {
      run_id: 'crun_legacy_1',
      state: 'RUNNING',
      project_id: 'prj_jester',
      created_at: new Date().toISOString(),
      selected_agents: ['research'],
      skipped_agents: ['developer', 'product', 'ux'],
      selection_reasoning: 'Legacy run without telemetry object.',
      ceo_invocation_count: 1,
      specialist_invocation_count: 0,
      execution_telemetry: null,
    }

    render(<CompanyFloor employees={mockEmployees} run={legacyRun} />)

    expect(screen.getByTestId('execution-metrics-section')).toBeInTheDocument()
    expect(screen.getByTestId('metric-token-usage')).toHaveTextContent('Unavailable')
  })
})
