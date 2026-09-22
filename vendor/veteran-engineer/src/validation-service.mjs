import fs from 'node:fs/promises';
import path from 'node:path';
import { runProcess, git } from './git.mjs';
import { nowIso, randomId } from './util.mjs';
import {
  normalizeProductService,
  startValidationService,
  waitForValidationReadiness,
  stopValidationService
} from './product-validation-runner.mjs';
import { normalizeValidationArtifacts, collectValidationArtifacts } from './validation-artifact-collector.mjs';
import { normalizeBrowserValidation, runBrowserValidation } from './browser-validation-provider.mjs';
import { BrowserValidationSessionManager } from './browser-validation-session-manager.mjs';
import { normalizeElectronValidation, runElectronValidation } from './electron-validation-provider.mjs';
import { CredentialBroker } from './credential-broker.mjs';
import { normalizeObservabilityValidation, runObservabilityValidation } from './observability-validation-provider.mjs';
import { LiveValidationSessionManager } from './live-validation-session-manager.mjs';

const VALIDATION_PURPOSES = new Set(['final-validation', 'runtime-feedback']);
const WORKTREE_ADMIN_TAILS = new Map();

async function withWorktreeAdminLock(repoPath, operation) {
  const key = path.resolve(repoPath);
  const previous = WORKTREE_ADMIN_TAILS.get(key) || Promise.resolve();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const tail = previous.catch(() => {}).then(() => gate);
  WORKTREE_ADMIN_TAILS.set(key, tail);
  await previous.catch(() => {});
  try {
    return await operation();
  } finally {
    release();
    if (WORKTREE_ADMIN_TAILS.get(key) === tail) WORKTREE_ADMIN_TAILS.delete(key);
  }
}

function normalizeCapability(raw) {
  if (!raw || typeof raw !== 'object' || !raw.name) return null;
  const browser = normalizeBrowserValidation(raw.browser);
  const electron = normalizeElectronValidation(raw.electron);
  const observability = normalizeObservabilityValidation(raw.observability);
  const hasCommand = Array.isArray(raw.command) && raw.command.length > 0;
  const modes = [hasCommand, Boolean(browser), Boolean(electron), Boolean(observability)].filter(Boolean).length;
  if (modes === 0) return null;
  if (modes > 1) {
    throw Object.assign(new Error('Validation capability must choose exactly one of command, browser, electron, or observability execution'), { code: 'VALIDATION_CAPABILITY_AMBIGUOUS' });
  }
  const service = normalizeProductService(raw.service);
  if (browser && !browser.baseUrl && !service?.readiness?.url) {
    throw Object.assign(new Error('Browser validation requires browser.baseUrl or service readiness URL'), { code: 'BROWSER_BASE_URL_REQUIRED' });
  }
  return {
    name: String(raw.name),
    description: String(raw.description || ''),
    command: hasCommand ? raw.command.map(String) : null,
    cwd: raw.cwd ? String(raw.cwd) : '.',
    timeoutMs: Number.isFinite(Number(raw.timeoutMs ?? 120_000)) ? Math.max(1000, Number(raw.timeoutMs ?? 120_000)) : 120_000,
    service,
    browser,
    electron,
    observability,
    artifacts: normalizeValidationArtifacts(raw.artifacts)
  };
}

async function resolveWorktreeCwd(worktree, relativeCwd, label = 'Validation') {
  const root = path.resolve(worktree);
  const cwd = path.resolve(root, relativeCwd);
  const realRoot = await fs.realpath(root).catch(() => root);
  const realCwd = await fs.realpath(cwd).catch(() => cwd);
  const relative = path.relative(realRoot, realCwd);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw Object.assign(new Error(`${label} cwd escapes detached worktree`), { code: 'VALIDATION_CWD_ESCAPE' });
  }
  return cwd;
}

