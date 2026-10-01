import React, { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { RolePortrait } from './Portraits'
import type { Task, TaskRun, VerificationResult } from '../types/company'

// =============================================================================
// CUSTOM NODE COMPONENTS — WARM DAYLIGHT DIGITAL WORKPLACE
// =============================================================================

function FounderCustomNode({ data }: NodeProps) {
  return (
    <div className="flow-custom-node founder-node" data-testid="flow-node-founder">
      <Handle type="source" position={Position.Bottom} style={{ background: '#F95924' }} />
      <div className="flow-avatar-wrapper">
        <RolePortrait role="owner" size={38} />
      </div>
      <div>
        <div className="flow-node-tag summit-pill">COMPANY SUMMIT</div>
        <div className="flow-node-title">Founder / Owner</div>
        <div className="flow-node-subtitle">{String(data.label || 'Mission Intent & Governance')}</div>
      </div>
    </div>
  )
}

function CEOCustomNode({ data }: NodeProps) {
  return (
    <div className="flow-custom-node ceo-node active" data-testid="flow-node-ceo">
      <Handle type="target" position={Position.Top} style={{ background: '#F95924' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#F95924' }} />
      <div className="flow-avatar-wrapper">
        <RolePortrait role="ceo" size={38} />
      </div>
      <div>
        <div className="flow-node-tag coord-pill">EXECUTIVE COORDINATOR</div>
        <div className="flow-node-title">CEO Strategy Desk</div>
        <div className="flow-node-subtitle">{String(data.label || 'Strategy & Allocation')}</div>
      </div>
    </div>
  )
}

function TaskCustomNode({ data }: NodeProps) {
  const isStandby = !data.hasTask
  const statusStr = String(data.status || 'STANDBY').toUpperCase()
  const isCompleted = statusStr === 'COMPLETED'
  const isInProgress = statusStr === 'IN_PROGRESS'

  let badgeColor = 'var(--text-muted)'
  let badgeBg = 'var(--bg-surface-subtle)'
  if (isCompleted) {
    badgeColor = 'var(--accent-green)'
    badgeBg = 'var(--accent-green-soft)'
  } else if (isInProgress) {
    badgeColor = 'var(--accent-orange)'
    badgeBg = 'var(--accent-orange-soft)'
  }

  return (
    <div
      className={`flow-custom-node task-node ${isStandby ? 'standby' : 'active'}`}
      data-testid="flow-node-task"
    >
      <Handle type="target" position={Position.Top} style={{ background: '#F95924' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#F95924' }} />
      <div className="flow-task-icon">📋</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="flow-node-tag-row">
          <span className="flow-node-tag work-pill">CURRENT WORK</span>
          <span
            className="flow-node-status-chip"
            style={{ color: badgeColor, background: badgeBg }}
          >
            {statusStr}
          </span>
        </div>
        <div
          className="flow-node-title text-truncate"
          title={String(data.title || 'No Active Task')}
        >
          {String(data.title || 'No Active Task')}
        </div>
        <div className="flow-node-subtitle">
          {data.hasTask ? 'Active Mission Mandate' : 'All systems standing by'}
        </div>
      </div>
    </div>
  )
}

function WorkerCustomNode({ data }: NodeProps) {
  const role = String(data.role || 'developer')
  const isStandby = data.status === 'IDLE'
  const isCompleted = data.status === 'COMPLETED'

  return (
    <div
      className={`flow-custom-node worker-node ${isStandby ? 'quiet-node' : 'active'}`}
      data-testid="flow-node-worker"
      data-testid-role={`flow-node-worker-${role}`}
    >
      <Handle type="target" position={Position.Top} style={{ background: '#F95924' }} />
      <Handle type="source" position={Position.Bottom} style={{ background: '#10B981' }} />
      <div className="flow-avatar-wrapper">
        <RolePortrait role={role} size={38} />
      </div>
      <div>
        <div className="flow-node-tag worker-pill">SPECIALIST BENCH</div>
        <div className="flow-node-title">{String(data.name || 'Specialist')}</div>
        <div
          className="flow-node-subtitle"
          style={{ color: isCompleted ? 'var(--accent-green)' : isStandby ? 'var(--text-muted)' : 'var(--accent-orange)' }}
        >
          {isCompleted ? '✓ Work Finished' : isStandby ? 'Ready for Mandates' : String(data.label || 'Active Allocation')}
        </div>
      </div>
    </div>
  )
}

function DeliverableCustomNode({ data }: NodeProps) {
  const isReady = data.hasArtifact
  return (
    <div
      className={`flow-custom-node deliverable-node ${isReady ? 'ready' : ''}`}
      data-testid="flow-node-deliverable"
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: isReady ? '#10B981' : 'var(--border-strong)' }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: isReady ? '#10B981' : 'var(--border-strong)' }}
      />
      <div className="flow-deliverable-icon">{isReady ? '📦' : '⏳'}</div>
      <div>
        <div className="flow-node-tag artifact-pill">DELIVERABLE ARTIFACT</div>
        <div className="flow-node-title">{String(data.label || 'Work Deliverables')}</div>
        <div className="flow-node-subtitle" style={{ color: isReady ? 'var(--accent-green)' : 'var(--text-muted)' }}>
          {String(data.path || (isReady ? 'Generated Artifact' : 'Pending Execution'))}
        </div>
      </div>
    </div>
  )
}

function QACustomNode({ data }: NodeProps) {
  const isFailed = data.status === 'FAILED'
  const isPassed = data.status === 'PASSED'
  const badgeClass = isFailed ? 'failed' : isPassed ? 'verified' : 'standby'

  return (
    <div className={`flow-custom-node qa-node ${badgeClass}`} data-testid="flow-node-qa">
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: isFailed ? '#EF4444' : isPassed ? '#10B981' : 'var(--border-strong)' }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ background: isFailed ? '#EF4444' : isPassed ? '#10B981' : 'var(--border-strong)' }}
      />
      <Handle id="remediate" type="source" position={Position.Right} style={{ background: '#EF4444' }} />
      <div className="flow-avatar-wrapper">
        <RolePortrait role="qa_engineer" size={38} />
      </div>
      <div>
        <div className="flow-node-tag qa-pill">QA VERIFICATION GATE</div>
        <div className="flow-node-title">QA Verification</div>
        <div
          className="flow-node-subtitle"
          style={{
            color: isFailed ? '#EF4444' : isPassed ? '#10B981' : 'var(--text-muted)',
            fontWeight: 600,
          }}
        >
          {isFailed ? 'REMEDIATION NEEDED' : isPassed ? 'CRITERIA PASSED' : 'STANDBY'}
        </div>
      </div>
    </div>
  )
}

