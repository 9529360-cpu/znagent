const RESOURCE_MODES = new Set(['shared', 'exclusive']);
const RESOURCE_SCOPES = new Set(['task', 'mission', 'project', 'global']);
const TERMINAL_TASK_STATUSES = new Set(['done', 'failed', 'cancelled', 'blocked', 'superseded']);
const BUILTIN_SENSING_CAPABILITIES = Object.freeze(['source-identity', 'mission-state', 'task-state']);
const MAX_ITEMS = 32;

function boundedName(value, label, limit = 160) {
  if (typeof value !== 'string') throw new Error(`${label} must be a string`);
  const normalized = value.trim();
  if (!normalized) throw new Error(`${label} must be a non-empty string`);
  if (normalized.length > limit) throw new Error(`${label} exceeds ${limit} characters`);
  return normalized;
}

function normalizeNames(values, label) {
  if (values === undefined || values === null) return [];
  if (!Array.isArray(values)) throw new Error(`${label} must be an array`);
  if (values.length > MAX_ITEMS) throw new Error(`${label} exceeds the ${MAX_ITEMS}-item safety bound`);
  return [...new Set(values.map((value, index) => boundedName(value, `${label}[${index}]`)))].sort();
}

function normalizeResource(raw, index, label) {
  if (typeof raw === 'string') {
    return { key: boundedName(raw, `${label}[${index}]`), scope: 'project', mode: 'exclusive' };
  }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error(`${label}[${index}] must be a string or object`);
  const key = boundedName(raw.key, `${label}[${index}].key`);
  const scope = raw.scope === undefined || raw.scope === null ? 'project' : boundedName(raw.scope, `${label}[${index}].scope`);
  const mode = raw.mode === undefined || raw.mode === null ? 'exclusive' : boundedName(raw.mode, `${label}[${index}].mode`);
  if (!RESOURCE_SCOPES.has(scope)) throw new Error(`${label}[${index}].scope must be one of ${[...RESOURCE_SCOPES].join(', ')}`);
  if (!RESOURCE_MODES.has(mode)) throw new Error(`${label}[${index}].mode must be one of ${[...RESOURCE_MODES].join(', ')}`);
  return { key, scope, mode };
}

function dedupeResources(resources) {
  const byIdentity = new Map();
  for (const resource of resources) {
    const identity = `${resource.scope}:${resource.key}`;
    const existing = byIdentity.get(identity);
    if (!existing || resource.mode === 'exclusive') byIdentity.set(identity, resource);
  }
  return [...byIdentity.values()].sort((a, b) => `${a.scope}:${a.key}`.localeCompare(`${b.scope}:${b.key}`));
}

export function normalizeTaskCapabilityContract(raw = {}, taskId = 'task') {
  const sensingCapabilities = normalizeNames(raw.sensingCapabilities, `${taskId}.sensingCapabilities`);
  const executionCapabilities = normalizeNames(raw.executionCapabilities, `${taskId}.executionCapabilities`);
  const coordinationKeys = normalizeNames(raw.coordinationKeys, `${taskId}.coordinationKeys`);
  const rawResources = raw.runtimeResources === undefined || raw.runtimeResources === null ? [] : raw.runtimeResources;
  if (!Array.isArray(rawResources)) throw new Error(`${taskId}.runtimeResources must be an array`);
  if (rawResources.length > MAX_ITEMS) throw new Error(`${taskId}.runtimeResources exceeds the ${MAX_ITEMS}-item safety bound`);
  const runtimeResources = rawResources.map((item, index) => normalizeResource(item, index, `${taskId}.runtimeResources`));
  for (const key of coordinationKeys) runtimeResources.push({ key: `coordination:${key}`, scope: 'project', mode: 'exclusive' });
  return { sensingCapabilities, executionCapabilities, coordinationKeys, runtimeResources: dedupeResources(runtimeResources) };
}

function resourceIdentity(resource, context = {}) {
  const projectId = context.projectId || 'project';
  const missionId = context.missionId || 'mission';
  const taskId = context.taskId || 'task';
  if (resource.scope === 'global') return `global:${resource.key}`;
  if (resource.scope === 'project') return `project:${projectId}:${resource.key}`;
  if (resource.scope === 'mission') return `mission:${projectId}:${missionId}:${resource.key}`;
  return `task:${projectId}:${missionId}:${taskId}:${resource.key}`;
}

