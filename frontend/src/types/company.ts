// =============================================================================
// JESTER AI COMPANY — DOMAIN MODELS
// Direct TypeScript representations of CompanyService / core.py entities
// Single Source of Truth: Backend State
// =============================================================================

export type RoleType =
  | 'owner'
  | 'ceo'
  | 'developer'
  | 'qa_engineer'
  | 'researcher'
  | 'product_manager'
  | 'designer'
  | 'marketing_specialist'
  | string

export interface Employee {
  id: string
  role: string
  title: string
  responsibilities: string
  tools: string[]
  status: 'ACTIVE' | 'PLANNED' | 'STANDBY' | string
  // Optional client-derived / legacy compatibility fields
  name?: string
  workstation?: string
  dialogue?: string
  specialty?: string
  deliverables_count?: number
  current_task_id?: string | null
}

export interface Artifact {
  id: string
  name: string
  artifact_type: string
  path: string
  durable: boolean
  created_at: string
  task_id?: string
  run_id?: string
  type?: string
  description?: string
}

export interface VerificationResult {
  id: string
  verifier_role: string
  passed: boolean
  summary: string
  details?: Record<string, any>
  executed_at: string
  run_id?: string
  task_id?: string
}

export interface TaskRun {
  id: string
  task_id: string
  attempt_number?: number
  run_number?: number
  status: 'INITIALIZING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'PENDING' | 'IN_PROGRESS' | string
  started_at: string
  finished_at?: string
  exit_code?: number
  stdout_preview?: string
  stderr_preview?: string
  verifications: VerificationResult[]
  artifacts: Artifact[]
  // Joined context fields from list_all_runs()
  project_id?: string
  project_name?: string
  task_title?: string
  task_goal?: string
  has_passed_verification?: boolean
  // Optional single verification reference
  verification?: VerificationResult | null
}

export interface TaskResult {
  status: string
  total_runs: number
  last_run_id?: string
  summary?: string
}

export interface Task {
  id: string
  project_id: string
  title: string
  goal: string
  status: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED' | 'BLOCKED' | 'PLANNED' | string
  assigned_to?: string | null
  constraints: string[]
  required_roles: string[]
  runs: TaskRun[]
  result?: TaskResult | null
  created_at: string
  updated_at: string
}

export interface Project {
  id: string
  name: string
  root_path?: string
  tech_stack: string[]
  conventions?: Record<string, any>
  status?: string
  created_at?: string
  tasks: Record<string, Task> | Task[]
}

export interface CompanyInfo {
  id: string
  name: string
  purpose: string
  health: string
  status: string
}

export interface CompanyCounts {
  total_employees: number
  active_employees: number
  total_projects: number
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
  in_progress_tasks: number
  pending_tasks: number
  total_runs: number
  successful_runs: number
  failed_runs: number
  total_verifications: number
  passed_verifications: number
  failed_verifications: number
}

export interface CompanyOverview {
  company: CompanyInfo
  counts: CompanyCounts
  recent_runs: TaskRun[]
  timestamp: string
  // Legacy root-level accessors for fallback compatibility
  company_name?: string
  status?: string
  health?: string
  completed_task_count?: number
  qa_passed_count?: number
  metrics?: Record<string, any>
}

export interface Company {
  id: string
  name: string
  purpose: string
  projects: Record<string, Project>
  employees: Record<string, Employee>
  messages: ChatMessage[]
}

export interface ChatMessage {
  id: string
  sender_role: string
  sender_name: string
  content: string
  timestamp: string
  task_id?: string | null
  project_id?: string | null
  meta?: Record<string, any>
}

export interface ChatResponse {
  user_message: ChatMessage
  reply: ChatMessage
  messages: ChatMessage[]
}

// =============================================================================
// UI STATE (Separated from backend domain models)
// =============================================================================

export type ViewMode = 'flow' | 'studio'

export interface UIState {
  activeView: ViewMode
  isChatOpen: boolean
  selectedEmployee: Employee | null
  selectedTask: Task | null
  remediatingTask: Task | null
}
