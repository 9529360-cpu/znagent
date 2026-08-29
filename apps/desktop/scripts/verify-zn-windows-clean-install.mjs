#!/usr/bin/env node
import fs from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const SHA_RE = /^[0-9a-f]{7,40}$/i
const SHA256_RE = /^[0-9a-f]{64}$/

function inside(root, target) {
  const relative = path.relative(path.resolve(root), path.resolve(target))
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))
}

export function validateInstalledLayout(installDir) {
  const root = path.resolve(installDir)
  return {
    root,
    executable: path.join(root, 'ZN.exe'),
    resources: path.join(root, 'resources'),
    appAsar: path.join(root, 'resources', 'app.asar'),
    bundledRuntime: path.join(root, 'resources', 'zn-runtime')
  }
}

export function validateEndpoint(endpoint, { znHome, expectedRuntimeId }) {
  if (!endpoint || typeof endpoint !== 'object') throw new Error('resident endpoint must be an object')
  if (endpoint.version !== 1 || endpoint.transport !== 'tcp') {
    throw new Error('resident endpoint must use version 1 tcp transport')
  }
  if (endpoint.host !== '127.0.0.1') throw new Error(`resident endpoint host is not loopback: ${endpoint.host}`)
  if (!Number.isInteger(endpoint.port) || endpoint.port <= 0 || endpoint.port > 65535) {
    throw new Error(`resident endpoint port is invalid: ${endpoint.port}`)
  }
  if (!Number.isInteger(endpoint.pid) || endpoint.pid <= 0) throw new Error('resident endpoint pid is invalid')
  if (typeof endpoint.instance_id !== 'string' || !endpoint.instance_id.trim()) {
    throw new Error('resident endpoint instance_id is missing')
  }
  if (endpoint.runtime_id !== expectedRuntimeId) {
    throw new Error(`resident runtime mismatch: expected ${expectedRuntimeId}, got ${endpoint.runtime_id}`)
  }
  if (typeof endpoint.python !== 'string' || !endpoint.python.trim()) {
    throw new Error('resident endpoint python is missing')
  }
  if (!inside(path.join(znHome, 'runtime', expectedRuntimeId), endpoint.python)) {
    throw new Error(`resident python is outside isolated installed runtime: ${endpoint.python}`)
  }
  return endpoint
}

