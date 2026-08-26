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

## Current checkpoint - 2026-08-26

M10 canonical source promotion remains complete. Ordinary development remains on `dev/zn-agent`; `main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`.

Latest core implementation checkpoint before this documentation update:

```text
86895eda3397cf71d7f24b2d7d84d0c73c5e7220
fix: preserve durable outcome across Life observation failure
```

Focused Windows verification checkpoint:

```text
6ac3dba5191aa5469bac0093bab15ca3e25b5d95
ci: verify completion observation recovery
```

Status: **THE RECOVERY-ONLY CANCELLATION PATH FOR UNVERIFIABLE OUTSIDE-WORLD EFFECTS REMAINS REACHABLE END TO END. IN ADDITION, POST-COMPLETION LIFE OBSERVATION FAILURE CAN NO LONGER RECLASSIFY AN ALREADY-DURABLE EVENT/WORK OUTCOME: THE RESIDENT NOW JOURNALS SECONDARY LIFE OBSERVATION, RETRIES PENDING OBSERVATION FROM THE DURABLE OUTCOME ON RESTART, AND DOES NOT REPLAY THE COMPLETED ACTION. THIS IS AT-LEAST-ONCE OBSERVATION REPAIR, NOT AN EXACTLY-ONCE CLAIM. BROADER WORK DURABILITY AND ALL INTENTIONAL-RESIDENT POST-COMPLETION PERCEPTION PATHS REMAIN PARTIAL.**

## 1. Durable uncertain-effect cancellation remains reachable

`KernelStore.cancel_uncertain_event()` remains the narrow authority for replay-blocked outside-world uncertainty. The proven state remains:

```text
stage == side_effect_recovery
blocked_by == outside_world_effect_uncertain
replay_blocked == true
attempt status == started
no durable EventOutcome yet exists
```

Its transaction still performs:

```text
side-effect attempt -> work_abandoned
event -> terminal
EventOutcome.cancelled = true
EventOutcome.execution_path = control
WorkingState -> idle
```

`work_abandoned` is non-epistemic: ZN stops continuing that Work, without asserting whether the external effect happened.

The reachable chain remains:

```text
KernelStore.cancel_uncertain_event
-> Resident explicit cancellation authority
-> IntentionalResident / NativeWill cancelled semantics
-> ResidentWorkControl ownership + finalization/reconciliation
-> ResidentRpcServer work_cancel
-> Electron resident process + IPC
-> preload bridge
-> desktop environment typing
-> resident-client recovery normalization + cancelZnWork
-> Workbench recovery-only Stop work control
```

The Workbench exposes `Stop work` only when resident state reports `replayBlocked === true`; there is no generic arbitrary-action stop control.

Key cancellation checkpoints include:

```text
6c655c761099cc6a206028285cc228d65f3e7734  atomic uncertain Work cancellation
1024752da9741326cf133e27c51358e45b9f6ef2  Will cancelled semantics
01a4a645e68bda87d74697af0fd9aacb9181e96b  Resident cancellation authority
1ad68ddb5f2e423ea02d249553aa404c98266b2d  Resident Work cancellation control
4cf85f33a6c000f31ed839e405bd2bb978e8d83e  work_cancel RPC
55d6922bc0cf51a05939ced26fe4386cd5f4cc48  reachable cancellation regression coverage
0be9340e2db305be7134d403a1ecdf392a7f36b4  focused cancellation workflow coverage
831bba875e77ecddd338bb2b464844171b479e93  Electron resident RPC method typing
5c679ea742a2c83578c85c215cf582ce8c22a8cf  Workbench recovery-only cancellation UI
```

## 2. Post-completion truth boundary is now explicit

The real completion order in `ZNResidentRuntime` is now:

```text
action result
-> KernelStore.complete_event(...)
-> durable terminal event + EventOutcome
-> CompletionObservationJournal.observe_life(...)
-> Life self-observation
```

The terminal `EventOutcome` is authoritative. Life observation occurs afterwards and is secondary resident self-state.

Before this change, `life.observe_action()` could fail after `complete_event()` had already committed. Because `run_once()` had a broad exception handler around `_complete_result()`, that secondary failure could be misclassified as a new execution failure and drive another completion attempt.

The new invariant is:

```text
durable EventOutcome exists
=> later hook failure must return/reconstruct that outcome
=> completed action is not replayed
=> secondary observation may remain pending and repairable
```

`run_once()` now checks `result_for(event_id)` before entering ordinary failure handling. Any exception after the durable outcome exists returns the existing truth instead of creating a second failure interpretation.

## 3. Durable Life observation repair

New resident-owned component:

```text
runtime/python/zn_agent/core/completion_observation.py
CompletionObservationJournal
```

It stores bounded repair state in the resident SQLite body:

```text
resident_completion_observations
(event_id, stage, status, attempts, last_error, updated_at)
```

