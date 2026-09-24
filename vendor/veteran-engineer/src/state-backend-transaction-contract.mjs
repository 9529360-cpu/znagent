import { assertStateBackend } from './state-backend-contract.mjs';

export const STATE_BACKEND_TRANSACTION_CONTRACT = 'veteran-state-transaction-v1';

function transactionContractError(message, details = null) {
  const error = new Error(message);
  error.code = 'STATE_BACKEND_TRANSACTION_CONTRACT_INVALID';
  if (details) error.details = details;
  return error;
}

export function assertTransactionalStateBackend(backend) {
  assertStateBackend(backend);
  if (backend.transactionContract !== STATE_BACKEND_TRANSACTION_CONTRACT) {
    throw transactionContractError(`State backend must declare ${STATE_BACKEND_TRANSACTION_CONTRACT}`, {
      expected: STATE_BACKEND_TRANSACTION_CONTRACT,
      actual: backend.transactionContract || null
    });
  }
  for (const method of ['readSnapshot', 'compareAndCommit']) {
    if (typeof backend[method] !== 'function') {
      throw transactionContractError(`Transactional state backend is missing required method ${method}()`);
    }
  }
  return backend;
}

export function stateRevisionConflict({ expectedRevision, actualRevision }) {
  const error = new Error('State revision changed before compare-and-commit');
  error.code = 'STATE_REVISION_CONFLICT';
  error.details = { expectedRevision, actualRevision };
  return error;
}
