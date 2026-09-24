import fs from 'node:fs/promises';
import path from 'node:path';

export const PINNED_MCP_PACKAGES = Object.freeze({
  '@modelcontextprotocol/client': '2.0.0',
  '@modelcontextprotocol/server': '2.0.0',
  '@modelcontextprotocol/core': '2.0.0',
  zod: '4.2.0'
});

async function readJson(file) {
  try {
    return { value: JSON.parse(await fs.readFile(file, 'utf8')), error: null };
  } catch (error) {
    return { value: null, error };
  }
}

export async function inspectMcpSdkIntegrity(runtimeRoot) {
  const root = path.resolve(runtimeRoot);
  const packages = {};
  let detected = 0;
  for (const [name, expected] of Object.entries(PINNED_MCP_PACKAGES)) {
    const file = path.join(root, 'node_modules', ...name.split('/'), 'package.json');
    const loaded = await readJson(file);
    const missing = loaded.error?.code === 'ENOENT';
    const packageDetected = !missing;
    const version = loaded.value?.version || null;
    if (packageDetected) detected += 1;
    packages[name] = {
      expected,
      version,
      detected: packageDetected,
      present: Boolean(version),
      readError: loaded.error && !missing ? (loaded.error.code || 'PACKAGE_JSON_INVALID') : null,
      path: file
    };
  }

  const graphErrors = [];
  if (detected > 0) {
    for (const [name, item] of Object.entries(packages)) {
      if (!item.detected) graphErrors.push(`${name} is missing`);
      else if (item.readError) graphErrors.push(`${name} package metadata is unreadable or invalid (${item.readError})`);
      else if (!item.present) graphErrors.push(`${name} package metadata is missing a version`);
      else if (item.version !== item.expected) graphErrors.push(`${name} expected ${item.expected}, found ${item.version}`);
    }
  }
  const graph = {
    status: detected === 0 ? 'unavailable' : (graphErrors.length ? 'invalid' : 'verified'),
    packages,
    errors: graphErrors
  };

  const packageFile = path.join(root, 'package.json');
  const lockFile = path.join(root, 'package-lock.json');
  const [manifestLoaded, lockLoaded] = await Promise.all([readJson(packageFile), readJson(lockFile)]);
  const lockErrors = [];
  if (lockLoaded.value) {
    const rootPins = { ...(manifestLoaded.value?.dependencies || {}), ...(manifestLoaded.value?.optionalDependencies || {}) };
    for (const [name, expected] of Object.entries(PINNED_MCP_PACKAGES)) {
      if (rootPins[name] !== expected) lockErrors.push(`root pin ${name} expected ${expected}, found ${rootPins[name] || 'missing'}`);
      const entry = lockLoaded.value.packages?.[`node_modules/${name}`];
      if (entry?.version !== expected) lockErrors.push(`lock entry ${name} expected ${expected}, found ${entry?.version || 'missing'}`);
      if (typeof entry?.integrity !== 'string' || !entry.integrity.startsWith('sha512-')) lockErrors.push(`lock entry ${name} has no sha512 integrity`);
    }
  }
  const lockfile = {
    status: !lockLoaded.value ? 'unavailable' : (lockErrors.length ? 'invalid' : 'verified'),
    path: lockFile,
    lockfileVersion: lockLoaded.value?.lockfileVersion || null,
    errors: lockErrors
  };

  const status = graph.status === 'unavailable'
    ? 'unavailable'
    : (graph.status === 'verified' && lockfile.status === 'verified' ? 'verified' : 'invalid');
  return { status, graph, lockfile };
}

export function assertMcpSdkIntegrity(report) {
  if (report.status === 'verified') return report;
  const error = new Error(report.status === 'unavailable'
    ? 'Official MCP SDK graph is unavailable'
    : `Official MCP SDK integrity failure: ${[...report.graph.errors, ...report.lockfile.errors].join('; ') || report.lockfile.status}`);
  error.code = report.status === 'unavailable' ? 'MCP_SDK_UNAVAILABLE' : 'MCP_SDK_INTEGRITY';
  error.details = report;
  throw error;
}
