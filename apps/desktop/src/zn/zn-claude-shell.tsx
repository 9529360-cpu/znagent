/**
 * ZN 桌面壳：用 vendor/open-claude-ui 里的组件/令牌原样组建的复原。
 *
 * 组装规则（用户亲定）：
 * - 只做组装，不重新设计、不加自己的审美、不“改进”。
 * - vendor 目录原样不动；这里只 import 它的组件和 cds-theme.css 令牌。
 * - 布局 = 会话列表 + 聊天主区 + 输入框。只留聊天交办 + 有事才现的
 *   待办/审批托盘。账本/控制台/秘书桌不进界面，本文件没有任何这类屏。
 * - 数据只从 props（ZnShellData / ZnShellCallbacks）来；没接后端的地方
 *   渲染空状态 / 加载态，不编造聊天记录、审批卡、待办。
 *
 * 两处与 vendor 原文的必要偏离（不是 redesign，是数据诚实所迫，
 * 原 vendor 文件未动）：
 * 1. 会话列表：vendor 的 DraggableSessionList 把演示会话写死在内部
 *    state 里，且不接受 sessions prop——原样用它会把假会话当成用户
 *    自己的会话展示出来。所以 `ZnSessionList` 按 vendor 同款结构/类名/
 *    拖拽物理重写为 prop 驱动版：数据全从 props 来，拖拽/固定只发回调。
 * 2. 输入框：vendor ChatComposer 的模型菜单写死了 Claude 模型、添加菜单
 *    会模拟出假附件。这里原样用它的 UI，但回调只把用户输入的正文传出，
 *    模型/附件/思考开关不进入数据层（见下方 onSendMessage 适配）。
 *
 * 另有两处 vendor 原文行为由接线层处理（见注释）：
 * - AssistantMessageBubble 头部曾硬编码 "Claude" 字样：接线时已把该
 *   一个渲染字样改成 "ZN"（仅改字样，不动样式；这是 vendor 文件
 *   唯一的例外改动，ZN 必须自称 ZN）。
 * - McpToolDecisionCard 在点“允许”后内部会模拟 1200ms 后翻成成功态，
 *   不代表后端真的执行了；接线层在决定发出后立刻把卡从托盘摘下
 *   （卸载掉模拟态），真实执行状态以后端返回为准。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChatComposer } from '../../../../vendor/open-claude-ui/code-examples/ChatComposer'
import {
  AssistantMessageBubble,
  UserMessageBubble
} from '../../../../vendor/open-claude-ui/code-examples/ChatMessageBubbles'
import { CdsButton } from '../../../../vendor/open-claude-ui/code-examples/CdsButton'
import { ClaudeDesktopHeader } from '../../../../vendor/open-claude-ui/code-examples/ClaudeDesktopHeader'
import { McpToolDecisionCard } from '../../../../vendor/open-claude-ui/code-examples/McpToolDecisionCard'
import {
  QuietDotsWave,
  SkeletonSweep,
  StatusDot
} from '../../../../vendor/open-claude-ui/code-examples/StatusIndicators'
import {
  useZnShellData,
  type ZnApprovalVerdict,
  type ZnShellCallbacks,
  type ZnShellConnection,
  type ZnShellData,
  type ZnShellSession
} from './zn-data-hooks'

export interface ZnClaudeShellProps {
  data: ZnShellData
  callbacks: ZnShellCallbacks
}

/* ------------------------------------------------------------------ */
/* 会话列表：vendor DraggableSessionList 的 prop 驱动版                */
/* 结构 / 类名 / 拖拽物理（4px 死区、幽灵态、落点导轨、Alt+方向键重排）  */
/* 均与 vendor 一致；唯一区别是数据从 props 来、动作只发回调。          */
/* ------------------------------------------------------------------ */

interface ZnSessionListProps {
  sessions: ZnShellSession[]
  activeSessionId: string | null
  loading: boolean
  onSelect: (sessionId: string) => void
  onNew: () => void
  onTogglePin: (sessionId: string) => void
  onReorder: (orderedSessionIds: string[]) => void
}

