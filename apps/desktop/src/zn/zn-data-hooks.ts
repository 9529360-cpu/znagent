/**
 * ZN 桌面壳的数据钩子接口（Data Hooks）。
 *
 * 这是 UI 与后端之间的唯一缝合处。`ZnClaudeShell` 只认这份接口，
 * 不直接调用 resident / IPC / fetch。`useZnShellData` 经
 * `resident-client.ts` 调渲染层唯一后端入口，
 * 再经现有 IPC + `ZnResidentProcess` 到 Resident；不建新控制面，
 * 不新增 channel，不写第三个 socket 客户端。
 *
 * 接线口径：
 * - 聊天交办走 `work_start`（转向语义），不用阻塞式 `work_submit`。
 * - 审批走 `approval_list` / `approval_decide`，决定只发一次；
 *   `always_allow` 是后端真实语义（放行本次 + 建 auto-allow 规则），
 *   直接用，不降级成 `allow_once`；`deny` 粘性由后端保证。
 * - 待办来自 `suggestions_list`（建议点击走同一条 Work 流程：
 *   有 thread 的续跑已有 Work，无 thread 的新建一个归属明确的
 *   会话再交办，绝不建孤儿任务）。
 * - 轮询按规格节奏：快照 12s、审批 30s、单个 Work 进度 700ms
 *   只读轮询（`observeZnWorkProgress`），重连用 `active_run`
 *   重新 attach 已有事件，永不重发用户任务。
 * - 会话固定 / 排序状态归本钩子所有（后端 `ZnThread` 没有 pin
 *   字段）；跨区拖拽同时发 `onReorder` + `onTogglePin` 时，
 *   本钩子按“先重排、再切换固定态”归一，并对重排顺序去重。
 * - 审批决定发出后，被决定的卡立刻从托盘摘下（直到后端刷新确认），
 *   这样 vendor `McpToolDecisionCard` 内部 1200ms 后模拟的成功态
 *   永远不会被展示——真实执行状态以后端返回为准。决定若没送达，
 *   卡会放回托盘供重试。
 *
 * 数据诚实规则（硬性）：
 * - 没接后端的地方返回空数组 / loading / offline，不许编造会话、
 *   消息、审批、待办来“撑场面”。
 * - 审批 / 待办托盘只在有真实待处理项时才出现；没有时不渲染空托盘。
 * - 账本是助理内部记账，永远不进这份接口、不进界面。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  createZnWorkThread,
  decideZnApproval,
  loadZnApprovals,
  loadZnResidentSnapshot,
  loadZnSuggestions,
  loadZnWorkProgress,
  loadZnWorkThread,
  loadZnWorkThreads,
  startZnWork,
  type ZnSuggestion
} from './resident-client'
import { newZnThread, titleForZnTask, type ZnThread } from './state'
import { observeZnWorkProgress } from './work-reconnection'

/** 后端连接状态：loading = 还没拿到首批真实数据；offline = 后端答不上来。 */
export type ZnShellConnection = 'loading' | 'live' | 'offline'

export interface ZnShellSession {
  /** 后端真实会话 id（Work thread id）。 */
  id: string
  /** 后端给的标题；没有标题时接线工人传后端默认值，不许现编。 */
  title: string
  /** 已格式化好的时间文案，如“10 分钟前”；格式化由接线层做。 */
  updatedAtLabel: string
  isPinned: boolean
  isUnread?: boolean
}

export interface ZnShellMessage {
  id: string
  role: 'user' | 'assistant'
  /** 真实消息正文。 */
  text: string
  timeLabel?: string
  /** 助手消息的模型名；不传则显示 ZN。 */
  modelName?: string
  state?: 'pending' | 'failed' | 'done'
}

export type ZnApprovalVerdict = 'allow_once' | 'always_allow' | 'deny'

export interface ZnShellApproval {
  /** 后端真实审批 id。 */
  id: string
  /** 给主人看的标题，如“允许读取文件”。 */
  title: string
  /** 补充说明；没有则不传，不许编。 */
  detail?: string
  /** 待审批的动作名，如 file_read / shell_run；映射到审批卡的工具名。 */
  toolName: string
  /** 动作来源，如 "zn://approval"；没有则不传。 */
  serverUrl?: string
  /** 待审批的入参原文，后端给什么就展示什么。 */
  inputParams: Record<string, unknown>
}

