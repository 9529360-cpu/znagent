import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { CredentialBroker, normalizeCredentialReferences } from './credential-broker.mjs';
import { signalProcessTree } from './process-lifecycle-authority.mjs';

export const OBSERVABILITY_VALIDATION_CONTRACT = 'veteran-observability-validation-v1';

const MAX_COMMAND_PARTS = 64;
const MAX_COMMAND_PART_LENGTH = 4096;
const MAX_CHECKS = 256;
const MAX_STDOUT_BYTES = 512 * 1024;
const MAX_STDERR_BYTES = 256 * 1024;
const MAX_TIMEOUT_MS = 10 * 60_000;
const MAX_WINDOW_SECONDS = 7 * 24 * 60 * 60;
const SAFE_ENV_KEYS = [
  'PATH', 'Path', 'PATHEXT', 'SystemRoot', 'WINDIR', 'COMSPEC',
  'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SHELL'
];

function codedError(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function normalizeCommand(raw) {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_COMMAND_PARTS) {
    throw codedError('Observability provider command must be a bounded non-empty argv array', 'OBSERVABILITY_PROVIDER_COMMAND_INVALID');
  }
  return raw.map((value) => {
    if (typeof value !== 'string' || value.length === 0 || value.length > MAX_COMMAND_PART_LENGTH || value.includes('\0')) {
      throw codedError('Observability provider command contains an invalid argv value', 'OBSERVABILITY_PROVIDER_COMMAND_INVALID');
    }
    return value;
  });
}

export function normalizeObservabilityValidation(raw) {
  if (raw === undefined || raw === null) return null;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw codedError('Observability validation configuration must be an object', 'OBSERVABILITY_CONFIG_INVALID');
  }
  const target = typeof raw.target === 'string' ? raw.target.trim() : '';
  if (!target || target.length > 160 || target.includes('\0')) {
    throw codedError('Observability target must be a bounded non-empty string', 'OBSERVABILITY_TARGET_INVALID');
  }
  const windowSeconds = Number(raw.windowSeconds ?? 300);
  if (!Number.isFinite(windowSeconds) || windowSeconds < 30 || windowSeconds > MAX_WINDOW_SECONDS) {
    throw codedError('Observability windowSeconds is outside the supported range', 'OBSERVABILITY_WINDOW_INVALID');
  }
  const timeoutMs = Number(raw.timeoutMs ?? 120_000);
  return {
    contract: OBSERVABILITY_VALIDATION_CONTRACT,
    command: normalizeCommand(raw.command),
    cwd: raw.cwd ? String(raw.cwd) : '.',
    target,
    windowSeconds: Math.floor(windowSeconds),
    timeoutMs: Number.isFinite(timeoutMs) ? Math.max(1000, Math.min(MAX_TIMEOUT_MS, timeoutMs)) : 120_000,
    requireSourceMatch: raw.requireSourceMatch !== false,
    credentialRefs: normalizeCredentialReferences(raw.credentialRefs)
  };
}

function appendBounded(state, chunk, limit) {
  const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
  state.bytes += buffer.length;
  const remaining = limit - state.capturedBytes;
  if (remaining > 0) {
    const slice = buffer.subarray(0, Math.max(0, remaining));
    state.buffers.push(slice);
    state.capturedBytes += slice.length;
  }
  if (state.bytes > limit) state.truncated = true;
}

function capturedText(state) {
  return Buffer.concat(state.buffers).toString('utf8');
}

function terminateTree(child) {
  if (!child?.pid) return;
  signalProcessTree(child.pid, 'SIGKILL');
}

