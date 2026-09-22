import crypto from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  PROCESS_LIFECYCLE_STATE,
  probeProcess,
  signalProcessTree
} from './process-lifecycle-authority.mjs';
import {
  defaultRemoteHostConfigPath,
  readRemoteHostConfig
} from './remote-host-config.mjs';

export const REMOTE_HOST_SERVICE_SCHEMA_VERSION = 1;
export const REMOTE_HOST_SERVICE_CONTROL_VERSION = 1;
export const DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_BYTES = 5 * 1024 * 1024;
export const DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_FILES = 4;

const SERVICE_DESIRED_STATES = new Set(['running', 'paused', 'stopped']);
const DEFAULT_POLL_MS = 500;
const DEFAULT_RESTART_BASE_MS = 1_000;
const DEFAULT_RESTART_MAX_MS = 30_000;
const DEFAULT_STABLE_RESET_MS = 30_000;
const DEFAULT_SHUTDOWN_GRACE_MS = 5_000;

function codedError(code, message, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const WINDOWS_REPLACE_RETRY_CODES = new Set(['EPERM', 'EACCES', 'EBUSY']);
const WINDOWS_REPLACE_MAX_ATTEMPTS = 8;

async function renameWithTransientWindowsRetry(source, target) {
  for (let attempt = 0; attempt < WINDOWS_REPLACE_MAX_ATTEMPTS; attempt += 1) {
    try {
      await fs.rename(source, target);
      return;
    } catch (error) {
      const retryable = process.platform === 'win32'
        && WINDOWS_REPLACE_RETRY_CODES.has(error?.code)
        && attempt < WINDOWS_REPLACE_MAX_ATTEMPTS - 1;
      if (!retryable) throw error;
      await delay(Math.min(200, 10 * (2 ** attempt)));
    }
  }
}

function servicePaths(serviceRoot = defaultRemoteHostServiceRoot()) {
  const root = path.resolve(serviceRoot);
  const logDir = path.join(root, 'logs');
  return {
    root,
    statePath: path.join(root, 'service.json'),
    controlPath: path.join(root, 'control.json'),
    pidPath: path.join(root, 'pid.json'),
    lockPath: path.join(root, 'supervisor.lock'),
    launcherPath: path.join(root, 'remote-host-service.ps1'),
    logDir,
    logPath: path.join(logDir, 'remote-host.log')
  };
}

export function defaultRemoteHostServiceRoot() {
  return path.join(os.homedir(), '.veteran-engineer', 'remote-host-service');
}

export function defaultRemoteHostCliPath() {
  return fileURLToPath(new URL('../bin/veteran-remote-host.mjs', import.meta.url));
}

function normalizePositiveInteger(value, fallback, label) {
  const number = value == null ? fallback : Number(value);
  if (!Number.isInteger(number) || number <= 0) {
    throw codedError('REMOTE_HOST_SERVICE_OPTION_INVALID', `${label} must be a positive integer`);
  }
  return number;
}

function validateLauncherPath(value, label) {
  const text = path.resolve(String(value || ''));
  if (!text || /[\r\n\0]/u.test(text)) {
    throw codedError('REMOTE_HOST_SERVICE_PATH_INVALID', `${label} contains characters that cannot be represented safely in the Windows launcher`);
  }
  return text;
}

function powershellQuote(value, label) {
  return `'${validateLauncherPath(value, label).replaceAll("'", "''")}'`;
}

function taskIdForConfig(configPath) {
  return crypto.createHash('sha256').update(path.resolve(configPath)).digest('hex').slice(0, 12);
}

export function buildWindowsScheduledTaskSpec({
  configPath = defaultRemoteHostConfigPath(),
  serviceRoot = defaultRemoteHostServiceRoot(),
  nodePath = process.execPath,
  cliPath = defaultRemoteHostCliPath()
} = {}) {
  const resolvedConfigPath = validateLauncherPath(configPath, 'configPath');
  const resolvedServiceRoot = validateLauncherPath(serviceRoot, 'serviceRoot');
  const resolvedNodePath = validateLauncherPath(nodePath, 'nodePath');
  const resolvedCliPath = validateLauncherPath(cliPath, 'cliPath');
  const launcherPath = path.join(resolvedServiceRoot, 'remote-host-service.ps1');
  const serviceId = `remote-host-${taskIdForConfig(resolvedConfigPath)}`;
  const taskName = `Veteran Remote Host ${taskIdForConfig(resolvedConfigPath)}`;
  const launcherContent = [
    "\uFEFF$ErrorActionPreference = 'Stop'",
    `& ${powershellQuote(resolvedNodePath, 'nodePath')} ${powershellQuote(resolvedCliPath, 'cliPath')} 'supervise' '--config' ${powershellQuote(resolvedConfigPath, 'configPath')} '--service-root' ${powershellQuote(resolvedServiceRoot, 'serviceRoot')}`,
    'exit $LASTEXITCODE',
    ''
  ].join('\r\n');
  const taskAction = `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "${launcherPath}"`;
  return {
    serviceId,
    taskName,
    launcherPath,
    launcherContent,
    taskAction,
    createArgs: ['/Create', '/TN', taskName, '/TR', taskAction, '/SC', 'ONLOGON', '/F'],
    runArgs: ['/Run', '/TN', taskName],
    queryArgs: ['/Query', '/TN', taskName],
    endArgs: ['/End', '/TN', taskName],
    deleteArgs: ['/Delete', '/TN', taskName, '/F']
  };
}

async function atomicWriteJson(target, value) {
  await fs.mkdir(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  try {
    await renameWithTransientWindowsRetry(temporary, target);
  } catch (error) {
    await fs.rm(temporary, { force: true }).catch(() => {});
    throw error;
  }
  await fs.chmod(target, 0o600).catch(() => {});
}

async function readJsonIfPresent(target) {
  try {
    return JSON.parse(await fs.readFile(target, 'utf8'));
  } catch (error) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}

async function readServiceState(paths) {
  const state = await readJsonIfPresent(paths.statePath);
  if (!state) return null;
  if (
    state.schemaVersion !== REMOTE_HOST_SERVICE_SCHEMA_VERSION
    || state.platform !== 'win32'
    || typeof state.serviceId !== 'string'
    || typeof state.taskName !== 'string'
    || typeof state.configPath !== 'string'
    || typeof state.nodePath !== 'string'
    || typeof state.cliPath !== 'string'
    || typeof state.logPath !== 'string'
  ) {
    throw codedError('REMOTE_HOST_SERVICE_STATE_INVALID', `Invalid Remote Host service state: ${paths.statePath}`);
  }
  return state;
}

async function readControl(paths, fallback = 'running') {
  const control = await readJsonIfPresent(paths.controlPath);
  if (!control) {
    return {
      schemaVersion: REMOTE_HOST_SERVICE_CONTROL_VERSION,
      desiredState: fallback,
      updatedAt: null
    };
  }
  if (control.schemaVersion !== REMOTE_HOST_SERVICE_CONTROL_VERSION || !SERVICE_DESIRED_STATES.has(control.desiredState)) {
    throw codedError('REMOTE_HOST_SERVICE_CONTROL_INVALID', `Invalid Remote Host service control: ${paths.controlPath}`);
  }
  return control;
}

async function writeControl(paths, desiredState) {
  if (!SERVICE_DESIRED_STATES.has(desiredState)) {
    throw codedError('REMOTE_HOST_SERVICE_CONTROL_INVALID', `Unsupported Remote Host service desired state: ${desiredState}`);
  }
  const control = {
    schemaVersion: REMOTE_HOST_SERVICE_CONTROL_VERSION,
    desiredState,
    updatedAt: new Date().toISOString(),
    requestedByPid: process.pid
  };
  await atomicWriteJson(paths.controlPath, control);
  return control;
}

function runWindowsTask(args, {
  runSync = spawnSync,
  allowFailure = false,
  code = 'REMOTE_HOST_SERVICE_TASK_FAILED'
} = {}) {
  let result;
  try {
    result = runSync('schtasks', args, {
      encoding: 'utf8',
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    });
  } catch (error) {
    if (allowFailure) return { ok: false, status: null, error };
    throw codedError(code, `schtasks ${args[0]} failed: ${error?.message || String(error)}`);
  }
  const ok = !result?.error && result?.status === 0;
  if (!ok && !allowFailure) {
    const reason = result?.error?.message || String(result?.stderr || result?.stdout || `exit ${result?.status ?? 'unknown'}`).trim();
    throw codedError(code, `schtasks ${args[0]} failed: ${reason}`, { status: result?.status ?? null });
  }
  return { ok, status: result?.status ?? null, result };
}

async function writeLauncher(spec) {
  await fs.mkdir(path.dirname(spec.launcherPath), { recursive: true });
  const temporary = `${spec.launcherPath}.${process.pid}.${crypto.randomUUID()}.tmp`;
  await fs.writeFile(temporary, spec.launcherContent, { mode: 0o600 });
  try {
    await renameWithTransientWindowsRetry(temporary, spec.launcherPath);
  } catch (error) {
    await fs.rm(temporary, { force: true }).catch(() => {});
    throw error;
  }
  await fs.chmod(spec.launcherPath, 0o600).catch(() => {});
}

function publicServiceState(state) {
  if (!state) return null;
  return {
    schemaVersion: state.schemaVersion,
    serviceId: state.serviceId,
    taskName: state.taskName,
    platform: state.platform,
    configPath: state.configPath,
    serviceRoot: state.serviceRoot,
    installedAt: state.installedAt,
    repairedAt: state.repairedAt || null,
    nodePath: state.nodePath,
    cliPath: state.cliPath,
    launcherPath: state.launcherPath,
    logPath: state.logPath,
    maxLogBytes: state.maxLogBytes,
    maxLogFiles: state.maxLogFiles
  };
}

function processProbe(pid, kill = process.kill) {
  return probeProcess(Number(pid), { kill });
}

async function readPidSnapshot(paths) {
  const snapshot = await readJsonIfPresent(paths.pidPath);
  if (!snapshot) return null;
  return {
    supervisorPid: Number(snapshot.supervisorPid) || null,
    childPid: Number(snapshot.childPid) || null,
    startedAt: snapshot.startedAt || null,
    childStartedAt: snapshot.childStartedAt || null,
    updatedAt: snapshot.updatedAt || null
  };
}

async function writePidSnapshot(paths, snapshot) {
  await atomicWriteJson(paths.pidPath, {
    schemaVersion: 1,
    ...snapshot,
    updatedAt: new Date().toISOString()
  });
}

async function taskRegistered(state, { platform = process.platform, runSync = spawnSync } = {}) {
  if (!state || platform !== 'win32') return null;
  return runWindowsTask(['/Query', '/TN', state.taskName], { runSync, allowFailure: true }).ok;
}

export async function remoteHostServiceStatus({
  serviceRoot = defaultRemoteHostServiceRoot(),
  platform = process.platform,
  runSync = spawnSync,
  kill = process.kill
} = {}) {
  const paths = servicePaths(serviceRoot);
  const state = await readServiceState(paths);
  if (!state) {
    return {
      installed: false,
      serviceRoot: paths.root,
      registration: 'absent',
      desiredState: null,
      runtimeState: 'stopped',
      supervisor: null,
      child: null,
      logPath: paths.logPath
    };
  }
  const [control, pid, registered] = await Promise.all([
    readControl(paths),
    readPidSnapshot(paths),
    taskRegistered(state, { platform, runSync })
  ]);
  const supervisor = pid?.supervisorPid ? processProbe(pid.supervisorPid, kill) : null;
  const child = pid?.childPid ? processProbe(pid.childPid, kill) : null;
  let runtimeState = 'waiting';
  if (control.desiredState === 'paused') runtimeState = 'paused';
  else if (control.desiredState === 'stopped') runtimeState = 'stopped';
  else if (supervisor?.state === PROCESS_LIFECYCLE_STATE.ALIVE && child?.state === PROCESS_LIFECYCLE_STATE.ALIVE) runtimeState = 'running';
  else if (supervisor?.state === PROCESS_LIFECYCLE_STATE.ALIVE) runtimeState = 'starting';
  else if (registered === false) runtimeState = 'degraded';
  return {
    installed: true,
    service: publicServiceState(state),
    serviceRoot: paths.root,
    registration: registered === true ? 'registered' : registered === false ? 'missing' : 'unknown',
    desiredState: control.desiredState,
    runtimeState,
    supervisor,
    child,
    pid,
    logPath: state.logPath
  };
}

async function bestEffortSignalSnapshot(paths, {
  platform = process.platform,
  kill = process.kill,
  runSync = spawnSync,
  signalTree = signalProcessTree
} = {}) {
  const pid = await readPidSnapshot(paths);
  if (pid?.childPid) signalTree(pid.childPid, 'SIGTERM', { platform, kill, runSync });
  if (pid?.supervisorPid) signalTree(pid.supervisorPid, 'SIGTERM', { platform, kill, runSync });
}

export async function installRemoteHostService({
  configPath = defaultRemoteHostConfigPath(),
  serviceRoot = defaultRemoteHostServiceRoot(),
  nodePath = process.execPath,
  cliPath = defaultRemoteHostCliPath(),
  platform = process.platform,
  runSync = spawnSync,
  kill = process.kill,
  signalTree = signalProcessTree,
  startNow = true,
  force = false,
  maxLogBytes = DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_BYTES,
  maxLogFiles = DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_FILES
} = {}) {
  if (platform !== 'win32') {
    throw codedError('REMOTE_HOST_SERVICE_UNSUPPORTED', 'Remote Host service installation is currently supported on Windows only');
  }
  const paths = servicePaths(serviceRoot);
  const resolvedConfigPath = path.resolve(configPath);
  await readRemoteHostConfig(resolvedConfigPath);
  await Promise.all([fs.access(nodePath), fs.access(cliPath)]);
  const existing = await readServiceState(paths);
  if (existing && !force) {
    throw codedError('REMOTE_HOST_SERVICE_EXISTS', `Remote Host service is already installed: ${paths.statePath}`);
  }
  let desiredState = 'running';
  if (existing) {
    desiredState = (await readControl(paths)).desiredState;
    await writeControl(paths, 'stopped');
    await bestEffortSignalSnapshot(paths, { platform, kill, runSync, signalTree });
    runWindowsTask(['/End', '/TN', existing.taskName], { runSync, allowFailure: true });
  }
  const spec = buildWindowsScheduledTaskSpec({
    configPath: resolvedConfigPath,
    serviceRoot: paths.root,
    nodePath,
    cliPath
  });
  const installedAt = existing?.installedAt || new Date().toISOString();
  const state = {
    schemaVersion: REMOTE_HOST_SERVICE_SCHEMA_VERSION,
    serviceId: spec.serviceId,
    taskName: spec.taskName,
    platform: 'win32',
    configPath: resolvedConfigPath,
    serviceRoot: paths.root,
    installedAt,
    ...(existing ? { repairedAt: new Date().toISOString() } : {}),
    nodePath: path.resolve(nodePath),
    cliPath: path.resolve(cliPath),
    launcherPath: spec.launcherPath,
    logPath: paths.logPath,
    maxLogBytes: normalizePositiveInteger(maxLogBytes, DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_BYTES, 'maxLogBytes'),
    maxLogFiles: normalizePositiveInteger(maxLogFiles, DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_FILES, 'maxLogFiles')
  };
  await fs.mkdir(paths.logDir, { recursive: true });
  await writeLauncher(spec);
  await atomicWriteJson(paths.statePath, state);
  await writeControl(paths, desiredState);
  try {
    runWindowsTask(spec.createArgs, { runSync, code: 'REMOTE_HOST_SERVICE_REGISTER_FAILED' });
  } catch (error) {
    if (!existing) {
      await Promise.all([
        fs.rm(paths.statePath, { force: true }),
        fs.rm(paths.controlPath, { force: true }),
        fs.rm(paths.launcherPath, { force: true })
      ]);
    }
    throw error;
  }
  let started = false;
  if (startNow && desiredState === 'running') {
    runWindowsTask(spec.runArgs, { runSync, code: 'REMOTE_HOST_SERVICE_START_FAILED' });
    started = true;
  }
  return {
    installed: true,
    repaired: Boolean(existing),
    started,
    desiredState,
    service: publicServiceState(state)
  };
}

export async function controlRemoteHostService(action, {
  serviceRoot = defaultRemoteHostServiceRoot(),
  platform = process.platform,
  runSync = spawnSync,
  kill = process.kill,
  signalTree = signalProcessTree
} = {}) {
  const paths = servicePaths(serviceRoot);
  const state = await readServiceState(paths);
  if (!state) throw codedError('REMOTE_HOST_SERVICE_NOT_INSTALLED', `Remote Host service is not installed: ${paths.root}`);
  const mapping = {
    start: 'running',
    resume: 'running',
    pause: 'paused',
    stop: 'stopped'
  };
  const desiredState = mapping[action];
  if (!desiredState) throw codedError('REMOTE_HOST_SERVICE_CONTROL_INVALID', `Unsupported Remote Host service action: ${action}`);
  await writeControl(paths, desiredState);
  const before = await readPidSnapshot(paths);
  const supervisorProbe = before?.supervisorPid ? processProbe(before.supervisorPid, kill) : null;
  let taskRunRequested = false;
  if (desiredState === 'running' && supervisorProbe?.state !== PROCESS_LIFECYCLE_STATE.ALIVE) {
    if (platform !== 'win32') throw codedError('REMOTE_HOST_SERVICE_UNSUPPORTED', 'Starting a registered Remote Host service is currently supported on Windows only');
    runWindowsTask(['/Run', '/TN', state.taskName], { runSync, code: 'REMOTE_HOST_SERVICE_START_FAILED' });
    taskRunRequested = true;
  }
  if (desiredState === 'stopped' && supervisorProbe?.state !== PROCESS_LIFECYCLE_STATE.ALIVE && before?.childPid) {
    signalTree(before.childPid, 'SIGTERM', { platform, kill, runSync });
  }
  return {
    ok: true,
    action,
    desiredState,
    taskRunRequested,
    service: publicServiceState(state)
  };
}

export async function uninstallRemoteHostService({
  serviceRoot = defaultRemoteHostServiceRoot(),
  platform = process.platform,
  runSync = spawnSync,
  kill = process.kill,
  signalTree = signalProcessTree,
  purgeLogs = false
} = {}) {
  const paths = servicePaths(serviceRoot);
  const state = await readServiceState(paths);
  if (!state) {
    return { removed: false, serviceRoot: paths.root, logPath: paths.logPath };
  }
  await writeControl(paths, 'stopped');
  await bestEffortSignalSnapshot(paths, { platform, kill, runSync, signalTree });
  if (platform === 'win32') {
    runWindowsTask(['/End', '/TN', state.taskName], { runSync, allowFailure: true });
    const registered = runWindowsTask(['/Query', '/TN', state.taskName], { runSync, allowFailure: true }).ok;
    if (registered) runWindowsTask(['/Delete', '/TN', state.taskName, '/F'], { runSync, code: 'REMOTE_HOST_SERVICE_UNREGISTER_FAILED' });
  }
  await Promise.all([
    fs.rm(paths.statePath, { force: true }),
    fs.rm(paths.controlPath, { force: true }),
    fs.rm(paths.pidPath, { force: true }),
    fs.rm(paths.lockPath, { force: true }),
    fs.rm(paths.launcherPath, { force: true })
  ]);
  if (purgeLogs) await fs.rm(paths.logDir, { recursive: true, force: true });
  return {
    removed: true,
    serviceRoot: paths.root,
    logsPreserved: !purgeLogs,
    logPath: paths.logPath
  };
}

async function rotateLogIfNeeded(logPath, incomingBytes, maxBytes, maxFiles) {
  let size = 0;
  try {
    size = (await fs.stat(logPath)).size;
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  if (size === 0 || size + incomingBytes <= maxBytes) return;
  await fs.rm(`${logPath}.${maxFiles}`, { force: true });
  for (let index = maxFiles - 1; index >= 1; index -= 1) {
    try {
      await fs.rename(`${logPath}.${index}`, `${logPath}.${index + 1}`);
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
    }
  }
  try {
    await fs.rename(logPath, `${logPath}.1`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}

export async function appendRemoteHostServiceLog(logPath, text, {
  maxBytes = DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_BYTES,
  maxFiles = DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_FILES
} = {}) {
  const resolvedMaxBytes = normalizePositiveInteger(maxBytes, DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_BYTES, 'maxBytes');
  const resolvedMaxFiles = normalizePositiveInteger(maxFiles, DEFAULT_REMOTE_HOST_SERVICE_MAX_LOG_FILES, 'maxFiles');
  const content = String(text ?? '');
  if (!content) return;
  const bytes = Buffer.byteLength(content);
  await fs.mkdir(path.dirname(logPath), { recursive: true });
  await rotateLogIfNeeded(logPath, bytes, resolvedMaxBytes, resolvedMaxFiles);
  await fs.appendFile(logPath, content, { mode: 0o600 });
  await fs.chmod(logPath, 0o600).catch(() => {});
}

function createSerializedLogger(state) {
  let pending = Promise.resolve();
  const write = (source, message) => {
    const text = String(message ?? '');
    if (!text) return pending;
    const line = `${new Date().toISOString()} [${source}] ${text.endsWith('\n') ? text : `${text}\n`}`;
    pending = pending.then(() => appendRemoteHostServiceLog(state.logPath, line, {
      maxBytes: state.maxLogBytes,
      maxFiles: state.maxLogFiles
    }));
    return pending;
  };
  return {
    write,
    flush: () => pending
  };
}

async function acquireSupervisorLock(paths, {
  probe = processProbe,
  kill = process.kill
} = {}) {
  await fs.mkdir(paths.root, { recursive: true });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const handle = await fs.open(paths.lockPath, 'wx', 0o600);
      try {
        await handle.writeFile(`${JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() })}\n`);
      } finally {
        await handle.close();
      }
      return;
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      const lock = await readJsonIfPresent(paths.lockPath).catch(() => null);
      const lockPid = Number(lock?.pid);
      const current = Number.isInteger(lockPid) && lockPid > 0 ? probe(lockPid, kill) : { state: PROCESS_LIFECYCLE_STATE.MISSING };
      if (current?.state === PROCESS_LIFECYCLE_STATE.ALIVE) {
        throw codedError('REMOTE_HOST_SERVICE_ALREADY_RUNNING', `Remote Host supervisor is already running with PID ${lockPid}`);
      }
      await fs.rm(paths.lockPath, { force: true });
    }
  }
  throw codedError('REMOTE_HOST_SERVICE_LOCK_FAILED', `Could not acquire Remote Host supervisor lock: ${paths.lockPath}`);
}

function childExitPromise(child) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    child.once('exit', (code, signal) => finish({ code, signal, error: null }));
    child.once('error', (error) => finish({ code: null, signal: null, error }));
  });
}

