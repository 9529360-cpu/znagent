import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { git, resolveRepository, runProcess, sourceIdentity } from './git.mjs';
import { PROCESS_LIFECYCLE_STATE, probeProcess } from './process-lifecycle-authority.mjs';
import { ensureDir, errorWithCode, pathExists, randomId, sha256, sleep, within } from './util.mjs';

const MANAGED_REPO_LOCK_TIMEOUT_MS = 120_000;
const MANAGED_REPO_LOCK_STALE_MS = 300_000;
const ALLOWED_URL_PROTOCOLS = new Set(['https:', 'ssh:', 'file:']);
const STORABLE_REMOTE_PROTOCOLS = new Set(['http:', 'https:', 'ssh:', 'git:', 'file:']);
const SCP_REMOTE_RE = /^(?<user>[A-Za-z0-9._-]+)@(?<host>[A-Za-z0-9.-]+):(?<repo>[^\s]+)$/;

function safeSegment(value, fallback = 'repo') {
  const cleaned = String(value || '').replace(/\.git$/i, '').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 64);
  return cleaned || fallback;
}

function suggestedNameFromPathname(pathname) {
  const normalized = String(pathname || '').replace(/\/+$/, '');
  const segment = normalized.split('/').filter(Boolean).at(-1) || 'repository';
  return segment.replace(/\.git$/i, '') || 'repository';
}

function normalizeScpRemote(value) {
  const match = String(value).match(SCP_REMOTE_RE);
  if (!match) return null;
  const user = match.groups.user;
  const host = match.groups.host.toLowerCase();
  const repo = match.groups.repo.replace(/\/+$/, '');
  if (!repo || repo.startsWith('-')) {
    throw errorWithCode('SSH repository path is invalid', 'PROJECT_REMOTE_URL_INVALID');
  }
  const canonicalRepo = repo.replace(/\.git$/i, '');
  return {
    cloneUrl: `${user}@${host}:${repo}`,
    canonicalUrl: `ssh://${user}@${host}/${canonicalRepo}`,
    displayUrl: `${user}@${host}:${repo}`,
    suggestedName: suggestedNameFromPathname(repo),
    protocol: 'ssh:'
  };
}

export function normalizeRemoteRepositoryUrl(input) {
  if (typeof input !== 'string' || !input.trim()) {
    throw errorWithCode('repoUrl must be a non-empty string', 'PROJECT_REMOTE_URL_INVALID');
  }
  const value = input.trim();
  if (/\p{C}/u.test(value)) throw errorWithCode('repoUrl contains control characters', 'PROJECT_REMOTE_URL_INVALID');

  const scp = normalizeScpRemote(value);
  if (scp) return scp;

  let url;
  try {
    url = new URL(value);
  } catch {
    throw errorWithCode('repoUrl must use HTTPS, SSH, file://, or SSH scp-style syntax', 'PROJECT_REMOTE_URL_UNSUPPORTED');
  }
  if (!ALLOWED_URL_PROTOCOLS.has(url.protocol)) {
    throw errorWithCode(`Unsupported repository URL protocol: ${url.protocol}`, 'PROJECT_REMOTE_URL_UNSUPPORTED', {
      allowedProtocols: [...ALLOWED_URL_PROTOCOLS]
    });
  }
  if (url.search || url.hash) {
    throw errorWithCode('Repository URLs may not contain query strings or fragments', 'PROJECT_REMOTE_URL_CREDENTIALS_FORBIDDEN');
  }
  if (url.protocol === 'https:' && (url.username || url.password)) {
    throw errorWithCode('HTTPS repository URLs may not embed credentials; use a credential helper or SSH', 'PROJECT_REMOTE_URL_CREDENTIALS_FORBIDDEN');
  }
  if (url.protocol === 'ssh:' && url.password) {
    throw errorWithCode('SSH repository URLs may not embed passwords', 'PROJECT_REMOTE_URL_CREDENTIALS_FORBIDDEN');
  }
  if (url.protocol === 'file:') {
    if (url.username || url.password || (url.hostname && url.hostname !== 'localhost')) {
      throw errorWithCode('file:// repository URLs must be local and credential-free', 'PROJECT_REMOTE_URL_INVALID');
    }
    const localPath = fileURLToPath(url);
    if (!path.isAbsolute(localPath)) throw errorWithCode('file:// repository URL must resolve to an absolute path', 'PROJECT_REMOTE_URL_INVALID');
  } else if (!url.hostname) {
    throw errorWithCode('Repository URL must include a host', 'PROJECT_REMOTE_URL_INVALID');
  }

  const cloneUrl = url.href;
  const canonical = new URL(url.href);
  canonical.hostname = canonical.hostname.toLowerCase();
  canonical.search = '';
  canonical.hash = '';
  canonical.pathname = canonical.pathname.replace(/\/+$/, '');
  if (canonical.protocol !== 'file:') canonical.pathname = canonical.pathname.replace(/\.git$/i, '');
  const display = new URL(url.href);
  if (display.protocol === 'https:') display.username = '';
  display.password = '';
  display.search = '';
  display.hash = '';
  return {
    cloneUrl,
    canonicalUrl: canonical.href,
    displayUrl: display.href,
    suggestedName: suggestedNameFromPathname(url.pathname),
    protocol: url.protocol
  };
}

