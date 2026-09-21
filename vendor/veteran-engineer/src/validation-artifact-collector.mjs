import fs from 'node:fs/promises';
import path from 'node:path';

const MAX_DECLARATIONS = 16;
const MAX_FILES = 128;
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const MAX_TOTAL_BYTES = 64 * 1024 * 1024;

function errorWithCode(message, code) {
  return Object.assign(new Error(message), { code });
}

function normalizeRelativePath(value) {
  const raw = String(value || '').trim().replaceAll('\\', '/');
  if (!raw) throw errorWithCode('Validation artifact path must be non-empty', 'VALIDATION_ARTIFACT_PATH_INVALID');
  if (raw.startsWith('/') || raw.startsWith('//') || /^[A-Za-z]:/.test(raw)) {
    throw errorWithCode('Validation artifact path must be repository-relative', 'VALIDATION_ARTIFACT_PATH_ESCAPE');
  }
  const normalized = path.posix.normalize(raw.replace(/^\.\//, ''));
  if (!normalized || normalized === '.' || normalized === '..' || normalized.startsWith('../')) {
    throw errorWithCode('Validation artifact path must name a contained file or directory', 'VALIDATION_ARTIFACT_PATH_ESCAPE');
  }
  return normalized;
}

export function normalizeValidationArtifacts(raw) {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) throw errorWithCode('Validation artifacts must be an array', 'VALIDATION_ARTIFACTS_INVALID');
  if (raw.length > MAX_DECLARATIONS) throw errorWithCode(`Validation artifacts may contain at most ${MAX_DECLARATIONS} declarations`, 'VALIDATION_ARTIFACT_LIMIT_EXCEEDED');
  return raw.map((item) => {
    if (typeof item === 'string') return { path: normalizeRelativePath(item), required: false, kind: 'validation-output' };
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      throw errorWithCode('Validation artifact declaration must be a path string or object', 'VALIDATION_ARTIFACTS_INVALID');
    }
    return {
      path: normalizeRelativePath(item.path),
      required: item.required === true,
      kind: item.kind ? String(item.kind).slice(0, 80) : 'validation-output'
    };
  });
}

function insideRoot(root, candidate) {
  const rel = path.relative(root, candidate);
  return rel === '' || (rel !== '..' && !rel.startsWith(`..${path.sep}`) && !path.isAbsolute(rel));
}

async function collectEntry(root, absolute, relative, state, declaration) {
  const info = await fs.lstat(absolute);
  if (info.isSymbolicLink()) {
    throw errorWithCode(`Validation artifact path contains a symlink: ${relative}`, 'VALIDATION_ARTIFACT_SYMLINK');
  }
  const real = await fs.realpath(absolute);
  if (!insideRoot(root, real)) {
    throw errorWithCode(`Validation artifact path escapes the validation worktree: ${relative}`, 'VALIDATION_ARTIFACT_PATH_ESCAPE');
  }
  if (info.isDirectory()) {
    const entries = await fs.readdir(absolute, { withFileTypes: true });
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      await collectEntry(root, path.join(absolute, entry.name), path.posix.join(relative, entry.name), state, declaration);
    }
    return;
  }
  if (!info.isFile()) return;
  if (info.size > MAX_FILE_BYTES) {
    throw errorWithCode(`Validation artifact exceeds ${MAX_FILE_BYTES} bytes: ${relative}`, 'VALIDATION_ARTIFACT_LIMIT_EXCEEDED');
  }
  if (state.files.length >= MAX_FILES || state.totalBytes + info.size > MAX_TOTAL_BYTES) {
    throw errorWithCode('Validation artifact collection exceeds the bounded file or byte limit', 'VALIDATION_ARTIFACT_LIMIT_EXCEEDED');
  }
  const content = await fs.readFile(absolute);
  state.totalBytes += content.length;
  state.files.push({ name: relative, kind: declaration.kind, content });
}

export async function collectValidationArtifacts(worktree, declarations) {
  const root = await fs.realpath(worktree);
  const state = { files: [], totalBytes: 0 };
  const items = [];
  let requiredMissing = false;
  for (const declaration of declarations) {
    const absolute = path.resolve(root, ...declaration.path.split('/'));
    if (!insideRoot(root, absolute)) {
      throw errorWithCode(`Validation artifact path escapes the validation worktree: ${declaration.path}`, 'VALIDATION_ARTIFACT_PATH_ESCAPE');
    }
    let beforeCount = state.files.length;
    try {
      await collectEntry(root, absolute, declaration.path, state, declaration);
      const fileCount = state.files.length - beforeCount;
      const missing = fileCount === 0;
      if (declaration.required && missing) requiredMissing = true;
      items.push({ path: declaration.path, kind: declaration.kind, required: declaration.required, missing, fileCount });
    } catch (error) {
      if (error?.code === 'ENOENT') {
        if (declaration.required) requiredMissing = true;
        items.push({ path: declaration.path, kind: declaration.kind, required: declaration.required, missing: true, fileCount: 0 });
        continue;
      }
      throw error;
    }
  }
  return {
    attachments: state.files,
    summary: {
      configured: declarations.length > 0,
      complete: !requiredMissing,
      requiredMissing,
      files: state.files.length,
      bytes: state.totalBytes,
      items
    }
  };
}
