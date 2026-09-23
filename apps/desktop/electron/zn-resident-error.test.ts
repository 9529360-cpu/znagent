import assert from 'node:assert/strict'
import { test } from 'vitest'

import { isZnResidentConnectionError } from '../src/zn/resident-error'

test('recognizes a missing Resident endpoint as a connection failure', () => {
  assert.equal(
    isZnResidentConnectionError(new Error("Error invoking remote method 'zn:resident:work-start': ENOENT opening resident-endpoint.json")),
    true
  )
})

test('does not classify ordinary task failures as a connection failure', () => {
  assert.equal(isZnResidentConnectionError(new Error('The requested file could not be found')), false)
})
