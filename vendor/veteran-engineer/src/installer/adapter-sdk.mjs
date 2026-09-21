import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { pathExists } from '../util.mjs';
import { HOST_ADAPTER_API_VERSION } from '../constants.mjs';
import { resolveSurfaceProfile } from '../surface-capabilities.mjs';

const ID_RE = /^[a-z][a-z0-9-]{1,63}$/;

export function validateHostAdapter(adapter, source = '<built-in>') {
  if (!adapter || typeof adapter !== 'object') throw new Error(`Invalid host adapter from ${source}`);
  if (adapter.apiVersion !== HOST_ADAPTER_API_VERSION) {
    const error = new Error(`Host adapter ${adapter.id || source} API version ${adapter.apiVersion} is incompatible with ${HOST_ADAPTER_API_VERSION}`);
    error.code = 'HOST_ADAPTER_API_INCOMPATIBLE';
    throw error;
  }
  if (!ID_RE.test(adapter.id || '')) throw new Error(`Invalid host adapter id from ${source}: ${adapter.id}`);
  if (!adapter.displayName || typeof adapter.displayName !== 'string') throw new Error(`Host adapter ${adapter.id} missing displayName`);
  resolveSurfaceProfile(adapter.surfaceProfile || 'local-stdio');
  for (const method of ['install', 'status', 'doctor', 'uninstall']) {
    if (typeof adapter[method] !== 'function') throw new Error(`Host adapter ${adapter.id} missing ${method}()`);
  }
  return adapter;
}

function invalidExternalAdapter(source, cause) {
  const sourceName = path.basename(source);
  const digest = crypto.createHash('sha256').update(path.resolve(source)).digest('hex').slice(0, 16);
  const failureCode = typeof cause?.code === 'string' && cause.code ? cause.code : 'HOST_ADAPTER_LOAD_FAILED';
  const details = { source: sourceName, failureCode };
  const fail = () => {
    const error = new Error(`External host adapter ${sourceName} is invalid and cannot be invoked`);
    error.code = 'HOST_ADAPTER_INVALID';
    error.details = details;
    throw error;
  };
  return validateHostAdapter({
    apiVersion: HOST_ADAPTER_API_VERSION,
    id: `invalid-external-${digest}`,
    displayName: `Invalid external adapter (${sourceName})`,
    surfaceProfile: 'local-stdio',
    capabilities: { external: true, invalid: true, ...details },
    async install() { return fail(); },
    async status() { return { installed: false, error: 'HOST_ADAPTER_INVALID', ...details }; },
    async doctor() { return { ok: false, error: 'HOST_ADAPTER_INVALID', checks: [{ name: 'adapter-valid', ok: false, ...details }] }; },
    async uninstall() { return fail(); }
  }, source);
}

export async function loadExternalAdapters(trustedDirs = []) {
  const adapters = [];
  for (const rawDir of trustedDirs) {
    const dir = path.resolve(rawDir);
    if (!(await pathExists(dir))) continue;
    let entries;
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch (error) {
      adapters.push(invalidExternalAdapter(dir, error));
      continue;
    }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      if (!entry.isFile() || !entry.name.endsWith('.mjs')) continue;
      const source = path.join(dir, entry.name);
      let adapter;
      try {
        const module = await import(pathToFileURL(source).href);
        adapter = validateHostAdapter(module.default || module.adapter, source);
      } catch (error) {
        adapters.push(invalidExternalAdapter(source, error));
        continue;
      }
      if (path.basename(entry.name, '.mjs') !== adapter.id) {
        const error = new Error(`External adapter filename must match id: ${entry.name} vs ${adapter.id}`);
        error.code = 'HOST_ADAPTER_FILENAME_MISMATCH';
        throw error;
      }
      adapters.push(adapter);
    }
  }
  return adapters;
}
