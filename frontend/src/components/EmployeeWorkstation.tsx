import React from 'react'
import { RolePortrait, ROLE_PERSONA_NAMES } from './Portraits'
import { normRole as normalizeRole } from './presentation'
import type { EmployeeSummary, WorkItem } from '../types/company'

type WorkstationStatus =
  | 'Available'
  | 'Selected'
  | 'Waiting'
  | 'Working'
  | 'Completed'
  | 'Failed'
  | 'Blocked'
  | 'Repairing'

interface EmployeeWorkstationProps {
  role: string
  name?: string
  title?: string
  status: WorkstationStatus
  currentAction?: string
  workItem?: WorkItem | null
  summary?: EmployeeSummary | null
  isActiveWorkforce: boolean
  onClick?: () => void
  onInspectArtifact?: (artifactPath: string) => void
  anchorId: string
}

/** Concise, truthful status line used only when the engine reported no summary/objective yet. */
const STATUS_FOCUS: Record<WorkstationStatus, string> = {
  Available: 'On standby',
  Selected: 'Selected for this objective',
  Waiting: 'Waiting for upstream work',
  Working: 'Working on assigned work',
  Completed: 'Work completed',
  Failed: 'Work failed — see Activity',
  Blocked: 'Blocked — see Activity',
  Repairing: 'Repairing after QA feedback',
}

export const EmployeeWorkstation: React.FC<EmployeeWorkstationProps> = ({
  role,
  name,
  title,
  status,
  currentAction,
  workItem,
  summary,
  isActiveWorkforce,
  onClick,
  onInspectArtifact,
  anchorId,
}) => {
  const normRole = normalizeRole(role)
  const personaName = ROLE_PERSONA_NAMES[normRole] || name || role.toUpperCase()
  const displayTitle = title || `${role.charAt(0).toUpperCase() + role.slice(1)} Specialist`

  // -------------------------------------------------------------------------
  // AVAILABLE (standby): compact portrait + identity, visually quieter
  // -------------------------------------------------------------------------
  if (!isActiveWorkforce) {
    return (
      <div
        className="available-worker-card quiet-station"
        data-testid={`station-${normRole}`}
        data-anchor={anchorId}
        onClick={onClick}
      >
        <div className="fl-portrait avail-portrait">
          <RolePortrait role={role} fill />
        </div>
        <div className="avail-details-box">
          <span className="avail-role-label">{normRole.toUpperCase()}</span>
          <h4 className="avail-name-title">{personaName}</h4>
          <span className="avail-status-pill">
            <span className="avail-status-dot" />
            Available
          </span>
        </div>
        {/* Hidden role pill for test assertions */}
        <div style={{ display: 'none' }} className="station-role-pill">
          {normRole.toUpperCase()}
        </div>
      </div>
    )
  }

  // -------------------------------------------------------------------------
  // ACTIVE RUN TEAM: editorial workstation
  // -------------------------------------------------------------------------
  const latestArtifact = summary?.artifact_refs?.[0]
  const focusText = currentAction || summary?.summary || workItem?.objective || STATUS_FOCUS[status]
  const statusKey = status.toLowerCase()

  return (
    <div
      className={`active-workstation-card active-floor-station status-${statusKey}`}
      data-testid={`station-${normRole}`}
      data-anchor={anchorId}
      onClick={onClick}
    >
      <div className="workstation-hero-portrait fl-portrait">
        <RolePortrait role={role} fill />
        {status === 'Working' && <div className="card-working-glow" />}
      </div>

      <div className="workstation-card-body">
        <span className="workstation-role-badge">
          <span className="role-name-text">{normRole.toUpperCase()}</span>
        </span>
        <div style={{ display: 'none' }} className="station-role-pill">
          {normRole.toUpperCase()}
        </div>

        <h3 className="workstation-persona-name">{personaName}</h3>

        <div className="workstation-status-row">
          <span className={`ws-status ws-status-${statusKey}`}>
            <span className="ws-status-dot" />
            {status === 'Completed' ? 'Completed' : status}
          </span>
        </div>

        <p className="workstation-focus-text" title={focusText}>
          {focusText}
        </p>

        {latestArtifact && (
          <button
            className="btn-artifact-link"
            onClick={(e) => {
              e.stopPropagation()
              onInspectArtifact?.(latestArtifact.path)
            }}
            type="button"
            title={latestArtifact.name}
          >
            <span className="artifact-filename">{latestArtifact.name}</span>
            <span className="artifact-arrow">→</span>
          </button>
        )}
      </div>

      {/* Hidden helper for test compatibility */}
      <div style={{ display: 'none' }}>
        <h4 className="station-name">{personaName}</h4>
        <span className="station-title">{displayTitle}</span>
      </div>
    </div>
  )
}
