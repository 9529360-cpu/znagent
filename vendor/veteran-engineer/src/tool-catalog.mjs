import { EXPERIENCE_REVIEW_ACTIONS } from './experience-lifecycle.mjs';

const REQUEST_ID_TOOL_NAMES = Object.freeze([
  'project_open', 'project_snapshot', 'mission_plan', 'mission_execute', 'mission_advance',
  'mission_cancel', 'mission_resume', 'task_result_commit', 'worker_cancel', 'worker_resume',
  'worker_retry', 'validation_run', 'review_run', 'semantic_review_run', 'remediation_plan',
  'candidate_refresh', 'experience_commit', 'experience_review', 'experience_challenge',
  'experience_compact', 'runtime_cleanup', 'runtime_maintenance', 'handoff_export'
]);

const REQUEST_ID_TOOL_SET = new Set(REQUEST_ID_TOOL_NAMES);
const RISK_LEVELS = ['low', 'medium', 'high', 'critical'];
const VALIDATION_PURPOSES = ['final-validation', 'runtime-feedback'];

function stringField(description, { minLength = 1, enumValues = null } = {}) {
  return {
    type: 'string',
    ...(minLength === null ? {} : { minLength }),
    ...(enumValues ? { enum: enumValues } : {}),
    description
  };
}

function booleanField(description) {
  return { type: 'boolean', description };
}

function integerField(description, minimum, maximum) {
  return { type: 'integer', minimum, maximum, description };
}

function stringArray(description, { maxItems = null } = {}) {
  return {
    type: 'array',
    items: { type: 'string' },
    ...(maxItems === null ? {} : { maxItems }),
    description
  };
}

function openObject(description, properties = {}, required = []) {
  return {
    type: 'object',
    description,
    properties,
    ...(required.length ? { required } : {}),
    additionalProperties: true
  };
}

const RUNTIME_RESOURCE = {
  description: 'Runtime resource declaration. A string means a project-scoped exclusive key; object form accepts key, scope, and mode.',
  anyOf: [
    { type: 'string', minLength: 1 },
    openObject('Structured runtime resource.', {
      key: stringField('Resource key.'),
      scope: stringField('Resource scope.', { enumValues: ['task', 'mission', 'project', 'global'] }),
      mode: stringField('Sharing mode.', { enumValues: ['shared', 'exclusive'] })
    }, ['key'])
  ]
};

const TASK = openObject('One bounded Mission task. contract and owner are required when tasks are supplied explicitly.', {
  id: stringField('Stable task id. Defaults to T1, T2, ... when omitted.'),
  contract: stringField('Observable task contract / behavior to implement.'),
  owner: stringField('Repository or product boundary that owns this task.'),
  dependencies: stringArray('Task ids that must complete first.', { maxItems: 64 }),
  writeSet: stringArray('Predicted repository paths this task may modify.'),
  protectedPaths: stringArray('Paths this task must not modify.'),
  risk: stringField('Task risk classification.', { enumValues: RISK_LEVELS }),
  validationCapability: stringField('Named validation capability that should falsify this task.', { minLength: null }),
  worker: stringField('Configured worker profile id.', { minLength: null }),
  notes: stringField('Optional bounded implementation notes.', { minLength: null }),
  sensingCapabilities: stringArray('Sensing capabilities required by the task.', { maxItems: 32 }),
  executionCapabilities: stringArray('Execution capabilities required by the task.', { maxItems: 32 }),
  coordinationKeys: stringArray('Project-scoped exclusive coordination keys.', { maxItems: 32 }),
  runtimeResources: {
    type: 'array',
    items: RUNTIME_RESOURCE,
    maxItems: 32,
    description: 'Shared/exclusive runtime resources used for conflict-aware admission.'
  }
}, ['contract', 'owner']);

const CREDENTIAL_REFERENCE = openObject('Reference to a credential resolved by the runtime credential broker; secret values are never sent in tool arguments.', {
  provider: stringField('Credential provider id; defaults to environment.', { minLength: null }),
  name: stringField('Credential name in the provider.'),
  targetEnv: stringField('Environment variable name exposed only to the authorized child process.', { minLength: null })
}, ['name']);

