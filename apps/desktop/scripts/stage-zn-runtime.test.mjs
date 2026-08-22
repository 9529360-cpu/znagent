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
