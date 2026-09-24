function nonempty(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

function criterionContext(criterion) {
  return {
    requirementId: criterion.id,
    requirement: criterion.statement,
    acceptance: criterion.acceptance
  };
}

export function evaluateRequirementReview(criteria, rawResults) {
  if (!criteria.length) return { passed: true, results: [], findings: [] };
  const findings = [];
  const rows = Array.isArray(rawResults) ? rawResults : [];
  if (!Array.isArray(rawResults)) {
    findings.push({ severity: 'high', code: 'ACCEPTANCE_RESULTS_REQUIRED', message: 'Semantic reviewer must return requirementResults for structured Mission acceptance criteria.' });
  }
  const byId = new Map();
  for (const row of rows) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) continue;
    const id = String(row.id || '').trim();
    if (!id) continue;
    if (byId.has(id)) {
      findings.push({ severity: 'high', code: 'ACCEPTANCE_RESULT_DUPLICATE', requirementId: id, message: `Duplicate semantic-review result for ${id}.` });
      continue;
    }
    byId.set(id, row);
  }
  const known = new Set(criteria.map((criterion) => criterion.id));
  for (const id of byId.keys()) {
    if (!known.has(id)) findings.push({ severity: 'high', code: 'ACCEPTANCE_RESULT_UNKNOWN', requirementId: id, message: `Semantic reviewer returned unknown requirement ${id}.` });
  }
  const normalized = [];
  for (const criterion of criteria) {
    const row = byId.get(criterion.id);
    const context = criterionContext(criterion);
    if (!row) {
      findings.push({ severity: 'high', code: 'ACCEPTANCE_REQUIREMENT_UNREVIEWED', ...context, message: `No semantic-review result for ${criterion.id}: ${criterion.statement}` });
      normalized.push({ id: criterion.id, status: 'unproven', evidence: [] });
      continue;
    }
    const status = String(row.status || '').trim();
    const evidence = Array.isArray(row.evidence) ? row.evidence.filter(nonempty).map((value) => value.trim()) : [];
    if (!['passed', 'failed', 'unproven'].includes(status)) {
      findings.push({ severity: 'high', code: 'ACCEPTANCE_RESULT_STATUS_INVALID', ...context, message: `Invalid acceptance result status for ${criterion.id}: ${status || 'missing'}. Requirement: ${criterion.statement}` });
    }
    if (status !== 'passed') {
      findings.push({ severity: 'high', code: 'ACCEPTANCE_REQUIREMENT_NOT_PROVEN', ...context, message: `Acceptance criterion ${criterion.id} is ${status || 'unproven'}: ${criterion.statement}` });
    }
    if (status === 'passed' && evidence.length === 0) {
      findings.push({ severity: 'high', code: 'ACCEPTANCE_EVIDENCE_REQUIRED', ...context, message: `Passed acceptance criterion ${criterion.id} requires concrete evidence: ${criterion.statement}` });
    }
    normalized.push({ id: criterion.id, status: ['passed', 'failed', 'unproven'].includes(status) ? status : 'unproven', evidence });
  }
  return {
    passed: findings.length === 0 && normalized.every((row) => row.status === 'passed' && row.evidence.length > 0),
    results: normalized,
    findings
  };
}
