import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { RUNTIME_VERSION } from '../constants.mjs';
import { ensureDir } from '../util.mjs';

export const RUNTIME_BUNDLE_SCHEMA_VERSION = 1;
export const RUNTIME_DISTRIBUTION_ROOTS = [
  '.codex-plugin', '.mcp.json', 'NEXT_CHAT_HANDOFF.md', 'README.md', 'bin', 'mcp',
  'package-lock.json', 'package.json', 'scripts', 'src', 'tests'
];
const SKILL_ROOT = 'skills/runtime-regression-debugger';
const SKILL_RUNTIME_ASSET = `${SKILL_ROOT}/assets/plugin-runtime-starter/`;
const MAX_FILES = 5000;
const MAX_CONTENT_BYTES = 64 * 1024 * 1024;

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function normalizedMode(stat) {
  return stat.mode & 0o111 ? 0o755 : 0o644;
}

function posixPath(value) {
  return value.split(path.sep).join('/');
}

function assertSafeRelativePath(rel) {
  if (typeof rel !== 'string' || !rel || rel.includes('\\') || rel.startsWith('/') || /^[A-Za-z]:/.test(rel)) {
    throw Object.assign(new Error(`Unsafe runtime bundle path: ${rel}`), { code: 'RUNTIME_BUNDLE_PATH_INVALID' });
  }
  const parts = rel.split('/');
  if (parts.some((part) => !part || part === '.' || part === '..')) {
    throw Object.assign(new Error(`Unsafe runtime bundle path: ${rel}`), { code: 'RUNTIME_BUNDLE_PATH_INVALID' });
  }
  return parts;
}

