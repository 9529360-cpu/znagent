import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { changedPaths, git } from './git.mjs';
import { sha256, stableStringify } from './util.mjs';
import { CredentialBroker, normalizeCredentialReferences } from './credential-broker.mjs';
import { signalProcessTree } from './process-lifecycle-authority.mjs';

export const PROJECT_BOOTSTRAP_EXECUTION_CONTRACT = 'veteran-project-bootstrap-execution-v1';
export const BOOTSTRAP_AUTHORIZATION_CONTRACT = 'veteran-bootstrap-authorization-v1';
const PLAN_CONTRACT = 'veteran-project-bootstrap-plan-v1';
const MAX_ENV_NAMES = 64;
const MAX_COMMAND_PARTS = 64;
const MAX_COMMAND_PART_LENGTH = 4096;
const MAX_OUTPUT_BYTES = 512 * 1024;
const MAX_STEP_TIMEOUT_MS = 10 * 60_000;
const DEFAULT_STEP_TIMEOUT_MS = 5 * 60_000;
const FORBIDDEN_ALLOWLIST_ENV = new Set(['HOME', 'USERPROFILE', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'GIT_TERMINAL_PROMPT']);
const SAFE_ENV_KEYS = [
  'PATHEXT', 'SystemRoot', 'WINDIR', 'COMSPEC',
  'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SHELL'
];

function codedError(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function normalizeEnvAllowlist(raw) {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw) || raw.length > MAX_ENV_NAMES) {
    throw codedError('bootstrapAuthorization.envAllowlist must be a bounded array', 'BOOTSTRAP_AUTHORIZATION_INVALID');
  }
  const seen = new Set();
  const output = [];
  for (const value of raw) {
    if (typeof value !== 'string' || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(value) || FORBIDDEN_ALLOWLIST_ENV.has(value)) {
      throw codedError('bootstrapAuthorization.envAllowlist contains an invalid or protected environment variable name', 'BOOTSTRAP_AUTHORIZATION_INVALID');
    }
    if (!seen.has(value)) {
      seen.add(value);
      output.push(value);
    }
  }
  return output;
}

export function normalizeBootstrapAuthorization(raw) {
  if (raw === undefined || raw === null || raw === false) return null;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw codedError('bootstrapAuthorization must be an object', 'BOOTSTRAP_AUTHORIZATION_INVALID');
  }
  const execute = raw.execute === true;
  if (!execute) {
    if (raw.execute !== false && raw.execute !== undefined) {
      throw codedError('bootstrapAuthorization.execute must be a boolean', 'BOOTSTRAP_AUTHORIZATION_INVALID');
    }
    return null;
  }
  if (raw.allowNetwork !== undefined && typeof raw.allowNetwork !== 'boolean') {
    throw codedError('bootstrapAuthorization.allowNetwork must be a boolean', 'BOOTSTRAP_AUTHORIZATION_INVALID');
  }
  if (raw.allowThirdPartyCode !== undefined && typeof raw.allowThirdPartyCode !== 'boolean') {
    throw codedError('bootstrapAuthorization.allowThirdPartyCode must be a boolean', 'BOOTSTRAP_AUTHORIZATION_INVALID');
  }
  if (raw.contract === BOOTSTRAP_AUTHORIZATION_CONTRACT) {
    return {
      contract: BOOTSTRAP_AUTHORIZATION_CONTRACT,
      execute: true,
      allowNetwork: raw.allowNetwork === true,
      allowThirdPartyCode: raw.allowThirdPartyCode === true,
      credentialRefs: normalizeCredentialReferences(raw.credentialRefs)
    };
  }
  const legacyEnvironmentNames = normalizeEnvAllowlist(raw.envAllowlist);
  return {
    contract: BOOTSTRAP_AUTHORIZATION_CONTRACT,
    execute: true,
    allowNetwork: raw.allowNetwork === true,
    allowThirdPartyCode: raw.allowThirdPartyCode === true,
    credentialRefs: normalizeCredentialReferences(raw.credentialRefs, { legacyEnvironmentNames })
  };
}

