import {
  experienceReviewInvalidStateMessage,
  experienceReviewTransition,
  isExperienceReviewAction
} from './experience-lifecycle.mjs';
import { nowIso, randomId, stableStringify } from './util.mjs';

const ACTIVE = new Set(['active']);

export class ExperienceService {
  constructor({ store }) {
    this.store = store;
  }

  async commit(input) {
    const required = ['projectId', 'mechanism', 'statement', 'kind'];
    for (const key of required) if (!String(input[key] || '').trim()) throw new Error(`${key} is required`);
    const evidenceIds = [...new Set((input.evidenceIds || []).map(String))].sort();
    const canonical = stableStringify({
      projectId: input.projectId,
      mechanism: input.mechanism,
      statement: input.statement,
      kind: input.kind,
      equivalenceClass: input.equivalenceClass || null,
      appliesWhen: input.appliesWhen || null,
      doesNotApplyWhen: input.doesNotApplyWhen || null,
      evidenceIds
    });
    return this.store.transaction('experience_candidate_committed', (state) => {
      const duplicate = Object.values(state.experiences).find((item) => item.status === 'candidate' && item.canonical === canonical);
      if (duplicate) return { ...duplicate, compacted: true };
      const id = randomId('experience');
      const record = {
        id,
        projectId: input.projectId,
        scopeType: input.scopeType || 'project',
        scopeId: input.scopeId || input.projectId,
        mechanism: input.mechanism,
        statement: input.statement,
        kind: input.kind,
        equivalenceClass: input.equivalenceClass || null,
        evidenceIds,
        sourceIdentity: input.sourceIdentity || null,
        appliesWhen: input.appliesWhen || null,
        doesNotApplyWhen: input.doesNotApplyWhen || null,
        expiresAt: input.expiresAt || null,
        status: 'candidate',
        reviewStatus: 'pending',
        supersedes: input.supersedes || [],
        supersededBy: [],
        challenges: [],
        usage: { count: 0, lastUsedAt: null },
        canonical,
        createdAt: nowIso(),
        lastConfirmedAt: null,
        updatedAt: nowIso()
      };
      state.experiences[id] = record;
      return record;
    }, { projectId: input.projectId, mechanism: input.mechanism });
  }

  async review({ experienceId, action, reviewer = 'operator', evidenceIds = [] }) {
    if (!isExperienceReviewAction(action)) throw new Error(`Unknown experience review action: ${action}`);
    return this.store.transaction('experience_reviewed', (state) => {
      const item = state.experiences[experienceId];
      if (!item) throw Object.assign(new Error(`Unknown experience: ${experienceId}`), { code: 'EXPERIENCE_NOT_FOUND' });
      const transition = experienceReviewTransition(item.status, action);
      if (!transition) {
        throw Object.assign(new Error(experienceReviewInvalidStateMessage(action)), { code: 'EXPERIENCE_STATE_INVALID' });
      }
      item.status = transition.toStatus;
      item.reviewStatus = transition.reviewStatus;
      if (transition.confirm) item.lastConfirmedAt = nowIso();
      item.review = { reviewer, evidenceIds: [...new Set(evidenceIds)], at: nowIso(), action };
      item.updatedAt = nowIso();
      return item;
    }, { experienceId, action });
  }

  async challenge({ experienceId, statement, evidenceIds = [] }) {
    if (!String(statement || '').trim()) throw new Error('challenge statement is required');
    return this.store.transaction('experience_challenged', (state) => {
      const item = state.experiences[experienceId];
      if (!item) throw Object.assign(new Error(`Unknown experience: ${experienceId}`), { code: 'EXPERIENCE_NOT_FOUND' });
      if (item.status !== 'active') throw Object.assign(new Error('Only active experience can be challenged'), { code: 'EXPERIENCE_STATE_INVALID' });
      item.status = 'challenged';
      item.challenges.push({ statement, evidenceIds: [...new Set(evidenceIds)], at: nowIso() });
      item.updatedAt = nowIso();
      return item;
    }, { experienceId });
  }

