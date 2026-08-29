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
  const python = path.join(znHome, 'runtime', runtimeId, 'python', 'cpython', 'python.exe')
  const endpoint = {
    version: 1,
    transport: 'tcp',
    host: '127.0.0.1',
    port: 42001,
    pid: 1234,
    instance_id: 'resident-instance',
    runtime_id: runtimeId,
    python
  }
  assert.equal(validateEndpoint(endpoint, { znHome, expectedRuntimeId: runtimeId }), endpoint)
})

test('endpoint rejects a stale runtime id', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  assert.throws(() => validateEndpoint({
    version: 1,
    transport: 'tcp',
    host: '127.0.0.1',
    port: 42001,
    pid: 1234,
    instance_id: 'resident-instance',
    runtime_id: 'fedcba9876543210fedcba9876543210fedcba98',
    python: path.join(znHome, 'runtime', runtimeId, 'python.exe')
  }, { znHome, expectedRuntimeId: runtimeId }), /resident runtime mismatch/)
})

test('endpoint rejects Python outside the isolated installed runtime', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  assert.throws(() => validateEndpoint({
    version: 1,
    transport: 'tcp',
    host: '127.0.0.1',
    port: 42001,
    pid: 1234,
    instance_id: 'resident-instance',
    runtime_id: runtimeId,
    python: path.join(os.tmpdir(), 'foreign-python', 'python.exe')
  }, { znHome, expectedRuntimeId: runtimeId }), /outside isolated installed runtime/)
})

test('endpoint rejects non-loopback transport evidence', () => {
  const znHome = path.join(os.tmpdir(), 'zn-clean-install-home')
  const runtimeId = '0123456789abcdef0123456789abcdef01234567'
  assert.throws(() => validateEndpoint({
    version: 1,
    transport: 'tcp',
    host: '0.0.0.0',
    port: 42001,
    pid: 1234,
    instance_id: 'resident-instance',
    runtime_id: runtimeId,
    python: path.join(znHome, 'runtime', runtimeId, 'python.exe')
  }, { znHome, expectedRuntimeId: runtimeId }), /not loopback/)
})

test('continuity baseline accepts bounded resident-owned references', () => {
  const baseline = {
    schema_version: 1,
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
    work: {
      reference_count: 1,
      reference_limit: 100,
      references_may_be_truncated: false,
      threads: [{ id: 'work-1', created_at: '2026-01-01T00:00:00+00:00' }]
    },
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
  assert.equal(validateContinuityBaseline(baseline), baseline)
})

test('continuity baseline rejects Work content beyond reference identity', () => {
  const baseline = {
    schema_version: 1,
    identity: { name: 'ZN', version: '1', created_at: 'born', updated_at: 'now' },
    living_self: {
      name: 'ZN', version: '1', born_at: 'born', wake_count: 1, pulse_count: 1,
      last_event_id: null, learning_candidate_ids: []
    },
    work: {
      reference_count: 1,
      reference_limit: 100,
      references_may_be_truncated: false,
      threads: [{ id: 'work-1', created_at: 'born', title: 'must not leave resident' }]
    },
    provider: {
      mode: 'default', provider: 'auto', model: '', base_url: '',
      credential: { configured: false, source: 'none', environment_name: null },
      active_routes: [], cognition_available: false
    }
  }
  assert.throws(() => validateContinuityBaseline(baseline), /unexpected field: title/)
})
