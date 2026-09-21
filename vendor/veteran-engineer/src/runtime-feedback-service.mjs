import { nowIso } from './util.mjs';

export const RUNTIME_FEEDBACK_CONTRACT = 'veteran-runtime-feedback-v1';

const MAX_OBSERVATION_ITEMS = 12;
const MAX_MISSION_TASKS = 64;

function boundedText(value, limit = 1000) {
  if (value === undefined || value === null) return null;
  return String(value).slice(0, limit);
}

function compactSessionObservation(session) {
  if (!session) return null;
  return {
    mode: boundedText(session.mode, 80),
    active: typeof session.active === 'boolean' ? session.active : null,
    reused: typeof session.reused === 'boolean' ? session.reused : null,
    restarted: typeof session.restarted === 'boolean' ? session.restarted : null,
    restartReason: boundedText(session.restartReason, 240),
    sourceChanged: typeof session.sourceChanged === 'boolean' ? session.sourceChanged : null,
    generation: Number.isInteger(session.generation) ? session.generation : null,
    released: typeof session.released === 'boolean' ? session.released : null,
    releaseReason: boundedText(session.releaseReason, 240),
    reason: boundedText(session.reason, 240),
    sourceCheck: session.sourceCheck ? {
      ok: session.sourceCheck.ok === true,
      reason: boundedText(session.sourceCheck.reason, 240)
    } : null
  };
}

function compactServiceObservation(service) {
  if (!service?.configured) return null;
  return {
    ready: service.ready === true,
    reason: service.readiness?.reason || null,
    lastStatus: service.readiness?.lastStatus ?? null,
    lastError: boundedText(service.readiness?.lastError, 500),
    session: compactSessionObservation(service.session)
  };
}

function compactBrowserObservation(browser) {
  if (!browser) return null;
  const failedAssertions = (browser.assertions || [])
    .filter((item) => item?.passed === false)
    .slice(0, MAX_OBSERVATION_ITEMS)
    .map((item) => ({
      name: boundedText(item.name, 240),
      detail: boundedText(item.detail, 800)
    }));
  return {
    kind: 'browser',
    summary: boundedText(browser.summary, 1200),
    currentUrl: boundedText(browser.currentUrl, 500),
    failureCode: browser.failureCode || null,
    failedAssertions
  };
}

function compactObservabilityObservation(observability) {
  if (!observability) return null;
  const failedChecks = (observability.checks || [])
    .filter((item) => item?.passed === false)
    .slice(0, MAX_OBSERVATION_ITEMS)
    .map((item) => ({
      name: boundedText(item.name, 240),
      signal: boundedText(item.signal, 120),
      observed: item.observed ?? null,
      threshold: item.threshold ?? null,
      detail: boundedText(item.detail, 800)
    }));
  return {
    kind: 'observability',
    summary: boundedText(observability.summary, 1200),
    failureCode: observability.failureCode || null,
    observedSourceHead: boundedText(observability.observedSourceHead, 240),
    failedChecks
  };
}

function compactArtifactObservation(artifacts) {
  if (!artifacts?.configured) return null;
  return {
    complete: artifacts.complete === true,
    requiredMissing: artifacts.requiredMissing === true,
    files: artifacts.files ?? null,
    errorCode: artifacts.error?.code || null
  };
}

function compactObservation(result) {
  const browser = compactBrowserObservation(result?.browser);
  const observability = compactObservabilityObservation(result?.observability);
  const service = compactServiceObservation(result?.service);
  const artifacts = compactArtifactObservation(result?.artifacts);
  if (browser) return { ...browser, service, artifacts };
  if (observability) return { ...observability, service, artifacts };
  if (service && service.ready === false) {
    return {
      kind: 'service-readiness',
      summary: 'Product service did not become ready for runtime feedback.',
      service,
      artifacts
    };
  }
  if (artifacts && artifacts.complete === false) {
    return {
      kind: 'artifact-collection',
      summary: 'Required runtime feedback artifacts were incomplete.',
      service,
      artifacts
    };
  }
  return {
    kind: 'command',
    summary: result?.passed === true
      ? 'Runtime feedback command passed.'
      : `Runtime feedback command failed${result?.exitCode === null || result?.exitCode === undefined ? '' : ` with exit code ${result.exitCode}`}.`,
    service,
    artifacts
  };
}

