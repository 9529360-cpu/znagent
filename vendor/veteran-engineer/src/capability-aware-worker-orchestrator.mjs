import { sourceIdentity } from './git.mjs';
import { nowIso, randomId } from './util.mjs';
import { activeProjectWriteConflicts, missionExecutionCapacity } from './adaptive-mission-strategy.mjs';
import {
  activeRuntimeResourceConflicts,
  bindRuntimeResources,
  buildCapabilitySnapshot,
  runtimeResourceConflicts,
  taskCapabilityReadiness,
  taskRuntimeContext
} from './capability-plane.mjs';
import { runtimeManagedExecutionReadiness, workerCapabilityProfile } from './worker-capability-profile.mjs';

const OUTSTANDING_LEASE_STATUSES = new Set(['admitted', 'dispatched', 'executing', 'cancelling', 'interrupted']);
const TERMINAL_TASK_STATUSES = new Set(['done', 'failed', 'cancelled', 'blocked', 'superseded']);

function readyWaveTasks(state, mission) {
  const waveIds = mission.waves?.[mission.nextWaveIndex] || [];
  const missionTasks = Object.values(state.tasks).filter((task) => task.missionId === mission.id);
  const byId = new Map(missionTasks.map((task) => [task.id, task]));
  return waveIds
    .map((id) => byId.get(id))
    .filter((task) => task?.status === 'planned')
    .filter((task) => task.dependencies.every((dep) => byId.get(dep)?.status === 'done'));
}

function predictedAdmission(state, mission, project, runWorkers) {
  const ready = readyWaveTasks(state, mission);
  const budget = missionExecutionCapacity({ state, mission, project, runWorkers });
  return { ready, capacity: budget.capacity, budget };
}

function sameReservationConflicts(tasks, mission, project) {
  const conflicts = [];
  for (let i = 0; i < tasks.length; i += 1) {
    for (let j = i + 1; j < tasks.length; j += 1) {
      const left = tasks[i];
      const right = tasks[j];
      const resources = runtimeResourceConflicts(
        left.runtimeResources || [],
        right.runtimeResources || [],
        taskRuntimeContext(left, mission, project),
        taskRuntimeContext(right, mission, project)
      );
      if (resources.length) conflicts.push({ taskId: right.id, conflictingTaskId: left.id, resources });
    }
  }
  return conflicts;
}

function missionSourceAuthorityEstablished(tasks = []) {
  return tasks.some((task) => Boolean(task.integrationSha) || (task.dispatches || []).length > 0);
}

function unavailableMissionSourceIdentity() {
  return {
    head: null,
    branch: null,
    dirty: true,
    dirtyPaths: [],
    unavailable: true
  };
}

export class CapabilityAwareWorkerOrchestrator {
  constructor({ delegate, store, projectService, missionService, worktreeManager = null }) {
    this.delegate = delegate;
    this.store = store;
    this.projectService = projectService;
    this.missionService = missionService;
    this.worktreeManager = worktreeManager;
  }

