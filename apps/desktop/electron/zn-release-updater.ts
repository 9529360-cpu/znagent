import { execFile, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { constants as fsConstants, createWriteStream } from 'node:fs'
import { promises as fs } from 'node:fs'
import * as https from 'node:https'
import type { IncomingMessage } from 'node:http'
import path from 'node:path'
import { promisify } from 'node:util'

import { app, ipcMain } from 'electron'

const execFileAsync = promisify(execFile)
const REPOSITORY = '9529360-cpu/znagent'
const LATEST_RELEASE_URL = `https://api.github.com/repos/${REPOSITORY}/releases/latest`
const USER_AGENT = 'ZN-Desktop-Updater/1'
const MAX_REDIRECTS = 6

interface ReleaseAsset {
  name: string
  size?: number
  browser_download_url: string
}

interface GitHubRelease {
  tag_name: string
  html_url: string
  prerelease?: boolean
  draft?: boolean
  assets: ReleaseAsset[]
}

interface ManifestAsset {
  name: string
  size: number
  sha256: string
}

interface ReleaseManifest {
  schema: number
  product: string
  repository: string
  version: string
  platform: string
  arch: string
  assets: ManifestAsset[]
}

export interface ZnReleaseUpdateStatus {
  supported: boolean
  currentVersion: string
  updateAvailable: boolean
  availableVersion?: string
  releaseUrl?: string
  assetName?: string
  message?: string
}

export interface ZnReleaseApplyResult {
  ok: boolean
  message?: string
  error?: string
}

interface UpdatePlan {
  status: ZnReleaseUpdateStatus
  release: GitHubRelease
  manifest: ReleaseManifest
  expected: ManifestAsset
  asset: ReleaseAsset
}

let registered = false

function platformKey(): 'windows' | 'macos' | 'linux' | null {
  if (process.platform === 'win32') return 'windows'
  if (process.platform === 'darwin') return 'macos'
  if (process.platform === 'linux') return 'linux'
  return null
}

function parseVersion(value: string): { core: number[]; prerelease: string | null } | null {
  const normalized = value.trim().replace(/^zn-v/i, '').replace(/^v/i, '')
  const match = normalized.match(/^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/)
  if (!match) return null
  return {
    core: [Number(match[1]), Number(match[2]), Number(match[3])],
    prerelease: match[4] || null
  }
}

export function compareZnVersions(left: string, right: string): number {
  const a = parseVersion(left)
  const b = parseVersion(right)
  if (!a || !b) return 0
  for (let i = 0; i < 3; i += 1) {
    if (a.core[i] !== b.core[i]) return a.core[i] > b.core[i] ? 1 : -1
  }
  if (a.prerelease === b.prerelease) return 0
  if (a.prerelease === null) return 1
  if (b.prerelease === null) return -1
  return a.prerelease.localeCompare(b.prerelease, undefined, { numeric: true })
}

function request(url: string, redirects = MAX_REDIRECTS): Promise<IncomingMessage> {
  return new Promise((resolve, reject) => {
    const req = https.get(
      url,
      {
        headers: {
          Accept: 'application/vnd.github+json',
          'User-Agent': USER_AGENT
        }
      },
      response => {
        const status = response.statusCode ?? 0
        const location = response.headers.location
        if (status >= 300 && status < 400 && location) {
          response.resume()
          if (redirects <= 0) {
            reject(new Error('too many update download redirects'))
            return
          }
          const next = new URL(location, url).toString()
          void request(next, redirects - 1).then(resolve, reject)
          return
        }
        if (status < 200 || status >= 300) {
          const chunks: Buffer[] = []
          response.on('data', chunk => chunks.push(Buffer.from(chunk)))
          response.on('end', () => {
            reject(
              new Error(
                `update request failed (${status}): ${Buffer.concat(chunks).toString('utf8').slice(0, 500)}`
              )
            )
          })
          return
        }
        resolve(response)
      }
    )
    req.once('error', reject)
    req.setTimeout(30_000, () => req.destroy(new Error('update request timed out')))
  })
}

async function readJson<T>(url: string): Promise<T> {
  const response = await request(url)
  const chunks: Buffer[] = []
  for await (const chunk of response) chunks.push(Buffer.from(chunk))
  return JSON.parse(Buffer.concat(chunks).toString('utf8')) as T
}

function preferredExtension(platform: 'windows' | 'macos' | 'linux'): string | null {
  if (platform === 'windows') return '.exe'
  if (platform === 'macos') return '.zip'
  if (platform === 'linux' && process.env.APPIMAGE) return '.AppImage'
  return null
}

async function resolvePlan(): Promise<UpdatePlan | { status: ZnReleaseUpdateStatus }> {
  const currentVersion = app.getVersion()
  if (!app.isPackaged && process.env.ZN_DESKTOP_ALLOW_DEV_UPDATES !== '1') {
    return {
      status: {
        supported: false,
        currentVersion,
        updateAvailable: false,
        message: 'release updates are disabled for source/dev desktop runs'
      }
    }
  }

  const platform = platformKey()
  if (!platform) {
    return {
      status: {
        supported: false,
        currentVersion,
        updateAvailable: false,
        message: `unsupported update platform: ${process.platform}`
      }
    }
  }

  const release = await readJson<GitHubRelease>(LATEST_RELEASE_URL)
  const availableVersion = release.tag_name.replace(/^zn-v/i, '')
  const updateAvailable =
    release.tag_name.startsWith('zn-v') && compareZnVersions(availableVersion, currentVersion) > 0
  const baseStatus: ZnReleaseUpdateStatus = {
    supported: false,
    currentVersion,
    updateAvailable,
    availableVersion,
    releaseUrl: release.html_url
  }

  if (!release.tag_name.startsWith('zn-v') || release.draft || release.prerelease) {
    return { status: { ...baseStatus, updateAvailable: false, message: 'no stable ZN release is available' } }
  }
  if (!updateAvailable) {
    return { status: { ...baseStatus, supported: true, updateAvailable: false } }
  }

  const extension = preferredExtension(platform)
  if (!extension) {
    return {
      status: {
        ...baseStatus,
        message: 'automatic Linux install is supported for AppImage; use the release asset for deb/rpm installs'
      }
    }
  }

  const manifestName = `zn-release-${platform}-${process.arch}.json`
  const manifestAsset = release.assets.find(asset => asset.name === manifestName)
  if (!manifestAsset) {
    return {
      status: {
        ...baseStatus,
        message: `release has no ${platform}/${process.arch} update manifest`
      }
    }
  }

  const manifest = await readJson<ReleaseManifest>(manifestAsset.browser_download_url)
  if (
    manifest.schema !== 1 ||
    manifest.product !== 'ZN' ||
    manifest.repository !== REPOSITORY ||
    manifest.version !== availableVersion ||
    manifest.platform !== platform ||
    manifest.arch !== process.arch
  ) {
    throw new Error('release manifest does not match this ZN desktop')
  }

  const expected = manifest.assets.find(item => item.name.endsWith(extension))
  if (!expected) {
    return {
      status: {
        ...baseStatus,
        message: `release manifest has no ${extension} installer`
      }
    }
  }
  const asset = release.assets.find(item => item.name === expected.name)
  if (!asset) throw new Error(`release asset missing: ${expected.name}`)

  return {
    status: {
      ...baseStatus,
      supported: true,
      assetName: asset.name
    },
    release,
    manifest,
    expected,
    asset
  }
}

export async function checkZnReleaseUpdate(): Promise<ZnReleaseUpdateStatus> {
  try {
    return (await resolvePlan()).status
  } catch (error) {
    return {
      supported: false,
      currentVersion: app.getVersion(),
      updateAvailable: false,
      message: error instanceof Error ? error.message : String(error)
    }
  }
}

async function downloadVerified(plan: UpdatePlan): Promise<string> {
  const directory = path.join(app.getPath('temp'), 'zn-updates', plan.manifest.version)
  await fs.mkdir(directory, { recursive: true })
  const finalPath = path.join(directory, plan.asset.name)
  const temporaryPath = `${finalPath}.${process.pid}.part`
  await fs.rm(temporaryPath, { force: true })

  const response = await request(plan.asset.browser_download_url)
  const output = createWriteStream(temporaryPath, { flags: 'w' })
  const hash = createHash('sha256')
  let size = 0

  await new Promise<void>((resolve, reject) => {
    const fail = (error: Error) => {
      output.destroy()
      reject(error)
    }
    response.on('data', chunk => {
      const bytes = Buffer.from(chunk)
      size += bytes.length
      hash.update(bytes)
    })
    response.once('error', fail)
    output.once('error', fail)
    output.once('finish', resolve)
    response.pipe(output)
  })

  const digest = hash.digest('hex')
  if (size !== Number(plan.expected.size) || digest !== plan.expected.sha256.toLowerCase()) {
    await fs.rm(temporaryPath, { force: true })
    throw new Error('downloaded ZN update failed manifest verification')
  }
  await fs.rename(temporaryPath, finalPath)
  return finalPath
}

function macBundlePath(): string {
  return path.dirname(path.dirname(path.dirname(process.execPath)))
}

async function handoffWindows(installer: string): Promise<void> {
  const child = spawn(installer, ['/S', '--updated'], {
    detached: true,
    stdio: 'ignore',
    windowsHide: true
  })
  child.unref()
}

async function handoffMac(zipPath: string): Promise<void> {
  const staging = path.join(path.dirname(zipPath), `staged-${process.pid}`)
  await fs.rm(staging, { force: true, recursive: true })
  await fs.mkdir(staging, { recursive: true })
  await execFileAsync('ditto', ['-x', '-k', zipPath, staging])
  const entries = await fs.readdir(staging, { withFileTypes: true })
  const appEntry = entries.find(entry => entry.isDirectory() && entry.name.endsWith('.app'))
  if (!appEntry) throw new Error('macOS update zip did not contain an app bundle')

  const stagedApp = path.join(staging, appEntry.name)
  const targetApp = macBundlePath()
  if (!targetApp.endsWith('.app')) throw new Error(`cannot resolve current app bundle from ${process.execPath}`)
  await fs.access(path.dirname(targetApp), fsConstants.W_OK)

  const script = String.raw`
pid="$1"
staged="$2"
target="$3"
backup="$target.zn-backup-$$"
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
rm -rf "$backup"
if ! mv "$target" "$backup"; then exit 1; fi
if ditto "$staged" "$target"; then
  rm -rf "$backup"
  open "$target"
  exit 0
fi
rm -rf "$target"
mv "$backup" "$target"
open "$target"
exit 1
`
  const child = spawn('/bin/bash', ['-c', script, 'zn-updater', String(process.pid), stagedApp, targetApp], {
    detached: true,
    stdio: 'ignore'
  })
  child.unref()
}

async function handoffLinux(appImage: string): Promise<void> {
  const current = String(process.env.APPIMAGE || '').trim()
  if (!current) throw new Error('current ZN desktop is not running from an AppImage')
  const parent = path.dirname(current)
  await fs.access(parent, fsConstants.W_OK)
  const staged = `${current}.zn-new`
  await fs.copyFile(appImage, staged)
  await fs.chmod(staged, 0o755)

  const script = String.raw`
pid="$1"
staged="$2"
target="$3"
backup="$target.zn-backup"
while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done
rm -f "$backup"
if ! mv "$target" "$backup"; then exit 1; fi
if mv "$staged" "$target"; then
  chmod +x "$target"
  rm -f "$backup"
  "$target" >/dev/null 2>&1 &
  exit 0
fi
mv "$backup" "$target"
"$target" >/dev/null 2>&1 &
exit 1
`
  const child = spawn('/bin/bash', ['-c', script, 'zn-updater', String(process.pid), staged, current], {
    detached: true,
    stdio: 'ignore'
  })
  child.unref()
}

export async function applyZnReleaseUpdate(): Promise<ZnReleaseApplyResult> {
  try {
    const resolved = await resolvePlan()
    if (!('asset' in resolved)) {
      return {
        ok: false,
        error: 'unavailable',
        message: resolved.status.message || 'no installable ZN update is available'
      }
    }
    if (!resolved.status.updateAvailable) {
      return { ok: true, message: 'ZN is already current' }
    }

    const installer = await downloadVerified(resolved)
    if (process.platform === 'win32') await handoffWindows(installer)
    else if (process.platform === 'darwin') await handoffMac(installer)
    else if (process.platform === 'linux') await handoffLinux(installer)
    else return { ok: false, error: 'unsupported-platform', message: process.platform }

    setTimeout(() => app.quit(), 100)
    return { ok: true, message: `installing ZN ${resolved.manifest.version}` }
  } catch (error) {
    return {
      ok: false,
      error: 'apply-failed',
      message: error instanceof Error ? error.message : String(error)
    }
  }
}

export function registerZnReleaseUpdaterIpc(): void {
  if (registered) return
  registered = true
  ipcMain.handle('zn:updates:check', () => checkZnReleaseUpdate())
  ipcMain.handle('zn:updates:apply', () => applyZnReleaseUpdate())
}
