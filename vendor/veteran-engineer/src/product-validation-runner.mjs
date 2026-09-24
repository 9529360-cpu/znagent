import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { probeProcessGroup, processGroupMayBeAlive, signalProcessTree } from './process-lifecycle-authority.mjs';

const DEFAULT_LOG_LIMIT_BYTES = 128 * 1024;
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);
const SAFE_ENV_KEYS = [
  'PATH', 'Path', 'PATHEXT', 'SystemRoot', 'WINDIR', 'COMSPEC',
  'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SHELL'
];

function boundedNumber(value, fallback, min, max) {
  const n = Number(value ?? fallback);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(n)));
}

export function normalizeProductService(raw) {
  if (raw === undefined || raw === null) return null;
  if (typeof raw !== 'object' || Array.isArray(raw)) {
    throw Object.assign(new Error('Validation service must be an object'), { code: 'VALIDATION_SERVICE_INVALID' });
  }
  if (!Array.isArray(raw.command) || raw.command.length === 0) {
    throw Object.assign(new Error('Validation service command must be a non-empty argv array'), { code: 'VALIDATION_SERVICE_INVALID' });
  }
  const readiness = raw.readiness;
  if (!readiness || typeof readiness !== 'object' || Array.isArray(readiness) || !readiness.url) {
    throw Object.assign(new Error('Validation service requires readiness.url'), { code: 'VALIDATION_READINESS_INVALID' });
  }
  let url;
  try {
    url = new URL(String(readiness.url));
  } catch {
    throw Object.assign(new Error('Validation readiness URL is invalid'), { code: 'VALIDATION_READINESS_INVALID' });
  }
  if (url.protocol !== 'http:' || !LOOPBACK_HOSTS.has(url.hostname)) {
    throw Object.assign(new Error('Validation readiness URL must use loopback HTTP'), { code: 'VALIDATION_READINESS_URL_NOT_LOCAL' });
  }
  if (url.username || url.password || url.search || url.hash) {
    throw Object.assign(new Error('Validation readiness URL must not contain credentials, query parameters, or fragments'), { code: 'VALIDATION_READINESS_URL_UNSAFE' });
  }
  const method = String(readiness.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD'].includes(method)) {
    throw Object.assign(new Error('Validation readiness method must be GET or HEAD'), { code: 'VALIDATION_READINESS_INVALID' });
  }
  const statuses = readiness.statuses === undefined ? [200] : readiness.statuses;
  if (!Array.isArray(statuses) || statuses.length === 0 || statuses.some((value) => !Number.isInteger(value) || value < 100 || value > 599)) {
    throw Object.assign(new Error('Validation readiness statuses must be a non-empty HTTP status array'), { code: 'VALIDATION_READINESS_INVALID' });
  }
  return {
    command: raw.command.map(String),
    cwd: raw.cwd ? String(raw.cwd) : '.',
    readiness: {
      url: url.toString(),
      method,
      statuses: [...new Set(statuses)],
      timeoutMs: boundedNumber(readiness.timeoutMs, 30_000, 1_000, 300_000),
      intervalMs: boundedNumber(readiness.intervalMs, 200, 50, 5_000),
      requestTimeoutMs: boundedNumber(readiness.requestTimeoutMs, 1_000, 100, 15_000)
    },
    shutdownGraceMs: boundedNumber(raw.shutdownGraceMs, 2_000, 100, 15_000),
    logLimitBytes: boundedNumber(raw.logLimitBytes, DEFAULT_LOG_LIMIT_BYTES, 4_096, 1_048_576)
  };
}

function appendBounded(current, chunk, limitBytes) {
  const marker = '[... truncated ...]\n';
  const next = `${current}${chunk}`;
  if (Buffer.byteLength(next, 'utf8') <= limitBytes) return { text: next, truncated: false };
  const bodyLimit = Math.max(0, limitBytes - Buffer.byteLength(marker, 'utf8'));
  let text = next;
  while (text.length > 0 && Buffer.byteLength(text, 'utf8') > bodyLimit) text = text.slice(Math.max(1, Math.floor(text.length / 8)));
  return { text: `${marker}${text}`, truncated: true };
}

function isAlive(child) {
  return child && child.exitCode === null && child.signalCode === null;
}

function managedTreeAlive(child) {
  if (!child?.pid) return false;
  if (process.platform === 'win32') return isAlive(child);
  return processGroupMayBeAlive(probeProcessGroup(child.pid));
}

