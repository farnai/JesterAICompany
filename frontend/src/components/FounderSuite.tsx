import React from 'react'
import { RolePortrait } from './Portraits'
import type { CompanyOverview } from '../types/company'

interface FounderSuiteProps {
  overview: CompanyOverview | null
  activeWorkersCount: number
  totalDeliverables: number
  qaPassedCount?: number
  healthStatus?: string
  companyName?: string
}

export const FounderSuite: React.FC<FounderSuiteProps> = ({
  overview,
  activeWorkersCount,
  totalDeliverables,
  qaPassedCount,
  healthStatus,
  companyName,
}) => {
  const name =
    companyName ||
    overview?.company?.name ||
    overview?.company_name ||
    'Jester AI Company'

  const health =
    healthStatus ||
    overview?.company?.health ||
    overview?.company?.status ||
    overview?.health ||
    'OPERATIONAL'

  const deliverables =
    overview?.counts?.completed_tasks ??
    overview?.completed_task_count ??
    totalDeliverables

  const verified =
    qaPassedCount ??
    overview?.counts?.passed_verifications ??
    overview?.qa_passed_count ??
    0

  return (
    <section className="founder-suite" data-testid="founder-suite">
      <div className="founder-identity">
        <div className="avatar-wrapper summit-avatar">
          <RolePortrait role="owner" size={56} />
        </div>
        <div className="founder-meta">
          <div className="summit-tag">
            <span className="summit-dot" />
            <span>COMPANY SUMMIT · EXECUTIVE OWNERSHIP</span>
          </div>
          <h2>Founder & Owner Suite</h2>
          <p className="founder-ownership-line">
            You own <strong>{name}</strong> · Directing an autonomous, human-led digital workforce
          </p>
          <div className="founder-mission-statement">
            <span className="mission-prefix">Mission & Direction:</span> Deliver verified, production-ready software solutions with human governance and autonomous execution.
          </div>
        </div>
      </div>

      <div className="company-pulse-metrics">
        <div className="metric-pill">
          <span className="metric-val">{activeWorkersCount}</span>
          <span className="metric-lbl">Active on Tasks</span>
        </div>

        <div className="metric-pill">
          <span className="metric-val">{deliverables}</span>
          <span className="metric-lbl">Deliverables</span>
        </div>

        <div className="metric-pill">
          <span className="metric-val">{verified}</span>
          <span className="metric-lbl">QA Verified</span>
        </div>

        <div className="header-status-chip">
          <span className="status-dot pulse" />
          <span>{health.toUpperCase()}</span>
        </div>
      </div>
    </section>
  )
}
