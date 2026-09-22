import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { electronError } from './electron-validation-contract.mjs';
import { signalProcessTree } from './process-lifecycle-authority.mjs';

const BRIDGE_CONTRACT = 'veteran-electron-bridge-v1';
const MAX_BRIDGE_MESSAGE_BYTES = 256 * 1024;
const FORCE_KILL_AFTER_MS = 3_000;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function killProcessTree(pid, signal = 'SIGTERM') {
  return signalProcessTree(pid, signal).signalled;
}

function appendBounded(current, chunk, max = 32 * 1024) {
  const next = `${current}${String(chunk || '')}`;
  return next.length <= max ? next : next.slice(next.length - max);
}

export async function launchElectronBridge({ executablePath, args, cwd, env, timeout, chromiumSandbox }) {
  const bridgePath = fileURLToPath(new URL('./electron-validation-bridge.cjs', import.meta.url));
  const launchArgs = ['-r', bridgePath, ...(chromiumSandbox ? [] : ['--no-sandbox']), ...args];
  let child;
  try {
    child = spawn(executablePath, launchArgs, {
      cwd,
      env,
      shell: false,
      detached: process.platform !== 'win32',
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe', 'pipe', 'pipe']
    });
  } catch (error) {
    throw electronError('Electron process could not be started', 'ELECTRON_PROCESS_START_FAILED', { code: error?.code || null });
  }

  const requestPipe = child.stdio[3];
  const responsePipe = child.stdio[4];
  let stderrTail = '';
  let stdoutTail = '';
  let settled = false;
  let responseBuffer = '';
  let sequence = 0;
  const pending = new Map();
  let readyResolve;
  let readyReject;
  const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; });

  child.stderr?.setEncoding('utf8');
  child.stdout?.setEncoding('utf8');
  child.stderr?.on('data', (chunk) => { stderrTail = appendBounded(stderrTail, chunk); });
  child.stdout?.on('data', (chunk) => { stdoutTail = appendBounded(stdoutTail, chunk); });

  const rejectPending = (error) => {
    for (const entry of pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(error);
    }
    pending.clear();
  };
  const processError = (code, signal) => electronError('Electron process exited before validation completed', 'ELECTRON_PROCESS_EXITED', {
    exitCode: Number.isInteger(code) ? code : null,
    signal: signal || null,
    stderrObserved: Boolean(stderrTail),
    stdoutObserved: Boolean(stdoutTail)
  });

  child.once('error', (error) => {
    const wrapped = electronError('Electron process emitted a spawn error', 'ELECTRON_PROCESS_START_FAILED', { code: error?.code || null });
    readyReject(wrapped);
    rejectPending(wrapped);
  });
  child.once('exit', (code, signal) => {
    if (settled) return;
    settled = true;
    const error = processError(code, signal);
    readyReject(error);
    rejectPending(error);
  });

  responsePipe?.setEncoding('utf8');
  responsePipe?.on('data', (chunk) => {
    responseBuffer += chunk;
    if (responseBuffer.length > MAX_BRIDGE_MESSAGE_BYTES * 2) responseBuffer = responseBuffer.slice(-MAX_BRIDGE_MESSAGE_BYTES);
    for (;;) {
      const newline = responseBuffer.indexOf('\n');
      if (newline === -1) break;
      const line = responseBuffer.slice(0, newline);
      responseBuffer = responseBuffer.slice(newline + 1);
      if (!line || Buffer.byteLength(line) > MAX_BRIDGE_MESSAGE_BYTES) continue;
      let message;
      try { message = JSON.parse(line); } catch { continue; }
      if (message?.type === 'ready' && message.contract === BRIDGE_CONTRACT) { readyResolve(true); continue; }
      if (!Number.isInteger(message?.id)) continue;
      const entry = pending.get(message.id);
      if (!entry) continue;
      pending.delete(message.id);
      clearTimeout(entry.timer);
      entry.resolve(message);
    }
  });
  responsePipe?.once('error', (error) => rejectPending(electronError('Electron bridge response pipe failed', 'ELECTRON_BRIDGE_FAILED', { code: error?.code || null })));
  requestPipe?.once('error', (error) => rejectPending(electronError('Electron bridge request pipe failed', 'ELECTRON_BRIDGE_FAILED', { code: error?.code || null })));

  const readyTimer = setTimeout(() => readyReject(electronError('Electron bridge did not become ready before timeout', 'ELECTRON_BRIDGE_TIMEOUT')), Math.max(250, Math.min(timeout, 15_000)));
  ready.finally(() => clearTimeout(readyTimer)).catch(() => {});

  async function request(operation, payload = {}, requestTimeout = 10_000) {
    await ready;
    if (settled) throw electronError('Electron process is no longer running', 'ELECTRON_PROCESS_EXITED');
    const id = ++sequence;
    const body = `${JSON.stringify({ id, operation, ...payload })}\n`;
    if (Buffer.byteLength(body) > MAX_BRIDGE_MESSAGE_BYTES) throw electronError('Electron bridge request exceeds bounded size', 'ELECTRON_BRIDGE_MESSAGE_TOO_LARGE');
    const response = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(electronError(`Electron bridge operation ${operation} timed out`, 'ELECTRON_BRIDGE_TIMEOUT'));
      }, Math.max(1, requestTimeout));
      pending.set(id, { resolve, reject, timer });
    });
    requestPipe.write(body, 'utf8', (error) => {
      if (!error) return;
      const entry = pending.get(id);
      if (!entry) return;
      pending.delete(id);
      clearTimeout(entry.timer);
      entry.reject(electronError('Electron bridge request could not be written', 'ELECTRON_BRIDGE_FAILED', { code: error?.code || null }));
    });
    return response;
  }

  async function close() {
    if (settled) return;
    try { await request('quit', {}, 1_000); } catch {}
    const exited = new Promise((resolve) => child.once('exit', resolve));
    await Promise.race([exited, delay(1_000)]);
    if (settled) return;
    killProcessTree(child.pid, 'SIGTERM');
    await Promise.race([exited, delay(FORCE_KILL_AFTER_MS)]);
    if (!settled) killProcessTree(child.pid, 'SIGKILL');
  }

  try {
    await ready;
    return {
      processId: child.pid,
      async listSurfaces(requestTimeout = 10_000) {
        const response = await request('inventory', {}, requestTimeout);
        if (!response?.ok) throw electronError('Electron surface inventory failed', response?.code || 'ELECTRON_BRIDGE_FAILED');
        return response.inventory || { windows: [], webviews: [] };
      },
      async command(target, operation, params = {}, requestTimeout = 10_000) {
        return request(operation, { target, params }, requestTimeout);
      },
      close
    };
  } catch (error) {
    killProcessTree(child.pid, 'SIGTERM');
    await delay(100);
    killProcessTree(child.pid, 'SIGKILL');
    throw error;
  }
}

export function nativeElectronAutomation() {
  return { launch: launchElectronBridge };
}
