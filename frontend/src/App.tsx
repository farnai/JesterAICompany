import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useCompanyState } from './hooks/useCompanyState'
import { FounderSuite } from './components/FounderSuite'
import { CEOStrategyDesk } from './components/CEOStrategyDesk'
import { WorkstationGrid } from './components/WorkstationGrid'
import { CompanyFlowCanvas } from './components/CompanyFlowCanvas'
import { CompanyChat } from './components/CompanyChat'
import { TaskDossierModal } from './components/TaskDossierModal'
import { EmployeeDossierModal } from './components/EmployeeDossierModal'
import { QARemediationModal } from './components/QARemediationModal'
import type { Employee, Task, ViewMode } from './types/company'

export default function App() {
  // 1. Single Source of Truth: Real Company State Layer
  const {
    overview,
    agents,
    tasks,
    runs,
    verifications,
    chatMessages,
    companyName,
    companyHealth,
    activeWorkersCount,
    completedTasksCount,
    qaPassedCount,
    activeTask,
    latestVerification,
    hasQAFailure,
    sendChat,
    executeTask,
    remediateTask,
  } = useCompanyState(4000)

  // 2. UI State (Decoupled from Domain Models)
  const [viewMode, setViewMode] = useState<ViewMode>('flow')
  const [chatOpen, setChatOpen] = useState<boolean>(false)
  const [selectedEmployee, setSelectedEmployee] = useState<Employee | null>(null)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [remediatingTask, setRemediatingTask] = useState<Task | null>(null)

  // Handlers
  const handleOpenChatWithPrompt = (prompt?: string) => {
    setChatOpen(true)
    if (prompt) {
      sendChat(prompt)
    }
  }

  const handleRemediateClick = () => {
    if (activeTask) {
      setRemediatingTask(activeTask)
    } else if (tasks.length > 0) {
      setRemediatingTask(tasks[0])
    }
  }

  return (
    <div className="app-container" data-testid="app-container">
      {/* Top Navbar */}
      <header className="top-navbar">
        <div className="brand-section">
          <span className="brand-badge">Company World</span>
          <div>
            <span className="brand-title">{companyName.toUpperCase()}</span>
            <span className="brand-subtitle"> · Autonomous Human-Directed Workforce</span>
          </div>
        </div>

        <div className="header-controls">
          <div className="mode-toggle-group">
            <button
              className={`mode-btn ${viewMode === 'flow' ? 'active' : ''}`}
              onClick={() => setViewMode('flow')}
              data-testid="toggle-flow-btn"
            >
              🗺️ Pipeline Flow
            </button>
            <button
              className={`mode-btn ${viewMode === 'studio' ? 'active' : ''}`}
              onClick={() => setViewMode('studio')}
              data-testid="toggle-studio-btn"
            >
              🏢 Studio Floor
            </button>
          </div>

          <div className="header-status-chip">
            <span className="status-dot pulse" />
            <span>{companyHealth} [OK]</span>
          </div>
        </div>
      </header>

      {/* Main World Viewport */}
      <main className="world-viewport">
        <div className={`world-main-content ${chatOpen ? 'chat-open' : ''}`}>
          {/* 1. Founder Suite */}
          <FounderSuite
            overview={overview}
            activeWorkersCount={activeWorkersCount}
            totalDeliverables={completedTasksCount}
            qaPassedCount={qaPassedCount}
            healthStatus={companyHealth}
            companyName={companyName}
          />

          {/* 2. CEO Strategy Desk */}
          <CEOStrategyDesk
            onOpenChat={() => setChatOpen(true)}
            onRunQA={activeTask ? () => executeTask(activeTask.id, undefined, true) : undefined}
            activeTaskTitle={activeTask?.title}
            hasQAFailure={hasQAFailure}
            assignedRoles={
              activeTask?.required_roles && activeTask.required_roles.length > 0
                ? activeTask.required_roles
                : activeTask?.assigned_to
                ? [activeTask.assigned_to]
                : []
            }
          />

          {/* 3. Dynamic Canvas: React Flow vs Studio Workstations */}
          <AnimatePresence mode="wait">
            {viewMode === 'flow' ? (
              <motion.div
                key="flow-view"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    Live Autonomous Pipeline
                  </h3>
                  {activeTask && (
                    <button
                      className="btn-secondary"
                      style={{ fontSize: '12px', padding: '4px 10px' }}
                      onClick={() => setSelectedTask(activeTask)}
                      data-testid="inspect-active-task-btn"
                    >
                      Inspect Active Task Dossier ➔
                    </button>
                  )}
                </div>
                <CompanyFlowCanvas
                  activeTask={activeTask}
                  runs={runs}
                  verifications={verifications}
                  onSelectNode={(nodeId) => {
                    if (nodeId === 'node-task' && activeTask) setSelectedTask(activeTask)
                    if (nodeId === 'node-qa' && hasQAFailure) handleRemediateClick()
                  }}
                />
              </motion.div>
            ) : (
              <motion.div
                key="studio-view"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
              >
                <div style={{ marginBottom: '12px' }}>
                  <h3 style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    Workforce Studio Stations ({agents.length} Registered Roles)
                  </h3>
                </div>
                <WorkstationGrid
                  employees={agents}
                  activeTask={activeTask}
                  onSelectEmployee={(emp) => setSelectedEmployee(emp)}
                  hasQAFailure={hasQAFailure}
                  onRemediate={handleRemediateClick}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Real Company Task Directory */}
          {tasks.length > 0 && (
            <section
              style={{
                marginTop: '16px',
                background: 'var(--bg-surface)',
                padding: '20px',
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                <h3 style={{ fontSize: '15px', fontWeight: 700 }}>Company Task Directory</h3>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  {tasks.length} {tasks.length === 1 ? 'task' : 'tasks'} registered
                </span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {tasks.map((task) => (
                  <div
                    key={task.id}
                    onClick={() => setSelectedTask(task)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      background: 'var(--bg-surface-subtle)',
                      borderRadius: 'var(--radius-md)',
                      cursor: 'pointer',
                      border: '1px solid var(--border-subtle)',
                    }}
                    data-testid={`task-row-${task.id}`}
                  >
                    <div>
                      <div style={{ fontWeight: 600, fontSize: '13.5px' }}>{task.title}</div>
                      <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>
                        ID: {task.id} · Assigned: {task.assigned_to || 'Developer'}
                      </div>
                    </div>
                    <span
                      style={{
                        fontSize: '11px',
                        fontWeight: 700,
                        padding: '3px 8px',
                        borderRadius: 'var(--radius-full)',
                        background:
                          task.status === 'COMPLETED'
                            ? 'var(--accent-green-soft)'
                            : task.status === 'IN_PROGRESS'
                            ? 'var(--accent-orange-soft)'
                            : 'var(--bg-surface-subtle)',
                        color:
                          task.status === 'COMPLETED'
                            ? 'var(--accent-green)'
                            : task.status === 'IN_PROGRESS'
                            ? 'var(--accent-orange)'
                            : 'var(--text-secondary)',
                      }}
                    >
                      {task.status}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* 4. Collapsible Persistent Company Chat Drawer */}
        <CompanyChat
          isOpen={chatOpen}
          onClose={() => setChatOpen(false)}
          onToggle={() => setChatOpen(!chatOpen)}
          messages={chatMessages}
          onSendMessage={sendChat}
        />
      </main>

      {/* 5. Modals */}
      {selectedEmployee && (
        <EmployeeDossierModal
          employee={selectedEmployee}
          onClose={() => setSelectedEmployee(null)}
          onDirectTask={(role) => {
            setSelectedEmployee(null)
            handleOpenChatWithPrompt(`Assign priority mission to ${role}`)
          }}
        />
      )}

      {selectedTask && (
        <TaskDossierModal
          task={selectedTask}
          runs={runs}
          verifications={verifications}
          onClose={() => setSelectedTask(null)}
          onExecute={executeTask}
          onRemediate={(taskId) => {
            setSelectedTask(null)
            const t = tasks.find((item) => item.id === taskId)
            if (t) setRemediatingTask(t)
          }}
        />
      )}

      {remediatingTask && (
        <QARemediationModal
          task={remediatingTask}
          verification={latestVerification}
          onClose={() => setRemediatingTask(null)}
          onSubmitRemediation={remediateTask}
        />
      )}
    </div>
  )
}
