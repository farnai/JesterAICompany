import React from 'react'
import type { Task, TaskRun, VerificationResult } from '../types/company'

interface TaskDossierModalProps {
  task: Task
  runs: TaskRun[]
  verifications: VerificationResult[]
  onClose: () => void
  onExecute: (taskId: string) => Promise<any>
  onRemediate: (taskId: string) => void
}

export const TaskDossierModal: React.FC<TaskDossierModalProps> = ({
  task,
  runs,
  verifications,
  onClose,
  onExecute,
  onRemediate,
}) => {
  const [executing, setExecuting] = React.useState(false)
  const taskRuns = runs.filter((r) => r.task_id === task.id)
  const latestRun = taskRuns.length > 0 ? taskRuns[taskRuns.length - 1] : null
  const latestVeri = verifications.find((v) => v.id === latestRun?.verification?.id) || latestRun?.verification

  const handleExecute = async () => {
    setExecuting(true)
    try {
      await onExecute(task.id)
    } finally {
      setExecuting(false)
    }
  }

  const isFailed = latestVeri ? !latestVeri.passed : false

  return (
    <div className="modal-backdrop" onClick={onClose} data-testid="task-dossier-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
              Task Dossier · {task.id}
            </div>
            <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
              {task.title}
            </h2>
          </div>
          <button className="chat-close-btn" onClick={onClose} data-testid="modal-close-btn">
            ✕
          </button>
        </div>

        <div className="modal-body">
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
              Strategic Goal:
            </div>
            <p>{task.goal || 'No explicit goal specified.'}</p>
          </div>

          <div style={{ display: 'flex', gap: '20px', background: 'var(--bg-surface-subtle)', padding: '12px 16px', borderRadius: 'var(--radius-md)' }}>
            <div>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                Status:
              </span>
              <div style={{ fontWeight: 700, color: task.status === 'COMPLETED' ? 'var(--accent-green)' : 'var(--accent-orange)' }}>
                {task.status}
              </div>
            </div>

            <div>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                Assigned Specialist:
              </span>
              <div style={{ fontWeight: 700 }}>
                {task.assigned_to || 'Developer Specialist'}
              </div>
            </div>

            <div>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700 }}>
                Execution Runs:
              </span>
              <div style={{ fontWeight: 700 }}>
                {taskRuns.length}
              </div>
            </div>
          </div>

          {/* QA Verification Status */}
          {latestVeri && (
            <div
              style={{
                border: `1px solid ${isFailed ? 'var(--accent-red-border)' : 'var(--accent-green-border)'}`,
                background: isFailed ? 'var(--accent-red-soft)' : 'var(--accent-green-soft)',
                padding: '12px 16px',
                borderRadius: 'var(--radius-md)',
              }}
            >
              <div style={{ fontWeight: 700, color: isFailed ? 'var(--accent-red)' : 'var(--accent-green)' }}>
                {isFailed ? '❌ QA Verification Failed' : '✅ QA Verification Passed'}
              </div>
              <div style={{ fontSize: '12.5px', marginTop: '4px' }}>{latestVeri.summary}</div>
            </div>
          )}

          {/* Stdout preview if any */}
          {latestRun?.stdout_preview && (
            <div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
                Latest Output Preview (Run #{latestRun.run_number}):
              </div>
              <pre className="code-preview-block">{latestRun.stdout_preview}</pre>
            </div>
          )}
        </div>

        <div className="modal-footer">
          {isFailed && (
            <button
              className="btn-primary"
              style={{ background: 'var(--accent-red)' }}
              onClick={() => onRemediate(task.id)}
              data-testid="task-remediate-btn"
            >
              🔧 Direct Remediation
            </button>
          )}

          <button
            className="btn-primary"
            onClick={handleExecute}
            disabled={executing}
            data-testid="task-execute-btn"
          >
            {executing ? 'Executing...' : '▶ Execute Run'}
          </button>
        </div>
      </div>
    </div>
  )
}
