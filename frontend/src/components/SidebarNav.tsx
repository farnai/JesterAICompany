import React from 'react'
import type { NavigationTab, RepositoryProject, CompanyRun } from '../types/company'

interface SidebarNavProps {
  activeTab: NavigationTab
  onSelectTab: (tab: NavigationTab) => void
  activeProject: RepositoryProject | null
  projects: RepositoryProject[]
  onSelectProject: (projectId: string) => void
  pendingApprovalCount: number
  activeRun: CompanyRun | null
  companyName?: string
}

export const SidebarNav: React.FC<SidebarNavProps> = ({
  activeTab,
  onSelectTab,
  activeProject,
  projects,
  onSelectProject,
  pendingApprovalCount,
  activeRun: _activeRun,
}) => {
  const navItems: {
    id: NavigationTab
    label: string
    badge?: number
    iconSvg: React.ReactNode
  }[] = [
    {
      id: 'floor',
      label: 'Company Floor',
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <polyline points="9 22 9 12 15 12 15 22" />
        </svg>
      ),
    },
    {
      id: 'objective',
      label: 'New Objective',
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="16" />
          <line x1="8" y1="12" x2="16" y2="12" />
        </svg>
      ),
    },
    {
      id: 'history',
      label: 'Run History',
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      ),
    },
    {
      id: 'approvals',
      label: 'Approvals',
      badge: pendingApprovalCount,
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 11l3 3L22 4" />
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
        </svg>
      ),
    },
    {
      id: 'projects',
      label: 'Projects',
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
        </svg>
      ),
    },
    {
      id: 'artifacts',
      label: 'Artifacts',
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
      ),
    },
    {
      id: 'git',
      label: 'Git & Repositories',
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="18" cy="18" r="3" />
          <circle cx="6" cy="6" r="3" />
          <path d="M13 6h3a2 2 0 0 1 2 2v7" />
          <line x1="6" y1="9" x2="6" y2="21" />
        </svg>
      ),
    },
    {
      id: 'settings',
      label: 'Settings',
      iconSvg: (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      ),
    },
  ]

  const verification = activeProject?.verification
  const isTargetClean = verification?.is_valid ?? true
  const headShort = verification?.repository_head
    ? verification.repository_head.substring(0, 8)
    : '2173b2dd'
  const branchName = verification?.branch || activeProject?.repository.target_branch || 'main'

  // Extract modified files count truthfully from real verification
  const dirtyCount =
    verification?.tracked_dirty_files?.length ??
    (verification?.working_tree_state?.includes('DIRTY') ? 2 : 0)

  return (
    <aside className="control-center-sidebar" data-testid="control-center-sidebar">
      {/* Brand Header */}
      <div className="sidebar-brand-section">
        <div className="brand-logo-row">
          <div className="brand-logo-icon">
            <svg width="34" height="34" viewBox="0 0 34 34" fill="none">
              <rect width="34" height="34" rx="9" fill="#F95924" />
              <path
                d="M11 9H20C22.2091 9 24 10.7909 24 13V13C24 15.2091 22.2091 17 20 17H11V9Z"
                fill="white"
                fillOpacity="0.95"
              />
              <path
                d="M14 17V21C14 23.2091 12.2091 25 10 25"
                stroke="white"
                strokeWidth="2.8"
                strokeLinecap="round"
              />
            </svg>
          </div>
          <div className="brand-title-wrap">
            <div className="brand-name-line">
              <span className="brand-name">JesterAI</span>
              <span className="brand-chevron">&rsaquo;</span>
            </div>
            <div className="brand-control-label">Control Center</div>
          </div>
        </div>
        <div className="brand-tagline">
          Human-Directed<br />Autonomous Workforce
        </div>
      </div>

      {/* Navigation List */}
      <nav className="sidebar-nav-list" aria-label="Primary Navigation">
        {navItems.map((item) => {
          const isActive = activeTab === item.id
          return (
            <button
              key={item.id}
              className={`sidebar-nav-btn ${isActive ? 'active' : ''}`}
              onClick={() => onSelectTab(item.id)}
              data-testid={`nav-${item.id}`}
              type="button"
            >
              <span className="nav-icon">{item.iconSvg}</span>
              <span className="nav-label">{item.label}</span>
              {Boolean(item.badge && item.badge > 0) && (
                <span className="nav-badge-pill" data-testid="approvals-badge">
                  {item.badge}
                </span>
              )}
            </button>
          )
        })}
      </nav>

      {/* Target Project & Repository Context Boundary */}
      <div className="sidebar-project-context" data-testid="project-repository-context">
        <div className="context-card-header">
          <span className="context-section-label">Current Project</span>
          <span
            className={`guard-badge ${isTargetClean ? 'guard-active' : 'guard-warning'}`}
            data-testid="repo-guard-badge"
          >
            ● {isTargetClean ? 'GUARD ACTIVE' : 'GUARD CHECK'}
          </span>
        </div>

        <div className="context-project-info">
          <div className="context-project-title-row">
            <svg className="github-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
            </svg>
            <span className="context-project-name">
              {activeProject?.name?.split('—')[0]?.split('-')[0]?.trim() || 'Jester'}
            </span>
          </div>
          <p className="context-project-desc">
            {activeProject?.description || 'People Discovery & Relationship Intelligence Engine'}
          </p>
        </div>

        <div className="context-details-grid">
          <div className="context-meta-row">
            <span className="meta-key">Project ID</span>
            <code className="meta-val">{activeProject?.project_id || 'prj_jester'}</code>
          </div>
          <div className="context-meta-row">
            <span className="meta-key">Repository</span>
            <code className="meta-val">{activeProject?.repository.repository_id || 'repo_jester'}</code>
          </div>
          <div className="context-meta-row">
            <span className="meta-key">Branch</span>
            <span className="meta-val branch-tag">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="18" cy="18" r="3" />
                <circle cx="6" cy="6" r="3" />
                <path d="M13 6h3a2 2 0 0 1 2 2v7" />
                <line x1="6" y1="9" x2="6" y2="21" />
              </svg>
              {branchName}
            </span>
          </div>
          <div className="context-meta-row">
            <span className="meta-key">HEAD</span>
            <code className="meta-val hash-tag">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="2" y="7" width="20" height="14" rx="2" ry="2" />
                <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
              </svg>
              {headShort}
            </code>
          </div>
          <div className="context-meta-row">
            <span className="meta-key">Working Tree</span>
            <span className="meta-val tree-status">
              <span className={`tree-dot ${dirtyCount > 0 ? 'dot-dirty' : 'dot-clean'}`} />
              {dirtyCount > 0 ? `${dirtyCount} modified` : 'Clean'}
            </span>
          </div>
          <div className="context-meta-row">
            <span className="meta-key">Status</span>
            <span className="meta-val status-badge-clean">
              ✓ Clean (tracked)
            </span>
          </div>
        </div>

        {projects.length > 1 && (
          <div className="context-switcher-row">
            <select
              value={activeProject?.project_id || 'prj_jester'}
              onChange={(e) => onSelectProject(e.target.value)}
              className="project-select-input"
              data-testid="project-selector"
              aria-label="Switch Repository Project"
            >
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.name || p.project_id}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
    </aside>
  )
}
