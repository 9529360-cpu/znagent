import { TOOL_NAMES, toolRequiresRequestId } from './tool-catalog.mjs';

const READ_ONLY_TOOLS = new Set([
  'mission_status',
  'mission_readiness',
  'mission_timeline',
  'evidence_query',
  'validation_capabilities',
  'candidate_preflight',
  'candidate_status',
  'experience_query',
  'experience_audit',
  'runtime_health',
  'runtime_integrity'
]);

const DESTRUCTIVE_TOOLS = new Set([
  'mission_execute',
  'mission_advance',
  'mission_cancel',
  'task_result_commit',
  'worker_cancel',
  'worker_resume',
  'validation_run',
  'experience_review',
  'experience_challenge',
  'experience_compact',
  'runtime_cleanup'
]);

const OPEN_WORLD_TOOLS = new Set([
  'project_open',
  'mission_plan',
  'mission_execute',
  'mission_advance',
  'validation_run',
  'semantic_review_run'
]);

function assertKnownTools(names, label) {
  for (const name of names) {
    if (!TOOL_NAMES.includes(name)) throw new Error(`Unknown ${label} tool annotation target: ${name}`);
  }
}

assertKnownTools(READ_ONLY_TOOLS, 'read-only');
assertKnownTools(DESTRUCTIVE_TOOLS, 'destructive');
assertKnownTools(OPEN_WORLD_TOOLS, 'open-world');

for (const name of TOOL_NAMES) {
  const readOnly = READ_ONLY_TOOLS.has(name);
  const mutating = toolRequiresRequestId(name);
  if (readOnly === mutating) {
    throw new Error(`Tool mutation authority mismatch for ${name}: readOnly=${readOnly} requestIdMutation=${mutating}`);
  }
  if (readOnly && DESTRUCTIVE_TOOLS.has(name)) {
    throw new Error(`Read-only tool cannot be destructive: ${name}`);
  }
}

export function toolAnnotations(name) {
  if (!TOOL_NAMES.includes(name)) throw new Error(`Unknown public tool annotation contract: ${name}`);
  const readOnly = READ_ONLY_TOOLS.has(name);
  if (readOnly) {
    return Object.freeze({
      readOnlyHint: true,
      openWorldHint: OPEN_WORLD_TOOLS.has(name)
    });
  }
  return Object.freeze({
    readOnlyHint: false,
    destructiveHint: DESTRUCTIVE_TOOLS.has(name),
    idempotentHint: toolRequiresRequestId(name),
    openWorldHint: OPEN_WORLD_TOOLS.has(name)
  });
}

export const TOOL_ANNOTATIONS = Object.freeze(Object.fromEntries(
  TOOL_NAMES.map((name) => [name, toolAnnotations(name)])
));
