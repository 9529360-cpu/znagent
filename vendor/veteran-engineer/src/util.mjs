import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

export function nowIso() {
  return new Date().toISOString();
}

export function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

export function stableStringify(value) {
  const seen = new WeakSet();
  const normalize = (input) => {
    if (input === null || typeof input !== 'object') return input;
    if (seen.has(input)) throw new TypeError('Cannot stableStringify cyclic structure');
    seen.add(input);
    if (Array.isArray(input)) return input.map(normalize);
    const out = {};
    for (const key of Object.keys(input).sort()) out[key] = normalize(input[key]);
    return out;
  };
  return JSON.stringify(normalize(value));
}

export function clone(value) {
  return structuredClone(value);
}

export function redactKnownSecrets(value, secrets = [], replacement = '[REDACTED]') {
  const known = [...new Set(secrets.filter((secret) => typeof secret === 'string' && secret.length > 0))]
    .sort((left, right) => right.length - left.length);
  if (known.length === 0) return value;

  const redactString = (input) => {
    let output = input;
    for (const secret of known) output = output.split(secret).join(replacement);
    return output;
  };
  const visit = (input) => {
    if (typeof input === 'string') return redactString(input);
    if (Array.isArray(input)) return input.map(visit);
    if (input && typeof input === 'object') {
      return Object.fromEntries(Object.entries(input).map(([key, item]) => [redactString(key), visit(item)]));
    }
    return input;
  };
  return visit(value);
}

export function randomId(prefix) {
  return `${prefix}_${crypto.randomUUID()}`;
}

export async function pathExists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

export async function ensureDir(target) {
  await fs.mkdir(target, { recursive: true });
  return target;
}

export function normalizePathList(items = []) {
  return [...new Set(items.map((item) => String(item).replaceAll('\\', '/').replace(/^\.\//, '').replace(/\/$/, '')))].sort();
}

export function assertPlainObject(value, label = 'value') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object`);
  }
}

export function errorWithCode(message, code, details) {
  const error = new Error(message);
  error.code = code;
  if (details !== undefined) error.details = details;
  return error;
}

export function within(root, candidate) {
  const rel = path.relative(path.resolve(root), path.resolve(candidate));
  return rel === '' || (rel !== '..' && !rel.startsWith(`..${path.sep}`) && !path.isAbsolute(rel));
}

export async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}
