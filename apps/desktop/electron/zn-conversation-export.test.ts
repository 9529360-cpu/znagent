import { describe, expect, it } from 'vitest'
import { znConversationExportPayload, znExportConversation, znExportFilename } from '../src/zn/conversation-export'

const thread = {
  id: 'work-1', title: '讨论 / Work', createdAt: 0, updatedAt: 10, artifacts: [],
  messages: [
    { id: 'm1', role: 'user', text: 'Hello', at: 0 },
    { id: 'm2', role: 'activity', text: 'calling tool', at: 1, detail: { secret: 'NOT_FOR_EXPORT', token: 'sensitive' } },
    { id: 'm3', role: 'zn', text: 'Done', at: 2, detail: { password: 'private', tool_args: 'sensitive' } }
  ],
  workspace: { name: 'Secret workspace', path: '/private/secrets', attachedAt: 3 }
} as const

describe('ZN conversation export', () => {
  it('exports only user-visible conversation and excludes tool arguments, paths, and internal details', () => {
    for (const format of ['json', 'markdown'] as const) {
      const exported = znExportConversation(thread, format)
      expect(exported).toContain('Hello')
      expect(exported).toContain('Done')
      expect(exported).not.toContain('NOT_FOR_EXPORT')
      expect(exported).not.toContain('sensitive')
      expect(exported).not.toContain('/private/secrets')
      expect(exported).not.toContain('calling tool')
      expect(exported).not.toContain('password')
    }
  })

  it('produces well-formed JSON with stable roles and timestamps', () => {
    expect(JSON.parse(znExportConversation(thread, 'json'))).toEqual(znConversationExportPayload(thread))
    expect(znConversationExportPayload(thread).messages.map(message => message.role)).toEqual(['user', 'assistant'])
    expect(znConversationExportPayload(thread).messages[0].at).toBe('1970-01-01T00:00:00.000Z')
  })

  it('uses an extension-appropriate, path-safe filename', () => {
    expect(znExportFilename(thread, 'json')).toMatch(/\.json$/)
    expect(znExportFilename(thread, 'markdown')).toMatch(/\.md$/)
    expect(znExportFilename(thread, 'markdown')).not.toContain('/')
  })
})
