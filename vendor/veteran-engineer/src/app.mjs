import path from 'node:path';
import { createStateBackend } from './state-backend-factory.mjs';
import { assertStateBackend } from './state-backend-contract.mjs';
import { assertTransactionalStateBackend } from './state-backend-transaction-contract.mjs';
import { assertDurableOutcomeStateBackend, isStateCommitAuditOutcomeUnknown } from './state-backend-durability-contract.mjs';
import { ProjectService } from './project-service.mjs';
import { MissionService } from './mission-service.mjs';
import { MissionExecutionLeaseManager } from './mission-execution-lease.mjs';
import { ExperienceService } from './experience-service.mjs';
import { EvidenceService } from './evidence-service.mjs';
import { WorktreeManager } from './worktree-manager.mjs';
import { WorkerAdapter } from './worker-adapter.mjs';
import { WorkerOrchestrator } from './worker-orchestrator.mjs';
import { FeedbackAwareWorkerOrchestrator } from './feedback-aware-worker-orchestrator.mjs';
import { CapabilityAwareWorkerOrchestrator } from './capability-aware-worker-orchestrator.mjs';
import { ValidationService } from './validation-service.mjs';
import { LiveValidationSessionManager } from './live-validation-session-manager.mjs';
import { RuntimeFeedbackService } from './runtime-feedback-service.mjs';
import { ReviewService } from './review-service.mjs';
import { CandidateService } from './candidate-service.mjs';
import { RuntimeService } from './runtime-service.mjs';
import { HandoffService } from './handoff-service.mjs';
import { MissionAdvanceService } from './mission-advance.mjs';
import { loadOperatorConfig } from './operator-config.mjs';
import { beginRequest, completeRequest, failRequest, markRequestUnknown, replayOrThrow } from './idempotency.mjs';
import { MCP_TRANSPORT_MODES } from './mcp-protocol-capability.mjs';
import { randomId, sha256, stableStringify } from './util.mjs';
import { resolveSurfaceProfile } from './surface-capabilities.mjs';

const MUTATING_TOOLS = new Set([
  'project_open', 'project_snapshot', 'mission_plan', 'mission_execute', 'mission_advance',
  'mission_cancel', 'mission_resume', 'task_result_commit', 'worker_cancel', 'worker_resume',
  'worker_retry', 'validation_run', 'review_run', 'semantic_review_run', 'remediation_plan',
  'candidate_refresh', 'experience_commit', 'experience_review', 'experience_challenge',
  'experience_compact', 'runtime_cleanup', 'runtime_maintenance', 'handoff_export'
]);

function requestOutcomeUnknown(requestId, cause) {
  const error = new Error('Mutation may have committed but its durable audit outcome requires reconciliation; the request will not be replayed blindly.');
  error.code = 'REQUEST_OUTCOME_UNKNOWN';
  error.details = {
    requestId,
    stateCommitId: cause?.details?.stateCommitId || null,
    causeCode: cause?.code || 'ERROR'
  };
  error.cause = cause;
  return error;
}

async function tryReconcileStateCommit(store) {
  try {
    await store.reconcilePendingAudit();
    return true;
  } catch {
    return false;
  }
}

function assertAppStateBackend(backend) {
  return assertDurableOutcomeStateBackend(assertTransactionalStateBackend(assertStateBackend(backend)));
}

