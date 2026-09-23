import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')
const repoRoot = path.resolve(desktopRoot, '..', '..')

function readJson(relative) {
  return JSON.parse(fs.readFileSync(path.join(repoRoot, relative), 'utf8'))
}

test('desktop package is the single Electron version authority', () => {
  const desktop = readJson('apps/desktop/package.json')
  const lock = readJson('package-lock.json')
  const builder = fs.readFileSync(path.join(desktopRoot, 'electron-builder.zn.yml'), 'utf8')
  const runner = fs.readFileSync(path.join(here, 'run-electron-builder.mjs'), 'utf8')

  const declared = desktop?.devDependencies?.electron
  assert.match(
    declared,
    /^\d+\.\d+\.\d+$/,
    'apps/desktop/package.json must pin Electron to one exact version'
  )

  assert.equal(
    lock?.packages?.['apps/desktop']?.devDependencies?.electron,
    declared,
    'workspace lock metadata must match the desktop Electron declaration'
  )
  assert.equal(
    lock?.packages?.['node_modules/electron']?.version,
    declared,
    'installed Electron lock entry must match the desktop Electron declaration'
  )

  assert.doesNotMatch(
    builder,
    /^electronVersion\s*:/m,
    'electron-builder config must not override the package Electron version'
  )
  assert.doesNotMatch(
    runner,
    /(?:^|[^A-Za-z])electronVersion\s*=/,
    'builder wrapper must not inject a second Electron version'
  )
})
