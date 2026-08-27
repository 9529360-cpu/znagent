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
```

Status: **BROADER WORK DURABILITY REMAINS PARTIAL. FOUR CONCRETE CRASH WINDOWS ARE NOW CLOSED AND VERIFIED: MISSING WORK INGRESS LINKAGE; COMMITTED RECOVERY DECISION BEFORE THE NEXT `WorkingState` CHECKPOINT; APPEND DISPATCH DURABLY `observed` BEFORE THE NEXT CHECKPOINT; AND GENERIC COMMAND DISPATCH DURABLY `observed` BEFORE THE NEXT CHECKPOINT. `EventOutcome` REMAINS TERMINAL TRUTH. CANCELLATION REMAINS LIFECYCLE AUTHORITY, NOT EVIDENCE THAT AN OUTSIDE-WORLD EFFECT DID OR DID NOT OCCUR.**

## 1. Existing durable foundations

The established durable boundaries remain:

- terminal event + `EventOutcome` + idle `WorkingState` publish atomically;
- Life observation is secondary and repairable without replaying a completed action;
- event-identity-safe nervous outcome perception uses event receipts and keeps receipted traces dereferenceable across pruning;
- Windows canonical path identity remains consistent across investigation, Body/Terminal, Git, Work, verification and procedural learning;
- Work cancellation is atomic and bypasses failure learning because cancellation is a control/lifecycle result.

Generic nervous `perceive()` remains intentionally plastic and is not an exactly-once API.

## 2. Four proven broader Work crash windows

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

## 3. Real Windows CI proof

Focused Work proof:

```text
ZN Work Recovery E2E run 33068588882
head 173e0d03fbf52cda68571eb5f22e4aabc3d08805
Windows resident Work restart recovery  success
Ran 50 tests                            OK
```

Ordinary CI proof:

```text
ZN CI run 33068588844
head 173e0d03fbf52cda68571eb5f22e4aabc3d08805
Electron / TypeScript / Windows   success
ZN Source Boundary / Windows      success
ZN Kernel / Python / Windows      success
Kernel                            600 tests / 5 skipped / OK
Publish Windows CI statuses       success
```

The new observed-command regression passed in both the focused Work suite and the full Kernel suite. No local test run is claimed for this web-maintainer slice; repository self-hosted Windows CI is the verification authority.

## 4. What remains partial

Open work still includes:

- broader Work durability beyond these four proven windows;
- no deliberate outcome-trace rewrite/compactor; any future implementation must atomically retarget receipts before deleting old representation and requires separate review for destructive long-term-memory migration;
- explanatory-comment cleanup in `intentional_resident.py` remains non-behavioral debt;
- Windows continuity M8;
- browser PRESS, broader click/editing/multi-select/page lifecycle;
- authenticated User Browser Bridge control;
- SM1+ self-maintenance.

High-risk identity, long-term memory, credential/permission, updater/signing, rollback and destructive self-maintenance changes still require human approval.

## 5. Next real target

Re-enter the active Work call chain read-only and identify the **next real unproven durability ambiguity** after the four closed windows. Start from durable event/checkpoint/side-effect state and follow active callers through recovery, terminalization, Work progress/finalization and restart. Do not mark broader Work durability complete until a concrete remaining crash window is proven closed by code and tests.

Keep `main` untouched during ordinary development.
