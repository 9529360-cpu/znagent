const REVIEW_ACTION_RULES = Object.freeze({
  activate: Object.freeze({
    fromStatuses: Object.freeze(['candidate']),
    toStatus: 'active',
    reviewStatus: 'approved',
    confirm: true,
    invalidStateMessage: 'Only candidate experience can be activated'
  }),
  reject: Object.freeze({
    fromStatuses: Object.freeze(['candidate']),
    toStatus: 'retired',
    reviewStatus: 'rejected',
    confirm: false,
    invalidStateMessage: 'Only candidate experience can be rejected'
  }),
  reactivate: Object.freeze({
    fromStatuses: Object.freeze(['challenged']),
    toStatus: 'active',
    reviewStatus: 'approved-after-challenge',
    confirm: true,
    invalidStateMessage: 'Only challenged experience can be reactivated'
  }),
  retire: Object.freeze({
    fromStatuses: Object.freeze(['active', 'challenged']),
    toStatus: 'retired',
    reviewStatus: 'retired',
    confirm: false,
    invalidStateMessage: 'Only active or challenged experience can be retired'
  })
});

export const EXPERIENCE_REVIEW_ACTIONS = Object.freeze(Object.keys(REVIEW_ACTION_RULES));

const REVIEW_ACTION_SET = new Set(EXPERIENCE_REVIEW_ACTIONS);

export function isExperienceReviewAction(action) {
  return REVIEW_ACTION_SET.has(action);
}

export function experienceReviewActionsForStatus(status) {
  return Object.freeze(EXPERIENCE_REVIEW_ACTIONS.filter((action) => REVIEW_ACTION_RULES[action].fromStatuses.includes(status)));
}

export function experienceReviewTransition(status, action) {
  const rule = REVIEW_ACTION_RULES[action];
  if (!rule || !rule.fromStatuses.includes(status)) return null;
  return rule;
}

export function experienceReviewInvalidStateMessage(action) {
  return REVIEW_ACTION_RULES[action]?.invalidStateMessage || null;
}
