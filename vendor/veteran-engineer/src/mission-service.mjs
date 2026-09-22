import path from 'node:path';
import { RISK_LEVELS } from './constants.mjs';
import {
  allowlistedProcessEnvironment,
  repositorySourceAuthority,
  runProcess,
  sameSourceAuthorityLineage,
  sourceIdentity,
  sourceIdentityFromAuthority,
  withDetachedWorktree,
  writeSetsConflict
} from './git.mjs';
import { normalizeTaskCapabilityContract, runtimeResourcesConflict } from './capability-plane.mjs';
import {
  assessTaskRisk,
  buildProjectContinuitySnapshot,
  compileMissionExecutionStrategy,
  plannerProjectAwareness
} from './adaptive-mission-strategy.mjs';
import { normalizePathList, nowIso, randomId, redactKnownSecrets } from './util.mjs';

const TERMINAL_TASKS = new Set(['done', 'failed', 'cancelled', 'blocked', 'superseded']);
const SUCCESS_TASKS = new Set(['done']);
export const MISSION_PROJECT_TRUTH_CONTRACT = 'veteran-mission-project-truth-v1';

function cloneTruthValue(value) {
  return value == null ? value : structuredClone(value);
}

function snapshotMissionProjectTruth(project, baseSourceIdentity, sourceAuthority, capturedAt) {
  const environmentSourceIdentity = project.environmentSourceIdentity || baseSourceIdentity;
  if (!environmentSourceIdentity?.head || environmentSourceIdentity.head !== baseSourceIdentity.head) {
    const error = new Error('Project environment truth is not bound to the Mission source authority.');
    error.code = 'PROJECT_TRUTH_SOURCE_MISMATCH';
    error.details = {
      missionSourceHead: baseSourceIdentity.head,
      environmentSourceHead: environmentSourceIdentity?.head || null,
      authorityRef: sourceAuthority?.ref || 'HEAD'
    };
    throw error;
  }
  return {
    contract: MISSION_PROJECT_TRUTH_CONTRACT,
    capturedAt,
    sourceIdentity: cloneTruthValue(baseSourceIdentity),
    sourceAuthority: cloneTruthValue(sourceAuthority),
    environmentSourceIdentity: cloneTruthValue(environmentSourceIdentity),
    environmentProfile: cloneTruthValue(project.environmentProfile),
    environmentReadiness: cloneTruthValue(project.environmentReadiness),
    bootstrapPlan: cloneTruthValue(project.bootstrapPlan)
  };
}

function validateTask(raw, index) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error(`tasks[${index}] must be an object`);
  const id = String(raw.id || `T${index + 1}`);
  const dependencies = [...new Set((raw.dependencies || []).map(String))];
  const writeSet = normalizePathList(raw.writeSet || []);
  const capabilityContract = normalizeTaskCapabilityContract(raw, id);
  const validationCapability = raw.validationCapability || null;
  const riskAssessment = assessTaskRisk({
    explicitRisk: raw.risk,
    writeSet,
    validationCapability,
    sensingCapabilities: capabilityContract.sensingCapabilities,
    executionCapabilities: capabilityContract.executionCapabilities,
    coordinationKeys: capabilityContract.coordinationKeys,
    runtimeResources: capabilityContract.runtimeResources
  });
  const risk = riskAssessment.risk;
  if (!RISK_LEVELS.includes(risk)) throw new Error(`Invalid risk level for ${id}: ${risk}`);
  if (!String(raw.contract || '').trim()) throw new Error(`Task ${id} requires a contract`);
  if (!String(raw.owner || '').trim()) throw new Error(`Task ${id} requires an owner/boundary`);
  return {
    id,
    contract: String(raw.contract).trim(),
    owner: String(raw.owner).trim(),
    dependencies,
    writeSet,
    protectedPaths: normalizePathList(raw.protectedPaths || []),
    risk,
    riskAssessment,
    validationCapability,
    worker: raw.worker || 'default',
    notes: raw.notes || null,
    ...capabilityContract
  };
}