function terminateTree(child, signal) {
  if (!child?.pid) return;
  if (process.platform === 'win32' && signal !== 'SIGKILL') {
    try { child.kill(); } catch {}
    return;
  }
  signalProcessTree(child.pid, signal);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isolatedServiceEnvironment(environment, home) {
  const env = {};
  for (const key of SAFE_ENV_KEYS) {
    if (typeof environment?.[key] === 'string') env[key] = environment[key];
  }
  env.HOME = home;
  env.USERPROFILE = home;
  env.XDG_CONFIG_HOME = path.join(home, '.config');
  env.XDG_CACHE_HOME = path.join(home, '.cache');
  env.GIT_TERMINAL_PROMPT = '0';
  return env;
}

function cleanupServiceHome(serviceHandle) {
  const home = serviceHandle?.home;
  if (!home) return;
  serviceHandle.home = null;
  try { fs.rmSync(home, { recursive: true, force: true }); } catch {}
}

export function startValidationService(service, { cwd, environment = process.env } = {}) {
  const [command, ...args] = service.command;
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'veteran-validation-service-home-'));
  let child;
  try {
    child = spawn(command, args, {
      cwd,
      env: isolatedServiceEnvironment(environment, home),
      shell: false,
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true
    });
  } catch (error) {
    try { fs.rmSync(home, { recursive: true, force: true }); } catch {}
    throw error;
  }
  const logs = { stdout: '', stderr: '', stdoutTruncated: false, stderrTruncated: false };
  let spawnError = null;
  let closed = false;
  child.stdout?.setEncoding('utf8');
  child.stderr?.setEncoding('utf8');
  child.stdout?.on('data', (chunk) => {
    const next = appendBounded(logs.stdout, chunk, service.logLimitBytes);
    logs.stdout = next.text;
    logs.stdoutTruncated ||= next.truncated;
  });
  child.stderr?.on('data', (chunk) => {
    const next = appendBounded(logs.stderr, chunk, service.logLimitBytes);
    logs.stderr = next.text;
    logs.stderrTruncated ||= next.truncated;
  });
  child.on('error', (error) => { spawnError = error; });
  child.on('close', () => { closed = true; });
  return {
    child,
    logs,
    home,
    status: () => ({
      running: isAlive(child),
      closed,
      exitCode: child.exitCode,
      signal: child.signalCode,
      spawnError: spawnError ? String(spawnError.message || spawnError) : null,
      treeRunning: managedTreeAlive(child)
    })
  };
}

export async function waitForValidationReadiness(serviceHandle, readiness, { fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== 'function') {
    throw Object.assign(new Error('HTTP readiness requires fetch support'), { code: 'VALIDATION_READINESS_FETCH_UNAVAILABLE' });
  }
  const startedAt = Date.now();
  let attempts = 0;
  let lastStatus = null;
  let lastError = null;
  while ((Date.now() - startedAt) <= readiness.timeoutMs) {
    attempts += 1;
    const serviceStatus = serviceHandle.status();
    if (serviceStatus.spawnError || !serviceStatus.running) {
      return { ready: false, reason: 'service-exited', attempts, elapsedMs: Date.now() - startedAt, lastStatus, lastError, serviceStatus };
    }
    const remainingMs = Math.max(1, readiness.timeoutMs - (Date.now() - startedAt));
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), Math.min(readiness.requestTimeoutMs, remainingMs));
    try {
      const response = await fetchImpl(readiness.url, { method: readiness.method, redirect: 'manual', signal: controller.signal });
      lastStatus = response.status;
      lastError = null;
      const accepted = readiness.statuses.includes(response.status);
      await response.body?.cancel().catch(() => {});
      if (accepted) {
        return { ready: true, reason: 'http-ready', attempts, elapsedMs: Date.now() - startedAt, lastStatus };
      }
    } catch (error) {
      lastError = error?.name === 'AbortError' ? 'request-timeout' : String(error?.message || error);
    } finally {
      clearTimeout(timer);
    }
    const afterAttemptRemaining = readiness.timeoutMs - (Date.now() - startedAt);
    if (afterAttemptRemaining > 0) await delay(Math.min(readiness.intervalMs, afterAttemptRemaining));
  }
  return { ready: false, reason: 'readiness-timeout', attempts, elapsedMs: Date.now() - startedAt, lastStatus, lastError, serviceStatus: serviceHandle.status() };
}

export async function stopValidationService(serviceHandle, graceMs) {
  const before = serviceHandle.status();
  if (!before.treeRunning && !before.running) {
    const after = serviceHandle.status();
    cleanupServiceHome(serviceHandle);
    return { attempted: false, forced: false, before, after };
  }
  terminateTree(serviceHandle.child, 'SIGTERM');
  const deadline = Date.now() + graceMs;
  while ((serviceHandle.status().treeRunning || serviceHandle.status().running) && Date.now() < deadline) await delay(25);
  let forced = false;
  if (serviceHandle.status().treeRunning || serviceHandle.status().running) {
    forced = true;
    terminateTree(serviceHandle.child, 'SIGKILL');
    const killDeadline = Date.now() + 1_000;
    while ((serviceHandle.status().treeRunning || serviceHandle.status().running) && Date.now() < killDeadline) await delay(25);
  }
  const after = serviceHandle.status();
  cleanupServiceHome(serviceHandle);
  return { attempted: true, forced, before, after };
}
