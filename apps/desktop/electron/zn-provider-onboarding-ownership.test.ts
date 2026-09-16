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

test('provider onboarding reuses ZN desktop composition instead of importing an external desktop', () => {
  const source = read('src/zn/provider-onboarding.tsx')
  const main = read('src/zn/main.tsx')
  const styles = read('src/zn/styles.css')

  assert.match(source, /ZnWorkbench/)
  assert.match(source, /loadZnProviderSettings/)
  assert.match(source, /updateZnProviderSettings/)
  assert.match(source, /className="zn-settings"/)
  assert.match(source, /zn-page-intro/)
  assert.match(source, /zn-settings-grid/)
  assert.match(source, /zn-card/)
  assert.match(source, /zn-search/)
  assert.match(source, /Continue without model/)
  assert.match(main, /ZnProviderOnboarding/)
  assert.match(styles, /\.zn-settings\s*\{/)
  assert.match(styles, /\.zn-card\s*\{/)

  assert.doesNotMatch(source, /provider-onboarding\.css/)
  assert.doesNotMatch(source, new RegExp(externalDesktopName, 'i'))
  assert.doesNotMatch(source, /onboarding-script|gateway|bootstrap-runner|src\/store/i)
})
