import path from 'node:path';
import {
  assertPathsWithinScope,
  changedPaths,
  git,
  repositorySourceAuthority,
  sameSourceAuthorityLineage,
  sourceIdentity,
  sourceIdentityFromAuthority
} from './git.mjs';
import { MissionService } from './mission-service.mjs';
import { missionExecutionCapacity } from './adaptive-mission-strategy.mjs';
import { nowIso, randomId } from './util.mjs';
import { resolveWorkerConfig, writeWorkerPacket } from './worker-adapter.mjs';
import { ProjectBootstrapExecutor, normalizeBootstrapAuthorization } from './bootstrap-executor.mjs';

function runtimeFeedbackForPacket(mission, waveBase) {
  const latest = mission.runtimeFeedback?.latestRound || null;
  if (!latest) return null;
  const sourceBound = latest.commitSha === waveBase;
  const scope = latest.scope === 'checkpoint' ? 'checkpoint' : 'wave';
  return {
    contract: mission.runtimeFeedback?.contract || 'veteran-runtime-feedback-v1',
    sourceBound,
    sourceHead: latest.commitSha || null,
    waveBase,
    observedWaveIndex: Number.isInteger(latest.waveIndex) ? latest.waveIndex : null,
    scope,
    completeWave: scope === 'wave',
    triggerTaskId: sourceBound && scope === 'checkpoint' ? (latest.triggerTaskId || null) : null,
    passed: sourceBound ? latest.passed === true : null,
    aggregateEvidenceId: latest.aggregateEvidenceId || null,
    capabilities: sourceBound ? (latest.capabilities || []) : [],
    reason: sourceBound ? null : 'feedback-source-does-not-match-wave-base',
    advisory: true,
    instructions: [
      ...(scope === 'checkpoint'
        ? ['Checkpoint feedback covers a stable partial-wave integration only; do not treat it as complete-wave validation or repair authority.']
        : []),
      'Treat source-bound failures as current product evidence and adapt within the current task contract and writeSet.',
      'If feedback points outside the current task authority, report it as an unresolved risk instead of broadening scope.'
    ]
  };
}

function packetFor(project, mission, task, waveBase, experience = { items: [], precedence: 'Current repository/runtime evidence outranks project experience.' }) {
  return {
    protocol: 'veteran-worker-v1',
    project: { id: project.id, repoPath: project.repoPath, sourceAuthority: mission.baseSourceAuthority || project.sourceAuthority || null },
    mission: {
      id: mission.id,
      goal: mission.goal,
      doneDefinition: mission.doneDefinition,
      baseHead: mission.baseSourceIdentity.head,
      sourceAuthority: mission.baseSourceAuthority || null,
      projectTruth: mission.projectTruth || null
    },
    task: {
      id: task.id,
      contract: task.contract,
      owner: task.owner,
      dependencies: task.dependencies,
      writeSet: task.writeSet,
      protectedPaths: task.protectedPaths,
      risk: task.risk,
      validationCapability: task.validationCapability
    },
    waveBase,
    runtimeFeedback: runtimeFeedbackForPacket(mission, waveBase),
    runtimeFeedbackPrecedence: 'Source-bound runtime feedback is current product evidence and outranks project experience, but it never expands task authority or write scope.',
    projectExperience: experience.items || [],
    experiencePrecedence: experience.precedence || 'Current repository/runtime evidence outranks project experience.',
    implementationPolicy: [
      'Prefer the smallest complete change in the existing authoritative owner; extend an existing owner before creating a parallel one when it can safely absorb the behavior.',
      'Do not add a service, state machine, store, adapter, wrapper layer, generic abstraction, extension point, or dependency unless repository evidence shows a distinct responsibility, lifecycle, or repeated semantic contract that earns it.',
      'Keep control flow, state, naming, and data movement direct and boring; do not hide product policy behind generic plumbing or duplicate the same fact across layers.',
      'After correctness is proven, run a compression pass: remove obsolete branches, redundant helpers, accidental indirection, duplicate tests, and temporary compatibility that no longer has a live consumer.',
      'Do not simplify away real correctness boundaries for authorization, concurrency, durability, failure recovery, observability, compatibility, or cleanup.',
      'Tests should protect behavior or machine-checkable invariants, not merely freeze prose, field presence, or current implementation shape.'
    ],
    returnContract: ['files changed', 'behavior changed', 'tests/evidence', 'unresolved risks', 'discoveries that invalidate plan'],
    stopConditions: ['write outside declared scope', 'mission-level semantic ambiguity', 'release/production action required', 'security-policy change required']
  };
}

function reconcileInterruptedMission(state, mission) {
  const interrupted = Object.values(state.tasks)
    .filter((task) => task.missionId === mission.id && task.status === 'interrupted')
    .sort((left, right) => left.id.localeCompare(right.id));
  if (interrupted.length) {
    mission.status = 'blocked';
    mission.interruption = {
      requiresReconciliation: true,
      taskIds: interrupted.map((task) => task.id),
      detectedAt: mission.interruption?.detectedAt || nowIso()
    };
    mission.updatedAt = nowIso();
    return interrupted;
  }
  if (mission.interruption?.requiresReconciliation) {
    mission.interruption = null;
    if (mission.status === 'blocked') mission.status = 'ready';
    mission.updatedAt = nowIso();
  }
  return interrupted;
}

