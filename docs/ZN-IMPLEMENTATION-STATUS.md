# ZN implementation status

> Architecture contract: [`../ZN.md`](../ZN.md)
>
> Product capability ledger: [`ZN-PRODUCT-CAPABILITY-MAP.md`](ZN-PRODUCT-CAPABILITY-MAP.md)
>
> Source adoption boundary: [`ZN-SOURCE-EXTRACTION.md`](ZN-SOURCE-EXTRACTION.md)
>
> Self-maintenance contract: [`ZN-SELF-MAINTENANCE.md`](ZN-SELF-MAINTENANCE.md)
>
> Real code, Git state and CI outrank this ledger.

Development branch: `dev/zn-agent`. Canonical source/release branch: `main`.

## Current checkpoint - 2026-08-27

`main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`. Ordinary development remains on `dev/zn-agent`.

Current verified implementation/test/CI checkpoint before documentation synchronization:

```text
20655834570a31dd4f59abcbc3502aab9e1d81f4  test: avoid slot-unsafe budget mocking
4f16cebfa867edbf50ed1094c410d3e15e3f90c7  ci: cover terminal failure restart recovery
c67d477397dbe02f12fb562aa7aece9ff941500a  test: prove terminal failure restart recovery
076a611994d85aa76fcaf895142eb46acf93a4e4  fix: make terminal failure completion restart safe
7fdeddc68c3828504931af24149092ddf824783f  feat: journal terminal failure task accounting
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. THIRTEEN CONCRETE CRASH WINDOWS ARE CLOSED AND VERIFIED. `EventOutcome` REMAINS TERMINAL TRUTH. CANCELLATION REMAINS LIFECYCLE AUTHORITY, NOT EVIDENCE THAT AN OUTSIDE-WORLD EFFECT DID OR DID NOT OCCUR.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + exact `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result;
- effect-capable resident work persists a durable ownership boundary before dispatch and treats unresolved restart state as uncertainty rather than invented success/failure truth.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Thirteen proven broader Work crash windows

The first eleven verified windows remain:

1. missing Work ingress linkage after durable resident event creation;
2. recovery decision committed before the next `WorkingState` save;
3. append dispatch durably `observed` before checkpoint save;
4. generic guarded side-effect dispatch durably `observed` before checkpoint save;
5. verified append recovery success before terminal `EventOutcome`;
6. common verified Body success resumes from `native_completion` without Body replay;
7. base resident investigation success resumes from `investigation_completion` without native reprobe;
8. verified semantic/focused/UI completion resumes from `native_completion` without resensing or input replay;
9. already-established base resident MEMORY/CAPABILITY success resumes from `resident_completion` without re-recall/re-execution;
10. compiled capability execution persists durable `started`/`observed` ownership, blocks blind replay by default, and uses event-idempotent successful capability accounting;
11. durable observed compiled-capability failure resumes into native investigation without capability replay or duplicate failure evidence, while malformed observed truth fails closed.

The detailed tenth- and eleventh-window contracts remain implemented in `capabilities.py`, `capability_recovery_resident.py`, `resident_accounting.py`, `test_resident_native_completion_recovery.py`, and `test_capability_failure_recovery.py`.

### 2.12 Terminal budget-blocked failure before `EventOutcome`

The active base resident previously reached a known terminal no-model failure through:

```text
native_deliberation
-> Life impasse unresolved
-> runtime_metrics.tasks_total++
-> WorkingState failed
-> return BUDGET_BLOCKED result
-> KernelStore.complete_event()
```

A crash after ordinary task accounting but before durable terminal publication could re-enter deliberation, increment the impasse attempt again, and count the same terminal task twice.

The base owner now persists terminal failure truth before terminal accounting:

```text
known terminal no-model failure
-> persist WorkingState stage=terminal_failure + exact failure payload
-> ResidentAccountingJournal.record_terminal_failure(event_id)
-> reconstruct BUDGET_BLOCKED result from durable checkpoint
-> KernelStore.complete_event()
```

`record_terminal_failure()` is gated by `(event_id, terminal_failure)` and atomically increments runtime task metrics only on the first insert. It deliberately does not add native ability or knowledge evidence; this preserves the existing semantics rather than inventing failure learning.

Restart semantics are explicit:

- crash after the `terminal_failure` checkpoint but before accounting resumes the same checkpoint and performs accounting once;
- crash after accounting but before `EventOutcome` resumes the same checkpoint without duplicate task count;
- restart does not repeat native deliberation or add another impasse attempt;
- the durable failure validator currently accepts only zero-model `BUDGET_BLOCKED` terminal failure. External cognition is not silently folded into this contract.

