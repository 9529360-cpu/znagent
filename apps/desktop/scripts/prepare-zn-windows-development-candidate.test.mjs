import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  prepareZnWindowsDevelopmentCandidate,
  verifyZnWindowsDevelopmentCandidatePayload
} from './prepare-zn-windows-development-candidate.mjs'

const VERSION = '0.17.0'
const COMMIT = 'a'.repeat(40)
const WORKFLOW = 'ZN Windows Clean Install'
const RUN_ID = '35123456789'
const RUN_ATTEMPT = 2
const EXE_NAME = `ZN-${VERSION}-win-x64.exe`
const MSI_NAME = `ZN-${VERSION}-win-x64.msi`
const PROVENANCE_NAME = 'zn-windows-x64-development-candidate.json'

function digest(bytes) {
  return createHash('sha256').update(bytes).digest('hex')
}

async function fixture() {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'zn-development-candidate-'))
  const releaseDir = path.join(root, 'release')
  const payloadDir = path.join(root, 'payload')
  await fs.mkdir(releaseDir, { recursive: true })
  const exe = Buffer.from('verified-nsis-exe')
  const msi = Buffer.from('formal-msi-only')
  const assets = [
    { name: EXE_NAME, size: exe.length, sha256: digest(exe) },
    { name: MSI_NAME, size: msi.length, sha256: digest(msi) }
  ]
  await fs.writeFile(path.join(releaseDir, EXE_NAME), exe)
  await fs.writeFile(path.join(releaseDir, MSI_NAME), msi)
  await fs.writeFile(
    path.join(releaseDir, 'zn-release-windows-x64.json'),
    `${JSON.stringify({
      schema: 1,
      product: 'ZN',
      repository: '9529360-cpu/znagent',
      version: VERSION,
      tag: null,
      platform: 'windows',
      arch: 'x64',
      generated_at: '2026-09-16T00:00:00.000Z',
      assets
    }, null, 2)}\n`,
    'utf8'
  )
  return {
    root,
    releaseDir,
    payloadDir,
    cleanup: () => fs.rm(root, { recursive: true, force: true })
  }
}

test('packages only the exact verified NSIS installer plus development provenance', async () => {
  const item = await fixture()
  try {
    const result = await prepareZnWindowsDevelopmentCandidate({
      releaseDir: item.releaseDir,
      payloadDir: item.payloadDir,
      version: VERSION,
      commitSha: COMMIT,
      workflowName: WORKFLOW,
      runId: RUN_ID,
      runAttempt: RUN_ATTEMPT,
      expectedInstallerName: EXE_NAME
    })

    const entries = (await fs.readdir(item.payloadDir)).sort()
    assert.deepEqual(entries, [EXE_NAME, PROVENANCE_NAME].sort())
    assert.equal(result.provenance.artifact_type, 'development_candidate')
    assert.equal(result.provenance.formal_release, false)
    assert.equal(result.provenance.commit_sha, COMMIT)
    assert.equal(result.provenance.installer.name, EXE_NAME)
    assert.equal(result.provenance.installer.sha256, digest(Buffer.from('verified-nsis-exe')))
    assert.equal(result.provenance.verification.workflow.name, WORKFLOW)
    assert.equal(result.provenance.verification.workflow.run_id, RUN_ID)
    assert.equal(result.provenance.verification.workflow.run_attempt, RUN_ATTEMPT)
    assert.deepEqual(result.provenance.verification.scope, [
      'packaged_runtime_verified',
      'windows_release_manifest_verified',
      'real_nsis_install_completed',
      'installed_desktop_resident_life_verified',
      'resident_autostart_continuity_verified'
    ])
    assert.doesNotMatch(JSON.stringify(result.provenance), /\.msi|zn-release-windows-x64\.json/)
  } finally {
    await item.cleanup()
  }
})

test('rejects provenance preparation when the verified exe is not the installer that was actually used', async () => {
  const item = await fixture()
  try {
    await assert.rejects(
      prepareZnWindowsDevelopmentCandidate({
        releaseDir: item.releaseDir,
        payloadDir: item.payloadDir,
        version: VERSION,
        commitSha: COMMIT,
        workflowName: WORKFLOW,
        runId: RUN_ID,
        runAttempt: RUN_ATTEMPT,
        expectedInstallerName: 'different.exe'
      }),
      /does not match the installer used for clean install/
    )
    assert.deepEqual(await fs.readdir(item.payloadDir), [])
  } finally {
    await item.cleanup()
  }
})

test('payload verification rejects installer drift after provenance is written', async () => {
  const item = await fixture()
  try {
    await prepareZnWindowsDevelopmentCandidate({
      releaseDir: item.releaseDir,
      payloadDir: item.payloadDir,
      version: VERSION,
      commitSha: COMMIT,
      workflowName: WORKFLOW,
      runId: RUN_ID,
      runAttempt: RUN_ATTEMPT,
      expectedInstallerName: EXE_NAME
    })
    await fs.writeFile(path.join(item.payloadDir, EXE_NAME), 'tampered')
    await assert.rejects(
      verifyZnWindowsDevelopmentCandidatePayload({
        payloadDir: item.payloadDir,
        expectedVersion: VERSION,
        expectedCommitSha: COMMIT,
        expectedRunId: RUN_ID
      }),
      /size mismatch|SHA-256 mismatch/
    )
  } finally {
    await item.cleanup()
  }
})

test('payload verification rejects extra files so formal release metadata cannot leak into the candidate artifact', async () => {
  const item = await fixture()
  try {
    await prepareZnWindowsDevelopmentCandidate({
      releaseDir: item.releaseDir,
      payloadDir: item.payloadDir,
      version: VERSION,
      commitSha: COMMIT,
      workflowName: WORKFLOW,
      runId: RUN_ID,
      runAttempt: RUN_ATTEMPT,
      expectedInstallerName: EXE_NAME
    })
    await fs.writeFile(path.join(item.payloadDir, 'zn-release-windows-x64.json'), '{}')
    await assert.rejects(
      verifyZnWindowsDevelopmentCandidatePayload({
        payloadDir: item.payloadDir,
        expectedVersion: VERSION,
        expectedCommitSha: COMMIT,
        expectedRunId: RUN_ID
      }),
      /must contain only the verified EXE and provenance/
    )
  } finally {
    await item.cleanup()
  }
})