function topo(tasks) {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  if (byId.size !== tasks.length) throw new Error('Task IDs must be unique');
  for (const task of tasks) {
    for (const dep of task.dependencies) if (!byId.has(dep)) throw new Error(`Task ${task.id} depends on unknown task ${dep}`);
    if (task.dependencies.includes(task.id)) throw new Error(`Task ${task.id} cannot depend on itself`);
  }
  const indegree = new Map(tasks.map((task) => [task.id, task.dependencies.length]));
  const dependents = new Map(tasks.map((task) => [task.id, []]));
  for (const task of tasks) for (const dep of task.dependencies) dependents.get(dep).push(task.id);
  const order = [];
  const queue = tasks.filter((task) => indegree.get(task.id) === 0).map((task) => task.id).sort();
  while (queue.length) {
    const id = queue.shift();
    order.push(id);
    for (const next of dependents.get(id)) {
      indegree.set(next, indegree.get(next) - 1);
      if (indegree.get(next) === 0) queue.push(next);
    }
    queue.sort();
  }
  if (order.length !== tasks.length) throw Object.assign(new Error('Mission task graph contains a cycle'), { code: 'MISSION_DAG_CYCLE' });
  return order;
}

function waveTasksConflict(left, right) {
  return writeSetsConflict(left.writeSet || [], right.writeSet || [])
    || runtimeResourcesConflict(
      left.runtimeResources || [],
      right.runtimeResources || [],
      { taskId: left.id },
      { taskId: right.id }
    );
}

function directDependentCounts(tasks) {
  const counts = new Map(tasks.map((task) => [task.id, 0]));
  for (const task of tasks) {
    for (const dependency of task.dependencies || []) {
      if (counts.has(dependency)) counts.set(dependency, counts.get(dependency) + 1);
    }
  }
  return counts;
}

function riskRank(task) {
  const index = RISK_LEVELS.indexOf(task.risk);
  return index >= 0 ? index : 0;
}

function compareWaveCandidates(left, right, available, dependentCounts) {
  const conflictDegree = (task) => available.reduce((count, other) => (
    other.id !== task.id && waveTasksConflict(task, other) ? count + 1 : count
  ), 0);
  const leftConflicts = conflictDegree(left);
  const rightConflicts = conflictDegree(right);
  if (leftConflicts !== rightConflicts) return leftConflicts - rightConflicts;
  const leftChildren = dependentCounts.get(left.id) || 0;
  const rightChildren = dependentCounts.get(right.id) || 0;
  if (leftChildren !== rightChildren) return rightChildren - leftChildren;
  const riskDelta = riskRank(left) - riskRank(right);
  if (riskDelta !== 0) return riskDelta;
  return left.id.localeCompare(right.id);
}

export function computeWaves(tasks) {
  const remaining = new Map(tasks.map((task) => [task.id, task]));
  const done = new Set();
  const waves = [];
  const dependentCounts = directDependentCounts(tasks);
  while (remaining.size) {
    const ready = [...remaining.values()].filter((task) => task.dependencies.every((dep) => done.has(dep))).sort((a, b) => a.id.localeCompare(b.id));
    if (!ready.length) throw new Error('Unable to compute mission waves');
    const pending = new Map(ready.map((task) => [task.id, task]));
    const wave = [];
    while (pending.size) {
      const available = [...pending.values()];
      const eligible = available.filter((task) => !wave.some((selected) => waveTasksConflict(selected, task)));
      if (!eligible.length) break;
      eligible.sort((left, right) => compareWaveCandidates(left, right, available, dependentCounts));
      const chosen = eligible[0];
      wave.push(chosen);
      pending.delete(chosen.id);
    }
    if (!wave.length) wave.push(ready[0]);
    const waveIds = wave.map((task) => task.id).sort((left, right) => left.localeCompare(right));
    waves.push(waveIds);
    for (const id of waveIds) {
      remaining.delete(id);
      done.add(id);
    }
  }
  return waves;
}

export class MissionService {
  constructor({ store, projectService, experienceService = null, evidenceService = null }) {
    this.store = store;
    this.projectService = projectService;
    this.experienceService = experienceService;
    this.evidenceService = evidenceService;
  }

