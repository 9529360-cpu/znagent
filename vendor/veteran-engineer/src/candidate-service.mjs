import {
  git,
  repositorySourceAuthority,
  sameSourceAuthorityLineage,
  sourceIdentity,
  sourceIdentityFromAuthority
} from './git.mjs';
import { isStateCommitAuditOutcomeUnknown } from './state-backend-durability-contract.mjs';
import { nowIso, randomId } from './util.mjs';

function parseMergeTree(stdout) {
  const first = stdout.trim().split(/\r?\n/)[0] || '';
  return /^[0-9a-f]{40,64}$/.test(first) ? first : null;
}

function candidateLifecycleBlockers(mission) {
  const blockers = [];
  if (mission.status === 'cancelled') blockers.push({ code: 'MISSION_CANCELLED' });
  if (mission.interruption?.requiresReconciliation) {
    blockers.push({ code: 'RECONCILIATION_REQUIRED', taskIds: mission.interruption.taskIds || [] });
  }
  return blockers;
}

function assertCandidateMutationAllowed(mission) {
  if (mission.status === 'cancelled') {
    throw Object.assign(new Error('Mission is cancelled'), { code: 'MISSION_CANCELLED' });
  }
  if (mission.interruption?.requiresReconciliation) {
    throw Object.assign(new Error('Mission requires interruption reconciliation before candidate mutation'), {
      code: 'RECONCILIATION_REQUIRED',
      details: { taskIds: mission.interruption.taskIds || [] }
    });
  }
}

function candidateRollbackError(original, cleanup, ref, commitSha) {
  const error = new Error('Candidate state did not commit and the candidate Git ref could not be rolled back safely');
  error.code = 'CANDIDATE_REF_ROLLBACK_FAILED';
  error.details = {
    ref,
    commitSha,
    causeCode: original?.code || null,
    cleanupExitCode: cleanup?.code ?? null,
    cleanupError: `${cleanup?.stderr || cleanup?.stdout || ''}`.trim().slice(0, 2000) || null
  };
  return error;
}

export class CandidateService {
  constructor({ store, projectService, missionService, worktreeManager, evidenceService }) {
    this.store = store;
    this.projectService = projectService;
    this.missionService = missionService;
    this.worktreeManager = worktreeManager;
    this.evidenceService = evidenceService;
  }

  async preflight({ missionId }) {
    const { mission } = await this.missionService.status({ missionId });
    const lifecycleBlockers = candidateLifecycleBlockers(mission);
    const project = await this.projectService.get(mission.projectId);
    const observed = await sourceIdentity(project.repoPath);
    const sourceAuthority = mission.baseSourceAuthority
      ? await repositorySourceAuthority(project.repoPath, { observedIdentity: observed })
      : null;
    if (mission.baseSourceAuthority && !sameSourceAuthorityLineage(mission.baseSourceAuthority, sourceAuthority)) {
      throw Object.assign(new Error('Repository source authority changed after the mission was planned'), {
        code: 'SOURCE_AUTHORITY_CHANGED',
        details: {
          expected: {
            scope: mission.baseSourceAuthority.scope,
            remote: mission.baseSourceAuthority.remote || null,
            ref: mission.baseSourceAuthority.ref || null
          },
          actual: {
            scope: sourceAuthority?.scope || null,
            remote: sourceAuthority?.remote || null,
            ref: sourceAuthority?.ref || null
          }
        }
      });
    }
    const live = sourceAuthority ? sourceIdentityFromAuthority(sourceAuthority) : observed;
    const checkoutIsAuthority = !mission.baseSourceAuthority || mission.baseSourceAuthority.scope === 'checkout';
    if (checkoutIsAuthority && observed.dirty) {
      throw Object.assign(new Error('Dirty source checkout blocks candidate preflight'), { code: 'DIRTY_SOURCE_BLOCKED', details: observed.dirtyPaths });
    }
    const missionWt = await this.worktreeManager.ensureMissionWorktree(project, mission);
    const missionHead = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
    const candidateId = mission.activeCandidateId || null;
    if (live.head === mission.baseSourceIdentity.head) {
      const ready = lifecycleBlockers.length === 0;
      return {
        missionId,
        candidateId,
        ready,
        ok: ready,
        blockers: lifecycleBlockers,
        sourceDrift: false,
        sourceHead: live.head,
        sourceBranch: live.branch,
        sourceAuthority,
        missionHead,
        candidateHead: missionHead,
        mergeTree: null
      };
    }
    const merge = await git(project.repoPath, ['merge-tree', '--write-tree', live.head, missionHead], { allowFailure: true });
    const mergeTree = parseMergeTree(merge.stdout);
    const sourceReady = merge.code === 0 && Boolean(mergeTree);
    const ready = sourceReady && lifecycleBlockers.length === 0;
    return {
      missionId,
      candidateId,
      ready,
      ok: ready,
      blockers: lifecycleBlockers,
      sourceDrift: true,
      sourceHead: live.head,
      sourceBranch: live.branch,
      sourceAuthority,
      missionHead,
      mergeTree,
      conflictOutput: merge.code === 0 ? null : `${merge.stdout}\n${merge.stderr}`.slice(0, 8000)
    };
  }

