import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api, ApiError } from '../api/client'

describe('STEP 2: Connect to Existing Backend API', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches overview successfully', async () => {
    const mockOverview = {
      company_name: 'Jester AI Company',
      status: 'OPERATIONAL',
      health: 'healthy',
      metrics: { total_projects: 1, active_tasks: 0, completed_tasks: 2 },
    }

    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => mockOverview,
    } as Response)

    const result = await api.getOverview()
    expect(result.company_name).toBe('Jester AI Company')
    expect(fetch).toHaveBeenCalledWith('/api/overview', expect.anything())
  })

  it('fetches chat messages successfully', async () => {
    const mockChat = {
      messages: [
        {
          id: 'msg_1',
          sender_role: 'ceo',
          sender_name: 'CEO Agent',
          content: 'Welcome Founder',
          timestamp: '2026-09-29T12:00:00Z',
        },
      ],
    }

    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => mockChat,
    } as Response)

    const res = await api.getChatMessages(50)
    expect(res.messages).toHaveLength(1)
    expect(res.messages[0].sender_role).toBe('ceo')
  })

  it('sends chat message and gets CEO reply', async () => {
    const mockResponse = {
      user_message: {
        id: 'msg_u1',
        sender_role: 'owner',
        sender_name: 'You (Founder)',
        content: 'Status check',
        timestamp: '2026-09-29T12:01:00Z',
      },
      reply: {
        id: 'msg_c1',
        sender_role: 'ceo',
        sender_name: 'CEO Agent',
        content: 'All systems operational',
        timestamp: '2026-09-29T12:01:01Z',
      },
      messages: [],
    }

    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => mockResponse,
    } as Response)

    const res = await api.sendChatMessage('Status check')
    expect(res.reply.content).toBe('All systems operational')
    expect(fetch).toHaveBeenCalledWith('/api/chat', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        content: 'Status check',
        sender_role: 'owner',
      }),
    }))
  })

  it('handles ApiError correctly on 400/500 responses', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 400,
      statusText: 'Bad Request',
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ error: 'Field content is required.' }),
    } as Response)

    await expect(api.sendChatMessage('')).rejects.toThrow(ApiError)
  })
})
