import { RISK_LEVELS } from './constants.mjs';
import { normalizeTaskCapabilityContract } from './capability-plane.mjs';
import { assessTaskRisk, compileMissionExecutionStrategy } from './adaptive-mission-strategy.mjs';
import { computeWaves } from './mission-service.mjs';
import { allowlistedProcessEnvironment, runProcess, git } from './git.mjs';
import { normalizePathList, nowIso, randomId, redactKnownSecrets } from './util.mjs';
import { evaluateRequirementReview } from './outcome-contract.mjs';

function semanticAcceptanceCriteria(mission, tasks) {
  return [
    {
      id: 'mission-goal',
      statement: mission.goal,
      acceptance: 'The whole change fulfills the requested Mission goal without substituting merely related work.'
    },
    {
      id: 'done-definition',
      statement: mission.doneDefinition,
      acceptance: mission.doneDefinition
    },
    ...tasks.map((task) => ({
      id: `task:${task.id}`,
      statement: task.contract,
      acceptance: task.contract
    }))
  ];
}

function normalizeFindingIndexes(raw, taskId) {
  if (!Array.isArray(raw) || raw.length === 0) {
    throw Object.assign(new Error(`Remediation task ${taskId} requires sourceFindingIndexes`), { code: 'REMEDIATION_FINDING_BINDING_REQUIRED', details: { taskId } });
  }
  const indexes = [...new Set(raw)];
  if (indexes.some((value) => !Number.isInteger(value) || value < 0)) {
    throw Object.assign(new Error(`Remediation task ${taskId} sourceFindingIndexes must contain non-negative integers`), { code: 'REMEDIATION_FINDING_BINDING_INVALID', details: { taskId, sourceFindingIndexes: raw } });
  }
  return indexes;
}

function normalizeRemediationTask(raw, index) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw Object.assign(new Error(`tasks[${index}] must be an object`), { code: 'REMEDIATION_TASK_INVALID' });
  const id = String(raw.id || `R${index + 1}`).trim();
  const contract = String(raw.contract || '').trim();
  const owner = String(raw.owner || '').trim();
  if (!id || !contract || !owner) throw Object.assign(new Error(`Remediation task ${id || index + 1} requires id, contract, and owner`), { code: 'REMEDIATION_TASK_INVALID' });
  const dependencies = [...new Set((raw.dependencies || []).map(String))];
  const writeSet = normalizePathList(raw.writeSet || []);
  const capabilityContract = normalizeTaskCapabilityContract(raw, id);
  const validationCapability = raw.validationCapability || null;
  const sourceFindingIndexes = normalizeFindingIndexes(raw.sourceFindingIndexes, id);
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
  if (!RISK_LEVELS.includes(risk)) throw Object.assign(new Error(`Invalid remediation risk level for ${id}: ${risk}`), { code: 'REMEDIATION_TASK_RISK_INVALID' });
  return {
    id,
    contract,
    owner,
    dependencies,
    writeSet,
    protectedPaths: normalizePathList(raw.protectedPaths || []),
    risk,
    riskAssessment,
    validationCapability,
    worker: raw.worker || 'default',
    notes: raw.notes || null,
    sourceFindingIndexes,
    ...capabilityContract
  };
}

function failedReviewHead(mission) {
  if (mission.semanticReview?.status === 'failed' && mission.semanticReview.commitSha) {
    return { kind: 'semantic-review', head: mission.semanticReview.commitSha };
  }
  if (mission.review?.status === 'failed' && mission.review.commitSha) {
    return { kind: 'deterministic-review', head: mission.review.commitSha };
  }
  return null;
}

function authoritativeReviewFindings(mission) {
  if (mission.semanticReview?.status === 'failed') return mission.semanticReview.findings || [];
  if (mission.review?.status === 'failed') return mission.review.findings || [];
  return [];
}

export class ReviewService {
  constructor({ store, projectService, missionService, worktreeManager, evidenceService, experienceService = null }) {
    this.store = store;
    this.projectService = projectService;
    this.missionService = missionService;
    this.worktreeManager = worktreeManager;
    this.evidenceService = evidenceService;
    this.experienceService = experienceService;
  }