function compactCapabilityResult(capability, result) {
  return {
    capability,
    passed: result?.passed === true,
    evidenceId: result?.evidenceId || null,
    exitCode: result?.exitCode ?? null,
    failureStage: result?.failureStage || null,
    errorCode: null,
    observation: compactObservation(result)
  };
}

function compactCapabilityError(capability, error) {
  return {
    capability,
    passed: false,
    evidenceId: null,
    exitCode: null,
    failureStage: 'runtime-feedback',
    errorCode: error?.code || 'RUNTIME_FEEDBACK_CAPABILITY_FAILED',
    observation: {
      kind: 'provider-error',
      summary: boundedText(error?.message || error, 1000)
    }
  };
}

function uniqueCapabilityNames(project, waveTasks) {
  const names = [];
  const seen = new Set();
  for (const value of [
    ...(project.runtimeFeedbackCapabilities || []),
    ...waveTasks.map((task) => task.validationCapability).filter(Boolean)
  ]) {
    const name = String(value || '').trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    names.push(name);
  }
  return names;
}

function completedWaveTasks(mission, tasks, waveIndex) {
  const ids = mission.waves?.[waveIndex] || [];
  if (!ids.length) return { ready: false, reason: 'wave-not-found', tasks: [] };
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const waveTasks = ids.map((id) => byId.get(id)).filter(Boolean);
  if (waveTasks.length !== ids.length || waveTasks.some((task) => task.status !== 'done')) {
    return { ready: false, reason: 'wave-not-complete', tasks: waveTasks };
  }
  return { ready: true, reason: null, tasks: waveTasks };
}

function integratedCheckpointTasks(mission, tasks, waveIndex) {
  const ids = mission.waves?.[waveIndex] || [];
  if (!ids.length) return { ready: false, reason: 'wave-not-found', tasks: [], remaining: [] };
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const waveTasks = ids.map((id) => byId.get(id)).filter(Boolean);
  if (waveTasks.length !== ids.length) return { ready: false, reason: 'wave-task-missing', tasks: [], remaining: [] };
  const done = waveTasks.filter((task) => task.status === 'done' && task.integrationSha);
  const remaining = waveTasks.filter((task) => task.status !== 'done');
  if (!done.length) return { ready: false, reason: 'no-integrated-checkpoint', tasks: [], remaining };
  if (!remaining.length) return { ready: false, reason: 'wave-already-complete', tasks: done, remaining: [] };
  return { ready: true, reason: null, tasks: done, remaining };
}

function deriveWaveCommit(waveTasks) {
  const ordered = [...waveTasks].sort((a, b) => a.id.localeCompare(b.id));
  const integrationSha = ordered.at(-1)?.integrationSha || null;
  if (!integrationSha) {
    throw Object.assign(new Error('Completed wave is missing its integrated source identity'), {
      code: 'RUNTIME_FEEDBACK_SOURCE_IDENTITY_MISSING'
    });
  }
  return integrationSha;
}

function reusedRound(mission, waveIndex, commitSha, scope = 'wave') {
  return (mission.runtimeFeedback?.rounds || []).find((round) =>
    round.waveIndex === waveIndex
    && round.commitSha === commitSha
    && (round.scope || 'wave') === scope
  ) || null;
}

function repairRootTaskId(task) {
  return task.feedbackRemediation?.rootTaskId || task.id;
}

function repairAttemptsFor(tasks, rootTaskId) {
  return tasks.filter((task) => task.feedbackRemediation?.rootTaskId === rootTaskId).length;
}

