import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { RUNTIME_NAME, RUNTIME_VERSION, STATE_SCHEMA_VERSION } from './constants.mjs';
import { git } from './git.mjs';
import { protocolCapability, MCP_TRANSPORT_MODES } from './mcp-protocol-capability.mjs';
import { TOOL_NAMES } from './tool-catalog.mjs';
import { nowIso, pathExists } from './util.mjs';
import { inspectMcpSdkIntegrity } from './mcp-sdk-integrity.mjs';
import { resolveSurfaceProfile } from './surface-capabilities.mjs';

const defaultRuntimeRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CANDIDATE_REF_PREFIX = 'refs/veteran/candidates/';
const CANDIDATE_PRODUCING_OPERATIONS = new Set(['candidate_refresh', 'mission_advance']);
const WORKTREE_MUTATING_OPERATIONS = new Set(['mission_execute', 'validation_run']);

function directRuntimeWorktreeName(worktreesDir, worktreePath) {
  if (!worktreePath) return null;
  const root = path.resolve(worktreesDir);
  const resolved = path.resolve(String(worktreePath));
  if (path.dirname(resolved) !== root) return null;
  return path.basename(resolved);
}

function requestBlockers(state, operations) {
  return Object.values(state.requests || {})
    .filter((request) => operations.has(request.operation) && ['started', 'unknown'].includes(request.status))
    .map((request) => ({ requestId: request.requestId, operation: request.operation, status: request.status }))
    .sort((a, b) => a.requestId.localeCompare(b.requestId));
}

function candidateMutationBlockers(state) {
  return requestBlockers(state, CANDIDATE_PRODUCING_OPERATIONS);
}

function worktreeMutationBlockers(state) {
  return requestBlockers(state, WORKTREE_MUTATING_OPERATIONS);
}

function referencedWorktreeNames(state, worktreesDir) {
  const referenced = new Set();
  for (const mission of Object.values(state.missions || {})) {
    if (!['completed', 'cancelled'].includes(mission.status)) referenced.add(`mission-${mission.id}`);
  }
  for (const task of Object.values(state.tasks || {})) {
    if (['done', 'cancelled', 'superseded'].includes(task.status)) continue;
    for (const dispatch of task.dispatches || []) {
      const name = directRuntimeWorktreeName(worktreesDir, dispatch.worktreePath);
      if (name) referenced.add(name);
    }
  }
  for (const lease of Object.values(state.runtime?.liveValidationLeases?.sessions || {})) {
    if (lease?.worktreeName) referenced.add(lease.worktreeName);
  }
  return referenced;
}

function candidateOwner(state, projectId, ref) {
  return Object.values(state.runtime?.candidates || {}).find((candidate) => candidate.projectId === projectId && candidate.ref === ref) || null;
}

async function listCandidateRefs(project) {
  const result = await git(project.repoPath, ['for-each-ref', '--format=%(refname) %(objectname)', CANDIDATE_REF_PREFIX], { allowFailure: true });
  if (result.code !== 0) {
    return {
      refs: [],
      error: {
        projectId: project.id,
        code: 'CANDIDATE_REF_SCAN_FAILED',
        message: `${result.stderr || result.stdout || 'git for-each-ref failed'}`.trim().slice(0, 2000)
      }
    };
  }
  const refs = result.stdout.trim()
    ? result.stdout.trim().split(/\r?\n/).map((line) => {
      const separator = line.indexOf(' ');
      return separator > 0 ? { ref: line.slice(0, separator), commitSha: line.slice(separator + 1).trim() } : null;
    }).filter(Boolean)
    : [];
  return { refs, error: null };
}

export class RuntimeService {
  constructor({ store, experienceService, protocolMode = MCP_TRANSPORT_MODES.STANDALONE_FALLBACK, runtimeRoot = defaultRuntimeRoot, surfaceProfile = 'local-stdio' }) {
    this.store = store;
    this.experienceService = experienceService;
    this.protocolMode = protocolMode;
    this.runtimeRoot = runtimeRoot;
    this.surfaceProfile = resolveSurfaceProfile(surfaceProfile);
  }

