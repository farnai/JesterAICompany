import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { FounderSuite } from '../components/FounderSuite'
import { CEOStrategyDesk } from '../components/CEOStrategyDesk'
import { WorkstationGrid } from '../components/WorkstationGrid'
import type { CompanyOverview, Employee } from '../types/company'

describe('STEP 3: Company World UI in React', () => {
  it('renders FounderSuite with metrics and health', () => {
    const mockOverview: CompanyOverview = {
      company_name: 'Jester AI Company',
      status: 'OPERATIONAL',
      health: 'HEALTHY',
      completed_task_count: 3,
      qa_passed_count: 3,
    }

    render(
      <FounderSuite
        overview={mockOverview}
        activeWorkersCount={2}
        totalDeliverables={3}
      />
    )

    expect(screen.getByTestId('founder-suite')).toBeInTheDocument()
    expect(screen.getByText(/Founder & Owner Suite/i)).toBeInTheDocument()
    expect(screen.getByText('Jester AI Company')).toBeInTheDocument()
    expect(screen.getByText('HEALTHY')).toBeInTheDocument()
    expect(screen.getByTestId('portrait-owner')).toBeInTheDocument()
  })

  it('renders CEOStrategyDesk and triggers talk to CEO', () => {
    const onOpenChat = vi.fn()

    render(
      <CEOStrategyDesk
        onOpenChat={onOpenChat}
        activeTaskTitle="Restaurant Website"
      />
    )

    expect(screen.getByTestId('ceo-strategy-desk')).toBeInTheDocument()
    expect(screen.getByText(/Restaurant Website/i)).toBeInTheDocument()
    expect(screen.getByTestId('portrait-ceo')).toBeInTheDocument()

    const chatBtn = screen.getByTestId('ceo-chat-btn')
    fireEvent.click(chatBtn)
    expect(onOpenChat).toHaveBeenCalled()
  })

  it('renders WorkstationGrid with employee workstations and click handlers', () => {
    const onSelect = vi.fn()
    const mockEmployees: Employee[] = [
      { id: '1', name: 'Developer', role: 'developer', status: 'ACTIVE' },
      { id: '2', name: 'QA Engineer', role: 'qa_engineer', status: 'ACTIVE' },
    ]

    render(
      <WorkstationGrid
        employees={mockEmployees}
        onSelectEmployee={onSelect}
      />
    )

    expect(screen.getByTestId('workstation-grid')).toBeInTheDocument()
    expect(screen.getByTestId('station-developer')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('station-developer'))
    expect(onSelect).toHaveBeenCalledWith(mockEmployees[0])
  })
})
