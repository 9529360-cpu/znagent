import { StateStore } from './state-store.mjs';
import { STATE_BACKEND_CONTRACT } from './state-backend-contract.mjs';
import { STATE_BACKEND_TRANSACTION_CONTRACT, stateRevisionConflict } from './state-backend-transaction-contract.mjs';
import { STATE_BACKEND_DURABILITY_CONTRACT } from './state-backend-durability-contract.mjs';
import { sha256, stableStringify } from './util.mjs';

function revisionFor(state) {
  return sha256(stableStringify(state));
}

export class LocalJsonStateBackend extends StateStore {
  constructor(options = {}) {
    super(options);
    this.backendContract = STATE_BACKEND_CONTRACT;
    this.backendKind = 'local-json';
    this.transactionContract = STATE_BACKEND_TRANSACTION_CONTRACT;
    this.durabilityContract = STATE_BACKEND_DURABILITY_CONTRACT;
  }

  async readSnapshot() {
    const state = await this.read();
    return { state, revision: revisionFor(state) };
  }

  async compareAndCommit(expectedRevision, eventType, mutator, auditSummary = {}) {
    if (typeof expectedRevision !== 'string' || !expectedRevision) {
      const error = new Error('compareAndCommit requires a non-empty expected revision');
      error.code = 'STATE_REVISION_REQUIRED';
      throw error;
    }
    return this.transaction(eventType, async (state) => {
      const actualRevision = revisionFor(state);
      if (actualRevision !== expectedRevision) {
        throw stateRevisionConflict({ expectedRevision, actualRevision });
      }
      return mutator(state);
    }, auditSummary);
  }
}