  async deterministic({ missionId, candidateId = null }) {
    const { mission, tasks } = await this.missionService.status({ missionId });
    const project = await this.projectService.get(mission.projectId);
    let head;
    let reviewBase = mission.baseSourceIdentity.head;
    if (candidateId) {
      const state = await this.store.read();
      const candidate = state.runtime.candidates?.[candidateId];
      if (!candidate || candidate.missionId !== missionId) throw Object.assign(new Error(`Unknown candidate ${candidateId}`), { code: 'CANDIDATE_NOT_FOUND' });
      head = candidate.commitSha;
      reviewBase = candidate.sourceHead;
    } else {
      const wt = await this.worktreeManager.ensureMissionWorktree(project, mission);
      head = (await git(wt.path, ['rev-parse', 'HEAD'])).stdout.trim();
    }
    const diff = await git(project.repoPath, ['diff', '--check', `${reviewBase}..${head}`], { allowFailure: true });
    const names = (await git(project.repoPath, ['diff', '--name-status', '-z', `${reviewBase}..${head}`])).stdout.split('\0').filter(Boolean);
    const patch = (await git(project.repoPath, ['diff', '--no-ext-diff', '--unified=3', `${reviewBase}..${head}`])).stdout;
    const findings = [];
    if (diff.code !== 0 || diff.stdout.trim() || diff.stderr.trim()) findings.push({ severity: 'high', code: 'DIFF_CHECK_FAILED', message: (diff.stdout || diff.stderr).trim().slice(0, 2000) });
    if (/^<<<<<<< |^=======\s*$|^>>>>>>> /m.test(patch)) findings.push({ severity: 'critical', code: 'CONFLICT_MARKER', message: 'Conflict marker found in whole-change diff' });
    const incomplete = tasks.filter((task) => task.status !== 'done');
    if (incomplete.length) findings.push({ severity: 'high', code: 'TASKS_INCOMPLETE', taskIds: incomplete.map((task) => task.id) });
    const passed = findings.every((item) => !['high', 'critical'].includes(item.severity));
    const evidence = await this.evidenceService.record({
      projectId: project.id,
      missionId,
      type: 'review',
      summary: { passed, head, reviewBase, changedEntries: names.length, findings },
      sourceIdentity: { head },
      artifact: patch,
      metadata: { candidateId }
    });
    await this.store.transaction('deterministic_review_completed', (state) => {
      const target = state.missions[missionId];
      target.review.status = passed ? 'passed' : 'failed';
      target.review.findings = findings;
      target.review.evidenceIds.push(evidence.id);
      target.review.commitSha = head;
      target.updatedAt = nowIso();
      state.runtime.timeline.push({ type: 'deterministic_review_completed', missionId, at: nowIso(), passed, evidenceId: evidence.id, head });
    }, { missionId, passed, head });
    return { passed, head, reviewBase, findings, evidenceId: evidence.id };
  }

