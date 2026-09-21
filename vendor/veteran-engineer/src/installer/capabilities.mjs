import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { POSTGRES_DRIVER_VERSION } from '../postgres-state-backend.mjs';
import { resolveStateBackendConfig, STATE_BACKEND_KINDS } from '../state-backend-factory.mjs';

function selectedKind(env) {
  return String(env?.VETERAN_ENGINEER_STATE_BACKEND || STATE_BACKEND_KINDS.LOCAL_JSON).trim();
}

async function inspectPostgresDriver(runtimeRoot) {
  const resolvedRoot = path.resolve(runtimeRoot);
  const packagePath = path.join(resolvedRoot, 'node_modules', 'pg', 'package.json');
  let pkg;
  try {
    const raw = await fs.readFile(packagePath, 'utf8');
    pkg = JSON.parse(raw);
  } catch (error) {
    if (error?.code === 'ENOENT') {
      return { installed: false, readable: false, version: null, loadable: false, errorCode: null };
    }
    return {
      installed: true,
      readable: false,
      version: null,
      loadable: false,
      errorCode: error?.code || 'PG_PACKAGE_INVALID'
    };
  }

  const version = typeof pkg.version === 'string' ? pkg.version : null;
  if (version !== POSTGRES_DRIVER_VERSION) {
    return { installed: true, readable: true, version, loadable: false, errorCode: null };
  }

  try {
    const requireFromRuntime = createRequire(path.join(resolvedRoot, 'package.json'));
    const module = requireFromRuntime('pg');
    const Pool = module?.Pool || module?.default?.Pool;
    if (typeof Pool !== 'function') {
      return { installed: true, readable: true, version, loadable: false, errorCode: 'POSTGRES_DRIVER_INVALID' };
    }
    return { installed: true, readable: true, version, loadable: true, errorCode: null };
  } catch (error) {
    return {
      installed: true,
      readable: true,
      version,
      loadable: false,
      errorCode: error?.code || 'POSTGRES_DRIVER_INVALID'
    };
  }
}

export async function inspectPostgresStateCapability({ runtimeRoot, env = process.env } = {}) {
  if (typeof runtimeRoot !== 'string' || !runtimeRoot) {
    const error = new Error('runtimeRoot is required to inspect PostgreSQL capability');
    error.code = 'RUNTIME_ROOT_REQUIRED';
    throw error;
  }

  const requestedKind = selectedKind(env);
  let resolved = null;
  let configError = null;
  try {
    resolved = resolveStateBackendConfig({ env });
  } catch (error) {
    configError = {
      code: error?.code || 'STATE_BACKEND_CONFIGURATION_INVALID',
      message: error?.message || 'State backend configuration is invalid'
    };
  }

  const driver = await inspectPostgresDriver(runtimeRoot);
  const driverExact = driver.readable && driver.version === POSTGRES_DRIVER_VERSION;
  const driverReady = driverExact && driver.loadable;
  const postgresSelected = requestedKind === STATE_BACKEND_KINDS.POSTGRES;
  const urlConfigured = typeof env?.VETERAN_ENGINEER_POSTGRES_URL === 'string' && Boolean(env.VETERAN_ENGINEER_POSTGRES_URL.trim());
  const instanceConfigured = typeof env?.VETERAN_ENGINEER_STATE_INSTANCE === 'string' && Boolean(env.VETERAN_ENGINEER_STATE_INSTANCE.trim());
  const checks = [
    {
      name: 'state-backend-config',
      ok: configError === null,
      selected: resolved?.kind || requestedKind,
      errorCode: configError?.code || null,
      message: configError?.message || null
    },
    {
      name: 'postgres-driver',
      ok: driverReady,
      optional: !postgresSelected,
      requiredVersion: POSTGRES_DRIVER_VERSION,
      installed: driver.installed,
      readable: driver.readable,
      installedVersion: driver.version,
      loadable: driver.loadable,
      errorCode: driver.errorCode || null
    }
  ];

  return {
    ok: checks.filter((check) => !check.optional).every((check) => check.ok),
    selected: resolved?.kind || requestedKind,
    postgresSelected,
    config: {
      valid: configError === null,
      urlConfigured,
      instanceConfigured,
      poolMax: resolved?.kind === STATE_BACKEND_KINDS.POSTGRES ? resolved.poolMax : null,
      errorCode: configError?.code || null,
      message: configError?.message || null
    },
    driver: {
      requiredVersion: POSTGRES_DRIVER_VERSION,
      installed: driver.installed,
      readable: driver.readable,
      installedVersion: driver.version,
      exact: driverExact,
      loadable: driver.loadable,
      ready: driverReady,
      errorCode: driver.errorCode || null
    },
    checks
  };
}
