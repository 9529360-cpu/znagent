import { nowIso, randomId } from './util.mjs';
import { git } from './git.mjs';
import { planValidationBatches, validationCapabilitiesCanRunTogether } from './validation-scheduler.mjs';

function proofFreshForCandidate(mission, candidate) {
  return ['passed', 'skipped'].includes(mission.validation.status)
    && mission.review.status === 'passed'
    && ['passed', 'skipped'].includes(mission.semanticReview.status)
    && mission.validation.commitSha === candidate.commitSha
    && mission.review.commitSha === candidate.commitSha
    && mission.semanticReview.commitSha === candidate.commitSha;
}

function proposalMatches(proposal, { missionId, candidate, preflight }) {
  return proposal
    && proposal.status === 'proposed'
    && proposal.missionId === missionId
    && proposal.candidateId === candidate.id
    && proposal.candidateCommitSha === candidate.commitSha
    && proposal.expectedSourceHead === preflight.sourceHead
    && proposal.missionHead === preflight.missionHead;
}

function conciseError(error) {
  return {
    code: error?.code || 'VALIDATION_EXECUTION_ERROR',
    message: String(error?.message || error || 'Validation execution failed').slice(0, 1000)
  };
}

function assertAdvanceMutationAuthority(mission) {
  if (!mission) throw Object.assign(new Error('Mission no longer exists'), { code: 'MISSION_NOT_FOUND' });
  if (mission.status === 'cancelled') throw Object.assign(new Error('Mission is cancelled'), { code: 'MISSION_CANCELLED' });
  if (mission.interruption?.requiresReconciliation) {
    throw Object.assign(new Error('Mission requires interruption reconciliation before advance'), { code: 'RECONCILIATION_REQUIRED' });
  }
}

function validationTierQueues(plan) {
  const tiers = new Map();
  for (const batch of plan.batches) {
    if (!tiers.has(batch.tier)) tiers.set(batch.tier, []);
    tiers.get(batch.tier).push(...batch.capabilities);
  }
  return [...tiers.entries()]
    .sort((left, right) => left[0] - right[0])
    .map(([tier, capabilities]) => ({ tier, capabilities }));
}

export class MissionAdvanceService {
  constructor({ store, projectService, missionService, worktreeManager, workerOrchestrator, validationService, reviewService, candidateService, evidenceService }) {
    Object.assign(this, { store, projectService, missionService, worktreeManager, workerOrchestrator, validationService, reviewService, candidateService, evidenceService });
  }

  async ensureMergeProposalEvidence({ proposal, project, preflight }) {
    if (proposal.evidenceId) return proposal;
    const evidence = await this.evidenceService.record({
      projectId: project.id,
      missionId: proposal.missionId,
      type: 'merge-proposal',
      summary: proposal,
      sourceIdentity: { head: preflight.sourceHead, branch: preflight.sourceBranch || null, dirty: false, dirtyPaths: [] }
    });
    return this.store.transaction('mission_finalize_evidence_attached', (state) => {
      const stored = state.runtime.mergeProposals?.[proposal.id];
      if (!stored) throw Object.assign(new Error(`Unknown merge proposal ${proposal.id}`), { code: 'MERGE_PROPOSAL_NOT_FOUND' });
      if (!stored.evidenceId) stored.evidenceId = evidence.id;
      return stored;
    }, { missionId: proposal.missionId, proposalId: proposal.id, evidenceId: evidence.id });
  }

  async validationCommitSha({ project, mission, candidateId }) {
    if (candidateId) {
      const state = await this.store.read();
      const candidate = state.runtime.candidates?.[candidateId];
      if (!candidate || candidate.projectId !== project.id || candidate.missionId !== mission.id || !candidate.commitSha) {
        throw Object.assign(new Error(`Unknown candidate ${candidateId}`), { code: 'CANDIDATE_NOT_FOUND' });
      }
      return candidate.commitSha;
    }
    const missionWt = await this.worktreeManager.ensureMissionWorktree(project, mission);
    const commitSha = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
    if (!commitSha) throw Object.assign(new Error('Mission validation requires a concrete source commit'), { code: 'VALIDATION_SOURCE_IDENTITY_MISSING' });
    return commitSha;
  }

  async validationExecutionFailure({ project, missionId, capability, commitSha, error }) {
    const failure = conciseError(error);
    let evidenceId = null;
    let evidenceError = null;
    try {
      const evidence = await this.evidenceService.record({
        projectId: project.id,
        missionId,
        type: 'validation',
        summary: {
          purpose: 'final-validation',
          capability,
          passed: false,
          commitSha,
          failureStage: 'validation-execution-error',
          error: failure
        },
        sourceIdentity: { head: commitSha },
        metadata: { capability, scheduler: 'mission-validation' }
      });
      evidenceId = evidence.id;
    } catch (recordError) {
      evidenceError = conciseError(recordError);
    }
    return {
      purpose: 'final-validation',
      passed: false,
      capability,
      commitSha,
      evidenceId,
      exitCode: null,
      failureStage: 'validation-execution-error',
      error: failure,
      evidenceError
    };
  }