async function walkRoot(root, rel, out, { excludePrefix = null } = {}) {
  const target = path.join(root, ...rel.split('/'));
  const stat = await fs.lstat(target);
  if (stat.isSymbolicLink()) {
    throw Object.assign(new Error(`Runtime distribution contains unsupported symlink: ${rel}`), { code: 'RUNTIME_BUNDLE_SYMLINK_REJECTED' });
  }
  if (stat.isFile()) {
    const content = await fs.readFile(target);
    out.push({ path: rel, mode: normalizedMode(stat), bytes: content.length, sha256: sha256(content), contentBase64: content.toString('base64') });
    return;
  }
  if (!stat.isDirectory()) return;
  for (const entry of (await fs.readdir(target, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    if (['node_modules', '.git', '__pycache__', '.DS_Store'].includes(entry.name)) continue;
    const child = `${rel}/${entry.name}`;
    if (excludePrefix && (child === excludePrefix.slice(0, -1) || child.startsWith(excludePrefix))) continue;
    await walkRoot(root, child, out, { excludePrefix });
  }
}

export async function buildRuntimeBundle({ root, version = RUNTIME_VERSION } = {}) {
  if (!root) throw new Error('root is required');
  const resolvedRoot = path.resolve(root);
  const files = [];
  for (const rel of RUNTIME_DISTRIBUTION_ROOTS) await walkRoot(resolvedRoot, rel, files);
  await walkRoot(resolvedRoot, SKILL_ROOT, files, { excludePrefix: SKILL_RUNTIME_ASSET });
  files.sort((a, b) => a.path.localeCompare(b.path));
  const totalBytes = files.reduce((sum, file) => sum + file.bytes, 0);
  if (files.length > MAX_FILES || totalBytes > MAX_CONTENT_BYTES) {
    throw Object.assign(new Error(`Runtime bundle exceeds safety limits: ${files.length} files / ${totalBytes} bytes`), { code: 'RUNTIME_BUNDLE_TOO_LARGE' });
  }
  return {
    schemaVersion: RUNTIME_BUNDLE_SCHEMA_VERSION,
    product: 'veteran-engineer',
    version,
    fileCount: files.length,
    contentBytes: totalBytes,
    files
  };
}

export function serializeRuntimeBundle(bundle) {
  return Buffer.from(`${JSON.stringify(bundle)}\n`, 'utf8');
}

export async function writeRuntimeBundle({ root, output, version = RUNTIME_VERSION } = {}) {
  const bundle = await buildRuntimeBundle({ root, version });
  const bytes = serializeRuntimeBundle(bundle);
  await fs.mkdir(path.dirname(path.resolve(output)), { recursive: true });
  await fs.writeFile(output, bytes);
  return { bundle, bytes, sha256: sha256(bytes) };
}

export async function materializeRuntimeBundle(input, targetRoot) {
  const bundle = Buffer.isBuffer(input) || input instanceof Uint8Array
    ? JSON.parse(Buffer.from(input).toString('utf8'))
    : input;
  if (!bundle || bundle.schemaVersion !== RUNTIME_BUNDLE_SCHEMA_VERSION || bundle.product !== 'veteran-engineer') {
    throw Object.assign(new Error('Unsupported Veteran Engineer runtime bundle'), { code: 'RUNTIME_BUNDLE_INVALID' });
  }
  if (typeof bundle.version !== 'string' || !/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(bundle.version)) {
    throw Object.assign(new Error(`Invalid runtime bundle version: ${bundle.version}`), { code: 'RUNTIME_BUNDLE_VERSION_INVALID' });
  }
  if (!Array.isArray(bundle.files) || bundle.files.length === 0 || bundle.files.length > MAX_FILES) {
    throw Object.assign(new Error('Runtime bundle file list is invalid'), { code: 'RUNTIME_BUNDLE_INVALID' });
  }
  const seen = new Set();
  let totalBytes = 0;
  const prepared = [];
  for (const file of bundle.files) {
    const parts = assertSafeRelativePath(file?.path);
    if (seen.has(file.path)) throw Object.assign(new Error(`Duplicate runtime bundle path: ${file.path}`), { code: 'RUNTIME_BUNDLE_DUPLICATE_PATH' });
    seen.add(file.path);
    if (![0o644, 0o755].includes(file.mode)) throw Object.assign(new Error(`Invalid runtime bundle mode for ${file.path}`), { code: 'RUNTIME_BUNDLE_MODE_INVALID' });
    if (typeof file.contentBase64 !== 'string' || typeof file.sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(file.sha256)) {
      throw Object.assign(new Error(`Invalid runtime bundle metadata for ${file.path}`), { code: 'RUNTIME_BUNDLE_INVALID' });
    }
    const content = Buffer.from(file.contentBase64, 'base64');
    if (content.length !== file.bytes || sha256(content) !== file.sha256) {
      throw Object.assign(new Error(`Runtime bundle digest mismatch: ${file.path}`), { code: 'RUNTIME_BUNDLE_DIGEST_MISMATCH' });
    }
    totalBytes += content.length;
    if (totalBytes > MAX_CONTENT_BYTES) throw Object.assign(new Error('Runtime bundle content exceeds safety limit'), { code: 'RUNTIME_BUNDLE_TOO_LARGE' });
    prepared.push({ file, parts, content });
  }
  if (bundle.fileCount !== prepared.length || bundle.contentBytes !== totalBytes) {
    throw Object.assign(new Error('Runtime bundle aggregate metadata mismatch'), { code: 'RUNTIME_BUNDLE_INVALID' });
  }
  const contentByPath = new Map(prepared.map((item) => [item.file.path, item.content]));
  try {
    const packageJson = JSON.parse(contentByPath.get('package.json')?.toString('utf8') || 'null');
    const pluginJson = JSON.parse(contentByPath.get('.codex-plugin/plugin.json')?.toString('utf8') || 'null');
    const constants = contentByPath.get('src/constants.mjs')?.toString('utf8') || '';
    if (packageJson?.name !== 'veteran-engineer' || packageJson?.version !== bundle.version || pluginJson?.name !== 'veteran-engineer' || pluginJson?.version !== bundle.version) {
      throw new Error('package/plugin version mismatch');
    }
    const escaped = bundle.version.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (!new RegExp(`RUNTIME_VERSION\\s*=\\s*['"]${escaped}['"]`).test(constants)) throw new Error('runtime constant version mismatch');
  } catch (cause) {
    throw Object.assign(new Error(`Runtime bundle product/version identity is invalid: ${cause.message}`), { code: 'RUNTIME_BUNDLE_IDENTITY_MISMATCH' });
  }
  const resolvedTarget = path.resolve(targetRoot);
  await fs.rm(resolvedTarget, { recursive: true, force: true });
  await ensureDir(resolvedTarget);
  for (const item of prepared) {
    const target = path.join(resolvedTarget, ...item.parts);
    await ensureDir(path.dirname(target));
    await fs.writeFile(target, item.content, { mode: item.file.mode });
    await fs.chmod(target, item.file.mode);
  }
  return { root: resolvedTarget, version: bundle.version, fileCount: prepared.length, contentBytes: totalBytes };
}
