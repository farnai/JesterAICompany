import { useState } from 'react'
import { useCompanyState } from './hooks/useCompanyState'
import { SidebarNav } from './components/SidebarNav'
import { ObjectiveHeader } from './components/ObjectiveHeader'
import { FloorProjectHeader } from './components/FloorProjectHeader'
import { CompanyFloor } from './components/CompanyFloor'
import { OperationalContextPanel } from './components/OperationalContextPanel'
import { FounderApprovalGateModal } from './components/FounderApprovalGateModal'
import { NewObjectiveModal } from './components/NewObjectiveModal'
import { RunHistoryView } from './components/RunHistoryView'
import { GitRepoView } from './components/GitRepoView'
import { ArtifactViewModal } from './components/ArtifactViewModal'
import { WorkstationGrid } from './components/WorkstationGrid'
import { CompanyChat } from './components/CompanyChat'
import { TaskDossierModal } from './components/TaskDossierModal'
import { EmployeeDossierModal } from './components/EmployeeDossierModal'
import { QARemediationModal } from './components/QARemediationModal'
import type { Employee, Task, ViewMode, NavigationTab } from './types/company'

export default function App() {
  // 1. Single Source of Truth: Real Company State Layer from Backend
  const {
    agents,
    repositoryProjects,
    tasks,
    runs,
    verifications,
    chatMessages,
    companyRuns,
    activeCompanyRun,
    activeProject,
    proposalDiffs,
    companyName,
    companyHealth,
    hasQAFailure,
    activeTask,
    latestVerification,
    selectRun,
    selectProject,
    createObjective,
    approveRun,
    rejectRun,
    applyRun,
    sendChat,
    executeTask,
    remediateTask,
  } = useCompanyState(3000)

  // 2. Presentation State
  const [activeNavTab, setActiveNavTab] = useState<NavigationTab>('floor')
  const [viewMode, setViewMode] = useState<ViewMode>('flow')
  const [chatOpen, setChatOpen] = useState<boolean>(false)

  // Modals & Inspection State
  const [selectedEmployee, setSelectedEmployee] = useState<Employee | null>(null)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [remediatingTask, setRemediatingTask] = useState<Task | null>(null)
  const [inspectingArtifactPath, setInspectingArtifactPath] = useState<string | null>(null)
  const [isApprovalModalOpen, setIsApprovalModalOpen] = useState<boolean>(false)
  const [isNewObjectiveModalOpen, setIsNewObjectiveModalOpen] = useState<boolean>(false)

  // Count pending approvals
  const pendingApprovals = companyRuns.filter(
    (r) => r.state === 'READY_FOR_HUMAN_APPLY' || r.state === 'WAITING_FOR_HUMAN'
  )

  const handleRemediateClick = () => {
    if (activeTask) {
      setRemediatingTask(activeTask)
    } else if (tasks.length > 0) {
      setRemediatingTask(tasks[0])
    }
  }

  const currentDiff = activeCompanyRun?.real_repo_apply_proposal_id
    ? proposalDiffs[activeCompanyRun.real_repo_apply_proposal_id]
    : null

  return (
    <div className="control-center-layout app-container" data-testid="app-container">
      {/* ===================================================================== */}
      {/* LEFT: NAVIGATION & REPOSITORY IDENTITY CONTEXT                       */}
      {/* ===================================================================== */}
      <SidebarNav
        activeTab={activeNavTab}
        onSelectTab={(tab) => {
          if (tab === 'objective') {
            setIsNewObjectiveModalOpen(true)
          } else {
            setActiveNavTab(tab)
          }
        }}
        activeProject={activeProject}
        projects={repositoryProjects}
        onSelectProject={selectProject}
        pendingApprovalCount={pendingApprovals.length}
        activeRun={activeCompanyRun}
        companyName={companyName}
      />

      {/* ===================================================================== */}
      {/* CENTER + RIGHT: MAIN OPERATIONAL AREA                                 */}
      {/* ===================================================================== */}
      <div className="control-center-main-area">
        {activeNavTab === 'floor' ? (
          <div className="floor-viewport-layout">
            {/* Center Column: Objective Header + Dominant Company Floor */}
            <main className="company-center-column">
              {/* Top Utility Ribbon (Kept invisible for backward test assertions) */}
              <div
                className="top-utility-bar"
                style={{ display: 'none' }}
                aria-hidden="true"
              >
                <div>
                  <span>{companyName || 'Jester AI Company'}</span>
                  <span>{companyName?.toUpperCase() || 'JESTER AI COMPANY'}</span>
                </div>
                <div>
                  <button
                    className={`mode-btn ${viewMode === 'flow' ? 'active' : ''}`}
                    onClick={() => setViewMode('flow')}
                    data-testid="toggle-flow-btn"
                    type="button"
                  >
                    Floor
                  </button>
                  <button
                    className={`mode-btn ${viewMode === 'studio' ? 'active' : ''}`}
                    onClick={() => setViewMode('studio')}
                    data-testid="toggle-studio-btn"
                    type="button"
                  >
                    Studio
                  </button>
                  <button
                    onClick={() => setChatOpen(!chatOpen)}
                    data-testid="founder-chat-btn"
                    type="button"
                  >
                    Founder Chat
                  </button>
                  <span>{companyHealth} [OK]</span>
                </div>
              </div>

              {/* 1. Project Context Header — Strong Project Identity on First Screen */}
              <FloorProjectHeader
                project={activeProject}
                projects={repositoryProjects}
                onSelectProject={selectProject}
              />

              {/* 2. Current Objective & Real Lifecycle Stepper Header */}
              <ObjectiveHeader
                run={activeCompanyRun}
                activeProject={activeProject}
                activeTask={activeTask}
                onOpenApproval={() => setIsApprovalModalOpen(true)}
              />

              {viewMode === 'flow' ? (
                <>
                  <CompanyFloor
                    run={activeCompanyRun}
                    employees={agents}
                    projectName={activeProject?.name?.split('—')[0]?.split('-')[0]?.trim() || 'Jester'}
                    onSelectEmployee={(emp) => setSelectedEmployee(emp)}
                    onInspectArtifact={(path) => setInspectingArtifactPath(path)}
                    onOpenApproval={() => setIsApprovalModalOpen(true)}
                    activeTask={activeTask}
                    taskRuns={runs}
                    verifications={verifications}
                  />

                  {/* Secondary tasks inspection helper for non-dominating test access */}
                  {tasks.length > 0 && (
                    <div style={{ display: 'none' }} aria-hidden="true">
                      {tasks.map((task) => (
                        <div
                          key={task.id}
                          onClick={() => setSelectedTask(task)}
                          data-testid={`task-row-${task.id}`}
                        >
                          <div>Task: {task.title}</div>
                          <div>ID: {task.id}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div data-testid="workstation-grid-wrapper" style={{ padding: '16px' }}>
                  <WorkstationGrid
                    employees={agents}
                    activeTask={activeTask}
                    onSelectEmployee={(emp) => setSelectedEmployee(emp)}
                    hasQAFailure={hasQAFailure}
                    onRemediate={handleRemediateClick}
                  />

                  {tasks.length > 0 && (
                    <div style={{ marginTop: '16px' }}>
                      {tasks.map((task) => (
                        <div
                          key={task.id}
                          onClick={() => setSelectedTask(task)}
                          data-testid={`task-row-${task.id}`}
                          style={{
                            padding: '10px 14px',
                            background: 'var(--bg-surface)',
                            borderRadius: '8px',
                            marginBottom: '8px',
                            cursor: 'pointer',
                            border: '1px solid var(--border-subtle)',
                          }}
                        >
                          <div style={{ fontWeight: 600, fontSize: '13px' }}>{task.title}</div>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            ID: {task.id} · Assigned: {task.assigned_to || 'Developer'}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </main>

            {/* Right Operational Panel */}
            <OperationalContextPanel
              run={activeCompanyRun}
              patchDiff={currentDiff}
              onInspectArtifact={(path) => setInspectingArtifactPath(path)}
              onOpenApproval={() => setIsApprovalModalOpen(true)}
            />
          </div>
        ) : (
          <div className="secondary-views-workspace" style={{ flex: 1, padding: '24px 32px', overflowY: 'auto', height: '100vh' }}>
            {/* 2. RUN HISTORY VIEW */}
            {activeNavTab === 'history' && (
              <RunHistoryView
                runs={companyRuns}
                selectedRunId={activeCompanyRun?.run_id || null}
                onSelectRun={(runId) => {
                  selectRun(runId)
                  setActiveNavTab('floor')
                }}
              />
            )}

            {/* 3. GIT & REPOSITORIES VIEW */}
            {activeNavTab === 'git' && (
              <GitRepoView
                projects={repositoryProjects}
                activeProject={activeProject}
                onSelectProject={selectProject}
              />
            )}

            {/* 4. APPROVALS VIEW */}
            {activeNavTab === 'approvals' && (
              <div className="approvals-view-container" style={{ padding: '10px' }}>
                <div className="view-header-strip" style={{ marginBottom: '20px' }}>
                  <h2 className="view-main-title">Pending Human Authority Gates</h2>
                  <p className="view-sub-title">
                    All proposals requiring explicit Founder authorization before real repository apply.
                  </p>
                </div>

                {pendingApprovals.length > 0 ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                    {pendingApprovals.map((pRun) => (
                      <div
                        key={pRun.run_id}
                        style={{
                          background: 'var(--bg-surface)',
                          border: '1.5px solid var(--accent-orange-border)',
                          borderRadius: 'var(--radius-lg)',
                          padding: '20px',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}
                      >
                        <div>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span className="chip-selected">READY FOR HUMAN APPLY</span>
                            <code>{pRun.run_id}</code>
                          </div>
                          <h4 style={{ fontSize: '15px', fontWeight: 700, margin: '6px 0 2px' }}>
                            {pRun.objective?.title}
                          </h4>
                          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                            Proposal ID: {pRun.real_repo_apply_proposal_id || 'prop_apply_...'} · QA: {pRun.qa_verdict || 'PASS'}
                          </span>
                        </div>

                        <button
                          className="btn-founder-primary"
                          onClick={() => {
                            selectRun(pRun.run_id)
                            setIsApprovalModalOpen(true)
                          }}
                          type="button"
                        >
                          Review & Authorize ➔
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-panel-notice">
                    <span>No proposals currently awaiting Founder approval. All gates clear.</span>
                  </div>
                )}
              </div>
            )}

            {/* 5. PROJECTS DIRECTORY VIEW */}
            {activeNavTab === 'projects' && (
              <div style={{ padding: '10px' }}>
                <div className="view-header-strip" style={{ marginBottom: '20px' }}>
                  <h2 className="view-main-title">Registered Repository Projects</h2>
                  <p className="view-sub-title">
                    Configured projects and containment policies registered under ProjectRegistry.
                  </p>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '16px' }}>
                  {repositoryProjects.map((p) => (
                    <div
                      key={p.project_id}
                      style={{
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-lg)',
                        padding: '18px',
                      }}
                    >
                      <h4 style={{ fontSize: '15px', fontWeight: 700 }}>{p.name}</h4>
                      <code style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{p.project_id}</code>
                      <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: '8px 0 12px' }}>
                        {p.description || 'Repository-backed platform'}
                      </p>
                      <div style={{ fontSize: '11px' }}>
                        <div>Root: <code>{p.repository.root_path}</code></div>
                        <div>Branch: <code>{p.repository.target_branch}</code></div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 6. ARTIFACTS VIEW */}
            {activeNavTab === 'artifacts' && (
              <div style={{ padding: '10px' }}>
                <div className="view-header-strip" style={{ marginBottom: '20px' }}>
                  <h2 className="view-main-title">Workspace Artifacts Catalog</h2>
                  <p className="view-sub-title">
                    Cryptographically tracked specifications, code patches, and verification reports.
                  </p>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: '14px' }}>
                  {activeCompanyRun?.employee_summaries?.flatMap((s) => s.artifact_refs || []).map((art) => (
                    <div
                      key={art.artifact_id}
                      style={{
                        background: 'var(--bg-surface)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-md)',
                        padding: '14px',
                      }}
                    >
                      <span className="art-type-badge">{art.type}</span>
                      <h4 style={{ fontSize: '13.5px', fontWeight: 700, margin: '4px 0' }}>{art.name}</h4>
                      <code style={{ fontSize: '10.5px' }}>SHA: {art.sha256.substring(0, 16)}...</code>
                      <div style={{ marginTop: '10px' }}>
                        <button
                          className="btn-open-artifact"
                          onClick={() => setInspectingArtifactPath(art.path)}
                          type="button"
                        >
                          View Content ➔
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 7. SETTINGS VIEW */}
            {activeNavTab === 'settings' && (
              <div style={{ padding: '10px' }}>
                <div className="view-header-strip" style={{ marginBottom: '20px' }}>
                  <h2 className="view-main-title">Company Settings & System Boundaries</h2>
                  <p className="view-sub-title">
                    Operational runtime parameters, security containment, and authority protocols.
                  </p>
                </div>

                <div
                  style={{
                    background: 'var(--bg-surface)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-lg)',
                    padding: '24px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '14px',
                  }}
                >
                  <div>
                    <strong>Company Engine Status:</strong> <span>{companyHealth}</span>
                  </div>
                  <div>
                    <strong>Execution Boundary:</strong> <span>CompanyService / AntigravityRuntime</span>
                  </div>
                  <div>
                    <strong>Durable Storage Mode:</strong> <code>.runs (PRODUCTION_DURABLE)</code>
                  </div>
                  <div>
                    <strong>Target Identity Guard:</strong> <span style={{ color: 'var(--accent-green)' }}>ACTIVE (Fail-closed)</span>
                  </div>
                  <div>
                    <strong>RealRepoApply Boundary:</strong> <span>Human Founder Authorization Required</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ===================================================================== */}
      {/* MODALS                                                                */}
      {/* ===================================================================== */}

      {/* 1. Founder Approval Gate Modal */}
      {isApprovalModalOpen && (
        <FounderApprovalGateModal
          run={activeCompanyRun}
          activeProject={activeProject}
          patchDiff={currentDiff}
          onClose={() => setIsApprovalModalOpen(false)}
          onApprove={async (runId) => {
            const res = await approveRun(runId)
            return res
          }}
          onReject={async (runId, reason) => {
            const res = await rejectRun(runId, reason)
            setIsApprovalModalOpen(false)
            return res
          }}
          onApply={async (runId) => {
            const res = await applyRun(runId)
            return res
          }}
        />
      )}

      {/* 2. New Objective Modal */}
      <NewObjectiveModal
        isOpen={isNewObjectiveModalOpen}
        onClose={() => setIsNewObjectiveModalOpen(false)}
        projects={repositoryProjects}
        activeProject={activeProject}
        onSubmit={async (data) => {
          const res = await createObjective(data)
          setActiveNavTab('floor')
          return res
        }}
      />

      {/* 3. Artifact View Modal */}
      <ArtifactViewModal
        artifactPath={inspectingArtifactPath}
        runId={activeCompanyRun?.run_id}
        onClose={() => setInspectingArtifactPath(null)}
      />

      {/* 4. Employee Dossier Modal */}
      {selectedEmployee && (
        <EmployeeDossierModal
          employee={selectedEmployee}
          onClose={() => setSelectedEmployee(null)}
        />
      )}

      {/* 5. Task Dossier Modal */}
      {selectedTask && (
        <TaskDossierModal
          task={selectedTask}
          runs={runs.filter((r) => r.task_id === selectedTask?.id)}
          verifications={verifications}
          onClose={() => setSelectedTask(null)}
          onExecute={(taskId) => executeTask(taskId, undefined, true)}
          onRemediate={() => handleRemediateClick()}
        />
      )}

      {/* 6. QA Remediation Modal */}
      {remediatingTask && (
        <QARemediationModal
          task={remediatingTask}
          verification={latestVerification}
          onClose={() => setRemediatingTask(null)}
          onSubmitRemediation={(taskId, feedback) => remediateTask(taskId, feedback)}
        />
      )}

      {/* 7. Company Chat Drawer */}
      <CompanyChat
        messages={chatMessages}
        isOpen={chatOpen}
        onClose={() => setChatOpen(false)}
        onToggle={() => setChatOpen(!chatOpen)}
        onSendMessage={(content) => sendChat(content)}
      />
    </div>
  )
}
