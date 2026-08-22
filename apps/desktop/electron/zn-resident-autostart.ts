import { spawn } from 'node:child_process'
import { promises as fs } from 'node:fs'
import path from 'node:path'

import { app } from 'electron'

import { defaultZnResidentLaunch } from './zn-resident-process'

function znHomeFromEndpoint(endpointPath: string): string {
  return path.dirname(path.dirname(endpointPath))
}

/**
 * Make the already-running resident survive the next OS login without asking
 * the user to open a terminal. The Python installer records the absolute
 * interpreter that successfully executed it, so the OS startup entry does not
 * later depend on Electron's PATH.
 *
 * We refresh the entry once per desktop version. That lets an app update move
 * the Python runtime or ZN home and naturally repair the next-login command,
 * without doing systemd/launchctl/schtasks work on every launch.
 */
export async function ensureZnResidentAutostart(): Promise<void> {
  const launch = defaultZnResidentLaunch()
  const marker = path.join(app.getPath('userData'), `zn-resident-autostart-${app.getVersion()}.ok`)

  try {
    await fs.access(marker)
    return
  } catch {
    // Not installed for this desktop version yet.
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