async function stopManagedChild(active, {
  platform,
  kill,
  runSync,
  signalTree,
  sleep,
  shutdownGraceMs,
  logger
}) {
  if (!active) return;
  signalTree(active.child.pid, 'SIGTERM', { platform, kill, runSync });
  const graceful = await Promise.race([
    active.exitPromise.then((result) => ({ exited: true, result })),
    sleep(shutdownGraceMs).then(() => ({ exited: false }))
  ]);
  if (!graceful.exited) {
    await logger.write('supervisor', `child pid=${active.child.pid} did not exit within ${shutdownGraceMs}ms; forcing termination`);
    signalTree(active.child.pid, 'SIGKILL', { platform, kill, runSync });
    await Promise.race([active.exitPromise, sleep(Math.min(shutdownGraceMs, 2_000))]);
  }
}

export async function superviseRemoteHostService({
  serviceRoot = defaultRemoteHostServiceRoot(),
  platform = process.platform,
  spawnImpl = spawn,
  runSync = spawnSync,
  kill = process.kill,
  signalTree = signalProcessTree,
  probe = processProbe,
  sleep = delay,
  signal = null,
  pollMs = DEFAULT_POLL_MS,
  restartBaseMs = DEFAULT_RESTART_BASE_MS,
  restartMaxMs = DEFAULT_RESTART_MAX_MS,
  stableResetMs = DEFAULT_STABLE_RESET_MS,
  shutdownGraceMs = DEFAULT_SHUTDOWN_GRACE_MS
} = {}) {
  const paths = servicePaths(serviceRoot);
  const state = await readServiceState(paths);
  if (!state) throw codedError('REMOTE_HOST_SERVICE_NOT_INSTALLED', `Remote Host service is not installed: ${paths.root}`);
  await readRemoteHostConfig(state.configPath);
  await acquireSupervisorLock(paths, { probe, kill });
  const logger = createSerializedLogger(state);
  const supervisorStartedAt = new Date().toISOString();
  let active = null;
  let consecutiveFailures = 0;
  await writePidSnapshot(paths, {
    supervisorPid: process.pid,
    childPid: null,
    startedAt: supervisorStartedAt,
    childStartedAt: null
  });
  await logger.write('supervisor', `started pid=${process.pid} service=${state.serviceId}`);
  let supervisorFailure = null;
  try {
    while (!signal?.aborted) {
      const control = await readControl(paths);
      if (control.desiredState === 'stopped') break;
      if (control.desiredState === 'paused') {
        if (active) {
          await logger.write('supervisor', `pausing child pid=${active.child.pid}`);
          await stopManagedChild(active, { platform, kill, runSync, signalTree, sleep, shutdownGraceMs, logger });
          active = null;
          await writePidSnapshot(paths, {
            supervisorPid: process.pid,
            childPid: null,
            startedAt: supervisorStartedAt,
            childStartedAt: null
          });
        }
        await sleep(pollMs);
        continue;
      }
      if (!active) {
        const childStartedAt = new Date().toISOString();
        try {
          const child = spawnImpl(state.nodePath, [state.cliPath, 'start', '--config', state.configPath], {
            stdio: ['ignore', 'pipe', 'pipe'],
            windowsHide: true,
            detached: platform !== 'win32'
          });
          if (!Number.isInteger(child?.pid) || child.pid <= 0) {
            throw codedError('REMOTE_HOST_SERVICE_CHILD_START_FAILED', 'Remote Host child did not expose a valid PID');
          }
          child.stdout?.on('data', (chunk) => { void logger.write('host:stdout', chunk.toString('utf8')); });
          child.stderr?.on('data', (chunk) => { void logger.write('host:stderr', chunk.toString('utf8')); });
          active = {
            child,
            exitPromise: childExitPromise(child),
            startedAtMs: Date.now(),
            childStartedAt
          };
          await writePidSnapshot(paths, {
            supervisorPid: process.pid,
            childPid: child.pid,
            startedAt: supervisorStartedAt,
            childStartedAt
          });
          await logger.write('supervisor', `child started pid=${child.pid}`);
        } catch (error) {
          consecutiveFailures += 1;
          const backoff = Math.min(restartMaxMs, restartBaseMs * (2 ** Math.min(consecutiveFailures - 1, 5)));
          await logger.write('supervisor', `child start failed: ${error?.code || error?.message || String(error)}; retrying in ${backoff}ms`);
          await sleep(backoff);
          continue;
        }
      }
      const event = await Promise.race([
        active.exitPromise.then((result) => ({ type: 'exit', result })),
        sleep(pollMs).then(() => ({ type: 'tick' }))
      ]);
      if (event.type !== 'exit') continue;
      const runtimeMs = Date.now() - active.startedAtMs;
      const exitedPid = active.child.pid;
      const result = event.result;
      active = null;
      await writePidSnapshot(paths, {
        supervisorPid: process.pid,
        childPid: null,
        startedAt: supervisorStartedAt,
        childStartedAt: null
      });
      await logger.write('supervisor', `child exited pid=${exitedPid} code=${String(result.code)} signal=${String(result.signal)}${result.error ? ` error=${result.error.code || result.error.message}` : ''}`);
      const latestControl = await readControl(paths);
      if (latestControl.desiredState !== 'running' || signal?.aborted) continue;
      consecutiveFailures = runtimeMs >= stableResetMs ? 0 : consecutiveFailures + 1;
      const backoff = Math.min(restartMaxMs, restartBaseMs * (2 ** Math.min(Math.max(consecutiveFailures - 1, 0), 5)));
      await logger.write('supervisor', `restarting after ${backoff}ms consecutiveFailures=${consecutiveFailures}`);
      await sleep(backoff);
    }
  } catch (error) {
    supervisorFailure = error;
    const failure = String(error?.code ? `${error.code}: ${error.message || error}` : error?.message || error)
      .replace(/[\r\n]+/g, ' ')
      .slice(0, 2000);
    await logger.write('supervisor', `failed: ${failure}`).catch(() => {});
    throw error;
  } finally {
    if (active) {
      await stopManagedChild(active, { platform, kill, runSync, signalTree, sleep, shutdownGraceMs, logger }).catch(async (error) => {
        await logger.write('supervisor', `child shutdown failed: ${error?.code || error?.message || String(error)}`);
      });
    }
    await logger.write(
      'supervisor',
      signal?.aborted ? 'stopped by process signal' : supervisorFailure ? 'stopped after failure' : 'stopped by desired state'
    );
    await logger.flush();
    await Promise.all([
      fs.rm(paths.pidPath, { force: true }),
      fs.rm(paths.lockPath, { force: true })
    ]);
  }
  return { stopped: true, serviceId: state.serviceId };
}
