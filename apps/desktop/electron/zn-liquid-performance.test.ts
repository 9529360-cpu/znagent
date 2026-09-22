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
  const liquid = read('src/zn/liquid-performance.css')

  const baseStyleIndex = entry.indexOf("import './styles.css'")
  const performanceIndex = entry.indexOf("import './liquid-performance.css'")
  assert.ok(baseStyleIndex >= 0)
  assert.ok(performanceIndex > baseStyleIndex)

  assert.match(liquid, /will-change:\s*transform/)
  assert.match(liquid, /backface-visibility:\s*hidden/)
  assert.match(liquid, /@media \(max-width: 720px\)/)
  assert.match(liquid, /@media \(max-width: 520px\)/)
  assert.match(liquid, /@media \(prefers-reduced-motion: reduce\)/)
  assert.match(liquid, /will-change:\s*auto/)
  assert.match(liquid, /@media \(forced-colors: active\)/)
  assert.match(liquid, /backdrop-filter:\s*none !important/)
  assert.match(liquid, /@media \(prefers-reduced-transparency: reduce\)/)

  assert.doesNotMatch(liquid, /\.zn-app\b/)
  assert.doesNotMatch(liquid, /grid-template-columns/)
  assert.doesNotMatch(liquid, /position:\s*(fixed|absolute)/)
})
