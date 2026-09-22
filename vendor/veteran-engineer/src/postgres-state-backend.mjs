import { createRequire } from 'node:module';
import path from 'node:path';
import { STATE_SCHEMA_VERSION } from './constants.mjs';
import { STATE_BACKEND_CONTRACT } from './state-backend-contract.mjs';
import { STATE_BACKEND_TRANSACTION_CONTRACT, stateRevisionConflict } from './state-backend-transaction-contract.mjs';
import { STATE_BACKEND_DURABILITY_CONTRACT, STATE_COMMIT_AUDIT_OUTCOME_UNKNOWN } from './state-backend-durability-contract.mjs';
import { emptyState } from './state-store.mjs';
import { clone, ensureDir, nowIso, randomId, sha256, stableStringify } from './util.mjs';

export const POSTGRES_DRIVER_VERSION = '8.23.0';
const STATE_TABLE = 'veteran_engineer_state';
const AUDIT_TABLE = 'veteran_engineer_audit';
const require = createRequire(import.meta.url);

function errorWithCode(message, code, details = null) {
  const error = new Error(message);
  error.code = code;
  if (details) error.details = details;
  return error;
}

function auditIntegrityError(details) {
  return errorWithCode(`PostgreSQL audit chain is not safe to use: ${details.reason || 'invalid audit chain'}`, 'STATE_AUDIT_INTEGRITY_FAILURE', details);
}

function unknownCommitError(commit, cause) {
  const error = errorWithCode(
    `PostgreSQL commit ${commit.id} outcome could not be reconciled; replay is unsafe until connectivity returns`,
    STATE_COMMIT_AUDIT_OUTCOME_UNKNOWN,
    {
      stateCommitId: commit.id,
      eventType: commit.eventType,
      commitOutcome: 'unknown',
      causeCode: cause?.code || 'ERROR',
      causeMessage: cause?.message || String(cause)
    }
  );
  error.stateCommitted = 'unknown';
  error.auditOutcome = 'unknown';
  error.requiresReconciliation = true;
  error.cause = cause;
  return error;
}

function attachCommit(state, eventType, auditSummary) {
  state.runtime ||= {};
  state.runtime.durability ||= {};
  const commit = {
    id: randomId('statecommit'),
    at: state.updatedAt || nowIso(),
    eventType,
    auditSummary: clone(auditSummary || {})
  };
  state.runtime.durability.lastStateCommit = commit;
  return commit;
}

function auditMaterial(entry) {
  const value = { seq: entry.seq, at: entry.at, type: entry.type, summary: entry.summary, prevHash: entry.prevHash };
  if (entry.stateCommitId) value.stateCommitId = entry.stateCommitId;
  return value;
}

async function loadPoolClass() {
  let pkg;
  try {
    pkg = require('pg/package.json');
  } catch (cause) {
    const error = errorWithCode(
      `PostgreSQL state backend requires pg@${POSTGRES_DRIVER_VERSION}; install it in the shared Veteran runtime before selecting postgres`,
      'POSTGRES_DRIVER_REQUIRED',
      { requiredVersion: POSTGRES_DRIVER_VERSION }
    );
    error.cause = cause;
    throw error;
  }
  if (pkg.version !== POSTGRES_DRIVER_VERSION) {
    throw errorWithCode(
      `PostgreSQL driver version mismatch: expected pg@${POSTGRES_DRIVER_VERSION}, found pg@${pkg.version}`,
      'POSTGRES_DRIVER_VERSION_MISMATCH',
      { expected: POSTGRES_DRIVER_VERSION, actual: pkg.version }
    );
  }
  const module = await import('pg');
  const Pool = module.Pool || module.default?.Pool;
  if (typeof Pool !== 'function') throw errorWithCode('Installed pg package does not expose Pool', 'POSTGRES_DRIVER_INVALID');
  return Pool;
}

