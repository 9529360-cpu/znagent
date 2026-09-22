import { TOOL_NAMES, toolInputJsonSchema } from './tool-catalog.mjs';
import { toolOutputJsonSchema } from './tool-output-contracts.mjs';
import { TOOL_WORKFLOW_RELATIONS } from './tool-workflow-relations.mjs';

export const TOOL_WORKFLOW_BINDINGS_META_KEY = 'io.veteran-engineer/workflow-bindings';
export const TOOL_WORKFLOW_BINDINGS_SCHEMA = 'veteran-tool-workflow-bindings-v1';

const SOURCE_KINDS = new Set(['arguments', 'structuredContent']);
const IDENTITY_KEYS = new Set(['projectId', 'missionId', 'taskId', 'candidateId', 'evidenceId', 'experienceId']);
const TRANSFORMS = new Set(['identity', 'singleton-array']);
const BINDING_AVAILABILITY = new Set(['guaranteed', 'conditional']);
const SELECTION_CARDINALITIES = new Set(['one', 'many']);
const FILTER_OPERATORS = new Set(['equals', 'in']);

function identitySource(source, pointer) {
  return Object.freeze({ source, pointer });
}

function explicitBinding(target, source, pointer, transform = 'identity') {
  return Object.freeze({ target, source, pointer, transform });
}

function selectionSource(collectionPointer, itemPointer, { legacyCollectionPointer = null, filter = null } = {}) {
  return Object.freeze({
    source: 'structuredContent',
    collectionPointer,
    ...(legacyCollectionPointer === null ? {} : { legacyCollectionPointer }),
    itemPointer,
    ...(filter ? { filter: Object.freeze({ ...filter }) } : {})
  });
}

function selection(target, cardinality, sources, reason) {
  return Object.freeze({
    target,
    cardinality,
    requiredForRelation: true,
    sources: Object.freeze([...sources]),
    reason
  });
}

function relationKey(sourceTool, targetTool, kind) {
  return `${sourceTool}:${kind}:${targetTool}`;
}

const DECLARED_IDENTITY_SOURCES = Object.freeze({
  project_open: { projectId: identitySource('structuredContent', '/id') },
  project_snapshot: { projectId: identitySource('structuredContent', '/id') },
  mission_plan: {
    projectId: identitySource('structuredContent', '/mission/projectId'),
    missionId: identitySource('structuredContent', '/mission/id')
  },
  mission_execute: { missionId: identitySource('structuredContent', '/missionId') },
  mission_status: {
    projectId: identitySource('structuredContent', '/mission/projectId'),
    missionId: identitySource('structuredContent', '/mission/id'),
    candidateId: identitySource('structuredContent', '/mission/activeCandidateId')
  },
  mission_advance: { missionId: identitySource('arguments', '/missionId') },
  mission_readiness: { missionId: identitySource('structuredContent', '/missionId') },
  mission_timeline: { missionId: identitySource('arguments', '/missionId') },
  mission_cancel: { missionId: identitySource('structuredContent', '/id') },
  mission_resume: { missionId: identitySource('structuredContent', '/id') },
  task_result_commit: {
    missionId: identitySource('structuredContent', '/missionId'),
    taskId: identitySource('structuredContent', '/taskId')
  },
  worker_cancel: {
    missionId: identitySource('structuredContent', '/missionId'),
    taskId: identitySource('structuredContent', '/taskId')
  },
  worker_resume: {
    missionId: identitySource('structuredContent', '/missionId'),
    taskId: identitySource('structuredContent', '/taskId')
  },
  worker_retry: {
    missionId: identitySource('arguments', '/missionId'),
    taskId: identitySource('arguments', '/taskId')
  },
  evidence_query: {
    projectId: identitySource('arguments', '/projectId'),
    missionId: identitySource('arguments', '/missionId'),
    taskId: identitySource('arguments', '/taskId')
  },
  validation_capabilities: { projectId: identitySource('arguments', '/projectId') },
  validation_run: {
    projectId: identitySource('arguments', '/projectId'),
    missionId: identitySource('arguments', '/missionId'),
    candidateId: identitySource('arguments', '/candidateId'),
    evidenceId: identitySource('structuredContent', '/evidenceId')
  },
  review_run: {
    missionId: identitySource('arguments', '/missionId'),
    candidateId: identitySource('arguments', '/candidateId'),
    evidenceId: identitySource('structuredContent', '/evidenceId')
  },
  semantic_review_run: {
    missionId: identitySource('arguments', '/missionId'),
    candidateId: identitySource('arguments', '/candidateId'),
    evidenceId: identitySource('structuredContent', '/evidenceId')
  },
  remediation_plan: { missionId: identitySource('structuredContent', '/missionId') },
  candidate_preflight: {
    missionId: identitySource('arguments', '/missionId'),
    candidateId: identitySource('structuredContent', '/candidateId')
  },
  candidate_refresh: {
    missionId: identitySource('arguments', '/missionId'),
    candidateId: identitySource('structuredContent', '/candidate/id'),
    evidenceId: identitySource('structuredContent', '/evidenceId')
  },
  candidate_status: { missionId: identitySource('structuredContent', '/missionId') },
  experience_query: { projectId: identitySource('arguments', '/projectId') },
  experience_commit: {
    projectId: identitySource('structuredContent', '/projectId'),
    experienceId: identitySource('structuredContent', '/id')
  },
  experience_review: {
    projectId: identitySource('structuredContent', '/projectId'),
    experienceId: identitySource('arguments', '/experienceId')
  },
  experience_challenge: {
    projectId: identitySource('structuredContent', '/projectId'),
    experienceId: identitySource('arguments', '/experienceId')
  },
  experience_audit: { projectId: identitySource('arguments', '/projectId') },
  experience_compact: { projectId: identitySource('arguments', '/projectId') },
  runtime_maintenance: { projectId: identitySource('arguments', '/projectId') },
  handoff_export: { missionId: identitySource('arguments', '/missionId') }
});

