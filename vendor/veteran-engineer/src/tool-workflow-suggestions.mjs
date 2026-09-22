import { toolInputJsonSchema, toolRequiresRequestId } from './tool-catalog.mjs';
import { TOOL_WORKFLOW_RELATIONS } from './tool-workflow-relations.mjs';
import { TOOL_IDENTITY_SOURCES, TOOL_WORKFLOW_BINDINGS } from './tool-workflow-bindings.mjs';
import { dependentWorkflowSelections } from './tool-workflow-dependent-selections.mjs';

export const TOOL_WORKFLOW_SUGGESTIONS_META_KEY = 'io.veteran-engineer/workflow-suggestions';
export const TOOL_WORKFLOW_SUGGESTIONS_SCHEMA = 'veteran-tool-workflow-suggestions-v1';

function decodePointerSegment(segment) {
  return segment.replace(/~1/g, '/').replace(/~0/g, '~');
}

function pointerSegments(pointer) {
  if (pointer === '') return [];
  if (typeof pointer !== 'string' || !pointer.startsWith('/')) return null;
  return pointer.slice(1).split('/').map(decodePointerSegment);
}

function resolvePointer(root, pointer) {
  const segments = pointerSegments(pointer);
  if (!segments) return { found: false, value: undefined };
  let current = root;
  for (const segment of segments) {
    if (current === null || current === undefined || (typeof current !== 'object' && typeof current !== 'function')) {
      return { found: false, value: undefined };
    }
    if (!Object.hasOwn(current, segment)) return { found: false, value: undefined };
    current = current[segment];
  }
  return { found: true, value: current };
}

function applyTransform(transform, value) {
  if (transform === undefined || transform === 'identity') return value;
  if (transform === 'singleton-array') return [value];
  throw new Error(`Unknown workflow suggestion binding transform: ${transform}`);
}

function requiredInvocationIdentityFallback(sourceTool, binding, args, sourceOutcome) {
  if (sourceOutcome !== 'error' || binding.source !== 'structuredContent' || binding.transform !== 'identity') {
    return { found: false, value: undefined };
  }
  const identitySource = TOOL_IDENTITY_SOURCES[sourceTool]?.[binding.target];
  if (!identitySource
    || identitySource.source !== binding.source
    || identitySource.pointer !== binding.pointer) {
    return { found: false, value: undefined };
  }
  const sourceInput = toolInputJsonSchema(sourceTool);
  if (!(sourceInput.required || []).includes(binding.target)) return { found: false, value: undefined };
  const resolved = resolvePointer(args, `/${binding.target}`);
  if (!resolved.found || resolved.value === null || resolved.value === undefined) return { found: false, value: undefined };
  return { found: true, value: resolved.value };
}

function bindingValue(sourceTool, binding, args, result, sourceOutcome) {
  const root = binding.source === 'arguments' ? args : result;
  const resolved = resolvePointer(root, binding.pointer);
  if (resolved.found && resolved.value !== null && resolved.value !== undefined) {
    return { found: true, value: applyTransform(binding.transform, resolved.value) };
  }
  return requiredInvocationIdentityFallback(sourceTool, binding, args, sourceOutcome);
}

function matchesFilter(item, filter) {
  if (!filter) return true;
  const resolved = resolvePointer(item, filter.pointer);
  if (!resolved.found) return false;
  if (filter.operator === 'equals') return Object.is(resolved.value, filter.value);
  if (filter.operator === 'in') return Array.isArray(filter.value) && filter.value.some((candidate) => Object.is(candidate, resolved.value));
  throw new Error(`Unknown workflow suggestion selection filter operator: ${filter.operator}`);
}

function matchesCondition(value, condition) {
  if (condition.operator === 'equals') return Object.is(value, condition.value);
  if (condition.operator === 'not-equals') return !Object.is(value, condition.value);
  if (condition.operator === 'in') return Array.isArray(condition.value) && condition.value.some((candidate) => Object.is(candidate, value));
  throw new Error(`Unknown workflow suggestion relation condition operator: ${condition.operator}`);
}