function validationArtifact({ result, serviceRun }) {
  const sections = [
    '--- validation stdout ---',
    result?.stdout || '',
    '--- validation stderr ---',
    result?.stderr || ''
  ];
  if (serviceRun) {
    sections.push(
      '--- service stdout ---',
      serviceRun.logs.stdout || '',
      '--- service stderr ---',
      serviceRun.logs.stderr || ''
    );
  }
  return `${sections.join('\n')}\n`;
}

function appendResultError(result, message) {
  return {
    ...result,
    code: result?.code === 0 ? 1 : (result?.code ?? 1),
    stderr: [result?.stderr || '', message].filter(Boolean).join('\n')
  };
}

function browserFallbackSession(attempt, liveSession) {
  if (!attempt?.used) {
    return liveSession
      ? { mode: 'ephemeral', active: false, reason: attempt?.reason || 'browser-session-disabled' }
      : { mode: 'ephemeral', active: false, reason: 'persistent-live-service-required' };
  }
  return {
    mode: 'ephemeral-fallback',
    active: false,
    fallbackReason: attempt.errorCode || 'BROWSER_SESSION_FAILED',
    fallbackMessage: String(attempt.message || '').slice(0, 500)
  };
}

function normalizedSourceCommitSha(value) {
  if (value === undefined || value === null) return null;
  const normalized = String(value).trim();
  if (!normalized) {
    throw Object.assign(new Error('sourceCommitSha must be a non-empty commit identity'), { code: 'VALIDATION_SOURCE_IDENTITY_INVALID' });
  }
  return normalized;
}

export class ValidationService {
  constructor({
    store,
    projectService,
    missionService,
    worktreeManager,
    evidenceService,
    credentialBroker = null,
    liveSessionManager = null,
    browserSessionManager = null
  }) {
    this.store = store;
    this.projectService = projectService;
    this.missionService = missionService;
    this.worktreeManager = worktreeManager;
    this.evidenceService = evidenceService;
    this.credentialBroker = credentialBroker || new CredentialBroker();
    this.liveSessionManager = liveSessionManager || new LiveValidationSessionManager({ store });
    this.browserSessionManager = browserSessionManager || new BrowserValidationSessionManager();
  }

  async capabilities({ projectId }) {
    const project = await this.projectService.get(projectId);
    return (project.validationCapabilities || []).map(normalizeCapability).filter(Boolean);
  }

  async releaseRuntimeFeedbackSessions({ missionId, reason = 'mission-finished' } = {}) {
    const browserReleased = await this.browserSessionManager.releaseMission({ missionId, reason });
    const liveReleased = await this.liveSessionManager.releaseMission({ missionId, reason });
    liveReleased.browserSessionsReleased = browserReleased.length;
    return liveReleased;
  }

  async releaseAllRuntimeFeedbackSessions({ reason = 'runtime-cleanup' } = {}) {
    const browser = await this.browserSessionManager.releaseAll({ reason });
    const live = await this.liveSessionManager.releaseAll({ reason });
    return { browser, live };
  }