export class PostgresStateBackend {
  constructor({ root, connectionString, instanceKey, poolMax = 4, faultInjector = null } = {}) {
    if (!root) throw errorWithCode('PostgreSQL state backend requires an execution-local root', 'POSTGRES_STATE_BACKEND_CONFIG_INVALID');
    if (typeof connectionString !== 'string' || !connectionString.trim()) throw errorWithCode('PostgreSQL state backend requires a non-empty connectionString', 'POSTGRES_STATE_BACKEND_CONFIG_INVALID');
    if (typeof instanceKey !== 'string' || !instanceKey.trim()) throw errorWithCode('PostgreSQL state backend requires an explicit non-empty instanceKey', 'POSTGRES_STATE_BACKEND_CONFIG_INVALID');
    if (!Number.isInteger(poolMax) || poolMax < 1 || poolMax > 32) throw errorWithCode('PostgreSQL poolMax must be an integer between 1 and 32', 'POSTGRES_STATE_BACKEND_CONFIG_INVALID');
    this.root = path.resolve(root);
    this.artifactsDir = path.join(this.root, 'artifacts');
    this.worktreesDir = path.join(this.root, 'worktrees');
    this.connectionString = connectionString;
    this.instanceKey = instanceKey.trim();
    this.poolMax = poolMax;
    this.faultInjector = typeof faultInjector === 'function' ? faultInjector : null;
    this.backendContract = STATE_BACKEND_CONTRACT;
    this.backendKind = 'postgres';
    this.transactionContract = STATE_BACKEND_TRANSACTION_CONTRACT;
    this.durabilityContract = STATE_BACKEND_DURABILITY_CONTRACT;
    this.pool = null;
  }

  async init() {
    await ensureDir(this.root);
    await ensureDir(this.artifactsDir);
    await ensureDir(this.worktreesDir);
    const Pool = await loadPoolClass();
    this.pool ||= new Pool({ connectionString: this.connectionString, max: this.poolMax, application_name: 'veteran-engineer' });
    await this.#ensureSchema();
    await this.#bootstrap();
    await this.reconcilePendingAudit();
    await this.#reconcileStartedRequests();
    return this;
  }

  async close() {
    const pool = this.pool;
    this.pool = null;
    if (pool) await pool.end();
  }