  async plan(args = {}) {
    const { projectId, goal, doneDefinition, nonGoals = [], tasks = null } = args;
    const riskEnvelopeSource = Object.prototype.hasOwnProperty.call(args, 'riskEnvelope') && args.riskEnvelope !== undefined
      ? 'explicit'
      : 'default';
    const riskEnvelope = args.riskEnvelope === undefined ? 'medium' : args.riskEnvelope;
    if (!RISK_LEVELS.includes(riskEnvelope)) throw new Error(`Invalid mission risk envelope: ${riskEnvelope}`);
    if (!String(goal || '').trim() || !String(doneDefinition || '').trim()) throw new Error('goal and doneDefinition are required');

    const missionId = randomId('mission');
    const project = await this.projectService.snapshot({ projectId });
    const observed = project.sourceIdentity || await sourceIdentity(project.repoPath);
    const sourceAuthority = project.sourceAuthority || await repositorySourceAuthority(project.repoPath, { observedIdentity: observed });
    const baseSourceIdentity = sourceIdentityFromAuthority(sourceAuthority);
    if (sourceAuthority.scope === 'checkout' && baseSourceIdentity.dirty) {
      const error = new Error('Cannot plan a mission from a dirty checkout when no stronger repository source authority is available.');
      error.code = 'DIRTY_SOURCE_BLOCKED';
      error.details = baseSourceIdentity.dirtyPaths;
      throw error;
    }
    const truthCapturedAt = nowIso();
    const projectTruth = snapshotMissionProjectTruth(project, baseSourceIdentity, sourceAuthority, truthCapturedAt);

    const projectState = await this.store.read();
    const continuity = buildProjectContinuitySnapshot({ state: projectState, projectId, liveHead: baseSourceIdentity.head });
    const experience = this.experienceService
      ? await this.experienceService.route({ projectId, sourceHead: baseSourceIdentity.head, role: 'planner', limit: 8 })
      : { role: 'planner', items: [], excludedConflicts: 0, precedence: 'Current repository/runtime evidence outranks project experience.' };
    let proposedTasks = tasks;
    let plannerEvidenceId = null;
    if (!Array.isArray(proposedTasks) || proposedTasks.length === 0) {
      const provider = project.plannerProvider || null;
      if (!provider?.command) throw new Error('mission requires at least one task or an operator-configured plannerProvider');

      const invokePlanner = async (plannerRepoPath) => {
        const plannerProject = {
          ...project,
          repoPath: plannerRepoPath,
          sourceIdentity: projectTruth.sourceIdentity,
          sourceAuthority: projectTruth.sourceAuthority,
          environmentSourceIdentity: projectTruth.environmentSourceIdentity,
          environmentProfile: projectTruth.environmentProfile,
          environmentReadiness: projectTruth.environmentReadiness,
          bootstrapPlan: projectTruth.bootstrapPlan
        };
        const payload = {
          protocol: 'veteran-planner-v1',
          project: {
            id: project.id,
            repoPath: plannerRepoPath,
            checkoutRepoPath: project.repoPath,
            sourceIdentity: projectTruth.sourceIdentity,
            sourceAuthority: projectTruth.sourceAuthority,
            environmentSourceIdentity: projectTruth.environmentSourceIdentity,
            observedSourceIdentity: observed
          },
          mission: { goal: String(goal).trim(), doneDefinition: String(doneDefinition).trim(), nonGoals: nonGoals.map(String), riskEnvelope, riskEnvelopeSource, projectTruthContract: projectTruth.contract },
          projectAwareness: plannerProjectAwareness(plannerProject, continuity),
          projectExperience: experience.items,
          experiencePrecedence: experience.precedence,
          limits: { maxTasks: 64 }
        };
        const providerEnv = allowlistedProcessEnvironment(provider.envAllowlist || []);
        const providerSecrets = (provider.envAllowlist || [])
          .map((key) => providerEnv[key.trim()])
          .filter((value) => typeof value === 'string' && value.length > 0);
        const result = await runProcess(provider.command, provider.args || [], {
          cwd: plannerRepoPath,
          env: providerEnv,
          inheritEnv: false,
          input: JSON.stringify(payload),
          allowFailure: true,
          timeoutMs: provider.timeoutMs || 180_000
        });
        let parsed = null;
        try { parsed = redactKnownSecrets(JSON.parse(result.stdout), providerSecrets); } catch { }
        const safeStderr = redactKnownSecrets(result.stderr, providerSecrets);
        if (result.code !== 0 || !Array.isArray(parsed?.tasks) || parsed.tasks.length === 0 || parsed.tasks.length > 64) {
          const error = new Error('Planner provider failed or returned an invalid task graph');
          error.code = 'PLANNER_PROVIDER_FAILED';
          error.details = { exitCode: result.code, stderr: safeStderr.slice(0, 2000), taskCount: Array.isArray(parsed?.tasks) ? parsed.tasks.length : null };
          throw error;
        }
        let evidenceId = null;
        if (this.evidenceService) {
          const evidence = await this.evidenceService.record({
            projectId,
            type: 'planner-provider',
            summary: {
              exitCode: result.code,
              taskCount: parsed.tasks.length,
              experienceIds: experience.items.map((item) => item.id),
              activeProjectMissionCount: continuity.activeMissionCount,
              sourceAuthorityScope: sourceAuthority.scope,
              sourceAuthorityRef: sourceAuthority.ref,
              projectTruthContract: projectTruth.contract
            },
            sourceIdentity: baseSourceIdentity,
            artifact: `${JSON.stringify(parsed, null, 2)}\n--- stderr ---\n${safeStderr}`
          });
          evidenceId = evidence.id;
        }
        return { tasks: parsed.tasks, evidenceId };
      };

      const plannerResult = sourceAuthority.scope === 'remote-default' && !sourceAuthority.aligned
        ? await withDetachedWorktree(
          project.repoPath,
          baseSourceIdentity.head,
          path.join(this.store.root, 'planning', missionId),
          invokePlanner
        )
        : await invokePlanner(project.repoPath);
      proposedTasks = plannerResult.tasks;
      plannerEvidenceId = plannerResult.evidenceId;
    }
    if (proposedTasks.length > 64) throw Object.assign(new Error('Mission plan exceeds the 64-task safety bound'), { code: 'MISSION_PLAN_TOO_LARGE' });
    const normalized = proposedTasks.map(validateTask);
    topo(normalized);
    const waves = computeWaves(normalized);
    const strategyProject = {
      ...project,
      sourceIdentity: projectTruth.sourceIdentity,
      sourceAuthority: projectTruth.sourceAuthority,
      environmentSourceIdentity: projectTruth.environmentSourceIdentity,
      environmentProfile: projectTruth.environmentProfile,
      environmentReadiness: projectTruth.environmentReadiness,
      bootstrapPlan: projectTruth.bootstrapPlan
    };
    const executionStrategy = compileMissionExecutionStrategy({ tasks: normalized, waves, project: strategyProject, riskEnvelope, riskEnvelopeSource, continuity });
    const createdAt = truthCapturedAt;
    const mission = {
      id: missionId,
      projectId,
      goal: String(goal).trim(),
      doneDefinition: String(doneDefinition).trim(),
      nonGoals: nonGoals.map(String),
      riskEnvelope,
      executionStrategy,
      projectContinuity: continuity,
      projectTruth,
      baseSourceIdentity: baseSourceIdentity,
      baseSourceAuthority: sourceAuthority,
      observedSourceIdentityAtPlan: observed,
      currentSourceIdentity: baseSourceIdentity,
      status: 'ready',
      phase: 'execution',
      waves,
      nextWaveIndex: 0,
      validation: { status: 'pending', evidenceIds: [] },
      review: { status: 'pending', evidenceIds: [], findings: [] },
      semanticReview: { status: 'pending', evidenceIds: [], findings: [] },
      candidateIds: [],
      activeCandidateId: null,
      mergeProposalIds: [],
      activeMergeProposalId: null,
      interruption: null,
      planningExperience: {
        ids: experience.items.map((item) => item.id),
        excludedConflicts: experience.excludedConflicts,
        precedence: experience.precedence,
        evidenceId: plannerEvidenceId
      },
      createdAt,
      updatedAt: createdAt
    };
    const taskRecords = normalized.map((task) => ({
      ...task,
      key: `${missionId}:${task.id}`,
      missionId,
      projectId,
      status: 'planned',
      attempts: 0,
      dispatches: [],
      commitSha: null,
      integrationSha: null,
      capabilityLease: null,
      evidenceIds: [],
      createdAt,
      updatedAt: createdAt
    }));
    return this.store.transaction('mission_planned', (state) => {
      state.missions[missionId] = mission;
      for (const task of taskRecords) state.tasks[task.key] = task;
      state.runtime.timeline.push({
        type: 'mission_planned',
        missionId,
        at: createdAt,
        baseHead: baseSourceIdentity.head,
        sourceAuthorityScope: sourceAuthority.scope,
        sourceAuthorityRef: sourceAuthority.ref,
        projectTruthContract: projectTruth.contract,
        projectTruthSourceHead: projectTruth.sourceIdentity.head,
        observedHead: observed.head,
        taskClass: executionStrategy.taskClass,
        executionMode: executionStrategy.executionMode,
        activeProjectMissionCount: continuity.activeMissionCount
      });
      return { mission, tasks: taskRecords };
    }, {
      missionId,
      projectId,
      baseHead: baseSourceIdentity.head,
      sourceAuthorityScope: sourceAuthority.scope,
      sourceAuthorityRef: sourceAuthority.ref,
      projectTruthContract: projectTruth.contract,
      projectTruthSourceHead: projectTruth.sourceIdentity.head,
      observedHead: observed.head,
      taskCount: taskRecords.length,
      taskClass: executionStrategy.taskClass,
      executionMode: executionStrategy.executionMode
    });
  }