function runProvider(command, args, { cwd, env, timeoutMs, input }) {
  return new Promise((resolve) => {
    const stdout = { bytes: 0, capturedBytes: 0, truncated: false, buffers: [] };
    const stderr = { bytes: 0, capturedBytes: 0, truncated: false, buffers: [] };
    let settled = false;
    let timedOut = false;
    const child = spawn(command, args, {
      cwd,
      env,
      shell: false,
      detached: process.platform !== 'win32',
      windowsHide: true,
      stdio: ['pipe', 'pipe', 'pipe']
    });
    const timer = setTimeout(() => {
      timedOut = true;
      terminateTree(child);
    }, timeoutMs);
    child.stdout.on('data', (chunk) => appendBounded(stdout, chunk, MAX_STDOUT_BYTES));
    child.stderr.on('data', (chunk) => appendBounded(stderr, chunk, MAX_STDERR_BYTES));
    child.once('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: null, signal: null, timedOut, spawnError: error, stdout, stderr });
    });
    child.once('close', (code, signal) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code, signal, timedOut, spawnError: null, stdout, stderr });
    });
    child.stdin.on('error', () => {});
    child.stdin.end(input);
  });
}

function redactText(value, secrets, limit) {
  let text = String(value);
  for (const secret of secrets) {
    if (typeof secret === 'string' && secret.length > 0) text = text.split(secret).join('[REDACTED]');
  }
  return text.slice(0, limit);
}

function normalizeScalar(value, secrets, limit = 240) {
  if (value === undefined || value === null) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'boolean') return value;
  return redactText(value, secrets, limit);
}

function normalizeCheck(raw, index, secrets) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw codedError(`Observability check ${index + 1} must be an object`, 'OBSERVABILITY_PROVIDER_RESULT_INVALID');
  }
  const rawName = typeof raw.name === 'string' ? raw.name.trim() : '';
  if (!rawName || rawName.length > 240 || typeof raw.passed !== 'boolean') {
    throw codedError(`Observability check ${index + 1} is invalid`, 'OBSERVABILITY_PROVIDER_RESULT_INVALID');
  }
  return {
    name: redactText(rawName, secrets, 240),
    passed: raw.passed,
    signal: raw.signal === undefined || raw.signal === null ? null : redactText(raw.signal, secrets, 80),
    observed: normalizeScalar(raw.observed, secrets),
    threshold: normalizeScalar(raw.threshold, secrets),
    detail: raw.detail === undefined || raw.detail === null ? null : redactText(raw.detail, secrets, 1200)
  };
}

function normalizeProviderResult(raw, { expectedSourceHead, requireSourceMatch, secrets = [] }) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw.contract !== OBSERVABILITY_VALIDATION_CONTRACT || typeof raw.passed !== 'boolean') {
    throw codedError('Observability provider returned an invalid result contract', 'OBSERVABILITY_PROVIDER_RESULT_INVALID');
  }
  if (raw.checks !== undefined && !Array.isArray(raw.checks)) {
    throw codedError('Observability provider checks must be an array', 'OBSERVABILITY_PROVIDER_RESULT_INVALID');
  }
  const checksRaw = raw.checks || [];
  if (checksRaw.length > MAX_CHECKS) {
    throw codedError(`Observability provider may return at most ${MAX_CHECKS} checks`, 'OBSERVABILITY_PROVIDER_RESULT_INVALID');
  }
  const checks = checksRaw.map((item, index) => normalizeCheck(item, index, secrets));
  if (raw.passed && checks.some((item) => !item.passed)) {
    throw codedError('Observability provider cannot report passed=true with failed checks', 'OBSERVABILITY_PROVIDER_RESULT_INVALID');
  }
  const rawObservedSourceHead = typeof raw.observedSourceHead === 'string' ? raw.observedSourceHead.trim() : '';
  const observedSourceHead = rawObservedSourceHead ? redactText(rawObservedSourceHead, secrets, 240) : null;
  if (requireSourceMatch) {
    if (!rawObservedSourceHead || rawObservedSourceHead !== expectedSourceHead) {
      return {
        contract: OBSERVABILITY_VALIDATION_CONTRACT,
        passed: false,
        failureCode: 'OBSERVABILITY_SOURCE_IDENTITY_MISMATCH',
        summary: 'Observed deployment/source identity does not match the validation source identity.',
        observedSourceHead,
        checks
      };
    }
  }
  return {
    contract: OBSERVABILITY_VALIDATION_CONTRACT,
    passed: raw.passed,
    failureCode: raw.passed ? null : 'OBSERVABILITY_CHECK_FAILED',
    summary: raw.summary === undefined || raw.summary === null ? '' : redactText(raw.summary, secrets, 2000),
    observedSourceHead,
    checks
  };
}

