import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { signalProcessTree } from './process-lifecycle-authority.mjs';

export const NATIVE_BROWSER_SCENARIO_CONTRACT = 'veteran-browser-scenario-v1';
const RESULT_CONTRACT = 'veteran-browser-validation-v1';
const SESSION_CONTRACT = 'veteran-browser-session-jsonl-v1';
const ACTIONS = new Set(['click', 'fill', 'assertVisible', 'assertText', 'assertValue', 'assertUrl', 'screenshot']);
const MATCH = new Set(['equals', 'contains']);
const MAX_STEPS = 256;
const MAX_SCREENSHOTS = 32;
const MAX_SCENARIO_BYTES = 256 * 1024;
const MAX_SCREENSHOT_BYTES = 16 * 1024 * 1024;
const MAX_CDP_BYTES = 2 * 1024 * 1024;
const DEFAULT_STEP_TIMEOUT = 10_000;

function fail(message, code) { const e = new Error(message); e.code = code; return e; }
function text(value, label, max = 4096, empty = false) {
  if (typeof value !== 'string' || (!empty && !value) || value.length > max || value.includes('\0')) throw fail(`${label} is invalid`, 'BROWSER_NATIVE_SCENARIO_INVALID');
  return value;
}
function timeout(value) {
  const n = Number(value ?? DEFAULT_STEP_TIMEOUT);
  if (!Number.isFinite(n) || n < 250 || n > 60_000) throw fail('Browser step timeout is invalid', 'BROWSER_NATIVE_SCENARIO_INVALID');
  return Math.floor(n);
}
export function normalizeNativeBrowserScenario(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw.contract !== NATIVE_BROWSER_SCENARIO_CONTRACT) throw fail(`Native browser scenario must use contract ${NATIVE_BROWSER_SCENARIO_CONTRACT}`, 'BROWSER_NATIVE_SCENARIO_INVALID');
  if (!Array.isArray(raw.steps) || !raw.steps.length || raw.steps.length > MAX_STEPS) throw fail(`Native browser scenario must contain 1-${MAX_STEPS} steps`, 'BROWSER_NATIVE_SCENARIO_INVALID');
  let screenshots = 0;
  const steps = raw.steps.map((item, index) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) throw fail(`Browser step ${index + 1} is invalid`, 'BROWSER_NATIVE_SCENARIO_INVALID');
    const action = String(item.action || '');
    if (!ACTIONS.has(action)) throw fail(`Browser step ${index + 1} has unknown action ${action || '<empty>'}`, 'BROWSER_NATIVE_SCENARIO_INVALID');
    const step = { action, timeoutMs: timeout(item.timeoutMs) };
    if (item.name !== undefined) step.name = text(item.name, 'Browser step name', 240);
    if (['click', 'fill', 'assertVisible', 'assertText', 'assertValue'].includes(action)) step.selector = text(item.selector, 'Browser selector', 2000);
    if (action === 'fill' || action === 'assertValue') step.value = text(item.value ?? '', 'Browser value', 10_000, true);
    if (action === 'assertText') {
      step.text = text(item.text ?? '', 'Browser asserted text', 10_000, true);
      step.match = item.match === undefined ? 'contains' : String(item.match);
      if (!MATCH.has(step.match)) throw fail('Browser text match is invalid', 'BROWSER_NATIVE_SCENARIO_INVALID');
    }
    if (action === 'assertUrl') {
      step.url = text(item.url ?? '', 'Browser asserted URL', 2000, true);
      step.match = item.match === undefined ? 'contains' : String(item.match);
      if (!MATCH.has(step.match)) throw fail('Browser URL match is invalid', 'BROWSER_NATIVE_SCENARIO_INVALID');
    }
    if (action === 'screenshot') {
      screenshots += 1;
      const filename = String(item.filename || `step-${String(index + 1).padStart(3, '0')}.png`).trim();
      if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}\.png$/i.test(filename)) throw fail('Browser screenshot filename is invalid', 'BROWSER_NATIVE_SCENARIO_INVALID');
      step.filename = filename;
    }
    return Object.freeze(step);
  });
  if (screenshots > MAX_SCREENSHOTS) throw fail(`Native browser scenario may request at most ${MAX_SCREENSHOTS} screenshots`, 'BROWSER_NATIVE_SCENARIO_INVALID');
  return Object.freeze({ contract: NATIVE_BROWSER_SCENARIO_CONTRACT, steps: Object.freeze(steps) });
}

