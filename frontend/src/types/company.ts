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

export type NavigationTab =
  | 'floor'
  | 'objective'
  | 'history'
  | 'approvals'
  | 'projects'
  | 'artifacts'
  | 'git'
  | 'settings'

export interface TargetRepositoryVerification {
  project_id: string
  repository_id?: string
  project_name?: string
  repository_root?: string
  target_root_path?: string
  target_branch?: string
  repository_head: string
  branch: string
  working_tree_state: string
  remote_url?: string
  is_valid: boolean
  is_git_repository?: boolean
  tracked_dirty_files?: string[]
  untracked_files?: string[]
  error_message?: string | null
  verified_at?: string
  details?: {
    tracked_changes_count: number
    untracked_files_count: number
    canonical_root: string
  }
}

export interface RepositoryProject {
  project_id: string
  name: string
  description?: string
  repository: {
    repository_id: string
    project_id?: string
    root_path: string
    target_branch: string
    expected_remote?: string | null
    allow_untracked?: boolean
    allowed_paths?: string[]
    prohibited_paths?: string[]
    max_files_per_apply?: number
    read_only_by_default?: boolean
    requires_founder_approval?: boolean
  }
  policy?: {
    read_allowed: string[]
    mutation_allowed: string[]
    denied: string[]
  }
  status?: string
  created_at?: string
  verification?: TargetRepositoryVerification
}

export interface CompanyObjective {
  id: string
  title: string
  description?: string
  constraints?: string[]
  acceptance_criteria?: string[]
  target_repository?: string
  project_id?: string
  created_at?: string
  created_by?: string
}

export interface WorkItem {
  work_item_id: string
  role: string
  objective: string
  depends_on: string[]
  expected_outputs: string[]
  priority: number
  state: 'PENDING' | 'READY' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'BLOCKED' | string
  refinement_count?: number
  task_id?: string
  run_id?: string
}

export interface CEOPlan {
  schema_version?: string
  plan_id: string
  objective_id: string
  version: number
  work_items: WorkItem[]
  completion_criteria: string[]
  constraints: string[]
  created_at: string
}

export interface ArtifactRef {
  artifact_id: string
  name: string
  type: string
  sha256: string
  path: string
  producer_role?: string
}

export interface EmployeeSummary {
  role: string
  task_id?: string
  run_id?: string
  status: string
  summary: string
  blockers?: string[]
  created_at?: string
  artifact_refs: ArtifactRef[]
}

export interface CompanyEvent {
  id?: string
  event_id?: string
  producer?: string
  summary?: string
  timestamp: string
  event_type: string
  company_run_id?: string
  work_item_id?: string | null
  role?: string | null
  task_id?: string | null
  artifact_refs?: any[]
  reason?: string
  details?: Record<string, any>
}

export interface RealRepoApplyProposal {
  schema_version?: string
  proposal_id: string
  company_run_id?: string
  target_root_path?: string
  target_repository_root?: string
  target_branch?: string
  target_head_hash?: string
  base_commit_hash?: string
  code_patch_artifact_id?: string
  code_patch_sha256?: string
  patch_sha256?: string
  patch_version?: number
  qa_report_artifact_id?: string
  qa_report_sha256?: string
  qa_execution_report_artifact_id?: string
  qa_execution_report_sha256?: string
  qa_verdict?: 'PASS' | 'FAIL' | 'BLOCKED' | 'REPAIRING' | string
  expected_changed_files?: string[]
  touched_paths?: string[]
  expected_diff_stat?: {
    files_changed: number
    insertions: number
    deletions: number
  }
  is_clean?: boolean
  created_at: string
  proposal_sha256?: string
  project_id?: string
  repository_id?: string | null
  patch_content?: string
  diff?: string
  status?: string
}

export interface RealRepoApplyGrant {
  schema_version?: string
  grant_id: string
  proposal_id: string
  company_run_id?: string
  proposal_sha256?: string
  target_root_path?: string
  target_repository_root?: string
  expected_head_hash?: string
  base_commit_hash?: string
  code_patch_artifact_id?: string
  code_patch_sha256?: string
  expected_patch_sha256?: string
  qa_execution_report_artifact_id?: string
  qa_execution_report_sha256?: string
  expected_changed_files?: string[]
  human_approval_id?: string
  approver?: string
  authorized_by?: string
  approved_at?: string
  authorized_at?: string
  authorized_file_budget?: number
  status: 'ISSUED' | 'AUTHORIZED' | 'CONSUMED' | 'EXPIRED' | 'REVOKED' | string
  validity_duration_seconds?: number
  project_id?: string
  repository_id?: string | null
}

