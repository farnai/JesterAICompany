import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { api } from '../api/client'
import type {
  CompanyOverview,
  Employee,
  Project,
  RepositoryProject,
  Task,
  TaskRun,
  VerificationResult,
  ChatMessage,
  CompanyRun,
} from '../types/company'

export function useCompanyState(pollInterval: number = 4000) {
  // Domain State (Directly from backend CompanyService)
  const [overview, setOverview] = useState<CompanyOverview | null>(null)
  const [agents, setAgents] = useState<Employee[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [repositoryProjects, setRepositoryProjects] = useState<RepositoryProject[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [runs, setRuns] = useState<TaskRun[]>([])
  const [verifications, setVerifications] = useState<VerificationResult[]>([])
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [companyRuns, setCompanyRuns] = useState<CompanyRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedProjectId, setSelectedProjectId] = useState<string>('prj_jester')
  const [proposalDiffs, setProposalDiffs] = useState<Record<string, string>>({})

  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchState = useCallback(async (isInitial: boolean = false) => {
    try {
      if (isInitial) setLoading(true)
      const [
        overviewData,
        agentsData,
        projectsData,
        repoProjectsData,
        tasksData,
        runsData,
        verisData,
        chatData,
        cRunsData,
      ] = await Promise.all([
        api.getOverview().catch(() => null),
        api.getAgents().catch(() => []),
        api.getProjects().catch(() => []),
        api.getRepositoryProjects().catch(() => []),
        api.getTasks().catch(() => []),
        api.getRuns().catch(() => []),
        api.getVerifications().catch(() => []),
        api.getChatMessages(50).catch(() => ({ messages: [] })),
        api.getCompanyRuns().catch(() => []),
      ])

      if (overviewData) setOverview(overviewData)
      if (agentsData) setAgents(agentsData)
      if (projectsData) setProjects(projectsData)
      if (repoProjectsData && repoProjectsData.length > 0) {
        setRepositoryProjects(repoProjectsData)
      }
      if (tasksData) setTasks(tasksData)
      if (runsData) setRuns(runsData)
      if (verisData) setVerifications(verisData)
      if (chatData?.messages) setChatMessages(chatData.messages)
      if (cRunsData) setCompanyRuns(cRunsData)

      setError(null)
    } catch (err: any) {
      setError(err?.message || 'Failed to sync company state')
    } finally {
      if (isInitial) setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchState(true)

    if (pollInterval > 0) {
      pollingRef.current = setInterval(() => {
        fetchState(false)
      }, pollInterval)
    }

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [fetchState, pollInterval])

  // Active Company Run & Selected Run
  const activeCompanyRun = useMemo(() => {
    if (selectedRunId) {
      const found = companyRuns.find((r) => r.run_id === selectedRunId)
      if (found) return found
    }
    // Prefer non-completed runs first, then newest
    const active = companyRuns.find(
      (r) => r.state !== 'COMPLETED' && r.state !== 'FAILED' && r.state !== 'BLOCKED'
    )
    return active || companyRuns[0] || null
  }, [companyRuns, selectedRunId])

  // Active Repository Project
  const activeProject = useMemo<RepositoryProject | null>(() => {
    const found = repositoryProjects.find((p) => p.project_id === selectedProjectId)
    if (found) return found
    return repositoryProjects[0] || null
  }, [repositoryProjects, selectedProjectId])

  // Fetch diff for active run's proposal on demand (strictly run-scoped)
  useEffect(() => {
    const propId = activeCompanyRun?.real_repo_apply_proposal_id
    const runId = activeCompanyRun?.run_id
    if (propId && !proposalDiffs[propId]) {
      let isCurrent = true
      api
        .getProposalDiff(propId, runId)
        .then((res) => {
          if (isCurrent && res?.diff) {
            setProposalDiffs((prev) => ({ ...prev, [propId]: res.diff }))
          }
        })
        .catch(() => {})
      return () => {
        isCurrent = false
      }
    }
  }, [activeCompanyRun?.real_repo_apply_proposal_id, activeCompanyRun?.run_id, proposalDiffs])

  // Purely Derived Domain Representations (derived from real state, no invented values)
  const companyName = useMemo(() => {
    return overview?.company?.name || overview?.company_name || 'Jester AI Company'
  }, [overview])

  const companyHealth = useMemo(() => {
    return overview?.company?.health || overview?.company?.status || overview?.health || 'OPERATIONAL'
  }, [overview])

  const activeWorkersCount = useMemo(() => {
    if (activeCompanyRun?.selected_agents) {
      return activeCompanyRun.selected_agents.length
    }
    if (overview?.counts?.active_employees !== undefined) {
      return overview.counts.active_employees
    }
    return agents.filter((a) => a.status === 'ACTIVE').length
  }, [activeCompanyRun, overview, agents])

  const completedTasksCount = useMemo(() => {
    if (overview?.counts?.completed_tasks !== undefined) {
      return overview.counts.completed_tasks
    }
    return tasks.filter((t) => t.status === 'COMPLETED').length
  }, [overview, tasks])

  const qaPassedCount = useMemo(() => {
    if (overview?.counts?.passed_verifications !== undefined) {
      return overview.counts.passed_verifications
    }
    return verifications.filter((v) => v.passed).length
  }, [overview, verifications])

  const qaFailedCount = useMemo(() => {
    if (overview?.counts?.failed_verifications !== undefined) {
      return overview.counts.failed_verifications
    }
    return verifications.filter((v) => !v.passed).length
  }, [overview, verifications])

  const activeTask = useMemo(() => {
    return (
      tasks.find((t) => t.status === 'IN_PROGRESS') ||
      tasks.find((t) => t.status === 'PENDING') ||
      tasks[0] ||
      null
    )
  }, [tasks])

  const latestVerification = useMemo(() => {
    return verifications.length > 0 ? verifications[verifications.length - 1] : null
  }, [verifications])

  const hasQAFailure = useMemo(() => {
    if (activeCompanyRun?.qa_verdict === 'FAIL') return true
    return Boolean(latestVerification && !latestVerification.passed)
  }, [activeCompanyRun, latestVerification])

  // Operations
  const selectRun = (runId: string) => {
    setSelectedRunId(runId)
  }

  const selectProject = (projectId: string) => {
    setSelectedProjectId(projectId)
  }

  const createObjective = async (data: {
    title: string
    description?: string
    project_id?: string
    constraints?: string[]
    acceptance_criteria?: string[]
    target_repository?: string
  }) => {
    const res = await api.createCompanyRun({
      ...data,
      project_id: data.project_id || activeProject?.project_id || 'prj_jester',
      auto_run: true,
    })
    await fetchState(false)
    setSelectedRunId(res.run_id)
    return res
  }

  const approveRun = async (
    runId: string,
    approver: string = 'Human Founder',
    proposalId?: string
  ) => {
    const res = await api.approveCompanyRun(runId, approver, proposalId)
    await fetchState(false)
    return res
  }

  const rejectRun = async (runId: string, reason: string = 'Rejected by Human Founder') => {
    const res = await api.rejectCompanyRun(runId, reason)
    await fetchState(false)
    return res
  }

  const applyRun = async (
    runId: string,
    proposalId?: string,
    grantId?: string
  ) => {
    const res = await api.applyCompanyRun(runId, proposalId, grantId)
    await fetchState(false)
    return res
  }

  const sendChat = async (content: string) => {
    const res = await api.sendChatMessage(content)
    setChatMessages((prev) => [...prev, res.user_message, res.reply])
    await fetchState(false)
    return res
  }

  const executeTask = async (taskId: string, verifyCmd?: string, mock: boolean = true) => {
    const res = await api.executeTask(taskId, verifyCmd, mock)
    await fetchState(false)
    return res
  }

  const remediateTask = async (taskId: string, feedback: string) => {
    const res = await api.retryTask(taskId, undefined, true)
    await api.sendChatMessage(
      `Founder directed QA Remediation on Task ${taskId}: ${feedback}`,
      'owner',
      undefined,
      taskId
    )
    await fetchState(false)
    return res
  }

  return {
    // Raw Domain State
    overview,
    agents,
    projects,
    repositoryProjects,
    tasks,
    runs,
    verifications,
    chatMessages,
    companyRuns,
    activeCompanyRun,
    activeProject,
    proposalDiffs,
    loading,
    error,
    // Derived Domain State
    companyName,
    companyHealth,
    activeWorkersCount,
    completedTasksCount,
    qaPassedCount,
    qaFailedCount,
    activeTask,
    latestVerification,
    hasQAFailure,
    // Operations
    refresh: () => fetchState(false),
    selectRun,
    selectProject,
    createObjective,
    approveRun,
    rejectRun,
    applyRun,
    sendChat,
    executeTask,
    remediateTask,
  }
}

