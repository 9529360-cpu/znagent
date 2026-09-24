import { assertStateBackend } from './state-backend-contract.mjs';
import { assertTransactionalStateBackend } from './state-backend-transaction-contract.mjs';

export const STATE_BACKEND_DURABILITY_CONTRACT = 'veteran-state-durability-v1';
export const STATE_COMMIT_AUDIT_OUTCOME_UNKNOWN = 'STATE_COMMIT_AUDIT_OUTCOME_UNKNOWN';

function durabilityContractError(message, details = null) {
  const error = new Error(message);
  error.code = 'STATE_BACKEND_DURABILITY_CONTRACT_INVALID';
  if (details) error.details = details;
  return error;
}

export function assertDurableOutcomeStateBackend(backend) {
  assertTransactionalStateBackend(assertStateBackend(backend));
  if (backend.durabilityContract !== STATE_BACKEND_DURABILITY_CONTRACT) {
    throw durabilityContractError(`State backend must declare ${STATE_BACKEND_DURABILITY_CONTRACT}`, {
      expected: STATE_BACKEND_DURABILITY_CONTRACT,
      actual: backend.durabilityContract || null
    });
  }
  if (typeof backend.reconcilePendingAudit !== 'function') {
    throw durabilityContractError('Durable-outcome state backend is missing required method reconcilePendingAudit()');
  }
  return backend;
}

export function isStateCommitAuditOutcomeUnknown(error) {
  return error?.code === STATE_COMMIT_AUDIT_OUTCOME_UNKNOWN
    && (error?.stateCommitted === true || error?.stateCommitted === 'unknown')
    && error?.auditOutcome === 'unknown'
    && error?.requiresReconciliation === true;
}
