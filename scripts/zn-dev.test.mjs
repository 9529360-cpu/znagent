// Contract tests for the one-command source bootstrap (scripts/zn-dev.mjs)
// and the source startup verifier (scripts/verify-zn-source-start.mjs).
//
// Run: node --test scripts/zn-dev.test.mjs
//
// Salvaged from work/dev-bootstrap-quickstart-v2@dbf568c. The v2 test file
// contained two tests asserting desktop behavior against
// apps/desktop/electron/zn-main.ts and zn-resident-autostart.ts; the desktop
// was removed from this repository in #623, so those tests have no subject
// here and are not carried over. The remaining pure-function contracts are
// kept, plus static guards that the bootstrap stays desktop-free.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import {
  isSupportedNodeVersion,
  isSupportedPythonVersion,
  pythonCandidatesFor,
  resolveDevHome,
  uvCandidatesFor,
  venvPythonPathFor
} from './zn-dev.mjs'
import {
  sourceBootstrapPaths,
  validateSourceEndpoint
} from './verify-zn-source-start.mjs'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8')

test('runtime version bounds match repository contracts', () => {
  assert.equal(isSupportedNodeVersion('22.22.0'), true)
  assert.equal(isSupportedNodeVersion('22.21.9'), false)
  assert.equal(isSupportedPythonVersion('3.11.0'), true)
  assert.equal(isSupportedPythonVersion('3.12.8'), true)
  assert.equal(isSupportedPythonVersion('3.13.7'), true)
  assert.equal(isSupportedPythonVersion('3.14.0'), false)
})

test('Windows virtualenv interpreter path uses Scripts/python.exe', () => {
  assert.equal(venvPythonPathFor('C:\\repo\\.venv', 'win32'), 'C:\\repo\\.venv\\Scripts\\python.exe')
})

test('explicit development Python wins over platform discovery', () => {
  const [first] = pythonCandidatesFor('win32', { ZN_DEV_PYTHON: 'D:\\Python312\\python.exe' })
  assert.deepEqual(first, {
    command: 'D:\\Python312\\python.exe',
    argsPrefix: [],
    source: 'ZN_DEV_PYTHON'
  })
})

test('uv can be pinned and otherwise falls back to PATH discovery', () => {
  assert.deepEqual(uvCandidatesFor({ ZN_DEV_UV: 'D:\\tools\\uv.exe' }), [
    { command: 'D:\\tools\\uv.exe', source: 'ZN_DEV_UV' },
    { command: 'uv', source: 'PATH' }
  ])
  assert.deepEqual(uvCandidatesFor({}), [{ command: 'uv', source: 'PATH' }])
})

test('development state defaults stay inside the source checkout', () => {
  assert.equal(resolveDevHome(root, {}), path.join(root, '.dev', 'zn-home'))
})

test('development state location can be explicitly overridden', () => {
  assert.equal(resolveDevHome(root, { ZN_DEV_AGENT_HOME: './tmp/home' }), path.resolve('./tmp/home'))
})

test('source-start verifier pins the Resident to isolated source state', () => {
  const paths = sourceBootstrapPaths(root, {})
  assert.equal(paths.devHome, path.join(root, '.dev', 'zn-home'))
  assert.equal(paths.endpointPath, path.join(root, '.dev', 'zn-home', 'kernel', 'resident-endpoint.json'))

  const endpoint = {
    version: 2,
    transport: 'tcp',
    host: '127.0.0.1',
    port: 43123,
    pid: 1234,
    instance_id: 'source-smoke',
    python: paths.pythonPath,
    authentication: {
      scheme: 'session-secret-v1',
      secret: 'a'.repeat(48)
    }
  }
  assert.equal(validateSourceEndpoint(endpoint, { pythonPath: paths.pythonPath }), endpoint)
  assert.throws(
    () => validateSourceEndpoint({ ...endpoint, host: '0.0.0.0' }, { pythonPath: paths.pythonPath }),
    /not loopback/
  )
  assert.throws(
    () => validateSourceEndpoint({ ...endpoint, python: path.join(root, 'other-python') }, { pythonPath: paths.pythonPath }),
    /python mismatch/
  )
  assert.throws(
    () => validateSourceEndpoint({ ...endpoint, version: 1 }, { pythonPath: paths.pythonPath }),
    /version 2/
  )
})

test('source bootstrap stays free of desktop coupling', () => {
  const launcher = read('scripts/zn-dev.mjs')
  const verifier = read('scripts/verify-zn-source-start.mjs')
  for (const source of [launcher, verifier]) {
    assert.doesNotMatch(source, /apps\/desktop/)
    assert.doesNotMatch(source, /[Ee]lectron/)
    assert.doesNotMatch(source, /zn-main/)
  }
  assert.doesNotMatch(verifier, /from ['"]\.\.\/apps\//)
})

test('dev launcher starts the resident engine, not a desktop shell', () => {
  const launcher = read('scripts/zn-dev.mjs')
  assert.match(launcher, /zn_agent\.resident/)
  assert.match(launcher, /ZN_AGENT_HOME:/)
  assert.match(launcher, /PLAYWRIGHT_BROWSERS_PATH:/)
})

test('source-start verifier terminates the whole spawned tree', () => {
  const verifier = read('scripts/verify-zn-source-start.mjs')
  assert.match(verifier, /detached: process\.platform !== ['"]win32['"]/)
  assert.match(verifier, /process\.kill\(-child\.pid, ['"]SIGTERM['"]\)/)
})
