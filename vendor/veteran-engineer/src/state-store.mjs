import fs from 'node:fs/promises';
import path from 'node:path';
import { DEFAULT_LOCK_STALE_MS, DEFAULT_LOCK_TIMEOUT_MS, STATE_SCHEMA_VERSION } from './constants.mjs';
import { PROCESS_LIFECYCLE_STATE, probeProcess } from './process-lifecycle-authority.mjs';
import { clone, ensureDir, nowIso, pathExists, randomId, sha256, sleep, stableStringify } from './util.mjs';

function emptyState() {
  return {
    schemaVersion: STATE_SCHEMA_VERSION,
    createdAt: nowIso(),
    updatedAt: nowIso(),
    projects: {},
    missions: {},
    tasks: {},
    evidence: {},
    experiences: {},
    requests: {},
    runtime: {
      timeline: [],
      maintenance: {},
      durability: {
        lastStateCommit: null
      }
    }
  };
}

function auditMaterial(entry) {
  const material = {
    seq: entry.seq,
    at: entry.at,
    type: entry.type,
    summary: entry.summary,
    prevHash: entry.prevHash
  };
  if (entry.stateCommitId) material.stateCommitId = entry.stateCommitId;
  return material;
}

function commitAuditOutcomeUnknown(commit, cause) {
  const error = new Error(`State commit ${commit.id} is durable but audit completion is unknown; reconciliation is required`);
  error.code = 'STATE_COMMIT_AUDIT_OUTCOME_UNKNOWN';
  error.stateCommitted = true;
  error.auditOutcome = 'unknown';
  error.requiresReconciliation = true;
  error.details = {
    stateCommitId: commit.id,
    eventType: commit.eventType,
    causeCode: cause?.code || 'ERROR',
    causeMessage: cause?.message || String(cause)
  };
  error.cause = cause;
  return error;
}

function auditIntegrityError(inspection) {
  const error = new Error(`Audit chain is not safe to reconcile: ${inspection.reason || 'invalid audit chain'}`);
  error.code = 'STATE_AUDIT_INTEGRITY_FAILURE';
  error.details = inspection;
  return error;
}

export class StateStore {
  constructor({ root, lockTimeoutMs = DEFAULT_LOCK_TIMEOUT_MS, lockStaleMs = DEFAULT_LOCK_STALE_MS, faultInjector = null } = {}) {
    if (!root) throw new Error('StateStore root is required');
    this.root = path.resolve(root);
    this.statePath = path.join(this.root, 'state.json');
    this.backupPath = path.join(this.root, 'state.json.bak');
    this.lockPath = path.join(this.root, 'state.lock');
    this.auditPath = path.join(this.root, 'audit.jsonl');
    this.artifactsDir = path.join(this.root, 'artifacts');
    this.worktreesDir = path.join(this.root, 'worktrees');
    this.lockTimeoutMs = lockTimeoutMs;
    this.lockStaleMs = lockStaleMs;
    this.faultInjector = typeof faultInjector === 'function' ? faultInjector : null;
  }

  async init() {
    await ensureDir(this.root);
    await ensureDir(this.artifactsDir);
    await ensureDir(this.worktreesDir);
    const release = await this.acquireLock();
    try {
      if (!(await pathExists(this.statePath))) {
        const state = emptyState();
        const commit = this.#attachStateCommit(state, 'state_initialized', { schemaVersion: STATE_SCHEMA_VERSION });
        await this.#writeAtomic(state, { backup: false });
        await this.#finishStateCommitAudit(commit);
      } else {
        const state = await this.read();
        await this.#reconcileStateCommitAudit(state);
        let changed = false;
        for (const request of Object.values(state.requests || {})) {
          if (request.status === 'started') {
            request.status = 'unknown';
            request.reconciledAt = nowIso();
            changed = true;
          }
        }
        if (changed) {
          state.updatedAt = nowIso();
          const summary = { count: Object.values(state.requests || {}).filter((request) => request.status === 'unknown').length };
          const commit = this.#attachStateCommit(state, 'request_outcomes_reconciled_unknown', summary);
          await this.#writeAtomic(state);
          await this.#finishStateCommitAudit(commit);
        }
      }
    } finally {
      await release();
    }
    return this;
  }

