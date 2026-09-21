import fs from 'node:fs/promises';
import path from 'node:path';

function policyError(message, details = null) {
  const error = new Error(message);
  error.code = 'REMOTE_WORKSPACE_NOT_ALLOWED';
  if (details) error.details = details;
  return error;
}

function normalizeRoots(roots) {
  if (roots == null) return [];
  if (!Array.isArray(roots)) throw new TypeError('allowedLocalRoots must be an array');
  const values = roots.map((root) => {
    if (typeof root !== 'string' || !root.trim()) throw new TypeError('allowedLocalRoots must contain non-empty paths');
    return path.resolve(root.trim());
  });
  return [...new Set(values)];
}

function within(root, target) {
  const relative = path.relative(root, target);
  return relative === '' || (relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}

async function realOrResolved(value) {
  const resolved = path.resolve(value);
  try {
    return await fs.realpath(resolved);
  } catch (error) {
    if (error?.code === 'ENOENT') return resolved;
    throw error;
  }
}

export function normalizedAllowedLocalRoots(roots = []) {
  return normalizeRoots(roots);
}

export async function canonicalizeAllowedLocalRoots(roots = []) {
  const normalized = normalizeRoots(roots);
  const canonical = [];
  for (const root of normalized) canonical.push(await realOrResolved(root));
  return [...new Set(canonical)];
}

export async function assertLocalPathAllowed(candidate, roots = [], { label = 'local path' } = {}) {
  const normalizedRoots = await canonicalizeAllowedLocalRoots(roots);
  if (normalizedRoots.length === 0) return realOrResolved(candidate);
  const target = await realOrResolved(candidate);
  if (normalizedRoots.some((root) => within(root, target))) return target;
  throw policyError(`${label} is outside the configured Veteran Remote Host workspaces`, {
    target,
    allowedLocalRoots: normalizedRoots
  });
}

export async function ensureWorkspaceRoots(roots = []) {
  const normalized = normalizeRoots(roots);
  for (const root of normalized) await fs.mkdir(root, { recursive: true });
  return canonicalizeAllowedLocalRoots(normalized);
}
