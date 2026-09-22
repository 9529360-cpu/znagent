import { experienceReviewActionsForStatus } from './experience-lifecycle.mjs';
import { toolInputJsonSchema } from './tool-catalog.mjs';
import { toolOutputJsonSchema } from './tool-output-contracts.mjs';

const EXPERIENCE_REVIEW_TARGET = 'experience_review';
const EXPERIENCE_COMPACT_TARGET = 'experience_compact';
const EXPERIENCE_QUERY_TARGET = 'experience_query';
const ACTION_TARGET = 'action';
const EXPERIENCE_ID_TARGET = 'experienceId';
const PROJECT_ID_TARGET = 'projectId';
const DIRECT_REVIEW_ACTION_SOURCES = new Set(['experience_commit', 'experience_challenge']);

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

function schemaPointerGuaranteed(schema, pointer) {
  const segments = pointerSegments(pointer);
  return segments !== null && schemaPathGuaranteed(schema, segments);
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

function itemPointerGuaranteed(schema, collectionPointer, itemPointer) {
  const itemSchemas = arrayItemSchemasAtPointer(schema, collectionPointer);
  if (!itemSchemas.length) return false;
  if (itemPointer === '') return true;
  return itemSchemas.every((itemSchema) => schemaPointerGuaranteed(itemSchema, itemPointer));
}

function uniqueValues(values) {
  const seen = new Set();
  const output = [];
  for (const value of values) {
    const key = `${typeof value}:${JSON.stringify(value)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(value);
  }
  return output;
}

function group(selectionValue, status) {
  return Object.freeze({
    when: Object.freeze({ target: EXPERIENCE_ID_TARGET, equals: selectionValue }),
    sourceState: status,
    candidates: Object.freeze([...experienceReviewActionsForStatus(status)])
  });
}

function directActionSelection(result) {
  const status = typeof result?.status === 'string' ? result.status : null;
  return Object.freeze({
    target: ACTION_TARGET,
    cardinality: 'one',
    requiredForRelation: true,
    ...(status ? { sourceState: status } : {}),
    candidates: Object.freeze(status ? [...experienceReviewActionsForStatus(status)] : []),
    reason: 'Explicitly select one lifecycle action published for the source experience current status. Actions are projected from the shared Experience lifecycle authority and are never auto-bound.'
  });
}

function auditActionSelection(result) {
  const groups = [];
  if (Array.isArray(result)) {
    for (const item of result) {
      if (!item || item.id === null || item.id === undefined || item.status === null || item.status === undefined) continue;
      const candidateGroup = group(item.id, item.status);
      if (candidateGroup.candidates.length) groups.push(candidateGroup);
    }
  }
  return Object.freeze({
    target: ACTION_TARGET,
    cardinality: 'one',
    requiredForRelation: true,
    dependsOn: Object.freeze({ target: EXPERIENCE_ID_TARGET }),
    candidates: Object.freeze([]),
    candidateGroups: Object.freeze(groups),
    reason: 'After selecting experienceId, explicitly select one lifecycle action published for that experience current status. Actions are projected from the shared Experience lifecycle authority and are never auto-bound.'
  });
}

function auditProjectSelection(result, targetTool) {
  const candidates = uniqueValues(Array.isArray(result)
    ? result.map((item) => item?.projectId).filter((value) => value !== null && value !== undefined)
    : []);
  return Object.freeze({
    target: PROJECT_ID_TARGET,
    cardinality: 'one',
    requiredForRelation: true,
    fallbackForMissingBinding: true,
    candidates: Object.freeze(candidates),
    reason: targetTool === EXPERIENCE_COMPACT_TARGET
      ? 'The audit was not project-scoped. Explicitly select one owning project from the audited records before compacting exact duplicate candidates.'
      : 'The audit was not project-scoped. Explicitly select one owning project from the audited records before re-querying reviewed experience.'
  });
}

function compactActionSelection(result) {
  const kept = Array.isArray(result?.kept) ? result.kept : [];
  const groups = uniqueValues(kept)
    .filter((value) => value !== null && value !== undefined)
    .map((value) => group(value, 'candidate'));
  return Object.freeze({
    target: ACTION_TARGET,
    cardinality: 'one',
    requiredForRelation: true,
    dependsOn: Object.freeze({ target: EXPERIENCE_ID_TARGET }),
    candidates: Object.freeze([]),
    candidateGroups: Object.freeze(groups),
    reason: 'After selecting a retained candidate experienceId, explicitly select one lifecycle action published for candidate state. Actions are projected from the shared Experience lifecycle authority and are never auto-bound.'
  });
}

export function dependentWorkflowSelections(sourceTool, edge, result, partialArguments = {}) {
  if (sourceTool === 'experience_audit'
    && ((edge.tool === EXPERIENCE_COMPACT_TARGET && edge.kind === 'next')
      || (edge.tool === EXPERIENCE_QUERY_TARGET && edge.kind === 'inspect'))) {
    if (Object.hasOwn(partialArguments, PROJECT_ID_TARGET)) return Object.freeze([]);
    return Object.freeze([auditProjectSelection(result, edge.tool)]);
  }
  if (edge.tool !== EXPERIENCE_REVIEW_TARGET || edge.kind !== 'next') return Object.freeze([]);
  if (DIRECT_REVIEW_ACTION_SOURCES.has(sourceTool)) return Object.freeze([directActionSelection(result)]);
  if (sourceTool === 'experience_audit') return Object.freeze([auditActionSelection(result)]);
  if (sourceTool === 'experience_compact') return Object.freeze([compactActionSelection(result)]);
  return Object.freeze([]);
}

function assertReviewActionTarget() {
  const target = toolInputJsonSchema(EXPERIENCE_REVIEW_TARGET).properties?.[ACTION_TARGET];
  if (!target || target.type !== 'string' || !Array.isArray(target.enum)) {
    throw new Error('Dependent workflow action discovery requires experience_review.action to remain a string enum');
  }
  const enumValues = new Set(target.enum);
  for (const status of ['candidate', 'active', 'challenged', 'retired']) {
    for (const action of experienceReviewActionsForStatus(status)) {
      if (!enumValues.has(action)) throw new Error(`Experience lifecycle action missing from experience_review.action enum: ${action}`);
    }
  }
}

function assertDirectSourceContract(sourceTool) {
  const natural = toolOutputJsonSchema(sourceTool);
  const legacy = toolOutputJsonSchema(sourceTool, { legacyEnvelope: true });
  for (const [kind, schema] of [['natural', natural], ['legacy', legacy]]) {
    if (!schemaPointerGuaranteed(schema, '/status')) {
      throw new Error(`${sourceTool} ${kind} output must guarantee /status for direct review action discovery`);
    }
  }
}

function assertAuditSourceContract() {
  const natural = toolOutputJsonSchema('experience_audit');
  const legacy = toolOutputJsonSchema('experience_audit', { legacyEnvelope: true });
  for (const [schema, collectionPointer] of [[natural, ''], [legacy, '/result']]) {
    for (const pointer of ['/id', '/projectId', '/status']) {
      if (!itemPointerExists(schema, collectionPointer, pointer)) {
        throw new Error(`Experience audit dependent selection pointer missing: ${collectionPointer}${pointer}`);
      }
      if (!itemPointerGuaranteed(schema, collectionPointer, pointer)) {
        throw new Error(`Experience audit dependent selection pointer must be guaranteed: ${collectionPointer}${pointer}`);
      }
    }
  }
}

function assertCompactSourceContract() {
  const natural = toolOutputJsonSchema('experience_compact');
  const legacy = toolOutputJsonSchema('experience_compact', { legacyEnvelope: true });
  for (const [schema, collectionPointer] of [[natural, '/kept'], [legacy, '/kept']]) {
    if (!itemPointerExists(schema, collectionPointer, '')) {
      throw new Error(`Experience compact dependent selection pointer missing: ${collectionPointer}`);
    }
  }
  if (experienceReviewActionsForStatus('candidate').length === 0) {
    throw new Error('Experience candidate lifecycle state must expose at least one review action');
  }
}

assertReviewActionTarget();
for (const sourceTool of DIRECT_REVIEW_ACTION_SOURCES) assertDirectSourceContract(sourceTool);
assertAuditSourceContract();
assertCompactSourceContract();