  async runValidationCapability({ project, missionId, candidateId, capability, commitSha }) {
    try {
      const result = await this.validationService.run({
        projectId: project.id,
        missionId,
        candidateId,
        capability,
        sourceCommitSha: commitSha,
        recordMissionValidation: false
      });
      if (result.commitSha !== commitSha) {
        throw Object.assign(new Error(`Validation ${capability} observed ${result.commitSha || 'no commit'} instead of ${commitSha}`), {
          code: 'VALIDATION_SOURCE_IDENTITY_MISMATCH',
          details: { capability, expectedCommitSha: commitSha, actualCommitSha: result.commitSha || null }
        });
      }
      return result;
    } catch (error) {
      return this.validationExecutionFailure({ project, missionId, capability, commitSha, error });
    }
  }

  async runValidationPlan({ project, mission, candidateId, required, commitSha }) {
    const catalog = project.validationCapabilities || [];
    const plan = planValidationBatches({
      required,
      catalog,
      maxParallel: project.validationPolicy?.maxParallel,
      projectId: project.id,
      missionId: mission.id
    });
    const resultByCapability = new Map();
    const requiredOrder = new Map(required.map((capability, index) => [capability, index]));
    const batchIndexByCapability = new Map();
    plan.batches.forEach((batch, batchIndex) => {
      for (const capability of batch.capabilities) batchIndexByCapability.set(capability, batchIndex);
    });
    let stoppedAfterBatch = null;

    for (const tier of validationTierQueues(plan)) {
      const pending = [...tier.capabilities];
      const active = new Map();
      const completed = [];
      let wake = null;
      let failed = false;

      const notifyCompletion = (entry) => {
        completed.push(entry);
        if (wake) {
          const resolve = wake;
          wake = null;
          resolve();
        }
      };
      const canAdmit = (capability) => validationCapabilitiesCanRunTogether({
        capabilities: [...active.keys(), capability],
        catalog,
        projectId: project.id,
        missionId: mission.id
      });
      const admit = () => {
        if (failed) return;
        while (active.size < plan.maxParallel && pending.length) {
          const pendingIndex = pending.findIndex((capability) => canAdmit(capability));
          if (pendingIndex < 0) break;
          const [capability] = pending.splice(pendingIndex, 1);
          const execution = this.runValidationCapability({
            project,
            missionId: mission.id,
            candidateId,
            capability,
            commitSha
          }).then((result) => notifyCompletion({ capability, result }));
          active.set(capability, execution);
        }
      };

      admit();
      while (active.size) {
        if (!completed.length) await new Promise((resolve) => { wake = resolve; });
        const ready = completed.splice(0)
          .sort((left, right) => requiredOrder.get(left.capability) - requiredOrder.get(right.capability));
        for (const { capability, result } of ready) {
          active.delete(capability);
          resultByCapability.set(result.capability, result);
        }
        const failures = ready.filter(({ result }) => !result.passed);
        if (failures.length) {
          failed = true;
          stoppedAfterBatch = Math.min(...failures.map(({ capability }) => batchIndexByCapability.get(capability) ?? plan.batches.length));
        }
        if (!failed) admit();
      }
      if (failed) break;
    }

    const results = required.filter((capability) => resultByCapability.has(capability)).map((capability) => resultByCapability.get(capability));
    const deferredCapabilities = required.filter((capability) => !resultByCapability.has(capability));
    return { plan, results, deferredCapabilities, stoppedAfterBatch };
  }

  async persistValidationAggregate({ missionId, required, commitSha, results, passed }) {
    const evidenceIds = results.map((result) => result.evidenceId).filter(Boolean);
    const transactionName = passed ? 'mission_validation_passed' : 'mission_validation_failed';
    await this.store.transaction(transactionName, (state) => {
      const target = state.missions[missionId];
      assertAdvanceMutationAuthority(target);
      const previous = target.validation || {};
      const previousEvidenceIds = previous.commitSha === commitSha && Array.isArray(previous.evidenceIds) ? previous.evidenceIds : [];
      target.validation = {
        ...previous,
        status: passed ? 'passed' : 'failed',
        evidenceIds: [...new Set([...previousEvidenceIds, ...evidenceIds])],
        commitSha
      };
      target.phase = passed ? 'review' : 'validation';
      target.status = 'ready';
      target.updatedAt = nowIso();
      state.runtime.timeline.push({
        type: transactionName,
        missionId,
        commitSha,
        capabilities: required,
        executedCapabilities: results.map((result) => result.capability),
        evidenceIds,
        at: nowIso()
      });
    }, { missionId, commitSha, capabilities: required, executedCapabilities: results.map((result) => result.capability), evidenceIds });
  }

