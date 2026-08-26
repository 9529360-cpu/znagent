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

Relevant checkpoints:

```text
5c679ea742a2c83578c85c215cf582ce8c22a8cf  recovery-only Work cancellation UI
86895eda3397cf71d7f24b2d7d84d0c73c5e7220  preserve durable outcome across Life observation failure
83ca2179bf1f836469687dac61310b016f482ca8  sanitized completion-observation health primitive
ef4d68b363fb381ac74ca83d6623a024651575a7  product resident status health projection
81dc10bff548eaaaa7a3dba95524f10107a5a855  product status sanitization regressions
d589e3aaf1ad276867926f33a814395630c59bdc  status RPC pass-through regression
08891757291954963c974504079137d5ca268a24  direct Embodied/Intentional observation regression
43142de23196b4e5fb3912bc177a8f25b95189e3  focused richer-resident observation coverage
```

Status: **RECOVERY-ONLY CANCELLATION REMAINS REACHABLE END TO END. POST-COMPLETION LIFE OBSERVATION FAILURE CANNOT RECLASSIFY OR REPLAY AN ALREADY-DURABLE EVENT/WORK OUTCOME. BOTH LEGITIMATE RESIDENT BIRTH SEQUENCES NOW OWN COMPLETION-OBSERVATION REPAIR, AND THE ACTIVE PRODUCT RESIDENT EXPOSES ONLY SANITIZED OBSERVATION HEALTH THROUGH `status`; THE EXISTING RPC STATUS PATH PASSES IT THROUGH WITHOUT RAW REPAIR DETAILS. THE NEW FULL-KERNEL MISSING-`completion_observations` REGRESSION IS FIXED. NERVOUS OUTCOME PERCEPTION IS STILL SECONDARY AND IS NOT SAFE FOR BLIND RETRY. BROADER WORK DURABILITY REMAINS PARTIAL.**

## 1. Durable cancellation and terminal truth

The established uncertain-effect cancellation authority remains `KernelStore.cancel_uncertain_event()` for the narrow replay-blocked recovery state. Cancellation is a lifecycle/control result, not failure learning and not evidence about whether the outside-world effect happened.

The post-completion authority remains:

```text
action result
-> KernelStore.complete_event(...)
-> durable terminal event + EventOutcome
-> secondary resident observation
```

`EventOutcome` is terminal truth. `CompletionObservationJournal` receipts Life observation after that boundary. A failed Life observation remains pending and can be repaired from the durable outcome after restart without rerunning the completed event/action.

This is **at-least-once Life observation repair**, not an exactly-once claim.

## 2. Richer resident birth regression and ownership fix

At earlier head `59af7bd050595682e3c0354d67d73187c6db7829`, ordinary Kernel CI exposed a real new regression separate from the known Windows path family:

```text
AttributeError: 'FocusedModernTextResidentRuntime' object has no attribute 'completion_observations'
```

The root cause was the second legitimate resident birth sequence. `EmbodiedResidentRuntime` intentionally does not call `ZNResidentRuntime.__init__`, because a richer resident must be born directly with `EmbodiedLifeCore`; temporarily constructing legacy `ZNLifeCore` would be wrong for persisted richer state.

The two valid birth paths are now explicit:

```text
ZNResidentRuntime
-> ZNLifeCore.wake()
-> CompletionObservationJournal

EmbodiedResidentRuntime and descendants
-> EmbodiedLifeCore.wake()
-> CompletionObservationJournal
```

`EmbodiedResidentRuntime` now installs the journal after the richer Life wake and repairs pending Life observation from durable `EventOutcome` truth. Direct `EmbodiedResidentRuntime`, `IntentionalResidentRuntime`, and later Transfer/World/Focused descendants therefore inherit the correct organ.

An initial builder-specific repair was removed again; `provider_bridge.py` remains assembly-only rather than becoming a hidden lifecycle compatibility layer.

The `embodied_resident.py` full-file edit was diff-reviewed. An intermediate edit removed explanatory comments/docstrings accidentally; `a395897e79c060e09b9aa2b0e67f206d4b841db8` restored them immediately. Net behavioral change in that file is journal import + initialization/repair after `EmbodiedLifeCore.wake()`.

