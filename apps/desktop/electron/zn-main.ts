import { app, dialog } from 'electron'

import { configureZnPackagedRuntime } from './zn-packaged-runtime'

async function bootstrapZnDesktop() {
  if (app.isPackaged) {
    const runtime = configureZnPackagedRuntime({ resourcesPath: process.resourcesPath })
    console.info(
      `[ZN] packaged runtime ${runtime.manifest.runtime_id.slice(0, 12)} ready at ${runtime.root}`
    )
  }

  await import('./main')

  const [{ registerZnResidentIpc, startZnResidentOnDesktopReady }, { registerZnReleaseUpdaterIpc }] =
    await Promise.all([import('./zn-resident-ipc'), import('./zn-release-updater')])

  registerZnResidentIpc()
  registerZnReleaseUpdaterIpc()

  await app.whenReady()
  await startZnResidentOnDesktopReady()
}

void bootstrapZnDesktop().catch(error => {
  const message = error instanceof Error ? error.message : String(error)
  console.error('[ZN] desktop bootstrap failed:', error)

  try {
    dialog.showErrorBox('ZN runtime unavailable', message)
  } catch {
    void 0
  }

  app.quit()
})
