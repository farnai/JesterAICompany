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
    <div className="modal-backdrop" data-testid="new-objective-modal">
      <div className="new-objective-card">
        <div className="objective-modal-header">
          <span className="objective-badge">MISSION INTENT</span>
          <h2 className="objective-modal-title">Formulate Company Objective</h2>
          <p className="objective-modal-subtitle">
            Define mission direction for CEO executive orchestration and specialist DAG formulation.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="objective-form">
          {error && <div className="form-error-banner">{error}</div>}

          <div className="form-group">
            <label className="form-label">Target Project & Repository Context:</label>
            {projects.length > 1 ? (
              <select
                className="form-input"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                style={{ marginBottom: '8px' }}
                data-testid="select-objective-project"
              >
                {projects.map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.name} ({p.repository.target_branch})
                  </option>
                ))}
              </select>
            ) : null}
            <div className="target-context-display">
              <span className="proj-name">{selectedProj?.name || 'Jester'}</span>
              <code className="repo-path">
                {selectedProj?.repository?.root_path || 'C:\\Users\\fiord\\OneDrive\\Desktop\\Jester'}
              </code>
              <span className="branch-tag">🌱 {selectedProj?.repository?.target_branch || 'main'}</span>
            </div>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="obj-title-input">
              Objective Title:
            </label>
            <input
              id="obj-title-input"
              className="form-input"
              type="text"
              placeholder="e.g. Add defensive validation to canonical_pair_seed"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              data-testid="input-objective-title"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="obj-desc-input">
              Goal & Acceptance Criteria Details:
            </label>
            <textarea
              id="obj-desc-input"
              className="form-textarea"
              placeholder="Describe the desired outcome, error behavior, and test criteria..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              data-testid="input-objective-desc"
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="obj-constraints-input">
              Constraints (one per line):
            </label>
            <textarea
              id="obj-constraints-input"
              className="form-textarea font-mono"
              placeholder="Enter operational constraints..."
              value={constraintsText}
              onChange={(e) => setConstraintsText(e.target.value)}
              rows={3}
              data-testid="input-objective-constraints"
            />
          </div>

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