function uniqueRepairTaskId(rootTaskId, attempt, tasks) {
  const existing = new Set(tasks.map((task) => task.id));
  const base = `${rootTaskId}-rf${attempt}`;
  if (!existing.has(base)) return base;
  let suffix = 2;
  while (existing.has(`${base}-${suffix}`)) suffix += 1;
  return `${base}-${suffix}`;
}

function repairPolicy(project) {
  const raw = project.runtimeFeedbackPolicy || {};
  return {
    autoRepair: raw.autoRepair === true,
    maxRepairAttempts: Number.isInteger(raw.maxRepairAttempts)
      ? Math.max(0, Math.min(3, raw.maxRepairAttempts))
      : 1
  };
}

export class RuntimeFeedbackService {
  constructor({ store, projectService, missionService, validationService, evidenceService }) {
    Object.assign(this, { store, projectService, missionService, validationService, evidenceService });
  }

  async runAfterWave({ missionId, waveIndex, targetCommitSha = null }) {
    if (!Number.isInteger(waveIndex) || waveIndex < 0) {
      throw Object.assign(new Error('runtime feedback waveIndex must be a non-negative integer'), { code: 'RUNTIME_FEEDBACK_WAVE_INVALID' });
    }
    const { mission, tasks } = await this.missionService.status({ missionId });
    const wave = completedWaveTasks(mission, tasks, waveIndex);
    if (!wave.ready) {
      return {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        configured: true,
        recorded: false,
        reason: wave.reason,
        missionId,
        waveIndex
      };
    }
    const project = await this.projectService.get(mission.projectId);
    const capabilities = uniqueCapabilityNames(project, wave.tasks);
    if (!capabilities.length) {
      return {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        configured: false,
        recorded: false,
        reason: 'no-runtime-feedback-capabilities',
        missionId,
        waveIndex
      };
    }
    const commitSha = targetCommitSha ? String(targetCommitSha).trim() : deriveWaveCommit(wave.tasks);
    if (!commitSha) {
      throw Object.assign(new Error('runtime feedback requires an exact integrated source identity'), { code: 'RUNTIME_FEEDBACK_SOURCE_IDENTITY_MISSING' });
    }
    const existing = reusedRound(mission, waveIndex, commitSha, 'wave');
    if (existing) return { contract: RUNTIME_FEEDBACK_CONTRACT, configured: true, recorded: true, reused: true, ...existing };

    const results = [];
    for (const capability of capabilities) {
      try {
        const result = await this.validationService.run({
          projectId: project.id,
          missionId,
          capability,
          purpose: 'runtime-feedback',
          targetCommitSha: commitSha
        });
        results.push(compactCapabilityResult(capability, result));
      } catch (error) {
        results.push(compactCapabilityError(capability, error));
      }
    }
    const passed = results.every((item) => item.passed);
    const createdAt = nowIso();
    const summary = {
      contract: RUNTIME_FEEDBACK_CONTRACT,
      missionId,
      waveIndex,
      commitSha,
      passed,
      capabilities: results
    };
    const aggregateEvidence = await this.evidenceService.record({
      projectId: project.id,
      missionId,
      type: 'runtime-feedback-round',
      summary,
      sourceIdentity: { head: commitSha }
    });
    const round = { ...summary, aggregateEvidenceId: aggregateEvidence.id, createdAt };

    return this.store.transaction('mission_runtime_feedback_recorded', (state) => {
      const target = state.missions[missionId];
      if (!target) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      target.runtimeFeedback ||= {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        status: 'pending',
        latestRound: null,
        rounds: []
      };
      const duplicate = reusedRound(target, waveIndex, commitSha, 'wave');
      if (duplicate) return { contract: RUNTIME_FEEDBACK_CONTRACT, configured: true, recorded: true, reused: true, ...duplicate };
      target.runtimeFeedback.status = passed ? 'passed' : 'failed';
      target.runtimeFeedback.latestRound = round;
      target.runtimeFeedback.rounds.push(round);
      if (target.runtimeFeedback.rounds.length > 65) target.runtimeFeedback.rounds = target.runtimeFeedback.rounds.slice(-65);
      target.updatedAt = nowIso();
      state.runtime.timeline.push({
        type: 'mission_runtime_feedback_recorded',
        missionId,
        waveIndex,
        commitSha,
        passed,
        evidenceId: aggregateEvidence.id,
        at: createdAt
      });
      return { contract: RUNTIME_FEEDBACK_CONTRACT, configured: true, recorded: true, reused: false, ...round };
    }, { missionId, waveIndex, commitSha, passed, evidenceId: aggregateEvidence.id });
  }

