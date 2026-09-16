import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

import {
  assertZnWindowsAuthenticodeTrust,
  parseZnWindowsSigningPublishers,
  verifyZnWindowsUpdateAuthenticode,
  type ZnWindowsAuthenticodeExec
} from './zn-windows-update-trust'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')
const repoRoot = path.resolve(desktopRoot, '..', '..')

function readRepo(relative: string): string {
  return fs.readFileSync(path.join(repoRoot, relative), 'utf8')
}

test('trusted Windows publisher configuration trims and deduplicates for certificate rotation', () => {
  assert.deepEqual(
    parseZnWindowsSigningPublishers(' ZN Project ; Example Corp;zn project;; '),
    ['ZN Project', 'Example Corp']
  )
  assert.deepEqual(parseZnWindowsSigningPublishers(undefined), [])
})

test('Authenticode trust requires a valid signature from an embedded publisher', () => {
  assert.deepEqual(
    assertZnWindowsAuthenticodeTrust(
      { status: 'Valid', publisher: 'ZN Project', thumbprint: 'aa11' },
      'Previous Publisher; ZN Project'
    ),
    { status: 'Valid', publisher: 'ZN Project', thumbprint: 'AA11' }
  )

  assert.throws(
    () => assertZnWindowsAuthenticodeTrust(
      { status: 'HashMismatch', publisher: 'ZN Project', thumbprint: 'AA11' },
      'ZN Project'
    ),
    /signature is not valid/
  )
  assert.throws(
    () => assertZnWindowsAuthenticodeTrust(
      { status: 'Valid', publisher: 'Other Publisher', thumbprint: 'AA11' },
      'ZN Project'
    ),
    /publisher is not trusted/
  )
  assert.throws(
    () => assertZnWindowsAuthenticodeTrust(
      { status: 'Valid', publisher: 'ZN Project', thumbprint: 'AA11' },
      ''
    ),
    /no trusted Windows update publishers/
  )
})

test('Windows installer verification passes the path through environment rather than PowerShell source', async () => {
  let observedExecutable = ''
  let observedArgs: string[] = []
  let observedPath = ''
  const execute: ZnWindowsAuthenticodeExec = async (executable, args, options) => {
    observedExecutable = executable
    observedArgs = args
    observedPath = String(options.env.ZN_VERIFY_UPDATE_PATH || '')
    return {
      stdout: JSON.stringify({
        status: 'Valid',
        publisher: 'ZN Project',
        thumbprint: 'BB22'
      })
    }
  }

  const installer = String.raw`C:\Users\Alice\Downloads\ZN 1.2.3; literal.exe`
  const result = await verifyZnWindowsUpdateAuthenticode(
    installer,
    'ZN Project',
    execute,
    { SystemRoot: String.raw`C:\Windows` }
  )

  assert.equal(observedExecutable, String.raw`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`)
  assert.equal(observedPath, installer)
  assert.equal(observedArgs.includes(installer), false)
  assert.equal(observedArgs.includes('-NoProfile'), true)
  assert.deepEqual(result, {
    status: 'Valid',
    publisher: 'ZN Project',
    thumbprint: 'BB22'
  })
})

test('Windows installer verification fails before process launch without a packaged trust root', async () => {
  let calls = 0
  const execute: ZnWindowsAuthenticodeExec = async () => {
    calls += 1
    return { stdout: '{}' }
  }

  await assert.rejects(
    verifyZnWindowsUpdateAuthenticode('C:\\update.exe', '', execute),
    /no trusted Windows update publishers/
  )
  assert.equal(calls, 0)
})

test('formal release and updater wiring retain one signing trust chain', () => {
  const builder = readRepo('apps/desktop/electron-builder.zn.yml')
  const bundle = readRepo('apps/desktop/scripts/bundle-electron-main.mjs')
  const updater = readRepo('apps/desktop/electron/zn-release-updater.ts')
  const workflow = readRepo('.github/workflows/zn-release.yml')
  const releaseVerifier = readRepo('apps/desktop/scripts/verify-zn-windows-authenticode.ps1')

  // Development and clean-install candidates deliberately retain the existing
  // unsigned builder baseline. Only the formal tag workflow may override it.
  assert.match(builder, /signAndEditExecutable:\s*false/)
  assert.match(bundle, /process\.env\.ZN_WINDOWS_SIGNING_PUBLISHERS/)
  assert.match(updater, /verifyZnWindowsUpdateAuthenticode/)
  assert.match(updater, /process\.env\.ZN_WINDOWS_SIGNING_PUBLISHERS/)
  assert.match(workflow, /WIN_CSC_LINK/)
  assert.match(workflow, /WIN_CSC_KEY_PASSWORD/)
  assert.match(workflow, /ZN_WINDOWS_SIGNING_PUBLISHERS/)
  assert.match(workflow, /signAndEditExecutable=true/)
  assert.match(workflow, /forceCodeSigning=true/)
  assert.match(workflow, /verify-zn-windows-authenticode\.ps1/)
  assert.match(releaseVerifier, /Get-AuthenticodeSignature/)
  assert.match(releaseVerifier, /Status -ne 'Valid'/)
  assert.match(releaseVerifier, /GetNameInfo/)
})
