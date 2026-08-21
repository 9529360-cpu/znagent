#!/usr/bin/env node
import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const releaseDir = path.resolve(here, '..', 'release')
const platform = String(process.argv[2] || process.platform).trim()
const version = String(process.argv[3] || '').trim()
const tag = String(process.argv[4] || '').trim()

if (!version) {
  throw new Error('usage: write-zn-release-manifest.mjs <platform> <version> [tag]')
}

const installerExtensions = new Set(['.dmg', '.zip', '.exe', '.msi', '.AppImage', '.deb', '.rpm'])
const entries = await fs.readdir(releaseDir, { withFileTypes: true })
const assets = []

for (const entry of entries) {
  if (!entry.isFile()) continue
  const extension = path.extname(entry.name)
  if (!installerExtensions.has(extension)) continue

  const filePath = path.join(releaseDir, entry.name)
  const bytes = await fs.readFile(filePath)
  const stat = await fs.stat(filePath)
  assets.push({
    name: entry.name,
    size: stat.size,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex')
  })
}

assets.sort((a, b) => a.name.localeCompare(b.name))
if (assets.length === 0) {
  throw new Error(`no ZN installer assets found in ${releaseDir}`)
}

const manifest = {
  schema: 1,
  product: 'ZN',
  repository: '9529360-cpu/znagent',
  version,
  tag: tag || null,
  platform,
  arch: process.arch,
  generated_at: new Date().toISOString(),
  assets
}

const output = path.join(releaseDir, `zn-release-${platform}-${process.arch}.json`)
await fs.writeFile(output, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
console.log(output)