export function sanitizeStoredRemoteUrl(input) {
  if (typeof input !== 'string' || !input.trim()) return null;
  const value = input.trim();
  const scp = normalizeScpRemote(value);
  if (scp) return scp.displayUrl;
  try {
    const url = new URL(value);
    if (!STORABLE_REMOTE_PROTOCOLS.has(url.protocol)) return null;
    if (url.protocol !== 'ssh:') url.username = '';
    url.password = '';
    url.search = '';
    url.hash = '';
    return url.href;
  } catch {
    return null;
  }
}

async function acquireManagedRepoLock(lockPath) {
  const started = Date.now();
  const token = randomId('repolock');
  while (true) {
    try {
      const handle = await fs.open(lockPath, 'wx', 0o600);
      try {
        await handle.writeFile(JSON.stringify({ pid: process.pid, token, acquiredAt: new Date().toISOString() }));
      } finally {
        await handle.close();
      }
      return async () => {
        try {
          const current = JSON.parse(await fs.readFile(lockPath, 'utf8'));
          if (current.token === token) await fs.unlink(lockPath);
        } catch (error) {
          if (error?.code !== 'ENOENT') throw error;
        }
      };
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      let stale = false;
      try {
        const [stat, raw] = await Promise.all([fs.stat(lockPath), fs.readFile(lockPath, 'utf8')]);
        const ageMs = Date.now() - stat.mtimeMs;
        try {
          const lock = JSON.parse(raw);
          const ownerProbe = probeProcess(lock.pid);
          stale = ageMs > MANAGED_REPO_LOCK_STALE_MS && ownerProbe.state === PROCESS_LIFECYCLE_STATE.MISSING;
        } catch {
          stale = ageMs > MANAGED_REPO_LOCK_STALE_MS;
        }
      } catch (inspectError) {
        if (inspectError?.code === 'ENOENT') continue;
        throw inspectError;
      }
      if (stale) {
        await fs.unlink(lockPath).catch((unlinkError) => {
          if (unlinkError?.code !== 'ENOENT') throw unlinkError;
        });
        continue;
      }
      if (Date.now() - started >= MANAGED_REPO_LOCK_TIMEOUT_MS) {
        throw errorWithCode('Timed out waiting for managed repository lock', 'PROJECT_REMOTE_LOCK_TIMEOUT', { lockPath });
      }
      await sleep(50);
    }
  }
}

async function assertManagedCheckoutMatches(repoPath, remote) {
  const resolved = await resolveRepository(repoPath);
  const expected = await fs.realpath(repoPath);
  if (resolved !== expected.replaceAll('\\', '/')) {
    throw errorWithCode('Managed repository path does not resolve to its own Git root', 'PROJECT_REMOTE_CHECKOUT_INVALID', { repoPath, resolved });
  }
  const origin = await git(resolved, ['config', '--get', 'remote.origin.url'], { allowFailure: true });
  if (origin.code !== 0 || !origin.stdout.trim()) {
    throw errorWithCode('Managed repository has no origin remote', 'PROJECT_REMOTE_CHECKOUT_INVALID', { repoPath: resolved });
  }
  let existing;
  try {
    existing = normalizeRemoteRepositoryUrl(origin.stdout.trim());
  } catch (cause) {
    const error = errorWithCode('Managed repository origin is not a supported remote URL', 'PROJECT_REMOTE_CHECKOUT_INVALID', { repoPath: resolved });
    error.cause = cause;
    throw error;
  }
  if (existing.canonicalUrl !== remote.canonicalUrl) {
    throw errorWithCode('Managed repository origin does not match requested repoUrl', 'PROJECT_REMOTE_CHECKOUT_CONFLICT', {
      repoPath: resolved,
      existingRemoteUrl: existing.displayUrl,
      requestedRemoteUrl: remote.displayUrl
    });
  }
  return resolved;
}

