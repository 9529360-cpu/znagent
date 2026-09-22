import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { signalProcessTree } from './process-lifecycle-authority.mjs';

export const BROWSER_VALIDATION_CONTRACT = 'veteran-browser-validation-v1';
export const BROWSER_SESSION_CONTRACT = 'veteran-browser-session-jsonl-v1';

const MAX_COMMAND_PARTS = 64;
const MAX_COMMAND_PART_LENGTH = 4096;
const MAX_ENV_NAMES = 64;
const MAX_ASSERTIONS = 256;
export const MAX_BROWSER_STDOUT_BYTES = 512 * 1024;
export const MAX_BROWSER_STDERR_BYTES = 256 * 1024;
const MAX_TIMEOUT_MS = 10 * 60_000;
const NATIVE_PROVIDER_PATH = fileURLToPath(new URL('./browser-native-provider.mjs', import.meta.url));
const SAFE_ENV_KEYS = [
  'PATH', 'Path', 'PATHEXT', 'SystemRoot', 'WINDIR', 'COMSPEC',
  'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SHELL'
];
const PROTECTED_HOME_ENV = new Set([
  'HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH',
  'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'APPDATA', 'LOCALAPPDATA'
]);

function errorWithCode(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function normalizeRelativeFile(value) {
  const raw = String(value || '').trim().replaceAll('\\', '/');
  if (!raw) throw errorWithCode('Browser scenarioFile must be non-empty', 'BROWSER_SCENARIO_PATH_INVALID');
  if (raw.startsWith('/') || raw.startsWith('//') || /^[A-Za-z]:/.test(raw)) {
    throw errorWithCode('Browser scenarioFile must be relative to the browser cwd', 'BROWSER_SCENARIO_PATH_ESCAPE');
  }
  const normalized = path.posix.normalize(raw.replace(/^\.\//, ''));
  if (!normalized || normalized === '.' || normalized === '..' || normalized.startsWith('../')) {
    throw errorWithCode('Browser scenarioFile must remain inside the browser cwd', 'BROWSER_SCENARIO_PATH_ESCAPE');
  }
  return normalized;
}

function normalizeLoopbackUrl(value, code = 'BROWSER_BASE_URL_NOT_LOCAL') {
  let url;
  try {
    url = new URL(String(value || ''));
  } catch {
    throw errorWithCode('Browser baseUrl must be a valid URL', code);
  }
  if (url.protocol !== 'http:') throw errorWithCode('Browser validation is restricted to loopback HTTP', code);
  if (url.username || url.password || url.search || url.hash) {
    throw errorWithCode('Browser baseUrl may not contain credentials, query, or fragment', code);
  }
  const host = url.hostname.toLowerCase();
  if (!['localhost', '127.0.0.1', '::1', '[::1]'].includes(host)) {
    throw errorWithCode('Browser validation is restricted to loopback hosts', code);
  }
  return url.toString();
}

function normalizeCommand(raw) {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_COMMAND_PARTS) {
    throw errorWithCode('Browser provider command must be a bounded non-empty argv array', 'BROWSER_PROVIDER_COMMAND_INVALID');
  }
  return raw.map((value) => {
    if (typeof value !== 'string' || value.length === 0 || value.length > MAX_COMMAND_PART_LENGTH || value.includes('\u0000')) {
      throw errorWithCode('Browser provider command contains an invalid argv value', 'BROWSER_PROVIDER_COMMAND_INVALID');
    }
    return value;
  });
}

function normalizeNativeBrowserProvider(raw) {
  if (raw === undefined || raw === null || raw === false) return null;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw errorWithCode('Native browser provider configuration must be an object', 'BROWSER_NATIVE_CONFIG_INVALID');
  }
  const executablePath = typeof raw.executablePath === 'string' ? raw.executablePath.trim() : '';
  if (!executablePath || executablePath.length > MAX_COMMAND_PART_LENGTH || executablePath.includes('\u0000') || !path.isAbsolute(executablePath)) {
    throw errorWithCode('Native browser executablePath must be a bounded absolute path', 'BROWSER_NATIVE_EXECUTABLE_PATH_INVALID');
  }
  return Object.freeze({ provider: 'native-chromium', executablePath });
}

function nativeProviderCommand(native, session = false) {
  return [process.execPath, NATIVE_PROVIDER_PATH, ...(session ? ['--session'] : []), '--executable', native.executablePath];
}

function normalizeEnvAllowlist(raw) {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw) || raw.length > MAX_ENV_NAMES) {
    throw errorWithCode('Browser provider envAllowlist must be a bounded array', 'BROWSER_PROVIDER_ENV_INVALID');
  }
  const output = [];
  const seen = new Set();
  for (const value of raw) {
    if (typeof value !== 'string' || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(value)) {
      throw errorWithCode('Browser provider envAllowlist contains an invalid variable name', 'BROWSER_PROVIDER_ENV_INVALID');
    }
    const identity = value.toUpperCase();
    if (PROTECTED_HOME_ENV.has(identity)) {
      throw errorWithCode('Browser provider envAllowlist may not override isolated home/config variables', 'BROWSER_PROVIDER_ENV_INVALID');
    }
    if (!seen.has(identity)) {
      seen.add(identity);
      output.push(value);
    }
  }
  return output;
}

