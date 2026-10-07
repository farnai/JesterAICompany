import React, { useState } from 'react'
import type { RepositoryProject } from '../types/company'
import { splitProjectName } from './presentation'

interface FloorProjectHeaderProps {
  project: RepositoryProject | null
  projects?: RepositoryProject[]
  onSelectProject?: (projectId: string) => void
}

/**
 * Strong project identity for the first screen of the Company Floor.
 * Conceptually:
 *   JESTER ▾
 *   People Discovery & Relationship Intelligence
 *   repo_jester • main   GUARD ACTIVE
 *   AI Workforce assigned to this project
 */
export const FloorProjectHeader: React.FC<FloorProjectHeaderProps> = ({
  project,
  projects = [],
  onSelectProject,
}) => {
  const [dropdownOpen, setDropdownOpen] = useState(false)

  if (!project) {
    return (
      <header className="fl-project-header" data-testid="floor-project-context">
        <div className="fl-project-main">
          <div className="fl-project-switch">
            <h1 className="fl-project-name fl-project-name-empty">No Project Connected</h1>
          </div>
          <p className="fl-project-tagline">Register a repository project to assign the AI workforce.</p>
        </div>
      </header>
    )
  }

  const { title, tagline } = splitProjectName(project.name, project.description)
  const displayTitle = title || project.project_id
  const displayTagline = tagline || 'People Discovery & Relationship Intelligence'
  const verification = project.verification
  const branch = verification?.branch || project.repository?.target_branch || 'main'
  const repoId = project.repository?.repository_id || 'repo_jester'
  const guardKnown = verification !== undefined && verification !== null
  const guardOk = Boolean(verification?.is_valid)

  return (
    <header className="fl-project-header" data-testid="floor-project-context">
      <div className="fl-project-main">
        <div className="fl-project-switch-container">
          <div
            className="fl-project-switch"
            role="button"
            tabIndex={0}
            onClick={() => projects.length > 1 && setDropdownOpen(!dropdownOpen)}
            aria-label="Active project selector"
            data-testid="floor-project-selector"
          >
            <h1 className="fl-project-name">{displayTitle}</h1>
            <span className="fl-project-chevron" aria-hidden="true">
              ▾
            </span>
          </div>

          {dropdownOpen && projects.length > 1 && (
            <div className="fl-project-dropdown-menu">
              {projects.map((p) => {
                const pTitle = splitProjectName(p.name, p.description).title || p.project_id
                const isSelected = p.project_id === project.project_id
                return (
                  <button
                    key={p.project_id}
                    className={`fl-project-dropdown-item ${isSelected ? 'selected' : ''}`}
                    onClick={() => {
                      onSelectProject?.(p.project_id)
                      setDropdownOpen(false)
                    }}
                    type="button"
                  >
                    <strong>{pTitle}</strong>
                    <small>{p.repository?.repository_id} · {p.project_id}</small>
                  </button>
                )
              })}
            </div>
          )}
        </div>
        {displayTagline && <p className="fl-project-tagline">{displayTagline}</p>}
      </div>

      <div className="fl-project-side">
        <div className="fl-project-meta">
          <span className="fl-repo-chip" title={project.repository?.root_path}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
            </svg>
            <span>{repoId}</span>
            <span className="meta-bullet">•</span>
            <span>{branch}</span>
          </span>
          {guardKnown && (
            <span
              className={`fl-guard-chip ${guardOk ? 'guard-ok' : 'guard-warn'}`}
              data-testid="floor-guard-badge"
            >
              <span className="fl-guard-dot" />
              {guardOk ? 'GUARD ACTIVE' : 'GUARD CHECK'}
            </span>
          )}
        </div>
        <p className="fl-project-workforce">AI Workforce assigned to this project</p>
      </div>
    </header>
  )
}