  async runCheckpoint({ missionId, waveIndex, targetCommitSha, triggerTaskId = null }) {
    if (!Number.isInteger(waveIndex) || waveIndex < 0) {
      throw Object.assign(new Error('runtime feedback checkpoint waveIndex must be a non-negative integer'), { code: 'RUNTIME_FEEDBACK_WAVE_INVALID' });
    }
    const { mission, tasks } = await this.missionService.status({ missionId });
    if (mission.phase !== 'execution' || mission.nextWaveIndex !== waveIndex) {
      return {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        configured: true,
        recorded: false,
        reason: 'checkpoint-wave-not-current',
        missionId,
        waveIndex
      };
    }
    const wave = integratedCheckpointTasks(mission, tasks, waveIndex);
    if (!wave.ready) {
      return {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        configured: true,
        recorded: false,
        reason: wave.reason,
        missionId,
        waveIndex
      };
    }
    const commitSha = String(targetCommitSha || '').trim();
    const allowed = new Set(wave.tasks.map((task) => task.integrationSha).filter(Boolean));
    if (!commitSha || !allowed.has(commitSha)) {
      throw Object.assign(new Error('runtime feedback checkpoint must target a completed task integration in the current wave'), {
        code: 'RUNTIME_FEEDBACK_CHECKPOINT_SOURCE_INVALID'
      });
    }
    const project = await this.projectService.get(mission.projectId);
    const capabilities = uniqueCapabilityNames(project, wave.tasks);
    if (!capabilities.length) {
      return {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        configured: false,
        recorded: false,
        reason: 'no-runtime-feedback-capabilities',
        missionId,
        waveIndex,
        scope: 'checkpoint'
      };
    }
    const existing = reusedRound(mission, waveIndex, commitSha, 'checkpoint');
    if (existing) return { contract: RUNTIME_FEEDBACK_CONTRACT, configured: true, recorded: true, reused: true, ...existing };

    const results = [];
    for (const capability of capabilities) {
      try {
        const result = await this.validationService.run({
          projectId: project.id,
          missionId,
          capability,
          purpose: 'runtime-feedback',
          targetCommitSha: commitSha
        });
        results.push(compactCapabilityResult(capability, result));
      } catch (error) {
        results.push(compactCapabilityError(capability, error));
      }
    }
    const passed = results.every((item) => item.passed);
    const createdAt = nowIso();
    const summary = {
      contract: RUNTIME_FEEDBACK_CONTRACT,
      scope: 'checkpoint',
      completeWave: false,
      advisory: true,
      missionId,
      waveIndex,
      triggerTaskId: triggerTaskId ? String(triggerTaskId).slice(0, 240) : null,
      commitSha,
      passed,
      capabilities: results
    };
    const aggregateEvidence = await this.evidenceService.record({
      projectId: project.id,
      missionId,
      type: 'runtime-feedback-checkpoint',
      summary,
      sourceIdentity: { head: commitSha }
    });
    const round = { ...summary, aggregateEvidenceId: aggregateEvidence.id, createdAt };

    return this.store.transaction('mission_runtime_feedback_checkpoint_recorded', (state) => {
      const target = state.missions[missionId];
      if (!target) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      if (target.phase !== 'execution' || target.nextWaveIndex !== waveIndex) {
        return {
          contract: RUNTIME_FEEDBACK_CONTRACT,
          configured: true,
          recorded: false,
          reason: 'checkpoint-stale-after-observation',
          missionId,
          waveIndex,
          scope: 'checkpoint'
        };
      }
      target.runtimeFeedback ||= {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        status: 'pending',
        latestRound: null,
        rounds: []
      };
      const duplicate = reusedRound(target, waveIndex, commitSha, 'checkpoint');
      if (duplicate) return { contract: RUNTIME_FEEDBACK_CONTRACT, configured: true, recorded: true, reused: true, ...duplicate };
      target.runtimeFeedback.latestRound = round;
      target.runtimeFeedback.rounds.push(round);
      if (target.runtimeFeedback.rounds.length > 65) target.runtimeFeedback.rounds = target.runtimeFeedback.rounds.slice(-65);
      target.updatedAt = nowIso();
      state.runtime.timeline.push({
        type: 'mission_runtime_feedback_checkpoint_recorded',
        missionId,
        waveIndex,
        triggerTaskId: round.triggerTaskId,
        commitSha,
        passed,
        evidenceId: aggregateEvidence.id,
        at: createdAt
      });
      return { contract: RUNTIME_FEEDBACK_CONTRACT, configured: true, recorded: true, reused: false, ...round };
    }, { missionId, waveIndex, triggerTaskId: round.triggerTaskId, commitSha, passed, evidenceId: aggregateEvidence.id });
  }