function normalizeTimeout(value, fallback = 120_000) {
  const numeric = Number(value ?? fallback);
  return Number.isFinite(numeric) ? Math.max(1000, Math.min(MAX_TIMEOUT_MS, numeric)) : fallback;
}

function normalizeBrowserSession(raw, browserTimeoutMs, native = null) {
  if (raw === undefined || raw === null || raw === false) return null;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw errorWithCode('Browser session configuration must be an object', 'BROWSER_SESSION_CONFIG_INVALID');
  }
  if (native && raw.command !== undefined) {
    throw errorWithCode('Native browser session may not override its provider command', 'BROWSER_PROVIDER_CONFIG_AMBIGUOUS');
  }
  return {
    contract: BROWSER_SESSION_CONTRACT,
    command: native ? nativeProviderCommand(native, true) : normalizeCommand(raw.command),
    timeoutMs: normalizeTimeout(raw.timeoutMs, browserTimeoutMs)
  };
}

export function normalizeBrowserValidation(raw) {
  if (raw === undefined || raw === null) return null;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw errorWithCode('Browser validation configuration must be an object', 'BROWSER_VALIDATION_CONFIG_INVALID');
  }
  const timeoutMs = normalizeTimeout(raw.timeoutMs);
  const native = normalizeNativeBrowserProvider(raw.native);
  if (native && raw.command !== undefined) {
    throw errorWithCode('Browser validation must choose either native or command provider execution', 'BROWSER_PROVIDER_CONFIG_AMBIGUOUS');
  }
  return {
    contract: BROWSER_VALIDATION_CONTRACT,
    command: native ? nativeProviderCommand(native, false) : normalizeCommand(raw.command),
    cwd: raw.cwd ? String(raw.cwd) : '.',
    timeoutMs,
    envAllowlist: normalizeEnvAllowlist(raw.envAllowlist),
    scenarioFile: normalizeRelativeFile(raw.scenarioFile),
    baseUrl: raw.baseUrl ? normalizeLoopbackUrl(raw.baseUrl) : null,
    session: normalizeBrowserSession(raw.session, timeoutMs, native),
    ...(native ? { native } : {})
  };
}

function insideRoot(root, candidate) {
  const rel = path.relative(root, candidate);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

async function resolveContainedFile(root, relativePath) {
  const realRoot = await fs.realpath(root);
  const absolute = path.resolve(realRoot, ...relativePath.split('/'));
  if (!insideRoot(realRoot, absolute)) {
    throw errorWithCode('Browser scenarioFile escapes the browser cwd', 'BROWSER_SCENARIO_PATH_ESCAPE');
  }
  const info = await fs.lstat(absolute).catch((error) => {
    if (error?.code === 'ENOENT') throw errorWithCode('Browser scenarioFile does not exist', 'BROWSER_SCENARIO_NOT_FOUND');
    throw error;
  });
  if (info.isSymbolicLink()) {
    throw errorWithCode('Browser scenarioFile may not be a symlink', 'BROWSER_SCENARIO_SYMLINK');
  }
  if (!info.isFile()) throw errorWithCode('Browser scenarioFile must be a regular file', 'BROWSER_SCENARIO_INVALID');
  const real = await fs.realpath(absolute);
  if (!insideRoot(realRoot, real)) {
    throw errorWithCode('Browser scenarioFile resolves outside the browser cwd', 'BROWSER_SCENARIO_PATH_ESCAPE');
  }
  return absolute;
}

export async function createBrowserIsolatedEnvironment(allowlist, environment) {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'veteran-browser-home-'));
  try {
    const env = {};
    for (const key of SAFE_ENV_KEYS) {
      if (typeof environment?.[key] === 'string') env[key] = environment[key];
    }
    env.HOME = home;
    env.USERPROFILE = home;
    env.XDG_CONFIG_HOME = path.join(home, '.config');
    env.XDG_CACHE_HOME = path.join(home, '.cache');
    if (process.platform === 'win32') {
      // Chrome needs a resolvable Windows profile even with --user-data-dir.
      // Keep all locations inside the private home, never the caller profile.
      env.APPDATA = path.join(home, 'AppData', 'Roaming');
      env.LOCALAPPDATA = path.join(home, 'AppData', 'Local');
      env.HOMEDRIVE = path.parse(home).root.replace(/[\\/]$/, '');
      env.HOMEPATH = home.slice(env.HOMEDRIVE.length);
      await fs.mkdir(env.APPDATA, { recursive: true });
      await fs.mkdir(env.LOCALAPPDATA, { recursive: true });
    }
    for (const key of allowlist) {
      if (typeof environment?.[key] === 'string') env[key] = environment[key];
    }
    return { env, home };
  } catch (error) {
    await fs.rm(home, { recursive: true, force: true }).catch(() => {});
    throw error;
  }
}