  setProtocolMode(mode) {
    this.protocolMode = mode;
  }

  async health() {
    const state = await this.store.read();
    const audit = await this.store.verifyAudit();
    return {
      name: RUNTIME_NAME,
      version: RUNTIME_VERSION,
      stateSchemaVersion: STATE_SCHEMA_VERSION,
      stateRoot: this.store.root,
      stateBackend: {
        kind: this.store.backendKind || 'legacy-state-store',
        contract: this.store.backendContract || null,
        transactionContract: this.store.transactionContract || null,
        durabilityContract: this.store.durabilityContract || null,
        instanceKey: this.store.backendKind === 'postgres' ? this.store.instanceKey : null
      },
      stateReadable: Boolean(state),
      audit: { ok: audit.ok, entries: audit.entries },
      mcp: protocolCapability(this.protocolMode),
      surface: this.surfaceProfile,
      sdk: await inspectMcpSdkIntegrity(this.runtimeRoot),
      toolCount: TOOL_NAMES.length,
      toolSurface: [...TOOL_NAMES],
      at: nowIso()
    };
  }

  async integrity() {
    const issues = [];
    let state;
    try { state = await this.store.read(); } catch (error) { issues.push({ code: 'STATE_UNREADABLE', message: error.message }); }
    const audit = await this.store.verifyAudit();
    if (!audit.ok) issues.push({ code: 'AUDIT_CHAIN_INVALID', details: audit });
    if (state) {
      const started = Object.values(state.requests || {}).filter((request) => request.status === 'started');
      if (started.length) issues.push({ code: 'UNRECONCILED_STARTED_REQUESTS', requestIds: started.map((item) => item.requestId) });
      for (const mission of Object.values(state.missions || {})) {
        if (!state.projects[mission.projectId]) issues.push({ code: 'MISSION_PROJECT_MISSING', missionId: mission.id });
      }
    }
    return { ok: issues.length === 0, audit, issues, toolCount: TOOL_NAMES.length };
  }

