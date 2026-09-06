#!/usr/bin/env node
import assert from 'node:assert/strict'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  validateContinuityBaseline,
  validateEndpoint,
  validateInstalledLayout
} from './verify-zn-windows-clean-install.mjs'

const AUTH = { scheme: 'session-secret-v1', secret: 's'.repeat(64) }

function endpointFixture({ znHome, runtimeId, ...overrides }) {
  return {
    version: 2,
    transport: 'tcp',
    host: '127.0.0.1',
    port: 42001,
    pid: 1234,
    instance_id: 'resident-instance',
    runtime_id: runtimeId,
    python: path.join(znHome, 'runtime', runtimeId, 'python', 'cpython', 'python.exe'),
    authentication: { ...AUTH },
    ...overrides
  }
}

test('installed layout is rooted in the requested installation directory', () => {
  const root = path.join(os.tmpdir(), 'zn-clean-install-layout')
  const layout = validateInstalledLayout(root)
  assert.equal(layout.root, path.resolve(root))
  assert.equal(layout.executable, path.join(path.resolve(root), 'ZN.exe'))
  assert.equal(layout.appAsar, path.join(path.resolve(root), 'resources', 'app.asar'))
  assert.equal(layout.bundledRuntime, path.join(path.resolve(root), 'resources', 'zn-runtime'))
})

test('endpoint accepts exact isolated materialized runtime identity', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  const endpoint = endpointFixture({ znHome, runtimeId })
  assert.equal(validateEndpoint(endpoint, { znHome, expectedRuntimeId: runtimeId }), endpoint)
})

test('endpoint rejects a stale runtime id', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  assert.throws(() => validateEndpoint(endpointFixture({
    znHome,
    runtimeId,
    runtime_id: 'fedcba9876543210fedcba9876543210fedcba98'
  }), { znHome, expectedRuntimeId: runtimeId }), /resident runtime mismatch/)
})

test('endpoint rejects Python outside the isolated installed runtime', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  assert.throws(() => validateEndpoint(endpointFixture({
    znHome,
    runtimeId,
    python: path.join(os.tmpdir(), 'foreign-python', 'python.exe')
  }), { znHome, expectedRuntimeId: runtimeId }), /outside isolated installed runtime/)
})

test('endpoint rejects non-loopback transport evidence', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  assert.throws(() => validateEndpoint(endpointFixture({
    znHome,
    runtimeId,
    host: '0.0.0.0'
  }), { znHome, expectedRuntimeId: runtimeId }), /not loopback/)
})

test('endpoint rejects missing or malformed authentication material', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  assert.throws(() => validateEndpoint(endpointFixture({
    znHome,
    runtimeId,
    authentication: undefined
  }), { znHome, expectedRuntimeId: runtimeId }), /authentication metadata is missing/)
  assert.throws(() => validateEndpoint(endpointFixture({
    znHome,
    runtimeId,
    authentication: { scheme: 'session-secret-v1', secret: 'short' }
  }), { znHome, expectedRuntimeId: runtimeId }), /authentication secret is invalid/)
})

const HASH_A = 'a'.repeat(64)
const HASH_B = 'b'.repeat(64)
const HASH_C = 'c'.repeat(64)
const HASH_E = 'e'.repeat(64)
const HASH_F = 'f'.repeat(64)

function proof(hashes = [HASH_A], section = 'stable_refs') {
  return {
    algorithm: 'sha256',
    count: hashes.length,
    section_counts: { [section]: hashes.length },
    digest: 'd'.repeat(64),
    reference_hashes: hashes
  }
}

function atomicRecoveryProof() {
  return {
    version: 1,
    algorithm: 'sha256',
    protocol_count: 1,
    protocols: [{
      reference_hash: HASH_A,
      attempt_hash: HASH_B,
      event_hash: HASH_C,
      stage_rank: 2,
      stage_identity_hash: HASH_E,
      write_strategy: 'replace_file_with_backup'
    }],
    verified_attempt_hashes: [],
    native_completion_attempt_hashes: [],
    terminal_event_hashes: [HASH_F],
    digest: 'd'.repeat(64)
  }
}

function continuityBaseline() {
  return {
    schema_version: 2,
    identity: {
      name: 'ZN Agent',
      version: '0.2.0',
      created_at: '2026-01-01T00:00:00+00:00',
      updated_at: '2026-01-02T00:00:00+00:00'
    },
    living_self: {
      name: 'ZN Agent',
      version: '0.2.0',
      born_at: '2026-01-01T00:00:00+00:00',
      wake_count: 1,
      pulse_count: 2,
      last_event_id: null,
      learning_candidate_ids: []
    },
    resident_state: {
      full_state_proof: proof([HASH_A], 'resident_intention_anchors')
    },
    long_lived_memory: {
      full_reference_proof: proof([HASH_B], 'neural_traces')
    },
    work: {
      reference_count: 1,
      total_count: 1,
      reference_limit: 100,
      references_may_be_truncated: false,
      threads: [{ id: 'work-1', created_at: '2026-01-01T00:00:00+00:00' }],
      full_state_proof: {
        ...proof([HASH_A, HASH_B], 'work_messages'),
        thread_count: 1
      }
    },
    verified_learning: {
      reference_count: 1,
      total_count: 1,
      reference_limit: 256,
      references_may_be_truncated: false,
      experience_ids: ['vx-1234'],
      retention_capacity: 2048,
      full_reference_proof: proof([HASH_A], 'verified_experiences')
    },
    atomic_overwrite_recovery: atomicRecoveryProof(),
    provider: {
      mode: 'default',
      provider: 'auto',
      model: '',
      base_url: '',
      credential: { configured: false, source: 'none', environment_name: null },
      active_routes: [],
      cognition_available: false
    }
  }
}

