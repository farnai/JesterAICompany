import type { CompanyEvent, CompanyRun } from '../types/company'

/** Normalises a backend role/id into the canonical snake_case key. */
export const normRole = (role: string): string => role.toLowerCase().replace(/[\s-]/g, '_')

const ACRONYM_LABELS: Record<string, string> = { qa: 'QA', ux: 'UX', ceo: 'CEO' }

/** Human label for a role: "qa" -> "QA", "developer" -> "Developer". */
export function roleLabel(role: string): string {
  return normRole(role)
    .split('_')
    .filter(Boolean)
    .map((w) => ACRONYM_LABELS[w] || w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/** Canonical display order of well-known roles; unknown roles follow alphabetically. */
export const CANONICAL_ROLE_ORDER = ['product', 'ux', 'developer', 'qa', 'research', 'marketing']

export function sortRoles(roles: string[]): string[] {
  const rank = (r: string) => {
    const i = CANONICAL_ROLE_ORDER.indexOf(r)
    return i === -1 ? CANONICAL_ROLE_ORDER.length : i
  }
  return [...roles].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
}

/**
 * Splits a registered project name such as
 * "Jester — People Discovery & Relationship Intelligence Engine"
 * into a short product title and a descriptive tagline.
 */
export function splitProjectName(
  name?: string | null,
  description?: string | null
): { title: string; tagline: string } {
  const full = (name || '').trim()
  if (!full) return { title: '', tagline: (description || '').trim() }
  const parts = full.split(/\s+[—–-]\s+/)
  const title = parts[0].trim()
  const tagline = parts.slice(1).join(' — ').trim() || (description || '').trim()
  return { title, tagline }
}

/** "13m 28s", "2h 14m", "1d 3h". */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const d = Math.floor(total / 86400)
  const h = Math.floor((total % 86400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

const EVENT_TITLES: Record<string, string> = {
  RUN_CREATED: 'Run created',
  OBJECTIVE_RECEIVED: 'Objective received',
  PLANNING_STARTED: 'CEO started planning',
  CEO_PLAN_ACCEPTED: 'CEO plan accepted',
  SPECIALISTS_SELECTED: 'CEO selected specialists',
  RUN_STARTED: 'Run started',
  RUN_COMPLETED: 'Run completed',
  DEVELOPER_PIPELINE_STARTED: 'Developer started implementation',
  DEVELOPER_PLAN_VERIFIED: 'Developer plan verified',
  EXECUTION_GRANT_ACCEPTED: 'Execution grant accepted',
  MUTATION_COMPLETED: 'Developer finished editing',
  CODE_PATCH_VERIFIED: 'Code patch verified',
  QA_STARTED: 'QA started verification',
  QA_PASSED: 'QA passed',
  QA_FAILED: 'QA failed',
  PROPOSAL_GENERATED: 'Proposal generated for Founder',
  READY_FOR_HUMAN_APPLY: 'Ready for Founder approval',
}

function sentenceCase(eventType: string): string {
  const words = eventType
    .toLowerCase()
    .split('_')
    .filter(Boolean)
    .map((w) => ACRONYM_LABELS[w] || w)
  const text = words.join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/**
 * Turns a raw engine event into a human-readable title plus an optional
 * secondary detail line. The raw event type is never altered or dropped.
 */
export function humanizeEvent(evt: CompanyEvent): { title: string; detail: string | null } {
  const type = evt.event_type
  const role = evt.role ? roleLabel(evt.role) : null
  let title = EVENT_TITLES[type]

  if (!title) {
    if (type === 'WORK_ITEM_STARTED') title = `${role || 'Specialist'} started work`
    else if (type === 'WORK_ITEM_COMPLETED') title = `${role || 'Specialist'} completed work`
    else if (type === 'WORK_ITEM_FAILED') title = `${role || 'Specialist'} work failed`
    else title = sentenceCase(type)
  }

  const detail = evt.summary || evt.reason || null
  return { title, detail }
}

export interface CeoPresence {
  label: string
  active: boolean
  tone: 'idle' | 'active' | 'attention' | 'done' | 'danger'
}

/** CEO status derived strictly from the real run state. */
export function ceoPresence(run: CompanyRun | null): CeoPresence {
  if (!run) return { label: 'Standing by', active: false, tone: 'idle' }
  switch (run.state) {
    case 'CREATED':
      return { label: 'Receiving objective', active: true, tone: 'active' }
    case 'PLANNING':
      return { label: 'Planning objective', active: true, tone: 'active' }
    case 'PLAN_READY':
      return { label: 'Selecting specialists', active: true, tone: 'active' }
    case 'RUNNING':
      return { label: 'Orchestrating', active: true, tone: 'active' }
    case 'WAITING_FOR_HUMAN':
    case 'READY_FOR_HUMAN_APPLY':
      return { label: 'Proposal awaiting Founder', active: false, tone: 'attention' }
    case 'APPLYING':
      return { label: 'Applying approved patch', active: true, tone: 'active' }
    case 'COMPLETED':
      return { label: 'Completed', active: false, tone: 'done' }
    case 'BLOCKED':
      return { label: 'Blocked', active: false, tone: 'danger' }
    case 'FAILED':
      return { label: 'Failed', active: false, tone: 'danger' }
    default:
      return { label: roleLabel(run.state), active: false, tone: 'idle' }
  }
}
