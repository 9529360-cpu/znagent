import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(here, '..')
const externalDesktopName = Buffer.from('6865726d6573', 'hex').toString('utf8')

function read(relative: string): string {
  return fs.readFileSync(path.join(desktopRoot, relative), 'utf8')
}

test('provider onboarding remains ZN-owned instead of importing an external desktop', () => {
  const source = read('src/zn/provider-onboarding.tsx')
  const css = read('src/zn/provider-onboarding.css')
  const main = read('src/zn/main.tsx')

  assert.match(source, /ZnWorkbench/)
  assert.match(source, /loadZnProviderSettings/)
  assert.match(source, /updateZnProviderSettings/)
  assert.match(source, /zn-onboarding-shell/)
  assert.match(source, /Continue without model/)
  assert.match(main, /ZnProviderOnboarding/)

  assert.doesNotMatch(source, new RegExp(externalDesktopName, 'i'))
  assert.doesNotMatch(css, new RegExp(externalDesktopName, 'i'))
  assert.doesNotMatch(source, /onboarding-script|gateway|bootstrap-runner|src\/store/i)

  const classNames = [...css.matchAll(/\.([A-Za-z][A-Za-z0-9_-]*)/g)].map(match => match[1])
  assert.ok(classNames.length > 0)
  assert.ok(classNames.every(name => name.startsWith('zn-')))
})
