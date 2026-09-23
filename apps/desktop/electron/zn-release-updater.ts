import { execFile, spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { constants as fsConstants, createReadStream, createWriteStream } from 'node:fs'
import { promises as fs } from 'node:fs'
import * as http from 'node:http'
import type { IncomingMessage } from 'node:http'
import * as https from 'node:https'
import path from 'node:path'
import { promisify } from 'node:util'

import { app } from 'electron'

import { handleZnDesktopIpc } from './zn-ipc-trust'

import { applyZnReleaseInstallerWithResidentGate } from './zn-release-application-gate'
import {
  parseZnReleaseChannel,
  znUpdatePlatform,
  type ZnReleaseChannelResolution,
  type ZnReleaseNotes,
  type ZnReleaseTarget
} from './zn-release-channel'
import { verifyZnReleaseChannelSignature } from './zn-release-signature'

const execFileAsync = promisify(execFile)
const USER_AGENT = 'ZN-Desktop-Updater/2'
const MAX_REDIRECTS = 6

type ZnDownloadState = 'idle' | 'downloading' | 'ready' | 'failed'

export interface ZnReleaseUpdateStatus {
  supported: boolean
  currentVersion: string
  updateAvailable: boolean
  availableVersion?: string
  releaseUrl?: string
  assetName?: string
  releaseNotes?: ZnReleaseNotes
  downloadState?: ZnDownloadState
  downloadedBytes?: number
  downloadTotalBytes?: number
  downloadError?: string
  message?: string
}

export interface ZnReleaseApplyResult {
  ok: boolean
  message?: string
  error?: string
}

interface UpdatePlan {
  status: ZnReleaseUpdateStatus
  release: ZnReleaseChannelResolution
  target: ZnReleaseTarget
}

interface PreparationState {
  key: string
  state: ZnDownloadState
  downloadedBytes: number
  totalBytes: number
  path?: string
  error?: string
  promise?: Promise<string>
}

let registered = false
let preparation: PreparationState | null = null

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

function allowInsecureUpdateUrls(): boolean {
  return !app.isPackaged && process.env.ZN_DESKTOP_ALLOW_INSECURE_UPDATE_URLS === '1'
}

function configuredChannelUrl(): string | null {
  const raw = String(process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL || '').trim()
  if (!raw) return null

  let url: URL
  try {
    url = new URL(raw)
  } catch {
    throw new Error('configured ZN update channel URL is invalid')
  }

  if (url.protocol !== 'https:' && !(allowInsecureUpdateUrls() && url.protocol === 'http:')) {
    throw new Error('configured ZN update channel must use HTTPS')
  }

  return url.toString()
}

function request(url: string, redirects = MAX_REDIRECTS): Promise<IncomingMessage> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url)
    const client =
      parsed.protocol === 'https:'
        ? https
        : allowInsecureUpdateUrls() && parsed.protocol === 'http:'
          ? http
          : null

    if (!client) {
      reject(new Error('ZN update requests must use HTTPS'))
      return
    }

    const req = client.get(
      url,
      {
        headers: {
          Accept: '*/*',
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

async function readJson(url: string): Promise<unknown> {
  const response = await request(url)
  const chunks: Buffer[] = []
  for await (const chunk of response) chunks.push(Buffer.from(chunk))
  const document = JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown
  verifyZnReleaseChannelSignature(
    document,
    String(process.env.ZN_UPDATE_SIGNING_PUBLIC_KEYS || ''),
    { required: app.isPackaged }
  )
  return document
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

  const channelUrl = configuredChannelUrl()
  if (!channelUrl) {
    return {
      status: {
        supported: false,
        currentVersion,
        updateAvailable: false,
        message: 'this ZN build has no public update channel configured'
      }
    }
  }

  const platform = znUpdatePlatform()
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

  const release = parseZnReleaseChannel(await readJson(channelUrl), {
    baseUrl: channelUrl,
    platform,
    arch: process.arch,
    allowInsecureUrls: allowInsecureUpdateUrls()
  })
  const updateAvailable = compareZnVersions(release.version, currentVersion) > 0
  const baseStatus: ZnReleaseUpdateStatus = {
    supported: true,
    currentVersion,
    updateAvailable,
    availableVersion: release.version,
    releaseUrl: release.releaseUrl,
    releaseNotes: release.notes
  }

  if (!updateAvailable) {
    return { status: baseStatus }
  }

  if (platform === 'linux' && !process.env.APPIMAGE) {
    return {
      status: {
        ...baseStatus,
        supported: false,
        message: 'automatic Linux install is supported for AppImage; use the published package for deb/rpm installs'
      }
    }
  }

  if (!release.target) {
    return {
      status: {
        ...baseStatus,
        supported: false,
        message: `update channel has no ${platform}/${process.arch} installer`
      }
    }
  }

  return {
    status: {
      ...baseStatus,
      assetName: release.target.name
    },
    release,
    target: release.target
  }
}

function planKey(plan: UpdatePlan): string {
  return `${plan.release.version}:${plan.target.sha256}:${plan.target.url}`
}

function statusWithPreparation(plan: UpdatePlan): ZnReleaseUpdateStatus {
  const key = planKey(plan)
  if (!preparation || preparation.key !== key) {
    return {
      ...plan.status,
      downloadState: 'idle',
      downloadedBytes: 0,
      downloadTotalBytes: plan.target.size
    }
  }

  return {
    ...plan.status,
    downloadState: preparation.state,
    downloadedBytes: preparation.downloadedBytes,
    downloadTotalBytes: preparation.totalBytes,
    downloadError: preparation.error
  }
}

export async function checkZnReleaseUpdate(): Promise<ZnReleaseUpdateStatus> {
  try {
    const resolved = await resolvePlan()
    if (!('target' in resolved)) return resolved.status

    void ensurePrepared(resolved).catch(() => {})
    return statusWithPreparation(resolved)
  } catch (error) {
    return {
      supported: false,
      currentVersion: app.getVersion(),
      updateAvailable: false,
      message: error instanceof Error ? error.message : String(error)
    }
  }
}

async function fileSha256(filePath: string): Promise<string> {
  const hash = createHash('sha256')
  const input = createReadStream(filePath)
  for await (const chunk of input) hash.update(Buffer.from(chunk))
  return hash.digest('hex')
}

async function isVerifiedDownload(filePath: string, target: ZnReleaseTarget): Promise<boolean> {
  try {
    const stat = await fs.stat(filePath)
    if (!stat.isFile() || stat.size !== target.size) return false
    return (await fileSha256(filePath)) === target.sha256
  } catch {
    return false
  }
}

async function downloadVerified(plan: UpdatePlan, state: PreparationState): Promise<string> {
  const directory = path.join(app.getPath('userData'), 'updates', plan.release.version)
  await fs.mkdir(directory, { recursive: true })
  const finalPath = path.join(directory, plan.target.name)

  if (await isVerifiedDownload(finalPath, plan.target)) {
    state.downloadedBytes = plan.target.size
    return finalPath
  }

  await fs.rm(finalPath, { force: true })
  const temporaryPath = `${finalPath}.${process.pid}.part`
  await fs.rm(temporaryPath, { force: true })

  try {
    const response = await request(plan.target.url)
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
        state.downloadedBytes = size
        hash.update(bytes)
      })
      response.once('error', fail)
      output.once('error', fail)
      output.once('finish', resolve)
      response.pipe(output)
    })

    const digest = hash.digest('hex')
    if (size !== plan.target.size || digest !== plan.target.sha256) {
      throw new Error('downloaded ZN update failed channel verification')
    }

    await fs.rename(temporaryPath, finalPath)
    state.downloadedBytes = size
    return finalPath
  } catch (error) {
    await fs.rm(temporaryPath, { force: true })
    throw error
  }
}