function ZnSessionList({
  sessions,
  activeSessionId,
  loading,
  onSelect,
  onNew,
  onTogglePin,
  onReorder
}: ZnSessionListProps) {
  // 乐观排序：本地顺序跟随 props 同步，拖拽落点后先本地重排再发回调。
  const [order, setOrder] = useState<string[]>(() => sessions.map(session => session.id))
  useEffect(() => {
    setOrder(current => {
      const known = new Set(sessions.map(session => session.id))
      const kept = current.filter(id => known.has(id))
      const fresh = sessions.map(session => session.id).filter(id => !kept.includes(id))
      if (kept.length === current.length && fresh.length === 0) return current
      return [...kept, ...fresh]
    })
  }, [sessions])

  const ordered = useMemo(() => {
    const byId = new Map(sessions.map(session => [session.id, session]))
    return order.map(id => byId.get(id)).filter((session): session is ZnShellSession => Boolean(session))
  }, [order, sessions])
  const pinnedSessions = ordered.filter(session => session.isPinned)
  const recentSessions = ordered.filter(session => !session.isPinned)

  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [overIndex, setOverIndex] = useState<number | null>(null)
  const [dropPosition, setDropPosition] = useState<'before' | 'after' | null>(null)
  const pointerStartRef = useRef<{ x: number; y: number; id: string } | null>(null)
  const isDraggingRef = useRef(false)

  const handleKeyDown = useCallback(
    (id: string, isPinned: boolean, event: React.KeyboardEvent) => {
      if (!event.altKey || (event.key !== 'ArrowUp' && event.key !== 'ArrowDown')) return
      event.preventDefault()
      // 直接用当前渲染的顺序计算，不在 setState updater 里发回调
      // （updater 在 StrictMode 下可能跑两次，回调会重复发出）。
      const list = ordered.filter(session => session.isPinned === isPinned)
      const currentIndex = list.findIndex(session => session.id === id)
      if (currentIndex === -1) return
      const targetIndex = event.key === 'ArrowUp' ? currentIndex - 1 : currentIndex + 1
      if (targetIndex < 0 || targetIndex >= list.length) return
      const updatedSubList = [...list]
      const [moved] = updatedSubList.splice(currentIndex, 1)
      updatedSubList.splice(targetIndex, 0, moved)
      const next = isPinned
        ? [...updatedSubList, ...ordered.filter(session => !session.isPinned)]
        : [...ordered.filter(session => session.isPinned), ...updatedSubList]
      setOrder(next.map(session => session.id))
      onReorder(next.map(session => session.id))
    },
    [onReorder, ordered]
  )

  const handlePointerDown = (id: string, event: React.PointerEvent) => {
    if (event.button !== 0) return
    pointerStartRef.current = { x: event.clientX, y: event.clientY, id }
    isDraggingRef.current = false
  }

  const handlePointerMove = (event: React.PointerEvent) => {
    if (!pointerStartRef.current) return
    const dx = Math.abs(event.clientX - pointerStartRef.current.x)
    const dy = Math.abs(event.clientY - pointerStartRef.current.y)
    if (!isDraggingRef.current && (dx > 4 || dy > 4)) {
      isDraggingRef.current = true
      setDraggedId(pointerStartRef.current.id)
    }
  }

  const handlePointerUp = () => {
    pointerStartRef.current = null
    isDraggingRef.current = false
    setDraggedId(null)
    setOverIndex(null)
    setDropPosition(null)
  }

  const handleDragStart = (id: string, event: React.DragEvent) => {
    setDraggedId(id)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', id)
  }

  const handleDragOverRow = (idx: number, event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    const rect = event.currentTarget.getBoundingClientRect()
    const midpoint = rect.top + rect.height / 2
    setOverIndex(idx)
    setDropPosition(event.clientY < midpoint ? 'before' : 'after')
  }

  const handleDrop = (targetIdx: number, targetIsPinned: boolean, event: React.DragEvent) => {
    event.preventDefault()
    const draggedSessionId = event.dataTransfer.getData('text/plain') || draggedId
    if (!draggedSessionId) return
    // 一次算出新顺序：本地乐观重排 + 回调发同一份顺序，避免两份计算漂移。
    const removedAt = order.findIndex(id => id === draggedSessionId)
    if (removedAt === -1) return
    const remaining = order.filter(id => id !== draggedSessionId)
    const rawInsertIdx = targetIdx + (dropPosition === 'after' ? 1 : 0)
    const insertIdx = removedAt < rawInsertIdx ? rawInsertIdx - 1 : rawInsertIdx
    const next = [...remaining]
    next.splice(Math.min(Math.max(insertIdx, 0), next.length), 0, draggedSessionId)
    setOrder(next)
    onReorder(next)
    // 跨区拖拽（如从“最近对话”拖入“已固定”）跟随 vendor 语义切换固定态；
    // 固定态归父级所有，这里只发回调，不本地改 props 数据。
    const dragged = sessions.find(session => session.id === draggedSessionId)
    if (dragged && dragged.isPinned !== targetIsPinned) onTogglePin(draggedSessionId)
    handlePointerUp()
  }

  const renderRow = (session: ZnShellSession, globalIdx: number, isPinnedSection: boolean) => {
    const isBeingDragged = draggedId === session.id
    const isOver = overIndex === globalIdx
    return (
      <div key={session.id} className="relative">
        {isOver && dropPosition === 'before' && (
          <div className="absolute -top-0.5 inset-x-0 h-0.5 bg-[var(--cds-fill-brand,#d97757)] rounded-full z-20 pointer-events-none" />
        )}
        <div
          role="listitem"
          tabIndex={0}
          draggable
          onDragStart={event => handleDragStart(session.id, event)}
          onDragOver={event => handleDragOverRow(globalIdx, event)}
          onDrop={event => handleDrop(globalIdx, isPinnedSection, event)}
          onPointerDown={event => handlePointerDown(session.id, event)}
          onKeyDown={event => handleKeyDown(session.id, isPinnedSection, event)}
          onClick={() => onSelect(session.id)}
          className={`group relative flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer transition-all duration-150 ${
            session.id === activeSessionId
              ? 'bg-[var(--cds-bg-selected,#f3ece7)] dark:bg-[var(--cds-bg-selected,#3a2c27)] text-[var(--cds-text-accent,#d97757)] font-medium'
              : 'text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)] hover:bg-[var(--cds-bg-hover,#f2f2ef)] dark:hover:bg-[var(--cds-bg-hover,#20201f)]'
          } ${isBeingDragged ? 'opacity-40 scale-[0.98] border border-dashed border-[var(--cds-fill-brand,#d97757)]' : ''}`}
        >
          <div className="min-w-0 flex-1 truncate pr-1">
            <div className="truncate text-xs">{session.title}</div>
            <div className="text-[10px] text-[var(--cds-text-muted,#8c8c8c)] truncate">{session.updatedAtLabel}</div>
          </div>
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              type="button"
              aria-label={session.isPinned ? '取消固定' : '固定到顶部'}
              onClick={event => {
                event.stopPropagation()
                onTogglePin(session.id)
              }}
              className="p-1 rounded text-xs text-[var(--cds-text-muted,#8c8c8c)] hover:text-[var(--cds-fill-brand,#d97757)] hover:bg-[var(--cds-alpha-1,rgba(0,0,0,0.05))]"
              title={session.isPinned ? '取消固定' : '固定到顶部'}
            >
              📌
            </button>
          </div>
        </div>
        {isOver && dropPosition === 'after' && (
          <div className="absolute -bottom-0.5 inset-x-0 h-0.5 bg-[var(--cds-fill-brand,#d97757)] rounded-full z-20 pointer-events-none" />
        )}
      </div>
    )
  }

  return (
    <nav
      aria-label="会话侧边栏导航"
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      className="flex flex-col w-72 h-full bg-[var(--cds-bg-secondary,#fbfbf9)] dark:bg-[var(--cds-bg-secondary,#141413)] border-r border-[var(--cds-border-subtle,#e8e8e6)] dark:border-[var(--cds-border-subtle,#242423)] select-none text-xs font-sans overflow-hidden"
    >
      <div className="flex items-center justify-between px-3 h-11 border-b border-[var(--cds-border-subtle,#e8e8e6)] dark:border-[var(--cds-border-subtle,#242423)]">
        <span className="font-semibold text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)] text-sm">
          对话列表
        </span>
        <button
          type="button"
          aria-label="新开对话"
          onClick={onNew}
          className="flex items-center gap-1 px-2 py-1 rounded-md bg-[var(--cds-bg-surface,#ffffff)] dark:bg-[var(--cds-bg-surface,#1f1f1e)] border border-[var(--cds-border-subtle,#e5e5e5)] dark:border-[var(--cds-border-subtle,#333)] text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)] hover:bg-[var(--cds-bg-hover,#f5f5f5)] active:scale-95 transition-all shadow-xs"
        >
          <span>＋</span>
          <span className="font-medium">新建</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-4">
        {loading && sessions.length === 0 ? (
          <div className="space-y-2 px-1 pt-1" aria-label="正在加载会话">
            <SkeletonSweep className="h-9 w-full" />
            <SkeletonSweep className="h-9 w-full" />
            <SkeletonSweep className="h-9 w-full" />
          </div>
        ) : null}
        {!loading && sessions.length === 0 ? (
          <div className="px-2 py-4 text-[var(--cds-text-muted,#8c8c8c)]">暂无会话</div>
        ) : null}
        {pinnedSessions.length > 0 && (
          <div>
            <div className="flex items-center justify-between px-2 pb-1 text-[11px] font-semibold text-[var(--cds-text-muted,#8c8c8c)] uppercase tracking-wider">
              <span>已固定 ({pinnedSessions.length})</span>
              <span className="text-[10px] font-normal lowercase">可拖拽重排</span>
            </div>
            <div className="space-y-0.5" role="list">
              {pinnedSessions.map(session => renderRow(session, ordered.findIndex(item => item.id === session.id), true))}
            </div>
          </div>
        )}
        {recentSessions.length > 0 && (
          <div>
            <div className="px-2 pb-1 text-[11px] font-semibold text-[var(--cds-text-muted,#8c8c8c)] uppercase tracking-wider">
              最近对话
            </div>
            <div className="space-y-0.5" role="list">
              {recentSessions.map(session => renderRow(session, ordered.findIndex(item => item.id === session.id), false))}
            </div>
          </div>
        )}
      </div>
    </nav>
  )
}