const BOOTSTRAP_AUTHORIZATION = openObject('Explicit authorization for reproducible project bootstrap before worker execution.', {
  execute: booleanField('Whether runtime bootstrap steps may execute.'),
  allowNetwork: booleanField('Allow bootstrap steps declared as network-using.'),
  allowThirdPartyCode: booleanField('Allow bootstrap steps that may execute third-party code.'),
  credentialRefs: { type: 'array', items: CREDENTIAL_REFERENCE, maxItems: 64, description: 'Credential references materialized only for the bootstrap process.' }
});

const FINDING = openObject('Review finding. Unknown provider-specific fields are preserved.', {
  severity: stringField('Finding severity.', { enumValues: ['low', 'medium', 'high', 'critical'] }),
  code: stringField('Stable finding code.', { minLength: null }),
  message: stringField('Human-readable finding summary.', { minLength: null })
});

const TOOL_INPUT_CONTRACTS = Object.freeze({
  project_open: {
    description: 'Bind a repository. Provide exactly one of repoPath or repoUrl; the runtime enforces the XOR and surface capability rules.',
    properties: {
      repoPath: stringField('Existing repository path on the runtime machine. Mutually exclusive with repoUrl.'),
      repoUrl: stringField('Authorized Git repository URL to acquire into runtime-managed storage. Mutually exclusive with repoPath.'),
      name: stringField('Optional display name for the project.', { minLength: null }),
      refreshRemote: booleanField('For a managed remote checkout, fetch and fast-forward before opening. Defaults to true.')
    },
    required: []
  },
  project_snapshot: {
    description: 'Refresh authoritative source/environment/bootstrap identity for an opened project.',
    properties: { projectId: stringField('Opened project id.') },
    required: ['projectId']
  },
  mission_plan: {
    description: 'Create a dependency-aware Mission. Explicit tasks are optional when an operator-configured plannerProvider can generate them.',
    properties: {
      projectId: stringField('Opened project id.'),
      goal: stringField('Product/engineering outcome to achieve.'),
      doneDefinition: stringField('Observable completion definition.'),
      nonGoals: stringArray('Explicit scope exclusions.'),
      riskEnvelope: stringField('Maximum Mission risk envelope.', { enumValues: RISK_LEVELS }),
      tasks: { type: 'array', items: TASK, minItems: 1, maxItems: 64, description: 'Optional explicit task DAG. Omit to use plannerProvider.' }
    },
    required: ['projectId', 'goal', 'doneDefinition']
  },
  mission_execute: {
    description: 'Dispatch or execute the next safe Mission wave.',
    properties: {
      missionId: stringField('Mission id.'),
      runWorkers: booleanField('Run configured coding workers now; false only creates dispatch packets.'),
      bootstrapAuthorization: BOOTSTRAP_AUTHORIZATION
    },
    required: ['missionId']
  },
  mission_status: { properties: { missionId: stringField('Mission id.') }, required: ['missionId'] },
  mission_advance: {
    description: 'Advance one Mission state-machine step; runWorkers is only used when the current phase is execution.',
    properties: { missionId: stringField('Mission id.'), runWorkers: booleanField('Allow configured worker execution while advancing execution phase.') },
    required: ['missionId']
  },
  mission_readiness: { properties: { missionId: stringField('Mission id.') }, required: ['missionId'] },
  mission_timeline: { properties: { missionId: stringField('Mission id.') }, required: ['missionId'] },
  mission_cancel: {
    properties: { missionId: stringField('Mission id.'), reason: stringField('Cancellation reason; defaults to operator-request.', { minLength: null }) },
    required: ['missionId']
  },
  mission_resume: { properties: { missionId: stringField('Interrupted Mission id.') }, required: ['missionId'] },
  task_result_commit: {
    description: 'Accept an externally produced task worktree result, enforce scope/ownership, commit it, then integrate serially.',
    properties: { missionId: stringField('Mission id.'), taskId: stringField('Task id.') },
    required: ['missionId', 'taskId']
  },
  worker_cancel: { properties: { missionId: stringField('Mission id.'), taskId: stringField('Executing task id.') }, required: ['missionId', 'taskId'] },
  worker_resume: { properties: { missionId: stringField('Mission id.'), taskId: stringField('Interrupted task id.') }, required: ['missionId', 'taskId'] },
  worker_retry: { properties: { missionId: stringField('Mission id.'), taskId: stringField('Failed or cancelled task id.') }, required: ['missionId', 'taskId'] },
  evidence_query: {
    description: 'Query bounded evidence metadata by scope or stable ids.',
    properties: {
      projectId: stringField('Optional project filter.'),
      missionId: stringField('Optional Mission filter.'),
      taskId: stringField('Optional task filter.'),
      type: stringField('Optional evidence type filter.'),
      ids: stringArray('Optional exact evidence ids. Required when includeImages=true.'),
      limit: integerField('Maximum records to return; runtime clamps to 1..200.', 1, 200),
      includeImages: booleanField('Also return bounded browser-screenshot attachments as MCP image content. Requires 1..4 unique exact evidence ids; structured evidence metadata is unchanged.'),
      maxImages: integerField('Maximum screenshot images to return when includeImages=true; runtime clamps to 1..4.', 1, 4)
    },
    required: []
  },
  validation_capabilities: { properties: { projectId: stringField('Opened project id.') }, required: ['projectId'] },
  validation_run: {
    description: 'Run a configured validation capability in isolated source. For ordinary use provide projectId plus capability and optionally Mission/candidate scope. rawCommand is an explicitly gated escape hatch.',
    properties: {
      projectId: stringField('Opened project id.'),
      missionId: stringField('Optional Mission scope.'),
      candidateId: stringField('Optional immutable candidate scope.'),
      capability: stringField('Configured validation capability name. May be omitted only when using allowed rawCommand.', { minLength: null }),
      rawCommand: { type: 'array', items: { type: 'string', minLength: 1 }, minItems: 1, description: 'Explicit argv command; requires operator allowRawValidation and confirmRawValidation=true.' },
      confirmRawValidation: booleanField('Explicit confirmation for rawCommand.'),
      purpose: stringField('Validation purpose.', { enumValues: VALIDATION_PURPOSES }),
      targetCommitSha: stringField('Integrated Mission commit to observe for runtime-feedback only.', { minLength: null })
    },
    required: ['projectId']
  },
  review_run: { properties: { missionId: stringField('Mission id.'), candidateId: stringField('Optional immutable candidate id.') }, required: ['missionId'] },
  semantic_review_run: { properties: { missionId: stringField('Mission id.'), candidateId: stringField('Optional immutable candidate id.') }, required: ['missionId'] },
  remediation_plan: {
    description: 'Create a bounded remediation proposal, or with apply=true and explicit task specs append source-bound remediation work to the same failed-review Mission and re-enter execution.',
    properties: {
      missionId: stringField('Mission id.'),
      findings: { type: 'array', items: FINDING, description: 'Optional explicit findings; defaults to current deterministic + semantic review findings.' },
      maxTasks: integerField('Maximum remediation tasks.', 1, 8),
      apply: booleanField('When true, append the explicit tasks to the same source-bound Mission and reset proof state for re-execution. Defaults to false.'),
      tasks: { type: 'array', items: TASK, minItems: 1, maxItems: 8, description: 'Explicit executable remediation task specs. Required by runtime when apply=true; owner/writeSet/risk must come from repository/review evidence, not guesses.' }
    },
    required: ['missionId']
  },
  candidate_preflight: { properties: { missionId: stringField('Mission id.') }, required: ['missionId'] },
  candidate_refresh: { properties: { missionId: stringField('Mission id.'), reason: stringField('Refresh reason.', { minLength: null }) }, required: ['missionId'] },
  candidate_status: { properties: { missionId: stringField('Mission id.'), candidateId: stringField('Optional candidate id; defaults to active candidate.') }, required: ['missionId'] },
  experience_query: {
    description: 'Query reviewed active project experience. Current repository/runtime truth always has precedence.',
    properties: {
      projectId: stringField('Project id.'),
      mechanism: stringField('Optional mechanism filter.'),
      sourceHead: stringField('Optional current source commit for freshness classification.'),
      limit: integerField('Maximum records; runtime clamps to 0..50.', 0, 50)
    },
    required: ['projectId']
  },
  experience_commit: {
    properties: {
      projectId: stringField('Project id.'),
      mechanism: stringField('Mechanism this lesson describes.'),
      statement: stringField('Evidence-backed lesson statement.'),
      kind: stringField('Experience kind/category.'),
      evidenceIds: stringArray('Supporting evidence ids.'),
      equivalenceClass: stringField('Optional equivalence class for conflict detection.', { minLength: null }),
      appliesWhen: stringField('Optional applicability condition.', { minLength: null }),
      doesNotApplyWhen: stringField('Optional anti-scope condition.', { minLength: null }),
      scopeType: stringField('Scope type; defaults to project.', { minLength: null }),
      scopeId: stringField('Scope identity; defaults to projectId.', { minLength: null }),
      sourceIdentity: openObject('Optional source identity supporting the experience.'),
      expiresAt: stringField('Optional ISO timestamp after which the experience is stale.', { minLength: null }),
      supersedes: stringArray('Experience ids superseded by this candidate.')
    },
    required: ['projectId', 'mechanism', 'statement', 'kind']
  },
  experience_review: {
    properties: {
      experienceId: stringField('Experience id.'),
      action: stringField('Review action.', { enumValues: EXPERIENCE_REVIEW_ACTIONS }),
      reviewer: stringField('Reviewer identity; defaults to operator.', { minLength: null }),
      evidenceIds: stringArray('Evidence ids supporting the review decision.')
    },
    required: ['experienceId', 'action']
  },
  experience_challenge: {
    properties: { experienceId: stringField('Active experience id.'), statement: stringField('Contrary evidence statement.'), evidenceIds: stringArray('Supporting evidence ids.') },
    required: ['experienceId', 'statement']
  },
  experience_audit: { properties: { projectId: stringField('Optional project filter.'), sourceHead: stringField('Optional current source commit for freshness classification.') }, required: [] },
  experience_compact: { properties: { projectId: stringField('Project id.') }, required: ['projectId'] },
  runtime_health: { properties: {}, required: [] },
  runtime_integrity: { properties: {}, required: [] },
  runtime_cleanup: { properties: { apply: booleanField('When true, remove runtime-owned orphan worktrees/candidate refs after blocker rechecks; false is inspection only.') }, required: [] },
  runtime_maintenance: { properties: { projectId: stringField('Optional project scope for experience audit.') }, required: [] },
  handoff_export: { properties: { missionId: stringField('Mission id to export.') }, required: ['missionId'] }
});

