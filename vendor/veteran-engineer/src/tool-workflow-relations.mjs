import { TOOL_NAMES } from './tool-catalog.mjs';

export const TOOL_WORKFLOW_META_KEY = 'io.veteran-engineer/workflow';
export const TOOL_WORKFLOW_SCHEMA = 'veteran-tool-workflow-v1';

const RELATION_KINDS = new Set(['next', 'inspect', 'recover', 'refresh', 'alternate']);
const RELATION_CONDITION_OPERATORS = new Set(['equals', 'in', 'not-equals']);
const WORKFLOW_GROUPS = new Set(['project', 'mission', 'worker', 'evidence', 'validation', 'review', 'candidate', 'experience', 'runtime', 'handoff']);
const SCOPE_KEYS = new Set(['projectId', 'missionId', 'taskId', 'candidateId', 'evidenceId', 'experienceId']);

function condition(pointer, operator, value) {
  return Object.freeze({
    source: 'structuredContent',
    pointer,
    operator,
    value: Array.isArray(value) ? Object.freeze([...value]) : value
  });
}

function relation(tool, kind, when, machineCondition = null) {
  return Object.freeze({
    tool,
    kind,
    when,
    ...(machineCondition ? { condition: machineCondition } : {})
  });
}

function workflow(group, scopeKeys, relations) {
  return Object.freeze({
    schema: TOOL_WORKFLOW_SCHEMA,
    group,
    scopeKeys: Object.freeze([...scopeKeys]),
    relations: Object.freeze([...relations])
  });
}