async function isolatedEnvironment(credentialBroker, credentialRefs) {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'veteran-observability-home-'));
  try {
    const env = {};
    for (const key of SAFE_ENV_KEYS) if (typeof process.env[key] === 'string') env[key] = process.env[key];
    env.HOME = home;
    env.USERPROFILE = home;
    env.XDG_CONFIG_HOME = path.join(home, '.config');
    env.XDG_CACHE_HOME = path.join(home, '.cache');
    env.GIT_TERMINAL_PROMPT = '0';
    const materialized = await credentialBroker.materialize(credentialRefs || []);
    Object.assign(env, materialized.env);
    return { env, home, credentialTargets: materialized.targets, credentialSecrets: materialized.targets.map((target) => env[target]) };
  } catch (error) {
    await fs.rm(home, { recursive: true, force: true }).catch(() => {});
    throw error;
  }
}

export async function runObservabilityValidation(observability, { cwd, expectedSourceHead, credentialBroker = null } = {}) {
  const broker = credentialBroker || new CredentialBroker();
  const { env, home, credentialTargets, credentialSecrets } = await isolatedEnvironment(broker, observability.credentialRefs);
  const payload = `${JSON.stringify({
    contract: OBSERVABILITY_VALIDATION_CONTRACT,
    mode: 'read-only-verification',
    target: observability.target,
    windowSeconds: observability.windowSeconds,
    expectedSourceHead
  })}\n`;
  const [command, ...args] = observability.command;
  try {
    const processResult = await runProvider(command, args, { cwd, env, timeoutMs: observability.timeoutMs, input: payload });
    const diagnostics = {
      exitCode: processResult.code,
      signal: processResult.signal,
      timedOut: processResult.timedOut,
      stdoutBytes: processResult.stdout.bytes,
      stderrBytes: processResult.stderr.bytes,
      stdoutTruncated: processResult.stdout.truncated,
      stderrTruncated: processResult.stderr.truncated
    };
    if (processResult.spawnError) {
      return { passed: false, failureCode: 'OBSERVABILITY_PROVIDER_SPAWN_FAILED', summary: 'Observability provider could not be started.', observedSourceHead: null, checks: [], diagnostics };
    }
    if (processResult.timedOut) {
      return { passed: false, failureCode: 'OBSERVABILITY_PROVIDER_TIMEOUT', summary: 'Observability provider exceeded its timeout.', observedSourceHead: null, checks: [], diagnostics };
    }
    if (processResult.stdout.truncated) {
      return { passed: false, failureCode: 'OBSERVABILITY_PROVIDER_OUTPUT_LIMIT', summary: 'Observability provider stdout exceeded the bounded protocol limit.', observedSourceHead: null, checks: [], diagnostics };
    }
    if (processResult.code !== 0) {
      return { passed: false, failureCode: 'OBSERVABILITY_PROVIDER_FAILED', summary: 'Observability provider exited unsuccessfully.', observedSourceHead: null, checks: [], diagnostics };
    }
    let parsed;
    try {
      parsed = JSON.parse(capturedText(processResult.stdout).trim());
    } catch {
      return { passed: false, failureCode: 'OBSERVABILITY_PROVIDER_RESULT_INVALID', summary: 'Observability provider stdout was not one valid JSON result object.', observedSourceHead: null, checks: [], diagnostics };
    }
    try {
      const normalized = normalizeProviderResult(parsed, { expectedSourceHead, requireSourceMatch: observability.requireSourceMatch, secrets: credentialSecrets });
      return { ...normalized, diagnostics };
    } catch (error) {
      return { passed: false, failureCode: error?.code || 'OBSERVABILITY_PROVIDER_RESULT_INVALID', summary: String(error?.message || error).slice(0, 1000), observedSourceHead: null, checks: [], diagnostics };
    }
  } finally {
    for (const target of credentialTargets) delete env[target];
    await fs.rm(home, { recursive: true, force: true }).catch(() => {});
  }
}