function ResultCustomNode({ data }: NodeProps) {
  const isFailed = data.status === 'FAILED'
  const isPassed = data.status === 'PASSED'

  return (
    <div
      className={`flow-custom-node result-node ${isFailed ? 'failed' : isPassed ? 'verified' : 'standby'}`}
      data-testid="flow-node-result"
    >
      <Handle
        type="target"
        position={Position.Top}
        style={{ background: isFailed ? '#EF4444' : isPassed ? '#10B981' : 'var(--border-strong)' }}
      />
      <div className="flow-result-icon">{isFailed ? '⚠️' : isPassed ? '🚀' : '⏳'}</div>
      <div>
        <div className="flow-node-tag result-pill">COMPANY RESULT</div>
        <div className="flow-node-title">
          {isFailed ? 'Verification Issue' : isPassed ? 'Deliverable Shipped' : 'Awaiting Release'}
        </div>
        <div className="flow-node-subtitle">{String(data.label || 'Standby')}</div>
      </div>
    </div>
  )
}

// =============================================================================
// MAIN FLOW COMPONENT — DYNAMIC REAL-STATE ADAPTATION
// =============================================================================

interface CompanyFlowCanvasProps {
  activeTask?: Task | null
  runs?: TaskRun[]
  verifications?: VerificationResult[]
  onSelectNode?: (nodeId: string) => void
}

