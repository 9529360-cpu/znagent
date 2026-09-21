import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import visualRegression from './electron-visual-regression.cjs';

const { normalizeVisualCompareRequest } = visualRegression;

export const ELECTRON_VALIDATION_CONTRACT = 'veteran-electron-validation-v1';
export const ELECTRON_SCENARIO_CONTRACT = 'veteran-electron-scenario-v1';
export const MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024;
export const MAX_SCREENSHOT_TOTAL_BYTES = 48 * 1024 * 1024;
export const MAX_SURFACES = 64;

const MAX_ARGS = 64;
const MAX_ARG_LENGTH = 4096;
const MAX_ENV_NAMES = 64;
const MAX_SCENARIO_BYTES = 256 * 1024;
const MAX_STEPS = 256;
const MAX_SCREENSHOTS = 32;
const MAX_TIMEOUT_MS = 10 * 60_000;
const MAX_WINDOW_DIMENSION = 32_768;
const DEFAULT_TIMEOUT_MS = 120_000;
const DEFAULT_STEP_TIMEOUT_MS = 10_000;
const ACTIONS = new Set(['waitForSurface', 'assertSurfaceCount', 'assertWindowState', 'assertMenuItem', 'assertVisual', 'click', 'fill', 'press', 'assertVisible', 'assertText', 'assertValue', 'assertUrl', 'screenshot']);
const TARGET_TYPES = new Set(['window', 'webview']);
const MATCH_MODES = new Set(['equals', 'contains']);
const WINDOW_STATE_FIELDS = new Set(['visible', 'minimized', 'maximized', 'fullScreen', 'bounds']);
const WINDOW_BOUND_FIELDS = new Set(['width', 'height']);
const MENU_ITEM_FIELDS = new Set(['id', 'label', 'role', 'type', 'accelerator', 'enabled', 'visible', 'checked']);
const MENU_ITEM_IDENTITY_FIELDS = new Set(['id', 'label', 'role', 'accelerator']);
const SAFE_ENV_KEYS = [
  'PATH', 'Path', 'PATHEXT', 'SystemRoot', 'WINDIR', 'COMSPEC',
  'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'LC_CTYPE', 'SHELL',
  'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XAUTHORITY'
];
const PROTECTED_HOME_ENV = new Set(['HOME', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME', 'APPDATA', 'LOCALAPPDATA']);

export function electronError(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function boundedString(value, label, { max = 4096, allowEmpty = false } = {}) {
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0) || value.length > max || value.includes('\u0000')) {
    throw electronError(`${label} must be ${allowEmpty ? 'a' : 'a non-empty'} bounded string`, 'ELECTRON_VALIDATION_CONFIG_INVALID');
  }
  return value;
}

function normalizeRelativeFile(value, label = 'Electron scenarioFile') {
  const raw = String(value || '').trim().replaceAll('\\', '/');
  if (!raw) throw electronError(`${label} must be non-empty`, 'ELECTRON_SCENARIO_PATH_INVALID');
  if (raw.startsWith('/') || raw.startsWith('//') || /^[A-Za-z]:/.test(raw)) throw electronError(`${label} must be relative to the Electron cwd`, 'ELECTRON_SCENARIO_PATH_ESCAPE');
  const normalized = path.posix.normalize(raw.replace(/^\.\//, ''));
  if (!normalized || normalized === '.' || normalized === '..' || normalized.startsWith('../')) throw electronError(`${label} must remain inside the Electron cwd`, 'ELECTRON_SCENARIO_PATH_ESCAPE');
  return normalized;
}

function normalizeExecutablePath(value) {
  if (typeof value !== 'string' || !value.trim() || value.includes('\u0000')) throw electronError('Electron executablePath must be a non-empty path', 'ELECTRON_EXECUTABLE_PATH_INVALID');
  const normalized = value.trim();
  if (normalized.length > 4096) throw electronError('Electron executablePath is too long', 'ELECTRON_EXECUTABLE_PATH_INVALID');
  if (path.isAbsolute(normalized)) return normalized;
  const relative = path.posix.normalize(normalized.replaceAll('\\', '/').replace(/^\.\//, ''));
  if (!relative || relative === '.' || relative === '..' || relative.startsWith('../') || relative.startsWith('/')) throw electronError('Relative Electron executablePath must remain inside the Electron cwd', 'ELECTRON_EXECUTABLE_PATH_ESCAPE');
  return relative;
}

function normalizeArgs(raw) {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw) || raw.length > MAX_ARGS) throw electronError(`Electron args must be an array with at most ${MAX_ARGS} values`, 'ELECTRON_ARGS_INVALID');
  return raw.map((value) => boundedString(value, 'Electron arg', { max: MAX_ARG_LENGTH, allowEmpty: true }));
}

function normalizeEnvAllowlist(raw) {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw) || raw.length > MAX_ENV_NAMES) throw electronError('Electron envAllowlist must be a bounded array', 'ELECTRON_ENV_INVALID');
  const output = [];
  const seen = new Set();
  for (const value of raw) {
    if (typeof value !== 'string' || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(value)) throw electronError('Electron envAllowlist contains an invalid variable name', 'ELECTRON_ENV_INVALID');
    const identity = value.toUpperCase();
    if (PROTECTED_HOME_ENV.has(identity)) throw electronError('Electron envAllowlist may not override isolated home/config variables', 'ELECTRON_ENV_INVALID');
    if (!seen.has(identity)) { seen.add(identity); output.push(value); }
  }
  return output;
}

function normalizeTimeout(value, fallback, code) {
  const numeric = Number(value ?? fallback);
  if (!Number.isFinite(numeric)) return fallback;
  if (numeric < 250 || numeric > MAX_TIMEOUT_MS) throw electronError(`Electron timeout must be between 250 and ${MAX_TIMEOUT_MS}ms`, code);
  return Math.floor(numeric);
}

export function normalizeElectronValidation(raw) {
  if (raw === undefined || raw === null) return null;
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw electronError('Electron validation configuration must be an object', 'ELECTRON_VALIDATION_CONFIG_INVALID');
  const timeoutMs = normalizeTimeout(raw.timeoutMs, DEFAULT_TIMEOUT_MS, 'ELECTRON_TIMEOUT_INVALID');
  const stepTimeoutMs = normalizeTimeout(raw.stepTimeoutMs, DEFAULT_STEP_TIMEOUT_MS, 'ELECTRON_STEP_TIMEOUT_INVALID');
  return Object.freeze({
    contract: ELECTRON_VALIDATION_CONTRACT,
    executablePath: normalizeExecutablePath(raw.executablePath),
    args: Object.freeze(normalizeArgs(raw.args)),
    cwd: raw.cwd ? boundedString(raw.cwd, 'Electron cwd', { max: 1000 }) : '.',
    scenarioFile: normalizeRelativeFile(raw.scenarioFile),
    timeoutMs,
    stepTimeoutMs: Math.min(stepTimeoutMs, timeoutMs),
    envAllowlist: Object.freeze(normalizeEnvAllowlist(raw.envAllowlist)),
    chromiumSandbox: raw.chromiumSandbox === undefined ? true : (() => {
      if (typeof raw.chromiumSandbox !== 'boolean') throw electronError('Electron chromiumSandbox must be boolean', 'ELECTRON_VALIDATION_CONFIG_INVALID');
      return raw.chromiumSandbox;
    })()
  });
}

function normalizeTarget(raw, index) {
  if (raw === undefined || raw === null) return Object.freeze({ type: 'window', index: 0 });
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw electronError(`Electron scenario step ${index + 1} target must be an object`, 'ELECTRON_SCENARIO_INVALID');
  const type = raw.type === undefined ? 'window' : String(raw.type);
  if (!TARGET_TYPES.has(type)) throw electronError(`Electron scenario step ${index + 1} has unknown target type ${type}`, 'ELECTRON_SCENARIO_INVALID');
  const targetIndex = raw.index === undefined ? 0 : Number(raw.index);
  if (!Number.isInteger(targetIndex) || targetIndex < 0 || targetIndex > 64) throw electronError(`Electron scenario step ${index + 1} target index is invalid`, 'ELECTRON_SCENARIO_INVALID');
  const titleIncludes = raw.titleIncludes === undefined ? null : boundedString(raw.titleIncludes, 'Electron target titleIncludes', { max: 240, allowEmpty: true });
  const urlIncludes = raw.urlIncludes === undefined ? null : boundedString(raw.urlIncludes, 'Electron target urlIncludes', { max: 1000, allowEmpty: true });
  return Object.freeze({ type, index: targetIndex, ...(titleIncludes === null ? {} : { titleIncludes }), ...(urlIncludes === null ? {} : { urlIncludes }) });
}

function normalizeWindowStateExpectation(raw, index) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw electronError(`Electron scenario step ${index + 1} window state must be an object`, 'ELECTRON_SCENARIO_INVALID');
  const keys = Object.keys(raw);
  if (keys.length === 0 || keys.some((key) => !WINDOW_STATE_FIELDS.has(key))) throw electronError(`Electron scenario step ${index + 1} window state contains no supported expectations or an unknown field`, 'ELECTRON_SCENARIO_INVALID');
  const output = {};
  for (const key of ['visible', 'minimized', 'maximized', 'fullScreen']) {
    if (raw[key] === undefined) continue;
    if (typeof raw[key] !== 'boolean') throw electronError(`Electron scenario step ${index + 1} window state ${key} must be boolean`, 'ELECTRON_SCENARIO_INVALID');
    output[key] = raw[key];
  }
  if (raw.bounds !== undefined) {
    if (!raw.bounds || typeof raw.bounds !== 'object' || Array.isArray(raw.bounds)) throw electronError(`Electron scenario step ${index + 1} window state bounds must be an object`, 'ELECTRON_SCENARIO_INVALID');
    const boundKeys = Object.keys(raw.bounds);
    if (boundKeys.length === 0 || boundKeys.some((key) => !WINDOW_BOUND_FIELDS.has(key))) throw electronError(`Electron scenario step ${index + 1} window state bounds contains no supported expectations or an unknown field`, 'ELECTRON_SCENARIO_INVALID');
    const bounds = {};
    for (const key of ['width', 'height']) {
      if (raw.bounds[key] === undefined) continue;
      if (!Number.isInteger(raw.bounds[key]) || raw.bounds[key] < 1 || raw.bounds[key] > MAX_WINDOW_DIMENSION) throw electronError(`Electron scenario step ${index + 1} window state bounds ${key} must be an integer between 1 and ${MAX_WINDOW_DIMENSION}`, 'ELECTRON_SCENARIO_INVALID');
      bounds[key] = raw.bounds[key];
    }
    if (Object.keys(bounds).length === 0) throw electronError(`Electron scenario step ${index + 1} window state bounds must include width or height`, 'ELECTRON_SCENARIO_INVALID');
    output.bounds = Object.freeze(bounds);
  }
  if (Object.keys(output).length === 0) throw electronError(`Electron scenario step ${index + 1} window state must include at least one expectation`, 'ELECTRON_SCENARIO_INVALID');
  return Object.freeze(output);
}