  async status({ missionId }) {
    const state = await this.store.read();
    const storedMission = state.missions[missionId];
    if (!storedMission) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
    const tasks = Object.values(state.tasks).filter((task) => task.missionId === missionId).sort((a, b) => a.id.localeCompare(b.id));
    const hasExecutionTaskBlocker = storedMission.phase === 'execution'
      && storedMission.status !== 'cancelled'
      && tasks.some((task) => ['failed', 'cancelled', 'interrupted'].includes(task.status));
    const mission = hasExecutionTaskBlocker && storedMission.status !== 'blocked'
      ? { ...storedMission, status: 'blocked' }
      : storedMission;
    const candidates = (mission.candidateIds || []).map((id) => state.runtime.candidates?.[id]).filter(Boolean);
    const mergeProposals = (mission.mergeProposalIds || []).map((id) => state.runtime.mergeProposals?.[id]).filter(Boolean);
    return { mission, tasks, candidates, mergeProposals };
  }

  async readiness({ missionId }) {
    const { mission, tasks, mergeProposals } = await this.status({ missionId });
    const project = await this.projectService.get(mission.projectId);
    const observed = await sourceIdentity(project.repoPath);
    const currentAuthority = mission.baseSourceAuthority
      ? await repositorySourceAuthority(project.repoPath, { observedIdentity: observed })
      : null;
    const authoritativeSource = currentAuthority ? sourceIdentityFromAuthority(currentAuthority) : observed;
    const blockers = [];
    const checkoutIsAuthority = !mission.baseSourceAuthority || mission.baseSourceAuthority.scope === 'checkout';
    if (checkoutIsAuthority && observed.dirty && ['execution', 'candidate', 'finalize'].includes(mission.phase)) {
      blockers.push({ code: 'DIRTY_SOURCE_BLOCKED', details: observed.dirtyPaths });
    }
    if (mission.baseSourceAuthority && !sameSourceAuthorityLineage(mission.baseSourceAuthority, currentAuthority)) {
      blockers.push({
        code: 'SOURCE_AUTHORITY_CHANGED',
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
      });
    }
    if (mission.projectTruth?.sourceIdentity?.head && mission.projectTruth.sourceIdentity.head !== mission.baseSourceIdentity.head) {
      blockers.push({
        code: 'MISSION_PROJECT_TRUTH_CORRUPT',
        projectTruthSourceHead: mission.projectTruth.sourceIdentity.head,
        missionBaseHead: mission.baseSourceIdentity.head
      });
    }
    if (mission.status === 'cancelled') blockers.push({ code: 'MISSION_CANCELLED' });
    const interruptedTaskIds = tasks.filter((task) => task.status === 'interrupted').map((task) => task.id);
    if (mission.interruption?.requiresReconciliation || interruptedTaskIds.length) {
      blockers.push({ code: 'RECONCILIATION_REQUIRED', taskIds: interruptedTaskIds.length ? interruptedTaskIds : (mission.interruption?.taskIds || []) });
    }
    if (mission.phase === 'execution') {
      const outstanding = tasks.filter((task) => ['admitted', 'dispatched', 'executing', 'cancelling'].includes(task.status));
      if (outstanding.length) blockers.push({ code: 'OUTSTANDING_TASKS', taskIds: outstanding.map((task) => task.id) });
      const failed = tasks.filter((task) => task.status === 'failed');
      if (failed.length) blockers.push({ code: 'FAILED_TASKS', taskIds: failed.map((task) => task.id) });
      if (mission.status !== 'cancelled') {
        const cancelled = tasks.filter((task) => task.status === 'cancelled');
        if (cancelled.length) blockers.push({ code: 'CANCELLED_TASKS', taskIds: cancelled.map((task) => task.id) });
      }
    }
    if (mission.phase === 'finalize' && !mission.activeCandidateId) blockers.push({ code: 'CANDIDATE_REQUIRED' });

    const awaitingOperatorMerge = mission.phase === 'finalize' && mission.status === 'awaiting-operator-merge';
    let proposalSourceStale = false;
    if (awaitingOperatorMerge) {
      const proposal = mergeProposals.find((item) => item.id === mission.activeMergeProposalId);
      if (!proposal) {
        blockers.push({ code: 'MERGE_PROPOSAL_REQUIRED', activeMergeProposalId: mission.activeMergeProposalId || null });
      } else if (proposal.status !== 'proposed') {
        blockers.push({ code: 'MERGE_PROPOSAL_NOT_ACTIVE', mergeProposalId: proposal.id, status: proposal.status || null });
      } else if (!proposal.expectedSourceHead) {
        blockers.push({ code: 'MERGE_PROPOSAL_SOURCE_IDENTITY_MISSING', mergeProposalId: proposal.id });
      } else if (proposal.expectedSourceHead !== authoritativeSource.head) {
        proposalSourceStale = true;
        blockers.push({
          code: 'MERGE_PROPOSAL_SOURCE_STALE',
          mergeProposalId: proposal.id,
          expectedSourceHead: proposal.expectedSourceHead,
          liveSourceHead: authoritativeSource.head
        });
      }
    }

    const ready = blockers.length === 0;
    const operatorActionRequired = awaitingOperatorMerge && ready;
    const nextAction = operatorActionRequired
      ? 'operator-merge'
      : (proposalSourceStale && blockers.length === 1 ? 'candidate-refresh' : null);
    return {
      missionId,
      ready,
      phase: mission.phase,
      status: mission.status,
      liveSourceIdentity: observed,
      sourceAuthority: currentAuthority,
      authoritativeSourceIdentity: authoritativeSource,
      projectTruth: mission.projectTruth || null,
      executionStrategy: mission.executionStrategy || null,
      projectContinuity: mission.projectContinuity || null,
      blockers,
      operatorActionRequired,
      nextAction,
      activeMergeProposalId: mission.activeMergeProposalId || null
    };
  }

