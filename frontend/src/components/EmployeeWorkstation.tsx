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
          <div className="avail-top-row">
            <span className="avail-role-label station-role-pill">{normRole.toUpperCase()}</span>
            <span className="avail-status-pill">
              <span className="avail-status-dot" />
              Available
            </span>
          </div>
          <h4 className="avail-name-title">{personaName}</h4>
          <span className="avail-role-subtitle">{displayTitle}</span>
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
        <div className="workstation-card-top-row">
          <span className="workstation-role-badge station-role-pill">
            <span className="role-name-text">{normRole.toUpperCase()}</span>
          </span>
          <span className={`ws-status ws-status-${statusKey}`}>
            <span className="ws-status-dot" />
            {status === 'Completed' ? 'Completed' : status}
          </span>
        </div>

        <div className="workstation-identity-block">
          <h3 className="workstation-persona-name station-name">{personaName}</h3>
          <span className="workstation-role-title station-title">{displayTitle}</span>
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
            <span className="artifact-pill-prefix">
              <span className="artifact-icon" aria-hidden="true">📄</span>
              <span className="artifact-filename">{latestArtifact.name}</span>
            </span>
            <span className="artifact-arrow">→</span>
          </button>
        )}
      </div>
    </div>
  )
}