const TOOL_DESCRIPTIONS = Object.freeze({
  project_open: 'Open a local Git project or safely acquire an authorized remote repository and capture exact source identity.',
  project_snapshot: 'Refresh repository identity, dirty state, environment readiness, and bootstrap signals.',
  mission_plan: 'Create a dependency-aware mission plan with quality, capability, and write-conflict gates.',
  mission_execute: 'Dispatch or execute ready worker waves inside isolated worktrees.',
  mission_status: 'Read current mission, task, validation, review, candidate, and merge-proposal status.',
  mission_advance: 'Advance the mission state machine through execution, proof gates, immutable candidate creation, and finalization.',
  mission_readiness: 'Explain whether a mission is safe and ready for its next transition.',
  mission_timeline: 'Return the durable mission event timeline.',
  mission_cancel: 'Cancel a mission and drain runtime-owned execution without mutating the user branch.',
  mission_resume: 'Resume an interrupted mission after conservative reconciliation.',
  task_result_commit: 'Commit an externally produced task result after scope and ownership checks.',
  worker_cancel: 'Request cancellation of an executing worker.',
  worker_resume: 'Resume an interrupted worker task after reconciliation.',
  worker_retry: 'Retry a failed worker task with a new dispatch identity.',
  evidence_query: 'Query bounded evidence records and artifact pointers.',
  validation_capabilities: 'List operator-defined repository validation capabilities.',
  validation_run: 'Run an allowed command, service, browser, or observability validation in isolated source.',
  review_run: 'Run deterministic whole-change review against the mission base.',
  semantic_review_run: 'Run the configured independent semantic reviewer provider.',
  remediation_plan: 'Create a bounded remediation proposal or explicitly append source-bound repair tasks to the same Mission for re-execution.',
  candidate_preflight: 'Read-only preflight the mission candidate against current source using merge-tree.',
  candidate_refresh: 'Create a new immutable candidate after source drift and invalidate stale proof.',
  candidate_status: 'Read immutable candidate identity and proof freshness.',
  experience_query: 'Retrieve reviewed active project experience without allowing candidates to influence execution.',
  experience_commit: 'Persist a candidate experience backed by evidence.',
  experience_review: 'Activate, reject, reactivate, or retire an experience after review.',
  experience_challenge: 'Challenge an active experience with contrary evidence.',
  experience_audit: 'Audit experience freshness, conflicts, evidence, and lifecycle state.',
  experience_compact: 'Compact exact duplicate candidate experiences without auto-activation.',
  runtime_health: 'Report runtime, state, MCP transport mode, surface capability, and protocol health.',
  runtime_integrity: 'Verify audit hash chain, state readability, and runtime invariants.',
  runtime_cleanup: 'Inspect or remove orphaned runtime-owned temporary resources.',
  runtime_maintenance: 'Run conservative reconciliation and maintenance tasks.',
  handoff_export: 'Export a compact resumable project/mission handoff bundle.'
});