function appendBounded(state, chunk, limit) {
  const text = String(chunk);
  state.bytes += Buffer.byteLength(text);
  if (Buffer.byteLength(state.text) < limit) {
    const remaining = Math.max(0, limit - Buffer.byteLength(state.text));
    if (remaining > 0) state.text += Buffer.from(text).subarray(0, remaining).toString('utf8');
  }
  if (state.bytes > limit) state.truncated = true;
}

export function terminateBrowserProviderTree(child) {
  if (!child?.pid) return;
  signalProcessTree(child.pid, 'SIGKILL');
}

async function runProviderProcess(command, args, { cwd, env, timeoutMs, input }) {
  return new Promise((resolve) => {
    let settled = false;
    let timedOut = false;
    const stdout = { text: '', bytes: 0, truncated: false };
    const stderr = { text: '', bytes: 0, truncated: false };
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
      terminateBrowserProviderTree(child);
    }, timeoutMs);
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => appendBounded(stdout, chunk, MAX_BROWSER_STDOUT_BYTES));
    child.stderr.on('data', (chunk) => appendBounded(stderr, chunk, MAX_BROWSER_STDERR_BYTES));
    child.on('error', (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code: null, signal: null, timedOut, spawnError: error, stdout, stderr });
    });
    child.on('close', (code, signal) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ code, signal, timedOut, spawnError: null, stdout, stderr });
    });
    child.stdin.on('error', () => {});
    child.stdin.end(input);
  });
}

function normalizeProviderFailureCode(raw, passed) {
  if (passed || typeof raw !== 'string') return null;
  const value = raw.trim();
  return /^[A-Z][A-Z0-9_]{0,119}$/.test(value) ? value : null;
}

function normalizeProviderDiagnostics(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const output = {};
  for (const [key, value] of Object.entries(raw).slice(0, 32)) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,79}$/.test(key)) continue;
    if (typeof value === 'boolean') output[key] = value;
    else if (typeof value === 'number' && Number.isFinite(value)) output[key] = value;
    else if (typeof value === 'string') output[key] = value.slice(0, 500);
  }
  return Object.keys(output).length ? output : null;
}

function normalizeAssertion(raw, index) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw errorWithCode(`Browser assertion ${index + 1} must be an object`, 'BROWSER_PROVIDER_RESULT_INVALID');
  }
  const name = typeof raw.name === 'string' ? raw.name.trim() : '';
  if (!name || name.length > 240 || typeof raw.passed !== 'boolean') {
    throw errorWithCode(`Browser assertion ${index + 1} is invalid`, 'BROWSER_PROVIDER_RESULT_INVALID');
  }
  const assertion = { name, passed: raw.passed };
  if (raw.detail !== undefined && raw.detail !== null) assertion.detail = String(raw.detail).slice(0, 1200);
  return assertion;
}