export const CompanyFlowCanvas: React.FC<CompanyFlowCanvasProps> = ({
  activeTask,
  runs = [],
  verifications = [],
  onSelectNode,
}) => {
  const latestRun = runs.length > 0 ? runs[runs.length - 1] : null
  const latestVeri = verifications.length > 0 ? verifications[verifications.length - 1] : null
  const hasFailedQA = latestVeri ? !latestVeri.passed : false
  const hasPassedQA = latestVeri ? latestVeri.passed : false

  // 1. Dynamic active roles derived from real Task and Team state
  const activeRoles: string[] = useMemo(() => {
    if (!activeTask) return ['developer']
    const roles: string[] = []
    if (activeTask.required_roles && activeTask.required_roles.length > 0) {
      roles.push(...activeTask.required_roles)
    } else if (activeTask.assigned_to) {
      roles.push(activeTask.assigned_to)
    } else {
      roles.push('developer')
    }
    // Filter QA out of worker list so QA stays at dedicated verification gate
    const workerRoles = roles.filter(
      (r) => !r.toLowerCase().includes('qa')
    )
    return workerRoles.length > 0 ? workerRoles : ['developer']
  }, [activeTask])

  // 2. Check if QA stage is required
  const requiresQA = useMemo(() => {
    if (!activeTask) return true // default standby includes verification gate
    if (verifications.length > 0) return true
    if (activeTask.required_roles?.some((r) => r.toLowerCase().includes('qa'))) return true
    // Development tasks require QA verification
    if (activeRoles.some((r) => r.toLowerCase().includes('dev') || r.toLowerCase().includes('ux'))) {
      return true
    }
    return verifications.length > 0
  }, [activeTask, activeRoles, verifications])

  const nodeTypes = useMemo(
    () => ({
      founderNode: FounderCustomNode,
      ceoNode: CEOCustomNode,
      taskNode: TaskCustomNode,
      workerNode: WorkerCustomNode,
      deliverableNode: DeliverableCustomNode,
      qaNode: QACustomNode,
      resultNode: ResultCustomNode,
    }),
    []
  )

  // 3. Construct Dynamic Node Topology based on Real State
  const nodes: Node[] = useMemo(() => {
    const runNum = latestRun?.attempt_number || latestRun?.run_number || (latestRun ? 1 : 0)
    const resultList: Node[] = []
    let currentY = 20

    // Top: Founder Summit
    resultList.push({
      id: 'node-founder',
      type: 'founderNode',
      position: { x: 380, y: currentY },
      data: { label: 'Mission Intent & Governance' },
    })
    currentY += 90

    // Central Coordinator: CEO
    resultList.push({
      id: 'node-ceo',
      type: 'ceoNode',
      position: { x: 380, y: currentY },
      data: {
        label: 'Workforce Strategy & Allocation',
      },
    })
    currentY += 90

    // Current Work: Task
    resultList.push({
      id: 'node-task',
      type: 'taskNode',
      position: { x: 380, y: currentY },
      data: {
        hasTask: Boolean(activeTask),
        title: activeTask?.title || 'No Active Task',
        status: activeTask?.status || 'STANDBY',
        goal: activeTask?.goal,
      },
    })
    currentY += 90

    // Active Employees: Dynamic subset
    activeRoles.forEach((role, idx) => {
      const nodeId = idx === 0 ? 'node-worker' : `node-worker-${role}`
      const cleanRole = role.replace(/_/g, ' ')
      const roleDisplayName =
        cleanRole.charAt(0).toUpperCase() + cleanRole.slice(1) + ' Specialist'

      resultList.push({
        id: nodeId,
        type: 'workerNode',
        position: { x: 380, y: currentY },
        data: {
          role,
          name: roleDisplayName,
          status: activeTask ? (activeTask.status === 'COMPLETED' ? 'COMPLETED' : 'ACTIVE') : 'IDLE',
          label: idx === 0 ? 'Primary Specialist Bench' : 'Collaborative Specialist Bench',
        },
      })
      currentY += 90
    })

    // Deliverable Artifact
    resultList.push({
      id: 'node-deliverable',
      type: 'deliverableNode',
      position: { x: 380, y: currentY },
      data: {
        hasArtifact: Boolean(latestRun),
        label: 'Work Deliverables',
        path: runNum > 0 ? `Run #${runNum} Artifacts` : 'Pending Execution',
      },
    })
    currentY += 90

    // QA Verification Gate (if required)
    if (requiresQA) {
      resultList.push({
        id: 'node-qa',
        type: 'qaNode',
        position: { x: 380, y: currentY },
        data: {
          status: hasFailedQA ? 'FAILED' : hasPassedQA ? 'PASSED' : 'STANDBY',
          summary: latestVeri?.summary,
        },
      })
      currentY += 90
    }

    // Company Result
    resultList.push({
      id: 'node-result',
      type: 'resultNode',
      position: { x: 380, y: currentY },
      data: {
        status: hasFailedQA ? 'FAILED' : hasPassedQA ? 'PASSED' : 'STANDBY',
        label: hasFailedQA
          ? 'Awaiting QA Remediation'
          : hasPassedQA
          ? 'Validated Production Ready'
          : 'Awaiting Release Verification',
      },
    })

    return resultList
  }, [activeTask, activeRoles, requiresQA, latestRun, hasFailedQA, hasPassedQA, latestVeri])

  // 4. Construct Semantic State Connections
  const edges: Edge[] = useMemo(() => {
    const list: Edge[] = []

    // Founder -> CEO
    list.push({
      id: 'e-f-ceo',
      source: 'node-founder',
      target: 'node-ceo',
      animated: true,
      style: { stroke: '#F95924', strokeWidth: 2 },
    })

    // CEO -> Task
    list.push({
      id: 'e-ceo-task',
      source: 'node-ceo',
      target: 'node-task',
      animated: Boolean(activeTask),
      style: { stroke: '#F95924', strokeWidth: 2 },
    })

    // Task -> First Worker
    list.push({
      id: 'e-task-worker',
      source: 'node-task',
      target: 'node-worker',
      animated: Boolean(activeTask),
      style: { stroke: '#F95924', strokeWidth: 2 },
    })

    // Worker chain (if multiple roles)
    for (let i = 0; i < activeRoles.length - 1; i++) {
      const fromId = i === 0 ? 'node-worker' : `node-worker-${activeRoles[i]}`
      const toId = `node-worker-${activeRoles[i + 1]}`
      list.push({
        id: `e-w-${i}-${i + 1}`,
        source: fromId,
        target: toId,
        animated: Boolean(activeTask),
        style: { stroke: '#F95924', strokeWidth: 2 },
      })
    }

    // Last Worker -> Deliverable
    const lastWorkerId =
      activeRoles.length > 1
        ? `node-worker-${activeRoles[activeRoles.length - 1]}`
        : 'node-worker'

    list.push({
      id: 'e-worker-deliv',
      source: lastWorkerId,
      target: 'node-deliverable',
      animated: Boolean(latestRun),
      style: { stroke: '#10B981', strokeWidth: 2 },
    })

    // Deliverable -> QA (or Deliverable -> Result if QA not required)
    if (requiresQA) {
      list.push({
        id: 'e-deliv-qa',
        source: 'node-deliverable',
        target: 'node-qa',
        animated: Boolean(latestRun),
        style: { stroke: '#10B981', strokeWidth: 2 },
      })

      // QA -> Result
      list.push({
        id: 'e-qa-result',
        source: 'node-qa',
        target: 'node-result',
        animated: false,
        style: {
          stroke: hasFailedQA ? '#EF4444' : hasPassedQA ? '#10B981' : '#DCDCD4',
          strokeWidth: 2,
        },
      })

      // Remediation feedback loop when QA failed
      if (hasFailedQA) {
        list.push({
          id: 'e-qa-remediate',
          source: 'node-qa',
          sourceHandle: 'remediate',
          target: lastWorkerId,
          animated: true,
          label: 'Remediate Issues',
          labelStyle: { fill: '#EF4444', fontWeight: 700, fontSize: 11 },
          style: { stroke: '#EF4444', strokeWidth: 2, strokeDasharray: '5,5' },
        })
      }
    } else {
      list.push({
        id: 'e-deliv-result',
        source: 'node-deliverable',
        target: 'node-result',
        animated: Boolean(latestRun),
        style: { stroke: '#10B981', strokeWidth: 2 },
      })
    }

    return list
  }, [activeTask, activeRoles, requiresQA, latestRun, hasFailedQA, hasPassedQA])

  return (
    <div className="flow-container" data-testid="flow-canvas-container">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        onNodeClick={(_, node) => onSelectNode?.(node.id)}
      >
        <Background color="#EAEAE4" gap={20} size={1} />
        <Controls />
      </ReactFlow>
    </div>
  )
}