export class WorkerOrchestrator {
  constructor({ store, projectService, missionService, worktreeManager, workerAdapter, evidenceService, experienceService = null, bootstrapExecutor = null }) {
    this.store = store;
    this.projectService = projectService;
    this.missionService = missionService;
    this.worktreeManager = worktreeManager;
    this.workerAdapter = workerAdapter;
    this.evidenceService = evidenceService;
    this.experienceService = experienceService;
    this.bootstrapExecutor = bootstrapExecutor || new ProjectBootstrapExecutor();
  }

  async execute({ missionId, runWorkers = false, bootstrapAuthorization = null }) {
    const normalizedBootstrapAuthorization = normalizeBootstrapAuthorization(bootstrapAuthorization);
    if (normalizedBootstrapAuthorization && !runWorkers) {
      throw Object.assign(new Error('Bootstrap execution is only supported when mission_execute runs workers'), { code: 'BOOTSTRAP_EXECUTION_REQUIRES_RUN_WORKERS' });
    }
    const { mission, tasks } = await this.missionService.status({ missionId });
    if (mission.status === 'cancelled') throw Object.assign(new Error('Mission is cancelled'), { code: 'MISSION_CANCELLED' });
    if (mission.phase !== 'execution') return { missionId, phase: mission.phase, message: 'Execution phase already complete' };
    let project = await this.projectService.get(mission.projectId);
    if (mission.projectTruth?.sourceIdentity?.head && mission.projectTruth.sourceIdentity.head !== mission.baseSourceIdentity.head) {
      throw Object.assign(new Error('Mission project truth no longer matches its frozen source base'), {
        code: 'MISSION_PROJECT_TRUTH_CORRUPT',
        details: {
          projectTruthSourceHead: mission.projectTruth.sourceIdentity.head,
          missionBaseHead: mission.baseSourceIdentity.head
        }
      });
    }
    const frozenBootstrapPlan = mission.projectTruth?.bootstrapPlan || project.bootstrapPlan;
    const observed = await sourceIdentity(project.repoPath);
    const currentAuthority = mission.baseSourceAuthority
      ? await repositorySourceAuthority(project.repoPath, { observedIdentity: observed })
      : null;
    const authoritativeSource = currentAuthority ? sourceIdentityFromAuthority(currentAuthority) : observed;
    const checkoutIsAuthority = !mission.baseSourceAuthority || mission.baseSourceAuthority.scope === 'checkout';
    if (checkoutIsAuthority && observed.dirty) {
      throw Object.assign(new Error('Dirty source checkout blocks first dispatch/execution'), { code: 'DIRTY_SOURCE_BLOCKED', details: observed.dirtyPaths });
    }
    if (mission.baseSourceAuthority && !sameSourceAuthorityLineage(mission.baseSourceAuthority, currentAuthority)) {
      throw Object.assign(new Error('Repository source authority changed after the mission was planned'), {
        code: 'SOURCE_AUTHORITY_CHANGED',
        details: {
          expected: {
            scope: mission.baseSourceAuthority.scope,
            remote: mission.baseSourceAuthority.remote || null,
            ref: mission.baseSourceAuthority.ref || null
          },
          actual: {
            scope: currentAuthority?.scope || null,
            remote: currentAuthority?.remote || null,
            ref: currentAuthority?.ref || null
          }
        }
      });
    }
    if (mission.nextWaveIndex === 0 && authoritativeSource.head !== mission.baseSourceIdentity.head) {
      throw Object.assign(new Error('Mission base is stale before first dispatch'), {
        code: 'MISSION_BASE_STALE',
        details: {
          planned: mission.baseSourceIdentity.head,
          live: authoritativeSource.head,
          observedCheckoutHead: observed.head,
          authorityRef: currentAuthority?.ref || 'HEAD'
        }
      });
    }
    if (normalizedBootstrapAuthorization) {
      if (observed.dirty || observed.head !== mission.baseSourceIdentity.head) {
        throw Object.assign(new Error('Bootstrap requires the project checkout to be clean and aligned with the frozen mission source authority'), {
          code: 'BOOTSTRAP_SOURCE_AUTHORITY_CHECKOUT_MISMATCH',
          details: {
            missionBaseHead: mission.baseSourceIdentity.head,
            checkoutHead: observed.head,
            dirty: observed.dirty,
            authorityRef: mission.baseSourceAuthority?.ref || 'HEAD'
          }
        });
      }
      project = await this.projectService.snapshot({ projectId: project.id });
      if (project.sourceIdentity.dirty || project.sourceIdentity.head !== observed.head) {
        throw Object.assign(new Error('Project environment snapshot changed source identity before bootstrap execution'), { code: 'BOOTSTRAP_SOURCE_IDENTITY_STALE', details: { expectedHead: observed.head, actualHead: project.sourceIdentity.head, dirty: project.sourceIdentity.dirty } });
      }
    }
    const waveIds = mission.waves[mission.nextWaveIndex] || [];
    if (!waveIds.length) {
      const completed = await this.store.transaction('mission_execution_complete', (state) => {
        const target = state.missions[missionId];
        if (!target || target.status === 'cancelled') return false;
        target.phase = 'validation';
        target.status = 'ready';
        target.updatedAt = nowIso();
        state.runtime.timeline.push({ type: 'mission_execution_complete', missionId, at: nowIso() });
        return true;
      }, { missionId });
      return completed
        ? { missionId, phase: 'validation', completed: true }
        : { missionId, phase: 'execution', completed: false, reason: 'mission-cancelled' };
    }
    const waveTasks = tasks.filter((task) => waveIds.includes(task.id));
    const outstanding = waveTasks.filter((task) => ['admitted', 'dispatched', 'executing', 'cancelling', 'interrupted'].includes(task.status));
    if (outstanding.length) {
      return {
        missionId,
        waveIndex: mission.nextWaveIndex,
        reason: 'wave-has-outstanding-dispatches',
        pending: outstanding.map((task) => ({ taskId: task.id, status: task.status, dispatchId: task.dispatches.at(-1)?.id || null }))
      };
    }
    const retryRequired = waveTasks.filter((task) => ['failed', 'cancelled'].includes(task.status));
    if (retryRequired.length) {
      return {
        missionId,
        waveIndex: mission.nextWaveIndex,
        reason: 'wave-has-tasks-requiring-retry',
        tasks: retryRequired.map((task) => ({ taskId: task.id, status: task.status }))
      };
    }
    const currentTasks = waveTasks.filter((task) => task.status === 'planned');
    if (!currentTasks.length && waveTasks.every((task) => task.status === 'done')) {
      const advanced = await this.#advanceWaveIfComplete(missionId, mission.nextWaveIndex);
      return { missionId, waveIndex: mission.nextWaveIndex, completed: advanced, reason: 'wave-already-complete' };
    }
    for (const task of currentTasks) {
      if (!MissionService.dependenciesSatisfied(task, tasks)) {
        throw Object.assign(new Error(`Dependencies are not satisfied for ${task.id}`), { code: 'TASK_DEPENDENCY_BLOCKED' });
      }
    }
    const admission = await this.#reserveAdmissions({ missionId, projectId: project.id, waveIndex: mission.nextWaveIndex, runWorkers });
    if (!admission.taskIds.length) return { missionId, admitted: [], reason: admission.reason || 'global-worker-admission-full' };

    let missionWt;
    let waveBase;
    try {
      missionWt = await this.worktreeManager.ensureMissionWorktree(project, mission);
      const missionIdentity = await sourceIdentity(missionWt.path);
      waveBase = missionIdentity.head;
    } catch (error) {
      await this.#releaseAdmissions(admission, 'mission-worktree-preparation-failed');
      throw error;
    }
    const experience = this.experienceService
      ? await this.experienceService.route({ projectId: project.id, sourceHead: waveBase, role: 'worker', limit: 8 })
      : { items: [], precedence: 'Current repository/runtime evidence outranks project experience.' };
    const refreshed = await this.missionService.status({ missionId });
    const admitted = refreshed.tasks.filter((task) => admission.taskIds.includes(task.id));

    const prepared = [];
    const preparationFailures = [];
    for (const task of admitted) {
      let worktree = null;
      const dispatchId = randomId('dispatch');
      try {
        worktree = await this.worktreeManager.createTaskWorktree(project, mission, task, waveBase);
        let bootstrap = null;
        let bootstrapEvidenceId = null;
        if (normalizedBootstrapAuthorization) {
          try {
            bootstrap = await this.bootstrapExecutor.prepare({ worktreePath: worktree.path, plan: frozenBootstrapPlan, authorization: normalizedBootstrapAuthorization });
            const evidence = await this.evidenceService.record({
              projectId: project.id, missionId, taskId: task.id, type: 'bootstrap',
              summary: bootstrap, sourceIdentity: { head: waveBase },
              metadata: { planContract: frozenBootstrapPlan?.contract || null, projectTruthContract: mission.projectTruth?.contract || null }
            });
            bootstrapEvidenceId = evidence.id;
          } catch (error) {
            const safeDetails = error?.details && typeof error.details === 'object' ? error.details : null;
            const evidence = await this.evidenceService.record({
              projectId: project.id, missionId, taskId: task.id, type: 'bootstrap-failure',
              summary: { code: error?.code || 'BOOTSTRAP_FAILED', message: String(error?.message || error).slice(0, 500), details: safeDetails },
              sourceIdentity: { head: waveBase }, metadata: { planContract: frozenBootstrapPlan?.contract || null, projectTruthContract: mission.projectTruth?.contract || null }
            });
            error.bootstrapEvidenceId = evidence.id;
            throw error;
          }
        }
        const packet = packetFor(project, refreshed.mission, task, waveBase, experience);
        const packetPath = path.join(this.store.artifactsDir, 'worker-packets', `${dispatchId}.json`);
        if (!runWorkers) {
          await writeWorkerPacket({
            worktreePath: worktree.path,
            packetPath,
            taskId: task.id,
            packet,
            packetRoot: this.store.artifactsDir
          });
        }
        await this.store.transaction('worker_dispatched', (state) => {
          const target = state.tasks[task.key];
          const liveMission = state.missions[missionId];
          if (liveMission?.status === 'cancelled') {
            throw Object.assign(new Error('Mission was cancelled before worker dispatch'), { code: 'MISSION_CANCELLED' });
          }
          if (target.status !== 'admitted' || target.admission?.id !== admission.id) {
            throw Object.assign(new Error(`Worker admission was lost for ${task.id}`), { code: 'WORKER_ADMISSION_LOST' });
          }
          target.status = runWorkers ? 'executing' : 'dispatched';
          target.attempts += 1;
          target.updatedAt = nowIso();
          target.admission = null;
          target.dispatches.push({ id: dispatchId, waveBase, worktreePath: worktree.path, packetPath, packet, bootstrapEvidenceId, status: runWorkers ? 'executing' : 'ready', createdAt: nowIso() });
          liveMission.status = runWorkers ? 'executing' : 'ready';
          state.runtime.timeline.push({ type: 'worker_dispatched', missionId, taskId: task.id, dispatchId, runWorkers, at: nowIso() });
        }, { missionId, taskId: task.id, dispatchId, runWorkers, admissionId: admission.id });
        prepared.push({ task: { ...task, attempts: task.attempts + 1 }, packet, packetPath, worktree, dispatchId, bootstrap, bootstrapEvidenceId });
      } catch (error) {
        if (worktree) await this.worktreeManager.removeTaskWorktree(project, mission, task).catch(() => {});
        await this.#releaseAdmissions({ ...admission, taskIds: [task.id] }, 'task-preparation-failed');
        preparationFailures.push({ taskId: task.id, code: error.code || 'ERROR', message: error.message, bootstrapEvidenceId: error.bootstrapEvidenceId || null });
      }
    }
    if (!runWorkers) return { missionId, waveIndex: mission.nextWaveIndex, waveBase, dispatched: prepared.map(({ task, packet, packetPath, worktree, dispatchId }) => ({ taskId: task.id, dispatchId, worktreePath: worktree.path, packetPath, packet })), preparationFailures };
    if (!prepared.length) return { missionId, waveIndex: mission.nextWaveIndex, waveBase, results: [], preparationFailures };

    const results = await Promise.all(prepared.map(async (item) => {
      const config = resolveWorkerConfig(project, item.task.worker);
      try {
        const before = await sourceIdentity(item.worktree.path);
        if (before.head !== waveBase) throw Object.assign(new Error('Task worktree HEAD drifted before worker start'), { code: 'TASK_HEAD_OWNERSHIP_VIOLATION' });
        const run = await this.workerAdapter.run({
          project,
          mission,
          task: { ...item.task, key: `${mission.id}:${item.task.id}` },
          worktreePath: item.worktree.path,
          packet: item.packet,
          packetPath: item.packetPath,
          packetRoot: this.store.artifactsDir,
          config
        });
        const after = await sourceIdentity(item.worktree.path);
        if (after.head !== waveBase) throw Object.assign(new Error('Worker changed task HEAD; runtime owns commits'), { code: 'TASK_HEAD_OWNERSHIP_VIOLATION', details: { before: waveBase, after: after.head } });
        if (run.termination?.reason === 'operator-cancel') {
          throw Object.assign(new Error('Worker execution was cancelled by the operator'), { code: 'WORKER_CANCELLED', details: run });
        }
        if (run.termination?.reason === 'timeout') {
          throw Object.assign(new Error('Worker execution exceeded its runtime timeout'), { code: 'WORKER_TIMEOUT', details: run });
        }
        if (run.code !== 0) throw Object.assign(new Error(`Worker exited with code ${run.code}`), { code: 'WORKER_FAILED', details: run });
        const paths = await changedPaths(item.worktree.path, waveBase);
        await assertPathsWithinScope(item.worktree.path, paths, item.task.writeSet);
        const evidence = await this.evidenceService.record({
          projectId: project.id,
          missionId,
          taskId: item.task.id,
          type: 'worker',
          summary: {
            exitCode: run.code,
            changedPaths: paths,
            runtimeNamespace: run.runtimeNamespace || null,
            durationMs: run.durationMs ?? null,
            outputCapture: run.outputCapture || null
          },
          sourceIdentity: { head: waveBase },
          artifact: `${run.stdout}\n--- stderr ---\n${run.stderr}`
        });
        let commitSha = null;
        if (paths.length) {
          await git(item.worktree.path, ['add', '-A']);
          await git(item.worktree.path, ['-c', 'user.name=Veteran Engineer Runtime', '-c', 'user.email=veteran-engineer@local.invalid', 'commit', '-m', `veteran(${mission.id}): ${item.task.id}`]);
          commitSha = (await git(item.worktree.path, ['rev-parse', 'HEAD'])).stdout.trim();
          await this.#validateTaskCommit(item.worktree.path, waveBase, commitSha, item.task.writeSet);
        }
        return { ...item, ok: true, commitSha, evidenceId: evidence.id, changedPaths: paths, run };
      } catch (error) {
        const failureCode = error.code || 'ERROR';
        const evidenceType = failureCode === 'WORKER_CANCELLED'
          ? 'worker-cancelled'
          : (failureCode === 'WORKER_TIMEOUT' ? 'worker-timeout' : 'worker-failure');
        const evidence = await this.evidenceService.record({
          projectId: project.id,
          missionId,
          taskId: item.task.id,
          type: evidenceType,
          summary: {
            code: failureCode,
            message: error.message,
            runtimeNamespace: error.details?.runtimeNamespace || null,
            durationMs: error.details?.durationMs ?? null,
            termination: error.details?.termination || null,
            outputCapture: error.details?.outputCapture || null
          },
          sourceIdentity: { head: waveBase },
          artifact: error.details || null
        });
        if (this.experienceService && !['WORKER_CANCELLED', 'WORKER_TIMEOUT', 'WORKER_SUPERVISOR_LOST'].includes(failureCode)) {
          await this.experienceService.commit({
            projectId: project.id,
            mechanism: 'worker-execution',
            statement: `Worker failure ${failureCode} occurred at owner ${item.task.owner}; treat this only as a reviewable project-scoped failed-attempt candidate.`,
            kind: 'failed-assumption',
            equivalenceClass: `${item.task.owner}:${failureCode}`,
            evidenceIds: [evidence.id],
            sourceIdentity: { head: waveBase },
            appliesWhen: `Task owner is ${item.task.owner} and failure class is ${failureCode}`,
            doesNotApplyWhen: 'Current repository/runtime evidence contradicts this candidate or scope differs.'
          }).catch(() => {});
        }
        return { ...item, ok: false, error, evidenceId: evidence.id };
      }
    }));

    for (const result of results.sort((a, b) => a.task.id.localeCompare(b.task.id))) {
      if (!result.ok) {
        const code = result.error.code || 'ERROR';
        const cancelled = code === 'WORKER_CANCELLED';
        const timedOut = code === 'WORKER_TIMEOUT';
        const operation = cancelled ? 'worker_cancelled' : (timedOut ? 'worker_timed_out' : 'worker_failed');
        const eventType = operation;
        await this.store.transaction(operation, (state) => {
          const task = state.tasks[`${missionId}:${result.task.id}`];
          const liveMission = state.missions[missionId];
          const missionCancelled = liveMission?.status === 'cancelled';
          task.status = missionCancelled ? 'cancelled' : (cancelled ? 'cancelled' : 'failed');
          task.updatedAt = nowIso();
          const dispatch = task.dispatches.find((entry) => entry.id === result.dispatchId);
          if (dispatch) {
            Object.assign(dispatch, {
              status: missionCancelled ? 'cancelled' : (cancelled ? 'cancelled' : 'failed'),
              endedAt: nowIso(),
              error: { code, message: result.error.message },
              runtimeNamespace: result.error.details?.runtimeNamespace || null,
              durationMs: result.error.details?.durationMs ?? null,
              termination: result.error.details?.termination || null,
              outputCapture: result.error.details?.outputCapture || null
            });
          }
          if (liveMission && !missionCancelled) liveMission.status = 'blocked';
          state.runtime.timeline.push({ type: eventType, missionId, taskId: result.task.id, at: nowIso(), code, missionCancelled });
        }, { missionId, taskId: result.task.id, code });
        continue;
      }

      const integrationBefore = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
      let integrationSha = integrationBefore;
      if (result.commitSha) {
        const cherry = await git(missionWt.path, ['cherry-pick', result.commitSha], { allowFailure: true });
        if (cherry.code !== 0) {
          await git(missionWt.path, ['cherry-pick', '--abort'], { allowFailure: true });
          await this.store.transaction('task_integration_failed', (state) => {
            const task = state.tasks[`${missionId}:${result.task.id}`];
            const liveMission = state.missions[missionId];
            const missionCancelled = liveMission?.status === 'cancelled';
            task.status = missionCancelled ? 'cancelled' : 'failed';
            task.commitSha = result.commitSha;
            task.updatedAt = nowIso();
            if (liveMission && !missionCancelled) liveMission.status = 'blocked';
            state.runtime.timeline.push({ type: 'task_integration_failed', missionId, taskId: result.task.id, at: nowIso(), missionCancelled });
          }, { missionId, taskId: result.task.id });
          continue;
        }
        integrationSha = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
      }
      const integrated = await this.store.transaction('task_integrated', (state) => {
        const liveMission = state.missions[missionId];
        if (!liveMission || liveMission.status === 'cancelled') return false;
        const task = state.tasks[`${missionId}:${result.task.id}`];
        task.status = 'done';
        task.commitSha = result.commitSha;
        task.integrationSha = integrationSha;
        task.updatedAt = nowIso();
        const dispatch = task.dispatches.find((entry) => entry.id === result.dispatchId);
        if (dispatch) {
          Object.assign(dispatch, {
            status: 'integrated',
            endedAt: nowIso(),
            commitSha: result.commitSha,
            integrationSha,
            runtimeNamespace: result.run?.runtimeNamespace || null,
            durationMs: result.run?.durationMs ?? null,
            termination: result.run?.termination || null,
            outputCapture: result.run?.outputCapture || null
          });
        }
        state.runtime.timeline.push({ type: 'task_integrated', missionId, taskId: result.task.id, integrationSha, at: nowIso() });
        return true;
      }, { missionId, taskId: result.task.id, integrationSha });
      if (!integrated) {
        const discardedCommitSha = result.commitSha || null;
        if (discardedCommitSha) await git(missionWt.path, ['reset', '--hard', integrationBefore]);
        await this.#recordDiscardedWorkerResult({ missionId, result });
        result.ok = false;
        result.discardedCommitSha = discardedCommitSha;
        result.commitSha = null;
        result.error = Object.assign(new Error('Worker result was discarded because the mission was cancelled before integration'), {
          code: 'MISSION_CANCELLED',
          details: result.run
        });
        continue;
      }
      await this.worktreeManager.removeTaskWorktree(project, mission, result.task);
    }

    await this.#advanceWaveIfComplete(missionId, mission.nextWaveIndex);
    return {
      missionId,
      waveIndex: mission.nextWaveIndex,
      waveBase,
      results: results.map((result) => ({
        taskId: result.task.id,
        ok: result.ok,
        commitSha: result.commitSha || null,
        discardedCommitSha: result.discardedCommitSha || null,
        bootstrap: result.bootstrap || null,
        bootstrapEvidenceId: result.bootstrapEvidenceId || null,
        runtime: result.ok
          ? {
              namespace: result.run?.runtimeNamespace || null,
              durationMs: result.run?.durationMs ?? null,
              termination: result.run?.termination || null,
              outputCapture: result.run?.outputCapture || null
            }
          : {
              namespace: result.error.details?.runtimeNamespace || null,
              durationMs: result.error.details?.durationMs ?? null,
              termination: result.error.details?.termination || null,
              outputCapture: result.error.details?.outputCapture || null
            },
        error: result.ok ? null : { code: result.error.code || 'ERROR', message: result.error.message }
      })),
      preparationFailures
    };
  }

