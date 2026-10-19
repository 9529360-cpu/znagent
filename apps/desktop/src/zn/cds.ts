/**
 * ZN wrapper barrel for the vendored open-claude-ui components.
 *
 * Only components whose props are fully driven by caller data are re-exported
 * here. Components with hardcoded demo data or simulated execution are
 * deliberately NOT re-exported (see PR description):
 *
 * - DraggableSessionList: owns its own hardcoded INITIAL_SESSIONS; rendering
 *   it would show fake sessions. The ZN session list is a thin zn/ wrapper
 *   styled with CDS tokens and fed only by resident workList data.
 * - RichComposerWithMentions: hardcoded DEFAULT_SLASH_COMMANDS (Claude
 *   commands) and DEFAULT_MENTIONS (fake files). ZN's composer is a thin
 *   zn/ wrapper; `@specialist` steering still goes through the existing
 *   parseZnTeamMention + assignZnTeamSpecialist path.
 * - ChatComposer: hardcoded CLAUDE_MODELS picker. ZN's model comes from the
 *   resident provider settings, never from a Claude model menu.
 * - McpToolDecisionCard: simulates tool execution (setTimeout -> success)
 *   and offers an "always allow" affordance. ZN restore approval is
 *   single-use and resident-verified, so the approval uses
 *   ConfirmationDialog instead; no persistent approval is ever offered.
 * - AssistantMessageBubble: hardcodes the assistant display name as
 *   "Claude". ZN replies must be attributed to ZN, so the assistant
 *   message is a thin zn/ wrapper (zn-assistant-message.tsx) in the same
 *   CDS visual language with the correct "ZN" attribution.
 * - createClaudeMainWindow: reference only, imports electron. ZN's
 *   Electron main (electron/zn-main.ts) stays ZN-owned and is never
 *   replaced by it.
 *
 * Vendored files are never edited. When ZN needs different behaviour, the
 * wrapper lives in apps/desktop/src/zn, not in vendor/.
 */
export { CdsButton } from '../../../../vendor/open-claude-ui/code-examples/CdsButton'
export type {
  ButtonSize,
  ButtonVariant,
  CdsButtonProps
} from '../../../../vendor/open-claude-ui/code-examples/CdsButton'
export { ConfirmationDialog } from '../../../../vendor/open-claude-ui/code-examples/ConfirmationDialog'
export type {
  ConfirmationDialogProps,
  DialogSize
} from '../../../../vendor/open-claude-ui/code-examples/ConfirmationDialog'
export { SegmentedControl } from '../../../../vendor/open-claude-ui/code-examples/SegmentedControl'
export type {
  SegmentedControlProps,
  SegmentedTabItem
} from '../../../../vendor/open-claude-ui/code-examples/SegmentedControl'
export {
  ClayBreatheDot,
  PulseRunningDot,
  QuietDotsWave,
  SkeletonSweep,
  StatusDot
} from '../../../../vendor/open-claude-ui/code-examples/StatusIndicators'
export type { StatusDotKind } from '../../../../vendor/open-claude-ui/code-examples/StatusIndicators'
export {
  UserMessageBubble
} from '../../../../vendor/open-claude-ui/code-examples/ChatMessageBubbles'
export type {
  AttachmentPreview,
  UserMessageProps
} from '../../../../vendor/open-claude-ui/code-examples/ChatMessageBubbles'
export { ThinkingAccordion } from '../../../../vendor/open-claude-ui/code-examples/ThinkingAccordion'
export type { ThinkingAccordionProps } from '../../../../vendor/open-claude-ui/code-examples/ThinkingAccordion'
export { CodeBlock } from '../../../../vendor/open-claude-ui/code-examples/CodeBlock'
export type { CodeBlockProps } from '../../../../vendor/open-claude-ui/code-examples/CodeBlock'
export { ScrollFadeContainer } from '../../../../vendor/open-claude-ui/code-examples/ScrollFadeContainer'
export type { ScrollFadeContainerProps } from '../../../../vendor/open-claude-ui/code-examples/ScrollFadeContainer'
export { ClaudeDesktopHeader } from '../../../../vendor/open-claude-ui/code-examples/ClaudeDesktopHeader'
