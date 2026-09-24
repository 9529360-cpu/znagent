import fs from 'node:fs/promises';
import path from 'node:path';
import { PROCESS_LIFECYCLE_STATE, probeProcess } from './process-lifecycle-authority.mjs';
import { nowIso, randomId, sha256 } from './util.mjs';

function errorWithCode(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function busyError({ missionId, operation, backendKind, owner = null, reason = 'lease-held' }) {
  return errorWithCode(
    'Cannot reconcile or start mission execution while another runtime still owns the mission execution lease.',
    'MISSION_EXECUTION_ACTIVE',
    { missionId, operation, backendKind, owner, reason }
  );
}

function advisoryKeys(instanceKey, missionId) {
  const digest = Buffer.from(sha256(`veteran-mission-execution\u0000${instanceKey}\u0000${missionId}`), 'hex');
  return [digest.readInt32BE(0), digest.readInt32BE(4)];
}

async function readLocalLease(lockPath) {
  try {
    const [raw, stat] = await Promise.all([fs.readFile(lockPath, 'utf8'), fs.stat(lockPath)]);
    try {
      return { exists: true, owner: JSON.parse(raw), malformed: false, ageMs: Math.max(0, Date.now() - stat.mtimeMs) };
    } catch {
      return { exists: true, owner: null, malformed: true, ageMs: Math.max(0, Date.now() - stat.mtimeMs) };
    }
  } catch (error) {
    if (error?.code === 'ENOENT') return { exists: false, owner: null, malformed: false, ageMs: 0 };
    throw error;
  }
}

export class MissionExecutionLeaseManager {
  constructor({ store }) {
    if (!store) throw new Error('MissionExecutionLeaseManager requires a state store');
    this.store = store;
  }

  async acquire({ missionId, operation = 'mission-execute' } = {}) {
    if (typeof missionId !== 'string' || !missionId.trim()) {
      throw errorWithCode('Mission execution lease requires a non-empty missionId', 'MISSION_ID_REQUIRED');
    }
    if (this.store.backendKind === 'local-json') return this.#acquireLocal({ missionId, operation });
    if (this.store.backendKind === 'postgres') return this.#acquirePostgres({ missionId, operation });
    throw errorWithCode(
      `State backend ${this.store.backendKind || 'unknown'} does not provide a mission execution lease implementation`,
      'MISSION_EXECUTION_LEASE_UNSUPPORTED',
      { missionId, operation, backendKind: this.store.backendKind || null }
    );
  }

  async #acquireLocal({ missionId, operation }) {
    if (typeof this.store.acquireLock !== 'function' || typeof this.store.root !== 'string') {
      throw errorWithCode('Local JSON backend does not expose the required lock/root authority', 'MISSION_EXECUTION_LEASE_UNSUPPORTED', {
        missionId,
        operation,
        backendKind: this.store.backendKind || null
      });
    }

    const store = this.store;
    const leaseDir = path.join(store.root, 'execution-leases');
    const lockPath = path.join(leaseDir, `mission-${sha256(missionId).slice(0, 40)}.lock`);
    const token = randomId('missionlease');
    const owner = { pid: process.pid, token, missionId, acquiredAt: nowIso() };
    await fs.mkdir(leaseDir, { recursive: true, mode: 0o700 });

    const releaseStateLock = await store.acquireLock();
    try {
      const current = await readLocalLease(lockPath);
      if (current.exists) {
        const ownerPid = current.owner?.pid;
        const ownerProbe = Number.isInteger(ownerPid) ? probeProcess(ownerPid) : null;
        const ownerMissing = ownerProbe?.state === PROCESS_LIFECYCLE_STATE.MISSING;
        const malformedStale = current.malformed && current.ageMs > (store.lockStaleMs || 30_000);
        if (ownerMissing || malformedStale) {
          await fs.unlink(lockPath).catch((error) => {
            if (error?.code !== 'ENOENT') throw error;
          });
        } else {
          throw busyError({
            missionId,
            operation,
            backendKind: 'local-json',
            owner: current.owner ? { pid: ownerPid || null, acquiredAt: current.owner.acquiredAt || null } : null,
            reason: current.malformed
              ? 'lease-metadata-unreadable'
              : ownerProbe?.state === PROCESS_LIFECYCLE_STATE.UNKNOWN
                ? 'lease-owner-probe-unknown'
                : 'lease-held'
          });
        }
      }

      let handle;
      try {
        handle = await fs.open(lockPath, 'wx', 0o600);
        await handle.writeFile(JSON.stringify(owner));
        await handle.sync();
      } catch (error) {
        if (error?.code === 'EEXIST') throw busyError({ missionId, operation, backendKind: 'local-json', reason: 'lease-raced' });
        throw error;
      } finally {
        await handle?.close().catch(() => {});
      }
    } finally {
      await releaseStateLock();
    }

    let released = false;
    return {
      missionId,
      backendKind: 'local-json',
      leaseId: token,
      release: async () => {
        if (released) return;
        released = true;
        const releaseLock = await store.acquireLock();
        try {
          const current = await readLocalLease(lockPath);
          if (!current.exists || current.owner?.token !== token) return;
          await fs.unlink(lockPath).catch((error) => {
            if (error?.code !== 'ENOENT') throw error;
          });
        } finally {
          await releaseLock();
        }
      }
    };
  }

  async #acquirePostgres({ missionId, operation }) {
    if (typeof this.store.connectionString !== 'string' || typeof this.store.instanceKey !== 'string') {
      throw errorWithCode('PostgreSQL backend does not expose connectionString/instanceKey lease authority', 'MISSION_EXECUTION_LEASE_UNSUPPORTED', {
        missionId,
        operation,
        backendKind: this.store.backendKind || null
      });
    }

    const module = await import('pg');
    const Client = module.Client || module.default?.Client;
    if (typeof Client !== 'function') {
      throw errorWithCode('Installed pg package does not expose Client for mission execution leasing', 'POSTGRES_DRIVER_INVALID');
    }
    const client = new Client({
      connectionString: this.store.connectionString,
      application_name: 'veteran-engineer-execution-lease'
    });
    await client.connect();
    const [keyA, keyB] = advisoryKeys(this.store.instanceKey, missionId);
    try {
      const result = await client.query('SELECT pg_try_advisory_lock($1::integer, $2::integer) AS acquired', [keyA, keyB]);
      if (result.rows?.[0]?.acquired !== true) {
        await client.end().catch(() => {});
        throw busyError({ missionId, operation, backendKind: 'postgres', reason: 'advisory-lock-held' });
      }
    } catch (error) {
      if (error?.code === 'MISSION_EXECUTION_ACTIVE') throw error;
      await client.end().catch(() => {});
      throw error;
    }

    let released = false;
    return {
      missionId,
      backendKind: 'postgres',
      leaseId: `${keyA}:${keyB}`,
      release: async () => {
        if (released) return;
        released = true;
        try {
          await client.query('SELECT pg_advisory_unlock($1::integer, $2::integer)', [keyA, keyB]);
        } catch {
          // Closing the dedicated session below is the final lease-release boundary.
        } finally {
          await client.end().catch(() => {});
        }
      }
    };
  }
}
