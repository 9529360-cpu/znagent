import assert from 'node:assert/strict'

import { test } from 'vitest'

import { defaultZnResidentLaunch, isZnResidentLoopbackHost } from './zn-resident-process'

test('resident endpoint host accepts loopback aliases only', () => {
  for (const host of ['127.0.0.1', ' localhost ', '::1']) {
    assert.equal(isZnResidentLoopbackHost(host), true, host)
  }
  for (const host of ['', '0.0.0.0', '192.0.2.10', 'example.com', '::']) {
    assert.equal(isZnResidentLoopbackHost(host), false, host)
  }
})

test('default desktop launch uses the stable formal resident entrypoint', () => {
  const launch = defaultZnResidentLaunch({
    ZN_AGENT_HOME: '/tmp/zn-home',
    ZN_RESIDENT_PYTHON: '/tmp/python'
  })

  assert.deepEqual(launch.args, ['-m', 'zn_agent.resident'])
})
