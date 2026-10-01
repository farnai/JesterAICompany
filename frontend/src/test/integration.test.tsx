import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import App from '../App'
import { api } from '../api/client'

describe('STEP 6 - 9: Real Company State, Motion, Interactions & Remediation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()

    // Mock API methods
    vi.spyOn(api, 'getOverview').mockResolvedValue({
      company_name: 'Jester AI Company',
      status: 'OPERATIONAL',
      health: 'HEALTHY',
      completed_task_count: 2,
      qa_passed_count: 2,
    })

    vi.spyOn(api, 'getAgents').mockResolvedValue([
      { id: '1', name: 'Developer', role: 'developer', status: 'ACTIVE' },
      { id: '2', name: 'QA Engineer', role: 'qa_engineer', status: 'ACTIVE' },
    ])

    vi.spyOn(api, 'getTasks').mockResolvedValue([
      {
        id: 'task-101',
        project_id: 'proj-1',
        title: 'Restaurant Booking Engine',
        goal: 'Complete reservation flow',
        status: 'IN_PROGRESS',
        assigned_to: 'developer',
      },
    ])

    vi.spyOn(api, 'getRuns').mockResolvedValue([
      {
        id: 'run-1',
        task_id: 'task-101',
        run_number: 1,
        status: 'SUCCESS',
        started_at: '2026-09-29T10:00:00Z',
        stdout_preview: 'Compiled 14 modules successfully.',
      },
    ])

    vi.spyOn(api, 'getVerifications').mockResolvedValue([
      {
        id: 'veri-1',
        verifier_role: 'qa_engineer',
        passed: false,
        summary: 'Acceptance test failed: reservation time picker overflow.',
      },
    ])

    vi.spyOn(api, 'getChatMessages').mockResolvedValue({
      messages: [
        {
          id: 'msg-1',
          sender_role: 'ceo',
          sender_name: 'CEO Agent',
          content: 'Standing by for missions, Founder.',
          timestamp: '2026-09-29T10:00:00Z',
        },
      ],
    })
  })

  it('STEP 6: Populates real company state into UI overview, tasks, and agents', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByText('Jester AI Company')).toBeInTheDocument()
      expect(screen.getAllByText(/Restaurant Booking Engine/i).length).toBeGreaterThan(0)
    })
  })

  it('STEP 7: Toggles between Pipeline Flow and Studio Floor views with motion', async () => {
    render(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('flow-canvas-container')).toBeInTheDocument()
    })

    const toggleStudioBtn = screen.getByTestId('toggle-studio-btn')
    fireEvent.click(toggleStudioBtn)

    await waitFor(() => {
      expect(screen.getByTestId('workstation-grid')).toBeInTheDocument()
    })

    const toggleFlowBtn = screen.getByTestId('toggle-flow-btn')
    fireEvent.click(toggleFlowBtn)

    await waitFor(() => {
      expect(screen.getByTestId('flow-canvas-container')).toBeInTheDocument()
    })
  })

  it('STEP 8: Opens Task Dossier Modal on task row click and allows execution', async () => {
    const mockExecute = vi.spyOn(api, 'executeTask').mockResolvedValue({
      id: 'run-new',
      task_id: 'task-101',
      run_number: 2,
      status: 'SUCCESS',
      started_at: '2026-09-29T10:05:00Z',
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('task-row-task-101')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('task-row-task-101'))

    expect(screen.getByTestId('task-dossier-modal')).toBeInTheDocument()
    expect(screen.getAllByText(/Restaurant Booking Engine/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/Compiled 14 modules successfully/i)).toBeInTheDocument()

    const execBtn = screen.getByTestId('task-execute-btn')
    fireEvent.click(execBtn)

    await waitFor(() => {
      expect(mockExecute).toHaveBeenCalledWith('task-101', undefined, true)
    })
  })

  it('STEP 9: Initiates QA Remediation Flow when verification fails', async () => {
    const mockRetry = vi.spyOn(api, 'retryTask').mockResolvedValue({
      id: 'run-retry',
      task_id: 'task-101',
      run_number: 2,
      status: 'SUCCESS',
      started_at: '2026-09-29T10:06:00Z',
    })

    const mockChat = vi.spyOn(api, 'sendChatMessage').mockResolvedValue({
      user_message: {
        id: 'msg-u',
        sender_role: 'owner',
        sender_name: 'You (Founder)',
        content: 'Fix',
        timestamp: '2026-09-29T10:06:00Z',
      },
      reply: {
        id: 'msg-r',
        sender_role: 'ceo',
        sender_name: 'CEO Agent',
        content: 'Fixing',
        timestamp: '2026-09-29T10:06:01Z',
      },
      messages: [],
    })

    render(<App />)

    // Switch to studio to see QA station remediation state
    const toggleStudioBtn = screen.getByTestId('toggle-studio-btn')
    fireEvent.click(toggleStudioBtn)

    await waitFor(() => {
      expect(screen.getByTestId('remediate-btn')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('remediate-btn'))

    expect(screen.getByTestId('qa-remediation-modal')).toBeInTheDocument()
    expect(screen.getAllByText(/reservation time picker overflow/i).length).toBeGreaterThan(0)

    const submitBtn = screen.getByTestId('submit-remediation-btn')
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(mockRetry).toHaveBeenCalledWith('task-101', undefined, true)
      expect(mockChat).toHaveBeenCalled()
    })
  })
})