  async query({ projectId, mechanism, sourceHead, limit = 8 }, { recordUsage = false } = {}) {
    const state = await this.store.read();
    const now = Date.now();
    const candidates = Object.values(state.experiences)
      .filter((item) => item.projectId === projectId && ACTIVE.has(item.status))
      .filter((item) => !mechanism || item.mechanism === mechanism)
      .map((item) => ({
        ...item,
        freshness: item.expiresAt && Date.parse(item.expiresAt) <= now ? 'stale' : (item.sourceIdentity?.head && sourceHead && item.sourceIdentity.head !== sourceHead ? 'stale-source' : 'fresh')
      }));
    const conflictKeys = new Map();
    for (const item of candidates) {
      if (!item.equivalenceClass) continue;
      const key = `${item.mechanism}::${item.equivalenceClass}`;
      if (!conflictKeys.has(key)) conflictKeys.set(key, new Set());
      conflictKeys.get(key).add(item.statement);
    }
    const nonConflicting = candidates.filter((item) => {
      if (!item.equivalenceClass) return true;
      return conflictKeys.get(`${item.mechanism}::${item.equivalenceClass}`).size === 1;
    });
    const usable = nonConflicting.slice(0, Math.max(0, Math.min(limit, 50)));
    if (recordUsage && usable.length) {
      await this.store.transaction('experience_used', (working) => {
        for (const item of usable) {
          const target = working.experiences[item.id];
          target.usage.count += 1;
          target.usage.lastUsedAt = nowIso();
        }
      }, { projectId, mechanism, experienceIds: usable.map((item) => item.id) });
    }
    return {
      items: usable,
      excludedConflicts: candidates.length - nonConflicting.length,
      note: 'Candidate, challenged, rejected, and retired experiences never influence execution.'
    };
  }

  async route({ projectId, sourceHead, role = 'general', limit = 8 }) {
    const result = await this.query({ projectId, sourceHead, limit }, { recordUsage: true });
    return {
      role,
      items: result.items.map((item) => ({
        id: item.id,
        mechanism: item.mechanism,
        statement: item.statement,
        kind: item.kind,
        equivalenceClass: item.equivalenceClass || null,
        evidenceIds: item.evidenceIds || [],
        appliesWhen: item.appliesWhen || null,
        doesNotApplyWhen: item.doesNotApplyWhen || null,
        freshness: item.freshness
      })),
      excludedConflicts: result.excludedConflicts,
      precedence: 'Current repository/runtime evidence outranks project experience.',
      note: result.note
    };
  }

  async audit({ projectId, sourceHead }) {
    const state = await this.store.read();
    const items = Object.values(state.experiences).filter((item) => !projectId || item.projectId === projectId);
    const now = Date.now();
    return items.map((item) => ({
      id: item.id,
      projectId: item.projectId,
      status: item.status,
      mechanism: item.mechanism,
      evidenceMissing: item.evidenceIds.filter((id) => !state.evidence[id]),
      freshness: item.expiresAt && Date.parse(item.expiresAt) <= now ? 'stale' : (item.sourceIdentity?.head && sourceHead && item.sourceIdentity.head !== sourceHead ? 'stale-source' : 'fresh'),
      usage: item.usage
    }));
  }

  async compact({ projectId }) {
    return this.store.transaction('experience_candidates_compacted', (state) => {
      const seen = new Map();
      const removed = [];
      for (const item of Object.values(state.experiences).filter((entry) => entry.projectId === projectId && entry.status === 'candidate').sort((a, b) => a.createdAt.localeCompare(b.createdAt))) {
        if (!seen.has(item.canonical)) {
          seen.set(item.canonical, item.id);
          continue;
        }
        delete state.experiences[item.id];
        removed.push(item.id);
      }
      return { removed, kept: [...seen.values()] };
    }, { projectId });
  }
}