  async scheduleRepairWave({ missionId, feedbackRound }) {
    const { mission, tasks } = await this.missionService.status({ missionId });
    const project = await this.projectService.get(mission.projectId);
    const policy = repairPolicy(project);
    if (!policy.autoRepair) {
      return { configured: false, scheduled: false, reason: 'auto-repair-disabled', maxRepairAttempts: policy.maxRepairAttempts };
    }
    if (feedbackRound?.scope === 'checkpoint') {
      return { configured: true, scheduled: false, reason: 'checkpoint-feedback-is-advisory', maxRepairAttempts: policy.maxRepairAttempts };
    }
    if (!feedbackRound?.recorded || feedbackRound.passed !== false) {
      return { configured: true, scheduled: false, reason: 'feedback-does-not-require-repair', maxRepairAttempts: policy.maxRepairAttempts };
    }
    if (mission.phase !== 'execution') {
      return { configured: true, scheduled: false, reason: 'mission-not-in-execution', maxRepairAttempts: policy.maxRepairAttempts };
    }
    const latest = mission.runtimeFeedback?.latestRound || null;
    if (!latest || latest.commitSha !== feedbackRound.commitSha || latest.waveIndex !== feedbackRound.waveIndex) {
      return { configured: true, scheduled: false, reason: 'feedback-not-current', maxRepairAttempts: policy.maxRepairAttempts };
    }
    const priorRepair = (mission.runtimeFeedback?.repairWaves || []).find((item) => item.feedbackEvidenceId === feedbackRound.aggregateEvidenceId);
    if (priorRepair) return { configured: true, scheduled: true, reused: true, maxRepairAttempts: policy.maxRepairAttempts, ...priorRepair };

    const nextWaveIds = mission.waves?.[mission.nextWaveIndex] || [];
    const byId = new Map(tasks.map((task) => [task.id, task]));
    if (nextWaveIds.some((id) => byId.get(id)?.status !== 'planned')) {
      return { configured: true, scheduled: false, reason: 'next-wave-already-active', maxRepairAttempts: policy.maxRepairAttempts };
    }

    const sourceWave = completedWaveTasks(mission, tasks, feedbackRound.waveIndex);
    if (!sourceWave.ready) {
      return { configured: true, scheduled: false, reason: sourceWave.reason, maxRepairAttempts: policy.maxRepairAttempts };
    }
    const failedCapabilities = new Set((feedbackRound.capabilities || []).filter((item) => item?.passed === false).map((item) => item.capability));
    const owned = sourceWave.tasks.filter((task) => task.validationCapability && failedCapabilities.has(task.validationCapability));
    if (!owned.length) {
      return { configured: true, scheduled: false, reason: 'no-owned-failed-capability', maxRepairAttempts: policy.maxRepairAttempts };
    }

    const createdAt = nowIso();
    const repairTasks = [];
    const exhausted = [];
    for (const sourceTask of owned) {
      const rootTaskId = repairRootTaskId(sourceTask);
      const used = repairAttemptsFor(tasks, rootTaskId);
      if (used >= policy.maxRepairAttempts) {
        exhausted.push({ rootTaskId, sourceTaskId: sourceTask.id, attempts: used });
        continue;
      }
      const attempt = used + 1;
      const id = uniqueRepairTaskId(rootTaskId, attempt, [...tasks, ...repairTasks]);
      repairTasks.push({
        id,
        key: `${missionId}:${id}`,
        missionId,
        projectId: project.id,
        contract: `Repair runtime feedback failure for ${sourceTask.validationCapability} while preserving the original task contract: ${sourceTask.contract}`,
        owner: sourceTask.owner,
        dependencies: [sourceTask.id],
        writeSet: [...(sourceTask.writeSet || [])],
        protectedPaths: [...(sourceTask.protectedPaths || [])],
        risk: sourceTask.risk,
        validationCapability: sourceTask.validationCapability,
        worker: sourceTask.worker || 'default',
        notes: `Auto-repair attempt ${attempt} from runtime feedback ${feedbackRound.aggregateEvidenceId || 'unknown'}.`,
        feedbackRemediation: {
          rootTaskId,
          sourceTaskId: sourceTask.id,
          attempt,
          feedbackWaveIndex: feedbackRound.waveIndex,
          feedbackCommitSha: feedbackRound.commitSha,
          feedbackEvidenceId: feedbackRound.aggregateEvidenceId || null,
          capability: sourceTask.validationCapability
        },
        status: 'planned',
        attempts: 0,
        dispatches: [],
        commitSha: null,
        integrationSha: null,
        evidenceIds: [],
        createdAt,
        updatedAt: createdAt
      });
    }
    if (!repairTasks.length) {
      return {
        configured: true,
        scheduled: false,
        reason: exhausted.length ? 'repair-attempts-exhausted' : 'no-repairable-tasks',
        maxRepairAttempts: policy.maxRepairAttempts,
        exhausted
      };
    }
    if (tasks.length + repairTasks.length > MAX_MISSION_TASKS) {
      return {
        configured: true,
        scheduled: false,
        reason: 'mission-task-limit-reached',
        maxRepairAttempts: policy.maxRepairAttempts,
        taskCount: tasks.length,
        requestedRepairTasks: repairTasks.length,
        exhausted
      };
    }

    return this.store.transaction('mission_runtime_feedback_repair_scheduled', (state) => {
      const target = state.missions[missionId];
      if (!target) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      const currentLatest = target.runtimeFeedback?.latestRound || null;
      if (target.phase !== 'execution' || !currentLatest || currentLatest.commitSha !== feedbackRound.commitSha || currentLatest.waveIndex !== feedbackRound.waveIndex) {
        return { configured: true, scheduled: false, reason: 'feedback-not-current', maxRepairAttempts: policy.maxRepairAttempts };
      }
      target.runtimeFeedback.repairWaves ||= [];
      const duplicate = target.runtimeFeedback.repairWaves.find((item) => item.feedbackEvidenceId === feedbackRound.aggregateEvidenceId);
      if (duplicate) return { configured: true, scheduled: true, reused: true, maxRepairAttempts: policy.maxRepairAttempts, ...duplicate };
      const currentNextIds = target.waves?.[target.nextWaveIndex] || [];
      if (currentNextIds.some((id) => state.tasks[`${missionId}:${id}`]?.status !== 'planned')) {
        return { configured: true, scheduled: false, reason: 'next-wave-already-active', maxRepairAttempts: policy.maxRepairAttempts };
      }
      const currentTaskCount = Object.values(state.tasks).filter((task) => task.missionId === missionId).length;
      if (currentTaskCount + repairTasks.length > MAX_MISSION_TASKS) {
        return {
          configured: true,
          scheduled: false,
          reason: 'mission-task-limit-reached',
          maxRepairAttempts: policy.maxRepairAttempts,
          taskCount: currentTaskCount,
          requestedRepairTasks: repairTasks.length
        };
      }
      for (const task of repairTasks) {
        if (state.tasks[task.key]) throw Object.assign(new Error(`Repair task already exists: ${task.id}`), { code: 'RUNTIME_FEEDBACK_REPAIR_TASK_CONFLICT' });
      }
      const waveIndex = target.nextWaveIndex;
      const taskIds = repairTasks.map((task) => task.id);
      target.waves.splice(waveIndex, 0, taskIds);
      for (const task of repairTasks) state.tasks[task.key] = task;
      const record = {
        feedbackEvidenceId: feedbackRound.aggregateEvidenceId || null,
        feedbackCommitSha: feedbackRound.commitSha,
        sourceWaveIndex: feedbackRound.waveIndex,
        waveIndex,
        taskIds,
        createdAt
      };
      target.runtimeFeedback.repairWaves.push(record);
      target.status = 'ready';
      target.updatedAt = nowIso();
      state.runtime.timeline.push({
        type: 'mission_runtime_feedback_repair_scheduled',
        missionId,
        feedbackEvidenceId: feedbackRound.aggregateEvidenceId || null,
        waveIndex,
        taskIds,
        at: createdAt
      });
      return {
        configured: true,
        scheduled: true,
        reused: false,
        maxRepairAttempts: policy.maxRepairAttempts,
        exhausted,
        ...record
      };
    }, { missionId, feedbackEvidenceId: feedbackRound.aggregateEvidenceId || null, repairTaskIds: repairTasks.map((task) => task.id) });
  }

