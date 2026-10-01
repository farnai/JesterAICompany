import React from 'react'
import { RolePortrait } from './Portraits'

interface CEOStrategyDeskProps {
  onOpenChat: () => void
  onRunQA?: () => void
  activeTaskTitle?: string
  hasQAFailure?: boolean
  assignedRoles?: string[]
}

export const CEOStrategyDesk: React.FC<CEOStrategyDeskProps> = ({
  onOpenChat,
  onRunQA,
  activeTaskTitle,
  hasQAFailure = false,
  assignedRoles = [],
}) => {
  const teamContext =
    assignedRoles.length > 0
      ? `Allocated specialists: ${assignedRoles.map((r) => r.replace(/_/g, ' ').toUpperCase()).join(', ')}.`
      : 'Specialist workforce allocated.'

  return (
    <section className="ceo-desk-card" data-testid="ceo-strategy-desk">
      <div className="station-identity">
        <div className="avatar-wrapper ceo-avatar">
          <RolePortrait role="ceo" size={52} />
        </div>
        <div>
          <div className="ceo-role-badge">
            <span className="coord-dot" />
            <span>EXECUTIVE COORDINATOR</span>
          </div>
          <h3 style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)' }}>CEO Strategy Desk</h3>
          <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            Connecting Founder Direction ➔ Specialist Workforce ➔ Verified Results
          </p>
        </div>
      </div>

      <div className={`ceo-thought-bubble ${hasQAFailure ? 'alert' : ''}`}>
        {hasQAFailure ? (
          <span style={{ color: 'var(--accent-red)', fontWeight: 600 }}>
            ⚠️ <strong>Verification Notice:</strong> QA detected acceptance criteria issues on "{activeTaskTitle}". Directing remediation with specialist team.
          </span>
        ) : activeTaskTitle ? (
          <>
            <strong>Active Mandate:</strong> Coordinating "{activeTaskTitle}". {teamContext} Overseeing execution standards before QA handoff.
          </>
        ) : (
          <>
            "Standing by for your direction, Founder. All specialists are available and ready for your mandate."
          </>
        )}
      </div>

      <div className="ceo-actions">
        <button
          className="btn-primary"
          onClick={onOpenChat}
          title="Direct the company via Company Chat"
          data-testid="ceo-chat-btn"
        >
          💬 Direct CEO
        </button>
        {onRunQA && (
          <button
            className="btn-secondary"
            onClick={onRunQA}
            title="Execute QA Verification"
            data-testid="ceo-qa-btn"
          >
            🛡️ Verify Work
          </button>
        )}
      </div>
    </section>
  )
}
