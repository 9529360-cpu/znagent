#!/usr/bin/env node
// Build the independent ZN Electron control plane and active renderer. None of
// these entries import a retired product main/preload or renderer root.
//
// Output:
//   dist/electron-main.mjs       ZN-owned Electron main process
//   dist/electron-preload.js     ZN-owned sandboxed preload bridge
//   dist/zn-shell-renderer.js    ZN workbench renderer
//   dist/zn-shell-renderer.css   ZN workbench styles
//   dist/zn-shell.html           ZN renderer document
import { build } from 'esbuild'
import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
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
const shellRendererEntry = resolve(root, 'src/zn/main.tsx')
const shellRendererOut = resolve(distDir, 'zn-shell-renderer.js')
const shellRendererCssOut = resolve(distDir, 'zn-shell-renderer.css')
const shellHtml = resolve(root, 'electron/zn-shell.html')
const shellHtmlOut = resolve(distDir, 'zn-shell.html')

const external = ['electron', 'node-pty', 'get-windows', 'fs']
const isDev = process.argv.includes('--dev')
const define = isDev
  ? {}
  : {
      'process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL': JSON.stringify(
        process.env.ZN_DESKTOP_UPDATE_CHANNEL_URL || ''
      ),
      'process.env.ZN_UPDATE_SIGNING_PUBLIC_KEYS': JSON.stringify(
        process.env.ZN_UPDATE_SIGNING_PUBLIC_KEYS || ''
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

// Generate the Tailwind utility layer for the vendored open-claude-ui
// components (whose classNames are the styling contract) plus the thin ZN
// wrappers. The vendored Tailwind config supplies the CDS theme; only the
// content globs are ZN-overridden in tailwind.config.cjs. The output is
// build output (gitignored) imported by src/zn/main.tsx alongside the
// vendored cds-theme.css tokens.
const tailwindInput = resolve(root, 'src/zn/cds-tailwind.css')
const tailwindOutput = resolve(root, 'src/zn/cds-tailwind.generated.css')
const tailwindConfig = resolve(root, 'tailwind.config.cjs')
const tailwindCliCandidates = [
  resolve(root, '../../node_modules/tailwindcss/lib/cli.js'),
  resolve(root, 'node_modules/tailwindcss/lib/cli.js')
]
const tailwindCli = tailwindCliCandidates.find(candidate => existsSync(candidate))
if (!tailwindCli) {
  throw new Error(
    'Tailwind CLI not found: run npm ci at the repository root before bundling the ZN desktop'
  )
}
execFileSync(
  process.execPath,
  [tailwindCli, '-i', tailwindInput, '-o', tailwindOutput, '--config', tailwindConfig],
  { stdio: 'inherit', cwd: root }
)
console.log(`generated ${tailwindOutput}`)

await build({
  entryPoints: [shellRendererEntry],
  bundle: true,
  platform: 'browser',
  format: 'iife',
  jsx: 'automatic',
  target: 'chrome132',
  outfile: shellRendererOut,
  logLevel: 'info',
  // The renderer bundle must contain exactly one React. Vendored files
  // resolve 'react' from the repository root while ZN files resolve it
  // from apps/desktop, so a second copy (e.g. React 18 hoisted for a
  // peer range) would otherwise slip into the same bundle and break
  // hooks at runtime (useContext dispatcher null). Root package.json
  // overrides pin React 19.2.7; this alias is the build-side guarantee.
  alias: (() => {
    const candidates = [
      resolve(root, '../../node_modules'),
      resolve(root, 'node_modules')
    ]
    const modules = candidates.find(dir => existsSync(resolve(dir, 'react/package.json')))
    if (!modules) throw new Error('React not found: run npm ci at the repository root before bundling the ZN desktop')
    return {
      react: resolve(modules, 'react'),
      'react-dom': resolve(modules, 'react-dom')
    }
  })()
})

if (!existsSync(shellRendererCssOut)) {
  throw new Error(`ZN renderer build did not emit stylesheet: ${shellRendererCssOut}`)
}

copyFileSync(shellHtml, shellHtmlOut)
console.log(`bundled ${shellRendererOut}`)
console.log(`bundled ${shellRendererCssOut}`)
console.log(`copied ${shellHtmlOut}`)
