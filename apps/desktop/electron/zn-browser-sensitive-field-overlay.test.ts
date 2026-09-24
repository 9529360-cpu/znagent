import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const extensionRoot = path.resolve(here, '..', 'browser-extension')

type Classifier = (attributes: Record<string, string>) => string

function classifier(): Classifier {
  const background = readFileSync(path.join(extensionRoot, 'background.js'), 'utf8')
  const overlay = readFileSync(path.join(extensionRoot, 'privacy-background.js'), 'utf8')
  const start = background.indexOf('function normalizedAutocomplete')
  const end = background.indexOf('async function sha256Text')
  assert.notEqual(start, -1, 'background classifier start was not found')
  assert.notEqual(end, -1, 'background classifier end was not found')
  assert.ok(end > start, 'background classifier source order changed')

  const imported: string[] = []
  const context = vm.createContext({
    importScripts: (...files: string[]) => imported.push(...files)
  })
  new vm.Script(background.slice(start, end), { filename: 'background-classifier.js' }).runInContext(context)
  new vm.Script(overlay, { filename: 'privacy-background.js' }).runInContext(context)
  assert.deepEqual(imported, ['research-background.js'])

  const classify = (context as { sensitiveTextboxKind?: Classifier }).sensitiveTextboxKind
  assert.equal(typeof classify, 'function')
  return classify as Classifier
}

test('recovery-code structural markers reuse the user-presence code class without broad code matching', () => {
  const classify = classifier()

  assert.equal(classify({ autocomplete: 'one-time-code', name: 'backup_code' }), 'one_time_code')
  assert.equal(classify({ autocomplete: 'current-password', name: 'backup_code' }), 'password')
  assert.equal(classify({ autocomplete: 'cc-number', name: 'backup_code' }), 'payment')
  assert.equal(classify({ autocomplete: 'off', name: 'account_recovery_code' }), 'one_time_code')
  assert.equal(classify({ type: 'password', id: 'backup-code' }), 'password')
  assert.equal(classify({ type: 'text', 'aria-label': 'Use emergency code' }), 'one_time_code')
  assert.equal(classify({ type: 'text', placeholder: 'Enter recovery codes' }), 'one_time_code')
  assert.equal(classify({ type: 'text', name: 'discount_code' }), '')
  assert.equal(classify({ type: 'text', placeholder: 'recovery codec' }), '')
  assert.equal(classify({ type: 'password', name: 'credential' }), 'password')
})