### 2.13 Outer `run_once()` deterministic exception before `EventOutcome`

The outer resident exception path had the same accounting-before-publication problem. It now uses the same durable terminal-failure checkpoint and event-idempotent task accounting before terminal publication.

The exception boundary also now preserves stronger durable truth instead of overwriting it:

- if an `EventOutcome` already exists, it remains authoritative and is returned;
- if a success/completion checkpoint is already durable and `complete_event()` itself throws before publication, the exception is propagated and the success checkpoint remains intact for retry; it is not reclassified as failure;
- if the current event is in `side_effect_recovery` or has `blocked_by=outside_world_effect_uncertain`, the exception is propagated without inventing known failure evidence, task completion, or an `EventOutcome`;
- already-durable terminal/completion stages remain owned by their stage-specific recovery path rather than by the generic exception fallback.

Focused regressions in `test_terminal_failure_recovery.py` prove five boundaries:

```text
test_budget_failure_accounting_survives_crash_before_outcome
test_budget_failure_checkpoint_survives_crash_before_accounting
test_outer_exception_failure_survives_restart_without_duplicate_accounting
test_publish_exception_preserves_durable_success_checkpoint
test_outer_exception_does_not_reclassify_outside_world_uncertainty
```

This closes the tested terminal no-model failure and deterministic outer-exception publication intervals. It does **not** claim that external cognition success/failure completion is durable, nor that structured-memory/investigation pre-checkpoint accounting is already idempotent.

## 3. Real Windows CI proof

Exact implementation/test/CI head `20655834570a31dd4f59abcbc3502aab9e1d81f4`:

```text
ZN Work Recovery E2E run 33108134821                success
Windows resident Work restart recovery               success
Compile Work recovery path                           success
Verify durable Work progress and restart recovery    success
  focused recovery suite                             66 tests / success

ZN CI run 33108134767                                success
ZN Kernel / Python / Windows                         success
  Boot isolated ZN distribution without a model      success
  Compile resident core                              success
  Run ZN core tests against working tree             success
ZN Source Boundary / Windows                         success
Electron / TypeScript / Windows                      success
```

The first focused attempt on superseded head `4f16cebfa867edbf50ed1094c410d3e15e3f90c7` failed only because two tests tried to patch the read-only slotted `CognitiveBudgetManager.decide` instance method. Code compiled and the other focused tests passed. Commit `20655834570a31dd4f59abcbc3502aab9e1d81f4` removed that slot-unsafe test instrumentation and the authoritative rerun passed.

No local repository test run is claimed for this web-maintainer slice. Repository self-hosted Windows CI is the verification authority.

Previous eleventh-window implementation head `79f7b07dec8e86576f7df66c588ca3b55b278922` passed `ZN Work Recovery E2E` run `33103741459` and `ZN CI` run `33103741461`.

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these thirteen proven windows;
- structured-memory success still performs self-model/runtime accounting before its `resident_completion` checkpoint; restart after an already-durable completion is proven, but the earlier accounting interval is not;
- base native-investigation success likewise performs self-model/runtime accounting before its `investigation_completion` checkpoint; the later restart interval is proven, the earlier interval is not;
- external cognition success/failure completion and learning/accounting boundaries still require direct crash/restart proof rather than analogy;
- the shared `resident_side_effect_attempts` truth is used by Body and compiled capability recovery, but low-level helper implementation is not yet fully consolidated; do not treat helper duplication as a second truth model;
- direct synchronous driving while a Work item is in unresolved `side_effect_recovery` still deserves separate lifecycle review; unresolved external truth must not be converted to automatic replay or failure merely to make synchronous callers terminate;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 5. Next real target

Run the bounded backward durability audit using the patterns now proven by the thirteen crash windows. Start with the nearest still-open accounting-before-checkpoint intervals:

1. structured-memory success: self-model/runtime accounting -> `resident_completion`;
2. base native-investigation success: self-model/runtime accounting -> `investigation_completion`;
3. external cognition success/failure: model execution/result, task accounting, learning, WorkingState and terminal `EventOutcome`.

For each path, trace entry -> owner -> durable state -> lifecycle -> dependencies -> tests -> active caller, and add direct crash/restart proof instead of assuming similarity. Preserve `outside_world_effect_uncertain` as uncertainty rather than success/failure evidence.

Keep `main` untouched during ordinary development.