function normalizeCommand(raw, stepId) {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_COMMAND_PARTS) {
    throw codedError(`Bootstrap step ${stepId} has an invalid command`, 'BOOTSTRAP_PLAN_INVALID', { stepId });
  }
  return raw.map((value) => {
    if (typeof value !== 'string' || value.length === 0 || value.length > MAX_COMMAND_PART_LENGTH || value.includes('\0')) {
      throw codedError(`Bootstrap step ${stepId} contains an invalid argv value`, 'BOOTSTRAP_PLAN_INVALID', { stepId });
    }
    return value;
  });
}

function validatePlan(plan, authorization) {
  if (!plan || typeof plan !== 'object' || Array.isArray(plan) || plan.contract !== PLAN_CONTRACT || !Array.isArray(plan.steps)) {
    throw codedError('Project bootstrap plan is missing or invalid', 'BOOTSTRAP_PLAN_INVALID');
  }
  if (plan.status === 'blocked') {
    throw codedError('Project bootstrap plan is blocked by host/environment requirements', 'BOOTSTRAP_PLAN_BLOCKED', {
      issues: Array.isArray(plan.issues) ? plan.issues.map((item) => item?.code).filter(Boolean).slice(0, 32) : []
    });
  }
  if (plan.status === 'manual') {
    throw codedError('Project bootstrap plan requires manual preparation and cannot be executed automatically', 'BOOTSTRAP_MANUAL_REQUIRED', {
      steps: plan.steps.map((step) => step?.id).filter(Boolean).slice(0, 32),
      issues: Array.isArray(plan.issues) ? plan.issues.map((item) => item?.code).filter(Boolean).slice(0, 32) : []
    });
  }
  if (plan.status === 'not-needed' || plan.steps.length === 0) return [];
  if (plan.status !== 'planned') {
    throw codedError(`Unsupported bootstrap plan status: ${String(plan.status)}`, 'BOOTSTRAP_PLAN_INVALID');
  }
  const seen = new Set();
  return plan.steps.map((step, index) => {
    if (!step || typeof step !== 'object' || Array.isArray(step)) throw codedError(`Bootstrap step ${index + 1} is invalid`, 'BOOTSTRAP_PLAN_INVALID');
    const id = typeof step.id === 'string' ? step.id.trim() : '';
    if (!id || id.length > 160 || seen.has(id)) throw codedError(`Bootstrap step ${index + 1} has an invalid/duplicate id`, 'BOOTSTRAP_PLAN_INVALID');
    seen.add(id);
    if (step.executionPolicy !== 'approval-required' || step.requiresAuthorization !== true || step.reproducible !== true) {
      throw codedError(`Bootstrap step ${id} is not eligible for automatic execution`, 'BOOTSTRAP_MANUAL_REQUIRED', { stepId: id, executionPolicy: step.executionPolicy || null });
    }
    if (step.network === true && !authorization.allowNetwork) {
      throw codedError(`Bootstrap step ${id} requires network authorization`, 'BOOTSTRAP_NETWORK_AUTHORIZATION_REQUIRED', { stepId: id });
    }
    if (step.executesThirdPartyCode === true && !authorization.allowThirdPartyCode) {
      throw codedError(`Bootstrap step ${id} may execute third-party code and requires explicit authorization`, 'BOOTSTRAP_THIRD_PARTY_CODE_AUTHORIZATION_REQUIRED', { stepId: id });
    }
    const cwd = step.cwd === undefined || step.cwd === null ? '.' : String(step.cwd);
    if (cwd !== '.') throw codedError(`Bootstrap step ${id} uses an unsupported cwd`, 'BOOTSTRAP_PLAN_INVALID', { stepId: id });
    return {
      id,
      command: normalizeCommand(step.command, id),
      network: step.network === true,
      executesThirdPartyCode: step.executesThirdPartyCode === true
    };
  });
}