  async acquireLock() {
    await ensureDir(this.root);
    const started = Date.now();
    const token = randomId('lock');
    while (true) {
      try {
        const handle = await fs.open(this.lockPath, 'wx', 0o600);
        try {
          await handle.writeFile(JSON.stringify({ pid: process.pid, token, acquiredAt: nowIso() }));
          await handle.sync();
        } finally {
          // Windows may deny other processes even read access while this handle is open.
          // Lock ownership is represented by the atomically-created file and token.
          await handle.close().catch(() => {});
        }
        return async () => {
          try {
            const raw = await fs.readFile(this.lockPath, 'utf8');
            const current = JSON.parse(raw);
            if (current.token === token) await fs.unlink(this.lockPath);
          } catch (error) {
            if (error?.code !== 'ENOENT') throw error;
          }
        };
      } catch (error) {
        if (error?.code !== 'EEXIST') throw error;
        let stale = false;
        try {
          const [stat, raw] = await Promise.all([fs.stat(this.lockPath), fs.readFile(this.lockPath, 'utf8')]);
          const ageMs = Date.now() - stat.mtimeMs;
          try {
            const lock = JSON.parse(raw);
            const ownerProbe = probeProcess(lock.pid);
            stale = ageMs > this.lockStaleMs && ownerProbe.state === PROCESS_LIFECYCLE_STATE.MISSING;
          } catch {
            // A newly created lock can be observed before its JSON payload is fully written.
            // Never delete a young malformed/partial lock; only age can make it reclaimable.
            stale = ageMs > this.lockStaleMs;
          }
        } catch (inspectError) {
          if (inspectError?.code === 'ENOENT') continue;
          throw inspectError;
        }
        if (stale) {
          await fs.unlink(this.lockPath).catch((unlinkError) => {
            if (unlinkError?.code !== 'ENOENT') throw unlinkError;
          });
          continue;
        }
        if (Date.now() - started >= this.lockTimeoutMs) {
          const timeout = new Error(`Timed out waiting for state lock after ${this.lockTimeoutMs}ms`);
          timeout.code = 'STATE_LOCK_TIMEOUT';
          throw timeout;
        }
        await sleep(25);
      }
    }
  }

  async read() {
    await ensureDir(this.root);
    try {
      const parsed = JSON.parse(await fs.readFile(this.statePath, 'utf8'));
      if (parsed.schemaVersion !== STATE_SCHEMA_VERSION) {
        const error = new Error(`Unsupported state schema: ${parsed.schemaVersion}`);
        error.code = 'STATE_SCHEMA_UNSUPPORTED';
        throw error;
      }
      return parsed;
    } catch (error) {
      if (error?.code === 'STATE_SCHEMA_UNSUPPORTED') throw error;
      if (!(await pathExists(this.backupPath))) throw error;
      const recovered = JSON.parse(await fs.readFile(this.backupPath, 'utf8'));
      if (recovered.schemaVersion !== STATE_SCHEMA_VERSION) throw error;
      await this.#writeAtomic(recovered, { backup: false });
      await this.#appendAudit('state_recovered_from_backup', { reason: error.message });
      return recovered;
    }
  }

  async transaction(eventType, mutator, auditSummary = {}) {
    const release = await this.acquireLock();
    try {
      const state = await this.read();
      await this.#reconcileStateCommitAudit(state);
      const working = clone(state);
      const result = await mutator(working);
      working.updatedAt = nowIso();
      const commit = this.#attachStateCommit(working, eventType, auditSummary);
      await this.#writeAtomic(working);
      await this.#finishStateCommitAudit(commit);
      return result;
    } finally {
      await release();
    }
  }

  async reconcilePendingAudit() {
    const release = await this.acquireLock();
    try {
      const state = await this.read();
      return await this.#reconcileStateCommitAudit(state);
    } finally {
      await release();
    }
  }

  async recordTimeline(event) {
    return this.transaction('runtime_timeline', (state) => {
      state.runtime.timeline.push({ ...event, at: event.at || nowIso() });
      if (state.runtime.timeline.length > 2000) state.runtime.timeline.splice(0, state.runtime.timeline.length - 2000);
    }, { type: event.type, missionId: event.missionId, taskId: event.taskId });
  }

  async verifyAudit() {
    const inspection = await this.#inspectAudit();
    if (!inspection.ok) return inspection;
    if (await pathExists(this.statePath)) {
      try {
        const state = JSON.parse(await fs.readFile(this.statePath, 'utf8'));
        const commit = state.runtime?.durability?.lastStateCommit;
        if (commit) {
          const matches = inspection.items.filter((entry) => entry.stateCommitId === commit.id);
          if (matches.length === 0) {
            return { ok: false, entries: inspection.entries, head: inspection.head, reason: 'state-commit-audit-missing', stateCommitId: commit.id };
          }
          if (matches.length > 1) {
            return { ok: false, entries: inspection.entries, head: inspection.head, reason: 'state-commit-audit-duplicate', stateCommitId: commit.id };
          }
          const entry = matches[0];
          if (entry.type !== commit.eventType || entry.at !== commit.at || stableStringify(entry.summary) !== stableStringify(commit.auditSummary)) {
            return { ok: false, entries: inspection.entries, head: inspection.head, reason: 'state-commit-audit-mismatch', stateCommitId: commit.id };
          }
        }
      } catch (error) {
        return { ok: false, entries: inspection.entries, head: inspection.head, reason: 'state-unreadable-for-audit-verification', message: error.message };
      }
    }
    return { ok: true, entries: inspection.entries, head: inspection.head };
  }