  async #snapshot(missionId) {
    const { mission, tasks } = await this.missionService.status({ missionId });
    const project = await this.projectService.get(mission.projectId);
    const projectSourceIdentity = await sourceIdentity(project.repoPath);
    const missionSourceExpected = Boolean(this.worktreeManager) && missionSourceAuthorityEstablished(tasks);
    let missionSourceIdentity = null;
    let missionSourceErrorCode = null;
    if (this.worktreeManager) {
      const missionPath = this.worktreeManager.missionPath(mission);
      try {
        missionSourceIdentity = await sourceIdentity(missionPath);
      } catch (error) {
        missionSourceErrorCode = error?.code || 'SOURCE_IDENTITY_UNAVAILABLE';
      }
    }
    const missionSourceUnavailable = missionSourceExpected && !missionSourceIdentity;
    const currentSourceIdentity = missionSourceIdentity
      || (missionSourceUnavailable ? unavailableMissionSourceIdentity() : projectSourceIdentity);
    const state = await this.store.read();
    const snapshot = buildCapabilitySnapshot({ project, mission, tasks, liveSourceIdentity: currentSourceIdentity, state });
    snapshot.sourceScope = missionSourceIdentity
      ? 'mission-worktree'
      : missionSourceUnavailable
        ? 'mission-worktree-unavailable'
        : 'project-checkout';
    snapshot.sourceAuthority = missionSourceIdentity
      ? { expectedScope: 'mission-worktree', available: true }
      : missionSourceUnavailable
        ? {
            expectedScope: 'mission-worktree',
            available: false,
            reason: 'mission-worktree-source-unavailable',
            errorCode: missionSourceErrorCode
          }
        : { expectedScope: 'project-checkout', available: true };
    snapshot.projectSourceIdentity = projectSourceIdentity;
    snapshot.executionStrategy = mission.executionStrategy || null;
    const byId = new Map(tasks.map((task) => [task.id, task]));
    snapshot.wave = snapshot.wave.map((item) => {
      const task = byId.get(item.taskId);
      const dispatchOnlyReadiness = taskCapabilityReadiness(task, project);
      const runtimeManagedReadiness = runtimeManagedExecutionReadiness(task, project);
      const projectWriteConflicts = task ? activeProjectWriteConflicts({ state, mission, task }) : [];
      return {
        ...item,
        dispatchOnlyCapabilityReady: dispatchOnlyReadiness.ready && projectWriteConflicts.length === 0,
        runtimeManagedCapabilityReady: dispatchOnlyReadiness.missingSensing.length === 0 && runtimeManagedReadiness.ready && projectWriteConflicts.length === 0,
        runtimeManagedMissingSensing: dispatchOnlyReadiness.missingSensing,
        runtimeManagedMissingExecution: runtimeManagedReadiness.missingExecution,
        runtimeManagedExecutionBlockers: runtimeManagedReadiness.blockers,
        runtimeManagedExecution: runtimeManagedReadiness.profile,
        projectWriteConflicts
      };
    });
    return snapshot;
  }

  async #snapshotAfterExecution(missionId, fallback) {
    try {
      const current = await this.#snapshot(missionId);
      return { ...current, observation: { stage: 'post-execution', currentAtReturn: true } };
    } catch (error) {
      return {
        ...fallback,
        observation: {
          stage: 'preflight-fallback',
          currentAtReturn: false,
          refreshError: { code: error?.code || 'SNAPSHOT_REFRESH_FAILED' }
        }
      };
    }
  }

  snapshot({ missionId }) {
    return this.#snapshot(missionId);
  }

  async #reserve({ missionId, runWorkers }) {
    const reservationId = randomId('capability');
    return this.store.transaction('capability_execution_reserved', (state) => {
      const mission = state.missions[missionId];
      if (!mission || mission.phase !== 'execution') {
        return { id: reservationId, missionId, taskIds: [], blocked: [], reason: 'mission-not-executing' };
      }
      const project = state.projects[mission.projectId];
      if (!project) throw Object.assign(new Error(`Unknown project: ${mission.projectId}`), { code: 'PROJECT_NOT_FOUND' });

      for (const task of Object.values(state.tasks)) {
        if (task.capabilityLease && TERMINAL_TASK_STATUSES.has(task.status)) task.capabilityLease = null;
      }

      const admission = predictedAdmission(state, mission, project, runWorkers);
      if (!admission.ready.length || admission.capacity === 0) {
        return {
          id: reservationId,
          missionId,
          taskIds: [],
          blocked: [],
          reason: admission.capacity === 0 ? (admission.budget.reason || 'global-worker-admission-full') : 'no-ready-planned-tasks'
        };
      }

      const blocked = [];
      const selected = [];
      for (const task of admission.ready) {
        if (selected.length >= admission.capacity) break;
        const projectWriteConflicts = activeProjectWriteConflicts({ state, mission, task });
        if (projectWriteConflicts.length) {
          blocked.push({ taskId: task.id, reason: 'project-write-conflict', conflicts: projectWriteConflicts });
          continue;
        }
        const policyReadiness = taskCapabilityReadiness(task, project);
        const managedReadiness = runWorkers ? runtimeManagedExecutionReadiness(task, project) : null;
        const missingExecution = runWorkers ? managedReadiness.missingExecution : policyReadiness.missingExecution;
        const executionBlockers = runWorkers ? managedReadiness.blockers : [];
        if (policyReadiness.missingSensing.length || missingExecution.length || executionBlockers.length) {
          blocked.push({
            taskId: task.id,
            reason: 'capability-missing',
            missingSensing: policyReadiness.missingSensing,
            missingExecution,
            executionBlockers,
            runtimeManagedExecution: managedReadiness?.profile || null
          });
          continue;
        }
        const conflicts = activeRuntimeResourceConflicts({ state, task, mission, project });
        if (conflicts.length) {
          blocked.push({ taskId: task.id, reason: 'runtime-resource-conflict', conflicts });
          continue;
        }
        const sameReservation = sameReservationConflicts([...selected, task], mission, project)
          .filter((entry) => entry.taskId === task.id);
        if (sameReservation.length) {
          blocked.push({ ...sameReservation[0], reason: 'same-admission-resource-conflict' });
          continue;
        }
        selected.push(task);
      }

      if (!selected.length) {
        if (blocked.length) {
          state.runtime.timeline.push({ type: 'capability_execution_blocked', missionId, taskIds: admission.ready.map((task) => task.id), blocked, at: nowIso() });
        }
        return {
          id: reservationId,
          missionId,
          taskIds: [],
          blocked,
          reason: blocked.length ? 'capability-preflight-blocked' : 'no-ready-planned-tasks'
        };
      }

      const leases = selected.map((task) => {
        const executionProfile = runWorkers ? workerCapabilityProfile(project, task) : null;
        const lease = {
          id: randomId('lease'),
          reservationId,
          missionId,
          projectId: mission.projectId,
          taskId: task.id,
          resources: bindRuntimeResources(task.runtimeResources || [], taskRuntimeContext(task, mission, project)),
          sensingCapabilities: task.sensingCapabilities || [],
          executionCapabilities: task.executionCapabilities || [],
          executionProfile,
          runWorkers: runWorkers === true,
          reservedAt: nowIso()
        };
        task.capabilityLease = lease;
        task.updatedAt = nowIso();
        return lease;
      });
      if (blocked.length) {
        state.runtime.timeline.push({
          type: 'capability_execution_partially_blocked',
          missionId,
          reservationId,
          admittedTaskIds: selected.map((task) => task.id),
          blocked,
          at: nowIso()
        });
      }
      state.runtime.timeline.push({ type: 'capability_execution_reserved', missionId, reservationId, taskIds: selected.map((task) => task.id), at: nowIso() });
      return {
        id: reservationId,
        missionId,
        taskIds: selected.map((task) => task.id),
        leases,
        blocked,
        reason: blocked.length ? 'capability-preflight-partial' : null
      };
    }, { missionId, runWorkers, reservationId });
  }

  async #release(reservation, reason, keepTaskIds = []) {
    if (!reservation?.taskIds?.length) return { released: [] };
    const keep = new Set(keepTaskIds);
    return this.store.transaction('capability_execution_released', (state) => {
      const released = [];
      for (const taskId of reservation.taskIds) {
        if (keep.has(taskId)) continue;
        const task = state.tasks[`${reservation.missionId}:${taskId}`];
        if (!task?.capabilityLease || task.capabilityLease.reservationId !== reservation.id) continue;
        task.capabilityLease = null;
        task.updatedAt = nowIso();
        released.push(taskId);
      }
      if (released.length) state.runtime.timeline.push({ type: 'capability_execution_released', missionId: reservation.missionId, reservationId: reservation.id, taskIds: released, reason, at: nowIso() });
      return { released };
    }, { missionId: reservation.missionId, reservationId: reservation.id, reason });
  }

  async #reconcileReservation(reservation, reason) {
    if (!reservation?.taskIds?.length) return { released: [], retained: [] };
    const state = await this.store.read();
    const retained = reservation.taskIds.filter((taskId) => {
      const task = state.tasks[`${reservation.missionId}:${taskId}`];
      return task?.capabilityLease?.reservationId === reservation.id && OUTSTANDING_LEASE_STATUSES.has(task.status);
    });
    const released = await this.#release(reservation, reason, retained);
    return { released: released.released, retained };
  }

  async #releaseTask(missionId, taskId, reason) {
    return this.store.transaction('capability_task_released', (state) => {
      const task = state.tasks[`${missionId}:${taskId}`];
      if (!task?.capabilityLease) return { released: false };
      const leaseId = task.capabilityLease.id;
      task.capabilityLease = null;
      task.updatedAt = nowIso();
      state.runtime.timeline.push({ type: 'capability_task_released', missionId, taskId, leaseId, reason, at: nowIso() });
      return { released: true, leaseId };
    }, { missionId, taskId, reason });
  }

  async reconcileMission({ missionId, reason = 'mission-resume' }) {
    return this.store.transaction('capability_mission_reconciled', (state) => {
      const mission = state.missions[missionId];
      if (!mission) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      const released = [];
      const retained = [];
      for (const task of Object.values(state.tasks).filter((item) => item.missionId === missionId && item.capabilityLease)) {
        if (task.status === 'planned' || TERMINAL_TASK_STATUSES.has(task.status)) {
          released.push({ taskId: task.id, leaseId: task.capabilityLease.id, previousStatus: task.status });
          task.capabilityLease = null;
          task.updatedAt = nowIso();
        } else {
          retained.push({ taskId: task.id, leaseId: task.capabilityLease.id, status: task.status });
        }
      }
      state.runtime.timeline.push({ type: 'capability_mission_reconciled', missionId, reason, releasedTaskIds: released.map((item) => item.taskId), retainedTaskIds: retained.map((item) => item.taskId), at: nowIso() });
      return { missionId, released, retained };
    }, { missionId, reason });
  }

  async execute(args) {
    const runWorkers = args.runWorkers === true;
    const { mission } = await this.missionService.status({ missionId: args.missionId });
    if (typeof this.projectService.snapshot === 'function') {
      await this.projectService.snapshot({ projectId: mission.projectId });
    }
    const preflightSnapshot = await this.#snapshot(args.missionId);
    const reservation = await this.#reserve({ missionId: args.missionId, runWorkers });
    if (reservation.reason === 'capability-preflight-blocked') {
      return {
        missionId: args.missionId,
        reason: reservation.reason,
        blocked: reservation.blocked,
        capabilitySnapshot: {
          ...preflightSnapshot,
          observation: { stage: 'preflight-blocked', currentAtReturn: true }
        }
      };
    }
    if (!reservation.taskIds.length) {
      const result = await this.delegate.execute(args);
      const capabilitySnapshot = await this.#snapshotAfterExecution(args.missionId, preflightSnapshot);
      return { ...result, capabilitySnapshot };
    }

    let result;
    try {
      result = await this.delegate.execute(args);
    } catch (error) {
      await this.#reconcileReservation(reservation, 'delegate-threw').catch(() => {});
      throw error;
    }

    await this.#reconcileReservation(reservation, 'delegate-returned');
    const capabilitySnapshot = await this.#snapshotAfterExecution(args.missionId, preflightSnapshot);
    return {
      ...result,
      ...(reservation.blocked.length ? { capabilityBlocked: reservation.blocked } : {}),
      capabilitySnapshot
    };
  }

  async commitExternalTaskResult(args) {
    try {
      return await this.delegate.commitExternalTaskResult(args);
    } finally {
      await this.#releaseTask(args.missionId, args.taskId, 'external-task-result-finished').catch(() => {});
    }
  }

  cancelWorker(args) {
    return this.delegate.cancelWorker(args);
  }

  async resumeWorker(args) {
    try {
      return await this.delegate.resumeWorker(args);
    } finally {
      await this.#releaseTask(args.missionId, args.taskId, 'worker-resume-finished').catch(() => {});
    }
  }

  async retryWorker(args) {
    const result = await this.delegate.retryWorker(args);
    await this.#releaseTask(args.missionId, args.taskId, 'worker-retry-scheduled');
    return result;
  }
}
