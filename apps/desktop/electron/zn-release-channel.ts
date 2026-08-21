export type ZnUpdatePlatform = 'windows' | 'macos' | 'linux'

export type ZnReleaseNotes = {
  new: string[]
  improvements: string[]
  fixes: string[]
  impact: string[]
}

export type ZnReleaseTarget = {
  platform: ZnUpdatePlatform
  arch: string
  name: string
  url: string
  size: number
  sha256: string
}

export type ZnReleaseChannelResolution = {
  version: string
  releaseUrl?: string
  publishedAt?: string
  notes: ZnReleaseNotes
  target?: ZnReleaseTarget
}

const SHA256_RE = /^[0-9a-f]{64}$/i
const VERSION_RE = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function normalizeList(value: unknown): string[] {
  if (!Array.isArray(value)) return []

  const seen = new Set<string>()
  const items: string[] = []

  for (const entry of value) {
    if (typeof entry !== 'string') continue
    const item = entry.trim()
    if (!item || seen.has(item)) continue
    seen.add(item)
    items.push(item)
  }

  return items
}

export function normalizeZnReleaseNotes(value: unknown): ZnReleaseNotes {
  const notes = asRecord(value)

  return {
    new: normalizeList(notes?.new),
    improvements: normalizeList(notes?.improvements),
    fixes: normalizeList(notes?.fixes),
    impact: normalizeList(notes?.impact)
  }
}

export function znUpdatePlatform(runtimePlatform = process.platform): ZnUpdatePlatform | null {
  if (runtimePlatform === 'win32') return 'windows'
  if (runtimePlatform === 'darwin') return 'macos'
  if (runtimePlatform === 'linux') return 'linux'
  return null
}

function resolveChannelUrl(value: unknown, baseUrl: string, label: string, allowInsecureUrls: boolean): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`ZN update channel ${label} is missing`)
  }

  let resolved: URL
  try {
    resolved = new URL(value, baseUrl)
  } catch {
    throw new Error(`ZN update channel ${label} is not a valid URL`)
  }

  if (resolved.protocol !== 'https:' && !(allowInsecureUrls && resolved.protocol === 'http:')) {
    throw new Error(`ZN update channel ${label} must use HTTPS`)
  }

  return resolved.toString()
}

function validateTarget(
  value: Record<string, unknown>,
  baseUrl: string,
  platform: ZnUpdatePlatform,
  arch: string,
  allowInsecureUrls: boolean
): ZnReleaseTarget {
  const name = typeof value.name === 'string' ? value.name.trim() : ''
  const size = typeof value.size === 'number' ? value.size : Number.NaN
  const sha256 = typeof value.sha256 === 'string' ? value.sha256.trim().toLowerCase() : ''
  const expectedSuffix = platform === 'windows' ? '.exe' : platform === 'macos' ? '.zip' : '.AppImage'

  if (!name || pathLikeName(name) !== name || !name.endsWith(expectedSuffix)) {
    throw new Error(`ZN update channel target must name a ${expectedSuffix} installer`)
  }
  if (!Number.isSafeInteger(size) || size <= 0) {
    throw new Error('ZN update channel target has an invalid size')
  }
  if (!SHA256_RE.test(sha256)) {
    throw new Error('ZN update channel target has an invalid SHA-256 digest')
  }

  return {
    platform,
    arch,
    name,
    url: resolveChannelUrl(value.url, baseUrl, 'target URL', allowInsecureUrls),
    size,
    sha256
  }
}

function pathLikeName(value: string): string {
  return value.replace(/^.*[\\/]/, '')
}

export function parseZnReleaseChannel(
  value: unknown,
  options: {
    baseUrl: string
    platform: ZnUpdatePlatform
    arch: string
    allowInsecureUrls?: boolean
  }
): ZnReleaseChannelResolution {
  const document = asRecord(value)

  if (!document || document.schema !== 1 || document.product !== 'ZN' || document.channel !== 'stable') {
    throw new Error('unsupported ZN update channel document')
  }

  const version = typeof document.version === 'string' ? document.version.trim() : ''
  if (!VERSION_RE.test(version)) {
    throw new Error('ZN update channel has an invalid version')
  }

  const targets = Array.isArray(document.targets) ? document.targets : []
  const rawTarget = targets
    .map(asRecord)
    .find(target => target?.platform === options.platform && target?.arch === options.arch)

  const releaseUrl = document.release_url
    ? resolveChannelUrl(document.release_url, options.baseUrl, 'release URL', Boolean(options.allowInsecureUrls))
    : undefined
  const publishedAt = typeof document.published_at === 'string' ? document.published_at.trim() || undefined : undefined

  return {
    version,
    releaseUrl,
    publishedAt,
    notes: normalizeZnReleaseNotes(document.notes),
    target: rawTarget
      ? validateTarget(rawTarget, options.baseUrl, options.platform, options.arch, Boolean(options.allowInsecureUrls))
      : undefined
  }
}
