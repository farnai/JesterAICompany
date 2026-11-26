import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { api, ApiError } from '../api/client'

describe('Stage 0A Security & Frontend Compatibility', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    document.head.querySelectorAll('meta[name="jester-csrf-token"]').forEach((el) => el.remove())
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.head.querySelectorAll('meta[name="jester-csrf-token"]').forEach((el) => el.remove())
  })

  it('sends credentials: same-origin and dynamically reads CSRF token from meta tag', async () => {
    const meta = document.createElement('meta')
    meta.setAttribute('name', 'jester-csrf-token')
    meta.setAttribute('content', 'ephemeral-runtime-csrf-12345')
    document.head.appendChild(meta)

    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ id: 'proj-1', name: 'Proj 1' }),
    } as Response)

    await api.createProject({ project_id: 'proj-1', name: 'Proj 1' })

    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/projects',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          'X-Jester-CSRF-Token': 'ephemeral-runtime-csrf-12345',
        }),
      })
    )
  })

  it('does not transmit verify_cmd over HTTP in executeTask or retryTask', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ id: 'run_1', status: 'SUCCESS' }),
    } as Response)

    await api.executeTask('task_1', 'echo should_not_be_sent', true)
    await api.retryTask('task_1', 'echo should_not_be_sent', true)

    expect(fetchSpy).toHaveBeenCalledTimes(2)
    for (const call of fetchSpy.mock.calls) {
      const init = call[1] as RequestInit
      const parsedBody = JSON.parse(String(init.body))
      expect(parsedBody).not.toHaveProperty('verify_cmd')
      expect(init.credentials).toBe('same-origin')
    }
  })

  it('surfaces fail-closed 403 ApiError on unverified approve/apply', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValueOnce({
      ok: false,
      status: 403,
      statusText: 'Forbidden',
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({
        error: 'Protected approval is blocked (fail-closed, DEF-004).',
        code: 'UNVERIFIED_PROTECTED_OPERATION',
      }),
    } as Response)

    await expect(api.approveCompanyRun('crun_1')).rejects.toThrow(ApiError)
  })

  it('contains zero hardcoded auth or CSRF secrets in frontend source files', () => {
    const clientSrc = fs.readFileSync(path.resolve(__dirname, '../api/client.ts'), 'utf-8')
    const indexHtml = fs.readFileSync(path.resolve(__dirname, '../../index.html'), 'utf-8')

    expect(clientSrc).not.toMatch(/Bearer\s+[A-Za-z0-9_\-]{12,}/)
    expect(clientSrc).not.toMatch(/X-Jester-CSRF-Token['"]\s*:\s*['"][A-Za-z0-9_\-]{8,}['"]/)
    expect(indexHtml).not.toContain('jester-csrf-token')
  })
})
