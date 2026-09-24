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
  resolveDevUserData,
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
  assert.equal(resolveDevUserData(root, {}), path.join(root, '.dev', 'electron-user-data'))
})

test('development state locations can be explicitly overridden', () => {
  assert.equal(resolveDevHome(root, { ZN_DEV_AGENT_HOME: './tmp/home' }), path.resolve('./tmp/home'))
  assert.equal(resolveDevUserData(root, { ZN_DEV_USER_DATA: './tmp/profile' }), path.resolve('./tmp/profile'))
})

test('source-start verifier pins Resident and Electron to isolated source state', () => {
  const paths = sourceBootstrapPaths(root, {})
  assert.equal(paths.devHome, path.join(root, '.dev', 'zn-home'))
  assert.equal(paths.userData, path.join(root, '.dev', 'electron-user-data'))
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
})

test('source desktop creates isolated profile paths before lock and skips protocol registration', () => {
  const main = read('apps/desktop/electron/zn-main.ts')
  const configureIndex = main.indexOf('configureSourceDevelopmentProfile()')
  const lockIndex = main.indexOf('requestSingleInstanceLock()')
  const mkdirIndex = main.indexOf('fs.mkdirSync(resolved')
  const setPathIndex = main.indexOf("app.setPath('userData'")
  assert.ok(configureIndex >= 0 && configureIndex < lockIndex)
  assert.ok(mkdirIndex >= 0 && mkdirIndex < setPathIndex)
  assert.match(main, /fs\.mkdirSync\(sessionData, \{ recursive: true \}\)/)
  assert.match(main, /app\.setPath\(['"]userData['"]/)
  assert.match(main, /app\.setPath\(['"]sessionData['"]/)
  assert.match(main, /sourceDevelopment[\s\S]*skips zn:\/\/ OS protocol registration/)
  assert.match(main, /else if \(!app\.setAsDefaultProtocolClient\(['"]zn['"]\)\)/)
})

test('source desktop cannot install login autostart and launcher supplies isolated identities', () => {
  const autostart = read('apps/desktop/electron/zn-resident-autostart.ts')
  const launcher = read('scripts/zn-dev.mjs')
  assert.match(autostart, /!app\.isPackaged && process\.env\.ZN_DESKTOP_DEV === ['"]1['"]/)
  assert.match(launcher, /ZN_DESKTOP_DEV:\s*['"]1['"]/)
  assert.match(launcher, /ZN_DESKTOP_USER_DATA:/)
  assert.match(launcher, /ZN_AGENT_HOME:/)
  assert.match(launcher, /ZN_RESIDENT_PYTHON:/)
  assert.match(launcher, /PLAYWRIGHT_BROWSERS_PATH:/)
})
