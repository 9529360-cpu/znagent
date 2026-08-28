import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))

function source(): string {
  return fs.readFileSync(path.join(here, 'zn-resident-autostart.ts'), 'utf8')
}

test('resident autostart marker versions the startup contract independently from desktop semver', () => {
  const text = source()

  assert.match(text, /ZN_RESIDENT_AUTOSTART_SCHEMA\s*=\s*2/)
  assert.match(text, /zn-resident-autostart-v\$\{ZN_RESIDENT_AUTOSTART_SCHEMA\}-\$\{desktopVersion\}\.ok/)
  assert.match(text, /znResidentAutostartMarkerName\(app\.getVersion\(\)\)/)
  assert.doesNotMatch(text, /`zn-resident-autostart-\$\{app\.getVersion\(\)\}\.ok`/)
})