  async semantic({ missionId, candidateId = null }) {
    const { mission, tasks } = await this.missionService.status({ missionId });
    const project = await this.projectService.get(mission.projectId);
    const provider = project.reviewerProvider || null;
    let head;
    if (candidateId) {
      const state = await this.store.read();
      const candidate = state.runtime.candidates?.[candidateId];
      if (!candidate || candidate.missionId !== missionId) throw Object.assign(new Error(`Unknown candidate ${candidateId}`), { code: 'CANDIDATE_NOT_FOUND' });
      head = candidate.commitSha;
    } else {
      const wt = await this.worktreeManager.ensureMissionWorktree(project, mission);
      head = (await git(wt.path, ['rev-parse', 'HEAD'])).stdout.trim();
    }
    if (!provider?.command) {
      const passed = project.requireSemanticReview !== true;
      const evidence = await this.evidenceService.record({ projectId: project.id, missionId, type: 'semantic-review', summary: { passed, skipped: true, reason: 'provider-not-configured', head }, sourceIdentity: { head } });
      await this.store.transaction('semantic_review_completed', (state) => {
        const target = state.missions[missionId];
        target.semanticReview.status = passed ? 'skipped' : 'blocked';
        target.semanticReview.findings = passed ? [] : [{ severity: 'high', code: 'SEMANTIC_REVIEWER_REQUIRED' }];
        target.semanticReview.evidenceIds.push(evidence.id);
        target.semanticReview.commitSha = head;
        target.updatedAt = nowIso();
      }, { missionId, passed, skipped: true });
      return { passed, skipped: true, reason: 'provider-not-configured', head, evidenceId: evidence.id };
    }
    const experience = this.experienceService
      ? await this.experienceService.route({ projectId: project.id, sourceHead: head, role: 'reviewer', limit: 8 })
      : { items: [], precedence: 'Current repository/runtime evidence outranks project experience.' };
    const acceptanceCriteria = semanticAcceptanceCriteria(mission, tasks);
    const payload = {
      protocol: 'veteran-reviewer-v1',
      mission: { id: mission.id, goal: mission.goal, doneDefinition: mission.doneDefinition, baseHead: mission.baseSourceIdentity.head, head },
      tasks: tasks.map((task) => ({ id: task.id, contract: task.contract, owner: task.owner, status: task.status })),
      acceptanceCriteria,
      requiredOutput: {
        requirementResults: 'Return exactly one row per acceptanceCriteria id with status passed|failed|unproven and a non-empty evidence array for passed rows.'
      },
      projectExperience: experience.items,
      experiencePrecedence: experience.precedence,
      reviewPolicy: [
        'Review the whole semantic change, not style in isolation. Look for new authorities, state machines, stores, services, wrappers, adapters, extension points, or dependencies that lack a distinct responsibility, lifecycle, or repeated semantic contract.',
        'Treat the Mission goal, done definition, and every task contract as independent acceptance obligations. Related work is not substitute work; do not let a visual/theme change stand in for a requested layout/workflow/function change.',
        'Decompose compound natural-language goals when judging mission-goal coverage. If one requested clause is absent or only indirectly related, mark mission-goal failed or unproven instead of passing the whole outcome.',
        'For every acceptanceCriteria id, return one requirementResults row. A passed row requires concrete repository/runtime/test evidence tied to the current head; plausibility, intent, or code presence alone is not evidence.',
        'Flag parallel sources of truth, duplicate state machines, wrapper-on-wrapper indirection, speculative generic interfaces, and product policy hidden behind generic plumbing when a simpler existing owner can safely carry the behavior.',
        'Check negative space after the change: obsolete branches, superseded compatibility, redundant helpers, duplicate tests, old owners, and temporary scaffolding should be removed when their live consumer is gone.',
        'Do not recommend simplification that erases real authorization, concurrency, durability, failure-recovery, observability, compatibility, isolation, or cleanup guarantees.',
        'Treat complexity as justified when current repository evidence demonstrates a distinct correctness boundary; do not report mere line count, file size, or personal style preference as a finding.'
      ],
      limits: { maxFindings: 20, maxRemediationTasks: 8 }
    };
    const providerEnv = allowlistedProcessEnvironment(provider.envAllowlist || []);
    const providerSecrets = (provider.envAllowlist || [])
      .map((key) => providerEnv[key.trim()])
      .filter((value) => typeof value === 'string' && value.length > 0);
    const result = await runProcess(provider.command, provider.args || [], {
      cwd: project.repoPath,
      env: providerEnv,
      inheritEnv: false,
      input: JSON.stringify(payload),
      allowFailure: true,
      timeoutMs: provider.timeoutMs || 180_000
    });
    let parsed = null;
    try { parsed = redactKnownSecrets(JSON.parse(result.stdout), providerSecrets); } catch { /* handled below */ }
    const safeStderr = redactKnownSecrets(result.stderr, providerSecrets);
    const providerFindings = Array.isArray(parsed?.findings) ? parsed.findings.slice(0, 20) : [{ severity: 'high', code: 'SEMANTIC_REVIEWER_INVALID_OUTPUT', message: safeStderr.slice(0, 1000) }];
    const requirementReview = evaluateRequirementReview(acceptanceCriteria, parsed?.requirementResults);
    const findings = [...providerFindings, ...requirementReview.findings];
    const passed = result.code === 0
      && parsed?.passed === true
      && requirementReview.passed
      && providerFindings.every((item) => item.severity !== 'critical');
    const artifact = parsed
      ? `${JSON.stringify(parsed, null, 2)}\n--- stderr ---\n${safeStderr}`
      : `semantic reviewer returned invalid JSON\n--- stderr ---\n${safeStderr}`;
    const evidence = await this.evidenceService.record({
      projectId: project.id,
      missionId,
      type: 'semantic-review',
      summary: { passed, head, findings, requirementResults: requirementReview.results },
      sourceIdentity: { head },
      artifact
    });
    await this.store.transaction('semantic_review_completed', (state) => {
      const target = state.missions[missionId];
      target.semanticReview.status = passed ? 'passed' : 'failed';
      target.semanticReview.findings = findings;
      target.semanticReview.requirementResults = requirementReview.results;
      target.semanticReview.evidenceIds.push(evidence.id);
      target.semanticReview.commitSha = head;
      target.updatedAt = nowIso();
      state.runtime.timeline.push({ type: 'semantic_review_completed', missionId, at: nowIso(), passed, evidenceId: evidence.id, head });
    }, { missionId, passed, head });
    return { passed, head, findings, requirementResults: requirementReview.results, evidenceId: evidence.id };
  }

