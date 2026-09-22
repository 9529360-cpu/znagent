import path from 'node:path';
import { LocalJsonStateBackend } from './local-json-state-backend.mjs';
import { PostgresStateBackend } from './postgres-state-backend.mjs';

export const STATE_BACKEND_KINDS = Object.freeze({
  LOCAL_JSON: 'local-json',
  POSTGRES: 'postgres'
});

function configError(message, details = null) {
  const error = new Error(message);
  error.code = 'STATE_BACKEND_CONFIGURATION_INVALID';
  if (details) error.details = details;
  return error;
}

function parsePoolMax(value) {
  if (value === undefined || value === null || value === '') return 4;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1 || parsed > 32) {
    throw configError('VETERAN_ENGINEER_POSTGRES_POOL_MAX must be an integer between 1 and 32');
  }
  return parsed;
}

export function resolveStateBackendConfig({ config = null, env = process.env } = {}) {
  if (config !== null && config !== undefined) {
    if (typeof config !== 'object' || Array.isArray(config)) {
      throw configError('Programmatic state backend config must be an object');
    }
    if (config.kind === STATE_BACKEND_KINDS.LOCAL_JSON) return { kind: STATE_BACKEND_KINDS.LOCAL_JSON };
    if (config.kind === STATE_BACKEND_KINDS.POSTGRES) {
      if (typeof config.connectionString !== 'string' || !config.connectionString.trim()) throw configError('PostgreSQL state backend requires connectionString');
      if (typeof config.instanceKey !== 'string' || !config.instanceKey.trim()) throw configError('PostgreSQL state backend requires explicit instanceKey');
      return {
        kind: STATE_BACKEND_KINDS.POSTGRES,
        connectionString: config.connectionString,
        instanceKey: config.instanceKey.trim(),
        poolMax: parsePoolMax(config.poolMax)
      };
    }
    throw configError(`Unsupported state backend kind: ${config.kind || 'missing'}`, { supported: Object.values(STATE_BACKEND_KINDS) });
  }

  const kind = String(env.VETERAN_ENGINEER_STATE_BACKEND || STATE_BACKEND_KINDS.LOCAL_JSON).trim();
  if (kind === STATE_BACKEND_KINDS.LOCAL_JSON) return { kind };
  if (kind !== STATE_BACKEND_KINDS.POSTGRES) {
    throw configError(`Unsupported VETERAN_ENGINEER_STATE_BACKEND: ${kind}`, { supported: Object.values(STATE_BACKEND_KINDS) });
  }
  const connectionString = env.VETERAN_ENGINEER_POSTGRES_URL;
  const instanceKey = env.VETERAN_ENGINEER_STATE_INSTANCE;
  if (typeof connectionString !== 'string' || !connectionString.trim()) {
    throw configError('VETERAN_ENGINEER_POSTGRES_URL is required when VETERAN_ENGINEER_STATE_BACKEND=postgres');
  }
  if (typeof instanceKey !== 'string' || !instanceKey.trim()) {
    throw configError('VETERAN_ENGINEER_STATE_INSTANCE is required when VETERAN_ENGINEER_STATE_BACKEND=postgres');
  }
  return {
    kind,
    connectionString,
    instanceKey: instanceKey.trim(),
    poolMax: parsePoolMax(env.VETERAN_ENGINEER_POSTGRES_POOL_MAX)
  };
}

export function createStateBackend({ stateRoot, config = null, env = process.env } = {}) {
  if (!stateRoot) throw configError('stateRoot is required to create a state backend');
  const resolved = resolveStateBackendConfig({ config, env });
  const root = path.resolve(stateRoot);
  if (resolved.kind === STATE_BACKEND_KINDS.LOCAL_JSON) return new LocalJsonStateBackend({ root });
  return new PostgresStateBackend({
    root,
    connectionString: resolved.connectionString,
    instanceKey: resolved.instanceKey,
    poolMax: resolved.poolMax
  });
}