function normalizeMenuItemExpectation(raw, index) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw electronError(`Electron scenario step ${index + 1} menu item must be an object`, 'ELECTRON_SCENARIO_INVALID');
  const keys = Object.keys(raw);
  if (keys.length === 0 || keys.some((key) => !MENU_ITEM_FIELDS.has(key))) throw electronError(`Electron scenario step ${index + 1} menu item contains no supported expectations or an unknown field`, 'ELECTRON_SCENARIO_INVALID');
  const output = {};
  const limits = { id: 240, label: 240, role: 120, type: 80, accelerator: 120 };
  for (const key of ['id', 'label', 'role', 'type', 'accelerator']) {
    if (raw[key] === undefined) continue;
    output[key] = boundedString(raw[key], `Electron scenario step ${index + 1} menu item ${key}`, { max: limits[key] });
  }
  for (const key of ['enabled', 'visible', 'checked']) {
    if (raw[key] === undefined) continue;
    if (typeof raw[key] !== 'boolean') throw electronError(`Electron scenario step ${index + 1} menu item ${key} must be boolean`, 'ELECTRON_SCENARIO_INVALID');
    output[key] = raw[key];
  }
  if (![...MENU_ITEM_IDENTITY_FIELDS].some((key) => Object.hasOwn(output, key))) throw electronError(`Electron scenario step ${index + 1} menu item must include id, label, role, or accelerator`, 'ELECTRON_SCENARIO_INVALID');
  return Object.freeze(output);
}

