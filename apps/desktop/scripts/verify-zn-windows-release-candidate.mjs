#!/usr/bin/env node
import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const SHA256_RE = /^[0-9a-f]{64}$/i
const REQUIRED_EXTENSIONS = new Set(['.exe', '.msi'])

async function sha256File(filePath) {
  const hash = createHash('sha256')
  const input = createReadStream(filePath)
  for await (const chunk of input) hash.update(chunk)
  return hash.digest('hex')
}

function requireSafeAssetName(name) {
  if (typeof name !== 'string' || !name.trim()) {
    throw new Error('Windows release candidate asset name must be non-empty')
  }
  if (name === '.' || name === '..' || name.includes('/') || name.includes('\\')) {
    throw new Error(`Windows release candidate asset name is unsafe: ${name}`)
  }
  return name
}

export async function verifyZnWindowsReleaseCandidate({
  releaseDir,
  version,
  arch = 'x64',
  manifestPath = null
}) {
  const root = path.resolve(releaseDir)
  if (!version || typeof version !== 'string') {
    throw new Error('Windows release candidate version is required')
  }
  if (arch !== 'x64') {
    throw new Error(`Windows-first release candidate must target x64, got ${arch}`)
  }

  const resolvedManifest = path.resolve(
    manifestPath || path.join(root, `zn-release-windows-${arch}.json`)
  )
  if (path.dirname(resolvedManifest) !== root) {
    throw new Error('Windows release candidate manifest must live in the release directory')
  }

  const manifestStat = await fs.lstat(resolvedManifest)
  if (!manifestStat.isFile() || manifestStat.isSymbolicLink()) {
    throw new Error(`Windows release candidate manifest is not a regular file: ${resolvedManifest}`)
  }
  const manifest = JSON.parse(await fs.readFile(resolvedManifest, 'utf8'))

  if (manifest?.schema !== 1) throw new Error('Windows release candidate manifest schema must be 1')
  if (manifest?.product !== 'ZN') throw new Error('Windows release candidate manifest product must be ZN')
  if (manifest?.platform !== 'windows') throw new Error(`Windows release candidate platform mismatch: ${manifest?.platform}`)
  if (manifest?.arch !== arch) throw new Error(`Windows release candidate arch mismatch: expected ${arch}, got ${manifest?.arch}`)
  if (manifest?.version !== version) {
    throw new Error(`Windows release candidate version mismatch: expected ${version}, got ${manifest?.version}`)
  }
  if (!Array.isArray(manifest?.assets)) throw new Error('Windows release candidate assets must be an array')
  if (manifest.assets.length !== 2) {
    throw new Error(`Windows release candidate must contain exactly two installer assets, got ${manifest.assets.length}`)
  }

  const seenNames = new Set()
  const extensionCounts = new Map([['.exe', 0], ['.msi', 0]])
  const verifiedAssets = []

  for (const asset of manifest.assets) {
    const name = requireSafeAssetName(asset?.name)
    if (seenNames.has(name)) throw new Error(`duplicate Windows release candidate asset: ${name}`)
    seenNames.add(name)

    const extension = path.extname(name).toLowerCase()
    if (!REQUIRED_EXTENSIONS.has(extension)) {
      throw new Error(`unexpected Windows release candidate asset extension: ${name}`)
    }
    extensionCounts.set(extension, extensionCounts.get(extension) + 1)

    if (!Number.isSafeInteger(asset?.size) || asset.size <= 0) {
      throw new Error(`Windows release candidate asset size is invalid: ${name}`)
    }
    if (typeof asset?.sha256 !== 'string' || !SHA256_RE.test(asset.sha256)) {
      throw new Error(`Windows release candidate asset SHA-256 is invalid: ${name}`)
    }

    const filePath = path.join(root, name)
    const stat = await fs.lstat(filePath)
    if (!stat.isFile() || stat.isSymbolicLink()) {
      throw new Error(`Windows release candidate asset is not a regular file: ${name}`)
    }
    if (stat.size !== asset.size) {
      throw new Error(`Windows release candidate asset size mismatch for ${name}: expected ${asset.size}, got ${stat.size}`)
    }
    const digest = await sha256File(filePath)
    if (digest.toLowerCase() !== asset.sha256.toLowerCase()) {
      throw new Error(`Windows release candidate asset SHA-256 mismatch for ${name}`)
    }
    verifiedAssets.push({ name, size: stat.size, sha256: digest })
  }

  for (const extension of REQUIRED_EXTENSIONS) {
    if (extensionCounts.get(extension) !== 1) {
      throw new Error(`Windows release candidate must contain exactly one ${extension} installer`)
    }
  }

  return {
    manifestPath: resolvedManifest,
    version,
    arch,
    assets: verifiedAssets.sort((a, b) => a.name.localeCompare(b.name))
  }
}

async function main() {
  const releaseDir = path.resolve(process.argv[2] || 'apps/desktop/release')
  const version = String(process.argv[3] || '').trim()
  const arch = String(process.argv[4] || 'x64').trim()
  if (!version) {
    throw new Error('usage: verify-zn-windows-release-candidate.mjs <release-dir> <version> [arch]')
  }
  const verified = await verifyZnWindowsReleaseCandidate({ releaseDir, version, arch })
  for (const asset of verified.assets) {
    console.log(`[zn-windows-candidate] verified ${asset.name} (${asset.size} bytes, sha256=${asset.sha256})`)
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main()
}