const EXPLICIT_RELATION_BINDINGS = Object.freeze({
  [relationKey('validation_run', 'evidence_query', 'inspect')]: Object.freeze([
    explicitBinding('ids', 'structuredContent', '/evidenceId', 'singleton-array')
  ]),
  [relationKey('review_run', 'evidence_query', 'inspect')]: Object.freeze([
    explicitBinding('ids', 'structuredContent', '/evidenceId', 'singleton-array')
  ]),
  [relationKey('semantic_review_run', 'evidence_query', 'inspect')]: Object.freeze([
    explicitBinding('ids', 'structuredContent', '/evidenceId', 'singleton-array')
  ]),
  [relationKey('candidate_refresh', 'evidence_query', 'inspect')]: Object.freeze([
    explicitBinding('ids', 'structuredContent', '/evidenceId', 'singleton-array')
  ]),
  [relationKey('experience_commit', 'evidence_query', 'inspect')]: Object.freeze([
    explicitBinding('ids', 'structuredContent', '/evidenceIds')
  ])
});

const RELATION_SELECTIONS = Object.freeze({
  [relationKey('validation_capabilities', 'validation_run', 'next')]: Object.freeze([
    selection('capability', 'one', [
      selectionSource('', '/name', { legacyCollectionPointer: '/result' })
    ], 'Select the configured validation capability to execute; rawCommand is a separate explicitly gated path.')
  ]),
  [relationKey('mission_execute', 'worker_retry', 'recover')]: Object.freeze([
    selection('taskId', 'one', [
      selectionSource('/results', '/taskId', { filter: { pointer: '/ok', operator: 'equals', value: false } }),
      selectionSource('/tasks', '/taskId')
    ], 'Select one failed or cancelled task. Result rows are restricted to ok=false; retry-required task rows are already failure-scoped.')
  ]),
  [relationKey('mission_execute', 'worker_cancel', 'recover')]: Object.freeze([
    selection('taskId', 'one', [
      selectionSource('/pending', '/taskId', { filter: { pointer: '/status', operator: 'in', value: ['executing', 'cancelling'] } })
    ], 'Select one currently executing or cancelling task; other pending states are not valid worker_cancel targets.')
  ]),
  [relationKey('mission_status', 'task_result_commit', 'next')]: Object.freeze([
    selection('taskId', 'one', [
      selectionSource('/tasks', '/id', { filter: { pointer: '/status', operator: 'equals', value: 'dispatched' } })
    ], 'Select one dispatched external task only after its external producer has finished writing the runtime-owned task worktree.')
  ]),
  [relationKey('mission_status', 'worker_cancel', 'recover')]: Object.freeze([
    selection('taskId', 'one', [
      selectionSource('/tasks', '/id', { filter: { pointer: '/status', operator: 'in', value: ['executing', 'cancelling'] } })
    ], 'Select one executing or cancelling task that the authoritative worker service can still cancel.')
  ]),
  [relationKey('mission_status', 'worker_resume', 'recover')]: Object.freeze([
    selection('taskId', 'one', [
      selectionSource('/tasks', '/id', { filter: { pointer: '/status', operator: 'equals', value: 'interrupted' } })
    ], 'Select one interrupted task whose uncertain runtime outcome requires explicit worker reconciliation.')
  ]),
  [relationKey('mission_status', 'worker_retry', 'recover')]: Object.freeze([
    selection('taskId', 'one', [
      selectionSource('/tasks', '/id', { filter: { pointer: '/status', operator: 'in', value: ['failed', 'interrupted', 'cancelled'] } })
    ], 'Select one failed, interrupted, or cancelled task that should start a new dispatch identity rather than resume prior execution.')
  ]),
  [relationKey('evidence_query', 'experience_commit', 'next')]: Object.freeze([
    selection('evidenceIds', 'many', [
      selectionSource('', '/id', { legacyCollectionPointer: '/result' })
    ], 'Select the evidence records that support the experience candidate; do not attach unrelated query results automatically.')
  ]),
  [relationKey('experience_audit', 'experience_review', 'next')]: Object.freeze([
    selection('experienceId', 'one', [
      selectionSource('', '/id', {
        legacyCollectionPointer: '/result',
        filter: { pointer: '/status', operator: 'in', value: ['candidate', 'active', 'challenged'] }
      })
    ], 'Select one candidate, active, or challenged experience whose lifecycle state supports an explicit review action.')
  ]),
  [relationKey('experience_compact', 'experience_review', 'next')]: Object.freeze([
    selection('experienceId', 'one', [
      selectionSource('/kept', '')
    ], 'Select one retained candidate experience for the next explicit lifecycle review.')
  ])
});