function normalizeVisualExpectation(raw, index) {
  try {
    return normalizeVisualCompareRequest(raw);
  } catch {
    throw electronError(`Electron scenario step ${index + 1} visual expectation is invalid`, 'ELECTRON_SCENARIO_INVALID');
  }
}

function normalizeStep(raw, index, defaultStepTimeoutMs) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw electronError(`Electron scenario step ${index + 1} must be an object`, 'ELECTRON_SCENARIO_INVALID');
  const action = String(raw.action || '');
  if (!ACTIONS.has(action)) throw electronError(`Electron scenario step ${index + 1} has unknown action ${action || '<empty>'}`, 'ELECTRON_SCENARIO_INVALID');
  if (action === 'assertMenuItem' && raw.target !== undefined) throw electronError(`Electron scenario step ${index + 1} menu item assertions are application-level and may not specify a target`, 'ELECTRON_SCENARIO_INVALID');
  const target = normalizeTarget(raw.target, index);
  const timeoutMs = raw.timeoutMs === undefined ? defaultStepTimeoutMs : normalizeTimeout(raw.timeoutMs, defaultStepTimeoutMs, 'ELECTRON_STEP_TIMEOUT_INVALID');
  const name = raw.name === undefined ? null : boundedString(raw.name, 'Electron step name', { max: 240 });
  const selectorRequired = new Set(['click', 'fill', 'assertVisible', 'assertText', 'assertValue']);
  const selector = raw.selector === undefined ? null : boundedString(raw.selector, 'Electron selector', { max: 2000 });
  if (selectorRequired.has(action) && !selector) throw electronError(`Electron scenario step ${index + 1} action ${action} requires selector`, 'ELECTRON_SCENARIO_INVALID');
  const step = { action, target, timeoutMs, ...(name ? { name } : {}) };
  if (selector) step.selector = selector;
  if (action === 'assertSurfaceCount') {
    const count = Number(raw.count);
    if (!Number.isInteger(count) || count < 0 || count > MAX_SURFACES) throw electronError(`Electron scenario step ${index + 1} surface count must be between 0 and ${MAX_SURFACES}`, 'ELECTRON_SCENARIO_INVALID');
    step.count = count;
  }
  if (action === 'assertWindowState') {
    if (target.type !== 'window') throw electronError(`Electron scenario step ${index + 1} window state assertions require a window target`, 'ELECTRON_SCENARIO_INVALID');
    step.state = normalizeWindowStateExpectation(raw.state, index);
  }
  if (action === 'assertMenuItem') step.item = normalizeMenuItemExpectation(raw.item, index);
  if (action === 'assertVisual') step.visual = normalizeVisualExpectation(raw.visual, index);
  if (action === 'fill') step.value = boundedString(raw.value ?? '', 'Electron fill value', { max: 10000, allowEmpty: true });
  if (action === 'press') { step.key = boundedString(raw.key, 'Electron key', { max: 120 }); if (selector) step.selector = selector; }
  if (action === 'assertText') {
    step.text = boundedString(raw.text ?? '', 'Electron asserted text', { max: 10000, allowEmpty: true });
    step.match = raw.match === undefined ? 'contains' : String(raw.match);
    if (!MATCH_MODES.has(step.match)) throw electronError(`Electron scenario step ${index + 1} has invalid text match`, 'ELECTRON_SCENARIO_INVALID');
  }
  if (action === 'assertValue') step.value = boundedString(raw.value ?? '', 'Electron asserted value', { max: 10000, allowEmpty: true });
  if (action === 'assertUrl') {
    step.url = boundedString(raw.url ?? '', 'Electron asserted URL', { max: 2000, allowEmpty: true });
    step.match = raw.match === undefined ? 'contains' : String(raw.match);
    if (!MATCH_MODES.has(step.match)) throw electronError(`Electron scenario step ${index + 1} has invalid URL match`, 'ELECTRON_SCENARIO_INVALID');
  }
  if (action === 'screenshot') {
    const filename = raw.filename === undefined ? `step-${String(index + 1).padStart(3, '0')}.png` : String(raw.filename).trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.png$/i.test(filename)) throw electronError(`Electron scenario step ${index + 1} screenshot name must be a bounded .png filename`, 'ELECTRON_SCENARIO_INVALID');
    step.filename = filename;
  }
  return Object.freeze(step);
}

