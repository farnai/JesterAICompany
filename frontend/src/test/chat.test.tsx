import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { CompanyChat } from '../components/CompanyChat'
import type { ChatMessage } from '../types/company'

describe('STEP 5: Company Chat React Integration', () => {
  const mockMessages: ChatMessage[] = [
    {
      id: 'msg_1',
      sender_role: 'ceo',
      sender_name: 'CEO Agent',
      content: 'Welcome Founder. I am ready.',
      timestamp: '2026-09-29T12:00:00Z',
    },
    {
      id: 'msg_2',
      sender_role: 'owner',
      sender_name: 'You (Founder)',
      content: 'I need a landing page.',
      timestamp: '2026-09-29T12:01:00Z',
    },
  ]

  it('renders closed launcher with message count when isOpen is false', () => {
    const onToggle = vi.fn()
    render(
      <CompanyChat
        isOpen={false}
        onClose={vi.fn()}
        onToggle={onToggle}
        messages={mockMessages}
        onSendMessage={vi.fn()}
      />
    )

    expect(screen.getByTestId('chat-launcher-btn')).toBeInTheDocument()
    expect(screen.getByTestId('chat-count-badge')).toHaveTextContent('2')

    fireEvent.click(screen.getByTestId('chat-launcher-btn'))
    expect(onToggle).toHaveBeenCalled()
  })

  it('renders open drawer with message thread and suggestions when isOpen is true', () => {
    render(
      <CompanyChat
        isOpen={true}
        onClose={vi.fn()}
        onToggle={vi.fn()}
        messages={mockMessages}
        onSendMessage={vi.fn()}
      />
    )

    expect(screen.getByTestId('company-chat-drawer')).toBeInTheDocument()
    expect(screen.getByText('Welcome Founder. I am ready.')).toBeInTheDocument()
    expect(screen.getByText('I need a landing page.')).toBeInTheDocument()
    expect(screen.getByTestId('suggestion-chip-0')).toBeInTheDocument()
  })

  it('sends message when clicking Send button or suggestion chip', async () => {
    const onSend = vi.fn().mockResolvedValue({})
    render(
      <CompanyChat
        isOpen={true}
        onClose={vi.fn()}
        onToggle={vi.fn()}
        messages={mockMessages}
        onSendMessage={onSend}
      />
    )

    const input = screen.getByTestId('chat-input-field')
    fireEvent.change(input, { target: { value: 'Status update please' } })

    const sendBtn = screen.getByTestId('chat-send-btn')
    fireEvent.click(sendBtn)

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith('Status update please')
    })

    // Click suggestion chip
    const chip = screen.getByTestId('suggestion-chip-0')
    fireEvent.click(chip)

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith('What is our company status?')
    })
  })

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn()
    render(
      <CompanyChat
        isOpen={true}
        onClose={onClose}
        onToggle={vi.fn()}
        messages={mockMessages}
        onSendMessage={vi.fn()}
      />
    )

    const closeBtn = screen.getByTestId('chat-close-btn')
    fireEvent.click(closeBtn)
    expect(onClose).toHaveBeenCalled()
  })
})
