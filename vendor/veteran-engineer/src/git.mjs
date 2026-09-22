import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { DEFAULT_COMMAND_TIMEOUT_MS } from './constants.mjs';
import { errorWithCode, normalizePathList, within } from './util.mjs';

const SAFE_SUBPROCESS_ENV_KEYS = ['PATH', 'HOME', 'USERPROFILE', 'TMP', 'TEMP', 'TMPDIR', 'SYSTEMROOT', 'COMSPEC', 'LANG', 'LC_ALL', 'SHELL'];
const DEFAULT_REMOTE_BRANCH_CANDIDATES = ['main', 'master'];

export function allowlistedProcessEnvironment(extraKeys = [], source = process.env) {
  if (!Array.isArray(extraKeys) || extraKeys.some((key) => typeof key !== 'string' || !key.trim())) {
    throw errorWithCode('Subprocess envAllowlist must contain non-empty environment variable names', 'PROCESS_ENV_ALLOWLIST_INVALID');
  }
  const env = {};
  for (const key of new Set([...SAFE_SUBPROCESS_ENV_KEYS, ...extraKeys.map((key) => key.trim())])) {
    if (source[key] !== undefined) env[key] = source[key];
  }
  return env;
}

export function runProcess(command, args = [], { cwd, env, inheritEnv = true, timeoutMs = DEFAULT_COMMAND_TIMEOUT_MS, input, allowFailure = false } = {}) {
  const childEnv = inheritEnv
    ? (env ? { ...process.env, ...env } : process.env)
    : { ...(env || {}) };
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: childEnv,
      shell: false,
      stdio: ['pipe', 'pipe', 'pipe']
    });
    let stdout = '';
    let stderr = '';
    const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('error', (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on('close', (code, signal) => {
      clearTimeout(timer);
      const result = { code, signal, stdout, stderr };
      if (code === 0 || allowFailure) return resolve(result);
      const error = errorWithCode(`${command} ${args.join(' ')} failed with code ${code}`, 'PROCESS_FAILED', result);
      reject(error);
    });
    if (input !== undefined) child.stdin.end(input);
    else child.stdin.end();
  });
}

export async function git(repo, args, options = {}) {
  return runProcess('git', ['-c', 'core.hooksPath=/dev/null', ...args], { cwd: repo, ...options });
}

export async function resolveRepository(inputPath) {
  const candidate = path.resolve(inputPath);
  const { stdout } = await git(candidate, ['rev-parse', '--show-toplevel']);
  return (await fs.realpath(stdout.trim())).replaceAll('\\', '/');
}

export async function sourceIdentity(repo) {
  const [head, branch, status] = await Promise.all([
    git(repo, ['rev-parse', 'HEAD']),
    git(repo, ['branch', '--show-current']),
    git(repo, ['status', '--porcelain=v1', '-z'])
  ]);
  const dirtyPaths = status.stdout.split('\0').filter(Boolean).map((line) => line.slice(3));
  return {
    head: head.stdout.trim(),
    branch: branch.stdout.trim() || null,
    dirty: dirtyPaths.length > 0,
    dirtyPaths: normalizePathList(dirtyPaths)
  };
}

async function verifiedRefHead(repo, ref) {
  const result = await git(repo, ['rev-parse', '--verify', ref], { allowFailure: true });
  const head = result.code === 0 ? result.stdout.trim() : '';
  return /^[0-9a-f]{40,64}$/i.test(head) ? head : null;
}

