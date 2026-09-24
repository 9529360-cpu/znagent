import { spawnSync } from 'node:child_process';

export const PROCESS_LIFECYCLE_STATE = Object.freeze({
  ALIVE: 'alive',
  MISSING: 'missing',
  UNKNOWN: 'unknown',
  UNSUPPORTED: 'unsupported'
});

export function validProcessId(pid) {
  return Number.isInteger(pid) && pid > 0;
}

function normalizeProbeError(error) {
  if (error?.code === 'ESRCH') return PROCESS_LIFECYCLE_STATE.MISSING;
  if (error?.code === 'EPERM') return PROCESS_LIFECYCLE_STATE.ALIVE;
  return PROCESS_LIFECYCLE_STATE.UNKNOWN;
}

export function probeProcess(pid, {
  kill = process.kill
} = {}) {
  if (!validProcessId(pid)) {
    return { state: PROCESS_LIFECYCLE_STATE.MISSING, pid, scope: 'process', reason: 'invalid-pid' };
  }
  try {
    kill(pid, 0);
    return { state: PROCESS_LIFECYCLE_STATE.ALIVE, pid, scope: 'process', reason: null };
  } catch (error) {
    return {
      state: normalizeProbeError(error),
      pid,
      scope: 'process',
      reason: error?.code || 'PROCESS_PROBE_FAILED'
    };
  }
}

export function probeProcessGroup(pid, {
  platform = process.platform,
  kill = process.kill
} = {}) {
  if (!validProcessId(pid)) {
    return { state: PROCESS_LIFECYCLE_STATE.MISSING, pid, scope: 'group', reason: 'invalid-pid' };
  }
  if (platform === 'win32') {
    return { state: PROCESS_LIFECYCLE_STATE.UNSUPPORTED, pid, scope: 'group', reason: 'platform' };
  }
  try {
    kill(-pid, 0);
    return { state: PROCESS_LIFECYCLE_STATE.ALIVE, pid, scope: 'group', reason: null };
  } catch (error) {
    return {
      state: normalizeProbeError(error),
      pid,
      scope: 'group',
      reason: error?.code || 'PROCESS_GROUP_PROBE_FAILED'
    };
  }
}

export function signalProcessTree(pid, signal = 'SIGTERM', {
  platform = process.platform,
  kill = process.kill,
  runSync = spawnSync
} = {}) {
  if (!validProcessId(pid)) {
    return { signalled: false, pid, signal, scope: 'none', reason: 'invalid-pid' };
  }

  if (platform === 'win32') {
    const args = ['/PID', String(pid), '/T'];
    if (signal === 'SIGKILL') args.push('/F');
    let result;
    try {
      result = runSync('taskkill', args, { stdio: 'ignore', windowsHide: true });
    } catch (error) {
      return {
        signalled: false,
        pid,
        signal,
        scope: 'tree',
        reason: error?.code || 'TASKKILL_FAILED'
      };
    }
    return {
      signalled: result?.status === 0,
      pid,
      signal,
      scope: 'tree',
      reason: result?.status === 0 ? null : `taskkill-status-${String(result?.status ?? 'unknown')}`
    };
  }

  try {
    kill(-pid, signal);
    return { signalled: true, pid, signal, scope: 'group', reason: null };
  } catch (groupError) {
    try {
      kill(pid, signal);
      return {
        signalled: true,
        pid,
        signal,
        scope: 'process',
        reason: groupError?.code ? `group-${groupError.code}` : 'group-signal-failed'
      };
    } catch (processError) {
      return {
        signalled: false,
        pid,
        signal,
        scope: 'none',
        reason: processError?.code || groupError?.code || 'PROCESS_SIGNAL_FAILED'
      };
    }
  }
}

export function processGroupMayBeAlive(probe) {
  return probe?.state !== PROCESS_LIFECYCLE_STATE.MISSING;
}