function appendBounded(state, chunk) {
  const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
  state.bytes += buffer.length;
  const remaining = MAX_OUTPUT_BYTES - state.capturedBytes;
  if (remaining > 0) {
    const slice = buffer.subarray(0, Math.max(0, remaining));
    state.capturedBytes += slice.length;
  }
  if (state.bytes > MAX_OUTPUT_BYTES) state.truncated = true;
}

function terminateTree(child) {
  if (!child?.pid) return;
  signalProcessTree(child.pid, 'SIGKILL');
}

function runStep(command, args, { cwd, env, timeoutMs }) {
  return new Promise((resolve) => {
    const stdout = { bytes: 0, capturedBytes: 0, truncated: false };
    const stderr = { bytes: 0, capturedBytes: 0, truncated: false };
    let settled = false;
    let timedOut = false;
    const started = Date.now();
    const child = spawn(command, args, {
      cwd,
      env,
      shell: false,
      detached: process.platform !== 'win32',
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    });
    const timer = setTimeout(() => {
      timedOut = true;
      terminateTree(child);
    }, timeoutMs);
    child.stdout.on('data', (chunk) => appendBounded(stdout, chunk));
    child.stderr.on('data', (chunk) => appendBounded(stderr, chunk));
    child.once('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: null, signal: null, timedOut, spawnError: error, durationMs: Date.now() - started, stdout, stderr });
    });
    child.once('close', (code, signal) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code, signal, timedOut, spawnError: null, durationMs: Date.now() - started, stdout, stderr });
    });
  });
}

function pathWithin(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative));
}

async function isolatedExecutablePath(worktreePath, environment) {
  const rawPath = typeof environment?.PATH === 'string'
    ? environment.PATH
    : (typeof environment?.Path === 'string' ? environment.Path : '');
  const worktreeResolved = path.resolve(worktreePath);
  const worktreeReal = await fs.realpath(worktreeResolved).catch(() => worktreeResolved);
  const entries = [];
  const seen = new Set();
  for (const rawEntry of rawPath.split(path.delimiter)) {
    const entry = rawEntry.trim();
    if (!entry || !path.isAbsolute(entry)) continue;
    const resolved = path.resolve(entry);
    const real = await fs.realpath(resolved).catch(() => resolved);
    if (pathWithin(worktreeReal, real)) continue;
    const identity = process.platform === 'win32' ? real.toLowerCase() : real;
    if (seen.has(identity)) continue;
    seen.add(identity);
    entries.push(resolved);
  }
  if (!entries.length) {
    throw codedError('Bootstrap execution host PATH contains no safe absolute executable directories', 'BOOTSTRAP_HOST_PATH_UNSAFE');
  }
  return entries.join(path.delimiter);
}

async function isolatedEnvironment(credentialBroker, credentialRefs, worktreePath, environment) {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'veteran-bootstrap-home-'));
  try {
    const env = {};
    for (const key of SAFE_ENV_KEYS) if (typeof environment?.[key] === 'string') env[key] = environment[key];
    env.PATH = await isolatedExecutablePath(worktreePath, environment);
    env.HOME = home;
    env.USERPROFILE = home;
    env.XDG_CONFIG_HOME = path.join(home, '.config');
    env.XDG_CACHE_HOME = path.join(home, '.cache');
    env.GIT_TERMINAL_PROMPT = '0';
    const materialized = await credentialBroker.materialize(credentialRefs || []);
    Object.assign(env, materialized.env);
    return { env, home, credentialTargets: materialized.targets };
  } catch (error) {
    await fs.rm(home, { recursive: true, force: true }).catch(() => {});
    throw error;
  }
}