/** 需要主人出面的待办（非审批类，如“需要你确认一句话”）。 */
export interface ZnShellTodo {
  id: string
  title: string
  detail?: string
  /** 为空时只展示、不渲染操作按钮。 */
  actionLabel?: string
}

export interface ZnShellData {
  connection: ZnShellConnection
  sessions: ZnShellSession[]
  /** null = 尚未选中任何会话（空状态）。 */
  activeSessionId: string | null
  /** 当前会话的真实消息；未选中会话时为空数组。 */
  messages: ZnShellMessage[]
  /** 待处理的审批；为空时托盘不出现。 */
  approvals: ZnShellApproval[]
  /** 待处理的待办；为空时托盘不出现。 */
  todos: ZnShellTodo[]
}

export interface ZnShellCallbacks {
  onSelectSession: (sessionId: string) => void
  onNewSession: () => void
  onTogglePin: (sessionId: string) => void
  /** 会话拖拽重排后的完整新顺序（id 数组）；持久化由接线层做。 */
  onReorderSessions: (orderedSessionIds: string[]) => void
  /** 只传用户输入的正文。vendor 输入框的模型/附件菜单是展示层，不进入数据。 */
  onSendMessage: (text: string) => void
  /** 审批裁决。只发一次；always_allow 用后端真实语义，不降级。 */
  onApprovalVerdict: (approvalId: string, verdict: ZnApprovalVerdict) => void
  onTodoAction: (todoId: string) => void
  onRetryMessage: (messageId: string) => void
}

export interface ZnShellHook {
  data: ZnShellData
  callbacks: ZnShellCallbacks
}