export const TOOL_WORKFLOW_RELATIONS = Object.freeze({
  project_open: workflow('project', ['projectId'], [
    relation('project_snapshot', 'refresh', 'Refresh repository and environment authority before consequential work after an external source change.'),
    relation('validation_capabilities', 'inspect', 'Discover configured validation capabilities before planning proof.'),
    relation('experience_query', 'inspect', 'Load reviewed project experience when it can inform planning.'),
    relation('mission_plan', 'next', 'Create a Mission when source identity is current and the engineering outcome is known.')
  ]),
  project_snapshot: workflow('project', ['projectId'], [
    relation('validation_capabilities', 'inspect', 'Re-read validation capability availability after project configuration changes.'),
    relation('experience_query', 'inspect', 'Load reviewed project experience against the refreshed source head.'),
    relation('mission_plan', 'next', 'Plan work from the refreshed project authority.')
  ]),
  mission_plan: workflow('mission', ['projectId', 'missionId'], [
    relation('mission_status', 'inspect', 'Inspect the persisted Mission and task DAG after planning.'),
    relation('mission_readiness', 'inspect', 'Check admission and blockers before the first consequential transition.'),
    relation('mission_execute', 'next', 'Dispatch or execute the first safe worker wave when readiness permits.'),
    relation('mission_cancel', 'recover', 'Abandon a planned Mission without advancing the user branch.')
  ]),
  mission_execute: workflow('mission', ['missionId'], [
    relation('mission_status', 'inspect', 'Inspect task and Mission state after a dispatch or worker wave.'),
    relation('mission_readiness', 'next', 'Re-read authoritative Mission blockers after execution before any lifecycle progression.'),
    relation('worker_cancel', 'recover', 'Stop an active worker when a task must not continue.'),
    relation('worker_retry', 'recover', 'Retry a failed or cancelled task after the failure is understood.'),
    relation('mission_cancel', 'recover', 'Drain and cancel the Mission when safe continuation is no longer desired.')
  ]),
  mission_status: workflow('mission', ['missionId'], [
    relation('mission_readiness', 'next', 'Determine the next safe transition from the current aggregate state.'),
    relation('mission_timeline', 'inspect', 'Inspect durable history when current status needs causal context.'),
    relation('candidate_status', 'inspect', 'Inspect immutable candidate identity when candidate or finalize work is active.'),
    relation('task_result_commit', 'next', 'Commit one externally produced dispatched task result only after the external producer has finished writing its runtime-owned task worktree.', condition('/mission/status', 'not-equals', 'cancelled')),
    relation('worker_cancel', 'recover', 'Cancel one executing or already-cancelling task selected from the fresh authoritative Mission status.'),
    relation('worker_resume', 'recover', 'Resume one interrupted task after Mission-level reconciliation has made the uncertain task state explicit.'),
    relation('worker_retry', 'recover', 'Retry one failed, interrupted, or cancelled task with a new dispatch identity after the failure or uncertain outcome is understood.', condition('/mission/status', 'not-equals', 'cancelled')),
    relation('mission_resume', 'recover', 'Reconcile and resume an interrupted Mission.', condition('/mission/status', 'not-equals', 'cancelled')),
    relation('mission_cancel', 'recover', 'Drain and cancel a Mission that should not continue.'),
    relation('handoff_export', 'alternate', 'Export resumable state when another operator or session should take over.')
  ]),
  mission_advance: workflow('mission', ['missionId'], [
    relation('mission_status', 'inspect', 'Inspect the authoritative state produced by the transition.'),
    relation('mission_readiness', 'next', 'Re-evaluate readiness after each state-machine step.'),
    relation('evidence_query', 'inspect', 'Inspect proof artifacts created by validation or review transitions.'),
    relation('mission_resume', 'recover', 'Resume and reconcile interrupted execution when readiness or advance reports RECONCILIATION_REQUIRED.'),
    relation('remediation_plan', 'recover', 'Create a bounded remediation plan when review findings block progress.'),
    relation('candidate_status', 'inspect', 'Inspect candidate identity and proof freshness during candidate/finalize phases.'),
    relation('handoff_export', 'next', 'Export a resumable handoff when finalization reaches operator action.')
  ]),
  mission_readiness: workflow('mission', ['missionId'], [
    relation('mission_advance', 'next', 'Perform the next authoritative transition when readiness reports ready.', condition('/ready', 'equals', true)),
    relation('mission_execute', 'alternate', 'Use explicit execution control when the current phase is execution.', condition('/phase', 'equals', 'execution')),
    relation('mission_status', 'inspect', 'Inspect full Mission/task state behind a readiness decision.'),
    relation('mission_timeline', 'inspect', 'Inspect durable history when a blocker needs causal context.'),
    relation('candidate_preflight', 'inspect', 'Check source drift explicitly during candidate or finalize work.', condition('/phase', 'in', ['candidate', 'finalize'])),
    relation('mission_resume', 'recover', 'Reconcile an interruption before trying to advance again.', condition('/status', 'not-equals', 'cancelled'))
  ]),
  mission_timeline: workflow('mission', ['missionId'], [
    relation('mission_status', 'inspect', 'Pair history with the current aggregate Mission state.'),
    relation('evidence_query', 'inspect', 'Inspect evidence referenced by timeline events.'),
    relation('mission_readiness', 'next', 'Re-evaluate the next safe action after diagnosing historical state.')
  ]),
  mission_cancel: workflow('mission', ['missionId'], [
    relation('mission_status', 'inspect', 'Verify the cancelled Mission and drained execution state.'),
    relation('mission_timeline', 'inspect', 'Inspect cancellation and drain events.'),
    relation('handoff_export', 'next', 'Export cancelled Mission context for audit or transfer when needed.')
  ]),
  mission_resume: workflow('mission', ['missionId'], [
    relation('mission_status', 'inspect', 'Inspect reconciled Mission/task state after resume.'),
    relation('mission_readiness', 'next', 'Check the next safe transition after reconciliation.'),
    relation('mission_timeline', 'inspect', 'Inspect interruption and reconciliation events.'),
    relation('mission_cancel', 'recover', 'Cancel if reconciliation shows the Mission should not continue.')
  ]),
  task_result_commit: workflow('worker', ['missionId', 'taskId'], [
    relation('mission_status', 'inspect', 'Verify task commit and serial Mission integration state.'),
    relation('evidence_query', 'inspect', 'Inspect task/integration evidence after accepting the external result.'),
    relation('mission_readiness', 'next', 'Check whether dependent work or the next Mission phase is now ready.'),
    relation('mission_cancel', 'recover', 'Cancel the Mission if accepted external work exposes an unsafe continuation.')
  ]),
  worker_cancel: workflow('worker', ['missionId', 'taskId'], [
    relation('mission_status', 'inspect', 'Inspect task and Mission state after cancellation signalling before choosing any further worker action.'),
    relation('mission_timeline', 'inspect', 'Inspect cancellation and drain events.')
  ]),
  worker_resume: workflow('worker', ['missionId', 'taskId'], [
    relation('mission_status', 'inspect', 'Inspect reconciled task and Mission state before choosing any further worker action.'),
    relation('mission_readiness', 'next', 'Check whether Mission progress is safe after task reconciliation.')
  ]),
  worker_retry: workflow('worker', ['missionId', 'taskId'], [
    relation('mission_status', 'inspect', 'Inspect task and Mission state after retry scheduling before choosing any further worker action.'),
    relation('mission_timeline', 'inspect', 'Inspect prior failure and retry events.'),
    relation('mission_readiness', 'next', 'Check whether retry scheduling allows Mission execution to continue.')
  ]),
  evidence_query: workflow('evidence', ['projectId', 'missionId', 'taskId', 'evidenceId'], [
    relation('mission_status', 'inspect', 'Correlate Mission-scoped evidence with current execution/proof state.'),
    relation('validation_run', 'alternate', 'Run targeted validation when the evidence set reveals a proof gap.'),
    relation('experience_commit', 'next', 'Create a reviewable project-experience candidate only when evidence supports a durable lesson.')
  ]),
  validation_capabilities: workflow('validation', ['projectId'], [
    relation('validation_run', 'next', 'Execute a specific configured capability for targeted proof.'),
    relation('mission_plan', 'next', 'Use capability names while assigning Mission task validation contracts.'),
    relation('project_snapshot', 'refresh', 'Refresh project authority if validation configuration may have changed.')
  ]),
  validation_run: workflow('validation', ['projectId', 'missionId', 'candidateId', 'evidenceId'], [
    relation('evidence_query', 'inspect', 'Inspect the durable validation evidence created by the run.'),
    relation('mission_status', 'inspect', 'Inspect Mission proof state after Mission-scoped validation.'),
    relation('mission_readiness', 'next', 'Re-enter Mission progression through a fresh readiness check after an independent Mission-scoped proof run.')
  ]),
  review_run: workflow('review', ['missionId', 'candidateId', 'evidenceId'], [
    relation('evidence_query', 'inspect', 'Inspect deterministic review evidence and artifacts.'),
    relation('mission_readiness', 'next', 'Re-enter Mission progression through a fresh readiness check after independent deterministic review.'),
    relation('semantic_review_run', 'next', 'Run independent semantic review after deterministic review passes when driving proof explicitly.', condition('/passed', 'equals', true)),
    relation('remediation_plan', 'recover', 'Create bounded remediation work when findings block progress.', condition('/passed', 'equals', false))
  ]),
  semantic_review_run: workflow('review', ['missionId', 'candidateId', 'evidenceId'], [
    relation('evidence_query', 'inspect', 'Inspect semantic review evidence and provider output.'),
    relation('mission_readiness', 'next', 'Re-enter Mission progression through a fresh readiness check after independent semantic review.'),
    relation('candidate_preflight', 'next', 'Check source/candidate safety after semantic review passes when driving proof explicitly.', condition('/passed', 'equals', true)),
    relation('remediation_plan', 'recover', 'Create bounded remediation work when semantic findings block progress.', condition('/passed', 'equals', false))
  ]),
  remediation_plan: workflow('review', ['missionId'], [
    relation('mission_status', 'inspect', 'Inspect Mission review state alongside the proposed remediation tasks.'),
    relation('mission_timeline', 'inspect', 'Inspect the finding and remediation-plan history.'),
    relation('mission_execute', 'next', 'Continue implementation immediately after source-bound remediation tasks were applied to the same Mission.', condition('/applied', 'equals', true)),
    relation('handoff_export', 'alternate', 'Export only proposal-only remediation when implementation must transfer to another operator or session.', condition('/applied', 'equals', false))
  ]),
  candidate_preflight: workflow('candidate', ['missionId', 'candidateId'], [
    relation('candidate_status', 'inspect', 'Inspect immutable candidate identity and proof freshness.'),
    relation('candidate_refresh', 'recover', 'Create or refresh an immutable candidate explicitly after candidate preflight reports ready.', condition('/ready', 'equals', true)),
    relation('mission_readiness', 'next', 'Re-evaluate Mission-level blockers before any state-machine transition from candidate preflight.')
  ]),
  candidate_refresh: workflow('candidate', ['missionId', 'candidateId', 'evidenceId'], [
    relation('candidate_status', 'inspect', 'Inspect the new immutable candidate and proof freshness.'),
    relation('evidence_query', 'inspect', 'Inspect candidate creation/refresh evidence.'),
    relation('mission_readiness', 'next', 'Determine whether revalidation or candidate progression is required.'),
    relation('mission_advance', 'alternate', 'Let the Mission state machine orchestrate the required revalidation/progression.')
  ]),
  candidate_status: workflow('candidate', ['missionId', 'candidateId'], [
    relation('candidate_preflight', 'inspect', 'Re-check source drift before finalization or operator handoff.'),
    relation('mission_readiness', 'next', 'Determine the next safe Mission transition for the current candidate.'),
    relation('handoff_export', 'next', 'Export resumable state when the candidate is awaiting operator action.')
  ]),
  experience_query: workflow('experience', ['projectId', 'experienceId'], [
    relation('experience_audit', 'inspect', 'Audit lifecycle/freshness when active experience is missing, stale, or conflicting.'),
    relation('evidence_query', 'inspect', 'Inspect supporting evidence for a reviewed experience when needed.'),
    relation('mission_plan', 'next', 'Use reviewed project experience as advisory context while planning new work.')
  ]),
  experience_commit: workflow('experience', ['projectId', 'experienceId', 'evidenceId'], [
    relation('experience_review', 'next', 'Review the candidate before it can become active project experience.'),
    relation('experience_audit', 'inspect', 'Inspect conflicts, freshness, and evidence links for the candidate.'),
    relation('evidence_query', 'inspect', 'Verify supporting evidence before review.')
  ]),
  experience_review: workflow('experience', ['experienceId', 'evidenceId'], [
    relation('experience_query', 'inspect', 'Confirm whether reviewed experience is now eligible for advisory use.'),
    relation('experience_audit', 'inspect', 'Audit lifecycle/freshness after activation, retirement, rejection, or reactivation.'),
    relation('experience_challenge', 'recover', 'Record contrary evidence against an active experience instead of silently overwriting it.', condition('/status', 'equals', 'active'))
  ]),
  experience_challenge: workflow('experience', ['experienceId', 'evidenceId'], [
    relation('experience_audit', 'inspect', 'Inspect conflicts and lifecycle state after contrary evidence is recorded.'),
    relation('experience_review', 'next', 'Retire or reactivate experience through explicit review after a challenge.'),
    relation('experience_query', 'inspect', 'Confirm which reviewed experience remains usable after challenge handling.')
  ]),
  experience_audit: workflow('experience', ['projectId', 'experienceId'], [
    relation('experience_review', 'next', 'Review candidate, active, or challenged lifecycle state when the audit shows an explicit decision is needed.'),
    relation('experience_compact', 'next', 'Compact exact duplicate candidates when the audit exposes redundant candidate records.'),
    relation('experience_query', 'inspect', 'Re-query the reviewed active set after lifecycle maintenance.')
  ]),
  experience_compact: workflow('experience', ['projectId', 'experienceId'], [
    relation('experience_audit', 'inspect', 'Verify duplicate compaction and remaining lifecycle state.'),
    relation('experience_review', 'next', 'Review retained candidates when they are ready for a lifecycle decision.'),
    relation('experience_query', 'inspect', 'Confirm the active advisory set after maintenance.')
  ]),
  runtime_health: workflow('runtime', [], [
    relation('runtime_integrity', 'inspect', 'Verify audit/state invariants when health needs stronger proof.'),
    relation('runtime_maintenance', 'recover', 'Run conservative reconciliation when health exposes recoverable runtime drift.'),
    relation('runtime_cleanup', 'recover', 'Inspect runtime-owned orphan resources when cleanup may be needed.')
  ]),
  runtime_integrity: workflow('runtime', [], [
    relation('runtime_health', 'inspect', 'Pair invariant results with effective runtime/protocol capability identity.'),
    relation('runtime_maintenance', 'recover', 'Reconcile recoverable state or request outcomes when integrity issues are found.'),
    relation('runtime_cleanup', 'recover', 'Inspect and remove runtime-owned orphans when they are the integrity issue.')
  ]),
  runtime_cleanup: workflow('runtime', [], [
    relation('runtime_integrity', 'inspect', 'Re-check invariants after cleanup inspection or application.'),
    relation('runtime_health', 'inspect', 'Confirm effective runtime health after cleanup.'),
    relation('runtime_maintenance', 'next', 'Run conservative reconciliation when cleanup exposes broader state drift.')
  ]),
  runtime_maintenance: workflow('runtime', ['projectId'], [
    relation('runtime_integrity', 'inspect', 'Verify invariants after reconciliation and maintenance.'),
    relation('runtime_health', 'inspect', 'Confirm effective runtime/protocol health after maintenance.'),
    relation('experience_audit', 'inspect', 'Inspect project experience lifecycle when maintenance was project-scoped.')
  ]),
  handoff_export: workflow('handoff', ['missionId'], [
    relation('mission_status', 'inspect', 'Inspect live Mission state if work continues in the current runtime.'),
    relation('mission_readiness', 'inspect', 'Recompute the next safe transition if the handoff is resumed locally.'),
    relation('mission_timeline', 'inspect', 'Inspect durable history accompanying the exported handoff.')
  ])
});

