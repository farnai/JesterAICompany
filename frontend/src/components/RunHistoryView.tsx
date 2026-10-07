import React from 'react'
import type { CompanyRun } from '../types/company'

interface RunHistoryViewProps {
  runs: CompanyRun[]
  selectedRunId: string | null
  onSelectRun: (runId: string) => void
}

export const RunHistoryView: React.FC<RunHistoryViewProps> = ({
  runs,
  selectedRunId,
  onSelectRun,
}) => {
  return (
    <div className="run-history-container" data-testid="run-history-view">
      <div className="view-header-strip">
        <div>
          <h2 className="view-main-title">Durable Company Run History</h2>
          <p className="view-sub-title">
            Persisted execution runs loaded directly from durable storage (<code>.runs/company_runs</code>)
          </p>
        </div>
        <span className="runs-count-pill">{runs.length} runs recorded</span>
      </div>

      {runs.length > 0 ? (
        <div className="run-history-table-wrapper">
          <table className="run-history-table">
            <thead>
              <tr>
                <th>Run ID</th>
                <th>Objective</th>
                <th>Project</th>
                <th>Created</th>
                <th>Status</th>
                <th>Workforce</th>
                <th>QA</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const isSelected = r.run_id === selectedRunId
                const timeStr = r.created_at
                  ? new Date(r.created_at).toLocaleString([], {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : 'N/A'

                return (
                  <tr
                    key={r.run_id}
                    className={`history-row ${isSelected ? 'row-selected' : ''}`}
                    onClick={() => onSelectRun(r.run_id)}
                    data-testid={`history-row-${r.run_id}`}
                  >
                    <td>
                      <code className="run-id-code">{r.run_id}</code>
                    </td>
                    <td>
                      <div className="history-obj-title" title={r.objective?.title}>
                        {r.objective?.title || 'Execution Run'}
                      </div>
                    </td>
                    <td>
                      <span className="project-tag">{r.project_id || 'prj_jester'}</span>
                    </td>
                    <td>
                      <span className="time-text">{timeStr}</span>
                    </td>
                    <td>
                      <span className={`run-state-badge state-${r.state.toLowerCase()}`}>
                        {r.state}
                      </span>
                    </td>
                    <td>
                      <div className="agents-chips-row">
                        {r.selected_agents?.map((agent) => (
                          <span key={agent} className="agent-mini-chip">
                            {agent}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      {r.qa_verdict ? (
                        <span
                          className={`qa-mini-badge ${
                            r.qa_verdict === 'PASS' ? 'pass' : 'fail'
                          }`}
                        >
                          {r.qa_verdict}
                        </span>
                      ) : (
                        <span className="qa-mini-badge none">—</span>
                      )}
                    </td>
                    <td>
                      <button
                        className="btn-select-run-cta"
                        onClick={(e) => {
                          e.stopPropagation()
                          onSelectRun(r.run_id)
                        }}
                        type="button"
                      >
                        {isSelected ? 'Loaded ✓' : 'Load Floor ➔'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="empty-panel-notice">
          <span>No historical company runs found in durable storage.</span>
        </div>
      )}
    </div>
  )
}