  async advance({ missionId, runWorkers = false }) {
    const { mission } = await this.missionService.status({ missionId });
    assertAdvanceMutationAuthority(mission);
    if (mission.phase === 'execution') {
      const result = await this.workerOrchestrator.execute({ missionId, runWorkers });
      const after = (await this.missionService.status({ missionId })).mission;
      return { action: 'execution', result, nextPhase: after.phase };
    }
    const project = await this.projectService.get(mission.projectId);
    const candidateId = mission.activeCandidateId;
    if (mission.phase === 'validation') {
      const required = project.requiredValidationCapabilities || [];
      if (required.length === 0) {
        if (project.requireValidation) throw Object.assign(new Error('Validation is required but no requiredValidationCapabilities are configured'), { code: 'VALIDATION_REQUIRED_NOT_CONFIGURED' });
        const commitSha = await this.validationCommitSha({ project, mission, candidateId });
        const evidence = await this.evidenceService.record({ projectId: project.id, missionId, type: 'validation', summary: { passed: true, skipped: true, reason: 'no-required-capabilities', commitSha }, sourceIdentity: { head: commitSha } });
        await this.store.transaction('mission_validation_skipped', (state) => {
          const target = state.missions[missionId];
          assertAdvanceMutationAuthority(target);
          target.validation = { status: 'skipped', evidenceIds: [evidence.id], commitSha };
          target.phase = 'review';
          target.status = 'ready';
          target.updatedAt = nowIso();
          state.runtime.timeline.push({ type: 'mission_validation_skipped', missionId, evidenceId: evidence.id, at: nowIso() });
        }, { missionId, evidenceId: evidence.id });
        return { action: 'validation-skipped', nextPhase: 'review', evidenceId: evidence.id };
      }

      const commitSha = await this.validationCommitSha({ project, mission, candidateId });
      const execution = await this.runValidationPlan({ project, mission, candidateId, required, commitSha });
      const passed = execution.results.length === required.length && execution.results.every((result) => result.passed);
      await this.persistValidationAggregate({ missionId, required, commitSha, results: execution.results, passed });
      if (!passed) {
        return {
          action: 'validation',
          results: execution.results,
          nextPhase: 'validation',
          blocked: true,
          deferredCapabilities: execution.deferredCapabilities,
          validationPlan: execution.plan,
          cancelPolicy: 'drain-in-flight'
        };
      }
      return {
        action: 'validation',
        results: execution.results,
        nextPhase: 'review',
        validationPlan: execution.plan,
        cancelPolicy: 'drain-in-flight'
      };
    }
    if (mission.phase === 'review') {
      const result = await this.reviewService.deterministic({ missionId, candidateId });
      if (!result.passed) return { action: 'review', result, nextPhase: 'review', blocked: true };
      await this.store.transaction('mission_review_passed', (state) => {
        const target = state.missions[missionId];
        assertAdvanceMutationAuthority(target);
        target.phase = 'semantic-review';
        target.status = 'ready';
        target.updatedAt = nowIso();
      }, { missionId });
      return { action: 'review', result, nextPhase: 'semantic-review' };
    }
    if (mission.phase === 'semantic-review') {
      const result = await this.reviewService.semantic({ missionId, candidateId });
      if (!result.passed) return { action: 'semantic-review', result, nextPhase: 'semantic-review', blocked: true };
      await this.store.transaction('mission_semantic_review_passed', (state) => {
        const target = state.missions[missionId];
        assertAdvanceMutationAuthority(target);
        target.phase = 'candidate';
        target.status = 'ready';
        target.updatedAt = nowIso();
      }, { missionId });
      return { action: 'semantic-review', result, nextPhase: 'candidate' };
    }
    if (mission.phase === 'candidate') {
      if (candidateId) {
        const state = await this.store.read();
        const candidate = state.runtime.candidates?.[candidateId];
        if (!candidate) throw Object.assign(new Error(`Unknown candidate ${candidateId}`), { code: 'CANDIDATE_NOT_FOUND' });
        const preflight = await this.candidateService.preflight({ missionId });
        const sourceChanged = preflight.sourceHead !== candidate.sourceHead || preflight.missionHead !== candidate.missionHead;
        if (sourceChanged) {
          const result = await this.candidateService.createOrRefresh({ missionId, reason: 'source-drift-refresh' });
          return { action: 'candidate-refresh', result, nextPhase: result.requiresRevalidation ? 'validation' : 'candidate' };
        }
        if (proofFreshForCandidate(mission, candidate)) {
          await this.store.transaction('mission_candidate_ready', (working) => {
            const target = working.missions[missionId];
            assertAdvanceMutationAuthority(target);
            target.phase = 'finalize';
            target.status = 'candidate-ready';
            target.updatedAt = nowIso();
          }, { missionId, candidateId });
          return { action: 'candidate-ready', candidate, nextPhase: 'finalize' };
        }
      }
      const result = await this.candidateService.createOrRefresh({ missionId, reason: candidateId ? 'proof-refresh' : 'finalize' });
      if (result.requiresRevalidation) return { action: 'candidate-refresh', result, nextPhase: 'validation' };
      return { action: 'candidate-created', result, nextPhase: 'candidate' };
    }
    if (mission.phase === 'finalize') {
      if (!candidateId) throw Object.assign(new Error('Finalize requires an active immutable candidate'), { code: 'CANDIDATE_REQUIRED' });
      const before = await this.store.read();
      const candidate = before.runtime.candidates?.[candidateId];
      if (!candidate) throw Object.assign(new Error(`Unknown candidate ${candidateId}`), { code: 'CANDIDATE_NOT_FOUND' });
      const preflight = await this.candidateService.preflight({ missionId });
      const sourceChanged = preflight.sourceHead !== candidate.sourceHead || preflight.missionHead !== candidate.missionHead;
      if (sourceChanged) {
        const result = await this.candidateService.createOrRefresh({ missionId, reason: 'finalize-source-drift' });
        return { action: 'candidate-refresh', result, nextPhase: result.requiresRevalidation ? 'validation' : 'candidate' };
      }
      if (!proofFreshForCandidate(mission, candidate)) {
        throw Object.assign(new Error('Finalize requires validation and review proof bound to the active candidate'), {
          code: 'FINALIZE_PROOF_STALE',
          details: { candidateId, candidateCommitSha: candidate.commitSha }
        });
      }

      const activeProposal = before.runtime.mergeProposals?.[mission.activeMergeProposalId];
      if (proposalMatches(activeProposal, { missionId, candidate, preflight })) {
        const repairedProposal = await this.ensureMergeProposalEvidence({ proposal: activeProposal, project, preflight });
        return { action: 'finalize-proposal', proposal: repairedProposal, evidenceId: repairedProposal.evidenceId, nextPhase: 'finalize', requiresOperatorAction: true, reused: true };
      }

      const proposalId = randomId('merge');
      const createdAt = nowIso();
      const proposal = {
        id: proposalId,
        projectId: project.id,
        missionId,
        candidateId: candidate.id,
        candidateCommitSha: candidate.commitSha,
        candidateRef: candidate.ref,
        expectedSourceHead: preflight.sourceHead,
        targetBranch: preflight.sourceBranch || null,
        missionHead: preflight.missionHead,
        sourceDrift: false,
        status: 'proposed',
        automaticMerge: false,
        automaticPush: false,
        requiresOperatorAction: true,
        proof: {
          validation: { status: mission.validation.status, commitSha: mission.validation.commitSha, evidenceIds: mission.validation.evidenceIds || [] },
          review: { status: mission.review.status, commitSha: mission.review.commitSha, evidenceIds: mission.review.evidenceIds || [] },
          semanticReview: { status: mission.semanticReview.status, commitSha: mission.semanticReview.commitSha, evidenceIds: mission.semanticReview.evidenceIds || [] }
        },
        evidenceId: null,
        createdAt
      };

      const persisted = await this.store.transaction('mission_finalize_proposed', (state) => {
        const target = state.missions[missionId];
        assertAdvanceMutationAuthority(target);
        state.runtime.mergeProposals ||= {};
        const current = state.runtime.mergeProposals[target.activeMergeProposalId];
        if (proposalMatches(current, { missionId, candidate, preflight })) return { proposal: current, reused: true };
        state.runtime.mergeProposals[proposalId] = proposal;
        target.mergeProposalIds ||= [];
        target.mergeProposalIds.push(proposalId);
        target.activeMergeProposalId = proposalId;
        target.phase = 'finalize';
        target.status = 'awaiting-operator-merge';
        target.updatedAt = nowIso();
        state.runtime.timeline.push({ type: 'mission_finalize_proposed', missionId, candidateId, proposalId, candidateCommitSha: candidate.commitSha, expectedSourceHead: preflight.sourceHead, at: nowIso() });
        return { proposal, reused: false };
      }, { missionId, candidateId, proposalId, candidateCommitSha: candidate.commitSha, expectedSourceHead: preflight.sourceHead });

      const finalProposal = await this.ensureMergeProposalEvidence({ proposal: persisted.proposal, project, preflight });
      return { action: 'finalize-proposal', proposal: finalProposal, evidenceId: finalProposal.evidenceId, nextPhase: 'finalize', requiresOperatorAction: true, reused: persisted.reused };
    }
    return { action: 'noop', phase: mission.phase, status: mission.status };
  }
}
