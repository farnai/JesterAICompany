import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, renderHook, screen, waitFor, act } from '@testing-library/react'
import App from '../App'
import { api } from '../api/client'
import { useCompanyState } from '../hooks/useCompanyState'
import type { CompanyOverview, Employee, Task, TaskRun, VerificationResult, ChatMessage } from '../types/company'

describe('27-E.2.1: Real Company State Foundation & Data Flow', () => {
  const initialOverview: CompanyOverview = {
    company: {
      id: 'co_test',
      name: 'Jester AI Company',
      purpose: 'Autonomous workforce demonstration',
      health: 'OPERATIONAL',
      status: 'OPERATIONAL',
    },
    counts: {
      total_employees: 3,
      active_employees: 2,
      total_projects: 1,
      total_tasks: 1,
      completed_tasks: 0,
      failed_tasks: 0,
      in_progress_tasks: 1,
      pending_tasks: 0,
      total_runs: 1,
      successful_runs: 0,
      failed_runs: 0,
      total_verifications: 1,
      passed_verifications: 1,
      failed_verifications: 0,
    },
    recent_runs: [],
    timestamp: '2026-09-29T12:00:00Z',
  }

  const initialEmployees: Employee[] = [
    {
      id: 'emp_dev',
      role: 'developer',
      title: 'Lead Systems Developer',
      responsibilities: 'Full-stack engineering & runtime testing',
      tools: ['code_search', 'run_tests'],
      status: 'ACTIVE',
    },
    {
      id: 'emp_qa',
      role: 'qa_engineer',
      title: 'Quality Verification Engineer',
      responsibilities: 'Independent criteria verification',
      tools: ['verify_deliverable'],
      status: 'ACTIVE',
    },
    {
      id: 'emp_pm',
      role: 'product_manager',
      title: 'Product Architect',
      responsibilities: 'Spec breakdown & acceptance standards',
      tools: ['roadmap_spec'],
      status: 'STANDBY',
    },
  ]

  const initialTasks: Task[] = [
    {
      id: 'task_alpha',
      project_id: 'proj_main',
      title: 'Build Autonomous Company UI',
      goal: 'Construct daylight-themed Company World',
      status: 'IN_PROGRESS',
      assigned_to: 'developer',
      constraints: ['React', 'TypeScript'],
      required_roles: ['developer', 'qa_engineer'],
      runs: [],
      created_at: '2026-09-29T11:00:00Z',
      updated_at: '2026-09-29T11:30:00Z',
    },
  ]

  const initialRuns: TaskRun[] = [
    {
      id: 'run_alpha_1',
      task_id: 'task_alpha',
      attempt_number: 1,
      status: 'RUNNING',
      started_at: '2026-09-29T11:30:00Z',
      verifications: [],
      artifacts: [],
    },
  ]

  const initialVerifications: VerificationResult[] = [
    {
      id: 'veri_1',
      verifier_role: 'qa_engineer',
      passed: true,
      summary: 'All criteria passed cleanly.',
      executed_at: '2026-09-29T11:35:00Z',
    },
  ]

  const initialChat: ChatMessage[] = [
    {
      id: 'msg_greet',
      sender_role: 'ceo',
      sender_name: 'CEO Agent',
      content: 'Welcome Founder. All systems operational.',
      timestamp: '2026-09-29T11:00:00Z',
    },
  ]

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'getOverview').mockResolvedValue(initialOverview)
    vi.spyOn(api, 'getAgents').mockResolvedValue(initialEmployees)
    vi.spyOn(api, 'getTasks').mockResolvedValue(initialTasks)
    vi.spyOn(api, 'getRuns').mockResolvedValue(initialRuns)
    vi.spyOn(api, 'getVerifications').mockResolvedValue(initialVerifications)
    vi.spyOn(api, 'getChatMessages').mockResolvedValue({ messages: initialChat })
    vi.spyOn(api, 'getProjects').mockResolvedValue([])
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('1. Company data loads directly into state and UI', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('JESTER AI COMPANY')).toBeInTheDocument()
      expect(screen.getByText(/OPERATIONAL \[OK\]/i)).toBeInTheDocument()
    })
  })

  it('2. Employees load with real roles, titles, and active statuses', async () => {
    render(<App />)

    // Switch to studio view to view stations
    const studioBtn = screen.getByTestId('toggle-studio-btn')
    act(() => {
      studioBtn.click()
    })

    await waitFor(() => {
      expect(screen.getByTestId('station-developer')).toBeInTheDocument()
      expect(screen.getAllByText('Lead Systems Developer').length).toBeGreaterThan(0)
      expect(screen.getAllByText('Quality Verification Engineer').length).toBeGreaterThan(0)
      expect(screen.getAllByText('Product Architect').length).toBeGreaterThan(0)
    })
  })

  it('3. Tasks load into pipeline and task directory', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('task-row-task_alpha')).toBeInTheDocument()
      expect(screen.getByText('Build Autonomous Company UI')).toBeInTheDocument()
    })
  })

  it('4. Chat messages load into Company Chat', async () => {
    render(<App />)

    const launcher = screen.getByTestId('chat-launcher-btn')
    act(() => {
      launcher.click()
    })

    await waitFor(() => {
      expect(screen.getByText('Welcome Founder. All systems operational.')).toBeInTheDocument()
    })
  })

  it('5. State updates when API data changes', async () => {
    const { result } = renderHook(() => useCompanyState(0))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
      expect(result.current.activeTask?.title).toBe('Build Autonomous Company UI')
      expect(result.current.completedTasksCount).toBe(0)
    })

    const updatedOverview: CompanyOverview = {
      ...initialOverview,
      counts: {
        ...initialOverview.counts,
        completed_tasks: 1,
        in_progress_tasks: 0,
      },
    }

    const updatedTasks: Task[] = [
      {
        ...initialTasks[0],
        status: 'COMPLETED',
      },
    ]

    vi.spyOn(api, 'getOverview').mockResolvedValue(updatedOverview)
    vi.spyOn(api, 'getTasks').mockResolvedValue(updatedTasks)

    await act(async () => {
      await result.current.refresh()
    })

    await waitFor(() => {
      expect(result.current.completedTasksCount).toBe(1)
      expect(result.current.tasks[0].status).toBe('COMPLETED')
    })
  })

  it('6. Components receive updated state consistently across World and Flow', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('flow-canvas-container')).toBeInTheDocument()
      expect(screen.getByTestId('flow-node-task')).toBeInTheDocument()
      expect(screen.getByText('Build Autonomous Company UI')).toBeInTheDocument()
    })
  })
})
