import type {
  CompanyOverview,
  Employee,
  Project,
  Task,
  TaskRun,
  VerificationResult,
  Artifact,
  ChatMessage,
  ChatResponse,
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
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {}),
    },
    ...options,
  })

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
}

export const api = {
  // 1. Health & Overview
  getHealth: () => request<{ status: string; timestamp: string }>('/health'),
  getOverview: () => request<CompanyOverview>('/overview'),
  getCompany: () => request<any>('/company'),

  // 2. Agents / Employees
  getAgents: () => request<Employee[]>('/agents'),
  getAgent: (agentId: string) => request<Employee>(`/agents/${agentId}`),

  // 3. Projects
  getProjects: () => request<Project[]>('/projects'),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),
  createProject: (data: { project_id: string; name?: string; tech_stack?: string[] }) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 4. Tasks
  getTasks: (projectId?: string) => {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
    return request<Task[]>(`/tasks${query}`)
  },
  getTask: (taskId: string) => request<Task>(`/tasks/${taskId}`),
  createTask: (data: { project_id: string; title: string; goal?: string; constraints?: string[]; required_roles?: string[] }) =>
    request<Task>('/tasks', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 5. Execution & Remediation
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

  // 6. Runs & Verifications
  getRuns: () => request<TaskRun[]>('/runs'),
  getRun: (runId: string) => request<TaskRun>(`/runs/${runId}`),
  getVerifications: () => request<VerificationResult[]>('/verifications'),

  // 7. Artifacts
  getArtifacts: () => request<Artifact[]>('/artifacts'),
  getArtifactContent: (path: string, runId?: string) => {
    let url = `/artifacts/content?path=${encodeURIComponent(path)}`
    if (runId) url += `&run_id=${encodeURIComponent(runId)}`
    return request<string>(url)
  },

  // 8. Company Chat
  getChatMessages: (limit: number = 50) =>
    request<{ messages: ChatMessage[] }>(`/chat?limit=${limit}`),
  sendChatMessage: (content: string, senderRole: string = 'owner', projectId?: string, taskId?: string) =>
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
