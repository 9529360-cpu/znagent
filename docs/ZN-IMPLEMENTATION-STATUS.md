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

Current relevant checkpoints:

```text
5c679ea742a2c83578c85c215cf582ce8c22a8cf  reachable recovery-only Work cancellation UI
86895eda3397cf71d7f24b2d7d84d0c73c5e7220  preserve durable outcome across Life observation failure
83ca2179bf1f836469687dac61310b016f482ca8  sanitized completion-observation health primitive
81dc10bff548eaaaa7a3dba95524f10107a5a855  product resident status exposes sanitized observation health
81dc10bff548eaaaa7a3dba95524f10107a5a855  status projection regression coverage
43142de23196b4e5fb3912bc177a8f25b95189e3  focused richer-resident observation ownership coverage
```

Status: **RECOVERY-ONLY CANCELLATION REMAINS REACHABLE END TO END. POST-COMPLETION LIFE OBSERVATION FAILURE CANNOT RECLASSIFY OR REPLAY AN ALREADY-DURABLE EVENT/WORK OUTCOME. COMPLETION-OBSERVATION OWNERSHIP NOW EXISTS IN BOTH LEGITIMATE RESIDENT BIRTH SEQUENCES, AND THE ACTIVE PRODUCT RESIDENT EXPOSES ONLY SANITIZED PENDING-OBSERVATION HEALTH THROUGH ITS `status` RESPONSE; DAEMON/RPC PASSES THAT PROJECTION THROUGH WITHOUT RAW ERROR DETAILS. THE NEW FULL-KERNEL REGRESSION CAUSED BY MISSING `completion_observations` IS FIXED. NERVOUS-SYSTEM OUTCOME PERCEPTION IS STILL SECONDARY AND NOT SAFE FOR BLIND RETRY. BROADER WORK DURABILITY REMAINS PARTIAL.**

## 1. Durable uncertain-effect cancellation remains unchanged

`KernelStore.cancel_uncertain_event()` remains the narrow authority for replay-blocked outside-world uncertainty. The accepted state is still:

```text
stage == side_effect_recovery
blocked_by == outside_world_effect_uncertain
replay_blocked == true
attempt status == started
no durable EventOutcome yet exists
```

The Store transaction publishes `work_abandoned`, terminal event state, `EventOutcome.cancelled = true`, `execution_path = control`, and idle WorkingState. `work_abandoned` is non-epistemic: stopping Work does not prove whether the external effect happened.

The active chain remains:

```text
Store
-> Resident cancellation authority
-> Will / Work reconciliation
-> work_cancel RPC
-> Electron / preload / resident client
-> Workbench recovery-only Stop work
```

There is still no generic arbitrary-action stop control.

## 2. EventOutcome remains the post-completion truth boundary

The authoritative completion order remains:

```text
action result
-> KernelStore.complete_event(...)
-> durable terminal event + EventOutcome
-> secondary resident observation
```

`CompletionObservationJournal` receipts the current `life` observation stage. If Life observation fails, the receipt remains pending while the terminal `EventOutcome` stays authoritative. Restart reconstructs the result from that outcome and retries only Life observation; the completed event/action is not rerun.

`run_once()` also checks for an existing durable outcome before ordinary exception/failure handling, so an exception after terminalization cannot manufacture a second failure interpretation.

This is **at-least-once Life observation repair**, not an exactly-once claim.

## 3. Richer resident birth regression found and fixed

Ordinary CI at earlier head `59af7bd050595682e3c0354d67d73187c6db7829` exposed a real new regression separate from the known Windows path family:

```text
AttributeError: 'FocusedModernTextResidentRuntime' object has no attribute 'completion_observations'
```

The root cause was architectural rather than a missing one-off field. ZN has two legitimate resident birth sequences:

```text
ZNResidentRuntime
-> ZNLifeCore
-> CompletionObservationJournal

EmbodiedResidentRuntime and descendants
-> intentionally skip ZNResidentRuntime.__init__
-> EmbodiedLifeCore from first durable load
```

The richer path deliberately cannot construct a legacy `ZNLifeCore` first and swap it later, because persisted richer `CognitiveSituation` state belongs to `EmbodiedLifeCore`.

The correct owner is therefore the richer birth root, `EmbodiedResidentRuntime`. It now installs `CompletionObservationJournal` only after `EmbodiedLifeCore.wake()`, then repairs pending Life observations from durable `EventOutcome` truth.

This covers direct `EmbodiedResidentRuntime`, `IntentionalResidentRuntime`, and their Transfer/World/Focused descendants. The provider bridge remains assembly-only rather than becoming a hidden lifecycle compatibility layer.

Relevant checkpoints from the repair sequence include:

