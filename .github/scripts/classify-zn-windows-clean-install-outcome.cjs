'use strict'

function latestStep(steps, conclusion) {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    if (steps[index]?.conclusion === conclusion) return steps[index]
  }
  return null
}

function description(value) {
  const text = String(value).replace(/\s+/g, ' ').trim()
  return text.length <= 140 ? text : `${text.slice(0, 137)}...`
}

function classifyCleanInstallOutcome(run, job) {
  const runConclusion = String(run?.conclusion || 'unknown')
  const jobConclusion = String(job?.conclusion || (job ? 'unknown' : 'missing'))
  const steps = Array.isArray(job?.steps) ? job.steps : []
  const timedOutStep = latestStep(steps, 'timed_out')
  const cancelledStep = latestStep(steps, 'cancelled')
  const failedStep = latestStep(steps, 'failure')

  if (runConclusion === 'success' && jobConclusion === 'success') {
    return { classification: 'success', state: 'success', description: 'isolated Windows x64 install/start proof: success' }
  }
  if (runConclusion === 'timed_out' || jobConclusion === 'timed_out' || timedOutStep) {
    return { classification: 'job-timeout', state: 'error', description: 'clean-install outcome: explicit workflow/job timeout' }
  }
  if (runConclusion === 'cancelled' || jobConclusion === 'cancelled') {
    return { classification: 'workflow-or-job-cancelled', state: 'error', description: 'clean-install outcome: workflow/job cancelled' }
  }
  if (cancelledStep) {
    return { classification: 'runner-or-job-interruption', state: 'error', description: 'clean-install outcome: runner/job interruption' }
  }
  if (!job) {
    return { classification: 'clean-install-job-missing', state: 'error', description: 'clean-install outcome: job missing/infrastructure failure' }
  }
  if (failedStep) {
    return { classification: 'step-failure', state: 'failure', description: description(`clean-install outcome: failed step ${failedStep.name || 'unknown'}`) }
  }
  if (runConclusion === 'failure' || jobConclusion === 'failure') {
    return { classification: 'runner-or-job-interruption', state: 'error', description: 'clean-install outcome: failure without a failed step' }
  }
  return {
    classification: `workflow-${runConclusion}-job-${jobConclusion}`,
    state: 'error',
    description: description(`clean-install outcome: workflow=${runConclusion} job=${jobConclusion}`)
  }
}

module.exports = { classifyCleanInstallOutcome }