async function refreshManagedCheckout(repoPath) {
  const before = await sourceIdentity(repoPath);
  if (before.dirty) {
    throw errorWithCode('Managed repository checkout is dirty; refusing remote refresh', 'PROJECT_REMOTE_CHECKOUT_DIRTY', {
      repoPath,
      dirtyPaths: before.dirtyPaths
    });
  }
  if (!before.branch) {
    throw errorWithCode('Managed repository checkout is detached; refusing remote refresh', 'PROJECT_REMOTE_CHECKOUT_DETACHED', { repoPath });
  }
  try {
    await git(repoPath, ['fetch', '--prune', 'origin'], { env: { GIT_TERMINAL_PROMPT: '0' } });
  } catch (cause) {
    const error = errorWithCode('Failed to refresh managed repository from origin', 'PROJECT_REMOTE_REFRESH_FAILED', { repoPath });
    error.cause = cause;
    throw error;
  }
  const upstream = await git(repoPath, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'], { allowFailure: true });
  if (upstream.code !== 0 || !upstream.stdout.trim()) {
    throw errorWithCode('Managed repository branch has no upstream tracking branch', 'PROJECT_REMOTE_UPSTREAM_MISSING', {
      repoPath,
      branch: before.branch
    });
  }
  const remoteRef = upstream.stdout.trim();
  const counts = await git(repoPath, ['rev-list', '--left-right', '--count', `${remoteRef}...HEAD`]);
  const [remoteAheadRaw, localAheadRaw] = counts.stdout.trim().split(/\s+/);
  const remoteAhead = Number(remoteAheadRaw || 0);
  const localAhead = Number(localAheadRaw || 0);
  if (!Number.isInteger(remoteAhead) || !Number.isInteger(localAhead)) {
    throw errorWithCode('Could not determine managed repository divergence', 'PROJECT_REMOTE_REFRESH_INVALID', { repoPath, output: counts.stdout.trim() });
  }
  if (localAhead > 0) {
    throw errorWithCode('Managed repository contains local commits and will not be reset automatically', 'PROJECT_REMOTE_CHECKOUT_DIVERGED', {
      repoPath,
      branch: before.branch,
      upstream: remoteRef,
      localAhead,
      remoteAhead
    });
  }
  if (remoteAhead > 0) {
    try {
      await git(repoPath, ['merge', '--ff-only', remoteRef]);
    } catch (cause) {
      const error = errorWithCode('Managed repository could not fast-forward to origin', 'PROJECT_REMOTE_FAST_FORWARD_FAILED', {
        repoPath,
        branch: before.branch,
        upstream: remoteRef
      });
      error.cause = cause;
      throw error;
    }
  }
  const after = await sourceIdentity(repoPath);
  return { refreshed: remoteAhead > 0, beforeHead: before.head, head: after.head, branch: after.branch, upstream: remoteRef };
}

async function cloneManagedCheckout(remote, stagingPath) {
  const args = [
    '-c', 'core.hooksPath=/dev/null',
    '-c', 'init.templateDir=',
    '-c', 'protocol.ext.allow=never',
    'clone', '--no-recurse-submodules', '--origin', 'origin', '--', remote.cloneUrl, stagingPath
  ];
  try {
    await runProcess('git', args, {
      cwd: path.dirname(stagingPath),
      env: { GIT_TERMINAL_PROMPT: '0' }
    });
  } catch (cause) {
    const error = errorWithCode('Failed to clone repository into managed checkout', 'PROJECT_REMOTE_CLONE_FAILED', {
      remoteUrl: remote.displayUrl
    });
    error.cause = cause;
    throw error;
  }
}

export async function acquireRemoteRepository({ repoUrl, managedRoot, refresh = true } = {}) {
  if (typeof managedRoot !== 'string' || !managedRoot) {
    throw errorWithCode('Managed repository root is required', 'PROJECT_REMOTE_ROOT_REQUIRED');
  }
  const remote = normalizeRemoteRepositoryUrl(repoUrl);
  const root = path.resolve(managedRoot);
  await ensureDir(root);
  const rootReal = await fs.realpath(root);
  const key = sha256(remote.canonicalUrl).slice(0, 20);
  const target = path.join(rootReal, `${safeSegment(remote.suggestedName)}-${key.slice(0, 12)}`);
  if (!within(rootReal, target)) throw errorWithCode('Managed repository target escaped root', 'PROJECT_REMOTE_PATH_INVALID');
  const lockPath = path.join(rootReal, `.repo-${key}.lock`);
  const release = await acquireManagedRepoLock(lockPath);
  let stagingPath = null;
  try {
    let reused = false;
    if (!(await pathExists(target))) {
      stagingPath = path.join(rootReal, `.clone-${key}-${randomId('tmp')}`);
      await cloneManagedCheckout(remote, stagingPath);
      await assertManagedCheckoutMatches(stagingPath, remote);
      try {
        await fs.rename(stagingPath, target);
        stagingPath = null;
      } catch (error) {
        if (!['EEXIST', 'ENOTEMPTY'].includes(error?.code)) throw error;
        await fs.rm(stagingPath, { recursive: true, force: true });
        stagingPath = null;
        reused = true;
      }
    } else {
      reused = true;
    }
    const repoPath = await assertManagedCheckoutMatches(target, remote);
    const refreshResult = reused && refresh ? await refreshManagedCheckout(repoPath) : {
      refreshed: false,
      beforeHead: null,
      ...(await sourceIdentity(repoPath)),
      upstream: null
    };
    return {
      repoPath,
      remoteUrl: remote.displayUrl,
      canonicalRemoteUrl: remote.canonicalUrl,
      suggestedName: remote.suggestedName,
      managed: true,
      reused,
      refresh: refreshResult
    };
  } finally {
    if (stagingPath) await fs.rm(stagingPath, { recursive: true, force: true }).catch(() => {});
    await release();
  }
}
