import assert from 'node:assert/strict'

import { test } from 'vitest'

import {
  describeZnProviderReadiness,
  providerUpdateNotice
} from '../src/zn/provider-readiness'
import type { ZnProviderSettings } from '../src/zn/resident-client'

function settings(overrides: Partial<ZnProviderSettings> = {}): ZnProviderSettings {
  return {
    mode: 'default',
    editable: true,
    provider: 'auto',
    model: '',
    baseUrl: '',
    credential: {
      configured: false,
      source: 'none',
      secureStore: {
        available: true,
        backend: 'test'
      }
    },
    cognitionAvailable: false,
    activeRoutes: [],
    ...overrides
  }
}

test('provider readiness treats missing settings as an in-progress check', () => {
  assert.deepEqual(describeZnProviderReadiness(null), {
    kind: 'checking',
    ready: false,
    headline: 'Checking model resources',
    detail: 'ZN is asking the resident for its current cognitive-resource state.'
  })
})

test('provider readiness does not turn an empty zero-model resident into success', () => {
  const readiness = describeZnProviderReadiness(settings())

  assert.equal(readiness.kind, 'not_configured')
  assert.equal(readiness.ready, false)
  assert.match(readiness.headline, /No external model configured/i)
})

test('provider readiness surfaces resident configuration errors', () => {
  const readiness = describeZnProviderReadiness(settings({
    provider: 'openai',
    model: 'gpt-test',
    configurationError: 'ValueError: route default has no credential for openai'
  }))

  assert.equal(readiness.kind, 'unavailable')
  assert.equal(readiness.ready, false)
  assert.match(readiness.detail, /no credential for openai/)
})

test('provider readiness uses the active resident route for ready state', () => {
  const readiness = describeZnProviderReadiness(settings({
    provider: 'openai',
    model: 'gpt-test',
    cognitionAvailable: true,
    activeRoutes: [{ id: 'default', provider: 'openai', model: 'gpt-test' }]
  }))

  assert.equal(readiness.kind, 'ready')
  assert.equal(readiness.ready, true)
  assert.equal(readiness.detail, 'openai · gpt-test')
})

test('provider update notice never claims readiness when resident cognition is unavailable', () => {
  const notice = providerUpdateNotice(settings({
    provider: 'openai',
    model: 'gpt-test',
    configurationError: 'missing credential'
  }))

  assert.match(notice, /not ready/i)
  assert.doesNotMatch(notice, /^Model ready\./)
})