export interface Step20CReceipt {
  status: string
  company_run_id: string
  proposal_id: string
  grant_id: string
  founder_auth_id: string
  stored_patch_sha256: string
  recomputed_patch_sha256: string
  target_repository: string
  target_branch: string
  head_before: string
  head_after: string
  targeted_test_command: string
  targeted_test_passed: number
  targeted_test_duration: string
  regression_command: string
  regression_passed: number
  regression_duration: string
  authorized_files: string[]
  actual_changed_files: string[]
}

export interface CompanyRun {
  run_id: string
  state:
    | 'CREATED'
    | 'PLANNING'
    | 'PLAN_READY'
    | 'RUNNING'
    | 'WAITING_FOR_HUMAN'
    | 'WAITING_FOR_CLARIFICATION'
    | 'READY_FOR_HUMAN_APPLY'
    | 'APPLYING'
    | 'COMPLETED'
    | 'BLOCKED'
    | 'FAILED'
    | string
  objective?: CompanyObjective | null
  project_id: string
  repository_id?: string
  target_branch?: string
  base_commit_hash?: string
  active_plan?: CEOPlan
  work_item_states?: Record<string, string>
  ceo_invocation_count?: number
  specialist_invocation_count?: number
  replan_count?: number
  employee_summaries?: EmployeeSummary[]
  events?: CompanyEvent[]
  code_patch_artifact_id?: string
  real_repo_apply_proposal_id?: string | null
  real_repo_apply_grant_id?: string | null
  target_repository_verification?: TargetRepositoryVerification
  created_at: string
  updated_at?: string
  completed_at?: string | null
  error?: string | null

  // Enriched fields from Control Center API
  selected_agents: string[]
  skipped_agents: string[]
  selection_reasoning: string
  qa_verdict?: 'PASS' | 'FAIL' | 'BLOCKED' | 'REPAIRING' | string | null
  qa_summary?: string | null
  proposal?: RealRepoApplyProposal | null
  grant?: RealRepoApplyGrant | null
  receipt?: Step20CReceipt | null
  real_repo_apply_result?: any

  // Step 23B.2 Clarification & Investigation fields
  clarification_request?: {
    question: string
    reason?: string
    reasoning?: string
    known_facts?: string[]
    assumptions?: string[]
    missing_critical_information?: string[]
    missing_information?: string[]
    proposed_next_action?: string
    investigation_count?: number
    requested_at?: string
  } | null
  investigation_findings?: string[]
  investigation_count?: number
  max_investigations?: number
  last_ceo_decision?: any
  founder_clarifications?: Array<{
    response: string
    author: string
    submitted_at: string
    in_response_to?: string
  }>

  // Step 23B.3 Adaptive Team Selection & Escalation fields
  team_selection?: TeamSelection | null
  team_escalations?: TeamEscalationRecord[]
  escalation_count?: number
  max_escalations?: number

  // Step 23B.4 Execution Observability & Telemetry
  execution_telemetry?: RunExecutionTelemetry | null

  // Step 23B.5-A Active Execution vs Persisted Snapshot distinction
  is_active_execution?: boolean
  is_persisted_snapshot?: boolean

  // Step 23B.5-C Fault-Tolerant Recovery & Checkpointing
  recovery_summary?: RecoverySummary | null
  recovery_checkpoint?: RecoveryCheckpoint | null
  recovery_history?: any[]
}

export interface RecoverySummary {
  current_attempt: number
  max_retries: number
  failure_category?: string | null
  recovery_decision?: string | null
  preserved_artifacts: string[]
  remaining_work: string[]
  founder_action_required: boolean
  explanation?: string | null
  is_exploration_timeout?: boolean
}

