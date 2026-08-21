import { app } from 'electron'

// Keep the mature desktop shell intact while ZN takes ownership of the new
// resident lifecycle around it. The legacy main module remains an implementation
// dependency during migration, not the identity/control plane of the product.
import './main'
import {
  getZnResidentProcess,
  registerZnResidentIpc,
  startZnResidentOnDesktopReady
} from './zn-resident-ipc'
import { ZnVisualSense } from './zn-visual-sense'

registerZnResidentIpc()

let visualSense: ZnVisualSense | null = null

void app.whenReady().then(async () => {
  await startZnResidentOnDesktopReady()
  visualSense = new ZnVisualSense(getZnResidentProcess())
  visualSense.start()
})

app.on('before-quit', () => {
  visualSense?.stop()
  visualSense = null
})
