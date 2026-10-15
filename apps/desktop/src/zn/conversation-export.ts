import type { ZnThread, ZnThreadMessage } from './state'

export type ZnConversationExportFormat = 'markdown' | 'json'

/**
 * User-initiated export of the visible conversation transcript.
 * Security boundary: do not serialize the entire Resident thread, internal
 * activity detail, local filesystem paths, credentials, or tool arguments.
 * The user may choose to share an exported file, so include only the
 * conversation content already visible in the transcript.
 */
export function znConversationExportPayload(thread: ZnThread) {
  return {
    format: 'zn-conversation-v1' as const,
    threadId: thread.id,
    title: thread.title,
    messages: thread.messages
      .filter((message): message is ZnThreadMessage => message.role === 'user' || message.role === 'zn')
      .map(message => ({
        role: message.role === 'user' ? 'user' as const : 'assistant' as const,
        text: message.text,
        at: new Date(message.at).toISOString()
      }))
  }
}

export function znExportConversation(thread: ZnThread, format: ZnConversationExportFormat): string {
  const payload = znConversationExportPayload(thread)
  if (format === 'json') return JSON.stringify(payload, null, 2) + '\n'
  const heading = payload.title.replace(/[\r\n]+/g, ' ').trim() || 'ZN conversation'
  const messages = payload.messages.map(message => {
    const role = message.role === 'user' ? 'You' : 'ZN'
    return '## ' + role + ' · ' + message.at + '\n\n' + message.text.trim() + '\n'
  })
  return '# ' + heading + '\n\n' + messages.join('\n')
}

export function znExportFilename(thread: ZnThread, format: ZnConversationExportFormat): string {
  const stem = thread.title.normalize('NFKC')
    .replace(/[^a-zA-Z0-9\u4e00-\u9fff_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60) || 'conversation'
  return stem + '.' + (format === 'json' ? 'json' : 'md')
}
