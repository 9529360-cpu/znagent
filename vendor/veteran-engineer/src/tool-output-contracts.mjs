import { TOOL_NAMES } from './tool-catalog.mjs';

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

function stringArray(description) {
  return { type: 'array', items: { type: 'string' }, description };
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

function outputArray(description, items = openObject('Result record.')) {
  return { type: 'array', description, items };
}

function anyField(description) {
  return { description };
}

function nullable(schema) {
  return { anyOf: [schema, { type: 'null' }] };
}

const FINDING = openObject('Review finding. Unknown provider-specific fields are preserved.', {
  severity: stringField('Finding severity.', { enumValues: ['low', 'medium', 'high', 'critical'] }),
  code: stringField('Stable finding code.', { minLength: null }),
  message: stringField('Human-readable finding summary.', { minLength: null })
});

const REQUIREMENT_RESULT = openObject('Semantic acceptance result for one required outcome clause.', {
  id: stringField('Acceptance criterion id.'),
  status: stringField('Acceptance proof status.', { enumValues: ['passed', 'failed', 'unproven'] }),
  evidence: stringArray('Concrete evidence supporting the result.')
}, ['id', 'status', 'evidence']);

const OUTPUT_PROJECT = openObject('Opened project record. Its id is the projectId for subsequent project and Mission tools.', {
  id: stringField('Stable project id to pass as projectId.'),
  name: stringField('Project display name.', { minLength: null }),
  repoPath: stringField('Repository path owned or referenced by this runtime.', { minLength: null }),
  remoteUrl: nullable(stringField('Sanitized origin URL when available.', { minLength: null })),
  sourceIdentity: openObject('Authoritative repository source identity.'),
  environmentReadiness: anyField('Environment readiness projection.'),
  bootstrapPlan: anyField('Repository-derived bootstrap plan.')
}, ['id']);

const OUTPUT_MISSION = openObject('Mission record. Its id is the missionId for execution, status, validation, candidate, and handoff tools.', {
  id: stringField('Stable Mission id to pass as missionId.'),
  projectId: stringField('Owning project id.'),
  phase: stringField('Current Mission phase.', { minLength: null }),
  status: stringField('Current Mission status.', { minLength: null }),
  activeCandidateId: nullable(stringField('Active immutable candidate id when one exists.', { minLength: null })),
  activeMergeProposalId: nullable(stringField('Active merge-proposal id when one exists.', { minLength: null }))
}, ['id', 'status']);

const OUTPUT_TASK = openObject('Mission task record.', {
  id: stringField('Stable task id.'),
  missionId: stringField('Owning Mission id.', { minLength: null }),
  status: stringField('Current task status.', { minLength: null }),
  commitSha: nullable(stringField('Task commit when completed.', { minLength: null })),
  evidenceIds: stringArray('Evidence ids produced by the task.')
});

const OUTPUT_CANDIDATE = openObject('Immutable candidate record.', {
  id: stringField('Stable candidate id.'),
  missionId: stringField('Owning Mission id.', { minLength: null }),
  commitSha: stringField('Immutable candidate commit.', { minLength: null }),
  proofFresh: booleanField('Whether required proof still matches current authority.')
});

const OUTPUT_EVIDENCE_ATTACHMENT = openObject('Durable evidence attachment metadata. Attachment bytes stay out of structuredContent and may be projected separately as MCP content.', {
  name: stringField('Original bounded attachment name.', { minLength: null }),
  kind: stringField('Attachment kind.', { minLength: null }),
  artifactPointer: stringField('Runtime-owned artifact pointer.', { minLength: null }),
  artifactHash: stringField('SHA-256 of the stored attachment.', { minLength: null }),
  bytes: integerField('Stored attachment byte length.', 0, Number.MAX_SAFE_INTEGER)
}, ['artifactPointer', 'artifactHash', 'bytes']);

const OUTPUT_EVIDENCE = openObject('Evidence metadata record.', {
  id: stringField('Stable evidence id.'),
  projectId: stringField('Owning project id.', { minLength: null }),
  missionId: nullable(stringField('Optional Mission id.', { minLength: null })),
  taskId: nullable(stringField('Optional task id.', { minLength: null })),
  type: stringField('Evidence type.', { minLength: null }),
  summary: stringField('Bounded evidence summary.', { minLength: null }),
  artifactPointer: nullable(stringField('Runtime artifact pointer when one exists.', { minLength: null })),
  artifactHash: nullable(stringField('SHA-256 for the primary evidence artifact when one exists.', { minLength: null })),
  attachments: { type: 'array', items: OUTPUT_EVIDENCE_ATTACHMENT, description: 'Durable attachment metadata; binary data is never embedded here.' },
  createdAt: stringField('Evidence creation time.', { minLength: null })
});

const OUTPUT_VALIDATION_CAPABILITY = openObject('Configured validation capability.', {
  name: stringField('Capability name used by validation_run.', { minLength: null }),
  type: stringField('Capability type.', { minLength: null }),
  tier: integerField('Validation tier when materialized.', 0, 2),
  command: anyField('Configured validation command when applicable.'),
  runtimeResources: anyField('Declared runtime resources used for conflict-aware admission.')
});

const OUTPUT_EXPERIENCE = openObject('Project experience record.', {
  id: stringField('Stable experience id.'),
  projectId: stringField('Owning project id.', { minLength: null }),
  mechanism: stringField('Mechanism described by the experience.', { minLength: null }),
  statement: stringField('Evidence-backed lesson statement.', { minLength: null }),
  status: stringField('Experience lifecycle status.', { minLength: null }),
  evidenceIds: stringArray('Supporting evidence ids.'),
  freshness: stringField('Freshness classification when queried.', { minLength: null })
}, ['id', 'projectId', 'status', 'evidenceIds']);

const TOOL_OUTPUT_CONTRACTS = Object.freeze({
  project_open: OUTPUT_PROJECT,
  project_snapshot: OUTPUT_PROJECT,
  mission_plan: openObject('Created Mission and its initial task DAG.', {
    mission: OUTPUT_MISSION,
    tasks: { type: 'array', items: OUTPUT_TASK, description: 'Planned Mission tasks.' }
  }, ['mission', 'tasks']),
  mission_execute: openObject('Execution dispatch/result for the current safe Mission wave. Fields are variant-dependent but missionId is always present.', {
    missionId: stringField('Mission id.'),
    phase: stringField('Current/next Mission phase when execution is already complete or no executable wave remains.', { minLength: null }),
    message: stringField('Bounded execution status message for already-complete phases.', { minLength: null }),
    waveIndex: integerField('Current Mission wave index when wave-scoped state is returned.', 0, Number.MAX_SAFE_INTEGER),
    completed: booleanField('Whether the current execution/wave completion transition completed.'),
    reason: stringField('Machine-readable execution state reason.', { minLength: null }),
    admitted: stringArray('Task ids admitted for execution when admission is the limiting step.'),
    waveBase: stringField('Mission integration head used as the worker wave base.', { minLength: null }),
    pending: { type: 'array', items: openObject('Outstanding task dispatch.', {
      taskId: stringField('Task id.'),
      status: stringField('Current task/dispatch status.', { minLength: null }),
      dispatchId: nullable(stringField('Latest dispatch id when present.', { minLength: null }))
    }, ['taskId', 'status']), description: 'Outstanding admitted/dispatched/executing/cancelling/interrupted tasks.' },
    tasks: { type: 'array', items: openObject('Task requiring an explicit retry.', {
      taskId: stringField('Task id.'),
      status: stringField('Failed/cancelled task status.', { minLength: null })
    }, ['taskId', 'status']), description: 'Failed/cancelled tasks that require retry before the wave can progress.' },
    dispatched: { type: 'array', items: openObject('Prepared external worker dispatch.', {
      taskId: stringField('Task id.'),
      dispatchId: stringField('Stable dispatch id.', { minLength: null }),
      worktreePath: stringField('Runtime-owned task worktree path.', { minLength: null }),
      packetPath: stringField('Worker packet artifact path.', { minLength: null }),
      packet: anyField('Durable worker packet payload.')
    }, ['taskId', 'dispatchId']), description: 'Prepared dispatch packets when runWorkers=false.' },
    results: { type: 'array', items: openObject('Per-task runtime worker/integration result.', {
      taskId: stringField('Task id.'),
      ok: booleanField('Whether worker execution and serial integration completed successfully.'),
      commitSha: nullable(stringField('Worker task commit when one was created and accepted.', { minLength: null })),
      discardedCommitSha: nullable(stringField('Discarded task commit when Mission cancellation fenced integration.', { minLength: null })),
      bootstrap: anyField('Bootstrap execution result when authorized.'),
      bootstrapEvidenceId: nullable(stringField('Bootstrap evidence id when present.', { minLength: null })),
      runtime: openObject('Bounded worker runtime outcome.', {
        namespace: nullable(stringField('Runtime namespace/container identity when present.', { minLength: null })),
        durationMs: nullable(integerField('Worker runtime duration in milliseconds when known.', 0, Number.MAX_SAFE_INTEGER)),
        termination: anyField('Worker termination projection.'),
        outputCapture: anyField('Bounded worker output-capture projection.')
      }),
      error: nullable(openObject('Worker failure summary.', {
        code: stringField('Stable worker failure code.', { minLength: null }),
        message: stringField('Bounded worker failure message.', { minLength: null })
      }))
    }, ['taskId', 'ok']), description: 'Per-task worker/commit results when runtime workers ran.' },
    preparationFailures: { type: 'array', items: openObject('Task preparation failure before worker launch.', {
      taskId: stringField('Task id.'),
      code: stringField('Stable preparation failure code.', { minLength: null }),
      message: stringField('Bounded preparation failure message.', { minLength: null }),
      bootstrapEvidenceId: nullable(stringField('Bootstrap-failure evidence id when present.', { minLength: null }))
    }, ['taskId', 'code', 'message']), description: 'Task worktree/bootstrap/dispatch preparation failures.' }
  }, ['missionId']),
  mission_status: openObject('Current Mission aggregate status.', {
    mission: OUTPUT_MISSION,
    tasks: { type: 'array', items: OUTPUT_TASK, description: 'Mission tasks.' },
    candidates: { type: 'array', items: OUTPUT_CANDIDATE, description: 'Immutable Mission candidates.' },
    mergeProposals: { type: 'array', items: openObject('Operator merge proposal.'), description: 'Durable merge proposals.' }
  }, ['mission', 'tasks']),
  mission_advance: openObject('Result of one authoritative Mission state-machine transition.', {
    action: stringField('Transition action taken.', { minLength: null }),
    nextPhase: stringField('Next Mission phase when supplied.', { minLength: null }),
    requiresOperatorAction: booleanField('Whether the transition requires operator action.'),
    result: anyField('Nested result for candidate or validation/review transitions.'),
    proposal: anyField('Merge proposal when finalization reaches operator handoff.')
  }),
  mission_readiness: openObject('Readiness decision for the next Mission transition.', {
    missionId: stringField('Mission id.'),
    ready: booleanField('Whether the next transition is currently safe.'),
    phase: stringField('Current Mission phase.', { minLength: null }),
    status: stringField('Current Mission status.', { minLength: null }),
    blockers: { type: 'array', items: openObject('Readiness blocker.'), description: 'Explicit blockers preventing the next transition.' },
    nextAction: nullable(stringField('Next safe action when known.', { minLength: null })),
    operatorActionRequired: booleanField('Whether progress requires operator action.'),
    capabilitySnapshot: anyField('Current worker/capability admission snapshot.')
  }, ['missionId', 'ready', 'phase', 'status']),
  mission_timeline: outputArray('Durable Mission timeline events.', openObject('Mission timeline event.', {
    type: stringField('Event type.', { minLength: null }),
    missionId: stringField('Mission id.', { minLength: null }),
    at: stringField('Event timestamp.', { minLength: null })
  })),
  mission_cancel: openObject('Cancelled Mission record plus runtime drain/reconciliation details.', {
    id: stringField('Mission id.', { minLength: null }),
    status: stringField('Mission status after cancellation.', { minLength: null }),
    workerDrain: anyField('Worker drain result.'),
    capabilityLeaseReconciliation: anyField('Capability-lease reconciliation result.'),
    runtimeFeedbackSessionsReleased: integerField('Released runtime-feedback session count.', 0, Number.MAX_SAFE_INTEGER)
  }),
  mission_resume: openObject('Resumed/reconciled Mission record.', {
    id: stringField('Mission id.', { minLength: null }),
    status: stringField('Mission status after resume reconciliation.', { minLength: null }),
    capabilityLeaseReconciliation: anyField('Capability-lease reconciliation result.')
  }),
  task_result_commit: openObject('Accepted external task result and serial integration outcome.', {
    taskId: stringField('Task id.', { minLength: null }),
    missionId: stringField('Mission id.', { minLength: null }),
    commitSha: nullable(stringField('Task or integrated commit SHA.', { minLength: null })),
    integrationSha: nullable(stringField('Integrated Mission SHA when present.', { minLength: null })),
    ok: booleanField('Whether commit/integration completed successfully.')
  }),
  worker_cancel: openObject('Worker cancellation result.', {
    missionId: stringField('Mission id.', { minLength: null }),
    taskId: stringField('Task id.', { minLength: null }),
    signalled: booleanField('Whether an active worker received a cancellation signal.'),
    status: stringField('Worker/task status after cancellation.', { minLength: null })
  }),
  worker_resume: openObject('Worker resume/reconciliation result.', {
    missionId: stringField('Mission id.', { minLength: null }),
    taskId: stringField('Task id.', { minLength: null }),
    status: stringField('Worker/task status after resume.', { minLength: null }),
    commitSha: nullable(stringField('Produced commit SHA when completed.', { minLength: null }))
  }),
  worker_retry: openObject('Retried task record or worker-dispatch result.', {
    id: stringField('Task id when a task record is returned.', { minLength: null }),
    missionId: stringField('Mission id.', { minLength: null }),
    taskId: stringField('Task id when a dispatch result is returned.', { minLength: null }),
    status: stringField('Task/worker status.', { minLength: null })
  }),
  evidence_query: outputArray('Evidence records matching the query.', OUTPUT_EVIDENCE),
  validation_capabilities: outputArray('Validation capabilities configured for the project.', OUTPUT_VALIDATION_CAPABILITY),
  validation_run: openObject('Validation result and bound evidence.', {
    passed: booleanField('Whether the validation passed.'),
    capability: stringField('Validation capability name.', { minLength: null }),
    evidenceId: stringField('Evidence id created for this validation.', { minLength: null }),
    sourceCommitSha: stringField('Commit that was actually validated.', { minLength: null }),
    exitCode: nullable(integerField('Process exit code when command-backed.', -2147483648, 2147483647))
  }, ['evidenceId']),
  review_run: openObject('Deterministic whole-change review result.', {
    passed: booleanField('Whether deterministic review passed.'),
    head: stringField('Reviewed head commit.', { minLength: null }),
    reviewBase: stringField('Review base commit.', { minLength: null }),
    findings: { type: 'array', items: FINDING, description: 'Review findings.' },
    evidenceId: stringField('Review evidence id.', { minLength: null })
  }, ['passed']),
  semantic_review_run: openObject('Independent semantic review result.', {
    passed: booleanField('Whether semantic review passed.'),
    findings: { type: 'array', items: FINDING, description: 'Semantic findings.' },
    requirementResults: { type: 'array', items: REQUIREMENT_RESULT, description: 'One evidence-bearing result per Mission acceptance obligation when semantic review is configured.' },
    evidenceId: stringField('Review evidence id.', { minLength: null })
  }, ['passed']),
  remediation_plan: openObject('Bounded remediation proposal or source-bound same-Mission re-entry derived from review findings.', {
    id: stringField('Remediation plan id.', { minLength: null }),
    missionId: stringField('Mission id.', { minLength: null }),
    applied: booleanField('Whether executable remediation tasks were appended and the Mission re-entered execution.'),
    sourceHead: stringField('Reviewed Mission head used as the remediation wave base when applied.', { minLength: null }),
    reviewKind: stringField('Review authority that triggered applied remediation.', { minLength: null }),
    taskIds: stringArray('Applied remediation task ids.'),
    tasks: { type: 'array', items: OUTPUT_TASK, description: 'Proposed or applied remediation tasks.' },
    findings: { type: 'array', items: FINDING, description: 'Findings addressed by the plan.' }
  }, ['missionId', 'applied', 'tasks', 'findings']),
  candidate_preflight: openObject('Read-only candidate/source preflight result.', {
    missionId: stringField('Mission id.'),
    candidateId: nullable(stringField('Candidate id when present.', { minLength: null })),
    ready: booleanField('Whether candidate creation/finalization is safe.'),
    sourceDrift: booleanField('Whether source authority drifted.')
  }, ['ready']),
  candidate_refresh: openObject('Created/refreshed immutable candidate.', {
    candidate: OUTPUT_CANDIDATE,
    evidenceId: stringField('Evidence id for candidate creation.', { minLength: null }),
    requiresRevalidation: booleanField('Whether source drift invalidated prior proof.')
  }),
  candidate_status: openObject('Candidate status for a Mission.', {
    missionId: stringField('Mission id.'),
    candidate: anyField('Active/requested candidate record, or null when no candidate exists.')
  }, ['missionId']),
  experience_query: openObject('Reviewed active experience safe to inform execution.', {
    items: { type: 'array', items: OUTPUT_EXPERIENCE, description: 'Usable active experiences.' },
    excludedConflicts: integerField('Conflicting active experiences excluded from use.', 0, Number.MAX_SAFE_INTEGER),
    note: stringField('Experience precedence/lifecycle note.', { minLength: null })
  }, ['items']),
  experience_commit: OUTPUT_EXPERIENCE,
  experience_review: OUTPUT_EXPERIENCE,
  experience_challenge: OUTPUT_EXPERIENCE,
  experience_audit: outputArray('Experience lifecycle/freshness audit records.', openObject('Experience audit record.', {
    id: stringField('Experience id.', { minLength: null }),
    projectId: stringField('Owning project id.', { minLength: null }),
    status: stringField('Lifecycle status.', { minLength: null }),
    mechanism: stringField('Mechanism.', { minLength: null }),
    freshness: stringField('Freshness classification.', { minLength: null }),
    evidenceMissing: stringArray('Missing supporting evidence ids.'),
    usage: anyField('Usage accounting projection.')
  }, ['id', 'projectId', 'status'])),
  experience_compact: openObject('Exact-duplicate candidate compaction result.', {
    removed: stringArray('Removed duplicate candidate experience ids.'),
    kept: stringArray('Retained canonical candidate experience ids.')
  }, ['removed', 'kept']),
  runtime_health: openObject('Runtime health and protocol/capability identity.', {
    name: stringField('Runtime name.'),
    version: stringField('Runtime version.'),
    stateSchemaVersion: integerField('Durable state schema version.', 1, Number.MAX_SAFE_INTEGER),
    stateRoot: stringField('Runtime state root.', { minLength: null }),
    stateReadable: booleanField('Whether durable state is readable.'),
    mcp: openObject('Effective MCP implementation and protocol eras.'),
    surface: openObject('Effective surface capability profile.'),
    toolCount: integerField('Public MCP tool count.', 0, 10000),
    toolSurface: anyField('Published tool surface identity.'),
    at: stringField('Health observation timestamp.', { minLength: null })
  }, ['name', 'version', 'toolCount']),
  runtime_integrity: openObject('Runtime/audit integrity result.', {
    ok: booleanField('Whether integrity checks passed.'),
    audit: anyField('Audit-chain integrity report.'),
    issues: { type: 'array', items: anyField('Integrity issue.'), description: 'Detected integrity issues.' },
    toolCount: integerField('Public MCP tool count.', 0, 10000)
  }, ['ok', 'toolCount']),
  runtime_cleanup: openObject('Runtime-owned cleanup inspection/application result.', {
    apply: booleanField('Whether destructive cleanup was requested.'),
    orphans: stringArray('Orphaned runtime-owned resources detected.'),
    removed: stringArray('Runtime-owned resources removed.'),
    worktrees: anyField('Runtime-owned worktree cleanup projection.'),
    candidateRefs: anyField('Runtime-owned candidate-ref cleanup projection.'),
    liveSessions: anyField('Live validation session cleanup projection.'),
    browserSessions: anyField('Browser validation session cleanup projection.')
  }),
  runtime_maintenance: openObject('Conservative runtime reconciliation/maintenance result.', {
    unknownRequests: anyField('Unknown request outcomes reconciled or remaining.'),
    experienceAudit: anyField('Experience audit projection.'),
    backupPresent: booleanField('Whether a state backup is present.'),
    at: stringField('Maintenance timestamp.', { minLength: null })
  }),
  handoff_export: openObject('Durable resumable handoff artifact and inline payload.', {
    id: stringField('Handoff id.'),
    artifactPointer: stringField('Runtime artifact pointer for the exported JSON.'),
    handoff: openObject('veteran-handoff-v1 payload.', {
      schema: stringField('Handoff schema id.'),
      project: openObject('Project identity.'),
      mission: OUTPUT_MISSION,
      tasks: { type: 'array', items: OUTPUT_TASK, description: 'Mission tasks.' },
      candidates: { type: 'array', items: OUTPUT_CANDIDATE, description: 'Mission candidates.' },
      readiness: openObject('Next-transition readiness.'),
      nextSafeAction: anyField('Next safe action, or null.')
    }, ['schema', 'project', 'mission'])
  }, ['id', 'artifactPointer', 'handoff'])
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function outputContract(name) {
  const contract = TOOL_OUTPUT_CONTRACTS[name];
  if (!contract) throw new Error(`Unknown public tool output contract: ${name}`);
  return contract;
}

export function toolOutputJsonSchema(name, { legacyEnvelope = false } = {}) {
  const contract = clone(outputContract(name));
  if (!legacyEnvelope || contract.type === 'object') return contract;
  return {
    type: 'object',
    description: `Legacy MCP envelope for ${name}; result contains the natural structured output.`,
    properties: { result: contract },
    required: ['result'],
    additionalProperties: false
  };
}

export function toolOutputStructuredContent(name, result, { legacyEnvelope = false } = {}) {
  const contract = outputContract(name);
  const isArray = Array.isArray(result);
  if (contract.type === 'array' && !isArray) throw new TypeError(`Tool ${name} output must be an array`);
  if (contract.type === 'object' && (result === null || typeof result !== 'object' || isArray)) throw new TypeError(`Tool ${name} output must be an object`);
  return legacyEnvelope && contract.type !== 'object' ? { result } : result;
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
  } else if (schema.type === 'null') {
    result = z.null();
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

export function toolOutputZodSchema(z, name) {
  return schemaToZod(z, toolOutputJsonSchema(name));
}

if (Object.keys(TOOL_OUTPUT_CONTRACTS).length !== TOOL_NAMES.length) {
  throw new Error(`Every public tool must have exactly one output contract; got ${Object.keys(TOOL_OUTPUT_CONTRACTS).length} contracts for ${TOOL_NAMES.length} tools`);
}
for (const name of TOOL_NAMES) {
  if (!TOOL_OUTPUT_CONTRACTS[name]) throw new Error(`Missing public tool output contract: ${name}`);
}
