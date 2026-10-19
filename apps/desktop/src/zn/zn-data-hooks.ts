/**
 * ZN 桌面壳的数据钩子接口（Data Hooks）。
 *
 * 这是 UI 与后端之间的唯一缝合处。`ZnClaudeShell` 只认这份接口，
 * 不直接调用 resident / IPC / fetch。接线工人只需把 `useZnShellData`
 * 的实现换成真实后端调用（resident-client / window.znDesktop），
 * UI 文件不需要动。
 *
 * 数据诚实规则（硬性）：
 * - 没接后端的地方返回空数组 / loading / offline，不许编造会话、
 *   消息、审批、待办来“撑场面”。
 * - 审批 / 待办托盘只在有真实待处理项时才出现；没有时不渲染空托盘。
 * - 账本是助理内部记账，永远不进这份接口、不进界面。
 */

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
  /** 审批裁决。ZN 后端若没有 always_allow 语义，接线层把 always_allow 当 allow_once 处理并记录。 */
  onApprovalVerdict: (approvalId: string, verdict: ZnApprovalVerdict) => void
  onTodoAction: (todoId: string) => void
  onRetryMessage: (messageId: string) => void
}

export interface ZnShellHook {
  data: ZnShellData
  callbacks: ZnShellCallbacks
}

/**
 * 数据钩子桩：组装阶段的默认实现。
 *
 * 返回 loading + 全空数据，不编造任何会话/消息/审批/待办。
 * 接线工人实现真实版时，保持返回值类型不变，UI 不需要任何改动。
 * 参考实现（接线时对照）：旧 `workbench.tsx` 里的 resident-client 调用
 * （loadZnWorkThreads / loadZnApprovals / startZnWork 等）就是真实数据源。
 */
export function useZnShellData(): ZnShellHook {
  return {
    data: {
      connection: 'loading',
      sessions: [],
      activeSessionId: null,
      messages: [],
      approvals: [],
      todos: []
    },
    callbacks: {
      onSelectSession: () => undefined,
      onNewSession: () => undefined,
      onTogglePin: () => undefined,
      onReorderSessions: () => undefined,
      onSendMessage: () => undefined,
      onApprovalVerdict: () => undefined,
      onTodoAction: () => undefined,
      onRetryMessage: () => undefined
    }
  }
}