function assertWorkflowContract() {
  const names = Object.keys(TOOL_WORKFLOW_RELATIONS);
  if (names.length !== TOOL_NAMES.length) {
    throw new Error(`Every public tool must have exactly one workflow relation contract; got ${names.length} contracts for ${TOOL_NAMES.length} tools`);
  }
  for (const name of TOOL_NAMES) {
    const spec = TOOL_WORKFLOW_RELATIONS[name];
    if (!spec) throw new Error(`Missing public tool workflow relation contract: ${name}`);
    if (!WORKFLOW_GROUPS.has(spec.group)) throw new Error(`Unknown workflow group for ${name}: ${spec.group}`);
    if (!Array.isArray(spec.scopeKeys)) throw new Error(`Workflow scopeKeys must be an array for ${name}`);
    for (const scopeKey of spec.scopeKeys) {
      if (!SCOPE_KEYS.has(scopeKey)) throw new Error(`Unknown workflow scope key for ${name}: ${scopeKey}`);
    }
    if (!Array.isArray(spec.relations) || spec.relations.length === 0) throw new Error(`Tool ${name} must publish at least one workflow relation`);
    const seen = new Set();
    for (const edge of spec.relations) {
      if (!TOOL_NAMES.includes(edge.tool)) throw new Error(`Unknown workflow relation target from ${name}: ${edge.tool}`);
      if (!RELATION_KINDS.has(edge.kind)) throw new Error(`Unknown workflow relation kind from ${name} to ${edge.tool}: ${edge.kind}`);
      if (typeof edge.when !== 'string' || edge.when.length === 0) throw new Error(`Workflow relation from ${name} to ${edge.tool} requires a condition`);
      if (edge.condition) {
        if (edge.condition.source !== 'structuredContent') throw new Error(`Workflow relation condition source must be structuredContent for ${name} -> ${edge.tool}`);
        if (typeof edge.condition.pointer !== 'string' || !edge.condition.pointer.startsWith('/')) throw new Error(`Workflow relation condition pointer must be a JSON pointer for ${name} -> ${edge.tool}`);
        if (!RELATION_CONDITION_OPERATORS.has(edge.condition.operator)) throw new Error(`Unknown workflow relation condition operator for ${name} -> ${edge.tool}: ${edge.condition.operator}`);
        if (edge.condition.operator === 'in' && !Array.isArray(edge.condition.value)) throw new Error(`Workflow relation in-condition requires an array value for ${name} -> ${edge.tool}`);
      }
      const key = `${edge.kind}:${edge.tool}`;
      if (seen.has(key)) throw new Error(`Duplicate workflow relation for ${name}: ${key}`);
      seen.add(key);
    }
  }
}

assertWorkflowContract();

export function toolWorkflowMeta(name) {
  const workflow = TOOL_WORKFLOW_RELATIONS[name];
  if (!workflow) throw new Error(`Unknown public tool workflow relation contract: ${name}`);
  return Object.freeze({ [TOOL_WORKFLOW_META_KEY]: workflow });
}