For the current `life` stage:

- observation begins only after durable event completion;
- a Life observation exception is recorded as pending and does not escape into action failure semantics;
- resident restart scans pending Life observations;
- repair reconstructs `ResidentRunResult` from the existing durable `EventOutcome`;
- repair reruns only `life.observe_action`, never the completed event/action;
- completed receipts suppress ordinary duplicate repair.

This is deliberately **at-least-once observation repair**. If Life state was written but the observation receipt could not be marked complete, a later retry may apply the bounded Life state update again. The current Life operation is designed to tolerate this; there is no exactly-once claim.

Relevant implementation checkpoints:

```text
baf5d5f3fcb9cad3c485d5ae4a05c7d937c5dbe8  durable completion observation journal
86895eda3397cf71d7f24b2d7d84d0c73c5e7220  preserve durable outcome across Life observation failure
f942bc07e4965af7f347c6659207328f92695e41  completion observation recovery regressions
6ac3dba5191aa5469bac0093bab15ca3e25b5d95  focused Windows CI coverage
```

## 4. What is and is not covered

`NativeWill` already has outcome reconciliation and `IntentionalResident` invokes `will.reconcile_outcomes()` during resident reconstruction. The generic durable-outcome guard also protects terminal event truth if another post-completion hook raises.

However, this slice does **not** claim every secondary `IntentionalResident` perception is durably receipted. In particular, nervous-system outcome perception remains secondary associative state and still needs an explicit audit to decide whether it should gain its own durable repair receipt or remain reconstructible/non-authoritative perception.

Therefore:

```text
Life observation recovery          VERIFIED
terminal event truth preservation  VERIFIED
no completed-action replay         VERIFIED
Will outcome restart reconciliation already present
all nervous/post-processing exactly once  NOT CLAIMED
broader Work durability            PARTIAL
```

## 5. Focused Windows proof

Exact current proof for completion observation recovery:

```text
ZN Work Recovery E2E run 33018036694
head 6ac3dba5191aa5469bac0093bab15ca3e25b5d95
Windows resident Work restart recovery  success
Compile Work recovery path               success
Verify durable Work progress and restart recovery  success
```

That focused unittest step includes the existing Work progress/restart/uncertain-side-effect/cancellation suites plus:

```text
tests.zn_agent.core.test_completion_observation_recovery
```

Its three new regressions prove:

```text
Life observation failure preserves the durable success outcome
restart repairs pending Life observation without replaying the event
an exception after completion returns the existing outcome instead of failing again
```

Earlier focused cancellation proofs remain valid:

```text
ZN Work Recovery E2E run 33016402296  success
head 0be9340e2db305be7134d403a1ecdf392a7f36b4

ZN Work Recovery E2E run 33014912312  success
head 6c655c761099cc6a206028285cc228d65f3e7734
```

## 6. Ordinary CI truth at code checkpoint

For code/workflow head `6ac3dba5191aa5469bac0093bab15ca3e25b5d95`:

```text
ZN CI run 33018036687
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       in progress at documentation sync
```

Electron success includes typecheck, independent ZN bundle, desktop ownership/packaged/update/handoff tests, and release/runtime/package verifier tests.

Do not call the whole ordinary CI green while Kernel is unfinished or failing.

## 7. Known ordinary Kernel issue remains separate

The ordinary Windows Kernel suite has an existing NetworkService DOS-8.3 versus long-path identity failure family. A prior exact run remains:

```text
ZN CI run 33014912300
head 6c655c761099cc6a206028285cc228d65f3e7734
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel suite                        573 tests, 16 errors, 5 skipped
```

Those errors are concentrated around repository targeted-test/text-delta verification and terminal/Work-artifact cwd identity, with cleanup `PermissionError` traces as secondary fallout. The earlier partial attempted fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains.

This defect remains **KNOWN / DEFERRED BY CURRENT PRODUCT PRIORITY** unless it materially blocks the active target or is explicitly reprioritized.

## 8. What remains partial

Open concerns include:

- sanitized resident status/health visibility for pending completion-observation repair;
- audit of `IntentionalResident` nervous-system outcome perception after durable completion;
- broader Work durability beyond the proven cancellation and Life-observation slices;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance stages;
- deferred Windows path identity above.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback, and destructive self-maintenance changes continue to require human approval.

## 9. Next real target

Next: **completion-observation health visibility plus IntentionalResident secondary post-processing audit**.

Trace and decide:

```text
pending completion observation receipts
-> sanitized resident status/health signal
-> operator/desktop visibility without leaking raw internal errors

IntentionalResident._complete_result
-> nervous outcome perception
-> NativeWill outcome handling/reconciliation
-> decide which secondary perceptions need durable repair receipts
```

Keep the durable `EventOutcome` as terminal authority. Do not replay completed actions, do not weaken cancellation semantics, and do not move development to `main`.