/* ------------------------------------------------------------------ */
/* 桌面壳本体                                                            */
/* ------------------------------------------------------------------ */

function connectionDot(connection: ZnShellConnection): { kind: 'ready' | 'running' | 'error'; label: string } {
  if (connection === 'live') return { kind: 'ready', label: '已连接' }
  if (connection === 'offline') return { kind: 'error', label: '未连接' }
  return { kind: 'running', label: '连接中' }
}

export function ZnClaudeShell({ data, callbacks }: ZnClaudeShellProps) {
  const activeSession = data.sessions.find(session => session.id === data.activeSessionId) || null
  const dot = connectionDot(data.connection)
  const showTray = data.approvals.length > 0 || data.todos.length > 0

  return (
    <div className="zn-shell dark">
      <ClaudeDesktopHeader title={activeSession ? activeSession.title : 'ZN'}>
        <StatusDot kind={dot.kind} label={dot.label} />
      </ClaudeDesktopHeader>

      <div className="zn-shell-body">
        <ZnSessionList
          sessions={data.sessions}
          activeSessionId={data.activeSessionId}
          loading={data.connection === 'loading'}
          onSelect={callbacks.onSelectSession}
          onNew={callbacks.onNewSession}
          onTogglePin={callbacks.onTogglePin}
          onReorder={callbacks.onReorderSessions}
        />

        <main className="zn-shell-main">
          {/* 待办 / 审批托盘：只有真实待处理项时才出现，平时不在界面上。 */}
          {showTray ? (
            <section className="zn-shell-tray" aria-label="需要你出面">
              <div className="flex items-center justify-between px-4 pt-3 pb-2">
                <span className="text-sm font-semibold text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)]">
                  需要你出面
                </span>
                <span className="text-xs text-[var(--cds-text-muted,#8c8c8c)]">
                  {data.approvals.length > 0 ? `${data.approvals.length} 个审批` : ''}
                  {data.approvals.length > 0 && data.todos.length > 0 ? ' · ' : ''}
                  {data.todos.length > 0 ? `${data.todos.length} 个待办` : ''}
                </span>
              </div>
              <div className="space-y-3 px-4 pb-3">
                {data.approvals.map(approval => (
                  <div key={approval.id} className="space-y-2">
                    <div>
                      <div className="text-sm font-medium text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)]">
                        {approval.title}
                      </div>
                      {approval.detail ? (
                        <div className="text-xs text-[var(--cds-text-muted,#8c8c8c)]">{approval.detail}</div>
                      ) : null}
                    </div>
                    <McpToolDecisionCard
                      toolCall={{
                        id: approval.id,
                        toolName: approval.toolName,
                        serverUrl: approval.serverUrl,
                        inputParams: approval.inputParams as Record<string, unknown>
                      }}
                      onVerdict={(verdict: ZnApprovalVerdict) => callbacks.onApprovalVerdict(approval.id, verdict)}
                    />
                  </div>
                ))}
                {data.todos.map(todo => (
                  <div
                    key={todo.id}
                    className="flex items-center justify-between gap-3 rounded-xl border border-[var(--cds-border,#e8e8e6)] dark:border-[var(--cds-border,#282827)] bg-[var(--cds-surface-1,#ffffff)] dark:bg-[var(--cds-surface-1,#1c1b1a)] px-3.5 py-2.5"
                  >
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)] truncate">
                        {todo.title}
                      </div>
                      {todo.detail ? (
                        <div className="text-xs text-[var(--cds-text-muted,#8c8c8c)] truncate">{todo.detail}</div>
                      ) : null}
                    </div>
                    {todo.actionLabel ? (
                      <CdsButton variant="primary" size="sm" onClick={() => callbacks.onTodoAction(todo.id)}>
                        {todo.actionLabel}
                      </CdsButton>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <div className="zn-shell-messages">
            <div className="mx-auto w-full max-w-3xl px-4 py-4 space-y-4">
              {data.messages.map(message => {
                if (message.role === 'user') {
                  return (
                    <UserMessageBubble
                      key={message.id}
                      text={message.text}
                      time={message.timeLabel}
                      state={message.state ?? 'done'}
                      onRetry={message.state === 'failed' ? () => callbacks.onRetryMessage(message.id) : undefined}
                    />
                  )
                }
                return (
                  <AssistantMessageBubble
                    key={message.id}
                    text={message.text}
                    time={message.timeLabel}
                    modelName={message.modelName ?? 'ZN'}
                    isThinkingLive={message.state === 'pending'}
                  />
                )
              })}

              {/* 空状态 / 加载态：绝不编造消息来填充。 */}
              {data.messages.length === 0 && data.connection === 'loading' ? (
                <div className="zn-shell-empty">
                  <QuietDotsWave label="正在连接 ZN…" />
                </div>
              ) : null}
              {data.messages.length === 0 && data.connection === 'offline' ? (
                <div className="zn-shell-empty">
                  <StatusDot kind="error" label="未连接" />
                  <p className="text-sm text-[var(--cds-text-muted,#8c8c8c)]">
                    后端未连接时不显示任何会话与消息。
                  </p>
                </div>
              ) : null}
              {data.messages.length === 0 && data.connection === 'live' && data.sessions.length === 0 ? (
                <div className="zn-shell-empty">
                  <p className="text-base font-medium text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)]">
                    暂无会话
                  </p>
                  <p className="text-sm text-[var(--cds-text-muted,#8c8c8c)]">新建一个会话，交办第一件事。</p>
                  <CdsButton variant="primary" size="md" onClick={callbacks.onNewSession}>
                    新建会话
                  </CdsButton>
                </div>
              ) : null}
              {data.messages.length === 0 && data.connection === 'live' && data.activeSessionId ? (
                <div className="zn-shell-empty">
                  <p className="text-base font-medium text-[var(--cds-text-primary,#1a1a1a)] dark:text-[var(--cds-text-primary,#f0f0f0)]">
                    向 ZN 交办一件事
                  </p>
                  <p className="text-sm text-[var(--cds-text-muted,#8c8c8c)]">
                    在下方输入框输入一句话，ZN 会接手去办。
                  </p>
                </div>
              ) : null}
            </div>
          </div>

          <div className="zn-shell-composer">
            <ChatComposer
              placeholder="向 ZN 交办一件事…"
              initialModel="ZN"
              onSendMessage={content => {
                // 只传正文：vendor 输入框的模型/附件菜单不进入数据层。
                callbacks.onSendMessage(content)
              }}
            />
          </div>
        </main>
      </div>
    </div>
  )
}

/** 桌面渲染根：接数据钩子 → 渲染壳。main.tsx 只渲染它。 */
export function ZnDesktopRoot() {
  const { data, callbacks } = useZnShellData()
  return <ZnClaudeShell data={data} callbacks={callbacks} />
}