function stepDiagnostic(step, result) {
  return {
    id: step.id,
    exitCode: result.code,
    signal: result.signal,
    timedOut: result.timedOut,
    durationMs: result.durationMs,
    stdoutBytes: result.stdout.bytes,
    stderrBytes: result.stderr.bytes,
    stdoutTruncated: result.stdout.truncated,
    stderrTruncated: result.stderr.truncated
  };
}

export class ProjectBootstrapExecutor {
  constructor({ stepTimeoutMs = DEFAULT_STEP_TIMEOUT_MS, credentialBroker = null, environment = process.env } = {}) {
    this.credentialBroker = credentialBroker || new CredentialBroker();
    this.environment = environment;
    this.stepTimeoutMs = Math.max(1000, Math.min(MAX_STEP_TIMEOUT_MS, Number(stepTimeoutMs) || DEFAULT_STEP_TIMEOUT_MS));
  }

  async prepare({ worktreePath, plan, authorization }) {
    const normalizedAuthorization = normalizeBootstrapAuthorization(authorization);
    if (!normalizedAuthorization) throw codedError('Bootstrap execution requires explicit authorization', 'BOOTSTRAP_AUTHORIZATION_REQUIRED');
    const steps = validatePlan(plan, normalizedAuthorization);
    const baseHead = (await git(worktreePath, ['rev-parse', 'HEAD'])).stdout.trim();
    const beforePaths = await changedPaths(worktreePath, baseHead);
    if (beforePaths.length) throw codedError('Bootstrap worktree must be clean before environment preparation', 'BOOTSTRAP_WORKTREE_DIRTY', { changedPaths: beforePaths.slice(0, 100) });
    const planHash = sha256(stableStringify(plan));
    if (steps.length === 0) {
      return { contract: PROJECT_BOOTSTRAP_EXECUTION_CONTRACT, status: 'not-needed', planHash, sourceHead: baseHead, steps: [] };
    }

    const { env, home, credentialTargets } = await isolatedEnvironment(this.credentialBroker, normalizedAuthorization.credentialRefs, worktreePath, this.environment);
    const results = [];
    try {
      for (const step of steps) {
        const [command, ...args] = step.command;
        const result = await runStep(command, args, { cwd: worktreePath, env, timeoutMs: this.stepTimeoutMs });
        const diagnostic = stepDiagnostic(step, result);
        results.push(diagnostic);
        if (result.spawnError) {
          throw codedError(`Bootstrap step ${step.id} could not be started`, 'BOOTSTRAP_STEP_SPAWN_FAILED', { ...diagnostic, spawnCode: result.spawnError.code || null });
        }
        if (result.timedOut) throw codedError(`Bootstrap step ${step.id} timed out`, 'BOOTSTRAP_STEP_TIMEOUT', diagnostic);
        if (result.code !== 0) throw codedError(`Bootstrap step ${step.id} failed`, 'BOOTSTRAP_STEP_FAILED', diagnostic);
        const head = (await git(worktreePath, ['rev-parse', 'HEAD'])).stdout.trim();
        if (head !== baseHead) throw codedError(`Bootstrap step ${step.id} changed task HEAD`, 'BOOTSTRAP_HEAD_OWNERSHIP_VIOLATION', { stepId: step.id, expectedHead: baseHead, actualHead: head });
        const paths = await changedPaths(worktreePath, baseHead);
        if (paths.length) throw codedError(`Bootstrap step ${step.id} mutated repository-visible files`, 'BOOTSTRAP_WORKTREE_MUTATION', { stepId: step.id, changedPaths: paths.slice(0, 100) });
      }
      return {
        contract: PROJECT_BOOTSTRAP_EXECUTION_CONTRACT,
        status: 'completed',
        planHash,
        sourceHead: baseHead,
        steps: results
      };
    } finally {
      for (const target of credentialTargets) delete env[target];
      await fs.rm(home, { recursive: true, force: true }).catch(() => {});
    }
  }
}
