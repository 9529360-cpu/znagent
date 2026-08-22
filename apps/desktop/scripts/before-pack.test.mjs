import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'vitest'

import beforePack, { cleanStaleAppOutDir, preserveRollbackBackup } from '../scripts/before-pack.mjs'

test('cleanStaleAppOutDir removes a populated unpacked directory', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-before-pack-'))
  try {
    const appOutDir = path.join(tempRoot, 'linux-unpacked')
    fs.mkdirSync(appOutDir, { recursive: true })
    fs.writeFileSync(path.join(appOutDir, 'LICENSE.electron.txt'), 'x', 'utf8')
    fs.writeFileSync(path.join(appOutDir, 'resources.pak'), 'x', 'utf8')
    fs.mkdirSync(path.join(appOutDir, 'resources'), { recursive: true })
    fs.writeFileSync(path.join(appOutDir, 'resources', 'app.asar'), 'x', 'utf8')

    assert.equal(cleanStaleAppOutDir(appOutDir), true)
    assert.equal(fs.existsSync(appOutDir), false)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('cleanStaleAppOutDir is a no-op when the directory is absent', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-before-pack-'))
  try {
    assert.equal(cleanStaleAppOutDir(path.join(tempRoot, 'does-not-exist')), false)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('cleanStaleAppOutDir ignores empty or invalid input', () => {
  assert.equal(cleanStaleAppOutDir(''), false)
  assert.equal(cleanStaleAppOutDir(undefined), false)
  assert.equal(cleanStaleAppOutDir(null), false)
  assert.equal(cleanStaleAppOutDir(42), false)
})

test('beforePack default export resolves without a target arch', async () => {
  await assert.doesNotReject(beforePack({ appOutDir: '', electronPlatformName: 'linux' }))
})

test('preserveRollbackBackup moves a working ZN build to .bak', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-before-pack-'))
  try {
    const appOutDir = path.join(tempRoot, 'win-unpacked')
    fs.mkdirSync(appOutDir, { recursive: true })
    fs.writeFileSync(path.join(appOutDir, 'ZN.exe'), 'MZ-old-build', 'utf8')
    fs.writeFileSync(path.join(appOutDir, 'resources.pak'), 'x', 'utf8')

    assert.equal(preserveRollbackBackup(appOutDir, 'ZN.exe'), true)
    assert.equal(fs.existsSync(appOutDir), false)
    assert.equal(fs.readFileSync(path.join(`${appOutDir}.bak`, 'ZN.exe'), 'utf8'), 'MZ-old-build')
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('preserveRollbackBackup replaces a stale .bak from an older update', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-before-pack-'))
  try {
    const appOutDir = path.join(tempRoot, 'win-unpacked')
    fs.mkdirSync(appOutDir, { recursive: true })
    fs.writeFileSync(path.join(appOutDir, 'ZN.exe'), 'current', 'utf8')
    fs.mkdirSync(`${appOutDir}.bak`, { recursive: true })
    fs.writeFileSync(path.join(`${appOutDir}.bak`, 'ZN.exe'), 'two-updates-ago', 'utf8')

    assert.equal(preserveRollbackBackup(appOutDir, 'ZN.exe'), true)
    assert.equal(fs.readFileSync(path.join(`${appOutDir}.bak`, 'ZN.exe'), 'utf8'), 'current')
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('preserveRollbackBackup refuses a partial tree missing the product exe', () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-before-pack-'))
  try {
    const appOutDir = path.join(tempRoot, 'win-unpacked')
    fs.mkdirSync(appOutDir, { recursive: true })
    fs.writeFileSync(path.join(appOutDir, 'LICENSE.electron.txt'), 'x', 'utf8')

    assert.equal(preserveRollbackBackup(appOutDir, 'ZN.exe'), false)
    assert.equal(fs.existsSync(appOutDir), true)
    assert.equal(fs.existsSync(`${appOutDir}.bak`), false)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('preserveRollbackBackup ignores missing or invalid input', () => {
  assert.equal(preserveRollbackBackup(''), false)
  assert.equal(preserveRollbackBackup(undefined), false)
  assert.equal(preserveRollbackBackup(null), false)
  assert.equal(preserveRollbackBackup(path.join(os.tmpdir(), 'does-not-exist-xyz')), false)
})

test('beforePack on win32 preserves the previous ZN build instead of wiping it', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-before-pack-'))
  try {
    const appOutDir = path.join(tempRoot, 'win-unpacked')
    fs.mkdirSync(appOutDir, { recursive: true })
    fs.writeFileSync(path.join(appOutDir, 'ZN.exe'), 'MZ-working', 'utf8')

    await beforePack({ appOutDir, electronPlatformName: 'win32' })

    assert.equal(fs.existsSync(appOutDir), false)
    assert.equal(fs.readFileSync(path.join(`${appOutDir}.bak`, 'ZN.exe'), 'utf8'), 'MZ-working')
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})

test('beforePack on linux keeps the plain wipe (no .bak)', async () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'zn-before-pack-'))
  try {
    const appOutDir = path.join(tempRoot, 'linux-unpacked')
    fs.mkdirSync(appOutDir, { recursive: true })
    fs.writeFileSync(path.join(appOutDir, 'ZN.exe'), 'x', 'utf8')

    await beforePack({ appOutDir, electronPlatformName: 'linux' })

    assert.equal(fs.existsSync(appOutDir), false)
    assert.equal(fs.existsSync(`${appOutDir}.bak`), false)
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true })
  }
})
