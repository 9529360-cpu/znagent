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

Recent Work durability checkpoints:

```text
8ebae2c43ba13349aa4aebdf8c84746783096c1b  repair missing Work ingress linkage after restart
b41b65dd35ab652e6ed573e5d512778d7313db47  make side-effect recovery resolution restart-idempotent
cf88774ba8c4c9b95adf2aeef5954da4d55ea14b  block observed append replay after restart
173e0d03fbf52cda68571eb5f22e4aabc3d08805  block observed command replay after restart
2ffb79c4bf11903d46f53dd9a7b8d1fcbd922642  keep verified append recovery replay-safe until terminal EventOutcome
f7d6cb64121e914e0250736c0089d58c4b7fea2b  align regression contract with the terminal EventOutcome boundary
dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d  resume verified Body completion without replay
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. SIX CONCRETE CRASH WINDOWS ARE NOW CLOSED AND VERIFIED, INCLUDING COMMON VERIFIED BODY SUCCESS BEFORE TERMINAL `EventOutcome` PUBLICATION. `EventOutcome` REMAINS TERMINAL TRUTH. CANCELLATION REMAINS LIFECYCLE AUTHORITY, NOT EVIDENCE THAT AN OUTSIDE-WORLD EFFECT DID OR DID NOT OCCUR.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Six proven broader Work crash windows

### 2.1 Missing ingress linkage

The Work start path persists the resident event and `work_runs` linkage separately. `ResidentWorkControl.reconcile_missing_ingress_runs()` repairs only a missing linkage when durable Work thread/message/event evidence agrees. It does not claim, execute, requeue or replay the event.

### 2.2 Recovery decision committed before checkpoint save

`SideEffectAwareBody.resolve_uncertain_attempt()` accepts an exact idempotent acknowledgement of the same already-committed recovery result for the same event/attempt. Conflicting recovery truth still fails closed.

### 2.3 Append `observed` before checkpoint save

A real append can complete and be durably marked `observed` while `WorkingState` still says `native_action`. Append replay admission now treats that matching `observed` attempt as replay-blocking. Restart enters `side_effect_recovery`, re-reads the exact text postcondition and can complete or authorize one retry only from fresh current reality.

### 2.4 Generic command `observed` before checkpoint save

The same durability split exists for commands:

```text
native_action checkpoint
-> side-effect attempt `started`
-> command/process dispatch
-> durable attempt `observed` + result metadata
-> crash before resident advances WorkingState
```

Before `173e0d03...`, command replay admission considered only `started`. Restart could reconstruct stale `native_action` and dispatch the same command again even though its prior dispatch had already returned and been recorded as `observed`.

`SideEffectAwareBody` now treats matching `observed` attempts as replay-blocking for every guarded generic side effect, including `command`, `terminal` and `shell`. Generic commands do not invent a verification contract: they enter `side_effect_recovery` with `user_decision_required` and remain blocked from replay.

`KernelStore.cancel_uncertain_event()` now accepts the recovery-owned attempt when its durable status is either `started` or `observed`. The cancellation transaction still atomically publishes the cancelled `EventOutcome`, terminal event, idle checkpoint and `work_abandoned` attempt state. For an `observed` attempt, existing `completed_at`, `result_action_id` and `result_success` are preserved; cancellation does not reinterpret whether or how the command affected the outside world.

Regression: `test_observed_command_restart_blocks_replay_and_cancellation_preserves_dispatch_metadata` constructs the exact stale-checkpoint state, reconstructs the product resident, proves no replay occurs, enters explicit recovery, cancels the Work, preserves the observed dispatch metadata and remains terminal after a second restart.

### 2.5 Verified append recovery success before terminal outcome

A narrower second split remained after append recovery had already independently re-read the exact requested text and durably resolved the side-effect attempt as `verified_effect`:

```text
durable side_effect_recovery checkpoint (`reverify_effect`)
-> fresh exact read-only text verification succeeds
-> side-effect attempt durably `verified_effect`
-> resident returns successful BODY result
-> crash before `_complete_result()` publishes EventOutcome
```

Before `2ffb79c4...`, the recovery success path persisted `WorkingState.stage = complete` before terminal publication. After restart, `_state_for_event()` intentionally does not resume a durable `complete` checkpoint and would reconstruct the still-nonterminal event from `orient`, separating the resident's durable recovery proof from the event's missing terminal truth.

The append effect-present recovery path now keeps the last replay-safe `side_effect_recovery` checkpoint on disk until `KernelStore.complete_event()` atomically publishes terminal event state, exact `EventOutcome` and idle `WorkingState`. The in-memory step may still return its success result immediately, but it does not persist an intermediate terminal-looking checkpoint.

If the process dies after recovery returns success but before terminal publication, restart recovers the event to pending while preserving `side_effect_recovery`. The resident re-runs the same exact read-only text verification, the already-committed `verified_effect` acknowledgement is idempotent, and no append is dispatched again. Only `_complete_result()` / `complete_event()` creates durable terminal truth.

`test_restart_after_verified_effect_before_checkpoint_save_completes_without_replay` now includes this second crash after the recovery result and before `_complete_result()`, reconstructs the final product resident again, proves another exact re-verification occurs without `write_text` replay, and then verifies terminal Work finalization. `test_interrupted_append_completes_from_verified_effect_without_replay_or_failure_learning` was aligned with the same contract: pre-terminal durable state remains replay-safe recovery, and successful terminal publication ends at `EventOutcome` + idle checkpoint rather than a durable intermediate `complete` marker.

This closes only this concrete append-recovery terminalization window. It does **not** prove that every resident success/failure path is safe from a pre-`EventOutcome` terminal-looking checkpoint.

### 2.6 Common verified Body success before terminal outcome

The common `EmbodiedResidentRuntime._complete_successful_body_action()` path
previously persisted `WorkingState.stage = complete` before outer
`_complete_result()` published the terminal event and `EventOutcome`. After a
crash, `_state_for_event()` intentionally discarded that terminal-looking
checkpoint and restarted the still-nonterminal event from `orient`, allowing
the verified Body path to be reconsidered and potentially replayed.

The common path now persists a nonterminal, resumable `native_completion`
checkpoint containing only the already-established Body result needed for
terminal publication. Ordinary success accounting is recorded before that
checkpoint becomes visible. On restart, the active resident reconstructs the
result from the checkpoint and enters the existing atomic `complete_event()`
boundary without invoking Body or repeating accounting. Missing or malformed
completion data fails closed as an event failure rather than reopening action.

`test_restart_publishes_verified_body_completion_without_body_replay` proves
the final product resident survives the exact crash, performs no Body call,
does not increment runtime task accounting twice, publishes `EventOutcome`,
clears to idle state and finalizes Work progress. Pointer/semantic UI completion
overrides are deliberately outside this common-path slice.

## 3. Real Windows CI proof

Current exact-head proof for `dc3b72ad1dfdc5bb8ac2a6c3898fe5038b85197d`:

```text
ZN Work Recovery E2E run 33076704204  success / 51 tests / OK
ZN CI run 33076704179
Electron / TypeScript / Windows      success
ZN Source Boundary / Windows         success
ZN Kernel / Python / Windows         success / 601 tests / 5 skipped / OK
Publish Windows CI statuses          success
```

Local proof before push matched the exact code checkpoint: focused Work suite
51 tests / OK; adjacent common Body callers 40 tests / OK; full core discovery
601 tests / 5 skipped / OK.

Focused Work proof for the fifth window and its companion contract update:

```text
ZN Work Recovery E2E run 33071963811
head f7d6cb64121e914e0250736c0089d58c4b7fea2b
Windows resident Work restart recovery  success
Ran 50 tests                            OK
```

Ordinary CI proof for the same verification head:

```text
ZN CI run 33071963819
head f7d6cb64121e914e0250736c0089d58c4b7fea2b
Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Kernel                            600 tests / 5 skipped / OK
Publish Windows CI statuses       success
```

Runtime behavior for the fifth window was changed in `2ffb79c4...`. The following `f7d6cb64...` commit corrected an older regression that still required the dangerous durable intermediate `complete` checkpoint; it did not broaden product behavior. The fifth-window regression passed in both the focused Work suite and the full Kernel suite. No local test run is claimed for this web-maintainer slice; repository self-hosted Windows CI is the verification authority.

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these six proven windows;
- semantic UI completion and base resident investigation completion have analogous pre-`EventOutcome` paths that still require separate call-chain proof rather than being inferred safe from the append recovery fix;
- failure-side terminal-looking checkpoint paths remain unproven;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 5. Next real target

Work is paused after the verified sixth-window checkpoint at the user's request.
When resumed, re-read repository/CI truth and select one remaining family, such
as semantic UI completion, base resident investigation completion, or a
failure-side terminal-looking checkpoint. Do not infer those paths safe from
the common Body fix.

Do not generalize any completed slice to all completion paths without proving
what durable evidence each path needs to resume safely. Keep `main` untouched
during ordinary development.