test('continuity baseline accepts complete privacy-preserving resident proofs', () => {
  const baseline = continuityBaseline()
  assert.equal(validateContinuityBaseline(baseline), baseline)
})

test('continuity baseline still accepts legacy schema-2 snapshot without complete proofs', () => {
  const baseline = continuityBaseline()
  delete baseline.resident_state.full_state_proof
  delete baseline.long_lived_memory.full_reference_proof
  delete baseline.work.full_state_proof
  delete baseline.verified_learning.full_reference_proof
  delete baseline.verified_learning.retention_capacity
  delete baseline.atomic_overwrite_recovery
  assert.equal(validateContinuityBaseline(baseline), baseline)
})

test('continuity baseline rejects Work content beyond reference identity', () => {
  const baseline = continuityBaseline()
  baseline.work.threads[0].title = 'must not leave resident'
  assert.throws(() => validateContinuityBaseline(baseline), /unexpected field: title/)
})

test('continuity baseline rejects causal learning payload beyond hashed experience identity', () => {
  const baseline = continuityBaseline()
  baseline.verified_learning.payload = { task: 'must not leave resident' }
  assert.throws(() => validateContinuityBaseline(baseline), /unexpected field: payload/)
})

test('continuity baseline rejects duplicate verified learning references', () => {
  const baseline = continuityBaseline()
  baseline.verified_learning.reference_count = 2
  baseline.verified_learning.total_count = 2
  baseline.verified_learning.experience_ids = ['vx-1234', 'vx-1234']
  assert.throws(() => validateContinuityBaseline(baseline), /must be unique/)
})

test('continuity baseline rejects plaintext fields smuggled into proof containers', () => {
  const baseline = continuityBaseline()
  baseline.resident_state.private_intention = 'must stay resident-only'
  assert.throws(() => validateContinuityBaseline(baseline), /unexpected field: private_intention/)
})

test('continuity baseline rejects malformed or duplicate hash references', () => {
  const malformed = continuityBaseline()
  malformed.resident_state.full_state_proof.reference_hashes = ['private-not-a-hash']
  assert.throws(() => validateContinuityBaseline(malformed), /reference hash is invalid/)

  const duplicate = continuityBaseline()
  duplicate.resident_state.full_state_proof = proof([HASH_A, HASH_A], 'resident_intention_anchors')
  assert.throws(() => validateContinuityBaseline(duplicate), /reference hashes must be unique/)
})

test('continuity baseline rejects proof counts inconsistent with section totals', () => {
  const baseline = continuityBaseline()
  baseline.long_lived_memory.full_reference_proof.section_counts.neural_traces = 2
  assert.throws(() => validateContinuityBaseline(baseline), /section counts do not match count/)
})

test('continuity baseline rejects verified learning beyond declared retention capacity', () => {
  const baseline = continuityBaseline()
  baseline.verified_learning.retention_capacity = 0
  assert.throws(() => validateContinuityBaseline(baseline), /retention_capacity is invalid/)
})

test('continuity baseline rejects Work proof thread count inconsistent with durable total', () => {
  const baseline = continuityBaseline()
  baseline.work.full_state_proof.thread_count = 2
  assert.throws(() => validateContinuityBaseline(baseline), /thread_count does not match total_count/)
})

test('continuity baseline rejects plaintext or extra atomic recovery fields', () => {
  const baseline = continuityBaseline()
  baseline.atomic_overwrite_recovery.protocols[0].staging_path = 'C:/private/stage.tmp'
  assert.throws(() => validateContinuityBaseline(baseline), /unexpected field: staging_path/)
})

test('continuity baseline rejects malformed atomic recovery hashes', () => {
  const baseline = continuityBaseline()
  baseline.atomic_overwrite_recovery.protocols[0].attempt_hash = 'attempt-private'
  assert.throws(() => validateContinuityBaseline(baseline), /attempt_hash is invalid/)
})

test('continuity baseline rejects duplicate atomic recovery protocol references', () => {
  const baseline = continuityBaseline()
  baseline.atomic_overwrite_recovery.protocol_count = 2
  baseline.atomic_overwrite_recovery.protocols.push({
    ...baseline.atomic_overwrite_recovery.protocols[0],
    attempt_hash: HASH_C,
    event_hash: HASH_E
  })
  assert.throws(() => validateContinuityBaseline(baseline), /reference hashes must be unique/)
})

test('continuity baseline rejects impossible atomic recovery rank and strategy pairs', () => {
  const stagedWithStrategy = continuityBaseline()
  stagedWithStrategy.atomic_overwrite_recovery.protocols[0].stage_rank = 1
  assert.throws(() => validateContinuityBaseline(stagedWithStrategy), /unexpectedly has write_strategy/)

  const commitWithoutStrategy = continuityBaseline()
  commitWithoutStrategy.atomic_overwrite_recovery.protocols[0].write_strategy = null
  assert.throws(() => validateContinuityBaseline(commitWithoutStrategy), /write_strategy is invalid/)
})

test('continuity baseline rejects duplicate or oversized atomic discharge witnesses', () => {
  const duplicate = continuityBaseline()
  duplicate.atomic_overwrite_recovery.verified_attempt_hashes = [HASH_A, HASH_A]
  assert.throws(() => validateContinuityBaseline(duplicate), /hashes must be unique/)

  const oversized = continuityBaseline()
  oversized.atomic_overwrite_recovery.native_completion_attempt_hashes = [HASH_A, HASH_B]
  assert.throws(() => validateContinuityBaseline(oversized), /too large/)
})