function formatRelativeTime(at: number): string {
  const diff = Date.now() - at
  if (!Number.isFinite(diff) || diff < 0) return '刚刚'
  const minute = 60_000
  const hour = 3_600_000
  const day = 86_400_000
  if (diff < minute) return '刚刚'
  if (diff < hour) return `${Math.floor(diff / minute)} 分钟前`
  if (diff < day) return `${Math.floor(diff / hour)} 小时前`
  if (diff < 30 * day) return `${Math.floor(diff / day)} 天前`
  const date = new Date(at)
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const dayOfMonth = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${dayOfMonth}`
}

function formatTimeLabel(at: number): string {
  const date = new Date(at)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function threadToSession(thread: ZnThread, isPinned: boolean): ZnShellSession {
  return {
    id: thread.id,
    title: thread.title,
    updatedAtLabel: formatRelativeTime(thread.updatedAt),
    isPinned
  }
}

function threadMessagesToShell(thread: ZnThread): ZnShellMessage[] {
  // 壳只有 user / assistant 两种消息；activity 是执行过程记录，
  // 没有聊天槽位，不混进对话。
  return thread.messages
    .filter(message => message.role === 'user' || message.role === 'zn')
    .map(message => ({
      id: message.id,
      role: message.role === 'user' ? 'user' as const : 'assistant' as const,
      text: message.text,
      timeLabel: formatTimeLabel(message.at),
      state: 'done' as const
    }))
}

function approvalToShell(
  approval: { id: string; actionKind: string; target: string; scope: string; valueText: string; source: string; diffText: string }
): ZnShellApproval {
  const inputParams: Record<string, unknown> = {
    action_kind: approval.actionKind,
    target: approval.target,
    scope: approval.scope,
    source: approval.source
  }
  if (approval.valueText) inputParams.value_text = approval.valueText
  // CUR-4 diff 先行评审：卡上能看到待批改动的 diff。
  if (approval.diffText) inputParams.diff_text = approval.diffText
  const detail = [approval.scope, approval.valueText].filter(Boolean).join(' — ')
  return {
    id: approval.id,
    title: approval.target ? `${approval.actionKind} · ${approval.target}` : approval.actionKind,
    ...(detail ? { detail } : {}),
    toolName: approval.actionKind,
    serverUrl: 'zn://approval',
    inputParams
  }
}

function suggestionToTodo(suggestion: ZnSuggestion): ZnShellTodo {
  return {
    id: suggestion.key,
    title: suggestion.title,
    detail: suggestion.source.label,
    actionLabel: '执行'
  }
}

function optimisticId(): string {
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 审批决定发出后、后端刷新确认前的遮蔽窗口：卡被摘下，过期放回。 */
const DECIDED_APPROVAL_TTL_MS = 60_000

type RunningWork = {
  threadId: string
  eventId: string
}

/**
 * 真实数据钩子：全部接 Resident 后端。
 *
 * 状态分三层：服务端快照（threads / pending 审批 / 建议）是真理；
 * 本地乐观消息只在“已发送、服务端快照还没回来”的窗口里补位，
 * 服务端快照一到就以服务端为准；固定/排序是纯本地 UI 状态，
 * 由本钩子持有，不写回后端。
 */
export function useZnShellData(): ZnShellHook {
  const [connection, setConnection] = useState<ZnShellConnection>('loading')
  const [threads, setThreads] = useState<ZnThread[]>([])
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)
  const [pendingApprovals, setPendingApprovals] = useState<
    Array<{ id: string; actionKind: string; target: string; scope: string; valueText: string; source: string; diffText: string }>
  >([])
  const [suggestions, setSuggestions] = useState<ZnSuggestion[]>([])
  const [startedSuggestionKeys, setStartedSuggestionKeys] = useState<string[]>([])
  /** 已决定、等后端确认的审批 id → 决定发出的时间戳。 */
  const [decidedApprovals, setDecidedApprovals] = useState<Record<string, number>>({})
  /** threadId → 尚未被服务端快照确认的本地乐观消息。 */
  const [optimistic, setOptimistic] = useState<Record<string, ZnShellMessage[]>>({})
  const [running, setRunning] = useState<RunningWork | null>(null)
  const [progressAssistantText, setProgressAssistantText] = useState('')
  /** 固定态归本钩子所有：已固定的会话 id。 */
  const [pinned, setPinned] = useState<string[]>([])
  /** 排序归本钩子所有：会话 id 的完整顺序（去重后）。 */
  const [sessionOrder, setSessionOrder] = useState<string[]>([])

  const sendingRef = useRef(false)
  const decidingRef = useRef(new Set<string>())

  /* ---------------- 快照 / 审批轮询 ---------------- */

  const refreshSnapshot = useCallback(async () => {
    try {
      const [_snapshot, nextThreads, nextSuggestions] = await Promise.all([
        loadZnResidentSnapshot(),
        loadZnWorkThreads(),
        loadZnSuggestions().catch(() => null)
      ])
      // 建议是 Resident 派生状态：拉取失败保留上一次的，不清空、不编造。
      if (nextSuggestions !== null) {
        setSuggestions(nextSuggestions)
        // 已执行过的建议不再出现；服务端已不再列出的 key 顺手收掉。
        setStartedSuggestionKeys(current =>
          current.filter(key => nextSuggestions.some(item => item.key === key))
        )
      }
      setThreads(nextThreads)
      setActiveThreadId(current => {
        if (current && nextThreads.some(thread => thread.id === current)) return current
        return nextThreads[0]?.id ?? null
      })
      setConnection('live')
    } catch {
      setConnection('offline')
    }
  }, [])

  const refreshApprovals = useCallback(async () => {
    try {
      const list = await loadZnApprovals()
      setPendingApprovals(list.pending)
      // 刷新即真理：已不在 pending 里的决定不再遮蔽；还在 pending
      // 里、且遮蔽未过期的，继续遮蔽直到后端确认或决定超时。
      setDecidedApprovals(current => {
        const pendingIds = new Set(list.pending.map(item => item.id))
        const now = Date.now()
        const next: Record<string, number> = {}
        for (const [id, decidedAt] of Object.entries(current)) {
          if (pendingIds.has(id) && now - decidedAt < DECIDED_APPROVAL_TTL_MS) next[id] = decidedAt
        }
        return next
      })
    } catch {
      // 审批拉取失败保留上一次的列表，不把托盘清空成“没事了”。
    }
  }, [])

  useEffect(() => {
    void refreshSnapshot()
    void refreshApprovals()
  }, [refreshSnapshot, refreshApprovals])

  // 快照 12s；审批 30s。Resident 无推送，全部轮询。
  useEffect(() => {
    const timer = window.setInterval(() => void refreshSnapshot(), 12_000)
    return () => window.clearInterval(timer)
  }, [refreshSnapshot])

  useEffect(() => {
    const timer = window.setInterval(() => void refreshApprovals(), 30_000)
    return () => window.clearInterval(timer)
  }, [refreshApprovals])

  /* ---------------- Work 进度：重连 + 700ms 只读轮询 ---------------- */

  // 发现已有事件：用 thread.activeRun 重新 attach，绝不重发用户任务。
  useEffect(() => {
    if (!activeThreadId) return
    const thread = threads.find(item => item.id === activeThreadId)
    const activeRun = thread?.activeRun
    if (!activeRun) return
    setRunning(current => {
      if (current && current.threadId === activeRun.threadId && current.eventId === activeRun.eventId) {
        return current
      }
      return { threadId: activeRun.threadId, eventId: activeRun.eventId }
    })
  }, [threads, activeThreadId])

  useEffect(() => {
    if (!running) return
    return observeZnWorkProgress(
      running,
      loadZnWorkProgress,
      update => {
        if (update.progress.assistantResponse) {
          setProgressAssistantText(update.progress.assistantResponse)
        }
        if (update.thread) {
          setThreads(current =>
            current.map(item => (item.id === update.thread?.id ? update.thread : item))
          )
        }
        if (update.progress.finalized || update.progress.terminal) {
          setRunning(null)
          setProgressAssistantText('')
          // 审批可能在执行中产生：收尾时刷新一次，让卡及时出现。
          void refreshApprovals()
          if (!update.thread) {
            void loadZnWorkThread(update.progress.threadId)
              .then(thread => {
                setThreads(current =>
                  current.map(item => (item.id === thread.id ? thread : item))
                )
              })
              .catch(() => undefined)
          }
        }
      },
      // 进度轮询是只读观察：瞬时错误只退避重试，不翻连接状态。
      () => undefined
    )
  }, [running, refreshApprovals])

  /* ---------------- 发消息 ---------------- */

  const sendToThread = useCallback(async (threadId: string, task: string, localId: string) => {
    try {
      const started = await startZnWork(threadId, task)
      // 服务端快照已含刚发的用户消息：撤下对应的本地乐观消息。
      setOptimistic(current => ({
        ...current,
        [threadId]: (current[threadId] ?? []).filter(message => message.id !== localId)
      }))
      setThreads(current =>
        current.map(item => (item.id === started.thread.id ? started.thread : item))
      )
      if (started.progress.finalized || started.progress.terminal) {
        setRunning(null)
        setProgressAssistantText('')
        void refreshApprovals()
      } else {
        setRunning({ threadId: started.thread.id, eventId: started.progress.eventId })
        if (started.progress.assistantResponse) {
          setProgressAssistantText(started.progress.assistantResponse)
        }
      }
    } catch {
      // 发送失败：把乐观消息标为失败，壳上出现重试按钮。
      setOptimistic(current => ({
        ...current,
        [threadId]: (current[threadId] ?? []).map(message =>
          message.id === localId ? { ...message, state: 'failed' as const } : message
        )
      }))
    }
  }, [refreshApprovals])

  const appendOptimistic = useCallback((threadId: string, text: string): string => {
    const id = optimisticId()
    const message: ZnShellMessage = {
      id,
      role: 'user',
      text,
      timeLabel: formatTimeLabel(Date.now()),
      state: 'done'
    }
    setOptimistic(current => ({
      ...current,
      [threadId]: [...(current[threadId] ?? []), message]
    }))
    return id
  }, [])

  /* ---------------- 派生数据 ---------------- */

  const sessions = useMemo<ZnShellSession[]>(() => {
    const byId = new Map(threads.map(thread => [thread.id, thread]))
    const known = threads.map(thread => thread.id)
    const ordered = [
      ...sessionOrder.filter(id => byId.has(id)),
      ...known.filter(id => !sessionOrder.includes(id))
    ]
    const pinnedSet = new Set(pinned)
    // 稳定排序：已固定在前，其余保持接线层顺序。
    const sorted = [...ordered].sort(
      (left, right) => Number(pinnedSet.has(right)) - Number(pinnedSet.has(left))
    )
    return sorted.map(id => threadToSession(byId.get(id) as ZnThread, pinnedSet.has(id)))
  }, [threads, sessionOrder, pinned])

  const messages = useMemo<ZnShellMessage[]>(() => {
    const activeThread = threads.find(thread => thread.id === activeThreadId)
    const serverMessages = activeThread ? threadMessagesToShell(activeThread) : []
    const local = activeThreadId ? (optimistic[activeThreadId] ?? []) : []
    // 补位去重：服务端已含同样正文的用户消息时，不重复展示本地那份。
    const extra = local.filter(
      item => !serverMessages.some(
        server => server.role === 'user' && server.text === item.text
      )
    )
    const combined = [...serverMessages, ...extra]
    // 执行中的事件：挂一条 pending 助手消息当思考指示，
    // 正文只用进度里真实返回的 assistantResponse，不编。
    if (running && running.threadId === activeThreadId) {
      combined.push({
        id: `pending-${running.eventId}`,
        role: 'assistant',
        text: progressAssistantText,
        state: 'pending'
      })
    }
    return combined
  }, [threads, activeThreadId, optimistic, running, progressAssistantText])

  const approvals = useMemo<ZnShellApproval[]>(() => {
    const now = Date.now()
    return pendingApprovals
      .filter(item => {
        const decidedAt = decidedApprovals[item.id]
        // 已决定且在遮蔽窗口内的卡不展示（屏蔽 vendor 的模拟成功态）；
        // 遮蔽过期或决定没送达的，放回托盘。
        return decidedAt === undefined || now - decidedAt >= DECIDED_APPROVAL_TTL_MS
      })
      .map(approvalToShell)
  }, [pendingApprovals, decidedApprovals])

  const todos = useMemo<ZnShellTodo[]>(() => {
    const started = new Set(startedSuggestionKeys)
    return suggestions
      .filter(item => !started.has(item.key))
      .map(suggestionToTodo)
  }, [suggestions, startedSuggestionKeys])

  /* ---------------- 回调 ---------------- */

  const onSelectSession = useCallback((sessionId: string) => {
    setActiveThreadId(sessionId)
    void loadZnWorkThread(sessionId)
      .then(thread => {
        setThreads(current =>
          current.map(item => (item.id === thread.id ? thread : item))
        )
      })
      .catch(() => undefined)
  }, [])

  const onNewSession = useCallback(() => {
    void (async () => {
      try {
        const created = await createZnWorkThread(newZnThread())
        setThreads(current => [created, ...current])
        setActiveThreadId(created.id)
      } catch {
        // 建不出会话说明后端答不上来；不留幻影会话。
        setConnection('offline')
      }
    })()
  }, [])

  const onTogglePin = useCallback((sessionId: string) => {
    setPinned(current =>
      current.includes(sessionId)
        ? current.filter(id => id !== sessionId)
        : [...current, sessionId]
    )
  }, [])

  const onReorderSessions = useCallback((orderedSessionIds: string[]) => {
    // 归一：去重（保留首次出现），固定态由 onTogglePin 单独管。
    const seen = new Set<string>()
    const deduped = orderedSessionIds.filter(id => {
      if (seen.has(id)) return false
      seen.add(id)
      return true
    })
    setSessionOrder(deduped)
  }, [])

  const onSendMessage = useCallback((text: string) => {
    const task = text.trim()
    if (!task || sendingRef.current) return
    void (async () => {
      sendingRef.current = true
      try {
        // 没有选中会话时：优先用已有的第一个会话，否则新建。
        let threadId = activeThreadId
        if (!threadId) threadId = threads[0]?.id ?? null
        if (!threadId) {
          const created = await createZnWorkThread({
            ...newZnThread(),
            title: titleForZnTask(task)
          })
          setThreads(current => [created, ...current])
          setActiveThreadId(created.id)
          threadId = created.id
        }
        const localId = appendOptimistic(threadId, task)
        await sendToThread(threadId, task, localId)
      } catch {
        setConnection('offline')
      } finally {
        sendingRef.current = false
      }
    })()
  }, [activeThreadId, threads, appendOptimistic, sendToThread])

  const onApprovalVerdict = useCallback((approvalId: string, verdict: ZnApprovalVerdict) => {
    // 决定只发一次：在途的重复点击直接忽略。
    if (decidingRef.current.has(approvalId)) return
    decidingRef.current.add(approvalId)
    // 先摘卡：vendor 卡内部 1200ms 模拟成功态随卸载一起消失。
    setDecidedApprovals(current => ({ ...current, [approvalId]: Date.now() }))
    void (async () => {
      try {
        // always_allow 直接用后端真实语义，不降级成 allow_once。
        await decideZnApproval(approvalId, verdict)
      } catch {
        // 决定没送达：把卡放回托盘，让主人可以重试。
        setDecidedApprovals(current => {
          const next = { ...current }
          delete next[approvalId]
          return next
        })
      } finally {
        decidingRef.current.delete(approvalId)
      }
      await refreshApprovals()
    })()
  }, [refreshApprovals])

  const onTodoAction = useCallback((todoId: string) => {
    const suggestion = suggestions.find(item => item.key === todoId)
    if (!suggestion || sendingRef.current) return
    void (async () => {
      sendingRef.current = true
      try {
        let threadId = suggestion.threadId
        if (!threadId) {
          // 非 Work 建议：新建一个归属明确的会话再交办，不建孤儿任务。
          const created = await createZnWorkThread({
            ...newZnThread(),
            title: suggestion.title
          })
          setThreads(current => [created, ...current])
          setActiveThreadId(created.id)
          threadId = created.id
        } else {
          setActiveThreadId(threadId)
        }
        const localId = appendOptimistic(threadId, suggestion.task)
        await sendToThread(threadId, suggestion.task, localId)
        // 旧工作台同款：执行成功后本地隐藏该建议，不调 dismiss。
        setStartedSuggestionKeys(current =>
          current.includes(suggestion.key) ? current : [...current, suggestion.key]
        )
      } catch {
        setConnection('offline')
      } finally {
        sendingRef.current = false
      }
    })()
  }, [suggestions, appendOptimistic, sendToThread])

  const onRetryMessage = useCallback((messageId: string) => {
    if (!activeThreadId || sendingRef.current) return
    const failed = (optimistic[activeThreadId] ?? []).find(
      item => item.id === messageId && item.state === 'failed'
    )
    if (!failed) return
    const threadId = activeThreadId
    const task = failed.text
    setOptimistic(current => ({
      ...current,
      [threadId]: (current[threadId] ?? []).filter(item => item.id !== messageId)
    }))
    void (async () => {
      sendingRef.current = true
      try {
        const localId = appendOptimistic(threadId, task)
        await sendToThread(threadId, task, localId)
      } finally {
        sendingRef.current = false
      }
    })()
  }, [activeThreadId, optimistic, appendOptimistic, sendToThread])

  const data = useMemo<ZnShellData>(() => ({
    connection,
    sessions,
    activeSessionId: activeThreadId,
    messages,
    approvals,
    todos
  }), [connection, sessions, activeThreadId, messages, approvals, todos])

  const callbacks = useMemo<ZnShellCallbacks>(() => ({
    onSelectSession,
    onNewSession,
    onTogglePin,
    onReorderSessions,
    onSendMessage,
    onApprovalVerdict,
    onTodoAction,
    onRetryMessage
  }), [
    onSelectSession,
    onNewSession,
    onTogglePin,
    onReorderSessions,
    onSendMessage,
    onApprovalVerdict,
    onTodoAction,
    onRetryMessage
  ])

  return { data, callbacks }
}
