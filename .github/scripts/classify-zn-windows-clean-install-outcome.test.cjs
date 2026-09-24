'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')
const { classifyCleanInstallOutcome } = require('./classify-zn-windows-clean-install-outcome.cjs')

function job(conclusion, steps = []) {
  return { name: 'Windows x64 clean install and start', conclusion, steps }
}

test('classifies successful clean install', () => {
  assert.deepEqual(classifyCleanInstallOutcome({ conclusion: 'success' }, job('success')), {
    classification: 'success', state: 'success', description: 'isolated Windows x64 install/start proof: success'
  })
})

test('separates explicit timeout from ordinary failure', () => {
  assert.equal(classifyCleanInstallOutcome({ conclusion: 'timed_out' }, job('timed_out')).classification, 'job-timeout')
})

test('separates workflow or job cancellation from product failure', () => {
  const outcome = classifyCleanInstallOutcome({ conclusion: 'cancelled' }, job('cancelled'))
  assert.equal(outcome.classification, 'workflow-or-job-cancelled')
  assert.equal(outcome.state, 'error')
})

test('treats a cancelled step inside a failed run as infrastructure interruption', () => {
  const outcome = classifyCleanInstallOutcome({ conclusion: 'failure' }, job('failure', [
    { name: 'Build unsigned Windows installer candidates from short path', conclusion: 'cancelled' }
  ]))
  assert.equal(outcome.classification, 'runner-or-job-interruption')
  assert.equal(outcome.state, 'error')
})

test('keeps an explicit failed step as a normal workflow failure', () => {
  const outcome = classifyCleanInstallOutcome({ conclusion: 'failure' }, job('failure', [
    { name: 'Build unsigned Windows installer candidates from short path', conclusion: 'failure' }
  ]))
  assert.equal(outcome.classification, 'step-failure')
  assert.equal(outcome.state, 'failure')
  assert.match(outcome.description, /Build unsigned Windows installer candidates/)
})

test('classifies missing job as infrastructure evidence', () => {
  assert.equal(classifyCleanInstallOutcome({ conclusion: 'failure' }, null).classification, 'clean-install-job-missing')
})

test('classifies failure without a failed step as interruption evidence', () => {
  assert.equal(classifyCleanInstallOutcome({ conclusion: 'failure' }, job('failure')).classification, 'runner-or-job-interruption')
})

test('secondary status failure does not mask a cancelled build step', () => {
  const outcome = classifyCleanInstallOutcome({ conclusion: 'failure' }, job('failure', [
    { name: 'Build unsigned Windows installer candidates from short path', conclusion: 'cancelled' },
    { name: 'Publish clean-install status', conclusion: 'failure' }
  ]))
  assert.equal(outcome.classification, 'runner-or-job-interruption')
  assert.equal(outcome.state, 'error')
})
