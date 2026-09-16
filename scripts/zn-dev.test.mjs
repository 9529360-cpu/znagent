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
  venvPythonPathFor
} from './zn-dev.mjs'

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

test('development state defaults stay inside the source checkout', () => {
  assert.equal(resolveDevHome(root, {}), path.join(root, '.dev', 'zn-home'))
  assert.equal(resolveDevUserData(root, {}), path.join(root, '.dev', 'electron-user-data'))
})

test('development state locations can be explicitly overridden', () => {
  assert.equal(resolveDevHome(root, { ZN_DEV_AGENT_HOME: './tmp/home' }), path.resolve('./tmp/home'))
  assert.equal(resolveDevUserData(root, { ZN_DEV_USER_DATA: './tmp/profile' }), path.resolve('./tmp/profile'))
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
