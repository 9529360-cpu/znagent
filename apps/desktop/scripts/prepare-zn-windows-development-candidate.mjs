#!/usr/bin/env node
import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import { verifyZnWindowsReleaseCandidate } from './verify-zn-windows-release-candidate.mjs'

const COMMIT_SHA_RE = /^[0-9a-f]{40}$/i
const SHA256_RE = /^[0-9a-f]{64}$/i
const REPOSITORY = '9529360-cpu/znagent'
const ARCH = 'x64'
const PAYLOAD_PROVENANCE = 'zn-windows-x64-development-candidate.json'
const WORKFLOW_FILE = '.github/workflows/zn-windows-clean-install.yml'
const VERIFICATION_SCOPE = Object.freeze([
  'packaged_runtime_verified',
  'windows_release_manifest_verified',
  'real_nsis_install_completed',
  'installed_desktop_resident_life_verified',
  'resident_autostart_continuity_verified'
])

async function sha256File(filePath) {
  const hash = createHash('sha256')
  const input = createReadStream(filePath)
  for await (const chunk of input) hash.update(chunk)
  return hash.digest('hex')
}

function requireNonEmpty(value, label) {
  const normalized = String(value || '').trim()
  if (!normalized) throw new Error(`${label} is required`)
  return normalized
}

function requireCommitSha(value) {
  const normalized = requireNonEmpty(value, 'candidate commit SHA')
  if (!COMMIT_SHA_RE.test(normalized)) {
    throw new Error(`candidate commit SHA must be 40 hex characters: ${normalized}`)
  }
  return normalized.toLowerCase()
}

function requireRunId(value) {
  const normalized = requireNonEmpty(value, 'candidate workflow run id')
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`candidate workflow run id must contain only digits: ${normalized}`)
  }
  return normalized
}

function requireRunAttempt(value) {
  const normalized = requireNonEmpty(value, 'candidate workflow run attempt')
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`candidate workflow run attempt must be a positive integer: ${value}`)
  }
  const parsed = Number(normalized)
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error(`candidate workflow run attempt must be a positive integer: ${value}`)
  }
  return parsed
}

function requireSafeFileName(value, label) {
  const name = requireNonEmpty(value, label)
  if (name === '.' || name === '..' || name.includes('/') || name.includes('\\')) {
    throw new Error(`${label} is unsafe: ${name}`)
  }
  return name
}

async function requireEmptyDirectory(root) {
  await fs.mkdir(root, { recursive: true })
  const entries = await fs.readdir(root)
  if (entries.length !== 0) {
    throw new Error(`development candidate payload directory must be empty: ${root}`)
  }
}

export async function verifyZnWindowsDevelopmentCandidatePayload({
  payloadDir,
  expectedVersion,
  expectedCommitSha,
  expectedRunId = null
}) {
  const root = path.resolve(payloadDir)
  const version = requireNonEmpty(expectedVersion, 'candidate version')
  const commitSha = requireCommitSha(expectedCommitSha)
  const provenancePath = path.join(root, PAYLOAD_PROVENANCE)
  const provenanceStat = await fs.lstat(provenancePath)
  if (!provenanceStat.isFile() || provenanceStat.isSymbolicLink()) {
    throw new Error(`development candidate provenance is not a regular file: ${provenancePath}`)
  }

  const provenance = JSON.parse(await fs.readFile(provenancePath, 'utf8'))
  if (provenance?.schema !== 1) throw new Error('development candidate provenance schema must be 1')
  if (provenance?.product !== 'ZN') throw new Error('development candidate product must be ZN')
  if (provenance?.repository !== REPOSITORY) throw new Error('development candidate repository mismatch')
  if (provenance?.artifact_type !== 'development_candidate') {
    throw new Error('development candidate artifact_type must be development_candidate')
  }
  if (provenance?.formal_release !== false) {
    throw new Error('development candidate must not identify itself as a formal release')
  }
  if (provenance?.version !== version) throw new Error('development candidate version mismatch')
  if (String(provenance?.commit_sha || '').toLowerCase() !== commitSha) {
    throw new Error('development candidate commit SHA mismatch')
  }
  if (provenance?.platform !== 'windows' || provenance?.arch !== ARCH) {
    throw new Error('development candidate platform/arch mismatch')
  }

  const installerName = requireSafeFileName(provenance?.installer?.name, 'development candidate installer name')
  if (path.extname(installerName).toLowerCase() !== '.exe') {
    throw new Error(`development candidate installer must be an EXE: ${installerName}`)
  }
  if (!Number.isSafeInteger(provenance?.installer?.size) || provenance.installer.size <= 0) {
    throw new Error('development candidate installer size is invalid')
  }
  if (typeof provenance?.installer?.sha256 !== 'string' || !SHA256_RE.test(provenance.installer.sha256)) {
    throw new Error('development candidate installer SHA-256 is invalid')
  }

  const workflow = provenance?.verification?.workflow
  if (workflow?.file !== WORKFLOW_FILE) throw new Error('development candidate workflow file mismatch')
  requireNonEmpty(workflow?.name, 'development candidate workflow name')
  const runId = requireRunId(workflow?.run_id)
  requireRunAttempt(workflow?.run_attempt)
  if (expectedRunId !== null && runId !== String(expectedRunId)) {
    throw new Error('development candidate workflow run id mismatch')
  }
  const scope = provenance?.verification?.scope
  if (!Array.isArray(scope) || scope.length !== VERIFICATION_SCOPE.length || scope.some((item, index) => item !== VERIFICATION_SCOPE[index])) {
    throw new Error('development candidate verification scope mismatch')
  }

  const entries = await fs.readdir(root, { withFileTypes: true })
  const names = entries.map(entry => entry.name).sort()
  const expectedNames = [installerName, PAYLOAD_PROVENANCE].sort()
  if (entries.length !== 2 || names.some((name, index) => name !== expectedNames[index])) {
    throw new Error(`development candidate payload must contain only the verified EXE and provenance: ${names.join(', ')}`)
  }
  for (const entry of entries) {
    if (!entry.isFile() || entry.isSymbolicLink()) {
      throw new Error(`development candidate payload entry is not a regular file: ${entry.name}`)
    }
  }

  const installerPath = path.join(root, installerName)
  const installerStat = await fs.lstat(installerPath)
  if (installerStat.size !== provenance.installer.size) {
    throw new Error('development candidate installer size mismatch')
  }
  const digest = await sha256File(installerPath)
  if (digest.toLowerCase() !== provenance.installer.sha256.toLowerCase()) {
    throw new Error('development candidate installer SHA-256 mismatch')
  }

  return { provenancePath, installerPath, provenance }
}