  async remediationPlan({ missionId, findings = null, maxTasks = 8, apply = false, tasks = null }) {
    const snapshot = await this.missionService.status({ missionId });
    const { mission, tasks: existingTasks } = snapshot;
    if (apply && findings !== null) {
      throw Object.assign(new Error('Applied remediation must use the current failed review findings; caller-supplied finding overrides are not allowed'), { code: 'REMEDIATION_FINDINGS_OVERRIDE_FORBIDDEN' });
    }
    const source = apply
      ? authoritativeReviewFindings(mission)
      : (findings || [...(mission.review.findings || []), ...(mission.semanticReview.findings || [])]);
    const boundedLimit = Math.max(1, Math.min(maxTasks, 8));
    const bounded = source.filter((item) => ['medium', 'high', 'critical'].includes(item.severity || 'high')).slice(0, boundedLimit);
    const planId = randomId('remediation');

    if (!apply) {
      const plan = {
        id: planId,
        missionId,
        createdAt: nowIso(),
        applied: false,
        findings: bounded,
        tasks: bounded.map((finding, index) => ({
          id: `R${index + 1}`,
          contract: finding.requirement
            ? `Implement missing requirement: ${finding.requirement}`
            : `Resolve ${finding.code || 'review finding'} without expanding mission scope`,
          sourceFindingIndexes: [index],
          sourceFinding: finding,
          status: 'proposed'
        }))
      };
      await this.store.transaction('remediation_plan_created', (state) => {
        const target = state.missions[missionId];
        target.remediationPlans ||= [];
        target.remediationPlans.push(plan);
        target.updatedAt = nowIso();
        state.runtime.timeline.push({ type: 'remediation_plan_created', missionId, remediationPlanId: plan.id, at: nowIso() });
      }, { missionId, remediationPlanId: plan.id, taskCount: plan.tasks.length });
      return plan;
    }

    if (!bounded.length) {
      throw Object.assign(new Error('Applying remediation requires at least one current medium/high/critical review finding'), { code: 'REMEDIATION_FINDINGS_REQUIRED' });
    }
    if (!Array.isArray(tasks) || tasks.length === 0) {
      throw Object.assign(new Error('Applying remediation requires explicit executable task specs'), { code: 'REMEDIATION_TASKS_REQUIRED' });
    }
    if (tasks.length > boundedLimit) {
      throw Object.assign(new Error(`Remediation task count exceeds maxTasks=${boundedLimit}`), { code: 'REMEDIATION_TASK_LIMIT_EXCEEDED' });
    }
    if (!['review', 'semantic-review'].includes(mission.phase)) {
      throw Object.assign(new Error(`Remediation can only re-enter execution from review phases, not ${mission.phase}`), { code: 'REMEDIATION_PHASE_INVALID' });
    }
    if (mission.status === 'cancelled') throw Object.assign(new Error('Cancelled missions cannot apply remediation'), { code: 'MISSION_CANCELLED' });
    if (mission.activeCandidateId || mission.activeMergeProposalId) {
      throw Object.assign(new Error('Remediation cannot mutate a Mission with an active immutable candidate or merge proposal'), { code: 'REMEDIATION_CANDIDATE_ACTIVE' });
    }
    const incomplete = existingTasks.filter((task) => task.status !== 'done');
    if (incomplete.length) {
      throw Object.assign(new Error('Remediation re-entry requires all existing Mission tasks to be integrated'), { code: 'REMEDIATION_EXISTING_TASKS_INCOMPLETE', details: incomplete.map((task) => task.id) });
    }
    const proof = failedReviewHead(mission);
    if (!proof) throw Object.assign(new Error('Remediation apply requires a failed source-bound review'), { code: 'REMEDIATION_FAILED_REVIEW_REQUIRED' });

    const normalized = tasks.map(normalizeRemediationTask);
    for (const task of normalized) {
      const invalidFindingIndexes = task.sourceFindingIndexes.filter((index) => index >= bounded.length);
      if (invalidFindingIndexes.length) {
        throw Object.assign(new Error(`Remediation task ${task.id} references findings outside the authoritative remediation set`), {
          code: 'REMEDIATION_FINDING_BINDING_INVALID',
          details: { taskId: task.id, sourceFindingIndexes: task.sourceFindingIndexes, findingCount: bounded.length }
        });
      }
    }
    const existingIds = new Set(existingTasks.map((task) => task.id));
    const newIds = new Set();
    for (const task of normalized) {
      if (existingIds.has(task.id) || newIds.has(task.id)) {
        throw Object.assign(new Error(`Duplicate remediation task id: ${task.id}`), { code: 'REMEDIATION_TASK_ID_CONFLICT', details: { taskId: task.id } });
      }
      newIds.add(task.id);
    }
    for (const task of normalized) {
      const externalDependencies = task.dependencies.filter((id) => !newIds.has(id));
      if (externalDependencies.length) {
        throw Object.assign(new Error(`Remediation task ${task.id} has dependencies outside the remediation set: ${externalDependencies.join(', ')}`), {
          code: 'REMEDIATION_DEPENDENCY_INVALID',
          details: { taskId: task.id, dependencies: externalDependencies }
        });
      }
    }
    const remediationWaves = computeWaves(normalized);
    const project = await this.projectService.get(mission.projectId);
    const missionWt = await this.worktreeManager.ensureMissionWorktree(project, mission);
    const sourceHead = (await git(missionWt.path, ['rev-parse', 'HEAD'])).stdout.trim();
    if (sourceHead !== proof.head) {
      throw Object.assign(new Error(`Remediation review proof is stale: reviewed ${proof.head}, current Mission head is ${sourceHead}`), {
        code: 'REMEDIATION_SOURCE_STALE',
        details: { reviewedHead: proof.head, currentHead: sourceHead, reviewKind: proof.kind }
      });
    }

    const combinedWaves = [...mission.waves, ...remediationWaves];
    const combinedTasks = [...existingTasks, ...normalized];
    const executionStrategy = compileMissionExecutionStrategy({
      tasks: combinedTasks,
      waves: combinedWaves,
      project,
      riskEnvelope: mission.riskEnvelope,
      riskEnvelopeSource: mission.executionStrategy?.riskEnvelopeSource === 'explicit' ? 'explicit' : 'default',
      continuity: mission.projectContinuity
    });
    const createdAt = nowIso();
    const taskRecords = normalized.map((task) => ({
      ...task,
      key: `${missionId}:${task.id}`,
      missionId,
      projectId: mission.projectId,
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
    const appliedPlan = {
      id: planId,
      missionId,
      createdAt,
      applied: true,
      sourceHead,
      reviewKind: proof.kind,
      findings: bounded,
      taskIds: normalized.map((task) => task.id),
      tasks: normalized.map((task) => ({ ...task, status: 'planned' }))
    };

    return this.store.transaction('remediation_plan_applied', (state) => {
      const target = state.missions[missionId];
      if (!target) throw Object.assign(new Error(`Unknown mission: ${missionId}`), { code: 'MISSION_NOT_FOUND' });
      if (target.status === 'cancelled') throw Object.assign(new Error('Cancelled missions cannot apply remediation'), { code: 'MISSION_CANCELLED' });
      if (!['review', 'semantic-review'].includes(target.phase)) throw Object.assign(new Error(`Mission phase changed before remediation apply: ${target.phase}`), { code: 'REMEDIATION_PHASE_STALE' });
      if (target.activeCandidateId || target.activeMergeProposalId) throw Object.assign(new Error('Candidate/finalize state appeared before remediation apply'), { code: 'REMEDIATION_CANDIDATE_ACTIVE' });
      const liveExisting = Object.values(state.tasks).filter((task) => task.missionId === missionId);
      if (liveExisting.some((task) => task.status !== 'done')) throw Object.assign(new Error('Mission task state changed before remediation apply'), { code: 'REMEDIATION_TASK_STATE_STALE' });
      const liveProof = failedReviewHead(target);
      if (!liveProof || liveProof.head !== proof.head || liveProof.kind !== proof.kind) throw Object.assign(new Error('Review authority changed before remediation apply'), { code: 'REMEDIATION_REVIEW_STALE' });
      const liveFindings = authoritativeReviewFindings(target).filter((item) => ['medium', 'high', 'critical'].includes(item.severity || 'high')).slice(0, boundedLimit);
      if (JSON.stringify(liveFindings) !== JSON.stringify(bounded)) {
        throw Object.assign(new Error('Authoritative review findings changed before remediation apply'), { code: 'REMEDIATION_FINDINGS_STALE' });
      }
      if (target.waves.length !== mission.waves.length || target.nextWaveIndex !== mission.waves.length) {
        throw Object.assign(new Error('Mission wave state changed before remediation apply'), { code: 'REMEDIATION_WAVE_STATE_STALE' });
      }
      for (const task of taskRecords) {
        if (state.tasks[task.key]) throw Object.assign(new Error(`Remediation task already exists: ${task.id}`), { code: 'REMEDIATION_TASK_ID_CONFLICT' });
        state.tasks[task.key] = task;
      }
      const firstRemediationWave = target.waves.length;
      target.waves.push(...remediationWaves);
      target.nextWaveIndex = firstRemediationWave;
      target.phase = 'execution';
      target.status = 'ready';
      target.executionStrategy = executionStrategy;
      target.currentSourceIdentity = { ...target.currentSourceIdentity, head: sourceHead, dirty: false, dirtyPaths: [] };
      target.validation = { status: 'pending', evidenceIds: [] };
      target.review = { status: 'pending', evidenceIds: [], findings: [] };
      target.semanticReview = { status: 'pending', evidenceIds: [], findings: [] };
      target.remediationPlans ||= [];
      target.remediationPlans.push(appliedPlan);
      target.updatedAt = createdAt;
      state.runtime.timeline.push({
        type: 'remediation_plan_applied',
        missionId,
        remediationPlanId: appliedPlan.id,
        sourceHead,
        reviewKind: proof.kind,
        taskIds: appliedPlan.taskIds,
        firstRemediationWave,
        at: createdAt
      });
      return appliedPlan;
    }, { missionId, remediationPlanId: appliedPlan.id, sourceHead, taskIds: appliedPlan.taskIds });
  }
}