  async read() {
    const result = await this.#pool().query(`SELECT schema_version, revision::text AS revision, state FROM ${STATE_TABLE} WHERE instance_key = $1`, [this.instanceKey]);
    if (result.rowCount !== 1) throw errorWithCode(`PostgreSQL state row is missing for instance ${this.instanceKey}`, 'POSTGRES_STATE_MISSING');
    return clone(this.#validateStateRow(result.rows[0]).state);
  }

  async readSnapshot() {
    const result = await this.#pool().query(`SELECT schema_version, revision::text AS revision, state FROM ${STATE_TABLE} WHERE instance_key = $1`, [this.instanceKey]);
    if (result.rowCount !== 1) throw errorWithCode(`PostgreSQL state row is missing for instance ${this.instanceKey}`, 'POSTGRES_STATE_MISSING');
    const row = this.#validateStateRow(result.rows[0]);
    return { state: clone(row.state), revision: row.revision };
  }

  async transaction(eventType, mutator, auditSummary = {}) {
    return this.#mutate({ eventType, mutator, auditSummary });
  }

  async compareAndCommit(expectedRevision, eventType, mutator, auditSummary = {}) {
    if (typeof expectedRevision !== 'string' || !expectedRevision) throw errorWithCode('compareAndCommit requires a non-empty expected revision', 'STATE_REVISION_REQUIRED');
    return this.#mutate({ expectedRevision, eventType, mutator, auditSummary });
  }

  async recordTimeline(event) {
    return this.transaction('runtime_timeline', (state) => {
      state.runtime.timeline.push({ ...event, at: event.at || nowIso() });
      if (state.runtime.timeline.length > 2000) state.runtime.timeline.splice(0, state.runtime.timeline.length - 2000);
    }, { type: event.type, missionId: event.missionId, taskId: event.taskId });
  }

  async verifyAudit() {
    const client = await this.#pool().connect();
    try {
      await client.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY');
      const stateResult = await client.query(`SELECT schema_version, revision::text AS revision, state FROM ${STATE_TABLE} WHERE instance_key = $1`, [this.instanceKey]);
      if (stateResult.rowCount !== 1) {
        await client.query('ROLLBACK');
        return { ok: false, entries: 0, head: null, reason: 'state-row-missing' };
      }
      const state = this.#validateStateRow(stateResult.rows[0]).state;
      const inspection = await this.#inspectAudit(client);
      await client.query('COMMIT');
      if (!inspection.ok) return inspection;
      return this.#verifyLatestCommit(state, inspection);
    } catch (error) {
      await client.query('ROLLBACK').catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async reconcilePendingAudit() {
    const client = await this.#pool().connect();
    try {
      await client.query('BEGIN');
      await this.#lockInstance(client);
      const row = await this.#readStateForUpdate(client);
      const result = await this.#reconcileLocked(client, row.state);
      await client.query('COMMIT');
      return result;
    } catch (error) {
      await client.query('ROLLBACK').catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async #mutate({ expectedRevision = null, eventType, mutator, auditSummary }) {
    if (typeof eventType !== 'string' || !eventType) throw errorWithCode('State transaction requires a non-empty eventType', 'POSTGRES_STATE_BACKEND_CONFIG_INVALID');
    if (typeof mutator !== 'function') throw errorWithCode('State transaction requires a mutator function', 'POSTGRES_STATE_BACKEND_CONFIG_INVALID');
    const client = await this.#pool().connect();
    let commit = null;
    let result;
    let commitSent = false;
    let uncertain = null;
    try {
      await client.query('BEGIN');
      await this.#lockInstance(client);
      const locked = await this.#readStateForUpdate(client);
      await this.#reconcileLocked(client, locked.state);
      if (expectedRevision !== null && expectedRevision !== locked.revision) {
        throw stateRevisionConflict({ expectedRevision, actualRevision: locked.revision });
      }
      const working = clone(locked.state);
      result = await mutator(working);
      working.updatedAt = nowIso();
      commit = attachCommit(working, eventType, auditSummary);
      const nextRevision = (BigInt(locked.revision) + 1n).toString();
      const updated = await client.query(
        `UPDATE ${STATE_TABLE} SET revision = $2::bigint, state = $3::jsonb, updated_at = $4 WHERE instance_key = $1 AND revision = $5::bigint`,
        [this.instanceKey, nextRevision, JSON.stringify(working), working.updatedAt, locked.revision]
      );
      if (updated.rowCount !== 1) throw stateRevisionConflict({ expectedRevision: locked.revision, actualRevision: 'changed-during-locked-update' });
      await this.#appendAudit(client, commit.eventType, commit.auditSummary, { stateCommitId: commit.id, at: commit.at });
      commitSent = true;
      await client.query('COMMIT');
      await this.#injectFault('after_db_commit_before_ack', commit);
    } catch (error) {
      if (!commitSent) {
        await client.query('ROLLBACK').catch(() => {});
        throw error;
      }
      uncertain = error;
    } finally {
      client.release(uncertain || undefined);
    }
    if (uncertain) return this.#resolveCommitOutcome(commit, result, uncertain);
    return result;
  }

  async #resolveCommitOutcome(commit, result, cause) {
    try {
      const client = await this.#pool().connect();
      try {
        await client.query('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY');
        const inspection = await this.#inspectAudit(client);
        if (!inspection.ok) throw auditIntegrityError(inspection);
        const matches = inspection.items.filter((entry) => entry.stateCommitId === commit.id);
        await client.query('COMMIT');
        if (matches.length === 1) {
          this.#assertAuditMatchesCommit(matches[0], commit);
          return result;
        }
        if (matches.length > 1) throw auditIntegrityError({ reason: 'state-commit-audit-duplicate', stateCommitId: commit.id });
        const error = errorWithCode(`PostgreSQL transaction ${commit.id} was not committed`, 'POSTGRES_COMMIT_NOT_APPLIED', { stateCommitId: commit.id, causeCode: cause?.code || 'ERROR' });
        error.cause = cause;
        throw error;
      } catch (error) {
        await client.query('ROLLBACK').catch(() => {});
        throw error;
      } finally {
        client.release();
      }
    } catch (error) {
      if (error?.code === 'POSTGRES_COMMIT_NOT_APPLIED' || error?.code === 'STATE_AUDIT_INTEGRITY_FAILURE') throw error;
      throw unknownCommitError(commit, error || cause);
    }
  }

  async #ensureSchema() {
    const client = await this.#pool().connect();
    try {
      await client.query('BEGIN');
      await client.query('SELECT pg_advisory_xact_lock(hashtext($1), $2::int)', ['veteran-engineer:schema', STATE_SCHEMA_VERSION]);
      await client.query(`CREATE TABLE IF NOT EXISTS ${STATE_TABLE} (
        instance_key TEXT PRIMARY KEY,
        schema_version INTEGER NOT NULL,
        revision BIGINT NOT NULL CHECK (revision >= 1),
        state JSONB NOT NULL,
        updated_at TEXT NOT NULL
      )`);
      await client.query(`CREATE TABLE IF NOT EXISTS ${AUDIT_TABLE} (
        instance_key TEXT NOT NULL,
        seq BIGINT NOT NULL CHECK (seq >= 1),
        at TEXT NOT NULL,
        type TEXT NOT NULL,
        summary JSONB NOT NULL,
        prev_hash TEXT NULL,
        state_commit_id TEXT NULL,
        hash TEXT NOT NULL,
        PRIMARY KEY (instance_key, seq),
        UNIQUE (instance_key, state_commit_id)
      )`);
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK').catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async #bootstrap() {
    const client = await this.#pool().connect();
    try {
      await client.query('BEGIN');
      await this.#lockInstance(client);
      const existing = await client.query(`SELECT schema_version, revision::text AS revision, state FROM ${STATE_TABLE} WHERE instance_key = $1 FOR UPDATE`, [this.instanceKey]);
      if (existing.rowCount === 0) {
        const state = emptyState();
        const summary = { schemaVersion: STATE_SCHEMA_VERSION };
        const commit = attachCommit(state, 'state_initialized', summary);
        await client.query(
          `INSERT INTO ${STATE_TABLE} (instance_key, schema_version, revision, state, updated_at) VALUES ($1, $2, 1, $3::jsonb, $4)`,
          [this.instanceKey, STATE_SCHEMA_VERSION, JSON.stringify(state), state.updatedAt]
        );
        await this.#appendAudit(client, commit.eventType, commit.auditSummary, { stateCommitId: commit.id, at: commit.at });
      } else {
        this.#validateStateRow(existing.rows[0]);
      }
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK').catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async #reconcileStartedRequests() {
    const client = await this.#pool().connect();
    try {
      await client.query('BEGIN');
      await this.#lockInstance(client);
      const locked = await this.#readStateForUpdate(client);
      await this.#reconcileLocked(client, locked.state);
      const working = clone(locked.state);
      let count = 0;
      for (const request of Object.values(working.requests || {})) {
        if (request.status === 'started') {
          request.status = 'unknown';
          request.reconciledAt = nowIso();
          count += 1;
        }
      }
      if (count === 0) {
        await client.query('COMMIT');
        return;
      }
      working.updatedAt = nowIso();
      const commit = attachCommit(working, 'request_outcomes_reconciled_unknown', { count });
      const nextRevision = (BigInt(locked.revision) + 1n).toString();
      await client.query(
        `UPDATE ${STATE_TABLE} SET revision = $2::bigint, state = $3::jsonb, updated_at = $4 WHERE instance_key = $1`,
        [this.instanceKey, nextRevision, JSON.stringify(working), working.updatedAt]
      );
      await this.#appendAudit(client, commit.eventType, commit.auditSummary, { stateCommitId: commit.id, at: commit.at });
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK').catch(() => {});
      throw error;
    } finally {
      client.release();
    }
  }

  async #lockInstance(client) {
    await client.query('SELECT pg_advisory_xact_lock(hashtext($1))', [`veteran-engineer:${this.instanceKey}`]);
  }

  async #readStateForUpdate(client) {
    const result = await client.query(`SELECT schema_version, revision::text AS revision, state FROM ${STATE_TABLE} WHERE instance_key = $1 FOR UPDATE`, [this.instanceKey]);
    if (result.rowCount !== 1) throw errorWithCode(`PostgreSQL state row is missing for instance ${this.instanceKey}`, 'POSTGRES_STATE_MISSING');
    return this.#validateStateRow(result.rows[0]);
  }

  #validateStateRow(row) {
    const state = typeof row.state === 'string' ? JSON.parse(row.state) : row.state;
    if (Number(row.schema_version) !== STATE_SCHEMA_VERSION || state?.schemaVersion !== STATE_SCHEMA_VERSION) {
      throw errorWithCode(`Unsupported state schema: ${state?.schemaVersion}`, 'STATE_SCHEMA_UNSUPPORTED');
    }
    return { revision: String(row.revision), state };
  }

  async #inspectAudit(client) {
    const result = await client.query(
      `SELECT seq::text AS audit_seq, at, type, summary, prev_hash, state_commit_id, hash FROM ${AUDIT_TABLE} WHERE instance_key = $1 ORDER BY ${AUDIT_TABLE}.seq ASC`,
      [this.instanceKey]
    );
    const items = [];
    let prevHash = null;
    let expectedSeq = 0n;
    for (const row of result.rows) {
      expectedSeq += 1n;
      const seq = BigInt(row.audit_seq);
      if (seq !== expectedSeq || row.prev_hash !== prevHash) return { ok: false, entries: items.length, head: prevHash, reason: 'chain-link-mismatch', entry: row };
      const entry = {
        seq: Number(seq),
        at: row.at,
        type: row.type,
        summary: row.summary,
        prevHash: row.prev_hash,
        stateCommitId: row.state_commit_id || null,
        hash: row.hash
      };
      const expected = sha256(stableStringify(auditMaterial(entry)));
      if (entry.hash !== expected) return { ok: false, entries: items.length, head: prevHash, reason: 'hash-mismatch', entry };
      prevHash = entry.hash;
      items.push(entry);
    }
    return { ok: true, entries: items.length, head: prevHash, items };
  }