## 3. Sanitized observation health is reachable through product status/RPC

`CompletionObservationJournal.health()` returns only:

```text
healthy
pending_count
waiting_count
running_count
stages
```

It excludes event IDs, `last_error`, raw exception text, paths, and repair payloads.

`FocusedModernTextResidentRuntime.status()` exposes that projection as `completion_observations`. `ResidentRpcServer` already passes resident-owned status data through, so the same sanitized object is available over the existing `status` RPC without a new daemon or renderer authority.

Regression coverage verifies healthy and pending cases and deliberately injects private-looking observation errors, then confirms neither the error text nor `last_error` appears in direct product status or RPC output.

The desktop resident snapshot already transports status opaquely. No UI warning, permission change, or new cancellation behavior was added in this slice.

## 4. Nervous/Will post-completion audit

`NativeWill` already reconciles durable outcomes on restart through `will.reconcile_outcomes()`. Keep that authority.

`IntentionalResident._complete_result()` also feeds the completed outcome into `PersistentNervousSystem.perceive("outcome", ...)` after base completion.

That perception is not safely replayable. A single call currently commits several effects independently:

```text
neural trace save
-> one or more neural-link writes
-> affect / nervous-state save
```

A repeated matching perception intentionally performs additional plasticity:

```text
repetitions += 1
trace strength increases
salience / valence / arousal blend again
links strengthen again
affect integrates again
```

Therefore a receipt table wrapped around the current call would not provide exactly-once semantics. A crash after partial plasticity could leave incomplete perception; suppressing retry would preserve the partial state, while retrying could falsely reinforce one lived event twice.

No nervous exactly-once claim and no naive retry queue were added.

## 5. Focused Windows proof

Current focused proof:

```text
ZN Work Recovery E2E run 33020344769
head 43142de23196b4e5fb3912bc177a8f25b95189e3
Windows resident Work restart recovery            success
Compile Work recovery path                        success
Verify durable Work progress and restart recovery success
```

The focused suite includes the existing Work progress/restart/side-effect/cancellation modules plus:

```text
test_completion_observation_recovery
test_completion_observation_embodied
```

The new direct richer-birth regression completes local events through both `EmbodiedResidentRuntime` and `IntentionalResidentRuntime` and verifies their durable observation receipt and Life outcome state.

## 6. Ordinary CI truth at the code checkpoint

Exact ordinary run for `43142de23196b4e5fb3912bc177a8f25b95189e3`:

```text
ZN CI run 33020344789
Electron / TypeScript / Windows    success
ZN Source Boundary / Windows       success
ZN Kernel / Python / Windows       failure
Kernel suite                        585 tests / 16 errors / 5 skipped
```

The earlier broken head had 29 errors and included the missing `completion_observations` exception plus cascading Intentional/Will/transfer failures. At `43142de...` those failures are gone and the affected richer resident/transfer tests execute successfully.

The remaining 16 errors are again the known Windows NetworkService DOS-8.3 versus long-path identity family around repository targeted-test/text-delta verification and terminal/Work artifact cwd identity, with cleanup `PermissionError` fallout.

The prior partial path fix remains normally reverted in `db647cb49c3de014aa82bc28ec87c1c4e5b02c15`; no half-fix remains. Ordinary CI is therefore **not green**. This path issue remains **KNOWN / DEFERRED** unless it materially blocks the active product target or is explicitly reprioritized.

## 7. What remains partial

Open work includes:

- event-identity-safe nervous outcome perception across crash/restart ambiguity;
- a non-blocking cleanup: remove the redundant second journal construction in the final FocusedModern layer while retaining its status projection;
- broader Work durability outside the proven cancellation/Life-observation slices;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance;
- deferred Windows path identity.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback, and destructive self-maintenance changes still require human approval.

## 8. Next real target

Next: **design and implement event-identity-safe nervous outcome perception without duplicating lived reinforcement.**

Required invariant:

```text
EventOutcome remains terminal authority
Life observation repair remains secondary and non-replaying
Will continues durable outcome reconciliation
one completed event is not neurally reinforced twice by recovery
partial plasticity writes cannot masquerade as complete perception
restart does not replay the completed action
```

Do not weaken cancellation semantics and do not move development to `main`.
