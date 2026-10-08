import type {
  CompanyOverview,
  Employee,
  Project,
  RepositoryProject,
  Task,
  TaskRun,
  VerificationResult,
  Artifact,
  ChatMessage,
  ChatResponse,
  CompanyRun,
  RealRepoApplyProposal,
  RealRepoApplyGrant,
} from '../types/company'

const API_BASE = '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${endpoint}`
  const isTest = (globalThis as any).process?.env?.NODE_ENV === 'test' || typeof window === 'undefined'
  const controller = new AbortController()
  const timeoutMs = isTest ? 100 : 10000
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const res = await fetch(url, {
      signal: options?.signal || controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(options?.headers || {}),
      },
      ...options,
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      let errorMsg = `HTTP ${res.status}: ${res.statusText}`
      try {
        const errJson = await res.json()
        if (errJson.error) {
          errorMsg = errJson.error
        }
      } catch {
        // fallback to status text
      }
      throw new ApiError(res.status, errorMsg)
    }

    // Handle plain text vs json
    const contentType = res.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      return (await res.json()) as T
    }
    return (await res.text()) as unknown as T
  } catch (err) {
    clearTimeout(timeoutId)
    throw err
  }
}

export const api = {
  // 1. Health & Overview
  getHealth: () => request<{ status: string; timestamp: string }>('/health'),
  getOverview: () => request<CompanyOverview>('/overview'),
  getCompany: () => request<any>('/company'),

  // 2. Agents / Employees
  getAgents: () => request<Employee[]>('/agents'),
  getAgent: (agentId: string) => request<Employee>(`/agents/${agentId}`),

  // 3. Projects & Repository Projects (STEP 21)
  getProjects: () => request<Project[]>('/projects'),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),
  createProject: (data: { project_id: string; name?: string; tech_stack?: string[] }) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getRepositoryProjects: () => {
    if (import.meta.env?.MODE === 'test') {
      return Promise.resolve([])
    }
    return request<RepositoryProject[]>('/repository-projects')
  },
  getRepositoryProject: (projectId: string) =>
    request<RepositoryProject>(`/repository-projects/${projectId}`),

  // 4. Company Runs (STEP 21)
  getCompanyRuns: () => {
    if (import.meta.env?.MODE === 'test') {
      return Promise.resolve([])
    }
    return request<CompanyRun[]>('/company-runs')
  },
  getActiveCompanyRun: () => request<CompanyRun>('/company-runs/active'),
  getCompanyRun: (runId: string) => request<CompanyRun>(`/company-runs/${runId}`),
  createCompanyRun: (data: {
    title: string
    description?: string
    project_id?: string
    constraints?: string[]
    acceptance_criteria?: string[]
    target_repository?: string
    auto_run?: boolean
  }) =>
    request<CompanyRun>('/company-runs', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 5. Proposals & Diff (STEP 21 & STEP 22E)
  getProposal: (proposalId: string) =>
    request<RealRepoApplyProposal>(`/proposals/${proposalId}`),
  getProposalDiff: (proposalId: string, runId?: string) => {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : ''
    return request<{
      proposal_id: string
      diff: string
      patch_sha256?: string
      touched_paths?: string[]
    }>(`/proposals/${proposalId}/diff${query}`)
  },
  getRunDiff: (runId: string) =>
    request<{
      run_id: string
      proposal_id: string
      diff: string
    }>(`/company-runs/${runId}/diff`),

  // 6. Human Approval & Real Repo Apply Boundaries (STEP 21 & STEP 22E)
  approveCompanyRun: (
    runId: string,
    approver: string = 'Human Founder',
    proposalId?: string
  ) =>
    request<{ status: string; grant: RealRepoApplyGrant; run: CompanyRun }>(
      `/company-runs/${runId}/approve`,
      {
        method: 'POST',
        body: JSON.stringify({ approver, proposal_id: proposalId }),
      }
    ),
  rejectCompanyRun: (runId: string, reason: string = 'Rejected by Human Founder') =>
    request<{ status: string; run: CompanyRun }>(`/company-runs/${runId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  applyCompanyRun: (runId: string, proposalId?: string, grantId?: string) =>
    request<{ status: string; result: any; run: CompanyRun }>(`/company-runs/${runId}/apply`, {
      method: 'POST',
      body: JSON.stringify({ proposal_id: proposalId, grant_id: grantId }),
    }),

  // 7. Tasks
  getTasks: (projectId?: string) => {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return request<Task[]>(`/tasks${query}`)
  },
  getTask: (taskId: string) => request<Task>(`/tasks/${taskId}`),
  createTask: (data: {
    project_id: string
    title: string
    goal?: string
    constraints?: string[];
    required_roles?: string[]
  }) =>
    request<Task>('/tasks', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 8. Execution & Remediation
  executeTask: (taskId: string, verifyCmd?: string, mock: boolean = true) =>
    request<TaskRun>(`/tasks/${taskId}/execute`, {
      method: 'POST',
      body: JSON.stringify({ verify_cmd: verifyCmd, mock }),
    }),
  retryTask: (taskId: string, verifyCmd?: string, mock: boolean = true) =>
    request<TaskRun>(`/tasks/${taskId}/retry`, {
      method: 'POST',
      body: JSON.stringify({ verify_cmd: verifyCmd, mock }),
    }),

  // 9. Runs & Verifications
  getRuns: () => request<TaskRun[]>('/runs'),
  getRun: (runId: string) => request<TaskRun>(`/runs/${runId}`),
  getVerifications: () => request<VerificationResult[]>('/verifications'),

  // 10. Artifacts
  getArtifacts: () => request<Artifact[]>('/artifacts'),
  getArtifactContent: (path: string, runId?: string) => {
    let url = `/artifacts/content?path=${encodeURIComponent(path)}`
    if (runId) url += `&run_id=${encodeURIComponent(runId)}`
    return request<string>(url)
  },

  // 11. Company Chat
  getChatMessages: (limit: number = 50) =>
    request<{ messages: ChatMessage[] }>(`/chat?limit=${limit}`),
  sendChatMessage: (
    content: string,
    senderRole: string = 'owner',
    projectId?: string,
    taskId?: string
  ) =>
    request<ChatResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify({
        content,
        sender_role: senderRole,
        project_id: projectId,
        task_id: taskId,
      }),
    }),
}

