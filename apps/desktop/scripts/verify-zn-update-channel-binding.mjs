#!/usr/bin/env node
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const RUNTIME_ENV_EXPRESSION = 'process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL'

export function normalizeZnUpdateChannelUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) throw new Error('expected ZN update channel URL is missing')

  let url
  try {
    url = new URL(raw)
  } catch {
    throw new Error('expected ZN update channel URL is invalid')
  }
  if (url.protocol !== 'https:' || !url.pathname.endsWith('/stable.json')) {
    throw new Error('expected ZN update channel must be an HTTPS URL ending in /stable.json')
  }
  if (url.username || url.password) {
    throw new Error('expected ZN update channel must not contain URL credentials')
  }
  return url.toString()
}

export async function verifyZnUpdateChannelBinding({ bundlePath, expectedUrl }) {
  const normalized = normalizeZnUpdateChannelUrl(expectedUrl)
  const resolvedBundle = path.resolve(bundlePath)
  const source = await fs.readFile(resolvedBundle, 'utf8')

  if (source.includes(RUNTIME_ENV_EXPRESSION)) {
    throw new Error('release bundle still depends on runtime update-channel environment configuration')
  }
  if (!source.includes(normalized)) {
    throw new Error('release bundle does not contain the expected public ZN update channel')
  }

  return { bundlePath: resolvedBundle, updateChannelUrl: normalized }
}

async function main() {
  const bundlePath = String(process.argv[2] || '').trim()
  const expectedUrl = String(process.argv[3] || process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL || '').trim()
  if (!bundlePath) {
    throw new Error('usage: verify-zn-update-channel-binding.mjs <electron-main-bundle> [expected-url]')
  }
  const result = await verifyZnUpdateChannelBinding({ bundlePath, expectedUrl })
  console.log(`[zn-update-channel] verified ${result.updateChannelUrl} in ${result.bundlePath}`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main()
}
