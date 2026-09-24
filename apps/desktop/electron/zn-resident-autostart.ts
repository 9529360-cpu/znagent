import { spawn } from 'node:child_process'
import { promises as fs } from 'node:fs'
import path from 'node:path'

import { app } from 'electron'

import { defaultZnResidentLaunch } from './zn-resident-process'

export const ZN_RESIDENT_AUTOSTART_SCHEMA = 2

export function znResidentAutostartMarkerName(desktopVersion: string): string {
  return `zn-resident-autostart-v${ZN_RESIDENT_AUTOSTART_SCHEMA}-${desktopVersion}.ok`
}

function znHomeFromEndpoint(endpointPath: string): string {
  return path.dirname(path.dirname(endpointPath))
}

/**
 * Make the already-running resident survive the next OS login without asking
 * the user to open a terminal. The Python installer records the absolute
 * interpreter that successfully executed it, so the OS startup entry does not
 * later depend on Electron's PATH.
 *
 * We refresh the entry once per desktop version and autostart schema. The
 * schema is deliberately independent from app semver: a resident launch
 * contract can change during development or repair without a package-version
 * bump, and an old marker must not preserve a stale OS startup command.
 */
export async function ensureZnResidentAutostart(): Promise<void> {
  if (!app.isPackaged && process.env.ZN_DESKTOP_DEV === '1') {
    console.info('[zn-resident] source-development instance skips login autostart installation')
    return
  }

  const launch = defaultZnResidentLaunch()
  const marker = path.join(
    app.getPath('userData'),
    znResidentAutostartMarkerName(app.getVersion())
  )

  try {
    await fs.access(marker)
    return
  } catch {
    // Not installed for this desktop version + autostart schema yet.
  }

  const args = [
    '-m',
    'zn_agent.core.resident_autostart',
    'install',
    '--home',
    znHomeFromEndpoint(launch.endpointPath)
  ]

  await new Promise<void>((resolve, reject) => {
    const child = spawn(launch.command, args, {
      cwd: launch.cwd,
      env: launch.env,
      windowsHide: true,
      stdio: ['ignore', 'ignore', 'pipe']
    })
    let errorText = ''

    child.stderr?.on('data', chunk => {
      if (errorText.length < 8_000) errorText += String(chunk)
    })
    child.once('error', reject)
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolve()
        return
      }
      reject(
        new Error(
          `resident autostart installer exited ${code ?? 'null'}${signal ? ` (${signal})` : ''}${
            errorText.trim() ? `: ${errorText.trim()}` : ''
          }`
        )
      )
    })
  })

  await fs.writeFile(marker, `${new Date().toISOString()}\n`, 'utf8')
}