export async function createVeteranApp({
  stateRoot,
  stateBackend = null,
  stateBackendConfig = null,
  stateBackendEnv = process.env,
  protocolMode = MCP_TRANSPORT_MODES.STANDALONE_FALLBACK,
  surfaceProfile = process.env.VETERAN_ENGINEER_SURFACE_PROFILE || 'local-stdio',
  configPath
} = {}) {
  if (!stateRoot) throw new Error('stateRoot is required');
  const resolvedSurfaceProfile = resolveSurfaceProfile(surfaceProfile);
  const backend = stateBackend || createStateBackend({
    stateRoot: path.resolve(stateRoot),
    config: stateBackendConfig,
    env: stateBackendEnv
  });
  assertAppStateBackend(backend);
  const store = assertAppStateBackend(await backend.init());
  const { config: operatorConfig, path: operatorConfigPath } = await loadOperatorConfig({ stateRoot, configPath });
  const projectService = new ProjectService({
    store,
    operatorConfig,
    managedProjectsRoot: path.join(path.resolve(stateRoot), 'projects'),
    surfaceProfile: resolvedSurfaceProfile
  });
  const evidenceService = new EvidenceService({ store });
  const experienceService = new ExperienceService({ store });
  const missionService = new MissionService({ store, projectService, experienceService, evidenceService });
  const missionExecutionLeaseManager = new MissionExecutionLeaseManager({ store });
  const worktreeManager = new WorktreeManager({ store });
  const workerAdapter = new WorkerAdapter();
  const liveSessionManager = new LiveValidationSessionManager({ store });
  const coreWorkerOrchestrator = new WorkerOrchestrator({ store, projectService, missionService, worktreeManager, workerAdapter, evidenceService, experienceService });
  const validationService = new ValidationService({ store, projectService, missionService, worktreeManager, evidenceService, liveSessionManager });
  const runtimeFeedbackService = new RuntimeFeedbackService({ store, projectService, missionService, validationService, evidenceService });
  const feedbackWorkerOrchestrator = new FeedbackAwareWorkerOrchestrator({ delegate: coreWorkerOrchestrator, missionService, runtimeFeedbackService, validationService });
  const workerOrchestrator = new CapabilityAwareWorkerOrchestrator({ delegate: feedbackWorkerOrchestrator, store, projectService, missionService, worktreeManager });
  const reviewService = new ReviewService({ store, projectService, missionService, worktreeManager, evidenceService, experienceService });
  const candidateService = new CandidateService({ store, projectService, missionService, worktreeManager, evidenceService });
  const runtimeService = new RuntimeService({ store, experienceService, protocolMode, surfaceProfile: resolvedSurfaceProfile });
  const handoffService = new HandoffService({ store, missionService });
  const missionAdvanceService = new MissionAdvanceService({ store, projectService, missionService, worktreeManager, workerOrchestrator, validationService, reviewService, candidateService, evidenceService });
  const activeMissionExecutions = new Map();

  async function withMissionExecutionLease(args, operation, handler) {
    const missionId = args?.missionId;
    const executionLease = await missionExecutionLeaseManager.acquire({ missionId, operation });
    try {
      return await handler();
    } finally {
      await executionLease.release();
    }
  }

  async function executeMission(args) {
    const missionId = args?.missionId;
    return withMissionExecutionLease(args, 'mission-execute', async () => {
      const current = await missionService.status({ missionId });
      if (current.mission.status === 'cancelled') {
        throw Object.assign(new Error('Cancelled missions cannot execute'), { code: 'MISSION_CANCELLED' });
      }
      if (current.mission.interruption?.requiresReconciliation) {
        throw Object.assign(new Error('Mission requires interruption reconciliation before execution'), { code: 'RECONCILIATION_REQUIRED' });
      }
      activeMissionExecutions.set(missionId, (activeMissionExecutions.get(missionId) || 0) + 1);
      try {
        return await workerOrchestrator.execute(args);
      } finally {
        const remaining = (activeMissionExecutions.get(missionId) || 1) - 1;
        if (remaining > 0) activeMissionExecutions.set(missionId, remaining);
        else activeMissionExecutions.delete(missionId);
      }
    });
  }

  async function cancelMission(args) {
    const result = await missionService.cancel(args);
    const workerDrain = workerAdapter.cancelMission(args.missionId);
    const capabilityLeaseReconciliation = await workerOrchestrator.reconcileMission({
      missionId: args.missionId,
      reason: 'mission-cancel'
    });
    const released = await validationService.releaseRuntimeFeedbackSessions({ missionId: args.missionId, reason: 'mission-cancelled' });
    return {
      ...result,
      workerDrain,
      capabilityLeaseReconciliation,
      runtimeFeedbackSessionsReleased: released.length
    };
  }

  async function resumeMission(args) {
    const current = await missionService.status({ missionId: args.missionId });
    if (current.mission.status === 'cancelled') {
      throw Object.assign(new Error('Cancelled missions cannot be resumed'), { code: 'MISSION_CANCELLED' });
    }
    return withMissionExecutionLease(args, 'mission-resume', async () => {
      const activeExecutionCalls = activeMissionExecutions.get(args.missionId) || 0;
      const activeWorkers = workerAdapter.snapshot().filter((item) => item.missionId === args.missionId);
      if (activeExecutionCalls || activeWorkers.length) {
        const error = new Error('Cannot resume a mission while this runtime still owns active execution; cancel it or wait for it to finish before restart reconciliation.');
        error.code = 'MISSION_EXECUTION_ACTIVE';
        error.details = {
          missionId: args.missionId,
          activeExecutionCalls,
          workers: activeWorkers.map((item) => ({ taskId: item.taskId, phase: item.phase, runtimeNamespace: item.runtimeNamespace || null }))
        };
        throw error;
      }
      const result = await missionService.resume(args);
      const capabilityLeaseReconciliation = await workerOrchestrator.reconcileMission({
        missionId: args.missionId,
        reason: 'mission-resume'
      });
      return { ...result, capabilityLeaseReconciliation };
    });
  }

  async function missionReadiness(args) {
    const [readiness, capabilitySnapshot] = await Promise.all([
      missionService.readiness(args),
      workerOrchestrator.snapshot(args)
    ]);
    return { ...readiness, capabilitySnapshot };
  }

  async function cleanupRuntime(args = {}) {
    const before = liveSessionManager.snapshot();
    const browserBefore = validationService.browserSessionManager.snapshot();
    const released = args.apply === true
      ? await validationService.releaseAllRuntimeFeedbackSessions({ reason: 'runtime-cleanup' })
      : { live: [], browser: [] };
    const result = await runtimeService.cleanup(args);
    if (args.apply !== true && before.length) {
      const activeNames = new Set(before.map((session) => session.worktreeName));
      result.orphans = (result.orphans || []).filter((name) => !activeNames.has(name));
    }
    return {
      ...result,
      liveSessions: {
        active: args.apply === true ? liveSessionManager.snapshot() : before,
        released: released.live
      },
      browserSessions: {
        active: args.apply === true ? validationService.browserSessionManager.snapshot() : browserBefore,
        released: released.browser
      }
    };
  }

  const handlers = {
    project_open: (a) => projectService.open(a),
    project_snapshot: (a) => projectService.snapshot(a),
    mission_plan: (a) => missionService.plan(a),
    mission_execute: (a) => executeMission(a),
    mission_status: (a) => missionService.status(a),
    mission_advance: (a) => missionAdvanceService.advance(a),
    mission_readiness: (a) => missionReadiness(a),
    mission_timeline: (a) => missionService.timeline(a),
    mission_cancel: (a) => cancelMission(a),
    mission_resume: (a) => resumeMission(a),
    task_result_commit: (a) => withMissionExecutionLease(a, 'task-result-commit', () => workerOrchestrator.commitExternalTaskResult(a)),
    worker_cancel: (a) => workerOrchestrator.cancelWorker(a),
    worker_resume: (a) => withMissionExecutionLease(a, 'worker-resume', () => workerOrchestrator.resumeWorker(a)),
    worker_retry: (a) => workerOrchestrator.retryWorker(a),
    evidence_query: (a) => evidenceService.query(a),
    validation_capabilities: (a) => validationService.capabilities(a),
    validation_run: (a) => validationService.run(a),
    review_run: (a) => reviewService.deterministic(a),
    semantic_review_run: (a) => reviewService.semantic(a),
    remediation_plan: (a) => reviewService.remediationPlan(a),
    candidate_preflight: (a) => candidateService.preflight(a),
    candidate_refresh: (a) => candidateService.createOrRefresh(a),
    candidate_status: (a) => candidateService.status(a),
    experience_query: (a) => experienceService.query(a),
    experience_commit: (a) => experienceService.commit(a),
    experience_review: (a) => experienceService.review(a),
    experience_challenge: (a) => experienceService.challenge(a),
    experience_audit: (a) => experienceService.audit(a),
    experience_compact: (a) => experienceService.compact(a),
    runtime_health: () => runtimeService.health(),
    runtime_integrity: () => runtimeService.integrity(),
    runtime_cleanup: (a) => cleanupRuntime(a),
    runtime_maintenance: (a) => runtimeService.maintenance(a),
    handoff_export: (a) => handoffService.export(a)
  };

  async function callTool(name, args = {}) {
    const handler = handlers[name];
    if (!handler) throw Object.assign(new Error(`Unknown tool: ${name}`), { code: 'TOOL_NOT_FOUND' });
    if (!MUTATING_TOOLS.has(name)) return handler(args || {});
    const { requestId, ...payload } = args || {};
    const legacyFingerprint = stableStringify(payload);
    const fingerprint = `sha256:${sha256(legacyFingerprint)}`;
    const admissionId = randomId('requestattempt');
    let begin;
    try {
      begin = await beginRequest(store, requestId, name, fingerprint, admissionId, { legacyFingerprints: [legacyFingerprint] });
    } catch (error) {
      if (isStateCommitAuditOutcomeUnknown(error)) {
        const reconciled = await tryReconcileStateCommit(store);
        if (!reconciled) throw requestOutcomeUnknown(requestId, error);
        const state = await store.read();
        const record = state.requests?.[requestId];
        if (!record) throw requestOutcomeUnknown(requestId, error);
        if (record.admissionId === admissionId && record.status === 'started') {
          begin = { replay: false, record };
        } else {
          return replayOrThrow(record);
        }
      } else {
        throw error;
      }
    }
    if (begin.replay) return replayOrThrow(begin.record);

    let result;
    try {
      result = await handler(payload);
    } catch (error) {
      if (isStateCommitAuditOutcomeUnknown(error)) {
        await tryReconcileStateCommit(store);
        await markRequestUnknown(store, requestId, error).catch(() => {});
        throw requestOutcomeUnknown(requestId, error);
      }
      await failRequest(store, requestId, error).catch(() => {});
      throw error;
    }

    try {
      await completeRequest(store, requestId, result);
      return result;
    } catch (error) {
      if (isStateCommitAuditOutcomeUnknown(error)) {
        const reconciled = await tryReconcileStateCommit(store);
        if (reconciled) {
          const state = await store.read();
          if (state.requests?.[requestId]?.status === 'completed') return result;
        }
        await markRequestUnknown(store, requestId, error).catch(() => {});
        throw requestOutcomeUnknown(requestId, error);
      }
      await markRequestUnknown(store, requestId, error).catch(() => {});
      throw requestOutcomeUnknown(requestId, error);
    }
  }

  async function toolContent(name, args = {}, result = null) {
    if (name !== 'evidence_query' || args?.includeImages !== true) return [];
    if (!Array.isArray(args.ids) || args.ids.length === 0) {
      throw Object.assign(new Error('includeImages requires one or more exact evidence ids'), { code: 'EVIDENCE_IMAGE_IDS_REQUIRED' });
    }
    if (args.ids.length > 4) {
      throw Object.assign(new Error('includeImages accepts at most 4 exact evidence ids'), { code: 'EVIDENCE_IMAGE_DELIVERY_LIMIT' });
    }
    const ids = args.ids.map(String);
    if (new Set(ids).size !== ids.length) {
      throw Object.assign(new Error('includeImages requires unique evidence ids'), { code: 'EVIDENCE_IMAGE_IDS_DUPLICATE' });
    }
    if (!Array.isArray(result)) {
      throw Object.assign(new Error('evidence_query must return an array before image projection'), { code: 'EVIDENCE_IMAGE_RESULT_INVALID' });
    }
    const byId = new Map(result.map((record) => [record?.id, record]));
    const records = ids.map((id) => {
      const record = byId.get(id);
      if (!record) {
        throw Object.assign(new Error(`Evidence id was not returned by the query: ${id}`), { code: 'EVIDENCE_IMAGE_EVIDENCE_NOT_FOUND' });
      }
      return record;
    });
    const images = await evidenceService.readQueryImages(records, { maxImages: args.maxImages });
    return images.flatMap((image) => [
      {
        type: 'text',
        text: `Evidence image metadata: ${JSON.stringify({ evidenceId: image.evidenceId, attachment: image.attachment, sha256: image.sha256, bytes: image.bytes })}`
      },
      { type: 'image', data: image.data.toString('base64'), mimeType: image.mimeType }
    ]);
  }

  return {
    store,
    services: { projectService, missionService, missionExecutionLeaseManager, evidenceService, experienceService, worktreeManager, workerAdapter, liveSessionManager, coreWorkerOrchestrator, feedbackWorkerOrchestrator, workerOrchestrator, validationService, runtimeFeedbackService, reviewService, candidateService, runtimeService, handoffService, missionAdvanceService },
    handlers,
    callTool,
    toolContent,
    operatorConfigPath,
    setProtocolMode: (mode) => runtimeService.setProtocolMode(mode)
  };
}
