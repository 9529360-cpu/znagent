import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import {
  BROWSER_SESSION_CONTRACT,
  MAX_BROWSER_STDERR_BYTES,
  MAX_BROWSER_STDOUT_BYTES,
  createBrowserIsolatedEnvironment,
  normalizeBrowserProviderResult,
  prepareBrowserValidationRequest,
  terminateBrowserProviderTree
} from './browser-validation-provider.mjs';
import { nowIso, randomId, sha256, stableStringify } from './util.mjs';

const MAX_BROWSER_SESSIONS = 16;

function sessionKey(projectId, missionId, capability) {
  return `${projectId}:${missionId}:${capability}`;
}

function providerFingerprint(browser, cwd) {
  return sha256(stableStringify({
    command: browser.session?.command || null,
    timeoutMs: browser.session?.timeoutMs || null,
    envAllowlist: browser.envAllowlist || [],
    cwd
  }));
}

function boundedMessage(value) {
  return String(value || '').slice(0, 1000);
}

function errorResult(code, message, details = null) {
  return { used: true, ok: false, errorCode: code, message: boundedMessage(message), details };
}

function sessionSummary(session, extra = {}) {
  return {
    mode: 'persistent-browser',
    sessionId: session.id,
    providerPid: session.child?.pid || null,
    serviceSessionId: session.serviceSessionId,
    observation: session.observations,
    sourceHead: session.sourceHead,
    startedAt: session.startedAt,
    lastUsedAt: session.lastUsedAt,
    ...extra
  };
}

async function waitForExit(child, timeoutMs = 500) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  await Promise.race([
    new Promise((resolve) => child.once('close', resolve)),
    new Promise((resolve) => setTimeout(resolve, timeoutMs))
  ]);
}

export class BrowserValidationSessionManager {
  constructor({ maxSessions = MAX_BROWSER_SESSIONS } = {}) {
    this.maxSessions = Math.max(1, Math.min(MAX_BROWSER_SESSIONS, Number(maxSessions) || MAX_BROWSER_SESSIONS));
    this.sessions = new Map();
    this.locks = new Map();
  }

  snapshot() {
    return [...this.sessions.values()].map((session) => ({
      id: session.id,
      projectId: session.projectId,
      missionId: session.missionId,
      capability: session.capability,
      providerPid: session.child?.pid || null,
      serviceSessionId: session.serviceSessionId,
      observations: session.observations,
      sourceHead: session.sourceHead,
      startedAt: session.startedAt,
      lastUsedAt: session.lastUsedAt,
      running: session.exited !== true && session.child?.exitCode === null
    }));
  }