export const TOOL_IDENTITY_SOURCES = Object.freeze(Object.fromEntries(
  TOOL_NAMES.map((name) => [name, Object.freeze({ ...(DECLARED_IDENTITY_SOURCES[name] || {}) })])
));

function decodePointerSegment(segment) {
  return segment.replace(/~1/g, '/').replace(/~0/g, '~');
}

function pointerSegments(pointer) {
  if (pointer === '') return [];
  if (typeof pointer !== 'string' || !pointer.startsWith('/')) return null;
  return pointer.slice(1).split('/').map(decodePointerSegment);
}

function expandVariants(schema) {
  if (Array.isArray(schema?.anyOf) && schema.anyOf.length) return schema.anyOf.flatMap(expandVariants);
  return [schema];
}

function schemasAtPointer(schema, pointer) {
  const segments = pointerSegments(pointer);
  if (!segments) return [];
  let candidates = expandVariants(schema);
  for (const segment of segments) {
    const next = [];
    for (const candidate of candidates) {
      for (const variant of expandVariants(candidate)) {
        const child = variant?.type === 'object' ? variant.properties?.[segment] : undefined;
        if (child) next.push(...expandVariants(child));
      }
    }
    if (next.length === 0) return [];
    candidates = next;
  }
  return candidates;
}

function schemaHasPointer(schema, pointer) {
  return schemasAtPointer(schema, pointer).length > 0;
}

function schemaPathGuaranteed(schema, segments) {
  if (Array.isArray(schema?.anyOf) && schema.anyOf.length) {
    return schema.anyOf.every((variant) => schemaPathGuaranteed(variant, segments));
  }
  if (segments.length === 0) return schema?.type !== 'null' && schema?.type !== undefined;
  if (schema?.type !== 'object') return false;
  const [segment, ...rest] = segments;
  if (!(schema.required || []).includes(segment)) return false;
  const child = schema.properties?.[segment];
  if (!child) return false;
  return schemaPathGuaranteed(child, rest);
}

function schemaPointerAvailability(schema, pointer) {
  const segments = pointerSegments(pointer);
  if (!segments) return 'conditional';
  return schemaPathGuaranteed(schema, segments) ? 'guaranteed' : 'conditional';
}

function sourceSchema(toolName, descriptor) {
  if (descriptor.source === 'arguments') return toolInputJsonSchema(toolName);
  if (descriptor.source === 'structuredContent') return toolOutputJsonSchema(toolName);
  return null;
}

function arrayItemSchemasAtPointer(schema, collectionPointer) {
  return schemasAtPointer(schema, collectionPointer)
    .filter((candidate) => candidate?.type === 'array' && candidate.items)
    .flatMap((candidate) => expandVariants(candidate.items));
}

