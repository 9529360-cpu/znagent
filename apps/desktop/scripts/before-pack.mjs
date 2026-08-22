import { existsSync, renameSync, rmSync } from 'node:fs'
import path from 'node:path'
import { Arch } from 'electron-builder'

import { stageGetWindows, stageNodePty } from './stage-native-deps.mjs'

/** Remove a stale electron-builder unpacked directory before a fresh pack. */
export function cleanStaleAppOutDir(appOutDir) {
  if (!appOutDir || typeof appOutDir !== 'string') return false
  if (!existsSync(appOutDir)) return false
  rmSync(appOutDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
  return true
}

/** Preserve a previously working Windows ZN build as rollback material. */
export function preserveRollbackBackup(appOutDir, productExeName = 'ZN.exe') {
  if (!appOutDir || typeof appOutDir !== 'string' || !existsSync(appOutDir)) return false
  if (!existsSync(path.join(appOutDir, productExeName))) return false

  const backupDir = `${appOutDir}.bak`
  try {
    rmSync(backupDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
    renameSync(appOutDir, backupDir)
    return true
  } catch {
    return false
  }
}

export default async function beforePack(context) {
  const appOutDir = context && context.appOutDir
  const platformName = context && context.electronPlatformName
  try {
    const productExe = `${(context && context.packager?.appInfo?.productFilename) || 'ZN'}.exe`
    if (platformName === 'win32' && preserveRollbackBackup(appOutDir, productExe)) {
      console.log(`[before-pack] preserved previous unpacked dir for rollback: ${appOutDir}.bak`)
    } else if (cleanStaleAppOutDir(appOutDir)) {
      console.log(`[before-pack] removed stale unpacked dir before staging: ${appOutDir}`)
    }
  } catch (err) {
    console.warn(`[before-pack] could not clean ${appOutDir} (${err.message}); continuing`)
  }

  const platform = context && context.electronPlatformName
  const archName = context && typeof context.arch === 'number' ? Arch[context.arch] : undefined
  if (!platform || !archName) return

  if (archName === 'universal') {
    console.warn(
      '[before-pack] target arch is "universal" — node-pty has no universal prebuild; ' +
        'the staged binary remains the host/single-arch copy unless a universal native payload is prepared.'
    )
  } else {
    await stageNodePty({ platform, arch: archName })
    console.log(`[before-pack] re-staged node-pty for target ${platform}-${archName}`)
  }
  stageGetWindows({ platform, arch: archName })
  console.log(`[before-pack] re-staged get-windows for target ${platform}-${archName}`)
}
