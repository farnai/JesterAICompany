import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { api } from '../api/client'
import type {
  CompanyOverview,
  Employee,
  Project,
  Task,
  TaskRun,
  VerificationResult,
  ChatMessage,
} from '../types/company'

export function useCompanyState(pollInterval: number = 4000) {
  // Domain State (Directly from backend CompanyService)
  const [overview, setOverview] = useState<CompanyOverview | null>(null)
  const [agents, setAgents] = useState<Employee[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [runs, setRuns] = useState<TaskRun[]>([])
  const [verifications, setVerifications] = useState<VerificationResult[]>([])
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
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
        tasksData,
        runsData,
        verisData,
        chatData,
      ] = await Promise.all([
        api.getOverview().catch(() => null),
        api.getAgents().catch(() => []),
        api.getProjects().catch(() => []),
        api.getTasks().catch(() => []),
        api.getRuns().catch(() => []),
        api.getVerifications().catch(() => []),
        api.getChatMessages(50).catch(() => ({ messages: [] })),
      ])

      if (overviewData) setOverview(overviewData)
      if (agentsData) setAgents(agentsData)
      if (projectsData) setProjects(projectsData)
      if (tasksData) setTasks(tasksData)
      if (runsData) setRuns(runsData)
      if (verisData) setVerifications(verisData)
      if (chatData?.messages) setChatMessages(chatData.messages)

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

  // Purely Derived Domain Representations (derived from real state, no invented values)
  const companyName = useMemo(() => {
    return overview?.company?.name || overview?.company_name || 'Jester AI Company'
  }, [overview])

  const companyHealth = useMemo(() => {
    return overview?.company?.health || overview?.company?.status || overview?.health || 'OPERATIONAL'
  }, [overview])

  const activeWorkersCount = useMemo(() => {
    if (overview?.counts?.active_employees !== undefined) {
      return overview.counts.active_employees
    }
    return agents.filter((a) => a.status === 'ACTIVE').length
  }, [overview, agents])

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
    return Boolean(latestVerification && !latestVerification.passed)
  }, [latestVerification])

  // Operations
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
    tasks,
    runs,
    verifications,
    chatMessages,
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
    sendChat,
    executeTask,
    remediateTask,
  }
}