function itemPointerExists(schema, collectionPointer, itemPointer) {
  const itemSchemas = arrayItemSchemasAtPointer(schema, collectionPointer);
  if (!itemSchemas.length) return false;
  if (itemPointer === '') return true;
  return itemSchemas.some((itemSchema) => schemaHasPointer(itemSchema, itemPointer));
}

function explicitBindingsFor(sourceTool, edge) {
  return EXPLICIT_RELATION_BINDINGS[relationKey(sourceTool, edge.tool, edge.kind)] || [];
}

function selectionsFor(sourceTool, edge) {
  return RELATION_SELECTIONS[relationKey(sourceTool, edge.tool, edge.kind)] || [];
}

function bindingAvailability(sourceTool, descriptor) {
  return schemaPointerAvailability(sourceSchema(sourceTool, descriptor), descriptor.pointer);
}

function requiredCoverage(targetSchema, bindings, selections) {
  const byTarget = new Map(bindings.map((binding) => [binding.target, binding]));
  const selectionTargets = new Set(selections.filter((item) => item.requiredForRelation === true).map((item) => item.target));
  const coverage = { guaranteed: [], conditional: [], selection: [], unbound: [] };
  for (const required of targetSchema.required || []) {
    const binding = byTarget.get(required);
    if (binding) coverage[binding.availability].push(required);
    else if (selectionTargets.has(required)) coverage.selection.push(required);
    else coverage.unbound.push(required);
  }
  return Object.freeze(Object.fromEntries(
    Object.entries(coverage).map(([key, values]) => [key, Object.freeze(values)])
  ));
}

function compileRelation(sourceTool, edge) {
  const targetSchema = toolInputJsonSchema(edge.tool);
  const targetProperties = targetSchema.properties || {};
  const bindings = [];
  for (const [identity, descriptor] of Object.entries(TOOL_IDENTITY_SOURCES[sourceTool])) {
    if (!Object.hasOwn(targetProperties, identity)) continue;
    bindings.push(Object.freeze({
      target: identity,
      source: descriptor.source,
      pointer: descriptor.pointer,
      mode: 'if-present-non-null',
      transform: 'identity',
      availability: bindingAvailability(sourceTool, descriptor)
    }));
  }
  for (const descriptor of explicitBindingsFor(sourceTool, edge)) {
    bindings.push(Object.freeze({
      target: descriptor.target,
      source: descriptor.source,
      pointer: descriptor.pointer,
      mode: 'if-present-non-null',
      transform: descriptor.transform,
      availability: bindingAvailability(sourceTool, descriptor)
    }));
  }
  const boundTargets = new Set(bindings.map((binding) => binding.target));
  const selections = selectionsFor(sourceTool, edge);
  const unboundRequired = (targetSchema.required || []).filter((name) => !boundTargets.has(name));
  return Object.freeze({
    tool: edge.tool,
    kind: edge.kind,
    bindings: Object.freeze(bindings),
    selections,
    requiredCoverage: requiredCoverage(targetSchema, bindings, selections),
    unboundRequired: Object.freeze(unboundRequired)
  });
}

export const TOOL_WORKFLOW_BINDINGS = Object.freeze(Object.fromEntries(
  TOOL_NAMES.map((name) => {
    const workflow = TOOL_WORKFLOW_RELATIONS[name];
    return [name, Object.freeze({
      schema: TOOL_WORKFLOW_BINDINGS_SCHEMA,
      sourceTool: name,
      copyPolicy: 'Copy a deterministic binding only when its source pointer resolves to a non-null value. availability=guaranteed means the source schema requires a non-null value on every path; conditional means runtime resolution may still be absent. Apply declared transforms exactly. Never synthesize requestId or non-identity business inputs.',
      selectionPolicy: 'Selections are not automatic bindings. A client or operator must choose values from the declared source collection after applying any filter. A selection target has exclusive input ownership and must never also be populated by a deterministic binding on the same relation.',
      relations: Object.freeze(workflow.relations.map((edge) => compileRelation(name, edge)))
    })];
  })
));

