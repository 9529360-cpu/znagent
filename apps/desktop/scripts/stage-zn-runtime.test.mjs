import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const source = fs.readFileSync(path.join(here, 'stage-zn-runtime.mjs'), 'utf8')

test('runtime staging derives backend root from the installed zn_agent module', () => {
  assert.match(source, /importlib\.util\.find_spec\(['"]zn_agent['"]\)/)
  assert.match(source, /Path\(spec\.origin\)\.resolve\(\)\.parent\.parent/)
  assert.match(source, /backend_root:\s*portableRelative\(runtimeRoot, backendRoot\)/)
  assert.doesNotMatch(source, /site\.getsitepackages\(\)/)
})

test('Windows runtime staging removes uv top-level Python aliases before packaging', () => {
  assert.match(source, /function removeWindowsPythonAliases\(/)
  assert.match(source, /entry\.isSymbolicLink\(\)/)
  assert.match(source, /fs\.realpathSync\(candidate\)/)
  assert.match(source, /fs\.unlinkSync\(candidate\)/)
  assert.match(source, /removeWindowsPythonAliases\(pythonInstallDir, pythonPath\)/)
  assert.match(source, /unsupported top-level aliases/)
})
