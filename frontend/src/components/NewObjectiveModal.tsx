import React, { useState } from 'react'
import type { RepositoryProject } from '../types/company'

interface NewObjectiveModalProps {
  isOpen: boolean
  onClose: () => void
  projects: RepositoryProject[]
  activeProject: RepositoryProject | null
  onSubmit: (data: {
    title: string
    description: string
    project_id: string
    constraints: string[]
  }) => Promise<any>
}

export const NewObjectiveModal: React.FC<NewObjectiveModalProps> = ({
  isOpen,
  onClose,
  projects,
  activeProject,
  onSubmit,
}) => {
  const [title, setTitle] = useState<string>('')
  const [description, setDescription] = useState<string>('')
  const [projectId, setProjectId] = useState<string>(activeProject?.project_id || 'prj_jester')
  const [constraintsText, setConstraintsText] = useState<string>(
    'target repository is external jester\norchestrate focused engineering delivery using product, ux, and developer specialist roles'
  )
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  if (!isOpen) return null

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) {
      setError('Objective title is required.')
      return
    }

    const constraints = constraintsText
      .split('\n')
      .map((c) => c.trim())
      .filter(Boolean)

    try {
      setLoading(true)
      setError(null)
      await onSubmit({
        title: title.trim(),
        description: description.trim() || title.trim(),
        project_id: projectId,
        constraints,
      })
      onClose()
    } catch (err: any) {
      setError(err?.message || 'Failed to submit objective')
    } finally {
      setLoading(false)
    }
  }

  const selectedProj = projects.find((p) => p.project_id === projectId) || activeProject

  return (
    <div className="modal-backdrop" data-testid="new-objective-modal" onClick={onClose}>
      <div className="new-objective-card" onClick={(e) => e.stopPropagation()}>
        <div className="objective-modal-header">
          <div className="modal-kicker-row">
            <span className="objective-badge">MISSION INTENT</span>
            <button
              type="button"
              className="modal-close-icon-btn"
              onClick={onClose}
              aria-label="Close modal"
              data-testid="modal-close-btn"
            >
              ✕
            </button>
          </div>
          <h2 className="objective-modal-title">Formulate Company Objective</h2>
          <p className="objective-modal-subtitle">
            Define mission direction for CEO executive orchestration and specialist DAG formulation.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="objective-form">
          {error && <div className="form-error-banner">{error}</div>}

          {/* TARGET PROJECT CONTEXT */}
          <div className="target-project-section">
            <div className="target-project-header-row">
              <span className="target-section-title">TARGET PROJECT</span>
              {projects.length > 1 && (
                <div className="project-select-wrapper">
                  <select
                    className="project-select-input"
                    value={projectId}
                    onChange={(e) => setProjectId(e.target.value)}
                    data-testid="select-objective-project"
                  >
                    {projects.map((p) => (
                      <option key={p.project_id} value={p.project_id}>
                        {p.name} ({p.repository.target_branch})
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="target-context-box">
              <div className="target-project-primary-line">
                <span className="target-project-name">{selectedProj?.name || 'Jester — People Discovery & Relationship Intelligence Engine'}</span>
                <span className="target-project-id-tag">{selectedProj?.project_id || 'prj_jester'}</span>
              </div>
              <div className="target-context-metadata-grid">
                <div className="metadata-cell">
                  <span className="metadata-label">Repository</span>
                  <code className="metadata-value repo-path" title={selectedProj?.repository?.root_path || ''}>
                    {selectedProj?.repository?.root_path || 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester'}
                  </code>
                </div>
                <div className="metadata-cell branch-cell">
                  <span className="metadata-label">Branch</span>
                  <span className="metadata-value branch-tag">
                    🌱 {selectedProj?.repository?.target_branch || 'main'}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* FORM FIELDS */}
          <div className="form-group">
            <label className="form-label" htmlFor="obj-title-input">
              Objective Title
            </label>
            <input
              id="obj-title-input"
              className="form-input"
              type="text"
              placeholder="e.g. Add defensive non-negative version validation to canonical_pair_seed"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              data-testid="input-objective-title"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="obj-desc-input">
              Goal & Acceptance Criteria
            </label>
            <textarea
              id="obj-desc-input"
              className="form-textarea"
              placeholder="Describe the desired outcome, error behavior, and test criteria..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              data-testid="input-objective-desc"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="obj-constraints-input">
              Constraints
            </label>
            <textarea
              id="obj-constraints-input"
              className="form-textarea font-mono"
              placeholder="Enter operational constraints (one per line)..."
              value={constraintsText}
              onChange={(e) => setConstraintsText(e.target.value)}
              rows={3}
              data-testid="input-objective-constraints"
            />
          </div>

          {/* ACTIONS */}
          <div className="form-action-row">
            <button className="btn-secondary" onClick={onClose} type="button">
              Cancel
            </button>
            <button
              className="btn-founder-primary"
              type="submit"
              disabled={loading}
              data-testid="submit-objective-btn"
            >
              {loading ? 'Orchestrating...' : '🚀 Submit to CEO & Floor'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