function assertBindingDescriptor(sourceTool, targetTool, descriptor, seenTargets) {
  if (!SOURCE_KINDS.has(descriptor.source)) throw new Error(`Unknown workflow binding source for ${sourceTool} -> ${targetTool}.${descriptor.target}: ${descriptor.source}`);
  if (!TRANSFORMS.has(descriptor.transform)) throw new Error(`Unknown workflow binding transform for ${sourceTool} -> ${targetTool}.${descriptor.target}: ${descriptor.transform}`);
  if (!BINDING_AVAILABILITY.has(descriptor.availability)) throw new Error(`Unknown workflow binding availability for ${sourceTool} -> ${targetTool}.${descriptor.target}: ${descriptor.availability}`);
  if (seenTargets.has(descriptor.target)) throw new Error(`Duplicate workflow binding target ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  seenTargets.add(descriptor.target);
  const sourceContract = sourceSchema(sourceTool, descriptor);
  const sourceCandidates = schemasAtPointer(sourceContract, descriptor.pointer);
  if (!sourceCandidates.length) throw new Error(`Workflow binding source pointer does not exist for ${sourceTool} -> ${targetTool}.${descriptor.target}: ${descriptor.source}${descriptor.pointer}`);
  const expectedAvailability = schemaPointerAvailability(sourceContract, descriptor.pointer);
  if (descriptor.availability !== expectedAvailability) throw new Error(`Workflow binding availability drift for ${sourceTool} -> ${targetTool}.${descriptor.target}: expected ${expectedAvailability}, got ${descriptor.availability}`);
  const targetSchema = toolInputJsonSchema(targetTool).properties?.[descriptor.target];
  if (!targetSchema) throw new Error(`Workflow binding targets unknown input ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  if (descriptor.transform === 'singleton-array' && targetSchema.type !== 'array') {
    throw new Error(`singleton-array binding target must be an array for ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  }
}

function assertSelectionDescriptor(sourceTool, targetTool, descriptor) {
  if (!SELECTION_CARDINALITIES.has(descriptor.cardinality)) throw new Error(`Unknown workflow selection cardinality for ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  if (descriptor.requiredForRelation !== true) throw new Error(`Workflow selection must be explicit requiredForRelation for ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  const targetSchema = toolInputJsonSchema(targetTool).properties?.[descriptor.target];
  if (!targetSchema) throw new Error(`Workflow selection targets unknown input ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  if (descriptor.cardinality === 'many' && targetSchema.type !== 'array') throw new Error(`Many-cardinality workflow selection requires an array target for ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  if (!Array.isArray(descriptor.sources) || descriptor.sources.length === 0) throw new Error(`Workflow selection requires at least one source for ${sourceTool} -> ${targetTool}.${descriptor.target}`);
  if (typeof descriptor.reason !== 'string' || descriptor.reason.length === 0) throw new Error(`Workflow selection requires a reason for ${sourceTool} -> ${targetTool}.${descriptor.target}`);

  const natural = toolOutputJsonSchema(sourceTool);
  const legacy = toolOutputJsonSchema(sourceTool, { legacyEnvelope: true });
  for (const source of descriptor.sources) {
    if (source.source !== 'structuredContent') throw new Error(`Workflow selection source must be structuredContent for ${sourceTool} -> ${targetTool}.${descriptor.target}`);
    if (!itemPointerExists(natural, source.collectionPointer, source.itemPointer)) {
      throw new Error(`Workflow selection pointer does not exist for ${sourceTool} -> ${targetTool}.${descriptor.target}: ${source.collectionPointer}${source.itemPointer}`);
    }
    const legacyPointer = source.legacyCollectionPointer ?? source.collectionPointer;
    if (!itemPointerExists(legacy, legacyPointer, source.itemPointer)) {
      throw new Error(`Legacy workflow selection pointer does not exist for ${sourceTool} -> ${targetTool}.${descriptor.target}: ${legacyPointer}${source.itemPointer}`);
    }
    if (source.filter) {
      if (!FILTER_OPERATORS.has(source.filter.operator)) throw new Error(`Unknown workflow selection filter operator for ${sourceTool} -> ${targetTool}.${descriptor.target}`);
      const itemSchemas = arrayItemSchemasAtPointer(natural, source.collectionPointer);
      if (!itemSchemas.some((itemSchema) => schemaHasPointer(itemSchema, source.filter.pointer))) {
        throw new Error(`Workflow selection filter pointer does not exist for ${sourceTool} -> ${targetTool}.${descriptor.target}: ${source.filter.pointer}`);
      }
    }
  }
}

function assertBindingContract() {
  if (Object.keys(TOOL_IDENTITY_SOURCES).length !== TOOL_NAMES.length) {
    throw new Error(`Every public tool must have an identity-source contract; got ${Object.keys(TOOL_IDENTITY_SOURCES).length} for ${TOOL_NAMES.length} tools`);
  }
  if (Object.keys(TOOL_WORKFLOW_BINDINGS).length !== TOOL_NAMES.length) {
    throw new Error(`Every public tool must have a workflow-binding contract; got ${Object.keys(TOOL_WORKFLOW_BINDINGS).length} for ${TOOL_NAMES.length} tools`);
  }

  for (const name of TOOL_NAMES) {
    const identities = TOOL_IDENTITY_SOURCES[name];
    for (const [identity, descriptor] of Object.entries(identities)) {
      if (!IDENTITY_KEYS.has(identity)) throw new Error(`Unknown workflow identity key for ${name}: ${identity}`);
      if (!SOURCE_KINDS.has(descriptor.source)) throw new Error(`Unknown workflow binding source for ${name}.${identity}: ${descriptor.source}`);
      const schema = sourceSchema(name, descriptor);
      if (!schemaHasPointer(schema, descriptor.pointer)) {
        throw new Error(`Workflow identity source pointer does not exist for ${name}.${identity}: ${descriptor.source}${descriptor.pointer}`);
      }
      if (descriptor.source === 'structuredContent' && toolOutputJsonSchema(name).type !== 'object') {
        throw new Error(`Structured-content identity source must use an object output contract for ${name}.${identity}`);
      }
    }

    const workflow = TOOL_WORKFLOW_RELATIONS[name];
    const compiled = TOOL_WORKFLOW_BINDINGS[name];
    if (compiled.relations.length !== workflow.relations.length) throw new Error(`Workflow binding relation count drift for ${name}`);
    for (let index = 0; index < workflow.relations.length; index += 1) {
      const edge = workflow.relations[index];
      const bindingEdge = compiled.relations[index];
      if (bindingEdge.tool !== edge.tool || bindingEdge.kind !== edge.kind) throw new Error(`Workflow binding relation drift for ${name} at index ${index}`);
      if (edge.condition) {
        const conditionSourceContract = toolOutputJsonSchema(name);
        if (!schemaHasPointer(conditionSourceContract, edge.condition.pointer)) {
          throw new Error(`Workflow relation condition pointer does not exist for ${name} -> ${edge.tool}: structuredContent${edge.condition.pointer}`);
        }
        if (schemaPointerAvailability(conditionSourceContract, edge.condition.pointer) !== 'guaranteed') {
          throw new Error(`Workflow relation condition source must be guaranteed for ${name} -> ${edge.tool}: structuredContent${edge.condition.pointer}`);
        }
      }
      const seenTargets = new Set();
      for (const binding of bindingEdge.bindings) assertBindingDescriptor(name, edge.tool, binding, seenTargets);
      const selectionTargets = new Set();
      for (const descriptor of bindingEdge.selections) {
        if (seenTargets.has(descriptor.target)) throw new Error(`Workflow input ownership overlap ${name} -> ${edge.tool}.${descriptor.target}: deterministic binding cannot also require explicit selection`);
        if (selectionTargets.has(descriptor.target)) throw new Error(`Duplicate workflow selection target ${name} -> ${edge.tool}.${descriptor.target}`);
        selectionTargets.add(descriptor.target);
        assertSelectionDescriptor(name, edge.tool, descriptor);
      }
      const targetSchema = toolInputJsonSchema(edge.tool);
      const expectedUnbound = (targetSchema.required || []).filter((required) => !seenTargets.has(required));
      if (JSON.stringify(expectedUnbound) !== JSON.stringify(bindingEdge.unboundRequired)) throw new Error(`Workflow unbound-required drift for ${name} -> ${edge.tool}`);
      const expectedCoverage = requiredCoverage(targetSchema, bindingEdge.bindings, bindingEdge.selections);
      if (JSON.stringify(expectedCoverage) !== JSON.stringify(bindingEdge.requiredCoverage)) throw new Error(`Workflow required-coverage drift for ${name} -> ${edge.tool}`);
    }
  }
}

assertBindingContract();

export function toolWorkflowBindingsMeta(name) {
  const bindings = TOOL_WORKFLOW_BINDINGS[name];
  if (!bindings) throw new Error(`Unknown public tool workflow-binding contract: ${name}`);
  return Object.freeze({ [TOOL_WORKFLOW_BINDINGS_META_KEY]: bindings });
}
