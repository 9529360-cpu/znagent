import path from 'node:path'

import { stampExeIdentity } from './set-exe-identity.mjs'

/** Stamp ZN Windows executable resources after electron-builder packs it. */
export default async function afterPack(context) {
  if (context.electronPlatformName !== 'win32') return

  const productName = context.packager?.appInfo?.productFilename || 'ZN'
  const exe = path.join(context.appOutDir, `${productName}.exe`)
  const desktopRoot = path.resolve(import.meta.dirname, '..')

  try {
    await stampExeIdentity(exe, desktopRoot)
  } catch (err) {
    // PE resource stamping is cosmetic; a failure must not hide a valid pack.
    console.warn(`[after-pack] exe identity stamp failed (${err.message}); ZN.exe keeps the stock Electron icon`)
  }
}
