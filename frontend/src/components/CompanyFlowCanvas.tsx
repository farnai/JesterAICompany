import React from 'react'
import { CompanyFloor } from './CompanyFloor'
import type { Task, TaskRun, VerificationResult, CompanyRun, Employee } from '../types/company'

interface CompanyFlowCanvasProps {
  activeTask?: Task | null
  runs?: TaskRun[]
  verifications?: VerificationResult[]
  onSelectNode?: (nodeId: string) => void
  run?: CompanyRun | null
  employees?: Employee[]
  onInspectArtifact?: (artifactPath: string) => void
  onOpenApproval?: () => void
}

/**
 * CompanyFlowCanvas — Pure React DOM + SVG Overlay implementation (STEP 21).
 * Completely replaces legacy React Flow with responsive DOM layout and lightweight SVG connectors.
 */
export const CompanyFlowCanvas: React.FC<CompanyFlowCanvasProps> = ({
  activeTask,
  runs = [],
  verifications = [],
  onSelectNode,
  run,
  employees = [],
  onInspectArtifact,
  onOpenApproval,
}) => {
  // Synthesize or adapt CompanyRun if not directly passed
  const effectiveRun: CompanyRun = run || {
    run_id: activeTask?.id || 'run_current',
    state: activeTask?.status === 'COMPLETED' ? 'COMPLETED' : activeTask ? 'RUNNING' : 'STANDBY',
    project_id: activeTask?.project_id || 'prj_jester',
    objective: activeTask
      ? {
          id: activeTask.id,
          title: activeTask.title,
          constraints: activeTask.constraints || [],
        }
      : null,
    created_at: new Date().toISOString(),
    selected_agents: activeTask?.required_roles || (activeTask ? ['developer', 'qa'] : []),
    skipped_agents: ['product', 'research', 'ux', 'marketing', 'developer', 'qa'].filter(
      (r) => !(activeTask?.required_roles || (activeTask ? ['developer', 'qa'] : [])).includes(r)
    ),
    selection_reasoning: activeTask ? 'Engineered specialized task allocation.' : 'Standby for objectives.',
    qa_verdict: verifications.length > 0 ? (verifications[verifications.length - 1].passed ? 'PASS' : 'FAIL') : null,
  }

  // Fallback synthetic employee summaries for QA verdict if failed
  const hasFailedQA = verifications.some((v) => !v.passed)
  if (hasFailedQA) {
    effectiveRun.qa_verdict = 'FAIL'
  }

  return (
    <div
      onClick={(e) => {
        const target = e.target as HTMLElement
        const node = target.closest('[data-testid^="flow-node-"]')
        if (node) {
          const testId = node.getAttribute('data-testid')
          if (testId && onSelectNode) {
            onSelectNode(testId.replace('flow-', ''))
          }
        }
      }}
    >
      <CompanyFloor
        run={effectiveRun}
        employees={employees}
        onInspectArtifact={onInspectArtifact}
        onOpenApproval={onOpenApproval}
        activeTask={activeTask}
        taskRuns={runs}
        verifications={verifications}
      />
    </div>
  )
}
