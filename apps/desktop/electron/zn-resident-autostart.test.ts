import { describe, expect, it } from 'vitest'

import {
  ZN_RESIDENT_AUTOSTART_SCHEMA,
  znResidentAutostartMarkerName
} from './zn-resident-autostart'

describe('ZN resident autostart contract marker', () => {
  it('changes independently from desktop semver when the startup contract changes', () => {
    expect(ZN_RESIDENT_AUTOSTART_SCHEMA).toBe(2)
    expect(znResidentAutostartMarkerName('0.2.0')).toBe('zn-resident-autostart-v2-0.2.0.ok')
    expect(znResidentAutostartMarkerName('0.2.0')).not.toBe('zn-resident-autostart-0.2.0.ok')
  })
})