export const TOOL_NAMES = Object.freeze(Object.keys(TOOL_DESCRIPTIONS));
export const TOOL_DEFINITIONS = Object.freeze(TOOL_NAMES.map((name) => ({ name, description: TOOL_DESCRIPTIONS[name] })));
export { REQUEST_ID_TOOL_NAMES };

export function toolRequiresRequestId(name) {
  return REQUEST_ID_TOOL_SET.has(name);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function inputContract(name) {
  const contract = TOOL_INPUT_CONTRACTS[name];
  if (!contract) throw new Error(`Unknown public tool input contract: ${name}`);
  return contract;
}

export function toolInputJsonSchema(name) {
  const contract = inputContract(name);
  const properties = clone(contract.properties || {});
  const required = [...(contract.required || [])];
  if (toolRequiresRequestId(name)) {
    properties.requestId = stringField('Stable idempotency key for this mutating operation. Reuse only for an identical logical request.');
    required.unshift('requestId');
  }
  return {
    type: 'object',
    ...(contract.description ? { description: contract.description } : {}),
    properties,
    ...(required.length ? { required: [...new Set(required)] } : {}),
    additionalProperties: true
  };
}

function schemaToZod(z, schema = {}) {
  if (Array.isArray(schema.anyOf) && schema.anyOf.length) {
    const variants = schema.anyOf.map((item) => schemaToZod(z, item));
    let union = variants.length === 1 ? variants[0] : z.union(variants);
    if (schema.description && typeof union.describe === 'function') union = union.describe(schema.description);
    return union;
  }

  let result;
  if (Array.isArray(schema.enum) && schema.enum.length) {
    result = z.enum(schema.enum);
  } else if (schema.type === 'string') {
    result = z.string();
    if (Number.isInteger(schema.minLength)) result = result.min(schema.minLength);
    if (Number.isInteger(schema.maxLength)) result = result.max(schema.maxLength);
  } else if (schema.type === 'boolean') {
    result = z.boolean();
  } else if (schema.type === 'integer' || schema.type === 'number') {
    result = z.number();
    if (schema.type === 'integer') result = result.int();
    if (Number.isFinite(schema.minimum)) result = result.min(schema.minimum);
    if (Number.isFinite(schema.maximum)) result = result.max(schema.maximum);
  } else if (schema.type === 'array') {
    result = z.array(schemaToZod(z, schema.items || {}));
    if (Number.isInteger(schema.minItems)) result = result.min(schema.minItems);
    if (Number.isInteger(schema.maxItems)) result = result.max(schema.maxItems);
  } else if (schema.type === 'object') {
    const required = new Set(schema.required || []);
    const shape = {};
    for (const [key, child] of Object.entries(schema.properties || {})) {
      let childSchema = schemaToZod(z, child);
      if (!required.has(key)) childSchema = childSchema.optional();
      shape[key] = childSchema;
    }
    result = z.object(shape);
    result = schema.additionalProperties === false ? result.strict() : result.passthrough();
  } else {
    result = z.any();
  }
  if (schema.description && typeof result.describe === 'function') result = result.describe(schema.description);
  return result;
}

export function toolInputZodSchema(z, name) {
  return schemaToZod(z, toolInputJsonSchema(name));
}

if (TOOL_NAMES.length !== 34) {
  throw new Error(`Veteran Engineer MCP surface must contain exactly 34 tools, got ${TOOL_NAMES.length}`);
}
if (Object.keys(TOOL_INPUT_CONTRACTS).length !== TOOL_NAMES.length) {
  throw new Error(`Every public tool must have exactly one input contract; got ${Object.keys(TOOL_INPUT_CONTRACTS).length} contracts for ${TOOL_NAMES.length} tools`);
}
for (const name of REQUEST_ID_TOOL_NAMES) {
  if (!TOOL_NAMES.includes(name)) throw new Error(`Unknown requestId-requiring tool in catalog: ${name}`);
}