function relationApplicability(edge, result, sourceOutcome) {
  if (!edge.condition) return Object.freeze({ state: 'not-declared' });
  if (edge.condition.source !== 'structuredContent') {
    throw new Error(`Unsupported workflow suggestion relation condition source: ${edge.condition.source}`);
  }
  if (sourceOutcome === 'error') {
    return Object.freeze({
      state: 'unknown',
      condition: edge.condition,
      reason: 'source-error'
    });
  }
  const resolved = resolvePointer(result, edge.condition.pointer);
  if (!resolved.found) {
    return Object.freeze({
      state: 'unknown',
      condition: edge.condition,
      reason: 'source-value-unavailable'
    });
  }
  return Object.freeze({
    state: matchesCondition(resolved.value, edge.condition) ? 'applicable' : 'not-applicable',
    condition: edge.condition
  });
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

function selectionCandidates(selection, result) {
  const values = [];
  for (const source of selection.sources || []) {
    if (source.source !== 'structuredContent') throw new Error(`Unsupported workflow suggestion selection source: ${source.source}`);
    const collection = resolvePointer(result, source.collectionPointer);
    if (!collection.found || !Array.isArray(collection.value)) continue;
    for (const item of collection.value) {
      if (!matchesFilter(item, source.filter)) continue;
      const selected = resolvePointer(item, source.itemPointer);
      if (!selected.found || selected.value === null || selected.value === undefined) continue;
      values.push(selected.value);
    }
  }
  return uniqueValues(values);
}

function resolvedSelection(selection, result) {
  return Object.freeze({
    target: selection.target,
    cardinality: selection.cardinality,
    requiredForRelation: selection.requiredForRelation === true,
    candidates: Object.freeze(selectionCandidates(selection, result)),
    reason: selection.reason
  });
}

function selectionHasCandidates(selection) {
  if (Array.isArray(selection.candidates) && selection.candidates.length > 0) return true;
  return Array.isArray(selection.candidateGroups)
    && selection.candidateGroups.some((group) => Array.isArray(group?.candidates) && group.candidates.length > 0);
}

function callerGeneratedRequiredTargets(targetTool, targetSchema) {
  if (!toolRequiresRequestId(targetTool)) return new Set();
  if (!(targetSchema.required || []).includes('requestId')) {
    throw new Error(`Workflow suggestion request-id authority drift for ${targetTool}`);
  }
  return new Set(['requestId']);
}

function invocationReadiness(targetSchema, bindingEdge, partialArguments, missingRequired, selections) {
  const callerGeneratedTargets = callerGeneratedRequiredTargets(bindingEdge.tool, targetSchema);
  const bindingByTarget = new Map((bindingEdge.bindings || []).map((binding) => [binding.target, binding]));
  const requiredSelections = (selections || []).filter((selection) => selection.requiredForRelation === true);
  const selectionTargets = new Set(requiredSelections.map((selection) => selection.target));
  const callerGeneratedRequired = [];
  const conditionalRequired = [];
  const resultRequired = [];
  const inputRequired = [];

  for (const name of missingRequired) {
    if (callerGeneratedTargets.has(name)) {
      callerGeneratedRequired.push(name);
      continue;
    }
    if (selectionTargets.has(name)) continue;
    const binding = bindingByTarget.get(name);
    if (binding) {
      if (binding.availability === 'conditional') conditionalRequired.push(name);
      else if (binding.source === 'structuredContent') resultRequired.push(name);
      else throw new Error(`Guaranteed argument binding is unexpectedly unresolved for ${bindingEdge.tool}.${name}`);
      continue;
    }
    inputRequired.push(name);
  }

  const selectionRequired = requiredSelections
    .filter((selection) => !Object.hasOwn(partialArguments, selection.target))
    .map((selection) => selection.target);
  const selectionUnavailable = requiredSelections
    .filter((selection) => selectionRequired.includes(selection.target) && !selectionHasCandidates(selection))
    .map((selection) => selection.target);

  const requiredNames = new Set(targetSchema.required || []);
  for (const target of selectionRequired) {
    if (requiredNames.has(target)) continue;
    if (callerGeneratedTargets.has(target) || bindingByTarget.has(target)) {
      throw new Error(`Workflow relation selection overlaps incompatible input ownership for ${bindingEdge.tool}.${target}`);
    }
  }

  return Object.freeze({
    readyAfterCallerGenerated: conditionalRequired.length === 0 && resultRequired.length === 0 && selectionRequired.length === 0 && inputRequired.length === 0,
    callerGeneratedRequired: Object.freeze(callerGeneratedRequired),
    conditionalRequired: Object.freeze(conditionalRequired),
    resultRequired: Object.freeze(resultRequired),
    selectionRequired: Object.freeze(selectionRequired),
    selectionUnavailable: Object.freeze(selectionUnavailable),
    inputRequired: Object.freeze(inputRequired)
  });
}

function suggestionFor(sourceTool, index, args, result, sourceOutcome) {
  const edge = TOOL_WORKFLOW_RELATIONS[sourceTool].relations[index];
  const bindingEdge = TOOL_WORKFLOW_BINDINGS[sourceTool].relations[index];
  if (edge.tool !== bindingEdge.tool || edge.kind !== bindingEdge.kind) {
    throw new Error(`Workflow suggestion relation drift for ${sourceTool} at index ${index}`);
  }

  const targetSchema = toolInputJsonSchema(edge.tool);
  const partialArguments = {};
  for (const binding of bindingEdge.bindings) {
    const resolved = bindingValue(sourceTool, binding, args, result, sourceOutcome);
    if (resolved.found) partialArguments[binding.target] = resolved.value;
  }
  const missingRequired = (targetSchema.required || []).filter((name) => !Object.hasOwn(partialArguments, name));
  const selections = Object.freeze([
    ...(bindingEdge.selections || []).map((item) => resolvedSelection(item, result)),
    ...dependentWorkflowSelections(sourceTool, edge, result, partialArguments)
  ]);
  const readiness = invocationReadiness(targetSchema, bindingEdge, partialArguments, missingRequired, selections);
  const applicability = relationApplicability(edge, result, sourceOutcome);

  return Object.freeze({
    tool: edge.tool,
    kind: edge.kind,
    when: edge.when,
    ...(edge.condition ? { condition: edge.condition } : {}),
    arguments: Object.freeze(partialArguments),
    missingRequired: Object.freeze(missingRequired),
    argumentsComplete: missingRequired.length === 0,
    selections,
    readiness,
    applicability
  });
}

function normalizeOutcome(sourceOutcome, sourceErrorCode) {
  if (!['success', 'error'].includes(sourceOutcome)) throw new Error(`Unknown workflow suggestion source outcome: ${sourceOutcome}`);
  if (sourceErrorCode !== null && sourceErrorCode !== undefined && (typeof sourceErrorCode !== 'string' || sourceErrorCode.length === 0)) {
    throw new Error('Workflow suggestion sourceErrorCode must be a non-empty string when provided');
  }
  return { sourceOutcome, sourceErrorCode: sourceErrorCode || null };
}

export function toolWorkflowSuggestions(sourceTool, args = {}, result = {}, { sourceOutcome = 'success', sourceErrorCode = null } = {}) {
  const workflow = TOOL_WORKFLOW_RELATIONS[sourceTool];
  const bindings = TOOL_WORKFLOW_BINDINGS[sourceTool];
  if (!workflow || !bindings) throw new Error(`Unknown public tool workflow suggestion source: ${sourceTool}`);
  const outcome = normalizeOutcome(sourceOutcome, sourceErrorCode);
  return Object.freeze({
    schema: TOOL_WORKFLOW_SUGGESTIONS_SCHEMA,
    sourceTool,
    sourceOutcome: outcome.sourceOutcome,
    ...(outcome.sourceErrorCode ? { sourceErrorCode: outcome.sourceErrorCode } : {}),
    invocationPolicy: 'Suggestions are partial call arguments only. Apply the relation condition before use, supply every missing required input, explicitly choose any declared selection, create a fresh requestId for mutating calls, and never treat a suggestion as authorization to invoke a tool. Dependent selections publish call-time choices derived from authoritative source results and do not auto-bind them; a selection marked fallbackForMissingBinding appears only when its deterministic conditional binding did not resolve and must then be explicitly chosen. Dependent action selections may publish candidateGroups keyed by an earlier explicit selection; they do not auto-bind either selection. applicability.state is machine-evaluated only when the relation declares a structured condition: applicable means the observed source result satisfies it, not-applicable means it does not, unknown means authoritative source evidence is unavailable, and not-declared means only the human-readable when condition is published. readiness.readyAfterCallerGenerated means all non-caller-generated relation inputs are currently resolved; it is independent from applicability and does not grant authorization. callerGeneratedRequired values still must be freshly created. conditionalRequired identifies absent optional/conditional source bindings that have no explicit fallback selection; resultRequired identifies a normally guaranteed result-derived identity that is unavailable. On successful calls, declared structured-result identities remain authoritative even when invocation arguments disagree. Error outcomes have no authoritative structured result, so a result-derived identity may retain same-name required invocation scope strictly as a recovery fallback; other result-derived bindings, selections, and structured applicability conditions may be unavailable.',
    suggestions: Object.freeze(workflow.relations.map((_edge, index) => suggestionFor(sourceTool, index, args || {}, result, outcome.sourceOutcome)))
  });
}

export function toolWorkflowSuggestionsMeta(sourceTool, args = {}, result = {}, options = {}) {
  return Object.freeze({ [TOOL_WORKFLOW_SUGGESTIONS_META_KEY]: toolWorkflowSuggestions(sourceTool, args, result, options) });
}

export function toolWorkflowErrorSuggestionsMeta(sourceTool, args = {}, sourceErrorCode = 'ERROR') {
  return toolWorkflowSuggestionsMeta(sourceTool, args, {}, { sourceOutcome: 'error', sourceErrorCode });
}
