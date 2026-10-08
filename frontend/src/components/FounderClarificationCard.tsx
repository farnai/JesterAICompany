import React, { useState } from 'react'
import type { CompanyRun } from '../types/company'

interface FounderClarificationCardProps {
  run: CompanyRun
  onSubmitClarification?: (response: string) => Promise<any> | void
  isSubmitting?: boolean
}

export const FounderClarificationCard: React.FC<FounderClarificationCardProps> = ({
  run,
  onSubmitClarification,
  isSubmitting = false,
}) => {
  const [response, setResponse] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const request = run.clarification_request
  const question = request?.question || 'Please clarify the business requirements for this objective.'
  const whyItMatters =
    request?.reason ||
    request?.reasoning ||
    'The CEO requires human judgment to avoid misinterpreting product intent.'
  const knownFacts = request?.known_facts || []
  const assumptions = request?.assumptions || []
  const findings = run.investigation_findings || []

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!response.trim() || submitting || isSubmitting) return

    setSubmitting(true)
    setError(null)
    try {
      if (onSubmitClarification) {
        await onSubmitClarification(response.trim())
      }
      setResponse('')
    } catch (err: any) {
      setError(err?.message || 'Failed to submit clarification')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section
      className="founder-clarification-card"
      data-testid="founder-clarification-card"
      style={{
        background: '#ffffff',
        border: '1px solid #ea580c',
        borderRadius: '12px',
        padding: '18px 22px',
        margin: '16px 0',
        boxShadow: '0 4px 16px rgba(234, 88, 12, 0.08)',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: '#ea580c',
            }}
          />
          <span
            style={{
              fontSize: '11px',
              fontWeight: 700,
              letterSpacing: '0.05em',
              textTransform: 'uppercase',
              color: '#ea580c',
            }}
          >
            CEO Clarification Request
          </span>
        </div>
        <span
          style={{
            fontSize: '11px',
            color: '#8E8E84',
            background: '#F6F6F2',
            padding: '3px 8px',
            borderRadius: '12px',
          }}
        >
          Investigation count: {run.investigation_count ?? 0} / {run.max_investigations ?? 2}
        </span>
      </div>

      {/* What CEO Needs to Know */}
      <div style={{ marginBottom: '14px' }}>
        <h4
          style={{
            fontSize: '13px',
            fontWeight: 600,
            color: '#5A5A52',
            marginBottom: '4px',
          }}
        >
          What CEO needs to know:
        </h4>
        <div
          data-testid="clarification-question"
          style={{
            fontSize: '15px',
            fontWeight: 600,
            color: '#1A1A18',
            lineHeight: 1.4,
            padding: '8px 12px',
            background: '#fff7ed',
            borderRadius: '8px',
            borderLeft: '3px solid #ea580c',
          }}
        >
          {question}
        </div>
      </div>

      {/* Why it Matters */}
      <div style={{ marginBottom: '14px' }}>
        <h4
          style={{
            fontSize: '12px',
            fontWeight: 600,
            color: '#5A5A52',
            marginBottom: '3px',
          }}
        >
          Why this information matters:
        </h4>
        <p
          data-testid="clarification-reason"
          style={{
            fontSize: '13px',
            color: '#5A5A52',
            lineHeight: 1.45,
            margin: 0,
          }}
        >
          {whyItMatters}
        </p>
      </div>

      {/* Context Tags: Known Facts & Investigation Findings */}
      {(knownFacts.length > 0 || findings.length > 0 || assumptions.length > 0) && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            marginBottom: '16px',
            padding: '10px 12px',
            background: '#fafaf9',
            borderRadius: '8px',
            border: '1px solid #EAEAE4',
            fontSize: '12px',
          }}
        >
          {knownFacts.length > 0 && (
            <div>
              <strong style={{ color: '#1A1A18' }}>Known Facts: </strong>
              <span style={{ color: '#5A5A52' }}>{knownFacts.join(' · ')}</span>
            </div>
          )}
          {assumptions.length > 0 && (
            <div>
              <strong style={{ color: '#1A1A18' }}>Assumptions: </strong>
              <span style={{ color: '#5A5A52' }}>{assumptions.join(' · ')}</span>
            </div>
          )}
          {findings.length > 0 && (
            <div>
              <strong style={{ color: '#1A1A18' }}>Investigation Findings: </strong>
              <span style={{ color: '#5A5A52' }}>{findings.join(' · ')}</span>
            </div>
          )}
        </div>
      )}

      {/* Response Action Form */}
      <form onSubmit={handleSubmit} style={{ marginTop: '12px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <textarea
            data-testid="clarification-input"
            value={response}
            onChange={(e) => setResponse(e.target.value)}
            placeholder="Type your direction or clarification to the CEO here..."
            rows={2}
            style={{
              width: '100%',
              padding: '10px 12px',
              fontSize: '13px',
              color: '#1A1A18',
              background: '#FFFFFF',
              border: '1px solid #DCDCD4',
              borderRadius: '8px',
              outline: 'none',
              fontFamily: 'inherit',
              resize: 'vertical',
            }}
          />
          {error && (
            <div style={{ color: '#EF4444', fontSize: '12px', fontWeight: 500 }}>
              {error}
            </div>
          )}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button
              type="submit"
              data-testid="clarification-submit-btn"
              disabled={!response.trim() || submitting || isSubmitting}
              style={{
                background: '#ea580c',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                padding: '8px 18px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: response.trim() && !submitting ? 'pointer' : 'not-allowed',
                opacity: response.trim() && !submitting ? 1 : 0.6,
                transition: 'background 0.2s ease',
              }}
            >
              {submitting || isSubmitting
                ? 'Resuming Run...'
                : 'Submit Clarification & Resume'}
            </button>
          </div>
        </div>
      </form>
    </section>
  )
}