export function bindRuntimeResources(resources = [], context = {}) {
  return resources.map((resource) => resource.identity ? { ...resource } : ({ ...resource, identity: resourceIdentity(resource, context) }));
}

export function runtimeResourceConflicts(left = [], right = [], leftContext = {}, rightContext = {}) {
  const a = bindRuntimeResources(left, leftContext);
  const b = bindRuntimeResources(right, rightContext);
  const conflicts = [];
  for (const first of a) {
    for (const second of b) {
      if (first.identity !== second.identity) continue;
      if (first.mode === 'exclusive' || second.mode === 'exclusive') {
        conflicts.push({ identity: first.identity, leftMode: first.mode, rightMode: second.mode });
      }
    }
  }
  return conflicts;
}

export function runtimeResourcesConflict(left = [], right = [], leftContext = {}, rightContext = {}) {
  return runtimeResourceConflicts(left, right, leftContext, rightContext).length > 0;
}

function validationCapabilityNames(catalog = []) {
  if (!Array.isArray(catalog)) return [];
  return [...new Set(catalog
    .map((entry) => typeof entry === 'string' ? entry : entry?.name)
    .filter((name) => typeof name === 'string' && name.trim())
    .map((name) => name.trim()))].sort();
}

function configuredCapabilityNames(values = []) {
  if (!Array.isArray(values)) return [];
  return [...new Set(values
    .filter((name) => typeof name === 'string' && name.trim())
    .map((name) => name.trim()))].sort();
}

export function projectCapabilityDiagnostics(project) {
  const providers = new Set(validationCapabilityNames(project.validationCapabilities));
  return {
    unbackedRuntimeFeedbackCapabilities: configuredCapabilityNames(project.runtimeFeedbackCapabilities)
      .filter((name) => !providers.has(name)),
    unbackedRequiredValidationCapabilities: configuredCapabilityNames(project.requiredValidationCapabilities)
      .filter((name) => !providers.has(name))
  };
}

export function availableProjectCapabilities(project) {
  return {
    sensing: [...new Set([
      ...BUILTIN_SENSING_CAPABILITIES,
      ...validationCapabilityNames(project.validationCapabilities)
    ])].sort(),
    execution: [...new Set(project.workerPolicy?.capabilities || [])].sort()
  };
}

export function taskCapabilityReadiness(task, project) {
  const available = availableProjectCapabilities(project);
  const sensing = new Set(available.sensing);
  const execution = new Set(available.execution);
  const missingSensing = (task.sensingCapabilities || []).filter((name) => !sensing.has(name));
  const missingExecution = (task.executionCapabilities || []).filter((name) => !execution.has(name));
  return { ready: missingSensing.length === 0 && missingExecution.length === 0, missingSensing, missingExecution, available };
}

export function taskRuntimeContext(task, mission, project) {
  return { taskId: task.id, missionId: mission.id, projectId: project.id };
}

function authoritativeLeaseContext(state, task) {
  const missionId = task?.missionId;
  const taskId = task?.id;
  if (typeof missionId !== 'string' || !missionId.trim()) {
    throw Object.assign(new Error('Active capability lease task is missing an authoritative mission identity'), { code: 'CAPABILITY_LEASE_CONTEXT_INVALID' });
  }
  if (typeof taskId !== 'string' || !taskId.trim()) {
    throw Object.assign(new Error('Active capability lease task is missing an authoritative task identity'), { code: 'CAPABILITY_LEASE_CONTEXT_INVALID' });
  }
  const ownerMission = state.missions?.[missionId];
  if (!ownerMission || typeof ownerMission.projectId !== 'string' || !ownerMission.projectId.trim()) {
    throw Object.assign(new Error(`Active capability lease references unknown or invalid mission context: ${missionId}`), { code: 'CAPABILITY_LEASE_CONTEXT_INVALID' });
  }
  return { projectId: ownerMission.projectId, missionId, taskId };
}