export interface RecoveryCheckpoint {
  checkpoint_id: string
  run_id: string
  completed_work_item_ids: string[]
  completed_work_items: any[]
  preserved_artifacts: any[]
  satisfied_criteria: string[]
  unmet_criteria: string[]
  remaining_work_item_ids: string[]
  attempt_counts: Record<string, number>
  failure_history: any[]
  last_failure?: any | null
  created_at: string
  is_validated: boolean
  validation_error?: string | null
}

export interface SpecialistExecutionMetrics {
  execution_id: string
  role: string
  phase: string
  started_at: string
  work_item_id?: string | null
  task_id?: string | null
  completed_at?: string | null
  duration_seconds?: number | null
  status: string
  model_identifier?: string | null
  model_invocation_count: number
  model_latency_seconds?: number | null
  tool_invocation_count?: number | null
  tool_execution_duration_seconds?: number | null
  input_tokens?: number | null
  output_tokens?: number | null
  total_tokens?: number | null
  error_count: number
  retry_count: number
  error_message?: string | null
  is_measured: boolean
}

export interface RunExecutionTelemetry {
  run_id: string
  started_at: string
  completed_at?: string | null
  duration_seconds?: number | null
  status: string
  specialist_metrics: SpecialistExecutionMetrics[]
  total_model_invocations: number
  total_model_latency_seconds: number
  total_tool_invocations?: number | null
  total_tool_duration_seconds?: number | null
  input_tokens?: number | null
  output_tokens?: number | null
  total_tokens?: number | null
  estimated_cost_usd?: number | null
  cost_status: string
  total_errors: number
  total_retries: number
  planned_specialists: string[]
  executed_specialists: string[]
  specialist_count_planned: number
  specialist_count_executed: number
  team_escalation_count: number
  bottleneck_stage?: {
    role: string
    phase: string
    work_item_id?: string | null
    duration_seconds: number
    reason: string
  } | null
  measured_fields: string[]
  unavailable_fields: string[]
}

export interface PerformanceComparisonReport {
  baseline_run_id: string
  candidate_run_id: string
  compared_at: string
  wall_clock: {
    baseline_seconds?: number | null
    candidate_seconds?: number | null
    delta_seconds?: number | null
    percentage_change?: number | null
  }
  model_invocations: {
    baseline_count: number
    candidate_count: number
    delta_count: number
  }
  model_latency: {
    baseline_seconds: number
    candidate_seconds: number
    delta_seconds: number
  }
  workforce: {
    baseline_planned: number
    candidate_planned: number
    baseline_executed: number
    candidate_executed: number
    baseline_roles: string[]
    candidate_roles: string[]
  }
  reliability: {
    baseline_errors: number
    candidate_errors: number
    baseline_retries: number
    candidate_retries: number
  }
  tokens_and_cost: {
    status: string
    reason: string
    baseline_tokens?: number | null
    candidate_tokens?: number | null
    token_delta?: number | null
    cost_savings_claimed: boolean
    estimated_cost_usd?: number | null
  }
  summary: string
}

export interface RoleRequirement {
  role: string
  why_necessary: string
  expected_deliverable: string
  required_upstream_inputs: string[]
  is_essential: boolean
}

export interface TeamSelection {
  task_category: string
  complexity: 'LOW' | 'MEDIUM' | 'HIGH' | string
  uncertainty: 'LOW' | 'MEDIUM' | 'HIGH' | string
  risk: 'LOW' | 'MEDIUM' | 'HIGH' | string
  required_capabilities: string[]
  selected_roles: string[]
  role_requirements: RoleRequirement[]
  omitted_roles_rationale: Record<string, string>
  selection_reasoning: string
  escalation_conditions: string[]
  estimated_specialist_count: number
  actual_specialist_count: number
  avoidable_delegation_warnings: string[]
  allow_direct_developer: boolean
  evaluated_at: string
}

export interface TeamEscalationRecord {
  escalation_id: string
  run_id: string
  triggered_by_role: string
  reason: string
  requested_capability: string
  added_roles: string[]
  action_taken: string
  created_at: string
}

// =============================================================================
// UI STATE (Separated from backend domain models)
// =============================================================================

export type ViewMode = 'flow' | 'studio'

export interface UIState {
  activeView: ViewMode
  activeNavTab: NavigationTab
  isChatOpen: boolean
  selectedEmployee: Employee | null
  selectedTask: Task | null
  selectedCompanyRun: CompanyRun | null
  remediatingTask: Task | null
}