function requireNonEmptyString(value, label) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${label} is missing`)
  return value
}

function rejectUnexpectedFields(value, allowed, label) {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new Error(`${label} exposes unexpected field: ${key}`)
  }
}

function validateReferenceProof(proof, label, { allowThreadCount = false } = {}) {
  if (!proof || typeof proof !== 'object' || Array.isArray(proof)) {
    throw new Error(`${label} is invalid`)
  }
  const allowed = new Set(['algorithm', 'count', 'section_counts', 'digest', 'reference_hashes'])
  if (allowThreadCount) allowed.add('thread_count')
  rejectUnexpectedFields(proof, allowed, label)
  if (proof.algorithm !== 'sha256') throw new Error(`${label} algorithm is invalid`)
  if (!Number.isInteger(proof.count) || proof.count < 0) throw new Error(`${label} count is invalid`)
  if (!SHA256_RE.test(String(proof.digest || ''))) throw new Error(`${label} digest is invalid`)
  if (!Array.isArray(proof.reference_hashes) || proof.reference_hashes.length !== proof.count) {
    throw new Error(`${label} reference hashes are inconsistent`)
  }
  if (proof.reference_hashes.some(value => typeof value !== 'string' || !SHA256_RE.test(value))) {
    throw new Error(`${label} reference hash is invalid`)
  }
  if (new Set(proof.reference_hashes).size !== proof.reference_hashes.length) {
    throw new Error(`${label} reference hashes must be unique`)
  }
  if (!proof.section_counts || typeof proof.section_counts !== 'object' || Array.isArray(proof.section_counts)) {
    throw new Error(`${label} section_counts is invalid`)
  }
  let sectionTotal = 0
  for (const [section, count] of Object.entries(proof.section_counts)) {
    if (!section.trim() || !Number.isInteger(count) || count < 0) {
      throw new Error(`${label} section count is invalid`)
    }
    sectionTotal += count
  }
  if (sectionTotal !== proof.count) throw new Error(`${label} section counts do not match count`)
  if (allowThreadCount && (!Number.isInteger(proof.thread_count) || proof.thread_count < 0)) {
    throw new Error(`${label} thread_count is invalid`)
  }
  return proof
}

function validateOptionalProofContainer(container, label, proofKey, options = {}) {
  if (!container || typeof container !== 'object' || Array.isArray(container)) {
    throw new Error(`${label} is invalid`)
  }
  rejectUnexpectedFields(container, new Set([proofKey]), label)
  if (Object.hasOwn(container, proofKey)) validateReferenceProof(container[proofKey], `${label} ${proofKey}`, options)
}

function validateHashArray(value, label, { maxLength = null } = {}) {
  if (!Array.isArray(value)) throw new Error(`${label} is invalid`)
  if (maxLength !== null && value.length > maxLength) throw new Error(`${label} is too large`)
  if (value.some(item => typeof item !== 'string' || !SHA256_RE.test(item))) {
    throw new Error(`${label} contains invalid hash`)
  }
  if (new Set(value).size !== value.length) throw new Error(`${label} hashes must be unique`)
  return value
}

function validateAtomicRecoveryProof(proof) {
  const label = 'continuity atomic_overwrite_recovery'
  if (!proof || typeof proof !== 'object' || Array.isArray(proof)) throw new Error(`${label} is invalid`)
  rejectUnexpectedFields(
    proof,
    new Set(['version', 'algorithm', 'protocol_count', 'protocols', 'verified_attempt_hashes', 'native_completion_attempt_hashes', 'terminal_event_hashes', 'digest']),
    label
  )
  if (proof.version !== 1) throw new Error(`${label} version is invalid`)
  if (proof.algorithm !== 'sha256') throw new Error(`${label} algorithm is invalid`)
  if (!Number.isInteger(proof.protocol_count) || proof.protocol_count < 0) throw new Error(`${label} protocol_count is invalid`)
  if (!Array.isArray(proof.protocols) || proof.protocols.length !== proof.protocol_count) {
    throw new Error(`${label} protocols are inconsistent`)
  }
  const protocolHashes = []
  for (const protocol of proof.protocols) {
    if (!protocol || typeof protocol !== 'object' || Array.isArray(protocol)) throw new Error(`${label} protocol is invalid`)
    rejectUnexpectedFields(
      protocol,
      new Set(['reference_hash', 'attempt_hash', 'event_hash', 'stage_rank', 'stage_identity_hash', 'write_strategy']),
      `${label} protocol`
    )
    for (const key of ['reference_hash', 'attempt_hash', 'event_hash', 'stage_identity_hash']) {
      if (typeof protocol[key] !== 'string' || !SHA256_RE.test(protocol[key])) {
        throw new Error(`${label} protocol ${key} is invalid`)
      }
    }
    if (![1, 2].includes(protocol.stage_rank)) throw new Error(`${label} protocol stage_rank is invalid`)
    if (protocol.stage_rank === 1 && protocol.write_strategy !== null) {
      throw new Error(`${label} staged protocol unexpectedly has write_strategy`)
    }
    if (protocol.stage_rank === 2 && !['replace_file_with_backup', 'move_new_no_replace'].includes(protocol.write_strategy)) {
      throw new Error(`${label} commit-started protocol write_strategy is invalid`)
    }
    protocolHashes.push(protocol.reference_hash)
  }
  if (new Set(protocolHashes).size !== protocolHashes.length) {
    throw new Error(`${label} protocol reference hashes must be unique`)
  }
  validateHashArray(proof.verified_attempt_hashes, `${label} verified_attempt_hashes`)
  validateHashArray(proof.native_completion_attempt_hashes, `${label} native_completion_attempt_hashes`, { maxLength: 1 })
  validateHashArray(proof.terminal_event_hashes, `${label} terminal_event_hashes`)
  if (typeof proof.digest !== 'string' || !SHA256_RE.test(proof.digest)) throw new Error(`${label} digest is invalid`)
  return proof
}

export function validateContinuityBaseline(baseline) {
  if (!baseline || typeof baseline !== 'object' || Array.isArray(baseline)) {
    throw new Error('resident continuity snapshot must be an object')
  }
  rejectUnexpectedFields(
    baseline,
    new Set(['schema_version', 'identity', 'living_self', 'resident_state', 'long_lived_memory', 'work', 'verified_learning', 'atomic_overwrite_recovery', 'provider']),
    'continuity snapshot'
  )
  if (baseline.schema_version !== 2) throw new Error(`unsupported continuity schema: ${baseline.schema_version}`)

  const identity = baseline.identity
  if (!identity || typeof identity !== 'object' || Array.isArray(identity)) throw new Error('continuity identity is invalid')
  rejectUnexpectedFields(identity, new Set(['name', 'version', 'created_at', 'updated_at']), 'continuity identity')
  requireNonEmptyString(identity.name, 'continuity identity name')
  requireNonEmptyString(identity.version, 'continuity identity version')
  requireNonEmptyString(identity.created_at, 'continuity identity created_at')
  requireNonEmptyString(identity.updated_at, 'continuity identity updated_at')

  const livingSelf = baseline.living_self
  if (!livingSelf || typeof livingSelf !== 'object' || Array.isArray(livingSelf)) throw new Error('continuity living_self is invalid')
  rejectUnexpectedFields(livingSelf, new Set(['name', 'version', 'born_at', 'wake_count', 'pulse_count', 'last_event_id', 'learning_candidate_ids']), 'continuity living_self')
  requireNonEmptyString(livingSelf.name, 'continuity living_self name')
  requireNonEmptyString(livingSelf.version, 'continuity living_self version')
  requireNonEmptyString(livingSelf.born_at, 'continuity living_self born_at')
  if (!Number.isInteger(livingSelf.wake_count) || livingSelf.wake_count < 1) throw new Error('continuity wake_count is invalid')
  if (!Number.isInteger(livingSelf.pulse_count) || livingSelf.pulse_count < 1) throw new Error('continuity pulse_count is invalid')
  if (livingSelf.last_event_id !== null && typeof livingSelf.last_event_id !== 'string') throw new Error('continuity last_event_id is invalid')
  if (!Array.isArray(livingSelf.learning_candidate_ids) || livingSelf.learning_candidate_ids.some(value => typeof value !== 'string')) {
    throw new Error('continuity learning_candidate_ids is invalid')
  }

  validateOptionalProofContainer(baseline.resident_state, 'continuity resident_state', 'full_state_proof')
  validateOptionalProofContainer(baseline.long_lived_memory, 'continuity long_lived_memory', 'full_reference_proof')

  const work = baseline.work
  if (!work || typeof work !== 'object' || Array.isArray(work)) throw new Error('continuity work is invalid')
  rejectUnexpectedFields(work, new Set(['reference_count', 'total_count', 'reference_limit', 'references_may_be_truncated', 'threads', 'full_state_proof']), 'continuity work')
  if (!Number.isInteger(work.reference_count) || work.reference_count < 0) throw new Error('continuity work reference_count is invalid')
  if (!Number.isInteger(work.total_count) || work.total_count < work.reference_count) throw new Error('continuity work total_count is invalid')
  if (!Number.isInteger(work.reference_limit) || work.reference_limit < 1) throw new Error('continuity work reference_limit is invalid')
  if (typeof work.references_may_be_truncated !== 'boolean') throw new Error('continuity work truncation marker is invalid')
  if (!Array.isArray(work.threads) || work.threads.length !== work.reference_count) throw new Error('continuity work references are inconsistent')
  for (const thread of work.threads) {
    if (!thread || typeof thread !== 'object' || Array.isArray(thread)) throw new Error('continuity work thread reference is invalid')
    rejectUnexpectedFields(thread, new Set(['id', 'created_at']), 'continuity work thread')
    requireNonEmptyString(thread.id, 'continuity work thread id')
    requireNonEmptyString(thread.created_at, 'continuity work thread created_at')
  }
  if (Object.hasOwn(work, 'full_state_proof')) {
    const proof = validateReferenceProof(work.full_state_proof, 'continuity work full_state_proof', { allowThreadCount: true })
    if (proof.thread_count !== work.total_count) throw new Error('continuity work proof thread_count does not match total_count')
  }

  const verifiedLearning = baseline.verified_learning
  if (!verifiedLearning || typeof verifiedLearning !== 'object' || Array.isArray(verifiedLearning)) {
    throw new Error('continuity verified_learning is invalid')
  }
  rejectUnexpectedFields(
    verifiedLearning,
    new Set(['reference_count', 'total_count', 'reference_limit', 'references_may_be_truncated', 'experience_ids', 'retention_capacity', 'full_reference_proof']),
    'continuity verified_learning'
  )
  if (!Number.isInteger(verifiedLearning.reference_count) || verifiedLearning.reference_count < 0) {
    throw new Error('continuity verified_learning reference_count is invalid')
  }
  if (!Number.isInteger(verifiedLearning.total_count) || verifiedLearning.total_count < verifiedLearning.reference_count) {
    throw new Error('continuity verified_learning total_count is invalid')
  }
  if (!Number.isInteger(verifiedLearning.reference_limit) || verifiedLearning.reference_limit < 1) {
    throw new Error('continuity verified_learning reference_limit is invalid')
  }
  if (typeof verifiedLearning.references_may_be_truncated !== 'boolean') {
    throw new Error('continuity verified_learning truncation marker is invalid')
  }
  if (!Array.isArray(verifiedLearning.experience_ids) || verifiedLearning.experience_ids.length !== verifiedLearning.reference_count) {
    throw new Error('continuity verified_learning references are inconsistent')
  }
  if (verifiedLearning.experience_ids.some(value => typeof value !== 'string' || !value.trim())) {
    throw new Error('continuity verified_learning experience id is invalid')
  }
  if (new Set(verifiedLearning.experience_ids).size !== verifiedLearning.experience_ids.length) {
    throw new Error('continuity verified_learning experience ids must be unique')
  }
  if (Object.hasOwn(verifiedLearning, 'retention_capacity')) {
    if (!Number.isInteger(verifiedLearning.retention_capacity) || verifiedLearning.retention_capacity < 1) {
      throw new Error('continuity verified_learning retention_capacity is invalid')
    }
    if (verifiedLearning.total_count > verifiedLearning.retention_capacity) {
      throw new Error('continuity verified_learning total_count exceeds retention_capacity')
    }
  }
  if (Object.hasOwn(verifiedLearning, 'full_reference_proof')) {
    const proof = validateReferenceProof(verifiedLearning.full_reference_proof, 'continuity verified_learning full_reference_proof')
    if (proof.count !== verifiedLearning.total_count) {
      throw new Error('continuity verified_learning proof count does not match total_count')
    }
  }

  if (Object.hasOwn(baseline, 'atomic_overwrite_recovery')) {
    validateAtomicRecoveryProof(baseline.atomic_overwrite_recovery)
  }

  const provider = baseline.provider
  if (!provider || typeof provider !== 'object' || Array.isArray(provider)) throw new Error('continuity provider is invalid')
  rejectUnexpectedFields(provider, new Set(['mode', 'provider', 'model', 'base_url', 'credential', 'active_routes', 'cognition_available']), 'continuity provider')
  for (const key of ['mode', 'provider', 'model', 'base_url']) {
    if (typeof provider[key] !== 'string') throw new Error(`continuity provider ${key} is invalid`)
  }
  const credential = provider.credential
  if (!credential || typeof credential !== 'object' || Array.isArray(credential)) throw new Error('continuity provider credential metadata is invalid')
  rejectUnexpectedFields(credential, new Set(['configured', 'source', 'environment_name']), 'continuity credential')
  if (typeof credential.configured !== 'boolean') throw new Error('continuity credential configured flag is invalid')
  if (typeof credential.source !== 'string') throw new Error('continuity credential source is invalid')
  if (credential.environment_name !== null && typeof credential.environment_name !== 'string') {
    throw new Error('continuity credential environment_name is invalid')
  }
  if (!Array.isArray(provider.active_routes)) throw new Error('continuity provider routes are invalid')
  for (const route of provider.active_routes) {
    if (!route || typeof route !== 'object' || Array.isArray(route)) throw new Error('continuity provider route is invalid')
    rejectUnexpectedFields(route, new Set(['id', 'provider', 'model']), 'continuity provider route')
    for (const key of ['id', 'provider', 'model']) {
      if (typeof route[key] !== 'string') throw new Error(`continuity provider route ${key} is invalid`)
    }
  }
  if (typeof provider.cognition_available !== 'boolean') throw new Error('continuity cognition flag is invalid')

  return baseline
}

async function requireRegularFile(filePath, label) {
  const stat = await fs.lstat(filePath)
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`${label} is not a regular file: ${filePath}`)
}

async function requireDirectory(dirPath, label) {
  const stat = await fs.lstat(dirPath)
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error(`${label} is not a directory: ${dirPath}`)
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
  throw new Error(`resident endpoint did not retire: ${filePath}`)
}

export async function rpcRequest(endpoint, method, params = {}, timeoutMs = 5000) {
  return await new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: endpoint.host, port: endpoint.port })
    let buffer = ''
    const requestId = `clean-install-${process.pid}-${Date.now()}`
    const timer = setTimeout(() => {
      socket.destroy()
      reject(new Error(`resident RPC timed out: ${method}`))
    }, timeoutMs)
    const fail = error => {
      clearTimeout(timer)
      socket.destroy()
      reject(error)
    }
    socket.once('error', fail)
    socket.once('connect', () => {
      socket.write(`${JSON.stringify({ id: requestId, method, params })}\n`)
    })
    socket.on('data', chunk => {
      buffer += chunk.toString('utf8')
      const newline = buffer.indexOf('\n')
      if (newline < 0) return
      const line = buffer.slice(0, newline)
      let response
      try { response = JSON.parse(line) } catch (error) { fail(error); return }
      if (response.id !== requestId) return
      clearTimeout(timer)
      socket.end()
      if (response.ok === false) reject(new Error(response.error || `resident RPC failed: ${method}`))
      else resolve(response.result)
    })
  })
}

export async function verifyZnWindowsCleanInstall({ installDir, znHome, expectedRuntimeId, continuityOutputPath = null, timeoutMs = 60000 }) {
  if (process.platform !== 'win32') throw new Error(`clean install proof requires win32, got ${process.platform}`)
  if (!SHA_RE.test(expectedRuntimeId)) throw new Error(`expected runtime id must be a commit-like SHA: ${expectedRuntimeId}`)

  const layout = validateInstalledLayout(installDir)
  await requireRegularFile(layout.executable, 'installed ZN executable')
  await requireDirectory(layout.resources, 'installed resources directory')
  await requireRegularFile(layout.appAsar, 'installed app.asar')
  await requireDirectory(layout.bundledRuntime, 'installed bundled runtime')
  await requireRegularFile(path.join(layout.bundledRuntime, 'runtime.json'), 'installed bundled runtime manifest')

  const endpointPath = path.join(path.resolve(znHome), 'kernel', 'resident-endpoint.json')
  const endpoint = validateEndpoint(await waitForJson(endpointPath, timeoutMs), {
    znHome: path.resolve(znHome),
    expectedRuntimeId
  })
  await requireRegularFile(endpoint.python, 'materialized resident python')
  await requireRegularFile(
    path.join(path.resolve(znHome), 'runtime', expectedRuntimeId, 'runtime.json'),
    'materialized runtime manifest'
  )

  const ping = await rpcRequest(endpoint, 'ping')
  if (!ping || ping.alive !== true || !Number.isInteger(ping.pulse_count) || ping.pulse_count < 1) {
    throw new Error(`installed resident ping is invalid: ${JSON.stringify(ping)}`)
  }
  const status = await rpcRequest(endpoint, 'status')
  if (!status || typeof status !== 'object') throw new Error('installed resident status is invalid')
  const self = await rpcRequest(endpoint, 'self')
  if (!self || typeof self !== 'object') throw new Error('installed resident self snapshot is invalid')
  const continuity = validateContinuityBaseline(await rpcRequest(endpoint, 'continuity_snapshot'))
  if (continuityOutputPath) {
    const outputPath = path.resolve(continuityOutputPath)
    await fs.mkdir(path.dirname(outputPath), { recursive: true })
    await fs.writeFile(outputPath, `${JSON.stringify(continuity, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' })
  }

  await rpcRequest(endpoint, 'shutdown')
  await waitForMissing(endpointPath, Math.min(timeoutMs, 15000))

  return {
    executable: layout.executable,
    endpointPath,
    runtimeId: endpoint.runtime_id,
    python: endpoint.python,
    pulseCount: ping.pulse_count,
    instanceId: endpoint.instance_id,
    continuity
  }
}