  async #recordDiscardedWorkerResult({ missionId, result }) {
    return this.store.transaction('worker_result_discarded_after_mission_cancel', (state) => {
      const mission = state.missions[missionId];
      if (!mission || mission.status !== 'cancelled') return false;
      const task = state.tasks[`${missionId}:${result.task.id}`];
      if (!task) return false;
      task.status = 'cancelled';
      task.updatedAt = nowIso();
      const dispatch = task.dispatches.find((entry) => entry.id === result.dispatchId);
      if (dispatch) {
        Object.assign(dispatch, {
          status: 'cancelled',
          endedAt: nowIso(),
          error: { code: 'MISSION_CANCELLED', message: 'Worker result was discarded because the mission was cancelled before integration' },
          discardedCommitSha: result.commitSha || null,
          discardedChangedPaths: result.changedPaths || [],
          runtimeNamespace: result.run?.runtimeNamespace || null,
          durationMs: result.run?.durationMs ?? null,
          termination: result.run?.termination || null,
          outputCapture: result.run?.outputCapture || null
        });
      }
      state.runtime.timeline.push({
        type: 'worker_result_discarded_after_mission_cancel',
        missionId,
        taskId: result.task.id,
        dispatchId: result.dispatchId,
        discardedCommitSha: result.commitSha || null,
        at: nowIso()
      });
      return true;
    }, { missionId, taskId: result.task.id, dispatchId: result.dispatchId, discardedCommitSha: result.commitSha || null });
  }

  async #reserveAdmissions({ missionId, projectId, waveIndex, runWorkers }) {
    const admissionId = randomId('admission');
    return this.store.transaction('worker_admission_reserved', (state) => {
      const mission = state.missions[missionId];
      const project = state.projects[projectId];
      if (!mission || !project || mission.status === 'cancelled' || mission.phase !== 'execution' || mission.nextWaveIndex !== waveIndex) {
        return { id: admissionId, missionId, taskIds: [], reason: 'mission-state-changed' };
      }
      const waveIds = mission.waves[waveIndex] || [];
      const candidates = waveIds.map((id) => state.tasks[`${missionId}:${id}`]).filter((task) => task?.status === 'planned');
      const capabilityReserved = candidates.filter((task) => task.capabilityLease?.reservationId);
      const admissionCandidates = capabilityReserved.length ? capabilityReserved : candidates;
      const byId = new Map(Object.values(state.tasks).filter((task) => task.missionId === missionId).map((task) => [task.id, task]));
      const ready = admissionCandidates.filter((task) => task.dependencies.every((dep) => byId.get(dep)?.status === 'done'));
      const budget = missionExecutionCapacity({ state, mission, project, runWorkers });
      const selected = ready.slice(0, budget.capacity);
      for (const task of selected) {
        task.status = 'admitted';
        task.admission = { id: admissionId, runWorkers, reservedAt: nowIso() };
        task.updatedAt = nowIso();
      }
      if (selected.length) {
        state.runtime.timeline.push({ type: 'worker_admission_reserved', missionId, admissionId, taskIds: selected.map((task) => task.id), runWorkers, at: nowIso() });
      }
      return { id: admissionId, missionId, taskIds: selected.map((task) => task.id), reason: selected.length ? null : (budget.capacity === 0 ? (budget.reason || 'global-worker-admission-full') : 'no-ready-planned-tasks') };
    }, { missionId, projectId, waveIndex, runWorkers, admissionId });
  }

  async #releaseAdmissions(admission, reason) {
    if (!admission?.taskIds?.length) return;
    await this.store.transaction('worker_admission_released', (state) => {
      const released = [];
      for (const taskId of admission.taskIds) {
        const task = state.tasks[`${admission.missionId || ''}:${taskId}`] || Object.values(state.tasks).find((item) => item.id === taskId && item.admission?.id === admission.id);
        if (!task || task.status !== 'admitted' || task.admission?.id !== admission.id) continue;
        task.status = 'planned';
        task.admission = null;
        task.updatedAt = nowIso();
        released.push(task.id);
      }
      if (released.length) state.runtime.timeline.push({ type: 'worker_admission_released', admissionId: admission.id, taskIds: released, reason, at: nowIso() });
    }, { admissionId: admission.id, taskIds: admission.taskIds, reason });
  }

  async commitExternalTaskResult({ missionId, taskId }) {
    const { mission, tasks } = await this.missionService.status({ missionId });
    if (mission.status === 'cancelled') throw Object.assign(new Error('Mission is cancelled'), { code: 'MISSION_CANCELLED' });
    const task = tasks.find((item) => item.id === taskId);
    if (!task) throw Object.assign(new Error(`Unknown task ${taskId}`), { code: 'TASK_NOT_FOUND' });
    if (!['dispatched', 'interrupted'].includes(task.status)) {
      throw Object.assign(new Error('External task result is only accepted for dispatched/interrupted tasks'), { code: 'TASK_RESULT_STATE_INVALID', details: { status: task.status } });
    }
    const project = await this.projectService.get(mission.projectId);
    const dispatch = task.dispatches.at(-1);
    if (!dispatch?.worktreePath) throw Object.assign(new Error('Task has no dispatched worktree'), { code: 'TASK_NOT_DISPATCHED' });
    const beforeHead = dispatch.waveBase;
    const current = await sourceIdentity(dispatch.worktreePath);
    if (current.head !== beforeHead) throw Object.assign(new Error('External worker changed HEAD; runtime owns commits'), { code: 'TASK_HEAD_OWNERSHIP_VIOLATION' });
    const paths = await changedPaths(dispatch.worktreePath, beforeHead);
    await assertPathsWithinScope(dispatch.worktreePath, paths, task.writeSet);
    let commitSha = null;
    if (paths.length) {
      await git(dispatch.worktreePath, ['add', '-A']);
      await git(dispatch.worktreePath, ['-c', 'user.name=Veteran Engineer Runtime', '-c', 'user.email=veteran-engineer@local.invalid', 'commit', '-m', `veteran(${mission.id}): ${task.id}`]);
      commitSha = (await git(dispatch.worktreePath, ['rev-parse', 'HEAD'])).stdout.trim();
      await this.#validateTaskCommit(dispatch.worktreePath, beforeHead, commitSha, task.writeSet);
    }
    const missionWt = await this.worktreeManager.ensureMissionWorktree(project, mission);
    const integrationBefore = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
    let integrationSha = integrationBefore;
    if (commitSha) {
      await git(missionWt.path, ['cherry-pick', commitSha]);
      integrationSha = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
    }
    const integrated = await this.store.transaction('external_task_result_integrated', (state) => {
      const liveMission = state.missions[missionId];
      if (!liveMission || liveMission.status === 'cancelled') return false;
      const target = state.tasks[`${missionId}:${taskId}`];
      target.status = 'done';
      target.commitSha = commitSha;
      target.integrationSha = integrationSha;
      target.updatedAt = nowIso();
      const d = target.dispatches.at(-1);
      if (d) Object.assign(d, { status: 'integrated', endedAt: nowIso(), commitSha, integrationSha });
      reconcileInterruptedMission(state, liveMission);
      state.runtime.timeline.push({ type: 'external_task_result_integrated', missionId, taskId, integrationSha, at: nowIso() });
      return true;
    }, { missionId, taskId, integrationSha });
    if (!integrated) {
      if (commitSha) await git(missionWt.path, ['reset', '--hard', integrationBefore]);
      throw Object.assign(new Error('Mission was cancelled before the external task result could be integrated'), { code: 'MISSION_CANCELLED' });
    }
    const waveAdvanced = await this.#advanceWaveIfComplete(missionId, mission.nextWaveIndex);
    await this.worktreeManager.removeTaskWorktree(project, mission, task);
    return { taskId, commitSha, integrationSha, changedPaths: paths, waveAdvanced };
  }

  async cancelWorker({ missionId, taskId }) {
    const key = `${missionId}:${taskId}`;
    const signalled = this.workerAdapter.cancel(key);
    await this.store.transaction('worker_cancel_requested', (state) => {
      const task = state.tasks[key];
      if (!task) throw Object.assign(new Error(`Unknown task ${taskId}`), { code: 'TASK_NOT_FOUND' });
      if (!['executing', 'cancelling'].includes(task.status)) throw Object.assign(new Error('Task is not executing'), { code: 'TASK_NOT_EXECUTING' });
      task.status = 'cancelling';
      task.updatedAt = nowIso();
      state.runtime.timeline.push({ type: 'worker_cancel_requested', missionId, taskId, signalled, at: nowIso() });
    }, { missionId, taskId, signalled });
    return { missionId, taskId, signalled };
  }

  async retryWorker({ missionId, taskId }) {
    return this.store.transaction('worker_retry_scheduled', (state) => {
      const task = state.tasks[`${missionId}:${taskId}`];
      if (!task) throw Object.assign(new Error(`Unknown task ${taskId}`), { code: 'TASK_NOT_FOUND' });
      const mission = state.missions[missionId];
      if (!mission) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      if (mission.status === 'cancelled') throw Object.assign(new Error('Cancelled missions cannot schedule worker retries'), { code: 'MISSION_CANCELLED' });
      if (!['failed', 'interrupted', 'cancelled'].includes(task.status)) throw Object.assign(new Error('Only failed/interrupted/cancelled tasks can be retried'), { code: 'TASK_RETRY_INVALID' });
      task.status = 'planned';
      task.admission = null;
      task.updatedAt = nowIso();
      mission.status = 'ready';
      reconcileInterruptedMission(state, mission);
      mission.updatedAt = nowIso();
      state.runtime.timeline.push({ type: 'worker_retry_scheduled', missionId, taskId, at: nowIso() });
      return task;
    }, { missionId, taskId });
  }

  async resumeWorker({ missionId, taskId }) {
    const { mission, tasks } = await this.missionService.status({ missionId });
    const task = tasks.find((item) => item.id === taskId);
    if (!task) throw Object.assign(new Error(`Unknown task ${taskId}`), { code: 'TASK_NOT_FOUND' });
    if (task.status !== 'interrupted') throw Object.assign(new Error('Task is not interrupted'), { code: 'TASK_NOT_INTERRUPTED' });
    const dispatch = task.dispatches.at(-1);
    if (!dispatch?.worktreePath) return this.retryWorker({ missionId, taskId });
    const current = await sourceIdentity(dispatch.worktreePath).catch(() => null);
    if (!current || current.head !== dispatch.waveBase) {
      throw Object.assign(new Error('Interrupted worker outcome cannot be reconciled safely; task HEAD changed or worktree disappeared'), { code: 'WORKER_RECONCILIATION_REQUIRED' });
    }
    const paths = await changedPaths(dispatch.worktreePath, dispatch.waveBase);
    await assertPathsWithinScope(dispatch.worktreePath, paths, task.writeSet);
    if (paths.length && ['executing', 'cancelling'].includes(dispatch.status)) {
      throw Object.assign(new Error('Interrupted runtime-managed worker left partial changes with an unknown completion boundary; explicit retry or reconciliation is required'), {
        code: 'WORKER_RECONCILIATION_REQUIRED',
        details: {
          dispatchId: dispatch.id || null,
          dispatchStatus: dispatch.status,
          changedPaths: paths,
          reason: 'runtime-managed-outcome-unknown'
        }
      });
    }
    if (paths.length) return this.commitExternalTaskResult({ missionId, taskId });
    return this.retryWorker({ missionId, taskId });
  }

  async #advanceWaveIfComplete(missionId, expectedWaveIndex) {
    const snapshot = await this.store.read();
    const mission = snapshot.missions[missionId];
    if (!mission || mission.status === 'cancelled' || mission.nextWaveIndex !== expectedWaveIndex) return false;
    const waveIds = mission.waves[expectedWaveIndex] || [];
    if (!waveIds.length) return false;
    const allDone = waveIds.every((id) => snapshot.tasks[`${missionId}:${id}`]?.status === 'done');
    if (!allDone) return false;
    return this.store.transaction('mission_wave_completed', (state) => {
      const target = state.missions[missionId];
      if (!target || target.status === 'cancelled' || target.nextWaveIndex !== expectedWaveIndex) return false;
      const ids = target.waves[expectedWaveIndex] || [];
      if (!ids.every((id) => state.tasks[`${missionId}:${id}`]?.status === 'done')) return false;
      target.nextWaveIndex += 1;
      target.status = 'ready';
      target.updatedAt = nowIso();
      state.runtime.timeline.push({ type: 'mission_wave_completed', missionId, waveIndex: expectedWaveIndex, at: nowIso() });
      return true;
    }, { missionId, waveIndex: expectedWaveIndex });
  }

  async #validateTaskCommit(repo, baseHead, commitSha, writeSet) {
    const parents = (await git(repo, ['rev-list', '--parents', '-n', '1', commitSha])).stdout.trim().split(/\s+/);
    if (parents[1] !== baseHead) throw Object.assign(new Error('Task commit parent does not equal wave base'), { code: 'TASK_COMMIT_STRUCTURE_INVALID', details: parents });
    const diff = (await git(repo, ['diff-tree', '--no-commit-id', '--name-only', '-r', '-z', commitSha])).stdout.split('\0').filter(Boolean);
    await assertPathsWithinScope(repo, diff, writeSet);
  }
}
