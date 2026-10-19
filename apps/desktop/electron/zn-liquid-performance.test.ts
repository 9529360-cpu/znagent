import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('ambient material keeps visual polish while degrading for compact and accessibility contexts', () => {
  const entry = read('src/zn/main.tsx')
  const theme = fs.readFileSync(
    path.join(desktopRoot, '../../vendor/open-claude-ui/code-examples/cds-theme.css'),
    'utf8'
  )
  const compat = read('src/zn/zn-vendor-compat.css')
  const shellCss = read('src/zn/zn-claude-shell.css')

  // New shell style order: vendor tokens first, then the mechanical Tailwind
  // mapping, then the shell's own structural layout glue.
  const themeIndex = entry.indexOf('cds-theme.css')
  const compatIndex = entry.indexOf("import './zn-vendor-compat.css'")
  const shellIndex = entry.indexOf("import './zn-claude-shell.css'")
  assert.ok(themeIndex >= 0)
  assert.ok(compatIndex > themeIndex)
  assert.ok(shellIndex > compatIndex)

  // Vendor motion system: keyframes + status primitives, motion gated on
  // reduced-motion preference.
  assert.match(theme, /@keyframes timeline-quiet-dot/)
  assert.match(theme, /@keyframes message-fade-up/)
  assert.match(theme, /@keyframes cds-skeleton-sweep/)
  assert.match(theme, /@media \(prefers-reduced-motion: no-preference\)/)
  assert.match(theme, /\.status-dot\s*\{/)
  assert.match(theme, /\.cds-btn-squish\s*\{/)

  // Compat mapping only implements vendor classes; it invents no layout.
  assert.doesNotMatch(compat, /\.zn-shell\b/)
  assert.doesNotMatch(compat, /grid-template-columns/)

  // Shell layout glue stays structural: flex positioning only, no fixed /
  // absolute positioning, no invented visual design.
  assert.match(shellCss, /display:\s*flex/)
  assert.doesNotMatch(shellCss, /position:\s*(fixed|absolute)/)
  assert.doesNotMatch(shellCss, /\.zn-app\b/)
})
