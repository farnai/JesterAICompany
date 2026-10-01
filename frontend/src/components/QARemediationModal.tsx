import React, { useState } from 'react'
import type { Task, VerificationResult } from '../types/company'

interface QARemediationModalProps {
  task: Task
  verification?: VerificationResult | null
  onClose: () => void
  onSubmitRemediation: (taskId: string, feedback: string) => Promise<any>
}

export const QARemediationModal: React.FC<QARemediationModalProps> = ({
  task,
  verification,
  onClose,
  onSubmitRemediation,
}) => {
  const [feedback, setFeedback] = useState(
    verification?.summary
      ? `Address QA failure: ${verification.summary}. Verify all criteria before re-submitting.`
      : 'Refactor implementation to resolve QA criteria violations and re-run verification suite.'
  )
  const [remediating, setRemediating] = useState(false)

  const handleSubmit = async () => {
    if (!feedback.trim() || remediating) return
    setRemediating(true)
    try {
      await onSubmitRemediation(task.id, feedback)
      onClose()
    } finally {
      setRemediating(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose} data-testid="qa-remediation-modal">
      <div className="modal-card" onClick={(e) => e.stopPropagation()} style={{ borderTop: '4px solid var(--accent-red)' }}>
        <div className="modal-header">
          <div>
            <div style={{ fontSize: '11px', color: 'var(--accent-red)', fontWeight: 700, textTransform: 'uppercase' }}>
              Quality Assurance Remediation Loop
            </div>
            <h2 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
              Remediate: {task.title}
            </h2>
          </div>
          <button className="chat-close-btn" onClick={onClose} data-testid="modal-close-btn">
            ✕
          </button>
        </div>

        <div className="modal-body">
          <div
            style={{
              background: 'var(--accent-red-soft)',
              border: '1px solid var(--accent-red-border)',
              padding: '14px',
              borderRadius: 'var(--radius-md)',
            }}
          >
            <div style={{ fontWeight: 700, color: 'var(--accent-red)', marginBottom: '4px' }}>
              Identified Defect / Failure:
            </div>
            <p style={{ color: '#991B1B' }}>
              {verification?.summary || 'Deliverable failed verification criteria.'}
            </p>
          </div>

          <div>
            <label style={{ display: 'block', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '6px' }}>
              Founder Remediation Directive to Developer & QA:
            </label>
            <textarea
              className="chat-input-field"
              rows={4}
              style={{ width: '100%', resize: 'vertical' }}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              disabled={remediating}
              data-testid="remediation-input"
            />
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose} disabled={remediating}>
            Cancel
          </button>
          <button
            className="btn-primary"
            style={{ background: 'var(--accent-red)' }}
            onClick={handleSubmit}
            disabled={remediating || !feedback.trim()}
            data-testid="submit-remediation-btn"
          >
            {remediating ? 'Dispatching...' : 'Dispatch Remediation ➔'}
          </button>
        </div>
      </div>
    </div>
  )
}
