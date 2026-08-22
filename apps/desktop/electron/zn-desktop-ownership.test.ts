import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

import { parseZnDeepLink, znDeepLinksFromArgv } from './zn-protocol'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('ZN Electron main owns window and protocol lifecycle without inherited desktop main', () => {
  const source = read('electron/zn-main.ts')

  assert.match(source, /new BrowserWindow\(/)
  assert.match(source, /zn-shell\.html/)
  assert.match(source, /registerZnResidentIpc\(\)/)
  assert.match(source, /requestSingleInstanceLock\(\)/)
  assert.match(source, /setAsDefaultProtocolClient\(['"]zn['"]\)/)
  assert.match(source, /contextIsolation:\s*true/)
  assert.match(source, /nodeIntegration:\s*false/)
  assert.match(source, /sandbox:\s*true/)
  assert.doesNotMatch(source, /import\(['"]\.\/main['"]\)/)
  assert.doesNotMatch(source, /from ['"]\.\/main['"]/) 
  assert.doesNotMatch(source, /hermes_cli|run_agent|HERMES_DESKTOP/)
})

test('ZN preload exposes only the ZN bridge and does not import inherited preload', () => {
  const source = read('electron/zn-preload.ts')

  assert.match(source, /exposeInMainWorld\(['"]znDesktop['"]/)
  assert.match(source, /zn:deep-link/)
  assert.doesNotMatch(source, /import ['"]\.\/preload['"]/) 
  assert.doesNotMatch(source, /hermesDesktop|hermes:/)
})

test('active ZN shell does not mount inherited renderer control plane', () => {
  const html = read('electron/zn-shell.html')
  const renderer = read('electron/zn-shell-renderer.ts')

  assert.match(html, /zn-shell-renderer\.js/)
  assert.match(renderer, /znDesktop/)
  assert.doesNotMatch(renderer, /hermesDesktop|ContribController|gateway/i)
  assert.doesNotMatch(html, /hermes/i)
})

test('Electron bundler emits only ZN control-plane entries', () => {
  const source = read('scripts/bundle-electron-main.mjs')

  assert.match(source, /electron\/zn-main\.ts/)
  assert.match(source, /electron\/zn-preload\.ts/)
  assert.match(source, /electron\/zn-shell-renderer\.ts/)
  assert.doesNotMatch(source, /legacy desktop shell|mature legacy|HERMES_DESKTOP_IS_PACKAGED/)
})

test('ZN deep links reject inherited and web schemes and preserve inert navigation data', () => {
  assert.deepEqual(parseZnDeepLink('zn://work/thread-42?workspace=alpha&mode=inspect'), {
    url: 'zn://work/thread-42?workspace=alpha&mode=inspect',
    route: 'work',
    path: '/thread-42',
    params: { workspace: 'alpha', mode: 'inspect' }
  })
  assert.equal(parseZnDeepLink('https://example.com/work'), null)
  assert.equal(parseZnDeepLink('hermes://work/thread-42'), null)
  assert.equal(parseZnDeepLink(`zn://work/${'x'.repeat(9000)}`), null)
})

test('single-instance argv deep links are normalized and deduplicated', () => {
  assert.deepEqual(
    znDeepLinksFromArgv(['electron', '.', 'zn://resident/status', 'zn://resident/status']),
    [{ url: 'zn://resident/status', route: 'resident', path: '/status', params: {} }]
  )
})