function ensurePrepared(plan: UpdatePlan, retryFailed = false): Promise<string> {
  const key = planKey(plan)

  if (preparation?.key === key) {
    if (preparation.state === 'ready' && preparation.path) return Promise.resolve(preparation.path)
    if (preparation.state === 'downloading' && preparation.promise) return preparation.promise
    if (preparation.state === 'failed' && !retryFailed) {
      return Promise.reject(new Error(preparation.error || 'ZN update download failed'))
    }
  }

  const state: PreparationState = {
    key,
    state: 'downloading',
    downloadedBytes: 0,
    totalBytes: plan.target.size
  }

  const promise = downloadVerified(plan, state)
    .then(filePath => {
      state.state = 'ready'
      state.path = filePath
      state.error = undefined
      state.downloadedBytes = state.totalBytes
      return filePath
    })
    .catch(error => {
      state.state = 'failed'
      state.error = error instanceof Error ? error.message : String(error)
      throw error
    })

  state.promise = promise
  preparation = state
  return promise
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
    if (!('target' in resolved)) {
      return {
        ok: false,
        error: 'unavailable',
        message: resolved.status.message || 'no installable ZN update is available'
      }
    }
    if (!resolved.status.updateAvailable) {
      return { ok: true, message: 'ZN is already current' }
    }

    const installer = await ensurePrepared(resolved, true)
    let handoff: (() => Promise<void>) | null = null
    if (process.platform === 'win32') handoff = () => handoffWindows(installer)
    else if (process.platform === 'darwin') handoff = () => handoffMac(installer)
    else if (process.platform === 'linux') handoff = () => handoffLinux(installer)
    else return { ok: false, error: 'unsupported-platform', message: process.platform }

    return await applyZnReleaseInstallerWithResidentGate({
      version: resolved.release.version,
      handoff
    })
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
  handleZnDesktopIpc('zn:updates:check', () => checkZnReleaseUpdate())
  handleZnDesktopIpc('zn:updates:apply', () => applyZnReleaseUpdate())
}
