import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  ZN_RESIDENT_AUTOSTART_SCHEMA,
  znResidentAutostartMarkerName
} from './zn-resident-autostart'

test('resident autostart marker versions the launch contract independently from desktop semver', () => {
  assert.equal(ZN_RESIDENT_AUTOSTART_SCHEMA, 2)
  assert.equal(
    znResidentAutostartMarkerName('0.2.0'),
    'zn-resident-autostart-v2-0.2.0.ok'
  )
  assert.notEqual(
    znResidentAutostartMarkerName('0.2.0'),
    'zn-resident-autostart-0.2.0.ok'
  )
})