  async #withLock(key, work) {
    const prior = this.locks.get(key) || Promise.resolve();
    let release;
    const current = new Promise((resolve) => { release = resolve; });
    const chained = prior.then(() => current);
    this.locks.set(key, chained);
    await prior;
    try {
      return await work();
    } finally {
      release();
      if (this.locks.get(key) === chained) this.locks.delete(key);
    }
  }

  #failPending(session, code, message) {
    const pending = session.pending;
    session.pending = null;
    if (!pending) return;
    clearTimeout(pending.timer);
    pending.reject(Object.assign(new Error(message), { code }));
  }

  #fault(session, code, message) {
    if (session.fault) return;
    session.fault = { code, message: boundedMessage(message) };
    this.#failPending(session, code, message);
    terminateBrowserProviderTree(session.child);
  }

  #attachProcess(session) {
    session.child.stdout.setEncoding('utf8');
    session.child.stderr.setEncoding('utf8');
    session.child.stdout.on('data', (chunk) => {
      session.stdoutBuffer += String(chunk);
      if (Buffer.byteLength(session.stdoutBuffer) > MAX_BROWSER_STDOUT_BYTES) {
        this.#fault(session, 'BROWSER_SESSION_OUTPUT_LIMIT', 'Persistent browser provider stdout exceeded the bounded protocol limit.');
        return;
      }
      while (true) {
        const newline = session.stdoutBuffer.indexOf('\n');
        if (newline < 0) break;
        const line = session.stdoutBuffer.slice(0, newline);
        session.stdoutBuffer = session.stdoutBuffer.slice(newline + 1);
        if (!line.trim()) continue;
        const pending = session.pending;
        if (!pending) {
          this.#fault(session, 'BROWSER_SESSION_UNSOLICITED_OUTPUT', 'Persistent browser provider emitted output without an active request.');
          return;
        }
        session.pending = null;
        clearTimeout(pending.timer);
        pending.resolve(line);
        if (session.stdoutBuffer.trim()) {
          this.#fault(session, 'BROWSER_SESSION_UNSOLICITED_OUTPUT', 'Persistent browser provider emitted more than one response for a request.');
          return;
        }
      }
    });
    session.child.stderr.on('data', (chunk) => {
      session.stderrBytes += Buffer.byteLength(String(chunk));
      if (session.stderrBytes > MAX_BROWSER_STDERR_BYTES) {
        this.#fault(session, 'BROWSER_SESSION_STDERR_LIMIT', 'Persistent browser provider stderr exceeded the bounded session limit.');
      }
    });
    session.child.on('error', (error) => {
      session.exited = true;
      this.#failPending(session, 'BROWSER_SESSION_PROVIDER_SPAWN_FAILED', error?.message || 'Persistent browser provider could not be started.');
    });
    session.child.on('close', (code, signal) => {
      session.exited = true;
      session.exitCode = code;
      session.signal = signal;
      this.#failPending(session, 'BROWSER_SESSION_PROVIDER_EXITED', 'Persistent browser provider exited before completing the request.');
    });
    session.child.stdin.on('error', (error) => {
      this.#failPending(session, 'BROWSER_SESSION_STDIN_FAILED', error?.message || 'Persistent browser provider stdin failed.');
    });
  }

  async #start({ key, projectId, missionId, capability, browser, cwd, serviceSessionId, sourceHead, environment }) {
    if (this.sessions.size >= this.maxSessions) {
      throw Object.assign(new Error('Persistent browser session limit reached'), { code: 'BROWSER_SESSION_LIMIT_REACHED' });
    }
    const { env, home } = await createBrowserIsolatedEnvironment(browser.envAllowlist, environment);
    const [command, ...args] = browser.session.command;
    let child;
    try {
      child = spawn(command, args, {
        cwd,
        env,
        shell: false,
        detached: process.platform !== 'win32',
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe']
      });
    } catch (error) {
      await fs.rm(home, { recursive: true, force: true }).catch(() => {});
      throw Object.assign(new Error(`Persistent browser provider could not be started: ${error?.message || error}`), {
        code: 'BROWSER_SESSION_PROVIDER_SPAWN_FAILED'
      });
    }
    const timestamp = nowIso();
    const session = {
      id: randomId('browsersession'),
      key,
      projectId,
      missionId,
      capability,
      fingerprint: providerFingerprint(browser, cwd),
      serviceSessionId,
      sourceHead,
      child,
      home,
      stdoutBuffer: '',
      stderrBytes: 0,
      pending: null,
      fault: null,
      exited: false,
      exitCode: null,
      signal: null,
      observations: 0,
      startedAt: timestamp,
      lastUsedAt: timestamp
    };
    this.#attachProcess(session);
    this.sessions.set(key, session);
    return session;
  }

  async #request(session, browser, { cwd, serviceReadinessUrl, sourceHead }) {
    const prepared = await prepareBrowserValidationRequest(browser, { cwd, serviceReadinessUrl });
    if (session.exited || session.fault || session.child.exitCode !== null) {
      throw Object.assign(new Error(session.fault?.message || 'Persistent browser provider is not running.'), {
        code: session.fault?.code || 'BROWSER_SESSION_PROVIDER_EXITED'
      });
    }
    if (session.pending) {
      throw Object.assign(new Error('Persistent browser provider already has an active request'), { code: 'BROWSER_SESSION_BUSY' });
    }
    const requestId = randomId('browserrequest');
    const payload = {
      sessionContract: BROWSER_SESSION_CONTRACT,
      operation: 'observe',
      requestId,
      sourceHead,
      ...prepared.payload
    };
    const line = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (session.pending?.requestId !== requestId) return;
        session.pending = null;
        reject(Object.assign(new Error('Persistent browser provider exceeded its request timeout.'), { code: 'BROWSER_SESSION_TIMEOUT' }));
        terminateBrowserProviderTree(session.child);
      }, browser.session.timeoutMs);
      session.pending = { requestId, resolve, reject, timer };
      session.child.stdin.write(`${JSON.stringify(payload)}\n`, (error) => {
        if (!error || session.pending?.requestId !== requestId) return;
        session.pending = null;
        clearTimeout(timer);
        reject(Object.assign(new Error(error.message || 'Persistent browser provider stdin failed.'), { code: 'BROWSER_SESSION_STDIN_FAILED' }));
      });
    });
    let raw;
    try {
      raw = JSON.parse(line);
    } catch {
      throw Object.assign(new Error('Persistent browser provider returned invalid JSONL output.'), { code: 'BROWSER_SESSION_RESULT_INVALID' });
    }
    if (raw?.sessionContract !== BROWSER_SESSION_CONTRACT || raw?.requestId !== requestId) {
      throw Object.assign(new Error('Persistent browser provider response did not match the active request.'), { code: 'BROWSER_SESSION_RESULT_INVALID' });
    }
    const normalized = normalizeBrowserProviderResult(raw, prepared.normalizedBaseUrl);
    session.observations += 1;
    session.sourceHead = sourceHead;
    session.lastUsedAt = nowIso();
    return {
      ...normalized,
      failureCode: normalized.passed ? null : 'BROWSER_ASSERTION_FAILED',
      diagnostics: {
        exitCode: null,
        signal: null,
        timedOut: false,
        stdoutBytes: Buffer.byteLength(line),
        stderrBytes: session.stderrBytes,
        stdoutTruncated: false,
        stderrTruncated: false
      }
    };
  }

  async observe({ projectId, missionId, capability, browser, cwd, serviceReadinessUrl = null, serviceSessionId, sourceHead, environment = process.env }) {
    if (!browser?.session) return { used: false, reason: 'browser-session-disabled' };
    if (!projectId || !missionId || !capability || !serviceSessionId) {
      return { used: false, reason: 'persistent-live-service-required' };
    }
    const key = sessionKey(projectId, missionId, capability);
    return this.#withLock(key, async () => {
      let session = this.sessions.get(key) || null;
      const fingerprint = providerFingerprint(browser, cwd);
      let reused = Boolean(session);
      let restartReason = null;
      if (session && (session.fingerprint !== fingerprint || session.serviceSessionId !== serviceSessionId || session.exited || session.fault)) {
        restartReason = session.fingerprint !== fingerprint
          ? 'provider-config-changed'
          : session.serviceSessionId !== serviceSessionId
            ? 'service-session-changed'
            : 'provider-not-running';
        await this.#releaseKey(key, restartReason);
        session = null;
        reused = false;
      }
      try {
        if (!session) {
          session = await this.#start({ key, projectId, missionId, capability, browser, cwd, serviceSessionId, sourceHead, environment });
        }
        const previousHead = session.sourceHead;
        const result = await this.#request(session, browser, { cwd, serviceReadinessUrl, sourceHead });
        return {
          used: true,
          ok: true,
          result: {
            ...result,
            session: sessionSummary(session, {
              active: true,
              reused,
              restarted: restartReason !== null,
              restartReason,
              sourceChanged: Boolean(previousHead && previousHead !== sourceHead)
            })
          }
        };
      } catch (error) {
        const code = error?.code || 'BROWSER_SESSION_FAILED';
        await this.#releaseKey(key, code);
        return errorResult(code, error?.message || error, error?.details || null);
      }
    });
  }

  async #releaseKey(key, reason = 'released') {
    const session = this.sessions.get(key);
    if (!session) return null;
    this.sessions.delete(key);
    this.#failPending(session, 'BROWSER_SESSION_RELEASED', `Persistent browser session released (${reason}).`);
    terminateBrowserProviderTree(session.child);
    await waitForExit(session.child);
    await fs.rm(session.home, { recursive: true, force: true }).catch(() => {});
    return sessionSummary(session, { active: false, released: true, releaseReason: reason });
  }

  async releaseCapability({ projectId, missionId, capability, reason = 'capability-released' } = {}) {
    if (!projectId || !missionId || !capability) return null;
    const key = sessionKey(projectId, missionId, capability);
    return this.#withLock(key, () => this.#releaseKey(key, reason));
  }

  async releaseMission({ missionId, reason = 'mission-finished' } = {}) {
    const keys = [...this.sessions.entries()]
      .filter(([, session]) => session.missionId === missionId)
      .map(([key]) => key);
    const released = [];
    for (const key of keys) {
      const item = await this.#withLock(key, () => this.#releaseKey(key, reason));
      if (item) released.push(item);
    }
    return released;
  }

  async releaseAll({ reason = 'runtime-cleanup' } = {}) {
    const keys = [...this.sessions.keys()];
    const released = [];
    for (const key of keys) {
      const item = await this.#withLock(key, () => this.#releaseKey(key, reason));
      if (item) released.push(item);
    }
    return released;
  }
}
