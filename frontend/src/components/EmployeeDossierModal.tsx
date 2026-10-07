import React from 'react'
import { RolePortrait } from './Portraits'
import type { Employee } from '../types/company'

interface EmployeeDossierModalProps {
  employee: Employee
  onClose: () => void
  onDirectTask?: (employeeRole: string) => void
}

export const EmployeeDossierModal: React.FC<EmployeeDossierModalProps> = ({
  employee,
  onClose,
  onDirectTask,
}) => {
  if (!employee) return null

  return (
    <div className="modal-backdrop" onClick={onClose} data-testid="employee-dossier-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <RolePortrait role={employee.role} size={48} />
            <div>
              <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
                {employee.name || employee.role.replace(/_/g, ' ').toUpperCase()}
              </h2>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Role: {employee.role} · Status: <strong>{employee.status}</strong>
              </div>
            </div>
          </div>
          <button className="chat-close-btn" onClick={onClose} data-testid="modal-close-btn">
            ✕
          </button>
        </div>

        <div className="modal-body">
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
              Specialization & Responsibilities:
            </div>
            <p>{employee.specialty || 'Core autonomous capability in company architecture.'}</p>
          </div>

          <div style={{ background: 'var(--bg-surface-subtle)', padding: '14px', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
              Current Workstation Thought:
            </div>
            <div style={{ fontStyle: 'italic', color: 'var(--text-secondary)' }}>
              "{employee.dialogue || 'Standing by for missions delegated by the CEO.'}"
            </div>
          </div>
        </div>

        <div className="modal-footer">
          {onDirectTask && (
            <button
              className="btn-primary"
              onClick={() => onDirectTask(employee.role)}
              data-testid="direct-task-btn"
            >
              💬 Assign Direct Task via Chat
            </button>
          )}
          <button className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
