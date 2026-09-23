import { promises as fs } from 'node:fs'
import path from 'node:path'

import { BrowserWindow, dialog, type OpenDialogOptions } from 'electron'

import { handleZnDesktopIpc } from './zn-ipc-trust'
import { getZnResidentProcess } from './zn-resident-ipc'

let registered = false

function threadIdFrom(payload: unknown): string {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return ''
  const value = payload as Record<string, unknown>
  return String(value.threadId || value.thread_id || '').trim()
}

export function registerZnWorkspaceIpc(): void {
  if (registered) return
  registered = true

  handleZnDesktopIpc('zn:workspaces:attach', async (event, payload) => {
    const threadId = threadIdFrom(payload)
    if (!threadId) throw new Error('threadId is required')

    const options: OpenDialogOptions = {
      title: 'Attach workspace folder',
      properties: ['openDirectory']
    }
    const owner = BrowserWindow.fromWebContents(event.sender)
    const selection = owner
      ? await dialog.showOpenDialog(owner, options)
      : await dialog.showOpenDialog(options)
    if (selection.canceled || selection.filePaths.length === 0) {
      return { cancelled: true }
    }

    // Canonicalize in the trusted Electron process before the resident records
    // the association. The renderer never supplies an arbitrary host path for
    // the normal attach flow; it only asks the OS-native picker for a directory.
    const resolved = await fs.realpath(selection.filePaths[0])
    const stat = await fs.stat(resolved)
    if (!stat.isDirectory()) throw new Error('Selected workspace is not a directory')

    const thread = await getZnResidentProcess().request('work_attach_workspace', {
      thread_id: threadId,
      workspace_path: resolved,
      workspace_name: path.basename(resolved) || resolved,
      message_limit: 120
    })
    return { cancelled: false, thread }
  })

  handleZnDesktopIpc('zn:workspaces:detach', async (_event, payload) => {
    const threadId = threadIdFrom(payload)
    if (!threadId) throw new Error('threadId is required')
    return getZnResidentProcess().request('work_detach_workspace', {
      thread_id: threadId,
      message_limit: 120
    })
  })
}
