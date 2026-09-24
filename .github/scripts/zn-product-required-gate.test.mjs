import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

import {
  PRODUCT_CONTRACT_WORKFLOWS,
  matchesPathFilters,
  pullRequestPaths,
  requiredProductContracts
} from './zn-product-required-gate.mjs'

test('parses pull_request paths without mixing push paths', () => {
  const source = `on:
  pull_request:
    branches:
      - main
    paths:
      - 'apps/desktop/**'
      - runtime/python/zn_agent/core/work.py
  push:
    branches:
      - main
    paths:
      - docs/**
`
  assert.deepEqual(pullRequestPaths(source), [
    'apps/desktop/**',
    'runtime/python/zn_agent/core/work.py'
  ])
})

test('matches GitHub-style positive and negative path filters in order', () => {
  assert.equal(matchesPathFilters('apps/desktop/electron/main.ts', ['apps/desktop/**']), true)
  assert.equal(matchesPathFilters('docs/readme.md', ['apps/desktop/**']), false)
  assert.equal(
    matchesPathFilters('apps/desktop/generated/a.ts', ['apps/desktop/**', '!apps/desktop/generated/**']),
    false
  )
})

test('current product contract workflows expose non-empty pull request path ownership', () => {
  const sources = Object.fromEntries(
    PRODUCT_CONTRACT_WORKFLOWS.map(workflowPath => [
      workflowPath,
      fs.readFileSync(path.resolve(workflowPath), 'utf8')
    ])
  )

  for (const workflowPath of PRODUCT_CONTRACT_WORKFLOWS) {
    assert.ok(pullRequestPaths(sources[workflowPath]).length > 0, workflowPath)
  }

  assert.deepEqual(
    requiredProductContracts(['apps/desktop/electron/main.ts'], sources),
    ['.github/workflows/zn-windows-clean-install.yml']
  )
  assert.ok(
    requiredProductContracts(['runtime/python/zn_agent/core/work.py'], sources)
      .includes('.github/workflows/zn-work-recovery-contract.yml')
  )
})
