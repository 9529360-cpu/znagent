#!/usr/bin/env node
// Build the independent ZN Electron control plane. None of these entries import
// the inherited Hermes main/preload or renderer root.
//
// Output:
//   dist/electron-main.mjs       ZN-owned Electron main process
//   dist/electron-preload.js     ZN-owned sandboxed preload bridge
//   dist/zn-shell-renderer.js    minimal ZN resident face
//   dist/zn-shell.html           minimal ZN resident document
import { build } from 'esbuild'
import { copyFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const distDir = resolve(root, 'dist')
mkdirSync(distDir, { recursive: true })

const mainEntry = resolve(root, 'electron/zn-main.ts')
const mainOut = resolve(distDir, 'electron-main.mjs')
const preloadEntry = resolve(root, 'electron/zn-preload.ts')
const preloadOut = resolve(distDir, 'electron-preload.js')
const shellRendererEntry = resolve(root, 'electron/zn-shell-renderer.ts')
const shellRendererOut = resolve(distDir, 'zn-shell-renderer.js')
const shellHtml = resolve(root, 'electron/zn-shell.html')
const shellHtmlOut = resolve(distDir, 'zn-shell.html')

const external = ['electron', 'node-pty', 'get-windows', 'fs']
const isDev = process.argv.includes('--dev')
const define = isDev
  ? {}
  : {
      'process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL': JSON.stringify(
        process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL || ''
      )
    }

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

await build({
  entryPoints: [preloadEntry],
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  outfile: preloadOut,
  external: ['electron'],
  define,
  logLevel: 'info'
})
console.log(`bundled ${preloadOut}${isDev ? ' (dev)' : ''}`)

await build({
  entryPoints: [shellRendererEntry],
  bundle: true,
  platform: 'browser',
  format: 'iife',
  target: 'chrome132',
  outfile: shellRendererOut,
  logLevel: 'info'
})
copyFileSync(shellHtml, shellHtmlOut)
console.log(`bundled ${shellRendererOut}`)
console.log(`copied ${shellHtmlOut}`)