  #verifyLatestCommit(state, inspection) {
    const commit = state.runtime?.durability?.lastStateCommit;
    if (!commit) return { ok: true, entries: inspection.entries, head: inspection.head };
    const matches = inspection.items.filter((entry) => entry.stateCommitId === commit.id);
    if (matches.length === 0) return { ok: false, entries: inspection.entries, head: inspection.head, reason: 'state-commit-audit-missing', stateCommitId: commit.id };
    if (matches.length > 1) return { ok: false, entries: inspection.entries, head: inspection.head, reason: 'state-commit-audit-duplicate', stateCommitId: commit.id };
    try {
      this.#assertAuditMatchesCommit(matches[0], commit);
      return { ok: true, entries: inspection.entries, head: inspection.head };
    } catch (error) {
      return { ok: false, entries: inspection.entries, head: inspection.head, reason: 'state-commit-audit-mismatch', stateCommitId: commit.id };
    }
  }

  #assertAuditMatchesCommit(entry, commit) {
    if (entry.type !== commit.eventType || entry.at !== commit.at || stableStringify(entry.summary) !== stableStringify(commit.auditSummary)) {
      throw auditIntegrityError({ reason: 'state-commit-audit-mismatch', stateCommitId: commit.id, entry });
    }
  }

  async #reconcileLocked(client, state) {
    const inspection = await this.#inspectAudit(client);
    if (!inspection.ok) throw auditIntegrityError(inspection);
    const commit = state.runtime?.durability?.lastStateCommit;
    if (!commit) return { ok: true, status: 'no-state-commit-marker', stateCommitId: null };
    const matches = inspection.items.filter((entry) => entry.stateCommitId === commit.id);
    if (matches.length > 1) throw auditIntegrityError({ reason: 'state-commit-audit-duplicate', stateCommitId: commit.id });
    if (matches.length === 1) {
      this.#assertAuditMatchesCommit(matches[0], commit);
      return { ok: true, status: 'already-audited', stateCommitId: commit.id, repaired: false };
    }
    await this.#appendAudit(client, commit.eventType, commit.auditSummary, { stateCommitId: commit.id, at: commit.at });
    return { ok: true, status: 'audit-repaired', stateCommitId: commit.id, repaired: true };
  }

  async #appendAudit(client, type, summary, { stateCommitId = null, at = nowIso() } = {}) {
    const inspection = await this.#inspectAudit(client);
    if (!inspection.ok) throw auditIntegrityError(inspection);
    const seq = inspection.entries + 1;
    const base = { seq, at, type, summary: clone(summary || {}), prevHash: inspection.head };
    if (stateCommitId) base.stateCommitId = stateCommitId;
    const hash = sha256(stableStringify(base));
    await client.query(
      `INSERT INTO ${AUDIT_TABLE} (instance_key, seq, at, type, summary, prev_hash, state_commit_id, hash) VALUES ($1, $2::bigint, $3, $4, $5::jsonb, $6, $7, $8)`,
      [this.instanceKey, String(seq), at, type, JSON.stringify(summary || {}), inspection.head, stateCommitId, hash]
    );
  }

  async #injectFault(stage, commit) {
    if (this.faultInjector) await this.faultInjector(stage, clone(commit));
  }

  #pool() {
    if (!this.pool) throw errorWithCode('PostgreSQL state backend is not initialized', 'POSTGRES_STATE_BACKEND_NOT_INITIALIZED');
    return this.pool;
  }
}
