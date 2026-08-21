#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const preferredSuffix = {
  windows: '.exe',
  macos: '.zip',
  linux: '.AppImage'
}
const installerSuffixes = ['.dmg', '.zip', '.exe', '.msi', '.AppImage', '.deb', '.rpm']
const VERSION_RE = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/

function isInstaller(name) {
  return installerSuffixes.some(suffix => name.endsWith(suffix))
}

function classifySubject(subject) {
  const patterns = [
    ['new', /^feat(?:\([^)]+\))?(!)?:\s*(.+)$/i],
    ['fixes', /^fix(?:\([^)]+\))?(!)?:\s*(.+)$/i],
    ['improvements', /^(?:perf|refactor|improve|enhance)(?:\([^)]+\))?(!)?:\s*(.+)$/i]
  ]

  for (const [category, pattern] of patterns) {
    const match = subject.match(pattern)
    if (!match) continue
    return {
      category,
      breaking: Boolean(match[1]),
      text: match[2].trim()
    }
  }

  return null
}

function gitSubjectsSincePreviousRelease(version) {
  try {
    const tags = execFileSync('git', ['tag', '--list', 'zn-v*', '--sort=-version:refname'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore']
    })
      .split(/\r?\n/)
      .map(tag => tag.trim())
      .filter(Boolean)
    const currentTag = `zn-v${version}`
    const previous = tags.find(tag => tag !== currentTag) || null
    const range = previous ? `${previous}..HEAD` : 'HEAD'
    return execFileSync('git', ['log', '--format=%s', range], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore']
    })
      .split(/\r?\n/)
      .map(line => line.trim())
      .filter(Boolean)
  } catch {
    return []
  }
}

export function deriveZnReleaseNotes(subjects) {
  const notes = { new: [], improvements: [], fixes: [], impact: [] }
  const seen = new Set()

  for (const subject of subjects) {
    const item = classifySubject(subject)
    if (!item || seen.has(`${item.category}:${item.text}`)) continue
    seen.add(`${item.category}:${item.text}`)
    notes[item.category].push(item.text)
    if (item.breaking && !notes.impact.includes(item.text)) notes.impact.push(item.text)
  }

  return notes
}

function assetUrl(version, name) {
  return `./releases/${encodeURIComponent(version)}/${encodeURIComponent(name)}`
}

export async function prepareZnPublicChannel({
  artifactDir,
  version,
  outputDir,
  releaseUrl = null,
  subjects = null
}) {
  const resolvedArtifactDir = path.resolve(artifactDir)
  const resolvedOutputDir = path.resolve(outputDir)

  if (!VERSION_RE.test(version)) {
    throw new Error(`invalid ZN release version: ${version}`)
  }

  await fs.rm(resolvedOutputDir, { recursive: true, force: true })
  const versionDir = path.join(resolvedOutputDir, 'releases', version)
  await fs.mkdir(versionDir, { recursive: true })

  const entries = await fs.readdir(resolvedArtifactDir, { withFileTypes: true })
  for (const entry of entries) {
    if (!entry.isFile() || !isInstaller(entry.name)) continue
    await fs.copyFile(path.join(resolvedArtifactDir, entry.name), path.join(versionDir, entry.name))
  }

  const manifestNames = entries
    .filter(entry => entry.isFile() && /^zn-release-(windows|macos|linux)-.+\.json$/.test(entry.name))
    .map(entry => entry.name)
    .sort()

  if (manifestNames.length === 0) {
    throw new Error(`no ZN release manifests found in ${resolvedArtifactDir}`)
  }

  const targets = []
  for (const manifestName of manifestNames) {
    const manifest = JSON.parse(await fs.readFile(path.join(resolvedArtifactDir, manifestName), 'utf8'))
    if (
      manifest?.schema !== 1 ||
      manifest?.product !== 'ZN' ||
      manifest?.repository !== '9529360-cpu/znagent' ||
      manifest?.version !== version ||
      !preferredSuffix[manifest?.platform] ||
      typeof manifest?.arch !== 'string' ||
      !Array.isArray(manifest?.assets)
    ) {
      throw new Error(`invalid ZN release manifest: ${manifestName}`)
    }

    const suffix = preferredSuffix[manifest.platform]
    const asset = manifest.assets.find(candidate => candidate?.name?.endsWith(suffix))
    if (!asset) {
      throw new Error(`${manifestName} has no preferred ${suffix} update asset`)
    }
    if (typeof asset.name !== 'string' || path.basename(asset.name) !== asset.name) {
      throw new Error(`${manifestName} has an unsafe update asset name`)
    }
    if (!Number.isSafeInteger(asset.size) || asset.size <= 0 || !/^[0-9a-f]{64}$/i.test(asset.sha256 || '')) {
      throw new Error(`${manifestName} has invalid asset verification metadata`)
    }

    const copied = path.join(versionDir, asset.name)
    const stat = await fs.stat(copied).catch(() => null)
    if (!stat?.isFile() || stat.size !== asset.size) {
      throw new Error(`public channel asset is missing or size-mismatched: ${asset.name}`)
    }

    targets.push({
      platform: manifest.platform,
      arch: manifest.arch,
      name: asset.name,
      url: assetUrl(version, asset.name),
      size: asset.size,
      sha256: String(asset.sha256).toLowerCase()
    })
  }

  targets.sort((a, b) => `${a.platform}:${a.arch}`.localeCompare(`${b.platform}:${b.arch}`))
  const noteSubjects = subjects ?? gitSubjectsSincePreviousRelease(version)
  const channel = {
    schema: 1,
    product: 'ZN',
    channel: 'stable',
    version,
    published_at: new Date().toISOString(),
    ...(releaseUrl ? { release_url: releaseUrl } : {}),
    notes: deriveZnReleaseNotes(noteSubjects),
    targets
  }

  const channelPath = path.join(resolvedOutputDir, 'stable.json')
  await fs.writeFile(channelPath, `${JSON.stringify(channel, null, 2)}\n`, 'utf8')
  return { channelPath, channel, outputDir: resolvedOutputDir }
}

async function main() {
  const artifactDir = path.resolve(process.argv[2] || 'dist')
  const version = String(process.argv[3] || '').trim()
  const outputDir = path.resolve(process.argv[4] || 'public-channel')
  const releaseUrl = String(process.env.ZN_PUBLIC_RELEASE_URL || '').trim() || null

  if (!version) {
    throw new Error('usage: prepare-zn-public-channel.mjs <artifact-dir> <version> [output-dir]')
  }

  const result = await prepareZnPublicChannel({ artifactDir, version, outputDir, releaseUrl })
  console.log(result.channelPath)
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main()
}