export async function prepareZnWindowsDevelopmentCandidate({
  releaseDir,
  payloadDir,
  version,
  commitSha,
  workflowName,
  runId,
  runAttempt,
  expectedInstallerName
}) {
  const releaseRoot = path.resolve(releaseDir)
  const payloadRoot = path.resolve(payloadDir)
  const normalizedVersion = requireNonEmpty(version, 'candidate version')
  const normalizedCommitSha = requireCommitSha(commitSha)
  const normalizedWorkflowName = requireNonEmpty(workflowName, 'candidate workflow name')
  const normalizedRunId = requireRunId(runId)
  const normalizedRunAttempt = requireRunAttempt(runAttempt)
  const installedName = requireSafeFileName(expectedInstallerName, 'installed candidate name')

  await requireEmptyDirectory(payloadRoot)
  const verified = await verifyZnWindowsReleaseCandidate({
    releaseDir: releaseRoot,
    version: normalizedVersion,
    arch: ARCH
  })
  const installer = verified.assets.find(asset => path.extname(asset.name).toLowerCase() === '.exe')
  if (!installer) throw new Error('verified Windows release candidate has no EXE installer')
  if (installer.name !== installedName) {
    throw new Error(`verified EXE does not match the installer used for clean install: expected ${installedName}, got ${installer.name}`)
  }

  const sourceInstaller = path.join(releaseRoot, installer.name)
  const payloadInstaller = path.join(payloadRoot, installer.name)
  await fs.copyFile(sourceInstaller, payloadInstaller)

  const provenance = {
    schema: 1,
    product: 'ZN',
    repository: REPOSITORY,
    artifact_type: 'development_candidate',
    formal_release: false,
    version: normalizedVersion,
    commit_sha: normalizedCommitSha,
    platform: 'windows',
    arch: ARCH,
    installer: {
      name: installer.name,
      size: installer.size,
      sha256: installer.sha256
    },
    verification: {
      workflow: {
        name: normalizedWorkflowName,
        file: WORKFLOW_FILE,
        run_id: normalizedRunId,
        run_attempt: normalizedRunAttempt
      },
      scope: [...VERIFICATION_SCOPE]
    },
    generated_at: new Date().toISOString()
  }
  const provenancePath = path.join(payloadRoot, PAYLOAD_PROVENANCE)
  await fs.writeFile(provenancePath, `${JSON.stringify(provenance, null, 2)}\n`, 'utf8')

  return verifyZnWindowsDevelopmentCandidatePayload({
    payloadDir: payloadRoot,
    expectedVersion: normalizedVersion,
    expectedCommitSha: normalizedCommitSha,
    expectedRunId: normalizedRunId
  })
}

async function main() {
  const [releaseDir, payloadDir, version, commitSha, workflowName, runId, runAttempt, expectedInstallerName] = process.argv.slice(2)
  if (!expectedInstallerName) {
    throw new Error('usage: prepare-zn-windows-development-candidate.mjs <release-dir> <payload-dir> <version> <commit-sha> <workflow-name> <run-id> <run-attempt> <installed-exe-name>')
  }
  const result = await prepareZnWindowsDevelopmentCandidate({
    releaseDir,
    payloadDir,
    version,
    commitSha,
    workflowName,
    runId,
    runAttempt,
    expectedInstallerName
  })
  const installer = result.provenance.installer
  console.log(`[zn-development-candidate] prepared ${installer.name} (${installer.size} bytes, sha256=${installer.sha256})`)
  console.log(`[zn-development-candidate] provenance ${result.provenancePath}`)
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  await main()
}