  async cleanup({ apply = false } = {}) {
    const state = await this.store.read();
    const referenced = referencedWorktreeNames(state, this.store.worktreesDir);
    const entries = await fs.readdir(this.store.worktreesDir, { withFileTypes: true }).catch(() => []);
    const orphans = entries.filter((entry) => entry.isDirectory() && !referenced.has(entry.name)).map((entry) => entry.name);
    const removed = [];
    const worktrees = {
      blockers: worktreeMutationBlockers(state),
      skipped: [],
      prunedProjects: [],
      pruneErrors: []
    };
    if (apply && worktrees.blockers.length === 0) {
      for (const name of orphans) {
        const latest = await this.store.read();
        const blockers = worktreeMutationBlockers(latest);
        if (blockers.length) {
          worktrees.blockers = blockers;
          break;
        }
        if (referencedWorktreeNames(latest, this.store.worktreesDir).has(name)) {
          worktrees.skipped.push({ name, reason: 'now-referenced' });
          continue;
        }
        await fs.rm(path.join(this.store.worktreesDir, name), { recursive: true, force: true });
        removed.push(name);
      }
    }
    if (apply && worktrees.blockers.length === 0) {
      const latest = await this.store.read();
      for (const project of Object.values(latest.projects || {})) {
        const blockers = worktreeMutationBlockers(await this.store.read());
        if (blockers.length) {
          worktrees.blockers = blockers;
          break;
        }
        if (!project?.id || !project?.repoPath) continue;
        const prune = await git(project.repoPath, ['worktree', 'prune', '--expire', 'now'], { allowFailure: true });
        if (prune.code === 0) {
          worktrees.prunedProjects.push(project.id);
        } else {
          worktrees.pruneErrors.push({
            projectId: project.id,
            code: 'WORKTREE_PRUNE_FAILED',
            message: `${prune.stderr || prune.stdout || 'git worktree prune failed'}`.trim().slice(0, 2000)
          });
        }
      }
    }

    const candidateRefs = {
      blockers: candidateMutationBlockers(state),
      orphans: [],
      mismatches: [],
      scanErrors: [],
      skipped: [],
      removed: []
    };
    for (const project of Object.values(state.projects || {})) {
      if (!project?.id || !project?.repoPath) continue;
      const scanned = await listCandidateRefs(project);
      if (scanned.error) {
        candidateRefs.scanErrors.push(scanned.error);
        continue;
      }
      for (const actual of scanned.refs) {
        const owner = candidateOwner(state, project.id, actual.ref);
        if (!owner) {
          candidateRefs.orphans.push({ projectId: project.id, ref: actual.ref, commitSha: actual.commitSha });
        } else if (owner.commitSha !== actual.commitSha) {
          candidateRefs.mismatches.push({
            projectId: project.id,
            candidateId: owner.id,
            ref: actual.ref,
            expectedCommitSha: owner.commitSha,
            actualCommitSha: actual.commitSha
          });
        }
      }
    }
    candidateRefs.orphans.sort((a, b) => `${a.projectId}:${a.ref}`.localeCompare(`${b.projectId}:${b.ref}`));
    candidateRefs.mismatches.sort((a, b) => `${a.projectId}:${a.ref}`.localeCompare(`${b.projectId}:${b.ref}`));

    if (apply && candidateRefs.blockers.length === 0) {
      for (const orphan of candidateRefs.orphans) {
        const latest = await this.store.read();
        const blockers = candidateMutationBlockers(latest);
        if (blockers.length) {
          candidateRefs.blockers = blockers;
          break;
        }
        const nowOwned = candidateOwner(latest, orphan.projectId, orphan.ref);
        if (nowOwned) {
          candidateRefs.skipped.push({ projectId: orphan.projectId, ref: orphan.ref, reason: 'now-owned' });
          continue;
        }
        const project = latest.projects?.[orphan.projectId];
        if (!project?.repoPath) {
          candidateRefs.skipped.push({ projectId: orphan.projectId, ref: orphan.ref, reason: 'project-unavailable' });
          continue;
        }
        const deletion = await git(project.repoPath, ['update-ref', '-d', orphan.ref, orphan.commitSha], { allowFailure: true });
        if (deletion.code !== 0) {
          const error = new Error(`Failed to remove orphan candidate ref ${orphan.ref}`);
          error.code = 'CANDIDATE_REF_CLEANUP_FAILED';
          error.details = {
            projectId: orphan.projectId,
            ref: orphan.ref,
            expectedCommitSha: orphan.commitSha,
            gitExitCode: deletion.code,
            gitError: `${deletion.stderr || deletion.stdout || ''}`.trim().slice(0, 2000) || null
          };
          throw error;
        }
        candidateRefs.removed.push(orphan);
      }
    }

    return { apply, orphans, removed, worktrees, candidateRefs };
  }

  async maintenance({ projectId = null } = {}) {
    const state = await this.store.read();
    const unknownRequests = Object.values(state.requests || {}).filter((item) => item.status === 'unknown').map((item) => item.requestId);
    const experienceAudit = await this.experienceService.audit({ projectId });
    const backupPresent = this.store.backupPath ? await pathExists(this.store.backupPath) : null;
    const result = { unknownRequests, experienceAudit, backupPresent, at: nowIso() };
    await this.store.transaction('runtime_maintenance', (working) => {
      working.runtime.maintenance.lastRun = result.at;
      working.runtime.maintenance.lastSummary = { unknownRequests: unknownRequests.length, experiences: experienceAudit.length, backupPresent };
    }, { unknownRequests: unknownRequests.length, experiences: experienceAudit.length });
    return result;
  }
}