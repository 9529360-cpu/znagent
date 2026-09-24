import { ipcMain, type IpcMainInvokeEvent, type WebContents } from 'electron'

type ZnDesktopIpcHandler = (
  event: IpcMainInvokeEvent,
  ...args: any[]
) => unknown | Promise<unknown>

const trustedWebContentsIds = new Set<number>()

export function trustZnDesktopWebContents(contents: WebContents): () => void {
  const id = contents.id
  trustedWebContentsIds.add(id)

  const revoke = () => {
    trustedWebContentsIds.delete(id)
  }
  contents.once('destroyed', revoke)
  return revoke
}

export function assertZnDesktopIpcSender(event: IpcMainInvokeEvent): void {
  const frame = event.senderFrame
  if (
    !frame ||
    frame !== frame.top ||
    frame !== event.sender.mainFrame ||
    !trustedWebContentsIds.has(event.sender.id)
  ) {
    throw new Error('untrusted ZN desktop IPC sender')
  }
}

export function handleZnDesktopIpc(
  channel: string,
  handler: ZnDesktopIpcHandler
): void {
  ipcMain.handle(channel, (event, ...args) => {
    assertZnDesktopIpcSender(event)
    return handler(event, ...args)
  })
}
