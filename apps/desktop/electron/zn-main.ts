import { app } from 'electron'

// Keep the mature desktop shell intact while ZN takes ownership of the new
// resident lifecycle around it. The legacy main module remains an implementation
// dependency during migration, not the identity/control plane of the product.
import './main'
import { registerZnResidentIpc, startZnResidentOnDesktopReady } from './zn-resident-ipc'

registerZnResidentIpc()

void app.whenReady().then(async () => {
  await startZnResidentOnDesktopReady()
})