```text
1058f7c5401db44c156c7a40c41317d327178a5b  initial product-builder repair
9303b257c12f324ed07fc095149e095dc4346b5d  product runtime regression
81dc10bff548eaaaa7a3dba95524f10107a5a855  product status health projection
08891757291954963c974504079137d5ca268a24  direct Embodied/Intentional birth regression
43142de23196b4e5fb3912bc177a8f25b95189e3  focused workflow owns richer birth proof
```

The intermediate builder-specific installation was removed again; the durable ownership lives in the resident birth sequence itself.

## 4. Sanitized observation health is now reachable through product status/RPC

`CompletionObservationJournal.health()` returns only:

```text
healthy
pending_count
waiting_count
running_count
stages
```

It excludes event IDs, `last_error`, raw exception text, paths, and repair payloads.

`FocusedModernTextResidentRuntime.status()` now adds this sanitized projection as:

```text
completion_observations
```

`ResidentRpcServer` already treats resident status as resident-owned data, so the same projection passes through the existing `status` RPC without a second authority or renderer-derived interpretation. Regression coverage creates pending observation failures with deliberate private-looking error text and verifies neither that text nor `last_error` appears in direct product status or RPC output.

The desktop resident snapshot already transports the opaque status object. No new desktop warning, cancellation authority, or permission behavior was added in this slice.

## 5. IntentionalResident nervous/Will audit

`NativeWill` already reconciles durable outcomes on restart through `will.reconcile_outcomes()`. It should continue using durable outcome reconciliation rather than gain another completion authority.

`IntentionalResident._complete_result()` separately feeds completed outcomes into `PersistentNervousSystem.perceive("outcome", ...)` after base completion.

That perception is **not safe for generic at-least-once replay**. One call currently spans several independently committed effects:

```text
neural trace save
-> one or more neural link strength writes
-> affect integration / nervous-system state save
```

A repeated matching perception also intentionally changes lived memory:

```text
repetitions += 1
strength increases
salience / valence / arousal blend again
recent links strengthen again
affect integrates again
```

Therefore a receipt table alone would be insufficient: a crash after only part of the plasticity writes could leave partial perception, while suppressing retry would preserve incomplete state and retrying would falsely reinforce the same lived event.

No exactly-once or safe nervous retry claim is made. The next nervous implementation must introduce an event-identity-safe atomic/deduplicated plasticity boundary, or an equivalent design that cannot duplicate lived reinforcement after crash/restart ambiguity.

## 6. Focused Windows proof

Current focused proof for the repaired resident ownership/status slice:

```text
ZN Work Recovery E2E run 33020344769
head 43142de23196b4e5fb3912bc177a8f25b95189e3
Windows resident Work restart recovery           success
Compile Work recovery path                       success
Verify durable Work progress and restart recovery success
```

The focused suite includes:

```text
test_work_progress
test_work_recovery
test_work_side_effect_recovery
test_work_cancellation
test_work_cancel_control
test_completion_observation_recovery
test_completion_observation_embodied
```

The new direct birth regression completes local events through both `EmbodiedResidentRuntime` and `IntentionalResidentRuntime` and verifies the durable observation receipt and Life outcome state.

## 7. Ordinary CI truth at current code checkpoint

Exact ordinary run for code/workflow head `43142de23196b4e5fb3912bc177a8f25b95189e3`:

```text
ZN CI run 33020344789
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel suite                        585 tests / 16 errors / 5 skipped
```

The earlier broken head had 29 errors and included missing `completion_observations` plus cascading Intentional/Will/transfer failures. At `43142de...` those failures are gone; the affected richer resident and transfer tests execute successfully.

The remaining 16 errors are again the known Windows NetworkService DOS-8.3 versus long-path identity family concentrated in repository targeted-test/text-delta verification and terminal/Work artifact cwd identity, with cleanup `PermissionError` fallout after those assertions fail.

The earlier partial path fix remains normally reverted in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`. No half-fix remains. Ordinary CI is therefore **not green**, and the path family stays **KNOWN / DEFERRED** unless it materially blocks the active product target or is explicitly reprioritized.

## 8. What remains partial

Open work includes:

- event-identity-safe nervous outcome perception across crash/restart ambiguity;
- remove the now-redundant second journal construction in the final FocusedModern layer when a low-risk edit path is available; this is cleanup, not a correctness blocker;
- broader Work durability outside the proven cancellation/Life-observation slices;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance;
- deferred Windows path identity.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback, and destructive self-maintenance changes still require human approval.

## 9. Next real target

Next: **design and implement event-identity-safe nervous outcome perception without duplicating lived reinforcement.**

Required invariant:

```text
EventOutcome remains terminal authority
Life observation repair remains secondary and non-replaying
Will continues durable outcome reconciliation
nervous outcome perception cannot be counted twice for one event
partial plasticity writes cannot be mistaken for complete observation
crash/restart recovery does not replay the completed action
```

Do not weaken cancellation semantics and do not move development to `main`.
