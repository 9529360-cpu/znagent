import { spawn, spawnSync } from 'node:child_process';
import { rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  PROCESS_LIFECYCLE_STATE,
  probeProcessGroup,
  signalProcessTree
} from './process-lifecycle-authority.mjs';

const FORCE_KILL_AFTER_MS = 3_000;
const RUNTIME_PROFILE_PREFIX = 'veteran-engineer-';
const SUPERVISOR_ENV_KEYS = new Set([
  'PATH', 'PATHEXT', 'SYSTEMROOT', 'COMSPEC', 'WINDIR',
  'TMP', 'TEMP', 'TMPDIR', 'LANG', 'LC_ALL'
]);

function scrubInheritedEnvironment() {
  for (const key of Object.keys(process.env)) {
    if (!SUPERVISOR_ENV_KEYS.has(key.toUpperCase())) delete process.env[key];
  }
}

scrubInheritedEnvironment();

let worker = null;
let container = null;
let workerEnv = null;
let forceTimer = null;
let reapTimer = null;
let pendingSignal = null;
let started = false;
let settled = false;
let workerOutcome = null;
let workerStreamsClosed = false;
let workerTreeReaped = false;

process.stdout.on('error', () => {});
process.stderr.on('error', () => {});

function cleanupContainer() {
  if (!container?.engine || !container?.name) return;
  try {
    spawnSync(container.engine, ['rm', '-f', container.name], {
      env: workerEnv || process.env,
      stdio: 'ignore',
      windowsHide: true,
      timeout: 5_000
    });
  } catch {
    // Best effort. The parent runtime records durable reconciliation state.
  }
}

function disposableRuntimeProfileRoot() {
  if (container) return null;
  const tmp = workerEnv?.TMPDIR;
  if (typeof tmp !== 'string' || !tmp.length) return null;
  const resolvedTmp = path.resolve(tmp);
  if (path.basename(resolvedTmp) !== 'tmp') return null;
  const root = path.dirname(resolvedTmp);
  const tempRoot = path.resolve(os.tmpdir());
  const relative = path.relative(tempRoot, root);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) return null;
  if (!path.basename(root).startsWith(RUNTIME_PROFILE_PREFIX)) return null;
  return root;
}

function cleanupRuntimeProfile() {
  const root = disposableRuntimeProfileRoot();
  if (!root) return;
  try {
    rmSync(root, { recursive: true, force: true });
  } catch {
    // Best effort. Runtime cleanup can sweep any remaining orphan later.
  }
}

function scheduleForceKill() {
  if (forceTimer || !worker?.pid) return;
  forceTimer = setTimeout(() => {
    signalProcessTree(worker.pid, 'SIGKILL');
    cleanupContainer();
  }, FORCE_KILL_AFTER_MS);
}

function terminateWorker(signal = 'SIGTERM') {
  if (signal === 'SIGKILL') pendingSignal = 'SIGKILL';
  else if (!pendingSignal) pendingSignal = 'SIGTERM';
  if (!worker?.pid) return false;
  const effectiveSignal = pendingSignal === 'SIGKILL' ? 'SIGKILL' : signal;
  const signalled = signalProcessTree(worker.pid, effectiveSignal).signalled;
  cleanupContainer();
  if (effectiveSignal !== 'SIGKILL' && signalled) scheduleForceKill();
  return signalled;
}

function send(message, callback = null) {
  if (!process.connected || typeof process.send !== 'function') {
    callback?.();
    return;
  }
  try {
    process.send(message, callback || undefined);
  } catch {
    callback?.();
  }
}

function finish(outcome, exitCode) {
  if (settled) return;
  settled = true;
  if (forceTimer) clearTimeout(forceTimer);
  forceTimer = null;
  if (reapTimer) clearTimeout(reapTimer);
  reapTimer = null;
  cleanupContainer();
  cleanupRuntimeProfile();
  send({ type: 'outcome', ...outcome }, () => process.exit(exitCode));
}

function maybeFinishWorkerOutcome() {
  if (settled || !workerOutcome || !workerStreamsClosed || !workerTreeReaped) return;
  const { code, signal } = workerOutcome;
  const exitCode = Number.isInteger(code) && code >= 0 ? Math.min(code, 255) : 1;
  finish({ code, signal, spawnError: null }, exitCode);
}

function markWorkerTreeReaped() {
  if (workerTreeReaped) return;
  workerTreeReaped = true;
  if (reapTimer) clearTimeout(reapTimer);
  reapTimer = null;
  maybeFinishWorkerOutcome();
}

function reapExitedWorkerGroup(pid) {
  if (!Number.isInteger(pid) || pid <= 0) {
    markWorkerTreeReaped();
    return;
  }

  const signalled = signalProcessTree(pid, 'SIGTERM').signalled;
  if (process.platform === 'win32') {
    // taskkill /T is the strongest available best effort after the root process exits.
    markWorkerTreeReaped();
    return;
  }
  if (signalled) scheduleForceKill();

  const poll = () => {
    const probe = probeProcessGroup(pid);
    if (probe.state === PROCESS_LIFECYCLE_STATE.MISSING) {
      markWorkerTreeReaped();
      return;
    }
    if (!forceTimer) scheduleForceKill();
    reapTimer = setTimeout(poll, 25);
  };
  poll();
}

function failStart(error) {
  const spawnError = {
    code: error?.code || 'WORKER_SPAWN_FAILED',
    message: String(error?.message || error).slice(0, 1_000)
  };
  finish({ code: null, signal: null, spawnError }, 127);
}

function startWorker(message) {
  if (started || settled) return;
  started = true;
  const command = typeof message?.command === 'string' ? message.command : '';
  const args = Array.isArray(message?.args) ? message.args : [];
  const cwd = typeof message?.cwd === 'string' ? message.cwd : process.cwd();
  workerEnv = message?.env && typeof message.env === 'object' ? message.env : {};
  container = message?.container && typeof message.container === 'object' ? message.container : null;
  if (!command) {
    failStart(Object.assign(new Error('Worker supervisor requires a command'), { code: 'WORKER_CONFIG_INVALID' }));
    return;
  }

  try {
    worker = spawn(command, args, {
      cwd,
      env: workerEnv,
      shell: false,
      detached: process.platform !== 'win32',
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe']
    });
  } catch (error) {
    failStart(error);
    return;
  }

  worker.stdout?.pipe(process.stdout, { end: false });
  worker.stderr?.pipe(process.stderr, { end: false });
  worker.on('error', failStart);
  worker.on('exit', (code, signal) => {
    workerOutcome = { code, signal };
    reapExitedWorkerGroup(worker.pid);
  });
  worker.on('close', () => {
    workerStreamsClosed = true;
    maybeFinishWorkerOutcome();
  });

  const stdin = message?.stdin;
  if (stdin !== undefined && stdin !== null) worker.stdin.end(String(stdin));
  else worker.stdin.end();

  send({ type: 'started', pid: worker.pid });
  if (pendingSignal) terminateWorker(pendingSignal);
}

process.on('message', (message) => {
  if (message?.type === 'start') {
    startWorker(message);
    return;
  }
  if (message?.type === 'terminate') {
    terminateWorker(message.signal === 'SIGKILL' ? 'SIGKILL' : 'SIGTERM');
  }
});

process.on('disconnect', () => {
  if (!started) {
    cleanupRuntimeProfile();
    process.exit(1);
    return;
  }
  terminateWorker('SIGTERM');
});

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => {
    if (!started) {
      cleanupRuntimeProfile();
      process.exit(1);
      return;
    }
    terminateWorker('SIGTERM');
  });
}