async function main() {
  const installDir = String(process.argv[2] || '').trim()
  const znHome = String(process.argv[3] || '').trim()
  const expectedRuntimeId = String(process.argv[4] || '').trim().toLowerCase()
  const continuityOutputPath = String(process.argv[5] || '').trim() || null
  if (!installDir || !znHome || !expectedRuntimeId) {
    throw new Error('usage: verify-zn-windows-clean-install.mjs <install-dir> <zn-home> <expected-runtime-id> [continuity-output-path]')
  }
  const result = await verifyZnWindowsCleanInstall({ installDir, znHome, expectedRuntimeId, continuityOutputPath })
  console.log(`[zn-clean-install] executable=${result.executable}`)
  console.log(`[zn-clean-install] runtime=${result.runtimeId}`)
  console.log(`[zn-clean-install] python=${result.python}`)
  console.log(`[zn-clean-install] pulse_count=${result.pulseCount}`)
  console.log(`[zn-clean-install] instance_id=${result.instanceId}`)
  console.log(`[zn-clean-install] continuity_schema=${result.continuity.schema_version}`)
  console.log(`[zn-clean-install] continuity_born_at=${result.continuity.living_self.born_at}`)
  console.log(`[zn-clean-install] continuity_work_refs=${result.continuity.work.reference_count}`)
  console.log(`[zn-clean-install] continuity_verified_learning_refs=${result.continuity.verified_learning.reference_count}`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main()
}