  async createOrRefresh({ missionId, reason = 'finalize' }) {
    const { mission } = await this.missionService.status({ missionId });
    assertCandidateMutationAllowed(mission);
    const project = await this.projectService.get(mission.projectId);
    const preflight = await this.preflight({ missionId });
    if (!preflight.ok) throw Object.assign(new Error('Candidate preflight is not ready'), { code: 'CANDIDATE_PREFLIGHT_FAILED', details: preflight });
    let commitSha = preflight.missionHead;
    if (preflight.sourceDrift) {
      const message = `Veteran candidate refresh ${missionId}\n\nSource: ${preflight.sourceHead}\nMission: ${preflight.missionHead}`;
      const commit = await git(project.repoPath, ['-c', 'user.name=Veteran Engineer Runtime', '-c', 'user.email=veteran-engineer@local.invalid', 'commit-tree', preflight.mergeTree, '-p', preflight.sourceHead, '-p', preflight.missionHead, '-m', message]);
      commitSha = commit.stdout.trim();
    }
    const candidateId = randomId('candidate');
    const ref = `refs/veteran/candidates/${candidateId}`;
    const candidate = {
      id: candidateId,
      projectId: project.id,
      missionId,
      commitSha,
      ref,
      sourceHead: preflight.sourceHead,
      sourceBranch: preflight.sourceBranch || null,
      sourceAuthority: preflight.sourceAuthority || null,
      missionHead: preflight.missionHead,
      sourceDrift: preflight.sourceDrift,
      reason,
      immutable: true,
      proof: {
        validation: preflight.sourceDrift ? 'stale' : mission.validation.status,
        review: preflight.sourceDrift ? 'stale' : mission.review.status,
        semanticReview: preflight.sourceDrift ? 'stale' : mission.semanticReview.status
      },
      createdAt: nowIso()
    };
    const evidence = this.evidenceService.prepareMetadataRecord({
      projectId: project.id,
      missionId,
      type: 'candidate',
      summary: candidate,
      sourceIdentity: { head: commitSha }
    });

    let refCreated = false;
    try {
      await git(project.repoPath, ['update-ref', ref, commitSha, '0000000000000000000000000000000000000000']);
      refCreated = true;
      await this.store.transaction('candidate_created', (state) => {
        const target = state.missions[missionId];
        assertCandidateMutationAllowed(target);
        this.evidenceService.attachPreparedRecord(state, evidence);
        state.runtime.candidates ||= {};
        state.runtime.candidates[candidateId] = candidate;
        if (target.activeMergeProposalId) {
          const prior = state.runtime.mergeProposals?.[target.activeMergeProposalId];
          if (prior && prior.status === 'proposed') {
            prior.status = 'superseded';
            prior.supersededAt = nowIso();
            prior.supersededByCandidateId = candidateId;
          }
          target.activeMergeProposalId = null;
        }
        target.candidateIds.push(candidateId);
        target.activeCandidateId = candidateId;
        target.updatedAt = nowIso();
        if (preflight.sourceDrift) {
          target.phase = 'validation';
          target.status = 'ready';
          target.validation = { status: 'pending', evidenceIds: [], commitSha };
          target.review = { status: 'pending', evidenceIds: [], findings: [], commitSha };
          target.semanticReview = { status: 'pending', evidenceIds: [], findings: [], commitSha };
          target.currentSourceIdentity = { ...target.currentSourceIdentity, head: preflight.sourceHead, branch: preflight.sourceBranch || null, dirty: false, dirtyPaths: [] };
        } else {
          target.phase = 'candidate';
          target.status = 'candidate-ready';
        }
        state.runtime.timeline.push({ type: preflight.sourceDrift ? 'candidate_refreshed' : 'candidate_created', missionId, candidateId, commitSha, sourceHead: preflight.sourceHead, at: nowIso() });
      }, { missionId, candidateId, commitSha, sourceDrift: preflight.sourceDrift, evidenceId: evidence.id });
      return { candidate, evidenceId: evidence.id, requiresRevalidation: preflight.sourceDrift };
    } catch (error) {
      if (refCreated && !isStateCommitAuditOutcomeUnknown(error)) {
        const cleanup = await git(project.repoPath, ['update-ref', '-d', ref, commitSha], { allowFailure: true });
        if (cleanup.code !== 0) throw candidateRollbackError(error, cleanup, ref, commitSha);
      }
      throw error;
    }
  }

  async status({ missionId, candidateId }) {
    const state = await this.store.read();
    const mission = state.missions[missionId];
    if (!mission) throw Object.assign(new Error(`Unknown mission ${missionId}`), { code: 'MISSION_NOT_FOUND' });
    const id = candidateId || mission.activeCandidateId;
    if (!id) return { missionId, candidate: null };
    const candidate = state.runtime.candidates?.[id];
    if (!candidate || candidate.missionId !== missionId) {
      throw Object.assign(new Error(`Unknown candidate ${id}`), { code: 'CANDIDATE_NOT_FOUND' });
    }
    return { missionId, candidate };
  }
}
