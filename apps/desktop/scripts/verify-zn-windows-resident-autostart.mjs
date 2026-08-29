#!/usr/bin/env node
import { execFile } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'

import {
  rpcRequest,
  validateContinuityBaseline,
  validateEndpoint
} from './verify-zn-windows-clean-install.mjs'

const TASK_NAME = 'ZN Resident'
const SHA_RE = /^[0-9a-f]{7,40}$/i

function inside(root, target) {
  const relative = path.relative(path.resolve(root), path.resolve(target))
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

function sameWindowsPath(left, right) {
  return path.resolve(String(left)).toLowerCase() === path.resolve(String(right)).toLowerCase()
}

function decodeXmlText(value) {
  return String(value || '')
    .replaceAll('&quot;', '"')
    .replaceAll('&apos;', "'")
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>')
    .replaceAll('&amp;', '&')
}

function xmlText(xml, tag) {
  const match = String(xml).match(new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`, 'i'))
  return match ? decodeXmlText(match[1].trim()) : ''
}

export function validateScheduledTaskXml(xml, { znHome, expectedRuntimeId }) {
  const command = xmlText(xml, 'Command')
  const args = xmlText(xml, 'Arguments')
  if (!command) throw new Error('ZN Resident scheduled task command is missing')
  if (!path.isAbsolute(command)) throw new Error(`ZN Resident scheduled task command is not absolute: ${command}`)

  const runtimeRoot = path.join(path.resolve(znHome), 'runtime', expectedRuntimeId)
  if (!inside(runtimeRoot, command)) {
    throw new Error(`ZN Resident scheduled task command is outside installed runtime: ${command}`)
  }
  if (!/(^|\s)-m(\s|$)/.test(args) || !/(^|\s)zn_agent\.resident(\s|$)/.test(args)) {
    throw new Error(`ZN Resident scheduled task does not launch formal resident: ${args}`)
  }
  if (!/(^|\s)--home(\s|$)/.test(args) || !args.toLowerCase().includes(path.resolve(znHome).toLowerCase())) {
    throw new Error(`ZN Resident scheduled task does not pin ZN home: ${args}`)
  }
  return { command, args }
}

function decodeProcessOutput(buffer) {
  if (!Buffer.isBuffer(buffer)) return String(buffer || '')
  if (buffer.length >= 2 && buffer[0] === 0xff && buffer[1] === 0xfe) {
    return buffer.subarray(2).toString('utf16le')
  }
  const utf8 = buffer.toString('utf8')
  if (utf8.includes('\u0000')) return buffer.toString('utf16le').replace(/^\ufeff/, '')
  return utf8.replace(/^\ufeff/, '')
}

function run(command, args) {
  return new Promise((resolve, reject) => {
    execFile(command, args, { encoding: 'buffer', windowsHide: true, maxBuffer: 4 * 1024 * 1024 }, (error, stdout, stderr) => {
      if (error) {
        const detail = decodeProcessOutput(stderr).trim() || decodeProcessOutput(stdout).trim() || error.message
        reject(new Error(`${command} ${args.join(' ')} failed: ${detail}`))
        return
      }
      resolve(decodeProcessOutput(stdout))
    })
  })
}

async function waitForTaskXml(timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    try {
      return await run('schtasks', ['/Query', '/TN', TASK_NAME, '/XML'])
    } catch (error) {
      lastError = error
      await new Promise(resolve => setTimeout(resolve, 250))
    }
  }
  throw new Error(`timed out waiting for ${TASK_NAME} scheduled task: ${lastError}`)
}

async function waitForJson(filePath, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    try {
      return JSON.parse(await fs.readFile(filePath, 'utf8'))
    } catch (error) {
      lastError = error
      await new Promise(resolve => setTimeout(resolve, 250))
    }
  }
  throw new Error(`timed out waiting for JSON at ${filePath}: ${lastError}`)
}

async function waitForMissing(filePath, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      await fs.access(filePath)
    } catch {
      return
    }
    await new Promise(resolve => setTimeout(resolve, 200))
  }
  throw new Error(`resident endpoint remained present before autostart proof: ${filePath}`)
}

export async function verifyZnWindowsResidentAutostart({ znHome, expectedRuntimeId, baselinePath, timeoutMs = 30000 }) {
  if (process.platform !== 'win32') throw new Error(`resident autostart proof requires win32, got ${process.platform}`)
  if (!SHA_RE.test(expectedRuntimeId)) throw new Error(`expected runtime id must be a commit-like SHA: ${expectedRuntimeId}`)

  const home = path.resolve(znHome)
  const endpointPath = path.join(home, 'kernel', 'resident-endpoint.json')
  const baseline = validateContinuityBaseline(JSON.parse(await fs.readFile(path.resolve(baselinePath), 'utf8')))

  await waitForMissing(endpointPath, Math.min(timeoutMs, 15000))
  const taskXml = await waitForTaskXml(Math.min(timeoutMs, 15000))
  const task = validateScheduledTaskXml(taskXml, { znHome: home, expectedRuntimeId })

  await run('schtasks', ['/Run', '/TN', TASK_NAME])
  const endpoint = validateEndpoint(await waitForJson(endpointPath, timeoutMs), {
    znHome: home,
    expectedRuntimeId
  })
  if (!sameWindowsPath(endpoint.python, task.command)) {
    throw new Error(`scheduled task Python does not match restarted resident: task=${task.command} resident=${endpoint.python}`)
  }

  try {
    const ping = await rpcRequest(endpoint, 'ping')
    if (!ping || ping.alive !== true || !Number.isInteger(ping.pulse_count) || ping.pulse_count < 1) {
      throw new Error(`autostarted resident ping is invalid: ${JSON.stringify(ping)}`)
    }

    const status = await rpcRequest(endpoint, 'status')
    if (!status || status.resident_surface?.name !== 'zn-formal-resident' || status.resident_surface?.schema !== 1) {
      throw new Error(`autostarted resident is not the formal surface: ${JSON.stringify(status?.resident_surface)}`)
    }

    const comparison = await rpcRequest(endpoint, 'continuity_compare', { baseline })
    if (!comparison || comparison.verdict?.compatible !== true) {
      throw new Error(`autostarted resident continuity is not proven: ${JSON.stringify(comparison?.verdict)}`)
    }

    return {
      endpointPath,
      runtimeId: endpoint.runtime_id,
      python: endpoint.python,
      pulseCount: ping.pulse_count,
      instanceId: endpoint.instance_id,
      continuityVerdict: comparison.verdict
    }
  } finally {
    try { await rpcRequest(endpoint, 'shutdown') } catch { void 0 }
    await waitForMissing(endpointPath, Math.min(timeoutMs, 15000))
  }
}

async function main() {
  const znHome = String(process.argv[2] || '').trim()
  const expectedRuntimeId = String(process.argv[3] || '').trim().toLowerCase()
  const baselinePath = String(process.argv[4] || '').trim()
  if (!znHome || !expectedRuntimeId || !baselinePath) {
    throw new Error('usage: verify-zn-windows-resident-autostart.mjs <zn-home> <expected-runtime-id> <continuity-baseline>')
  }
  const result = await verifyZnWindowsResidentAutostart({ znHome, expectedRuntimeId, baselinePath })
  console.log(`[zn-autostart] runtime=${result.runtimeId}`)
  console.log(`[zn-autostart] pulse_count=${result.pulseCount}`)
  console.log(`[zn-autostart] instance_id=${result.instanceId}`)
  console.log(`[zn-autostart] continuity_compatible=${result.continuityVerdict.compatible}`)
}

if (process.argv[1] && import.meta.url === new URL(`file://${path.resolve(process.argv[1]).replaceAll('\\', '/')}`).href) {
  main().catch(error => {
    console.error(error?.stack || String(error))
    process.exitCode = 1
  })
}
