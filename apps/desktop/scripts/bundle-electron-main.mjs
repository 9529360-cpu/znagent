#!/usr/bin/env node
// bundle-electron-main.mjs — bundles the ZN Electron wrapper entries into
// self-contained js files in dist/. The wrappers import the mature legacy
// desktop shell and layer ZN Resident lifecycle/IPC around it, allowing the
// migration to proceed without invasive edits to the giant legacy main file.
//
// Output:
//   dist/electron-main.mjs    (MJS bundle — entry point for packaged app)
//   dist/electron-preload.js (CJS bundle — loaded via BrowserWindow preload)
//
// `electron` and `node-pty` are external (provided by the runtime / staged
// separately via stage-native-deps).
import { build } from 'esbuild'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdirSync } from 'node:fs'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const distDir = resolve(root, 'dist')
mkdirSync(distDir, { recursive: true })

const mainEntry = resolve(root, 'electron/zn-main.ts')
const mainOut = resolve(distDir, 'electron-main.mjs')
const preloadEntry = resolve(root, 'electron/zn-preload.ts')
const preloadOut = resolve(distDir, 'electron-preload.js')

const external = ['electron', 'node-pty', 'get-windows', 'fs']
// Production bundles bake packaged=true and the public ZN update-channel URL.
// Dev bundles (`--dev`) leave process.env alone so local update-channel fixtures
// and source-tree resolution can be changed without rebuilding the bundle.
const isDev = process.argv.includes('--dev')
const define = isDev
  ? {}
  : {
      'process.env.HERMES_DESKTOP_IS_PACKAGED': JSON.stringify(true),
      'process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL': JSON.stringify(
        process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL || ''
      )
    }

// Bundle ZN wrapper main → dist/electron-main.mjs
await build({
  entryPoints: [mainEntry],
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  outfile: mainOut,
  external,
  banner: {
    js: "import { createRequire } from 'module'; const require = createRequire(import.meta.url);"
  },
  define,
  logLevel: 'info'
})
console.log(`bundled ${mainOut}${isDev ? ' (dev)' : ''}`)

// Bundle ZN wrapper preload → dist/electron-preload.js
await build({
  entryPoints: [preloadEntry],
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  outfile: preloadOut,
  external,
  define,
  logLevel: 'info'
})
console.log(`bundled ${preloadOut}${isDev ? ' (dev)' : ''}`)
