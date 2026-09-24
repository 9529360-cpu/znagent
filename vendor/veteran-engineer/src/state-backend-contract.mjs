import path from 'node:path';

export const STATE_BACKEND_CONTRACT = 'veteran-state-backend-v1';

const REQUIRED_METHODS = ['init', 'read', 'transaction', 'recordTimeline', 'verifyAudit'];
const REQUIRED_PATHS = ['artifactsDir', 'worktreesDir'];

function contractError(message, details = null) {
  const error = new Error(message);
  error.code = 'STATE_BACKEND_CONTRACT_INVALID';
  if (details) error.details = details;
  return error;
}

export function assertStateBackend(backend) {
  if (!backend || typeof backend !== 'object') {
    throw contractError('State backend must be an object');
  }
  if (backend.backendContract !== STATE_BACKEND_CONTRACT) {
    throw contractError(`State backend must declare ${STATE_BACKEND_CONTRACT}`, {
      expected: STATE_BACKEND_CONTRACT,
      actual: backend.backendContract || null
    });
  }
  if (!backend.backendKind || typeof backend.backendKind !== 'string') {
    throw contractError('State backend must declare a non-empty backendKind');
  }
  for (const method of REQUIRED_METHODS) {
    if (typeof backend[method] !== 'function') {
      throw contractError(`State backend is missing required method ${method}()`);
    }
  }
  for (const key of REQUIRED_PATHS) {
    if (typeof backend[key] !== 'string' || !backend[key]) {
      throw contractError(`State backend is missing required execution-local path ${key}`);
    }
    if (!path.isAbsolute(backend[key])) {
      throw contractError(`State backend execution-local path ${key} must be absolute`, { path: key });
    }
  }
  return backend;
}

export function describeStateBackend(backend) {
  assertStateBackend(backend);
  return {
    contract: backend.backendContract,
    kind: backend.backendKind,
    executionLocalPaths: {
      artifacts: backend.artifactsDir,
      worktrees: backend.worktreesDir
    }
  };
}
