#!/usr/bin/env node

import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { rcedit } from 'rcedit'

import { isMain } from './utils.mjs'

/** Stamp the ZN icon and Windows version resources without enabling signing. */
async function stampExeIdentity(exe, desktopRoot = resolve(import.meta.dirname, '..')) {
  if (!exe || !existsSync(exe)) {
    throw new Error(`target exe not found: ${exe}`)
  }

  const icon = join(desktopRoot, 'assets', 'icon.ico')
  if (!existsSync(icon)) {
    throw new Error(`icon not found: ${icon}`)
  }

  console.log(`[set-exe-identity] stamping ${exe}`)
  console.log(`[set-exe-identity] icon: ${icon}`)

  await rcedit(exe, {
    icon,
    'version-string': {
      ProductName: 'ZN',
      FileDescription: 'ZN',
      CompanyName: 'ZN Project',
      LegalCopyright: 'Copyright (c) 2026 ZN Project'
    }
  })

  console.log('[set-exe-identity] done — ZN icon + identity stamped')
}

export { stampExeIdentity }

if (isMain(import.meta.url)) {
  const exe = process.argv[2]
  if (!exe) {
    console.error('[set-exe-identity] usage: set-exe-identity.mjs <path-to-ZN.exe>')
    process.exit(2)
  }
  stampExeIdentity(exe).catch(err => {
    console.error(`[set-exe-identity] ${err.message}`)
    process.exit(1)
  })
}