export async function repositorySourceAuthority(repo, { observedIdentity = null, remote = 'origin' } = {}) {
  const observed = observedIdentity || await sourceIdentity(repo);
  const remoteUrl = await git(repo, ['remote', 'get-url', remote], { allowFailure: true });
  let remoteRef = null;
  let head = null;

  if (remoteUrl.code === 0 && remoteUrl.stdout.trim()) {
    const symbolic = await git(repo, ['symbolic-ref', '-q', `refs/remotes/${remote}/HEAD`], { allowFailure: true });
    const symbolicRef = symbolic.code === 0 ? symbolic.stdout.trim() : '';
    if (symbolicRef) {
      const symbolicHead = await verifiedRefHead(repo, symbolicRef);
      if (symbolicHead) {
        remoteRef = symbolicRef;
        head = symbolicHead;
      }
    }
    if (!remoteRef) {
      for (const branch of DEFAULT_REMOTE_BRANCH_CANDIDATES) {
        const candidate = `refs/remotes/${remote}/${branch}`;
        const candidateHead = await verifiedRefHead(repo, candidate);
        if (!candidateHead) continue;
        remoteRef = candidate;
        head = candidateHead;
        break;
      }
    }
  }

  const observedProjection = {
    head: observed.head,
    branch: observed.branch,
    dirty: observed.dirty
  };
  if (remoteRef && head) {
    const prefix = `refs/remotes/${remote}/`;
    const branch = remoteRef.startsWith(prefix) ? remoteRef.slice(prefix.length) : remoteRef;
    return {
      contract: 'veteran-source-authority-v1',
      scope: 'remote-default',
      remote,
      ref: remoteRef,
      head,
      branch,
      dirty: false,
      dirtyPaths: [],
      aligned: observed.head === head && !observed.dirty,
      observed: observedProjection
    };
  }

  return {
    contract: 'veteran-source-authority-v1',
    scope: 'checkout',
    remote: null,
    ref: 'HEAD',
    head: observed.head,
    branch: observed.branch,
    dirty: observed.dirty,
    dirtyPaths: observed.dirtyPaths,
    aligned: !observed.dirty,
    observed: observedProjection
  };
}

export function sourceIdentityFromAuthority(authority) {
  return {
    head: authority.head,
    branch: authority.branch || null,
    dirty: authority.dirty === true,
    dirtyPaths: normalizePathList(authority.dirtyPaths || [])
  };
}

export function sameSourceAuthorityLineage(left, right) {
  if (!left || !right) return false;
  return left.scope === right.scope
    && (left.remote || null) === (right.remote || null)
    && (left.ref || null) === (right.ref || null);
}

export async function withDetachedWorktree(repo, commitSha, target, callback) {
  if (typeof callback !== 'function') throw new TypeError('withDetachedWorktree requires a callback');
  const resolvedTarget = path.resolve(target);
  await fs.rm(resolvedTarget, { recursive: true, force: true });
  await fs.mkdir(path.dirname(resolvedTarget), { recursive: true });
  await git(repo, ['worktree', 'add', '--detach', resolvedTarget, commitSha]);
  try {
    return await callback(resolvedTarget);
  } finally {
    await git(repo, ['worktree', 'remove', '--force', resolvedTarget], { allowFailure: true });
    await fs.rm(resolvedTarget, { recursive: true, force: true });
    await git(repo, ['worktree', 'prune', '--expire', 'now'], { allowFailure: true });
  }
}

export async function changedPaths(repo, base = 'HEAD') {
  const tracked = await git(repo, ['diff', '--name-only', '-z', base], { allowFailure: false });
  const untracked = await git(repo, ['ls-files', '--others', '--exclude-standard', '-z']);
  return normalizePathList([
    ...tracked.stdout.split('\0').filter(Boolean),
    ...untracked.stdout.split('\0').filter(Boolean)
  ]);
}

export async function assertPathsWithinScope(repo, paths, writeSet) {
  const scopes = normalizePathList(writeSet);
  if (paths.length === 0) return;
  const broad = scopes.includes('.');
  for (const rel of paths) {
    if (rel.startsWith('../') || path.isAbsolute(rel)) {
      throw errorWithCode(`Write escaped repository: ${rel}`, 'WRITE_SCOPE_VIOLATION', { path: rel });
    }
    const abs = path.join(repo, rel);
    let real = abs;
    try { real = await fs.realpath(abs); } catch { real = path.resolve(abs); }
    if (!within(repo, real)) {
      throw errorWithCode(`Symlink traversal escaped repository: ${rel}`, 'SYMLINK_SCOPE_VIOLATION', { path: rel, real });
    }
    const allowed = broad || scopes.some((scope) => rel === scope || rel.startsWith(`${scope}/`));
    if (!allowed) throw errorWithCode(`Path outside declared write scope: ${rel}`, 'WRITE_SCOPE_VIOLATION', { path: rel, writeSet: scopes });
  }
}

export function writeSetsConflict(a = [], b = []) {
  const left = normalizePathList(a);
  const right = normalizePathList(b);
  if (left.includes('.') || right.includes('.')) return left.length > 0 && right.length > 0;
  return left.some((x) => right.some((y) => x === y || x.startsWith(`${y}/`) || y.startsWith(`${x}/`)));
}