const delay = (ms) => new Promise((r) => setTimeout(r, ms));
function kill(child, signal = 'SIGTERM') {
  if (!child?.pid) return;
  signalProcessTree(child.pid, signal);
}
class Cdp {
  constructor(child) {
    this.child = child; this.id = 0; this.pending = new Map(); this.handlers = new Set(); this.buffer = Buffer.alloc(0); this.closed = false;
    child.stdio[4].on('data', (chunk) => this.onData(chunk));
    child.stdio[4].on('error', () => this.close('BROWSER_NATIVE_CDP_PIPE_FAILED'));
    child.stdio[4].once('end', () => this.close('BROWSER_NATIVE_CDP_PIPE_FAILED'));
    child.stdio[3].on('error', () => this.close('BROWSER_NATIVE_CDP_PIPE_FAILED'));
    child.once('error', () => this.close('BROWSER_NATIVE_SPAWN_FAILED'));
    child.once('exit', () => this.close('BROWSER_NATIVE_PROCESS_EXITED'));
  }
  on(handler) { this.handlers.add(handler); }
  close(code) {
    if (this.closed) return; this.closed = true;
    for (const p of this.pending.values()) { clearTimeout(p.timer); p.reject(fail('Chromium DevTools pipe closed', code)); }
    this.pending.clear();
  }
  onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, Buffer.from(chunk)]);
    if (this.buffer.length > MAX_CDP_BYTES * 2) return this.close('BROWSER_NATIVE_CDP_MESSAGE_TOO_LARGE');
    for (;;) {
      const end = this.buffer.indexOf(0); if (end < 0) break;
      const raw = this.buffer.subarray(0, end); this.buffer = this.buffer.subarray(end + 1);
      if (!raw.length || raw.length > MAX_CDP_BYTES) continue;
      let msg; try { msg = JSON.parse(raw.toString('utf8')); } catch { continue; }
      if (Number.isInteger(msg.id)) {
        const p = this.pending.get(msg.id); if (!p) continue; this.pending.delete(msg.id); clearTimeout(p.timer);
        msg.error ? p.reject(fail(String(msg.error.message || 'CDP request failed'), 'BROWSER_NATIVE_CDP_FAILED')) : p.resolve(msg.result || {});
      } else for (const h of this.handlers) { try { h(msg); } catch {} }
    }
  }
  request(method, params = {}, sessionId = null, timeoutMs = 10_000) {
    if (this.closed) return Promise.reject(fail('Chromium DevTools pipe is closed', 'BROWSER_NATIVE_CDP_PIPE_FAILED'));
    const id = ++this.id;
    const body = Buffer.from(`${JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) })}\0`);
    if (body.length > MAX_CDP_BYTES) return Promise.reject(fail('Chromium DevTools request is too large', 'BROWSER_NATIVE_CDP_MESSAGE_TOO_LARGE'));
    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(fail(`Chromium DevTools request timed out: ${method}`, 'BROWSER_NATIVE_CDP_TIMEOUT')); }, Math.max(1, timeoutMs));
      this.pending.set(id, { resolve, reject, timer });
    });
    this.child.stdio[3].write(body, (error) => {
      if (!error) return; const p = this.pending.get(id); if (!p) return; this.pending.delete(id); clearTimeout(p.timer); p.reject(fail('Chromium DevTools request pipe failed', 'BROWSER_NATIVE_CDP_PIPE_FAILED'));
    });
    return promise;
  }
}
function allowed(url, base) {
  try { const u = new URL(url, base), b = new URL(base); return ['data:', 'about:'].includes(u.protocol) || (u.protocol === 'blob:' ? u.origin === b.origin : u.origin === b.origin); } catch { return false; }
}
function safeUrl(value, base) {
  try { const u = new URL(value, base), b = new URL(base); if (u.origin !== b.origin) return `${b.origin}/`; u.username = ''; u.password = ''; u.search = ''; u.hash = ''; return u.toString(); } catch { return base; }
}
class Runtime {
  constructor(executable, cwd, env) { this.executable = executable; this.cwd = cwd; this.env = env; this.base = null; this.child = null; this.cdp = null; this.session = null; this.diag = this.blank(); this.stderrBytes = 0; }
  blank() { return { consoleMessages: 0, consoleErrors: 0, pageErrors: 0, requestFailures: 0, httpErrors: 0, blockedExternalRequests: 0, crashes: 0 }; }
  async start() {
    const profile = path.join(this.env.HOME || os.tmpdir(), 'chromium-profile'); await fs.mkdir(profile, { recursive: true });
    this.child = spawn(this.executable, ['--headless=new', '--remote-debugging-pipe', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--metrics-recording-only', '--disable-default-apps', 'about:blank'], { cwd: this.cwd, env: this.env, shell: false, detached: process.platform !== 'win32', windowsHide: true, stdio: ['pipe', 'pipe', 'pipe', 'pipe', 'pipe'] });
    // Keep valid standard handles alongside CDP fds 3/4 on Windows. Drain
    // browser stdout without forwarding it into the provider JSON protocol.
    this.child.stdin.on('error', () => {});
    this.child.stdout.resume();
    this.child.stderr.on('data', (c) => { this.stderrBytes += Buffer.byteLength(c); });
    this.cdp = new Cdp(this.child); await this.cdp.request('Browser.getVersion', {}, null, 15_000);
    const target = await this.cdp.request('Target.createTarget', { url: 'about:blank' });
    const attached = await this.cdp.request('Target.attachToTarget', { targetId: target.targetId, flatten: true }); this.session = attached.sessionId;
    for (const method of ['Page.enable', 'Runtime.enable', 'Network.enable', 'Inspector.enable']) await this.cdp.request(method, {}, this.session);
    await this.cdp.request('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] }, this.session);
    this.cdp.on((m) => this.event(m));
  }
  event(m) {
    if (m.sessionId && m.sessionId !== this.session) return; const p = m.params || {};
    if (m.method === 'Runtime.consoleAPICalled') { this.diag.consoleMessages += 1; if (p.type === 'error') this.diag.consoleErrors += 1; }
    else if (m.method === 'Runtime.exceptionThrown') this.diag.pageErrors += 1;
    else if (m.method === 'Network.loadingFailed' && !p.canceled) this.diag.requestFailures += 1;
    else if (m.method === 'Network.responseReceived' && Number(p.response?.status) >= 400) this.diag.httpErrors += 1;
    else if (m.method === 'Inspector.targetCrashed' || m.method === 'Target.targetCrashed') this.diag.crashes += 1;
    else if (m.method === 'Fetch.requestPaused') {
      const method = allowed(String(p.request?.url || ''), this.base || 'http://127.0.0.1/') ? 'Fetch.continueRequest' : 'Fetch.failRequest';
      if (method === 'Fetch.failRequest') this.diag.blockedExternalRequests += 1;
      this.cdp.request(method, method === 'Fetch.continueRequest' ? { requestId: p.requestId } : { requestId: p.requestId, errorReason: 'BlockedByClient' }, this.session).catch(() => {});
    }
  }
  snapshot() { return { ...this.diag }; }
  delta(before) { const r = {}; for (const [k, v] of Object.entries(this.diag)) r[k] = Math.max(0, v - Number(before[k] || 0)); r.stderrBytes = this.stderrBytes; return r; }
  async close() { if (!this.child) return; try { await this.cdp?.request('Browser.close', {}, null, 1000); } catch {} await delay(100); if (this.child.exitCode === null) kill(this.child); await delay(150); if (this.child.exitCode === null) kill(this.child, 'SIGKILL'); }
  async eval(expression, ms = 5000) { const r = await this.cdp.request('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }, this.session, ms); if (r.exceptionDetails) throw fail('Browser runtime evaluation failed', 'BROWSER_NATIVE_RUNTIME_ERROR'); return r.result?.value; }
  async current() { return String(await this.eval('location.href', 2000) || ''); }
  async origin() { const u = await this.current(); if (!allowed(u, this.base)) throw fail('Browser navigation escaped validation origin', 'BROWSER_NATIVE_ORIGIN_ESCAPE'); }
  async navigate(url, ms) { await this.cdp.request('Page.navigate', { url }, this.session, ms); const end = Date.now() + ms; for (;;) { const s = await this.eval('document.readyState', Math.min(1000, Math.max(1, end - Date.now()))).catch(() => ''); if (s === 'interactive' || s === 'complete') break; if (Date.now() >= end) throw fail('Browser page did not become ready', 'BROWSER_NATIVE_NAVIGATION_TIMEOUT'); await delay(50); } }
  inspect(selector, ms) { const q = JSON.stringify(selector); return this.eval(`(()=>{const e=document.querySelector(${q});if(!e)return {found:false,visible:false,text:null,value:null,rect:null};const s=getComputedStyle(e),r=e.getBoundingClientRect();return {found:true,visible:s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity||1)!==0&&r.width>0&&r.height>0,text:e.textContent??'',value:'value' in e?String(e.value??''):null,rect:{x:r.x,y:r.y,width:r.width,height:r.height}}})()`, ms); }
  async click(selector, ms) { const v = await this.inspect(selector, ms); if (!v?.found || !v.visible || !v.rect) return false; const x = Math.floor(v.rect.x + v.rect.width / 2), y = Math.floor(v.rect.y + v.rect.height / 2); for (const [type, extra] of [['mouseMoved', {}], ['mousePressed', { button: 'left', clickCount: 1 }], ['mouseReleased', { button: 'left', clickCount: 1 }]]) await this.cdp.request('Input.dispatchMouseEvent', { type, x, y, ...extra }, this.session, ms); return true; }
  async fill(selector, value, ms) { const q = JSON.stringify(selector); const ok = await this.eval(`(()=>{const e=document.querySelector(${q});if(!e)return false;e.focus();if('value' in e){const p=Object.getPrototypeOf(e),s=Object.getOwnPropertyDescriptor(p,'value')?.set;s?s.call(e,''):e.value='';e.dispatchEvent(new Event('input',{bubbles:true}))}return true})()`, ms); if (!ok) return false; await this.cdp.request('Input.insertText', { text: String(value) }, this.session, ms); return true; }
  async shot(file, ms) { const r = await this.cdp.request('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false }, this.session, ms); const b = Buffer.from(String(r.data || ''), 'base64'); if (!b.length || b.length > MAX_SCREENSHOT_BYTES) throw fail('Browser screenshot is invalid', 'BROWSER_NATIVE_SCREENSHOT_FAILED'); await fs.mkdir(path.dirname(file), { recursive: true }); await fs.writeFile(file, b); }
}
async function readScenario(cwd, rel) {
  const normalized = path.posix.normalize(String(rel || '').replaceAll('\\', '/'));
  if (!normalized || normalized === '.' || normalized === '..' || normalized.startsWith('../') || path.posix.isAbsolute(normalized)) throw fail('Browser scenario path escaped provider cwd', 'BROWSER_NATIVE_SCENARIO_PATH_ESCAPE');
  const root = await fs.realpath(cwd), target = path.resolve(root, ...normalized.split('/')), relative = path.relative(root, target);
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw fail('Browser scenario path escaped provider cwd', 'BROWSER_NATIVE_SCENARIO_PATH_ESCAPE');
  const info = await fs.lstat(target); if (info.isSymbolicLink() || !info.isFile() || info.size > MAX_SCENARIO_BYTES) throw fail('Browser scenario file is invalid', 'BROWSER_NATIVE_SCENARIO_INVALID');
  return normalizeNativeBrowserScenario(JSON.parse(await fs.readFile(target, 'utf8')));
}
const matching = (a, b, mode) => mode === 'equals' ? a === b : a.includes(b);
async function poll(ms, operation, predicate) { const end = Date.now() + ms; let value; for (;;) { value = await operation(Math.max(1, Math.min(1000, end - Date.now()))).catch(() => null); if (predicate(value) || Date.now() >= end) return value; await delay(Math.min(50, Math.max(1, end - Date.now()))); } }
async function execute(runtime, payload, cwd) {
  const base = new URL(payload.baseUrl).toString(); runtime.base = base; const scenario = await readScenario(cwd, payload.scenario?.path);
  const artifactDir = path.join(cwd, '.veteran-browser-artifacts'); await fs.rm(artifactDir, { recursive: true, force: true }); await fs.mkdir(artifactDir, { recursive: true });
  const assertions = [], before = runtime.snapshot(); let code = null, message = null, failedAt = null;
  try {
    await runtime.navigate(base, Math.min(15_000, scenario.steps[0]?.timeoutMs || DEFAULT_STEP_TIMEOUT)); await runtime.origin();
    for (let i = 0; i < scenario.steps.length; i += 1) {
      const s = scenario.steps[i];
      try {
        if (s.action === 'click') { if (!(await poll(s.timeoutMs, (t) => runtime.click(s.selector, t), Boolean))) throw fail('Browser click target was not interactable', 'BROWSER_NATIVE_ACTION_FAILED'); await runtime.origin(); continue; }
        if (s.action === 'fill') { if (!(await poll(s.timeoutMs, (t) => runtime.fill(s.selector, s.value, t), Boolean))) throw fail('Browser fill target was not found', 'BROWSER_NATIVE_ACTION_FAILED'); continue; }
        if (s.action === 'screenshot') { await runtime.shot(path.join(artifactDir, s.filename), s.timeoutMs); continue; }
        let actual = null, passed = false;
        if (s.action === 'assertVisible') { actual = await poll(s.timeoutMs, (t) => runtime.inspect(s.selector, t), (v) => Boolean(v?.found && v.visible)); passed = Boolean(actual?.found && actual.visible); }
        else if (s.action === 'assertText') { actual = await poll(s.timeoutMs, (t) => runtime.inspect(s.selector, t), (v) => Boolean(v?.found && matching(String(v.text ?? ''), s.text, s.match))); passed = Boolean(actual?.found && matching(String(actual.text ?? ''), s.text, s.match)); }
        else if (s.action === 'assertValue') { actual = await poll(s.timeoutMs, (t) => runtime.inspect(s.selector, t), (v) => Boolean(v?.found && String(v.value ?? '') === s.value)); passed = Boolean(actual?.found && String(actual.value ?? '') === s.value); }
        else if (s.action === 'assertUrl') { actual = await poll(s.timeoutMs, () => runtime.current(), (v) => typeof v === 'string' && matching(v, s.url, s.match)); passed = typeof actual === 'string' && matching(actual, s.url, s.match); }
        assertions.push({ name: s.name || `${s.action} step ${i + 1}`, passed, ...(s.action === 'assertText' ? { detail: String(actual?.text ?? '').slice(0, 1200) } : {}) });
        if (!passed) throw fail(`Browser assertion failed: ${assertions.at(-1).name}`, 'BROWSER_ASSERTION_FAILED');
      } catch (e) { code = e?.code || 'BROWSER_NATIVE_STEP_FAILED'; message = String(e?.message || e).slice(0, 1000); failedAt = i; try { await runtime.shot(path.join(artifactDir, `failure-step-${String(i + 1).padStart(3, '0')}.png`), Math.min(1500, s.timeoutMs)); } catch {} break; }
    }
  } catch (e) { code = e?.code || 'BROWSER_NATIVE_VALIDATION_FAILED'; message = String(e?.message || e).slice(0, 1000); }
  const diagnostics = runtime.delta(before);
  if (!code && diagnostics.crashes) { code = 'BROWSER_RENDERER_CRASHED'; message = 'Browser renderer crashed during validation.'; }
  if (!code && diagnostics.pageErrors) { code = 'BROWSER_PAGE_ERROR'; message = 'Browser page emitted an uncaught runtime error.'; }
  if (!code && diagnostics.blockedExternalRequests) { code = 'BROWSER_EXTERNAL_REQUEST_BLOCKED'; message = 'Browser page attempted network access outside the loopback validation origin.'; }
  const passed = !code && assertions.every((a) => a.passed), current = safeUrl(await runtime.current().catch(() => base), base);
  return { contract: RESULT_CONTRACT, passed, summary: passed ? `Native browser scenario passed ${assertions.length} assertion(s) across ${scenario.steps.length} step(s).` : `Native browser scenario failed${failedAt === null ? '' : ` at step ${failedAt + 1}`}: ${message || code}`, assertions, currentUrl: current, diagnostics, ...(passed ? {} : { failureCode: code || 'BROWSER_ASSERTION_FAILED' }) };
}
function args(argv) { let executable = null, session = false; for (let i = 0; i < argv.length; i += 1) { if (argv[i] === '--session') session = true; else if (argv[i] === '--executable') executable = argv[++i] || null; } if (!executable) throw fail('Native browser provider requires --executable', 'BROWSER_NATIVE_EXECUTABLE_REQUIRED'); return { executable, session }; }
async function one(executable) {
  let input = '';
  process.stdin.setEncoding('utf8');
  for await (const c of process.stdin) input += c;
  const runtime = new Runtime(executable, process.cwd(), process.env);
  let phase = 'startup', result;
  try {
    await runtime.start();
    phase = 'scenario';
    result = await execute(runtime, JSON.parse(input), process.cwd());
  } catch (error) {
    // A failed browser is a failed validation result, not a broken provider
    // protocol. Preserve the bounded code without persisting raw stderr,
    // executable paths, environment values, or a secret-bearing stack trace.
    const failureCode = /^BROWSER_[A-Z0-9_]{1,100}$/.test(error?.code || '')
      ? error.code : 'BROWSER_NATIVE_STARTUP_FAILED';
    result = {
      contract: RESULT_CONTRACT, passed: false, failureCode,
      summary: `Native browser ${phase} failed (${failureCode}).`,
      assertions: [], currentUrl: null,
      diagnostics: { phase, browserExitCode: runtime.child?.exitCode ?? -1, stderrBytes: runtime.stderrBytes }
    };
  } finally {
    await runtime.close().catch(() => {});
  }
  process.stdout.write(JSON.stringify(result));
}
async function persistent(executable) {
  const runtime = new Runtime(executable, process.cwd(), process.env); await runtime.start(); let buffer = '', chain = Promise.resolve(); process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => { buffer += chunk; let end; while ((end = buffer.indexOf('\n')) >= 0) { const line = buffer.slice(0, end).trim(); buffer = buffer.slice(end + 1); if (!line) continue; chain = chain.then(async () => { const raw = JSON.parse(line); if (raw.sessionContract !== SESSION_CONTRACT || raw.operation !== 'observe' || !raw.requestId) throw fail('Native browser session request is invalid', 'BROWSER_NATIVE_REQUEST_INVALID'); const result = await execute(runtime, raw, process.cwd()); process.stdout.write(`${JSON.stringify({ sessionContract: SESSION_CONTRACT, requestId: raw.requestId, ...result })}\n`); }).catch(async (e) => { process.stderr.write(`${String(e?.stack || e)}\n`); await runtime.close().catch(() => {}); process.exitCode = 1; }); } });
  process.stdin.on('end', async () => { await chain.catch(() => {}); await runtime.close().catch(() => {}); });
}
export async function main(argv = process.argv.slice(2)) { const parsed = args(argv); parsed.session ? await persistent(parsed.executable) : await one(parsed.executable); }
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch((e) => { process.stderr.write(`${String(e?.stack || e)}\n`); process.exitCode = 1; });