function canonicalLeaseResources(state, task) {
  const rawResources = task.capabilityLease?.resources ?? [];
  if (!Array.isArray(rawResources)) {
    throw Object.assign(new Error(`Capability lease resources for ${task.missionId}:${task.id} must be an array`), { code: 'CAPABILITY_LEASE_RESOURCE_INVALID' });
  }
  if (rawResources.length > MAX_ITEMS) {
    throw Object.assign(new Error(`Capability lease resources for ${task.missionId}:${task.id} exceed the ${MAX_ITEMS}-item safety bound`), { code: 'CAPABILITY_LEASE_RESOURCE_INVALID' });
  }
  const context = authoritativeLeaseContext(state, task);
  return rawResources.map((resource, index) => {
    const normalized = normalizeResource(resource, index, `${task.missionId}:${task.id}.capabilityLease.resources`);
    return { ...normalized, identity: resourceIdentity(normalized, context) };
  });
}

export function activeRuntimeResourceConflicts({ state, task, mission, project }) {
  const conflicts = [];
  for (const other of Object.values(state.tasks || {})) {
    if (!other.capabilityLease || TERMINAL_TASK_STATUSES.has(other.status)) continue;
    if (other.missionId === mission.id && other.id === task.id) continue;
    const resourceConflicts = runtimeResourceConflicts(
      task.runtimeResources || [],
      canonicalLeaseResources(state, other),
      taskRuntimeContext(task, mission, project),
      {}
    );
    if (!resourceConflicts.length) continue;
    conflicts.push({ missionId: other.missionId, taskId: other.id, conflicts: resourceConflicts });
  }
  return conflicts;
}

function visibleLeaseResources(state, task, project, mission) {
  const resources = canonicalLeaseResources(state, task);
  if (task.missionId === mission.id) return resources;
  const projectPrefix = `project:${project.id}:`;
  return resources.filter((resource) => resource.identity.startsWith('global:') || resource.identity.startsWith(projectPrefix));
}

export function buildCapabilitySnapshot({ project, mission, tasks, liveSourceIdentity, state }) {
  const waveIds = mission.waves?.[mission.nextWaveIndex] || [];
  const waveTasks = tasks.filter((task) => waveIds.includes(task.id));
  const latestFeedback = mission.runtimeFeedback?.latestRound || null;
  const feedbackSourceBound = latestFeedback
    ? liveSourceIdentity.dirty !== true && latestFeedback.commitSha === liveSourceIdentity.head
    : false;
  const activeLeases = Object.values(state.tasks || {})
    .filter((task) => task.capabilityLease && !TERMINAL_TASK_STATUSES.has(task.status))
    .map((task) => ({ task, resources: visibleLeaseResources(state, task, project, mission) }))
    .filter(({ task, resources }) => task.missionId === mission.id || resources.length > 0)
    .map(({ task, resources }) => ({
      missionId: task.missionId,
      taskId: task.id,
      status: task.status,
      leaseId: task.capabilityLease.id,
      resources
    }));
  return {
    contract: 'veteran-capability-snapshot-v1',
    sourceIdentity: liveSourceIdentity,
    mission: { id: mission.id, phase: mission.phase, status: mission.status, waveIndex: mission.nextWaveIndex },
    availableCapabilities: availableProjectCapabilities(project),
    capabilityDiagnostics: projectCapabilityDiagnostics(project),
    wave: waveTasks.map((task) => ({
      taskId: task.id,
      status: task.status,
      sensingCapabilities: task.sensingCapabilities || [],
      executionCapabilities: task.executionCapabilities || [],
      runtimeResources: bindRuntimeResources(task.runtimeResources || [], taskRuntimeContext(task, mission, project)),
      capabilityReady: taskCapabilityReadiness(task, project).ready
    })),
    runtimeFeedback: latestFeedback ? {
      sourceHead: latestFeedback.commitSha || null,
      sourceBoundToLiveHead: feedbackSourceBound,
      sourceBoundToCurrentMissionHead: feedbackSourceBound,
      sourceDirty: liveSourceIdentity.dirty === true,
      scope: latestFeedback.scope || 'wave',
      passed: latestFeedback.passed === true,
      evidenceId: latestFeedback.aggregateEvidenceId || null
    } : null,
    activeLeases
  };
}
