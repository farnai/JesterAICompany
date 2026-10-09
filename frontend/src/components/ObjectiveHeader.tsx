import React from 'react'
import type { CompanyRun, RepositoryProject, Task } from '../types/company'

interface ObjectiveHeaderProps {
  run: CompanyRun | null
  activeProject: RepositoryProject | null
  activeTask?: Task | null
  onOpenApproval?: () => void
}

const LIFECYCLE_PHASES = [
  { id: 'objective', label: 'Objective', stepNum: 1 },
  { id: 'planning', label: 'Planning', stepNum: 2 },
  { id: 'specialists', label: 'Specialists', stepNum: 3 },
  { id: 'development', label: 'Development', stepNum: 4 },
  { id: 'qa', label: 'QA', stepNum: 5 },
  { id: 'approval', label: 'Approval', stepNum: 9 }, // matching mockup's numbered badge
  { id: 'apply', label: 'Apply', stepNum: 7 },
  { id: 'verify', label: 'Verify', stepNum: 8 },
  { id: 'completed', label: 'Complete', stepNum: 9 },
]

export const ObjectiveHeader: React.FC<ObjectiveHeaderProps> = ({
  run,
  activeProject,
  activeTask,
  onOpenApproval,
}) => {
  const objective = run?.objective
  const title =
    objective?.title || (run ? (run.objective?.title || 'Untitled Objective') : (activeTask ? `Active Task: ${activeTask.title}` : 'No Active Objective'))
  const objectiveId =
    objective?.id?.toUpperCase() ||
    activeTask?.id?.toUpperCase() ||
    (run?.run_id ? run.run_id.replace('crun_', 'TASK-').toUpperCase() : '--')

  // Description / summary from constraints or objective
  const rawDesc =
    (objective?.constraints && objective.constraints.length > 0)
      ? objective.constraints.join(' · ')
      : objective?.description ||
        run?.selection_reasoning ||
        (run ? 'No description provided.' : 'Submit an objective or select a project to begin execution.')
  const description = rawDesc.length > 300 ? rawDesc.slice(0, 297) + '...' : rawDesc

  // Determine current active lifecycle phase index from REAL backend state
  const getCurrentPhaseIndex = (): number => {
    if (!run) return 0
    const st = run.state

    if (st === 'CREATED') return 0
    if (st === 'PLANNING' || st === 'PLAN_READY') return 1

    if (st === 'RUNNING') {
      const wiStates = run.work_item_states || {}
      const hasDev = Object.keys(wiStates).some((k) => k.includes('dev'))
      const hasQa = Object.keys(wiStates).some((k) => k.includes('qa'))
      if (hasQa) return 4
      if (hasDev) return 3
      return 2
    }

    if (st === 'WAITING_FOR_HUMAN' || st === 'READY_FOR_HUMAN_APPLY') return 5
    if (st === 'APPLYING') return 6
    if (st === 'COMPLETED') return 8
    if (st === 'BLOCKED' || st === 'FAILED') {
      return run.real_repo_apply_proposal_id ? 5 : 2
    }
    return 0
  }

  const currentPhaseIndex = getCurrentPhaseIndex()
  const isLive = Boolean(run?.is_active_execution)

  // Format real duration if available
  const getElapsedDuration = (): string => {
    if (!run?.created_at) return '--'
    if (run.state === 'CREATED' && !isLive) return '0s (Not started)'
    try {
      const start = new Date(run.created_at).getTime()
      const end = run.completed_at ? new Date(run.completed_at).getTime() : Date.now()
      const diffSec = Math.floor((end - start) / 1000)
      if (diffSec <= 0) return '0s'
      const mins = Math.floor(diffSec / 60)
      const secs = diffSec % 60
      if (mins === 0) return `${secs}s`
      return `${mins}m ${secs}s`
    } catch {
      return '--'
    }
  }

  const durationStr = getElapsedDuration()

  const getPhaseSubstatus = (
    phaseId: string,
    isDone: boolean,
    isCurrent: boolean
  ): string => {
    if (isDone) return 'Completed'
    if (!isCurrent) return ''
    if (phaseId === 'approval') return 'Waiting'
    if (run?.state === 'CREATED') return 'Ready'
    if (run?.state === 'PLAN_READY') return 'Plan Ready'
    if (run?.state === 'FAILED') return 'Failed'
    if (run?.state === 'BLOCKED') return 'Blocked'
    if (run?.state === 'RUNNING') {
      return isLive ? 'Working' : 'Restored'
    }
    return isLive ? 'Working' : 'Saved'
  }

  const startedDateStr = run?.created_at
    ? new Date(run.created_at).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '--'

  const projectName = activeProject?.name?.split('—')[0]?.split('-')[0]?.trim() || 'Jester'
  const repoName = activeProject?.repository?.repository_id || 'repo_jester'
  const branchName = activeProject?.verification?.branch || activeProject?.repository?.target_branch || 'main'

  return (
    <header className="objective-header-card" data-testid="objective-header">
      {/* Top Meta Line: Badge, Category, Repo, Branch, Elapsed Timer */}
      <div className="objective-top-bar">
        <div className="meta-left-group">
          <div className="task-id-badge">
            <span className="code-brackets">&lt;/&gt;</span>
            <span className="task-id-text">{objectiveId}</span>
          </div>

          <span className="category-pill">Backend</span>

          <span className="repo-badge">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            {projectName} / {repoName}
          </span>

          <span className="branch-badge">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="18" cy="18" r="3" />
              <circle cx="6" cy="6" r="3" />
              <path d="M13 6h3a2 2 0 0 1 2 2v7" />
              <line x1="6" y1="9" x2="6" y2="21" />
            </svg>
            {branchName}
          </span>
        </div>

        <div className="meta-right-group">
          <div className="elapsed-timer-block">
            <div className="elapsed-time-row">
              <span className="timer-icon">⏱</span>
              <span className="elapsed-label">Elapsed</span>
              <strong className="elapsed-value">{durationStr}</strong>
            </div>
            <span className="started-subtext">Started {startedDateStr}</span>
          </div>
        </div>
      </div>

      {/* Main Title & Subtitle */}
      <div className="objective-content-row">
        <div className="title-text-group">
          <h1 className="objective-hero-title">{title}</h1>
          <p className="objective-sub-description">{description}</p>
        </div>
      </div>

      {onOpenApproval && (
        <button
          onClick={onOpenApproval}
          data-testid="founder-approval-gate-btn"
          style={{ display: 'none' }}
          aria-hidden="true"
        />
      )}
      <nav className="lifecycle-stepper-track" aria-label="Objective Lifecycle Stepper">
        {LIFECYCLE_PHASES.map((phase, idx) => {
          const isDone =
            idx < currentPhaseIndex || (idx === currentPhaseIndex && run?.state === 'COMPLETED')
          const isCurrent = idx === currentPhaseIndex && run?.state !== 'COMPLETED'
          const isApprovalStep = phase.id === 'approval'

          return (
            <React.Fragment key={phase.id}>
              <div
                className={`stepper-node ${
                  isDone
                    ? 'node-completed'
                    : isCurrent
                    ? isApprovalStep
                      ? 'node-waiting-approval'
                      : isLive
                      ? 'node-active'
                      : 'node-standby'
                    : 'node-upcoming'
                }`}
              >
                <div className="stepper-circle">
                  {isDone ? (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  ) : (
                    <span>{phase.stepNum}</span>
                  )}
                </div>
                <div className="stepper-label-group">
                  <span className="phase-name">{phase.label}</span>
                  <span className="phase-substatus">
                    {getPhaseSubstatus(phase.id, isDone, isCurrent)}
                  </span>
                </div>
              </div>

              {idx < LIFECYCLE_PHASES.length - 1 && (
                <div
                  className={`stepper-connector-line ${
                    idx < currentPhaseIndex ? 'line-completed' : 'line-upcoming'
                  }`}
                />
              )}
            </React.Fragment>
          )
        })}
      </nav>

      {/* Real run state tag for telemetry & tests */}
      <div style={{ display: 'none' }}>
        <span data-testid="run-state-badge">{run?.state || 'STANDBY'}</span>
      </div>
    </header>
  )
}