  async #inspectAudit() {
    if (!(await pathExists(this.auditPath))) return { ok: true, entries: 0, head: null, items: [] };
    const raw = await fs.readFile(this.auditPath, 'utf8');
    const lines = raw.split('\n').filter(Boolean);
    const items = [];
    let prevHash = null;
    let seq = 0;
    for (const line of lines) {
      let entry;
      try {
        entry = JSON.parse(line);
      } catch (error) {
        return { ok: false, entries: seq, head: prevHash, reason: 'invalid-json', message: error.message };
      }
      seq += 1;
      if (entry.seq !== seq || entry.prevHash !== prevHash) {
        return { ok: false, entries: seq - 1, head: prevHash, reason: 'chain-link-mismatch', entry };
      }
      const expected = sha256(stableStringify(auditMaterial(entry)));
      if (entry.hash !== expected) return { ok: false, entries: seq - 1, head: prevHash, reason: 'hash-mismatch', entry };
      prevHash = entry.hash;
      items.push(entry);
    }
    return { ok: true, entries: items.length, head: prevHash, items };
  }

  #attachStateCommit(state, eventType, auditSummary) {
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

  async #finishStateCommitAudit(commit) {
    try {
      await this.#injectFault('after_state_commit_before_audit', commit);
      await this.#appendAudit(commit.eventType, commit.auditSummary, { stateCommitId: commit.id, at: commit.at });
      await this.#injectFault('after_audit_append_before_ack', commit);
    } catch (cause) {
      throw commitAuditOutcomeUnknown(commit, cause);
    }
  }

  async #reconcileStateCommitAudit(state) {
    const commit = state.runtime?.durability?.lastStateCommit;
    if (!commit) return { ok: true, status: 'no-state-commit-marker', stateCommitId: null };
    const inspection = await this.#inspectAudit();
    if (!inspection.ok) throw auditIntegrityError(inspection);
    const matches = inspection.items.filter((entry) => entry.stateCommitId === commit.id);
    if (matches.length > 1) {
      throw auditIntegrityError({ ok: false, reason: 'state-commit-audit-duplicate', stateCommitId: commit.id, entries: inspection.entries, head: inspection.head });
    }
    if (matches.length === 1) {
      const entry = matches[0];
      if (entry.type !== commit.eventType || entry.at !== commit.at || stableStringify(entry.summary) !== stableStringify(commit.auditSummary)) {
        throw auditIntegrityError({ ok: false, reason: 'state-commit-audit-mismatch', stateCommitId: commit.id, entry });
      }
      return { ok: true, status: 'already-audited', stateCommitId: commit.id, repaired: false };
    }
    await this.#appendAudit(commit.eventType, commit.auditSummary, { stateCommitId: commit.id, at: commit.at });
    return { ok: true, status: 'audit-repaired', stateCommitId: commit.id, repaired: true };
  }

  async #injectFault(stage, commit) {
    if (!this.faultInjector) return;
    await this.faultInjector(stage, clone(commit));
  }

  async #writeAtomic(state, { backup = true } = {}) {
    await ensureDir(this.root);
    const tempPath = `${this.statePath}.${process.pid}.${Date.now()}.tmp`;
    const serialized = `${JSON.stringify(state, null, 2)}\n`;
    const handle = await fs.open(tempPath, 'w', 0o600);
    try {
      await handle.writeFile(serialized);
      await handle.sync();
    } finally {
      await handle.close();
    }
    if (backup && (await pathExists(this.statePath))) {
      await fs.copyFile(this.statePath, this.backupPath);
    }
    await fs.rename(tempPath, this.statePath);
    try {
      const dir = await fs.open(this.root, 'r');
      await dir.sync();
      await dir.close();
    } catch {
      // Directory fsync is not uniformly supported; state file fsync remains authoritative.
    }
  }

  async #appendAudit(type, summary, { stateCommitId = null, at = nowIso() } = {}) {
    await ensureDir(this.root);
    const inspection = await this.#inspectAudit();
    if (!inspection.ok) throw auditIntegrityError(inspection);
    const base = {
      seq: inspection.entries + 1,
      at,
      type,
      summary,
      prevHash: inspection.head
    };
    if (stateCommitId) base.stateCommitId = stateCommitId;
    const entry = { ...base, hash: sha256(stableStringify(base)) };
    const handle = await fs.open(this.auditPath, 'a', 0o600);
    try {
      await handle.writeFile(`${JSON.stringify(entry)}\n`);
      await handle.sync();
    } finally {
      await handle.close();
    }
  }
}

export { emptyState };
