export type ZnWorkbenchShortcut = 'send' | 'search' | 'stop'

export type ZnShortcutKey = {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  altKey: boolean
  shiftKey: boolean
  isComposing?: boolean
  repeat?: boolean
}

/**
 * Keyboard-only presentation intent. The renderer may ask the Resident to
 * cancel Work, but must never fabricate a completed or cancelled outcome.
 */
export function znWorkbenchShortcut(event: ZnShortcutKey): ZnWorkbenchShortcut | null {
  if (event.isComposing || event.repeat) return null
  const command = event.metaKey || event.ctrlKey
  if (event.altKey || event.shiftKey) return null
  if (command && event.key === 'Enter') return 'send'
  if (command && event.key.toLowerCase() === 'k') return 'search'
  if (!command && event.key === 'Escape') return 'stop'
  return null
}

export function znPlainEnterToSend(event: ZnShortcutKey): boolean {
  return !event.isComposing && !event.repeat &&
    event.key === 'Enter' && !event.metaKey && !event.ctrlKey &&
    !event.altKey && !event.shiftKey
}