export function normalizeBrowserProviderResult(raw, baseUrl) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw.contract !== BROWSER_VALIDATION_CONTRACT || typeof raw.passed !== 'boolean') {
    throw errorWithCode('Browser provider returned an invalid result contract', 'BROWSER_PROVIDER_RESULT_INVALID');
  }
  if (raw.assertions !== undefined && !Array.isArray(raw.assertions)) {
    throw errorWithCode('Browser provider assertions must be an array', 'BROWSER_PROVIDER_RESULT_INVALID');
  }
  const assertionsRaw = raw.assertions || [];
  if (assertionsRaw.length > MAX_ASSERTIONS) {
    throw errorWithCode(`Browser provider may return at most ${MAX_ASSERTIONS} assertions`, 'BROWSER_PROVIDER_RESULT_INVALID');
  }
  const assertions = assertionsRaw.map(normalizeAssertion);
  if (raw.passed && assertions.some((item) => !item.passed)) {
    throw errorWithCode('Browser provider cannot report passed=true with failed assertions', 'BROWSER_PROVIDER_RESULT_INVALID');
  }
  let currentUrl = null;
  if (raw.currentUrl !== undefined && raw.currentUrl !== null) {
    currentUrl = normalizeLoopbackUrl(raw.currentUrl, 'BROWSER_PROVIDER_CURRENT_URL_INVALID');
    if (new URL(currentUrl).origin !== new URL(baseUrl).origin) {
      throw errorWithCode('Browser provider currentUrl must remain on the validation base origin', 'BROWSER_PROVIDER_CURRENT_URL_INVALID');
    }
  }
  return {
    contract: BROWSER_VALIDATION_CONTRACT,
    passed: raw.passed,
    summary: raw.summary === undefined || raw.summary === null ? '' : String(raw.summary).slice(0, 2000),
    assertions,
    currentUrl,
    failureCode: normalizeProviderFailureCode(raw.failureCode, raw.passed),
    providerDiagnostics: normalizeProviderDiagnostics(raw.diagnostics)
  };
}

export async function prepareBrowserValidationRequest(browser, { cwd, serviceReadinessUrl = null } = {}) {
  await resolveContainedFile(cwd, browser.scenarioFile);
  const baseUrl = browser.baseUrl || (serviceReadinessUrl ? `${new URL(serviceReadinessUrl).origin}/` : null);
  if (!baseUrl) throw errorWithCode('Browser validation requires browser.baseUrl or service readiness URL', 'BROWSER_BASE_URL_REQUIRED');
  const normalizedBaseUrl = normalizeLoopbackUrl(baseUrl);
  return {
    normalizedBaseUrl,
    payload: {
      contract: BROWSER_VALIDATION_CONTRACT,
      baseUrl: normalizedBaseUrl,
      scenario: { path: browser.scenarioFile },
      artifactsManagedByValidation: true
    }
  };
}

export async function runBrowserValidation(browser, { cwd, serviceReadinessUrl = null, environment = process.env } = {}) {
  const request = await prepareBrowserValidationRequest(browser, { cwd, serviceReadinessUrl });
  const payload = `${JSON.stringify(request.payload)}\n`;
  const [command, ...args] = browser.command;
  const { env, home } = await createBrowserIsolatedEnvironment(browser.envAllowlist, environment);
  let processResult;
  try {
    processResult = await runProviderProcess(command, args, {
      cwd,
      env,
      timeoutMs: browser.timeoutMs,
      input: payload
    });
  } finally {
    await fs.rm(home, { recursive: true, force: true }).catch(() => {});
  }
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
    return { passed: false, failureCode: 'BROWSER_PROVIDER_SPAWN_FAILED', summary: 'Browser provider could not be started.', assertions: [], currentUrl: null, diagnostics };
  }
  if (processResult.timedOut) {
    return { passed: false, failureCode: 'BROWSER_PROVIDER_TIMEOUT', summary: 'Browser provider exceeded its timeout.', assertions: [], currentUrl: null, diagnostics };
  }
  if (processResult.stdout.truncated) {
    return { passed: false, failureCode: 'BROWSER_PROVIDER_OUTPUT_LIMIT', summary: 'Browser provider stdout exceeded the bounded protocol limit.', assertions: [], currentUrl: null, diagnostics };
  }
  if (processResult.code !== 0) {
    return { passed: false, failureCode: 'BROWSER_PROVIDER_FAILED', summary: 'Browser provider process exited unsuccessfully.', assertions: [], currentUrl: null, diagnostics };
  }
  let parsed;
  try {
    parsed = JSON.parse(processResult.stdout.text.trim());
  } catch {
    return { passed: false, failureCode: 'BROWSER_PROVIDER_RESULT_INVALID', summary: 'Browser provider stdout was not one valid JSON result object.', assertions: [], currentUrl: null, diagnostics };
  }
  try {
    const normalized = normalizeBrowserProviderResult(parsed, request.normalizedBaseUrl);
    return { ...normalized, failureCode: normalized.passed ? null : (normalized.failureCode || 'BROWSER_ASSERTION_FAILED'), diagnostics };
  } catch (error) {
    return { passed: false, failureCode: error?.code || 'BROWSER_PROVIDER_RESULT_INVALID', summary: String(error?.message || error).slice(0, 1000), assertions: [], currentUrl: null, diagnostics };
  }
}
