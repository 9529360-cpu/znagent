/**
 * ZN assistant message in the CDS visual language.
 *
 * Why not the vendored AssistantMessageBubble? That component hardcodes the
 * assistant's display name as "Claude" (code-examples/ChatMessageBubbles.tsx),
 * so rendering ZN's replies with it would misattribute ZN's answer to
 * Claude. ZN identifies as ZN. This thin ZN-owned wrapper keeps the CDS
 * assistant presentation (plain text, no user-bubble background, text
 * inset, copy affordance) with the correct "ZN" attribution.
 */
import { useState } from 'react'

import { CdsButton } from './cds'

type Props = {
  text: string
  time?: string
  artifact?: { title: string; kind: string } | null
  onOpenArtifact?: () => void
}

export function ZnAssistantMessage({ text, time, artifact, onOpenArtifact }: Props) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard is a convenience; the message text stays readable.
    }
  }
  return (
    <div data-cds="AssistantMessage" className="flex w-full min-w-0 flex-col gap-1 font-sans">
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-[var(--cds-clay)] text-[10px] font-semibold text-white" aria-hidden="true">ZN</span>
        <span className="text-sm font-semibold text-[var(--cds-text-primary)]">ZN</span>
        {time ? <span className="text-xs text-[var(--cds-text-muted)]">{time}</span> : null}
      </div>
      <div
        className="whitespace-pre-wrap text-[15px] leading-relaxed text-[var(--cds-text-primary)]"
        style={{ paddingLeft: 'var(--cds-assistant-message-text-inset, 4px)' }}
      >
        {text}
      </div>
      <div className="flex flex-wrap gap-2">
        <CdsButton size="sm" type="button" onClick={() => void copy()}>
          {copied ? '✓ Copied' : 'Copy'}
        </CdsButton>
        {artifact && onOpenArtifact ? (
          <CdsButton size="sm" type="button" onClick={onOpenArtifact}>
            View {artifact.title}
          </CdsButton>
        ) : null}
      </div>
    </div>
  )
}
