import React from 'react'
import { RolePortrait } from './Portraits'
import type { Employee, Task } from '../types/company'

interface WorkstationGridProps {
  employees: Employee[]
  activeTask?: Task | null
  onSelectEmployee: (emp: Employee) => void
  hasQAFailure?: boolean
  onRemediate?: () => void
}

export type EmployeeVisualState = 'IDLE' | 'ACTIVE' | 'REVIEWING' | 'WAITING' | 'BLOCKED' | 'COMPLETED'

export const WorkstationGrid: React.FC<WorkstationGridProps> = ({
  employees,
  activeTask,
  onSelectEmployee,
  hasQAFailure = false,
  onRemediate,
}) => {
  if (employees.length === 0) {
    return (
      <div
        className="studio-grid"
        style={{ display: 'flex', justifyContent: 'center', padding: '40px', color: 'var(--text-muted)' }}
        data-testid="workstation-grid-empty"
      >
        Connecting to company employee roster...
      </div>
    )
  }

  return (
    <div className="studio-grid" data-testid="workstation-grid">
      {employees.map((emp) => {
        const roleKey = emp.role.toLowerCase()
        const idKey = (emp.id || '').toLowerCase()
        const isQA = roleKey === 'qa_engineer' || roleKey === 'qa'

        const isTaskActive = activeTask && (activeTask.status === 'IN_PROGRESS' || activeTask.status === 'PENDING')
        const isAssigned = Boolean(
          activeTask && (
            activeTask.assigned_to?.toLowerCase() === roleKey ||
            activeTask.assigned_to?.toLowerCase() === idKey ||
            activeTask.required_roles?.some(
              (r) => r.toLowerCase() === roleKey || r.toLowerCase() === idKey
            )
          )
        )

        // Compute genuine State-driven Visual State
        let visualState: EmployeeVisualState = 'IDLE'
        let badgeLabel = 'AVAILABLE'
        let badgeClass = 'badge-idle badge-standby'
        let cardStateClass = 'state-idle quiet-station'
        let dialogue = emp.dialogue

        if (isQA && hasQAFailure) {
          visualState = 'BLOCKED'
          badgeLabel = 'QA ALERT'
          badgeClass = 'badge-blocked badge-remediate'
          cardStateClass = 'state-blocked remediation-alert'
          if (!dialogue) {
            dialogue = 'Verification criteria violation detected. Awaiting remediation directive.'
          }
        } else if (isAssigned || (isQA && isTaskActive)) {
          if (activeTask?.status === 'BLOCKED') {
            visualState = 'BLOCKED'
            badgeLabel = 'BLOCKED'
            badgeClass = 'badge-blocked'
            cardStateClass = 'state-blocked'
            if (!dialogue) dialogue = `Execution blocked on mission "${activeTask.title}".`
          } else if (activeTask?.status === 'COMPLETED') {
            visualState = 'COMPLETED'
            badgeLabel = 'COMPLETED'
            badgeClass = 'badge-completed'
            cardStateClass = 'state-completed'
            if (!dialogue) dialogue = `Successfully completed and verified work for "${activeTask.title}".`
          } else if (activeTask?.status === 'PENDING') {
            visualState = 'WAITING'
            badgeLabel = 'WAITING'
            badgeClass = 'badge-waiting'
            cardStateClass = 'state-waiting'
            if (!dialogue) dialogue = `Allocated to mission "${activeTask.title}". Standing by for run trigger.`
          } else if (activeTask?.status === 'IN_PROGRESS') {
            if (isQA) {
              visualState = 'REVIEWING'
              badgeLabel = 'REVIEWING'
              badgeClass = 'badge-reviewing'
              cardStateClass = 'state-reviewing'
              if (!dialogue) dialogue = `Auditing deliverable for "${activeTask.title}" against acceptance tests.`
            } else {
              visualState = 'ACTIVE'
              badgeLabel = 'ACTIVE'
              badgeClass = 'badge-active'
              cardStateClass = 'state-active active-worker'
              if (!dialogue) dialogue = `Actively executing work on mission: "${activeTask.title}".`
            }
          } else {
            visualState = 'ACTIVE'
            badgeLabel = 'ALLOCATED'
            badgeClass = 'badge-active'
            cardStateClass = 'state-active active-worker'
            if (!dialogue) dialogue = `Working on mission: "${activeTask?.title}".`
          }
        } else {
          // Employee is genuinely IDLE and available
          visualState = 'IDLE'
          badgeLabel = 'AVAILABLE'
          badgeClass = 'badge-idle badge-standby'
          cardStateClass = 'state-idle quiet-station'
          if (!dialogue) {
            dialogue = `Available for deployment. Specializing in ${emp.responsibilities || emp.title || emp.role}.`
          }
        }

        const displayName = emp.name || emp.title || emp.role.replace(/_/g, ' ').toUpperCase()
        const stationTitle = emp.title || emp.role.replace(/_/g, ' ').toUpperCase()
        const specialty = emp.responsibilities || emp.specialty || 'Autonomous Specialist'
        const isAlert = visualState === 'BLOCKED'

        return (
          <div
            key={emp.id || emp.role}
            className={`station-card ${cardStateClass}`}
            onClick={() => onSelectEmployee(emp)}
            data-testid={`station-${emp.role}`}
            data-visual-state={visualState}
          >
            <div>
              <div className="station-header">
                <div className="station-identity">
                  <div className="station-avatar">
                    <RolePortrait role={emp.role} size={42} />
                  </div>
                  <div className="station-title">
                    <h3>{displayName}</h3>
                    <p>{stationTitle}</p>
                  </div>
                </div>
                <span className={`station-badge ${badgeClass}`}>{badgeLabel}</span>
              </div>

              <div className="station-dialogue">
                {isAlert ? (
                  <span style={{ color: 'var(--accent-red)', fontWeight: 600 }}>
                    ⚠️ {dialogue}
                  </span>
                ) : (
                  dialogue
                )}
              </div>
            </div>

            <div className="station-footer">
              <span
                style={{ maxWidth: '190px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={specialty}
              >
                {specialty}
              </span>
              {isAlert && onRemediate ? (
                <button
                  className="btn-primary"
                  style={{
                    padding: '4px 10px',
                    fontSize: '11.5px',
                    background: 'var(--accent-red)',
                  }}
                  onClick={(e) => {
                    e.stopPropagation()
                    onRemediate()
                  }}
                  data-testid="remediate-btn"
                >
                  Fix Now ➔
                </button>
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>Inspect Dossier ➔</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