  async runAfterWaveSafe(args) {
    try {
      return await this.runAfterWave(args);
    } catch (error) {
      return {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        configured: true,
        recorded: false,
        reason: 'runtime-feedback-unavailable',
        missionId: args?.missionId || null,
        waveIndex: Number.isInteger(args?.waveIndex) ? args.waveIndex : null,
        error: {
          code: error?.code || 'RUNTIME_FEEDBACK_UNAVAILABLE',
          message: String(error?.message || error).slice(0, 500)
        }
      };
    }
  }

  async runCheckpointSafe(args) {
    try {
      return await this.runCheckpoint(args);
    } catch (error) {
      return {
        contract: RUNTIME_FEEDBACK_CONTRACT,
        configured: true,
        recorded: false,
        reason: 'runtime-feedback-checkpoint-unavailable',
        scope: 'checkpoint',
        missionId: args?.missionId || null,
        waveIndex: Number.isInteger(args?.waveIndex) ? args.waveIndex : null,
        error: {
          code: error?.code || 'RUNTIME_FEEDBACK_CHECKPOINT_UNAVAILABLE',
          message: String(error?.message || error).slice(0, 500)
        }
      };
    }
  }

  async scheduleRepairWaveSafe(args) {
    try {
      return await this.scheduleRepairWave(args);
    } catch (error) {
      return {
        configured: true,
        scheduled: false,
        reason: 'auto-repair-unavailable',
        error: {
          code: error?.code || 'RUNTIME_FEEDBACK_REPAIR_UNAVAILABLE',
          message: String(error?.message || error).slice(0, 500)
        }
      };
    }
  }
}
