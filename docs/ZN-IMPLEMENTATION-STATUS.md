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

`main` remains unchanged at `8234a835dea604783cea0bd9d28a40de654ec03d`. Ordinary development remains on `dev/zn-agent`.

Current implementation checkpoints:

```text
5c679ea742a2c83578c85c215cf582ce8c22a8cf  reachable recovery-only Work cancellation UI
86895eda3397cf71d7f24b2d7d84d0c73c5e7220  preserve durable outcome across Life observation failure
6ac3dba5191aa5469bac0093bab15ca3e25b5d95  focused completion-observation recovery CI coverage
83ca2179bf1f836469687dac61310b016f482ca8  sanitized completion-observation health projection primitive
503edf31ce676810117a6e52d945f9d50cbb935d  sanitized health regression coverage
```

Status: **RECOVERY-ONLY CANCELLATION REMAINS REACHABLE END TO END. POST-COMPLETION LIFE OBSERVATION FAILURE NO LONGER RECLASSIFIES OR REPLAYS AN ALREADY-DURABLE EVENT/WORK OUTCOME. A SANITIZED PENDING-OBSERVATION HEALTH SUMMARY NOW EXISTS AND IS TESTED, BUT IT IS NOT YET WIRED INTO RESIDENT `status` / RPC / DESKTOP HEALTH. NERVOUS-SYSTEM OUTCOME PERCEPTION HAS BEEN AUDITED ENOUGH TO SHOW THAT BLIND RETRY IS NOT SAFE: REPEATED `perceive()` CALLS INTENTIONALLY STRENGTHEN/INCREMENT A TRACE. BROADER WORK DURABILITY REMAINS PARTIAL.**

## 1. Durable uncertain-effect cancellation

The established authority remains `KernelStore.cancel_uncertain_event()` for the narrow replay-blocked state:

```text
stage == side_effect_recovery
blocked_by == outside_world_effect_uncertain
replay_blocked == true
attempt status == started
no durable EventOutcome yet exists
```

The transaction records `work_abandoned`, terminal event state, `EventOutcome.cancelled = true`, `execution_path = control`, and idle WorkingState. `work_abandoned` is non-epistemic: stopping Work does not prove whether an outside-world effect happened.

The active control chain remains:

```text
Store
-> Resident cancellation authority
-> Will/Work reconciliation
-> work_cancel RPC
-> Electron/preload/client
-> Workbench recovery-only Stop work
```

There is no generic arbitrary-action stop control.

Focused cancellation proof remains green:

```text
ZN Work Recovery E2E run 33016402296  success
head 0be9340e2db305be7134d403a1ecdf392a7f36b4
```

## 2. Post-completion terminal truth

The completion boundary is now:

```text
action result
-> KernelStore.complete_event(...)
-> durable terminal event + EventOutcome
-> secondary resident observation
```

`EventOutcome` is authoritative. `run_once()` checks for an existing durable outcome before ordinary exception/failure handling, so a later hook exception cannot manufacture a second failure interpretation.

`CompletionObservationJournal` durably receipts the current `life` observation stage. Failed Life observation remains pending and can be retried from the durable `EventOutcome` after restart without rerunning the completed event/action.

This is **at-least-once observation repair**, not an exactly-once claim.

Focused Windows proof:

```text
ZN Work Recovery E2E run 33018036694
head 6ac3dba5191aa5469bac0093bab15ca3e25b5d95
Windows resident Work restart recovery  success
Compile Work recovery path               success
Verify durable Work progress and restart recovery  success
```

The included completion-observation regressions prove durable success survives Life observation failure, restart repairs only observation with event attempts remaining `1`, and arbitrary post-completion exceptions return the existing outcome.

## 3. Sanitized observation health primitive

`CompletionObservationJournal.health()` now returns only bounded control-plane health fields:

```text
healthy
pending_count
waiting_count
running_count
stages
```

It deliberately excludes event IDs, `last_error`, raw exception text, paths, and other internal repair details.

Regression coverage verifies both pending counts and non-disclosure of raw internal error text. Exact Windows proof:

```text
ZN Work Recovery E2E run 33018371392
head 503edf31ce676810117a6e52d945f9d50cbb935d
Compile Work recovery path               success
Verify durable Work progress and restart recovery  success
```

This is currently a **projection primitive only**. It is not yet surfaced through `ZNResidentRuntime.status`, daemon/RPC status, or desktop health.

## 4. IntentionalResident post-completion audit

`NativeWill` already reconciles durable outcomes on restart through `will.reconcile_outcomes()`. Do not create a second competing completion authority for Will.

`IntentionalResident._complete_result()` also writes an `outcome` neural trace through `PersistentNervousSystem.perceive()` after base completion. The nervous-system implementation fingerprints matching perceptions but intentionally treats a repeated perception as new lived reinforcement:

```text
repetitions = prior.repetitions + 1
strength increases
salience/valence/arousal blend again
links/affect are integrated again
```

Therefore a generic retry receipt around nervous `perceive()` would alter resident memory if replayed after an ambiguous commit boundary. It is not safe to copy the Life retry mechanism blindly.

The next nervous design must either make outcome perception durably idempotent by event identity, or define a reconstructible/non-authoritative rule that does not duplicate reinforcement.

## 5. Ordinary CI truth

At code/workflow checkpoint `6ac3dba5191aa5469bac0093bab15ca3e25b5d95`, ordinary `ZN CI` run `33018036687` had:

```text
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       still running at documentation sync
```

The ordinary Windows Kernel suite also has a separate known NetworkService DOS-8.3 versus long-path identity failure family. Prior exact evidence remains:

```text
ZN CI run 33014912300
head 6c655c761099cc6a206028285cc228d65f3e7734
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
573 tests / 16 errors / 5 skipped
```

The partial path fix was reverted normally in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. This issue stays **KNOWN / DEFERRED** unless it materially blocks the active product target.

## 6. What remains partial

Open work includes:

- wire sanitized completion-observation health into resident status/RPC and, if useful, desktop resident health;
- design safe event-identity semantics for nervous outcome perception rather than blind retry;
- broader Work durability outside the proven cancellation/Life-observation slices;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance;
- deferred Windows path identity.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback, and destructive self-maintenance changes still require human approval.

## 7. Next real target

Next: **wire sanitized completion-observation health into the real resident status chain, then make a deliberate event-identity decision for nervous outcome perception.**

Required invariant:

```text
EventOutcome remains terminal authority
status exposes health, not raw repair internals
no completed action is replayed
Will continues durable outcome reconciliation
nervous outcome repair must not duplicate lived reinforcement
```

Do not weaken cancellation semantics and do not move development to `main`.