  async run({
    projectId,
    missionId = null,
    candidateId = null,
    capability,
    rawCommand = null,
    confirmRawValidation = false,
    purpose = 'final-validation',
    targetCommitSha = null,
    sourceCommitSha = null,
    recordMissionValidation = true
  }) {
    if (!VALIDATION_PURPOSES.has(purpose)) {
      throw Object.assign(new Error(`Unknown validation purpose: ${purpose}`), { code: 'VALIDATION_PURPOSE_INVALID' });
    }
    if (purpose === 'runtime-feedback' && (!missionId || candidateId || rawCommand)) {
      throw Object.assign(new Error('Runtime feedback requires a mission capability and does not accept candidate or raw-command overrides'), { code: 'RUNTIME_FEEDBACK_SCOPE_INVALID' });
    }
    if (purpose !== 'runtime-feedback' && targetCommitSha) {
      throw Object.assign(new Error('targetCommitSha is reserved for runtime feedback'), { code: 'VALIDATION_TARGET_OVERRIDE_BLOCKED' });
    }
    if (sourceCommitSha !== null && purpose !== 'final-validation') {
      throw Object.assign(new Error('sourceCommitSha is reserved for final validation snapshot execution'), { code: 'VALIDATION_SOURCE_OVERRIDE_BLOCKED' });
    }
    if (typeof recordMissionValidation !== 'boolean') {
      throw Object.assign(new Error('recordMissionValidation must be boolean'), { code: 'VALIDATION_RECORDING_MODE_INVALID' });
    }
    const anchoredCommitSha = normalizedSourceCommitSha(sourceCommitSha);

    const project = await this.projectService.get(projectId);
    const caps = await this.capabilities({ projectId });
    let selected = caps.find((item) => item.name === capability) || null;
    if (rawCommand) {
      if (!project.workerPolicy?.allowRawValidation || confirmRawValidation !== true) {
        const error = new Error('Raw validation requires operator allowRawValidation plus explicit confirmRawValidation=true');
        error.code = 'RAW_VALIDATION_NOT_ALLOWED';
        throw error;
      }
      if (!Array.isArray(rawCommand) || rawCommand.length === 0) throw new Error('rawCommand must be a non-empty argv array');
      selected = { name: 'raw', description: 'Explicit raw validation', command: rawCommand.map(String), cwd: '.', timeoutMs: 120_000, service: null, browser: null, electron: null, observability: null, artifacts: [] };
    }
    if (!selected) throw Object.assign(new Error(`Unknown validation capability: ${capability}`), { code: 'VALIDATION_CAPABILITY_NOT_FOUND' });

    let commitSha;
    let mission = null;
    let validationMissionId = null;
    if (purpose === 'runtime-feedback') {
      const status = await this.missionService.status({ missionId });
      mission = status.mission;
      if (mission.projectId !== projectId) {
        throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      }
      const missionWt = await this.worktreeManager.ensureMissionWorktree(project, mission);
      const missionHead = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
      const allowedCommits = new Set([missionHead, ...status.tasks.map((task) => task.integrationSha).filter(Boolean)]);
      commitSha = targetCommitSha ? String(targetCommitSha).trim() : missionHead;
      if (!allowedCommits.has(commitSha)) {
        throw Object.assign(new Error('Runtime feedback target must be an integrated mission source identity'), {
          code: 'RUNTIME_FEEDBACK_TARGET_INVALID',
          details: { targetCommitSha: commitSha, missionHead }
        });
      }
    } else if (candidateId) {
      const state = await this.store.read();
      const candidate = state.runtime.candidates?.[candidateId];
      const candidateMission = candidate ? state.missions[candidate.missionId] : null;
      if (!candidate || candidate.projectId !== projectId || !candidateMission || candidateMission.projectId !== projectId || (missionId && missionId !== candidate.missionId)) {
        throw Object.assign(new Error(`Unknown candidate ${candidateId}`), { code: 'CANDIDATE_NOT_FOUND' });
      }
      commitSha = candidate.commitSha;
      mission = candidateMission;
      if (missionId) validationMissionId = candidate.missionId;
    } else if (missionId) {
      ({ mission } = await this.missionService.status({ missionId }));
      if (mission.projectId !== projectId) {
        throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      }
      validationMissionId = mission.id;
      if (anchoredCommitSha) {
        commitSha = anchoredCommitSha;
      } else {
        const missionWt = await this.worktreeManager.ensureMissionWorktree(project, mission);
        commitSha = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
      }
    } else {
      if (anchoredCommitSha) {
        throw Object.assign(new Error('sourceCommitSha requires a mission or candidate validation scope'), { code: 'VALIDATION_SOURCE_SCOPE_INVALID' });
      }
      commitSha = project.sourceIdentity.head;
    }
    if (anchoredCommitSha && commitSha !== anchoredCommitSha) {
      throw Object.assign(new Error('Validation source snapshot does not match the requested commit identity'), {
        code: 'VALIDATION_SOURCE_IDENTITY_MISMATCH',
        details: { expectedCommitSha: anchoredCommitSha, actualCommitSha: commitSha }
      });
    }

    const liveSupport = purpose === 'runtime-feedback' && selected.service
      ? this.liveSessionManager.support({ project, service: selected.service })
      : { enabled: false, reason: purpose === 'runtime-feedback' ? 'validation-service-required' : 'not-runtime-feedback' };
    let wt = null;
    let ownsEphemeralWorktree = false;
    let liveSession = null;
    if (liveSupport.enabled) {
      liveSession = await this.liveSessionManager.acquire({
        project,
        mission,
        capability: selected.name,
        commitSha,
        service: selected.service
      });
      wt = liveSession.worktreePath;
    } else {
      const validationId = randomId('validation');
      wt = path.join(this.store.worktreesDir, `validation-${validationId}`);
      await withWorktreeAdminLock(project.repoPath, () => git(project.repoPath, ['worktree', 'add', '--detach', wt, commitSha]));
      ownsEphemeralWorktree = true;
    }

    let result = { code: 1, signal: null, stdout: '', stderr: '' };
    let serviceRun = liveSession?.serviceRun || null;
    let readiness = liveSession?.readiness || null;
    let cleanup = null;
    let liveSessionFinish = null;
    let liveSourceCheck = null;
    let failureStage = null;
    let browserSummary = null;
    let electronSummary = null;
    let electronAttachments = [];
    let observabilitySummary = null;
    let artifactCollection = { attachments: [], summary: null };
    let artifactCollectionError = null;
    try {
      const cwd = await resolveWorktreeCwd(wt, selected.cwd);
      if (selected.service) {
        if (!liveSession) {
          const serviceCwd = await resolveWorktreeCwd(wt, selected.service.cwd, 'Validation service');
          serviceRun = startValidationService(selected.service, { cwd: serviceCwd });
          readiness = await waitForValidationReadiness(serviceRun, selected.service.readiness);
        }
        if (!readiness?.ready) {
          failureStage = readiness?.reason === 'service-exited' ? 'service-startup' : 'readiness';
          result = {
            code: 1,
            signal: null,
            stdout: '',
            stderr: readiness?.reason === 'service-exited'
              ? 'Validation service exited before readiness was established.'
              : `Validation service did not become ready within ${selected.service.readiness.timeoutMs}ms.`
          };
        } else if (liveSession) {
          liveSourceCheck = await this.liveSessionManager.checkSource({ sessionId: liveSession.sessionId, expectedHead: commitSha });
          if (!liveSourceCheck.ok) {
            failureStage = 'live-session-source-drift';
            result = appendResultError(result, `Persistent live validation source drifted before observation (${liveSourceCheck.reason}).`);
          }
        }
      }
      if (!failureStage) {
        if (selected.observability) {
          try {
            const observabilityCwd = await resolveWorktreeCwd(wt, selected.observability.cwd, 'Observability provider');
            observabilitySummary = await runObservabilityValidation(selected.observability, {
              cwd: observabilityCwd,
              expectedSourceHead: commitSha,
              credentialBroker: this.credentialBroker
            });
            result = {
              code: observabilitySummary.passed ? 0 : 1,
              signal: null,
              stdout: observabilitySummary.summary || '',
              stderr: observabilitySummary.passed ? '' : (observabilitySummary.failureCode || 'Observability validation failed')
            };
            if (!observabilitySummary.passed) failureStage = 'observability-validation';
          } catch (error) {
            observabilitySummary = {
              contract: selected.observability.contract,
              passed: false,
              failureCode: error?.code || 'OBSERVABILITY_VALIDATION_FAILED',
              summary: String(error?.message || error).slice(0, 1000),
              observedSourceHead: null,
              checks: [],
              diagnostics: null
            };
            result = { code: 1, signal: null, stdout: '', stderr: observabilitySummary.failureCode };
            failureStage = 'observability-validation';
          }
        } else if (selected.browser) {
          try {
            const browserCwd = await resolveWorktreeCwd(wt, selected.browser.cwd, 'Browser provider');
            const sessionAttempt = purpose === 'runtime-feedback' && liveSession && selected.browser.session
              ? await this.browserSessionManager.observe({
                  projectId,
                  missionId,
                  capability: selected.name,
                  browser: selected.browser,
                  cwd: browserCwd,
                  serviceReadinessUrl: selected.service?.readiness?.url || null,
                  serviceSessionId: liveSession.sessionId,
                  sourceHead: commitSha
                })
              : { used: false, reason: selected.browser.session ? 'persistent-live-service-required' : 'browser-session-disabled' };
            if (sessionAttempt.used && sessionAttempt.ok) {
              browserSummary = sessionAttempt.result;
            } else {
              browserSummary = await runBrowserValidation(selected.browser, {
                cwd: browserCwd,
                serviceReadinessUrl: selected.service?.readiness?.url || null
              });
              if (purpose === 'runtime-feedback') {
                browserSummary = { ...browserSummary, session: browserFallbackSession(sessionAttempt, liveSession) };
              }
            }
            result = {
              code: browserSummary.passed ? 0 : 1,
              signal: null,
              stdout: browserSummary.summary || '',
              stderr: browserSummary.passed ? '' : (browserSummary.failureCode || 'Browser validation failed')
            };
            if (!browserSummary.passed) failureStage = 'browser-validation';
          } catch (error) {
            browserSummary = {
              contract: selected.browser.contract,
              passed: false,
              failureCode: error?.code || 'BROWSER_VALIDATION_FAILED',
              summary: String(error?.message || error).slice(0, 1000),
              assertions: [],
              currentUrl: null,
              diagnostics: null
            };
            result = { code: 1, signal: null, stdout: '', stderr: browserSummary.failureCode };
            failureStage = 'browser-validation';
          }
        } else if (selected.electron) {
          try {
            const electronCwd = await resolveWorktreeCwd(wt, selected.electron.cwd, 'Electron validation');
            const electronRun = await runElectronValidation(selected.electron, { cwd: electronCwd });
            const { attachments = [], ...summary } = electronRun;
            electronAttachments = attachments;
            electronSummary = summary;
            result = {
              code: electronSummary.passed ? 0 : 1,
              signal: null,
              stdout: electronSummary.summary || '',
              stderr: electronSummary.passed ? '' : (electronSummary.failureCode || 'Electron validation failed')
            };
            if (!electronSummary.passed) failureStage = 'electron-validation';
          } catch (error) {
            electronSummary = {
              contract: selected.electron.contract,
              passed: false,
              failureCode: error?.code || 'ELECTRON_VALIDATION_FAILED',
              summary: String(error?.message || error).slice(0, 1000),
              assertions: [],
              surfaces: { windows: [], webviews: [] },
              diagnostics: null
            };
            result = { code: 1, signal: null, stdout: '', stderr: electronSummary.failureCode };
            failureStage = 'electron-validation';
          }
        } else {
          const [command, ...args] = selected.command;
          result = await runProcess(command, args, { cwd, timeoutMs: selected.timeoutMs, allowFailure: true });
          if (result.code !== 0) failureStage = 'validation-command';
        }
      }
    } finally {
      if (selected.artifacts?.length) {
        try {
          artifactCollection = await collectValidationArtifacts(wt, selected.artifacts);
          if (!artifactCollection.summary.complete && !failureStage) {
            failureStage = 'artifact-collection';
            result = { code: 1, signal: null, stdout: result.stdout || '', stderr: 'Required validation evidence artifacts were not produced.' };
          }
        } catch (error) {
          artifactCollectionError = { code: error?.code || 'VALIDATION_ARTIFACT_COLLECTION_FAILED', message: String(error?.message || error).slice(0, 1000) };
          if (!failureStage) {
            failureStage = 'artifact-collection';
            result = { code: 1, signal: null, stdout: result.stdout || '', stderr: artifactCollectionError.message };
          }
        }
      }
      if (liveSession) {
        const finalSourceCheck = await this.liveSessionManager.checkSource({ sessionId: liveSession.sessionId, expectedHead: commitSha });
        if (!finalSourceCheck.ok) {
          liveSourceCheck = finalSourceCheck;
          failureStage ||= 'live-session-source-drift';
          result = appendResultError(result, `Persistent live validation source drifted during observation (${finalSourceCheck.reason}).`);
        } else if (!liveSourceCheck) {
          liveSourceCheck = finalSourceCheck;
        }
        const keepLive = liveSession.active === true && finalSourceCheck.ok;
        if (!keepLive && selected.browser?.session) {
          await this.browserSessionManager.releaseCapability({
            projectId,
            missionId,
            capability: selected.name,
            reason: finalSourceCheck.ok ? 'live-service-released' : 'source-drift'
          });
        }
        liveSessionFinish = await this.liveSessionManager.finish({
          sessionId: liveSession.sessionId,
          keepAlive: keepLive,
          reason: finalSourceCheck.ok ? null : 'source-drift'
        });
      } else if (serviceRun) {
        cleanup = await stopValidationService(serviceRun, selected.service.shutdownGraceMs);
      }
      if (ownsEphemeralWorktree) {
        await withWorktreeAdminLock(project.repoPath, () => git(project.repoPath, ['worktree', 'remove', '--force', wt], { allowFailure: true }));
        await fs.rm(wt, { recursive: true, force: true });
      }
    }
    const passed = !failureStage && result.code === 0;
    const sessionSummary = selected.service && purpose === 'runtime-feedback'
      ? (liveSession
          ? {
              ...liveSession.summary,
              active: liveSessionFinish?.released !== true && liveSession.active === true,
              sourceCheck: liveSourceCheck,
              released: liveSessionFinish?.released === true,
              releaseReason: liveSessionFinish?.cleanup?.reason || liveSessionFinish?.reason || null
            }
          : { mode: 'ephemeral', reason: liveSupport.reason || 'persistent-session-unavailable' })
      : null;
    const serviceSummary = serviceRun ? {
      configured: true,
      ready: readiness?.ready === true,
      readiness: readiness ? {
        reason: readiness.reason,
        attempts: readiness.attempts,
        elapsedMs: readiness.elapsedMs,
        lastStatus: readiness.lastStatus ?? null,
        lastError: readiness.lastError ?? null
      } : null,
      stdoutTruncated: serviceRun.logs.stdoutTruncated,
      stderrTruncated: serviceRun.logs.stderrTruncated,
      cleanup,
      session: sessionSummary
    } : null;
    const artifactSummary = selected.artifacts?.length ? {
      ...(artifactCollection.summary || { configured: true, complete: false, requiredMissing: false, files: 0, bytes: 0, items: [] }),
      error: artifactCollectionError
    } : null;
    const evidence = await this.evidenceService.record({
      projectId,
      missionId: mission?.id || null,
      type: purpose === 'runtime-feedback' ? 'runtime-feedback-observation' : 'validation',
      summary: { purpose, capability: selected.name, passed, exitCode: result.code, commitSha, failureStage, service: serviceSummary, browser: browserSummary, electron: electronSummary, observability: observabilitySummary, artifacts: artifactSummary },
      sourceIdentity: { head: commitSha },
      artifact: validationArtifact({ result, serviceRun }),
      attachments: [...artifactCollection.attachments, ...electronAttachments],
      metadata: { candidateId, purpose }
    });
    if (validationMissionId && recordMissionValidation) {
      await this.store.transaction('mission_validation_recorded', (state) => {
        const target = state.missions[validationMissionId];
        target.validation.status = passed ? 'passed' : 'failed';
        target.validation.evidenceIds.push(evidence.id);
        target.validation.commitSha = commitSha;
        target.updatedAt = nowIso();
        state.runtime.timeline.push({ type: 'validation_completed', missionId: validationMissionId, at: nowIso(), passed, evidenceId: evidence.id, commitSha });
      }, { missionId: validationMissionId, passed, capability: selected.name, commitSha, failureStage });
    }
    return { purpose, passed, capability: selected.name, commitSha, evidenceId: evidence.id, exitCode: result.code, failureStage, service: serviceSummary, browser: browserSummary, electron: electronSummary, observability: observabilitySummary, artifacts: artifactSummary };
  }
}
