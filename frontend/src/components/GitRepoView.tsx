import React from 'react'
import type { RepositoryProject } from '../types/company'

interface GitRepoViewProps {
  projects: RepositoryProject[]
  activeProject: RepositoryProject | null
  onSelectProject: (projectId: string) => void
}

export const GitRepoView: React.FC<GitRepoViewProps> = ({
  projects,
  activeProject,
  onSelectProject,
}) => {
  const current = activeProject || projects[0]
  const verification = current?.verification

  return (
    <div className="git-repo-view-container" data-testid="git-repo-view">
      <div className="view-header-strip">
        <div>
          <h2 className="view-main-title">Git & Registered Repositories</h2>
          <p className="view-sub-title">
            Authoritative repository boundaries, live Git fingerprints, and mutation containment policies.
          </p>
        </div>
      </div>

      {/* Safety Notice */}
      <div className="git-safety-notice-banner" data-testid="git-safety-banner">
        <div className="notice-icon">🛡️</div>
        <div>
          <div className="notice-title">FOUNDER GIT SAFETY GUARANTEE</div>
          <div className="notice-text">
            No automatic <code>git add</code>, <code>git commit</code>, or <code>git push</code> operations
            are executed by autonomous workers. All repository mutations require explicit Founder
            authorization and are applied transactionally with rollback safeguards.
          </div>
        </div>
      </div>

      {current && (
        <div className="repo-details-card">
          <div className="card-top-row">
            <div>
              <span className="card-badge">REGISTERED TARGET REPOSITORY</span>
              <h3 className="repo-name-heading">{current.name}</h3>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              {projects.length > 1 && (
                <select
                  value={current.project_id}
                  onChange={(e) => onSelectProject(e.target.value)}
                  className="project-select-input"
                >
                  {projects.map((p) => (
                    <option key={p.project_id} value={p.project_id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
              <span
                className={`repo-guard-pill ${
                  verification?.is_valid ? 'guard-pass' : 'guard-fail'
                }`}
              >
                ● {verification?.is_valid ? 'IDENTITY GUARD: PASS' : 'VERIFICATION FAILED'}
              </span>
            </div>
          </div>

          <div className="repo-grid-properties">
            <div className="prop-box">
              <span className="prop-k">Project ID:</span>
              <code>{current.project_id}</code>
            </div>
            <div className="prop-box">
              <span className="prop-k">Repository ID:</span>
              <code>{current.repository.repository_id}</code>
            </div>
            <div className="prop-box">
              <span className="prop-k">Target Branch:</span>
              <span className="branch-val">🌱 {current.repository.target_branch}</span>
            </div>
            <div className="prop-box">
              <span className="prop-k">Verified HEAD Commit:</span>
              <code className="hash-val">{verification?.repository_head || 'Unknown'}</code>
            </div>
            <div className="prop-box full-width">
              <span className="prop-k">Filesystem Root Path:</span>
              <code className="path-val">{current.repository.root_path}</code>
            </div>
            <div className="prop-box full-width">
              <span className="prop-k">Origin Remote:</span>
              <code className="remote-val">{verification?.remote_url || 'git@github.com:farnai/Jester.git'}</code>
            </div>
            <div className="prop-box full-width">
              <span className="prop-k">Working Tree State:</span>
              <span
                className={`tree-val ${
                  verification?.working_tree_state?.includes('CLEAN')
                    ? 'clean'
                    : 'dirty'
                }`}
              >
                {verification?.working_tree_state || 'CLEAN_TRACKED'}
              </span>
            </div>
          </div>

          {/* Access & Mutation Policy */}
          <div className="policy-section">
            <h4 className="policy-title">REPOSITORY ACCESS & CONTAINMENT POLICY</h4>
            <div className="policy-columns">
              <div className="policy-col">
                <span className="col-header read">READ ALLOWED:</span>
                <ul className="policy-list">
                  {(current.policy?.read_allowed || ['backend/**', 'frontend/**', 'tests/**', 'docs/**']).map(
                    (p) => (
                      <li key={p}><code>{p}</code></li>
                    )
                  )}
                </ul>
              </div>

              <div className="policy-col">
                <span className="col-header write">MUTATION ALLOWED:</span>
                <ul className="policy-list">
                  {(current.policy?.mutation_allowed || ['backend/**', 'tests/**']).map((p) => (
                    <li key={p}><code>{p}</code></li>
                  ))}
                </ul>
              </div>

              <div className="policy-col">
                <span className="col-header deny">DENIED PATHS (STRICT):</span>
                <ul className="policy-list">
                  {(current.policy?.denied || ['.git', '.git/**', '.env*', '*.key', '*.secret']).map(
                    (p) => (
                      <li key={p} className="denied-item"><code>{p}</code></li>
                    )
                  )}
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