export function normalizeElectronScenario(raw, { stepTimeoutMs = DEFAULT_STEP_TIMEOUT_MS } = {}) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw.contract !== ELECTRON_SCENARIO_CONTRACT) throw electronError(`Electron scenario must use contract ${ELECTRON_SCENARIO_CONTRACT}`, 'ELECTRON_SCENARIO_INVALID');
  if (!Array.isArray(raw.steps) || raw.steps.length === 0 || raw.steps.length > MAX_STEPS) throw electronError(`Electron scenario steps must contain 1-${MAX_STEPS} entries`, 'ELECTRON_SCENARIO_INVALID');
  const steps = raw.steps.map((step, index) => normalizeStep(step, index, stepTimeoutMs));
  if (steps.filter((step) => step.action === 'screenshot').length > MAX_SCREENSHOTS) throw electronError(`Electron scenario may request at most ${MAX_SCREENSHOTS} screenshots`, 'ELECTRON_SCENARIO_INVALID');
  return Object.freeze({ contract: ELECTRON_SCENARIO_CONTRACT, steps: Object.freeze(steps) });
}

function insideRoot(root, candidate) {
  const rel = path.relative(root, candidate);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

export async function prepareElectronValidation(electron, cwd, environment) {
  const realRoot = await fs.realpath(cwd);
  const scenarioPath = path.resolve(realRoot, ...electron.scenarioFile.split('/'));
  if (!insideRoot(realRoot, scenarioPath)) throw electronError('Electron scenarioFile escapes the Electron cwd', 'ELECTRON_SCENARIO_PATH_ESCAPE');
  const info = await fs.lstat(scenarioPath).catch((error) => {
    if (error?.code === 'ENOENT') throw electronError('Electron scenarioFile does not exist', 'ELECTRON_SCENARIO_NOT_FOUND');
    throw error;
  });
  if (info.isSymbolicLink()) throw electronError('Electron scenarioFile may not be a symlink', 'ELECTRON_SCENARIO_SYMLINK');
  if (!info.isFile() || info.size > MAX_SCENARIO_BYTES) throw electronError('Electron scenarioFile is invalid or too large', 'ELECTRON_SCENARIO_INVALID');
  const scenarioReal = await fs.realpath(scenarioPath);
  if (!insideRoot(realRoot, scenarioReal)) throw electronError('Electron scenarioFile resolves outside the Electron cwd', 'ELECTRON_SCENARIO_PATH_ESCAPE');
  let parsed;
  try { parsed = JSON.parse(await fs.readFile(scenarioReal, 'utf8')); } catch (error) {
    if (error?.code) throw error;
    throw electronError('Electron scenarioFile is not valid JSON', 'ELECTRON_SCENARIO_INVALID');
  }
  const executablePath = path.isAbsolute(electron.executablePath) ? electron.executablePath : path.resolve(realRoot, ...electron.executablePath.replaceAll('\\', '/').split('/'));
  if (!path.isAbsolute(electron.executablePath)) {
    const resolved = await fs.realpath(executablePath).catch(() => executablePath);
    if (!insideRoot(realRoot, resolved)) throw electronError('Relative Electron executablePath escapes the Electron cwd', 'ELECTRON_EXECUTABLE_PATH_ESCAPE');
  }
  const executableInfo = await fs.stat(executablePath).catch((error) => {
    if (error?.code === 'ENOENT') throw electronError('Electron executablePath does not exist', 'ELECTRON_EXECUTABLE_NOT_FOUND');
    throw error;
  });
  if (!executableInfo.isFile()) throw electronError('Electron executablePath must resolve to a file', 'ELECTRON_EXECUTABLE_PATH_INVALID');
  const home = await fs.mkdtemp(path.join(os.tmpdir(), 'veteran-electron-home-'));
  const env = {};
  for (const key of SAFE_ENV_KEYS) if (typeof environment?.[key] === 'string') env[key] = environment[key];
  Object.assign(env, {
    HOME: home,
    USERPROFILE: home,
    XDG_CONFIG_HOME: path.join(home, '.config'),
    XDG_CACHE_HOME: path.join(home, '.cache'),
    APPDATA: path.join(home, 'AppData', 'Roaming'),
    LOCALAPPDATA: path.join(home, 'AppData', 'Local')
  });
  for (const key of electron.envAllowlist) if (typeof environment?.[key] === 'string') env[key] = environment[key];
  return { scenario: normalizeElectronScenario(parsed, { stepTimeoutMs: electron.stepTimeoutMs }), executablePath, env, home };
}

export function sanitizeElectronUrl(value) {
  if (!value) return '';
  try {
    const url = new URL(value);
    url.username = ''; url.password = ''; url.search = ''; url.hash = '';
    if (url.protocol === 'file:') return `file:///${path.basename(decodeURIComponent(url.pathname))}`;
    return url.toString();
  } catch {
    return String(value).slice(0, 1000).replace(/[?#].*$/, '');
  }
}