  async timeline({ missionId }) {
    const state = await this.store.read();
    return state.runtime.timeline.filter((event) => event.missionId === missionId);
  }

  async cancel({ missionId, reason = 'operator-request' }) {
    return this.store.transaction('mission_cancelled', (state) => {
      const mission = state.missions[missionId];
      if (!mission) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      mission.status = 'cancelled';
      mission.updatedAt = nowIso();
      for (const task of Object.values(state.tasks).filter((item) => item.missionId === missionId)) {
        if (!TERMINAL_TASKS.has(task.status)) {
          task.status = task.status === 'executing' ? 'cancelling' : 'cancelled';
          if (task.status === 'cancelled') {
            task.admission = null;
            task.capabilityLease = null;
          }
        }
      }
      state.runtime.timeline.push({ type: 'mission_cancelled', missionId, reason, at: nowIso() });
      return mission;
    }, { missionId, reason });
  }

  async resume({ missionId }) {
    return this.store.transaction('mission_resumed', (state) => {
      const mission = state.missions[missionId];
      if (!mission) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      if (mission.status === 'cancelled') throw Object.assign(new Error('Cancelled missions cannot be resumed'), { code: 'MISSION_CANCELLED' });
      const tasks = Object.values(state.tasks).filter((task) => task.missionId === missionId);
      const recoverableAdmissions = tasks.filter((task) => task.status === 'admitted' && task.admission);
      for (const task of recoverableAdmissions) {
        task.status = 'planned';
        task.admission = null;
        task.updatedAt = nowIso();
      }
      const uncertain = tasks.filter((task) =>
        ['executing', 'cancelling', 'interrupted'].includes(task.status)
        || (task.status === 'admitted' && !task.admission)
      );
      for (const task of uncertain) {
        task.status = 'interrupted';
        task.updatedAt = nowIso();
      }
      mission.interruption = uncertain.length ? {
        requiresReconciliation: true,
        taskIds: uncertain.map((task) => task.id),
        detectedAt: mission.interruption?.detectedAt || nowIso()
      } : null;
      mission.status = uncertain.length ? 'blocked' : 'ready';
      mission.updatedAt = nowIso();
      state.runtime.timeline.push({
        type: 'mission_resume_checked',
        missionId,
        recoveredAdmissionTaskIds: recoverableAdmissions.map((task) => task.id),
        uncertainTaskIds: uncertain.map((task) => task.id),
        at: nowIso()
      });
      return mission;
    }, { missionId });
  }

  static dependenciesSatisfied(task, tasks) {
    const byId = new Map(tasks.map((item) => [item.id, item]));
    return task.dependencies.every((dep) => SUCCESS_TASKS.has(byId.get(dep)?.status));
  }
}
